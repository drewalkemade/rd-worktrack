"""
travel_parser.py — Parser for the weekly Centerline travel hours PDF.

PDF format: one table with columns:
  Name | Company | Sunday | Monday | Tuesday | Wednesday | Thursday | Friday | Saturday | Total Travel Hrs

Business rules encoded here:
  1. Only rows where Company = "R&D" are relevant.
  2. The PDF date range is Sun–Sat.  Sunday belongs to the PRIOR Mon–Sun business week.
  3. Mon–Sat hours belong to the current Mon–Sun business week.
  4. The "Total" column in the PDF is the full Sun–Sat total and is used only for
     cross-check, not for storage (we store per-day columns separately).
  5. Employee names in the travel PDF may differ from the payroll PDF; they
     are resolved via the employee_aliases table.  Unresolvable names are
     returned as warnings, never silently discarded.

Data returned for each R&D employee row:
  {
    "raw_name":       str,    # name as it appears in the PDF
    "company":        str,    # company column value (e.g. "R&D")
    "sun_hours":      float,
    "mon_hours":      float,
    "tue_hours":      float,
    "wed_hours":      float,
    "thu_hours":      float,
    "fri_hours":      float,
    "sat_hours":      float,
    "pdf_total":      float,  # total from the PDF (cross-check only)
    "current_week_total": float,   # Mon–Sat (belongs to week in this PDF)
    "prior_sun_hours":    float,   # Sunday hours (belong to prior week)
    "week_start_date": str,  # ISO date of Monday (e.g. "2026-03-23")
    "week_end_date":   str,  # ISO date of Saturday (e.g. "2026-03-28")
    "pdf_sunday_date": str,  # ISO date of the Sunday in this PDF
  }
"""

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pdfplumber


# ---------------------------------------------------------------------------
# Column name detection
# The PDF header row contains: Name, Company, Sunday, Monday, ..., Saturday, Total
# We detect day-column x-positions by finding these header labels.
# ---------------------------------------------------------------------------

_DAY_COLUMN_LABELS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_TOTAL_LABEL = "Total"
_COMPANY_LABEL = "Company"
_NAME_LABEL = "Name"

# Tolerance for x-position matching (points)
_COL_TOLERANCE = 22.0

# R&D company label variants
_RD_COMPANY_VARIANTS = {"R&D", "R&D Controls", "R&D Controls Corp"}

# Pattern for a numeric hour value: integer or decimal (e.g. 3.5, 4, 12)
_RE_HOURS = re.compile(r"^\d+(\.\d+)?$")


# ---------------------------------------------------------------------------
# Date range parsing from PDF title
# ---------------------------------------------------------------------------

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_RE_DATE_RANGE = re.compile(
    r"for\s+dates\s+"
    r"([A-Za-z]+)\s+(\d+)\s*[-–]\s*(?:([A-Za-z]+)\s+)?(\d+),?\s*(\d{4})",
    re.IGNORECASE,
)


def _parse_date_range_from_text(text: str) -> tuple[date | None, date | None]:
    """Extract the Sunday and Saturday dates from the 'For Dates ...' header line.

    Returns:
        (sunday_date, saturday_date) as date objects, or (None, None) if parse fails.
    """
    m = _RE_DATE_RANGE.search(text)
    if not m:
        return None, None

    start_month_str, start_day_str, end_month_str, end_day_str, year_str = m.groups()

    year = int(year_str)
    start_month = _MONTH_MAP.get(start_month_str.lower())
    if start_month is None:
        return None, None

    # If end month is given, use it; otherwise end is same month as start
    if end_month_str:
        end_month = _MONTH_MAP.get(end_month_str.lower())
        if end_month is None:
            end_month = start_month
    else:
        end_month = start_month

    try:
        start_date = date(year, start_month, int(start_day_str))
        end_date   = date(year, end_month,   int(end_day_str))
    except ValueError:
        return None, None

    return start_date, end_date


# ---------------------------------------------------------------------------
# Word grouping (same as pdf_parser_v2)
# ---------------------------------------------------------------------------

