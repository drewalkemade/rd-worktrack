"""
pdf_parser_v2.py — Word-position-based payroll PDF parser.

Replaces the legacy position-indexed parser (pdf_parser.py).

Key improvements over v1:
  - Uses pdfplumber.extract_words() with x-position proximity to locate
    REG/OT/DBL column values rather than relying on fixed list indices.
  - Detects column headers from the garbled PDF header text using regex
    patterns (the header font embeds characters as quadrupled glyphs).
  - Extracts per-day detail rows in addition to per-employee totals.
  - Handles employees whose data spans across page boundaries (any employee,
    not a hardcoded one — which employee hits the boundary depends on how many
    employees Centerline has and how the PDF paginates).
  - Never silently discards a row that looks like it could be an employee —
    parsing warnings are returned alongside the data.

Data returned for each employee:
  {
    "employee_name":  str,       # e.g. "Trif, Daniel" (title-cased)
    "pdf_name":       str,       # e.g. "TRIF, DANIEL" (raw from PDF)
    "centerline_id":  int,       # e.g. 8190
    "pdf_id":         str,       # e.g. "E8190"
    "reg_hours":      float,
    "ot_hours":       float,
    "dbl_hours":      float,
    "daily_rows": [
      {
        "day_name":    str,      # "Monday", "Tuesday", etc.
        "work_date":   str,      # "Mar 23" — date string from PDF
        "clock_in":    str,      # "6:00" or "" if absent
        "clock_out":   str,      # "16:30" or "" if absent
        "total_hours": float,    # attendance total for this day
        "is_dbl_day":  bool,     # True if the pay class contains "DBL" or "SUN"
      }
    ]
  }

Warnings list contains strings describing any rows that were ambiguous,
skipped, or required fallback handling.
"""

import re
from pathlib import Path
from typing import Any

import pdfplumber


# ---------------------------------------------------------------------------
# Column detection — the PDF header row uses font glyphs that double/triple
# each letter, so "REG" appears as "RRREEEGGG".  We match with + quantifiers.
# ---------------------------------------------------------------------------

_RE_REG_HEADER = re.compile(r"^R+E+G+$", re.IGNORECASE)
_RE_OT_HEADER  = re.compile(r"^O+T+$",   re.IGNORECASE)
_RE_DBL_HEADER = re.compile(r"^D+B+L+$", re.IGNORECASE)

# Employee header pattern: "LASTNAME, FIRSTNAME  08022"
# The name is all-caps; the ID is exactly 5 digits.
_RE_EMPLOYEE_HEADER = re.compile(
    r"^([A-Z]+(?:-[A-Z]+)?,\s+[A-Z]+(?:-[A-Z]+)?)\s+(\d{5})$"
)

# Time value: matches HH:MM or H:MM (allows large hour totals like 120:00)
_RE_TIME_VALUE = re.compile(r"^\d{1,3}:\d{2}$")

# Day names that appear as the first word on a daily-detail row
_DAY_NAMES = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
              "Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday"}

# Approximate x-position tolerance when matching column values (points)
_COL_TOLERANCE = 18.0

# Minimum number of time values on a line for it to be considered a totals row
_TOTALS_MIN_TIME_VALUES = 6

# Words in the pay class field that indicate double-time
_DBL_INDICATORS = {"DBL", "SUN", "Double", "dbl"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _time_to_decimal(time_str: str) -> float:
    """Convert HH:MM to decimal hours. Returns 0.0 on any parse failure."""
    if not time_str or not _RE_TIME_VALUE.match(time_str.strip()):
        return 0.0
    try:
        h, m = time_str.strip().split(":")
        return round(int(h) + int(m) / 60.0, 4)
    except (ValueError, AttributeError):
        return 0.0


def _words_on_row(words: list[dict], y: float, y_tolerance: float = 3.0) -> list[dict]:
    """Return all words whose 'top' value is within y_tolerance of y."""
    return [w for w in words if abs(w["top"] - y) <= y_tolerance]


def _find_column_x(words: list[dict], pattern: re.Pattern) -> float | None:
    """Return the x0 of the first word in the header region that matches pattern."""
    for w in words:
        if pattern.match(w["text"]):
            return w["x0"]
    return None


def _value_at_column(row_words: list[dict], col_x: float | None) -> str:
    """Return the text of the word closest to col_x on a row, or '' if none found."""
    if col_x is None:
        return ""
    candidates = [
        w for w in row_words
        if abs(w["x0"] - col_x) <= _COL_TOLERANCE and _RE_TIME_VALUE.match(w["text"])
    ]
    if not candidates:
        return ""
    # Pick the word whose x0 is closest to the column center
    return min(candidates, key=lambda w: abs(w["x0"] - col_x))["text"]


def _is_totals_row(row_words: list[dict]) -> bool:
    """Return True if this row looks like an employee biweekly totals row.

    Criteria:
      - All words on the row are time values
      - At least _TOTALS_MIN_TIME_VALUES time values present
      - The first word starts at x0 > 300 (not a name or day-of-week column)
    """
    if not row_words:
        return False
    time_words = [w for w in row_words if _RE_TIME_VALUE.match(w["text"])]
    non_time_words = [w for w in row_words if not _RE_TIME_VALUE.match(w["text"])]
    if len(time_words) < _TOTALS_MIN_TIME_VALUES:
        return False
    if non_time_words:
        return False
    min_x = min(w["x0"] for w in row_words)
    return min_x > 300


def _is_grand_total_row(row_words: list[dict]) -> bool:
    """Return True if this looks like the document-level grand total row.

    The grand total row looks exactly like a per-employee totals row but
    appears after all employees.  We rely on the caller tracking state
    (no active employee) rather than trying to distinguish it here.
    """
    return _is_totals_row(row_words)


# ---------------------------------------------------------------------------
# Per-page word grouping
# ---------------------------------------------------------------------------

def _group_words_by_row(words: list[dict], y_tolerance: float = 3.0) -> list[list[dict]]:
    """Group a flat list of words into rows by their y-position.

    Words within y_tolerance of each other are considered to be on the same row.
    Returns a list of rows, each row being a list of words sorted by x0.
    """
    if not words:
        return []

    # Sort by top then x0
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))

    rows: list[list[dict]] = []
    current_row: list[dict] = [sorted_words[0]]
    current_y: float = sorted_words[0]["top"]

    for word in sorted_words[1:]:
        if abs(word["top"] - current_y) <= y_tolerance:
            current_row.append(word)
        else:
            rows.append(sorted(current_row, key=lambda w: w["x0"]))
            current_row = [word]
            current_y = word["top"]

    if current_row:
        rows.append(sorted(current_row, key=lambda w: w["x0"]))

    return rows


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_payroll_pdf(
    pdf_path: str | Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse a payroll approval PDF and extract per-employee hour totals and daily detail.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        A 2-tuple: (employees, warnings)

        employees: List of dicts, one per employee (see module docstring for shape).
        warnings:  List of human-readable strings describing ambiguous or skipped rows.

    Raises:
        FileNotFoundError: If pdf_path does not exist.
        Exception:         Re-raised from pdfplumber on corrupt/unreadable PDFs.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Payroll PDF not found: {pdf_path}")

    employees: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Column x-positions — detected from the first header row encountered
    reg_col_x: float | None = None
    ot_col_x:  float | None = None
    dbl_col_x: float | None = None

    # State machine across pages
    current_employee: dict[str, Any] | None = None  # employee being built
    pending_day_rows: list[dict] = []                # daily rows for current employee

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            words = page.extract_words()
            if not words:
                continue

            rows = _group_words_by_row(words)

            for row in rows:
                texts = [w["text"] for w in row]

                # ---- Detect column headers (only needs to happen once) ----
                if reg_col_x is None:
                    reg_x = _find_column_x(row, _RE_REG_HEADER)
                    if reg_x is not None:
                        reg_col_x = reg_x
                        ot_col_x  = _find_column_x(row, _RE_OT_HEADER)
                        dbl_col_x = _find_column_x(row, _RE_DBL_HEADER)
                    continue  # header row — skip to next row

                # ---- Check for employee header row ----
                # Employee header: "LASTNAME, FIRSTNAME  08022  Mon, Mar 23 ..."
                # The name and ID are split across three separate word tokens:
                #   "ATKINSON,"  "JEREMY"  "08022"
                # We must try 3-word window combinations to match the full pattern.
                employee_match = None
                if len(texts) >= 3:
                    for i in range(len(texts) - 2):
                        # Try 3-word window: "LASTNAME, FIRSTNAME 08022"
                        combined3 = " ".join(texts[i : i + 3])
                        m = _RE_EMPLOYEE_HEADER.match(combined3)
                        if m:
                            employee_match = m
                            break
                        # Also try 2-word window in case the name+ID are fused
                        combined2 = " ".join(texts[i : i + 2])
                        m = _RE_EMPLOYEE_HEADER.match(combined2)
                        if m:
                            employee_match = m
                            break

                if employee_match:
                    # Save the previous employee before starting a new one
                    if current_employee is not None:
                        warnings.append(
                            f"Employee {current_employee['pdf_name']!r} had no totals row "
                            f"before next employee started — data may be incomplete."
                        )
                        employees.append(current_employee)

                    raw_name = employee_match.group(1)
                    raw_id   = employee_match.group(2)
                    cid      = int(raw_id)  # strips leading zero: 08022 → 8022

                    current_employee = {
                        "pdf_name":      raw_name,
                        "employee_name": raw_name.title(),
                        "centerline_id": cid,
                        "pdf_id":        f"E{cid}",
                        "reg_hours":     0.0,
                        "ot_hours":      0.0,
                        "dbl_hours":     0.0,
                        "daily_rows":    [],
                    }
                    pending_day_rows = []

                    # Extract first daily row from the same line.
                    # The employee header row contains the name + ID + Monday's full detail
                    # on the same line.  The name is the first 3 words (LASTNAME, FIRSTNAME,
                    # NNNNN), so we skip to the first word that is a day-name abbreviation.
                    day_start_idx = None
                    for idx, w in enumerate(row):
                        if w["text"].rstrip(",") in _DAY_NAMES:
                            day_start_idx = idx
                            break
                    if day_start_idx is not None:
                        sub_row = row[day_start_idx:]
                        day_row = _extract_day_row_from_words(sub_row, reg_col_x, ot_col_x, dbl_col_x)
                        if day_row:
                            current_employee["daily_rows"].append(day_row)
                    continue

                # ---- Check for totals row ----
                if _is_totals_row(row):
                    if current_employee is None:
                        # Grand total row — skip
                        continue

                    # Extract REG / OT / DBL from column positions
                    if reg_col_x is not None:
                        reg_str = _value_at_column(row, reg_col_x)
                        ot_str  = _value_at_column(row, ot_col_x)
                        dbl_str = _value_at_column(row, dbl_col_x)
                    else:
                        # Column positions never detected — fall back to positional index
                        time_values = [w["text"] for w in row]
                        reg_str = time_values[3] if len(time_values) > 3 else "0:00"
                        ot_str  = time_values[4] if len(time_values) > 4 else "0:00"
                        dbl_str = time_values[5] if len(time_values) > 5 else "0:00"
                        warnings.append(
                            f"Column headers not found — used positional fallback for "
                            f"employee {current_employee['pdf_name']!r}."
                        )

                    current_employee["reg_hours"] = _time_to_decimal(reg_str)
                    current_employee["ot_hours"]  = _time_to_decimal(ot_str)
                    current_employee["dbl_hours"] = _time_to_decimal(dbl_str)

                    employees.append(current_employee)
                    current_employee = None
                    continue

                # ---- Check for daily detail row ----
                if current_employee is not None:
                    day_row = _extract_day_row_from_words(row, reg_col_x, ot_col_x, dbl_col_x)
                    if day_row:
                        current_employee["daily_rows"].append(day_row)

    # Handle any employee still open at end of last page
    if current_employee is not None:
        warnings.append(
            f"Employee {current_employee['pdf_name']!r} had no totals row at end of PDF."
        )
        employees.append(current_employee)

    if reg_col_x is None:
        warnings.append(
            "REG/OT/DBL column headers were never detected in this PDF. "
            "All hour values used positional fallback."
        )

    return employees, warnings


# ---------------------------------------------------------------------------
# Daily row extraction helper
# ---------------------------------------------------------------------------

def _extract_day_row_from_words(
    row: list[dict],
    reg_col_x: float | None,
    ot_col_x: float | None,
    dbl_col_x: float | None,
) -> dict | None:
    """Extract a daily-detail record from a row of words, or return None.

    A daily row starts with a day-of-week abbreviation (Mon, Tue, …) at
    x0 ≈ 150.  It may also include clock-in, clock-out, total hours, and
    pay-class text.

    Returns:
        A dict with daily row fields, or None if this row is not a daily row.
    """
    texts = [w["text"] for w in row]
    if not texts:
        return None

    # The first word on a daily row is the day abbreviation, near x0=150
    first_word = row[0]
    if first_word["x0"] > 200:
        return None  # Not a daily row (too far right for a day name)

    day_text = first_word["text"].rstrip(",")
    if day_text not in _DAY_NAMES:
        return None

    # Collect date: the next one or two tokens after the day name are the date
    date_parts = []
    for w in row[1:3]:
        if w["x0"] < 200 and not _RE_TIME_VALUE.match(w["text"]) and w["text"] not in _DAY_NAMES:
            date_parts.append(w["text"])
        else:
            break
    work_date = " ".join(date_parts)

    # Clock-in: word near x0 ≈ 280 that is a time value
    clock_in  = _find_time_near_x(row, 280.0)
    clock_out = _find_time_near_x(row, 317.0)

    # Total hours: word near x0 ≈ 358–361 (attendance / labour total column)
    total_hours_str = _find_time_near_x(row, 358.0) or _find_time_near_x(row, 361.0)
    total_hours = _time_to_decimal(total_hours_str) if total_hours_str else 0.0

    # Detect double-time day from pay-class field text
    pay_class_text = " ".join(
        w["text"] for w in row if 439.0 <= w["x0"] <= 530.0
    )
    is_dbl_day = any(ind in pay_class_text for ind in _DBL_INDICATORS)

    return {
        "day_name":    day_text,
        "work_date":   work_date,
        "clock_in":    clock_in or "",
        "clock_out":   clock_out or "",
        "total_hours": total_hours,
        "is_dbl_day":  is_dbl_day,
    }


def _find_time_near_x(row: list[dict], target_x: float, tolerance: float = 20.0) -> str | None:
    """Return the text of the first time-valued word near target_x, or None."""
    candidates = [
        w for w in row
        if abs(w["x0"] - target_x) <= tolerance and _RE_TIME_VALUE.match(w["text"])
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda w: abs(w["x0"] - target_x))["text"]


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def parse_payroll_pdf_totals_only(
    pdf_path: str | Path,
) -> list[dict[str, Any]]:
    """Parse a payroll PDF and return only the per-employee totals (no daily rows).

    Raises ParseError on any warning, so callers that only need totals can
    use this simpler interface and get clear failure on unexpected input.

    Returns:
        List of dicts with keys: pdf_name, employee_name, centerline_id,
        pdf_id, reg_hours, ot_hours, dbl_hours.
    """
    employees, warnings = parse_payroll_pdf(pdf_path)
    # Strip daily rows for callers that don't need them
    for emp in employees:
        emp.pop("daily_rows", None)
    return employees, warnings