def _group_words_by_row(words: list[dict], y_tolerance: float = 3.0) -> list[list[dict]]:
    """Group words into rows by y-position."""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    rows: list[list[dict]] = []
    current_row = [sorted_words[0]]
    current_y   = sorted_words[0]["top"]
    for word in sorted_words[1:]:
        if abs(word["top"] - current_y) <= y_tolerance:
            current_row.append(word)
        else:
            rows.append(sorted(current_row, key=lambda w: w["x0"]))
            current_row = [word]
            current_y   = word["top"]
    if current_row:
        rows.append(sorted(current_row, key=lambda w: w["x0"]))
    return rows


# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------

def _detect_columns(header_row: list[dict]) -> dict[str, float]:
    """Return a mapping of label → x0 from the PDF header row.

    Looks for Name, Company, Sunday, Monday, … Saturday, Total.
    """
    col_map: dict[str, float] = {}
    labels_to_find = set(_DAY_COLUMN_LABELS + [_TOTAL_LABEL, _COMPANY_LABEL, _NAME_LABEL])
    for word in header_row:
        text = word["text"].strip().rstrip(":")
        if text in labels_to_find:
            col_map[text] = word["x0"]
    return col_map


def _value_at_x(row_words: list[dict], col_x: float) -> str:
    """Return the text of the word closest to col_x on a row, or ''."""
    candidates = [w for w in row_words if abs(w["x0"] - col_x) <= _COL_TOLERANCE]
    if not candidates:
        return ""
    return min(candidates, key=lambda w: abs(w["x0"] - col_x))["text"]


def _hours_at_x(row_words: list[dict], col_x: float) -> float:
    """Return the numeric hour value closest to col_x, or 0.0."""
    text = _value_at_x(row_words, col_x)
    if _RE_HOURS.match(text):
        return float(text)
    return 0.0


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_travel_pdf(
    pdf_path: str | Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse a travel hours PDF and return per-employee rows.

    Only R&D employees are returned (company column = "R&D" variant).
    All other vendors are silently skipped — the travel PDF includes all
    Centerline contractors.

    Args:
        pdf_path: Path to the travel PDF file.

    Returns:
        A 2-tuple: (rows, warnings)

        rows:     List of dicts (see module docstring for shape), one per R&D employee.
        warnings: Strings describing skipped or ambiguous rows.

    Raises:
        FileNotFoundError: If pdf_path does not exist.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Travel PDF not found: {pdf_path}")

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Date range determined from the PDF title line
    sunday_date:   date | None = None
    saturday_date: date | None = None

    # Column x-positions from the header row
    col_map: dict[str, float] = {}
    header_detected = False

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            words = page.extract_words()
            if not words:
                continue

            # Try to extract the date range from the full page text
            if sunday_date is None:
                page_text = page.extract_text() or ""
                sd, ed = _parse_date_range_from_text(page_text)
                if sd and ed:
                    sunday_date   = sd
                    saturday_date = ed
                elif sunday_date is None:
                    warnings.append(
                        f"Page {page_num}: Could not parse date range from PDF header. "
                        "Week dates will be absent from results."
                    )

            word_rows = _group_words_by_row(words)

            for row in word_rows:
                texts = [w["text"] for w in row]
                if not texts:
                    continue

                # ---- Accumulate column positions from header rows ----
                # The travel PDF uses a multi-row header:
                #   Row 1: "Sunday Monday Tuesday ... Saturday Total Travel Hrs"  (y≈68)
                #   Row 2: "Name Company"                                          (y≈81)
                #   Row 3: "TRAVEL TRAVEL ... TRAVEL Travel Hrs"                  (y≈82)
                # We accumulate col_map entries from all header-like rows before
                # the first data row appears.
                if not header_detected:
                    # Check if this row has day-name headers
                    if "Sunday" in texts and "Monday" in texts:
                        col_map.update(_detect_columns(row))
                        continue
                    # Check if this row has Name/Company headers
                    if "Name" in texts or "Company" in texts:
                        col_map.update(_detect_columns(row))
                        continue
                    # Skip TRAVEL label rows and other pure-label rows
                    if all(t in {"TRAVEL", "Travel", "Hrs", "TRAVEL"} for t in texts):
                        continue
                    # If we have the key columns we need, mark header as detected
                    if "Sunday" in col_map and "Monday" in col_map and "Company" in col_map:
                        header_detected = True
                    elif "Sunday" in col_map and "Monday" in col_map:
                        # Company label may be absent in some PDFs; mark as detected anyway
                        header_detected = True
                    else:
                        continue  # still in header area, skip

                # ---- Skip the TRAVEL sub-header row (just "TRAVEL" labels) ----
                if all(t == "TRAVEL" or t == "Travel" or t == "Hrs" for t in texts):
                    continue

                # ---- Skip empty or header-like rows ----
                if len(row) < 2:
                    continue

                # ---- Determine if this is an R&D employee row ----
                # The name column starts at the leftmost x; company column follows.
                # We need the company column to be present.
                if "Company" not in col_map:
                    warnings.append(f"Page {page_num}: Company column not found in column map.")
                    continue

                company_x = col_map["Company"]
                company_text = _value_at_x(row, company_x).strip()

                # Skip non-R&D rows
                if company_text not in _RD_COMPANY_VARIANTS:
                    continue

                # Extract employee name from words to the left of the Company column
                name_words = [w for w in row if w["x0"] < company_x - 10]
                raw_name = " ".join(w["text"] for w in name_words).strip()

                if not raw_name:
                    warnings.append(
                        f"Page {page_num}: R&D row found but name is empty. "
                        f"Row texts: {texts!r}"
                    )
                    continue

                # Extract hours from each day column
                day_hours: dict[str, float] = {}
                for day_label in _DAY_COLUMN_LABELS:
                    if day_label in col_map:
                        day_hours[day_label] = _hours_at_x(row, col_map[day_label])
                    else:
                        day_hours[day_label] = 0.0

                pdf_total = _hours_at_x(row, col_map.get("Total", -999))

                # Compute cross-check total
                computed_total = sum(day_hours.values())
                if pdf_total > 0 and abs(computed_total - pdf_total) > 0.01:
                    warnings.append(
                        f"Travel total mismatch for {raw_name!r}: "
                        f"PDF says {pdf_total}, computed {computed_total:.2f}."
                    )

                # Business rule: Monday–Saturday belong to the current Mon–Sun week;
                # Sunday belongs to the prior Mon–Sun week.
                current_week_total = sum(
                    day_hours[d] for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
                )
                prior_sun_hours = day_hours.get("Sunday", 0.0)

                # Resolve dates
                week_start_date = str(sunday_date + timedelta(days=1)) if sunday_date else ""
                week_end_date   = str(saturday_date) if saturday_date else ""
                pdf_sunday_date = str(sunday_date) if sunday_date else ""

                rows.append({
                    "raw_name":            raw_name,
                    "company":             company_text,
                    "sun_hours":           day_hours.get("Sunday",    0.0),
                    "mon_hours":           day_hours.get("Monday",    0.0),
                    "tue_hours":           day_hours.get("Tuesday",   0.0),
                    "wed_hours":           day_hours.get("Wednesday", 0.0),
                    "thu_hours":           day_hours.get("Thursday",  0.0),
                    "fri_hours":           day_hours.get("Friday",    0.0),
                    "sat_hours":           day_hours.get("Saturday",  0.0),
                    "pdf_total":           pdf_total,
                    "current_week_total":  current_week_total,
                    "prior_sun_hours":     prior_sun_hours,
                    "week_start_date":     week_start_date,
                    "week_end_date":       week_end_date,
                    "pdf_sunday_date":     pdf_sunday_date,
                })

    if not header_detected:
        warnings.append("Travel PDF column headers (Sunday, Monday, …) were never found.")

    return rows, warnings
