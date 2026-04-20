"""
importer.py — Source file ingestion pipeline.

Responsible for ingesting all three source file types into the database:
  1. Payroll approval PDFs  (weekly, one per week ending date)
  2. Travel hour PDFs       (weekly, Sun–Sat range)
  3. Employee timesheets    (biweekly .xlsx workbooks)

Public entry points
-------------------
  import_payroll_pdf(conn, pdf_path, week_ending_date, *, original_name, normalized_name)
  import_travel_pdf(conn, pdf_path, *, original_name, normalized_name)
  import_timesheet(conn, xlsx_path, *, original_name, normalized_name)

Each function:
  1. Copies the file into the source-file store (db.store_source_file)
  2. Parses the file using the relevant extractor
  3. Resolves employee identities via the employee_aliases table
  4. Creates or updates pay_period and weekly_approval records
  5. Upserts all extracted data idempotently
  6. Returns an ImportResult with counts and warnings

Idempotency
-----------
Importing the same file twice is safe.  On conflict, existing rows are updated
to match the freshly parsed values.  Employee hour rows use ON CONFLICT DO UPDATE.
Expense items have no natural unique key, so they are deleted and re-inserted
on re-import (receipt links are not yet implemented in Phase 2).

Sunday travel boundary
----------------------
The travel PDF is formatted Sun–Sat, but the business week is Mon–Sun.
  • The PDF's Sunday belongs to the PRIOR Mon–Sun week.
  • Mon–Sat hours belong to the CURRENT week (week ending = Saturday + 1 day).
  • The current week's Sunday is unknown until the NEXT travel PDF arrives.
    Its status is stored as current_sun_status = 'pending_next_pdf' until confirmed.
When a travel PDF is imported, its Sunday hours are applied back to the prior
weekly_approval's travel_hours row (setting current_sun_status = 'confirmed').

Employee resolution
-------------------
For payroll PDFs:   alias_type = 'pdf_name',    e.g. "TRIF, DANIEL"
For travel PDFs:    alias_type = 'travel_name', e.g. "Daniel Trif"
For timesheets:     alias_type = 'display_name' or any, e.g. "Daniel Trif"

Unresolvable employees are never silently dropped — they appear in warnings.
"""

import dataclasses
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from payroll_app import config
from payroll_app.database import db, employee_manager
from payroll_app.extractors import pdf_parser_v2, travel_parser, timesheet_extractor_v2


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ImportResult:
    """Return value from every import_* function."""
    success: bool
    source_file_id: int | None
    pay_period_id: int | None
    weekly_approval_id: int | None   # set by payroll/travel imports; None for timesheets
    timesheet_import_id: int | None  # set by timesheet imports; None for payroll/travel
    employee_count: int              # number of employee records successfully imported
    skipped_count: int               # number of employee rows that could not be resolved
    warnings: list[str]
    errors: list[str]
    extraction_log: list[str] = dataclasses.field(default_factory=list)
    # Human-readable line-by-line log of what was extracted.
    # Each entry is one line; the UI renders these in a monospace block.


# ---------------------------------------------------------------------------
# Pay-period helpers
# ---------------------------------------------------------------------------

def _find_or_create_pay_period(
    conn: Any,
    week_ending: date,
) -> tuple[int, int]:
    """Find or create a pay period given a week-ending Sunday date.

    Resolution order:
      1. Existing period where week1_ending = week_ending → return (id, 1)
      2. Existing period where week2_ending = week_ending → return (id, 2)
      3. Existing period where week1_ending = week_ending − 7 → assign as week 2,
         update period_end and week2_ending, return (id, 2)
      4. None of the above → create new period with this date as week1_ending,
         return (new_id, 1)

    The Monday of a business week is week_ending − 6 days.
    The biweekly period covers two consecutive Mon–Sun weeks.

    Args:
        conn:         Open database connection.
        week_ending:  The Sunday that ends a Mon–Sun business week.

    Returns:
        (pay_period_id, week_number) where week_number is 1 or 2.
    """
    week_ending_str = str(week_ending)

    # Case 1: already the first week of an existing period
    row = db.fetch_one(
        conn,
        "SELECT id FROM pay_periods WHERE week1_ending = ?",
        (week_ending_str,),
    )
    if row:
        return row["id"], 1

    # Case 2: already the second week of an existing period
    row = db.fetch_one(
        conn,
        "SELECT id FROM pay_periods WHERE week2_ending = ?",
        (week_ending_str,),
    )
    if row:
        return row["id"], 2

    # Case 3: week_ending − 7 is week 1 of an existing period → this is week 2
    prior_week_str = str(week_ending - timedelta(days=7))
    row = db.fetch_one(
        conn,
        "SELECT id FROM pay_periods WHERE week1_ending = ?",
        (prior_week_str,),
    )
    if row:
        period_id = row["id"]
        conn.execute(
            "UPDATE pay_periods SET week2_ending = ?, period_end = ? WHERE id = ?",
            (week_ending_str, week_ending_str, period_id),
        )
        return period_id, 2

    # Case 4: no existing period — create one with this as week 1
    period_start  = week_ending - timedelta(days=6)   # Monday of week 1
    week2_ending  = week_ending + timedelta(days=7)    # Sunday of week 2
    period_end    = week2_ending

    cursor = conn.execute(
        """
        INSERT INTO pay_periods (period_start, period_end, week1_ending, week2_ending, status)
        VALUES (?, ?, ?, ?, 'open')
        """,
        (str(period_start), str(period_end), week_ending_str, str(week2_ending)),
    )
    return cursor.lastrowid, 1


def _find_or_create_pay_period_from_period_end(
    conn: Any,
    period_end: date,
) -> int:
    """Find or create a pay period given the biweekly period end date.

    For timesheets, the period_end extracted from cell H5 is always the Sunday
    that ends week 2 of the pay period (= week2_ending).

    Args:
        conn:        Open database connection.
        period_end:  The Sunday that ends the biweekly pay period (= week2_ending).

    Returns:
        pay_period_id
    """
    period_end_str = str(period_end)

    # Prefer week2_ending match — the normal case
    row = db.fetch_one(
        conn,
        "SELECT id FROM pay_periods WHERE week2_ending = ?",
        (period_end_str,),
    )
    if row:
        return row["id"]

    # Fall back to week1_ending match.  This handles the edge case where the
    # payroll PDF for the same week-ending date was imported first and was
    # assigned as week1 because no prior week existed at import time.
    row = db.fetch_one(
        conn,
        "SELECT id FROM pay_periods WHERE week1_ending = ?",
        (period_end_str,),
    )
    if row:
        return row["id"]

    # Create a new period — period_end is week2_ending
    week2_ending  = period_end
    week1_ending  = period_end - timedelta(days=7)
    period_start  = period_end - timedelta(days=13)  # 14-day period (2 × Mon–Sun)

    cursor = conn.execute(
        """
        INSERT INTO pay_periods (period_start, period_end, week1_ending, week2_ending, status)
        VALUES (?, ?, ?, ?, 'open')
        """,
        (str(period_start), str(period_end), str(week1_ending), str(week2_ending)),
    )
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Weekly-approval helper
# ---------------------------------------------------------------------------

def _find_or_create_weekly_approval(
    conn: Any,
    pay_period_id: int,
    week_number: int,
    week_ending: date,
    *,
    payroll_pdf_file: str | None = None,
    travel_pdf_file: str | None = None,
) -> int:
    """Find or create a weekly_approvals row for the given period/week slot.

    If the row already exists, only non-None file name arguments are updated
    (so importing a travel PDF does not erase the previously stored payroll PDF
    filename, and vice versa).

    Args:
        conn:              Open database connection.
        pay_period_id:     ID of the parent pay_periods row.
        week_number:       1 or 2.
        week_ending:       The Sunday date that ends this week.
        payroll_pdf_file:  Normalized payroll PDF filename (if this is a payroll import).
        travel_pdf_file:   Normalized travel PDF filename (if this is a travel import).

    Returns:
        weekly_approvals.id
    """
    existing = db.fetch_one(
        conn,
        "SELECT * FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
        (pay_period_id, week_number),
    )

    if existing:
        wa_id = existing["id"]
        if payroll_pdf_file:
            conn.execute(
                "UPDATE weekly_approvals SET payroll_pdf_file = ? WHERE id = ?",
                (payroll_pdf_file, wa_id),
            )
        if travel_pdf_file:
            conn.execute(
                "UPDATE weekly_approvals SET travel_pdf_file = ? WHERE id = ?",
                (travel_pdf_file, wa_id),
            )
        return wa_id

    cursor = conn.execute(
        """
        INSERT INTO weekly_approvals
            (pay_period_id, week_ending, week_number, payroll_pdf_file, travel_pdf_file)
        VALUES (?, ?, ?, ?, ?)
        """,
        (pay_period_id, str(week_ending), week_number, payroll_pdf_file, travel_pdf_file),
    )
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Employee resolution
# ---------------------------------------------------------------------------

def _resolve_pdf_date(date_str: str, week_ending: date) -> str | None:
    """Convert a PDF date string like "Mar 23" to an ISO date "2026-03-23".

    The PDF omits the year.  We try the week_ending year first; if the resulting
    date is more than 30 days away from week_ending we try the prior year, which
    handles January PDFs processed in a prior-December pay period.
    """
    if not date_str or not date_str.strip():
        return None
    try:
        # "%b %d" handles "Mar 23", "Apr  7", etc.
        parsed = date.fromisoformat(
            f"{week_ending.year}-"
            + datetime.strptime(date_str.strip(), "%b %d").strftime("%m-%d")
        )
    except ValueError:
        try:
            # Some PDFs use full month names: "March 23"
            parsed = date.fromisoformat(
                f"{week_ending.year}-"
                + datetime.strptime(date_str.strip(), "%B %d").strftime("%m-%d")
            )
        except ValueError:
            return None

    # If >30 days from week_ending, the year is likely off — try prior year
    if abs((parsed - week_ending).days) > 30:
        parsed = parsed.replace(year=week_ending.year - 1)

    return str(parsed)


def _resolve_employee(
    conn: Any,
    name: str,
    alias_type: str,
) -> tuple[int | None, list[str]]:
    """Resolve an employee name to an employees.id via the alias table.

    Tries exact alias match first, then rapidfuzz fuzzy match.  Ambiguous
    fuzzy matches are never silently accepted; they return None with a warning.

    Args:
        conn:        Open database connection.
        name:        Raw name string from the source document.
        alias_type:  Alias type to search: 'pdf_name' | 'travel_name' | 'display_name'

    Returns:
        (employee_id_or_None, warnings_list)
    """
    warnings: list[str] = []

    # 1. Exact alias match
    emp = employee_manager.find_employee_by_alias(conn, name, alias_type=alias_type)
    if emp:
        return emp["id"], warnings

    # 2. Fuzzy match
    emp, score, is_ambiguous = employee_manager.fuzzy_find_employee(
        conn, name, alias_type=alias_type, min_score=80
    )

    if is_ambiguous:
        warnings.append(
            f"Ambiguous employee match for {name!r} (alias_type={alias_type!r}, "
            f"score={score}): multiple candidates within 5 points — skipped."
        )
        return None, warnings

    if emp:
        warnings.append(
            f"Fuzzy match: {name!r} → {emp['display_name']!r} "
            f"(alias_type={alias_type!r}, score={score})"
        )
        return emp["id"], warnings

    warnings.append(
        f"No employee match for {name!r} (alias_type={alias_type!r}) — skipped."
    )
    return None, warnings


# ---------------------------------------------------------------------------
# Travel Sunday backfill
# ---------------------------------------------------------------------------

def _apply_travel_sunday_to_prior_week(
    conn: Any,
    employee_id: int,
    sun_hours: float,
    pdf_sunday_date: date,
    source_file_id: int,
) -> bool:
    """Apply the PDF's Sunday hours back to the prior week's travel_hours record.

    The PDF's Sunday (pdf_sunday_date) is the Sunday that ENDS the prior
    Mon–Sun business week (week_ending = pdf_sunday_date).

    If a weekly_approval exists for that prior week, this function updates
    (or creates) the travel_hours row to record the confirmed Sunday hours and
    sets current_sun_status = 'confirmed'.

    Args:
        conn:             Open database connection.
        employee_id:      employees.id
        sun_hours:        Hours from the PDF's Sunday column.
        pdf_sunday_date:  The Sunday date from the travel PDF header.
        source_file_id:   source_files.id of the travel PDF being imported.

    Returns:
        True if a prior-week record was found and updated; False otherwise.
    """
    # Find the weekly_approval for the prior week
    prior_wa = db.fetch_one(
        conn,
        "SELECT id FROM weekly_approvals WHERE week_ending = ?",
        (str(pdf_sunday_date),),
    )
    if not prior_wa:
        # Prior week not yet imported; nothing to update
        return False

    prior_wa_id = prior_wa["id"]

    existing = db.fetch_one(
        conn,
        "SELECT id, current_sun_status FROM travel_hours WHERE weekly_approval_id = ? AND employee_id = ?",
        (prior_wa_id, employee_id),
    )

    if existing:
        conn.execute(
            """
            UPDATE travel_hours
            SET current_sun_status          = 'confirmed',
                current_sun_hours_assumed   = ?,
                current_sun_note            = 'Confirmed from following travel PDF'
            WHERE id = ?
            """,
            (sun_hours, existing["id"]),
        )
    else:
        # The prior week's travel PDF was not yet imported (or employee was absent);
        # create a skeleton record so the confirmed Sunday is not lost.
        conn.execute(
            """
            INSERT INTO travel_hours
                (weekly_approval_id, employee_id,
                 current_sun_status, current_sun_hours_assumed, current_sun_note,
                 source_file_id)
            VALUES (?, ?, 'confirmed', ?, 'Confirmed from following travel PDF', ?)
            """,
            (prior_wa_id, employee_id, sun_hours, source_file_id),
        )

    return True


# ---------------------------------------------------------------------------
# Payroll PDF importer
# ---------------------------------------------------------------------------

def import_payroll_pdf(
    conn: Any,
    pdf_path: str | Path,
    week_ending_date: str | date,
    *,
    original_name: str | None = None,
    normalized_name: str | None = None,
) -> ImportResult:
    """Ingest a weekly payroll approval PDF.

    Parses the PDF, resolves each employee against the alias table, and upserts
    the resulting customer_hours rows.  Creates or updates the pay_period and
    weekly_approval records as needed.

    Args:
        conn:               Open database connection.  Caller commits.
        pdf_path:           Path to the payroll approval PDF.
        week_ending_date:   The Sunday that ends the work week covered by this PDF.
                            Pass as a date object or ISO string (YYYY-MM-DD).
        original_name:      Original incoming filename (e.g. "R&D Controls Payroll...pdf").
                            Defaults to the file's basename.
        normalized_name:    Internal normalized filename (e.g. "R&D_260329-xxxxx.pdf").

    Returns:
        ImportResult
    """
    pdf_path = Path(pdf_path)
    errors: list[str] = []
    warnings: list[str] = []

    # --- Normalise week_ending_date ---
    if isinstance(week_ending_date, str):
        week_ending = date.fromisoformat(week_ending_date)
    else:
        week_ending = week_ending_date

    orig_name = original_name or pdf_path.name

    # 1. Store file and record in source_files
    try:
        source_file_id = db.store_source_file(
            conn,
            source_path=pdf_path,
            file_type="payroll_pdf",
            original_name=orig_name,
            normalized_name=normalized_name,
        )
    except (FileNotFoundError, ValueError) as exc:
        return ImportResult(
            success=False,
            source_file_id=None,
            pay_period_id=None,
            weekly_approval_id=None,
            timesheet_import_id=None,
            employee_count=0,
            skipped_count=0,
            warnings=warnings,
            errors=[str(exc)],
        )

    # 2. Parse the PDF
    try:
        employees, parse_warnings = pdf_parser_v2.parse_payroll_pdf(pdf_path)
    except Exception as exc:
        errors.append(f"PDF parse failed: {exc}")
        return ImportResult(
            success=False,
            source_file_id=source_file_id,
            pay_period_id=None,
            weekly_approval_id=None,
            timesheet_import_id=None,
            employee_count=0,
            skipped_count=0,
            warnings=warnings,
            errors=errors,
        )

    warnings.extend(parse_warnings)

    # 3. Resolve pay period and weekly approval
    pay_period_id, week_number = _find_or_create_pay_period(conn, week_ending)
    weekly_approval_id = _find_or_create_weekly_approval(
        conn,
        pay_period_id,
        week_number,
        week_ending,
        payroll_pdf_file=normalized_name or orig_name,
    )

    # 4. Upsert customer_hours for each employee
    employee_count = 0
    skipped_count = 0
    log_lines: list[str] = []

    for emp_data in employees:
        pdf_name = emp_data["pdf_name"]  # e.g. "TRIF, DANIEL"

        employee_id, emp_warnings = _resolve_employee(conn, pdf_name, alias_type="pdf_name")
        warnings.extend(emp_warnings)

        if employee_id is None:
            skipped_count += 1
            log_lines.append(f"  SKIP  {pdf_name} — no employee match")
            continue

        conn.execute(
            """
            INSERT INTO customer_hours
                (weekly_approval_id, employee_id, reg_hours, ot_hours, dbl_hours, source_file_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(weekly_approval_id, employee_id) DO UPDATE SET
                reg_hours      = excluded.reg_hours,
                ot_hours       = excluded.ot_hours,
                dbl_hours      = excluded.dbl_hours,
                source_file_id = excluded.source_file_id
            """,
            (
                weekly_approval_id,
                employee_id,
                emp_data["reg_hours"],
                emp_data["ot_hours"],
                emp_data["dbl_hours"],
                source_file_id,
            ),
        )

        # Store daily rows — clock-in, clock-out, total hours, pay class per day.
        # These power the day-level comparison in the Reconcile panel.
        for day in emp_data.get("daily_rows", []):
            # Resolve work_date: the PDF gives e.g. "Mar 23" — pair with week_ending year.
            work_date_str = _resolve_pdf_date(day["work_date"], week_ending)
            if work_date_str is None:
                warnings.append(
                    f"{pdf_name}: could not parse daily date {day['work_date']!r} — skipped"
                )
                continue
            conn.execute(
                """
                INSERT INTO customer_daily_hours
                    (weekly_approval_id, employee_id, work_date, day_name,
                     clock_in, clock_out, total_hours, is_dbl_day, source_file_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(weekly_approval_id, employee_id, work_date) DO UPDATE SET
                    day_name       = excluded.day_name,
                    clock_in       = excluded.clock_in,
                    clock_out      = excluded.clock_out,
                    total_hours    = excluded.total_hours,
                    is_dbl_day     = excluded.is_dbl_day,
                    source_file_id = excluded.source_file_id
                """,
                (
                    weekly_approval_id,
                    employee_id,
                    work_date_str,
                    day["day_name"],
                    day.get("clock_in") or None,
                    day.get("clock_out") or None,
                    day["total_hours"],
                    1 if day["is_dbl_day"] else 0,
                    source_file_id,
                ),
            )

        employee_count += 1
        # Fetch display name for the log
        emp_row = db.fetch_one(conn, "SELECT display_name FROM employees WHERE id = ?", (employee_id,))
        display = emp_row["display_name"] if emp_row else pdf_name
        daily_count = len(emp_data.get("daily_rows", []))
        log_lines.append(
            f"  OK    {pdf_name} → {display}:"
            f"  REG={emp_data['reg_hours']:.2f}"
            f"  OT={emp_data['ot_hours']:.2f}"
            f"  DBL={emp_data['dbl_hours']:.2f}"
            f"  ({daily_count} daily rows)"
        )

    # Build the period info for the header
    period_row = db.fetch_one(conn, "SELECT period_start, period_end FROM pay_periods WHERE id = ?", (pay_period_id,))
    period_hdr = ""
    if period_row:
        period_hdr = f"  Period: {period_row['period_start']} – {period_row['period_end']}  (Week {week_number})"

    extraction_log = [
        f"Payroll PDF: {orig_name}",
        f"  Week ending: {week_ending}",
        period_hdr,
        f"  Weekly approval ID: {weekly_approval_id}",
        f"",
        f"  Employees: {employee_count} imported, {skipped_count} skipped",
    ] + log_lines

    db.log_audit(
        conn,
        action="import_payroll_pdf",
        entity_type="weekly_approvals",
        entity_id=weekly_approval_id,
        new_value=(
            f"week_ending={week_ending}, employees={employee_count}, "
            f"skipped={skipped_count}, source_file_id={source_file_id}"
        ),
    )

    return ImportResult(
        success=True,
        source_file_id=source_file_id,
        pay_period_id=pay_period_id,
        weekly_approval_id=weekly_approval_id,
        timesheet_import_id=None,
        employee_count=employee_count,
        skipped_count=skipped_count,
        warnings=warnings,
        errors=errors,
        extraction_log=extraction_log,
    )


# ---------------------------------------------------------------------------
# Travel PDF importer
# ---------------------------------------------------------------------------

def import_travel_pdf(
    conn: Any,
    pdf_path: str | Path,
    *,
    original_name: str | None = None,
    normalized_name: str | None = None,
) -> ImportResult:
    """Ingest a weekly travel hours PDF.

    The travel PDF date range (Sunday–Saturday) is detected from the PDF header.
    Mon–Sat hours are recorded against the weekly_approval for the Mon–Sun week
    that ends on saturday + 1 day.  The PDF's Sunday hours are applied back to
    the prior week's travel_hours record (current_sun_status → 'confirmed').

    Args:
        conn:            Open database connection.  Caller commits.
        pdf_path:        Path to the travel PDF.
        original_name:   Original incoming filename.
        normalized_name: Internal normalized filename.

    Returns:
        ImportResult
    """
    pdf_path = Path(pdf_path)
    errors: list[str] = []
    warnings: list[str] = []

    orig_name = original_name or pdf_path.name

    # 1. Store file
    try:
        source_file_id = db.store_source_file(
            conn,
            source_path=pdf_path,
            file_type="travel_pdf",
            original_name=orig_name,
            normalized_name=normalized_name,
        )
    except (FileNotFoundError, ValueError) as exc:
        return ImportResult(
            success=False,
            source_file_id=None,
            pay_period_id=None,
            weekly_approval_id=None,
            timesheet_import_id=None,
            employee_count=0,
            skipped_count=0,
            warnings=warnings,
            errors=[str(exc)],
        )

    # 2. Parse the PDF
    try:
        travel_rows, parse_warnings = travel_parser.parse_travel_pdf(pdf_path)
    except Exception as exc:
        errors.append(f"Travel PDF parse failed: {exc}")
        return ImportResult(
            success=False,
            source_file_id=source_file_id,
            pay_period_id=None,
            weekly_approval_id=None,
            timesheet_import_id=None,
            employee_count=0,
            skipped_count=0,
            warnings=warnings,
            errors=errors,
        )

    warnings.extend(parse_warnings)

    if not travel_rows:
        warnings.append("Travel PDF contained no R&D employee rows.")
        return ImportResult(
            success=True,
            source_file_id=source_file_id,
            pay_period_id=None,
            weekly_approval_id=None,
            timesheet_import_id=None,
            employee_count=0,
            skipped_count=0,
            warnings=warnings,
            errors=errors,
        )

    # 3. Derive week_ending from the parsed date fields
    #    All rows in one PDF share the same date range; use the first row.
    first_row = travel_rows[0]

    week_end_str   = first_row["week_end_date"]     # Saturday (e.g. "2026-03-28")
    pdf_sunday_str = first_row["pdf_sunday_date"]   # Sunday at start of PDF (e.g. "2026-03-22")

    if not week_end_str or not pdf_sunday_str:
        errors.append(
            "Travel PDF date range could not be determined.  "
            "Import aborted — check warnings for header parse details."
        )
        return ImportResult(
            success=False,
            source_file_id=source_file_id,
            pay_period_id=None,
            weekly_approval_id=None,
            timesheet_import_id=None,
            employee_count=0,
            skipped_count=0,
            warnings=warnings,
            errors=errors,
        )

    saturday_date  = date.fromisoformat(week_end_str)
    pdf_sunday     = date.fromisoformat(pdf_sunday_str)
    # Business week ending = the Sunday AFTER the Saturday in the travel PDF
    current_week_ending = saturday_date + timedelta(days=1)

    # 4. Resolve pay period and weekly approval for the current week
    pay_period_id, week_number = _find_or_create_pay_period(conn, current_week_ending)
    weekly_approval_id = _find_or_create_weekly_approval(
        conn,
        pay_period_id,
        week_number,
        current_week_ending,
        travel_pdf_file=normalized_name or orig_name,
    )

    # 5. Upsert travel_hours for each R&D employee
    employee_count = 0
    skipped_count  = 0
    log_lines: list[str] = []

    for row in travel_rows:
        raw_name = row["raw_name"]

        employee_id, emp_warnings = _resolve_employee(conn, raw_name, alias_type="travel_name")
        warnings.extend(emp_warnings)

        if employee_id is None:
            skipped_count += 1
            log_lines.append(f"  SKIP  {raw_name} — no employee match")
            continue

        # Sun_hours = the PDF Sunday, which belongs to the PRIOR week
        sun_hours          = row["sun_hours"]
        current_week_total = row["current_week_total"]   # Mon–Sat total

        conn.execute(
            """
            INSERT INTO travel_hours
                (weekly_approval_id, employee_id,
                 sun_hours, mon_hours, tue_hours, wed_hours, thu_hours, fri_hours, sat_hours,
                 current_week_total, prior_week_sun_applied, current_sun_status,
                 source_file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending_next_pdf', ?)
            ON CONFLICT(weekly_approval_id, employee_id) DO UPDATE SET
                sun_hours            = excluded.sun_hours,
                mon_hours            = excluded.mon_hours,
                tue_hours            = excluded.tue_hours,
                wed_hours            = excluded.wed_hours,
                thu_hours            = excluded.thu_hours,
                fri_hours            = excluded.fri_hours,
                sat_hours            = excluded.sat_hours,
                current_week_total   = excluded.current_week_total,
                source_file_id       = excluded.source_file_id
            """,
            (
                weekly_approval_id,
                employee_id,
                sun_hours,
                row["mon_hours"],
                row["tue_hours"],
                row["wed_hours"],
                row["thu_hours"],
                row["fri_hours"],
                row["sat_hours"],
                current_week_total,
                source_file_id,
            ),
        )

        # Mark prior_week_sun_applied on the current row if Sunday hours are non-zero
        sun_applied = False
        if sun_hours > 0:
            applied = _apply_travel_sunday_to_prior_week(
                conn, employee_id, sun_hours, pdf_sunday, source_file_id
            )
            if applied:
                conn.execute(
                    """
                    UPDATE travel_hours
                    SET prior_week_sun_applied = 1
                    WHERE weekly_approval_id = ? AND employee_id = ?
                    """,
                    (weekly_approval_id, employee_id),
                )
                sun_applied = True

        employee_count += 1
        emp_row = db.fetch_one(conn, "SELECT display_name FROM employees WHERE id = ?", (employee_id,))
        display = emp_row["display_name"] if emp_row else raw_name
        sun_note = ""
        if sun_hours > 0:
            sun_note = f"  Sun(prior)={sun_hours:.2f}h {'→ applied' if sun_applied else '→ no prior week found'}"
        log_lines.append(
            f"  OK    {raw_name} → {display}:"
            f"  Mon-Sat={current_week_total:.2f}h"
            + sun_note
        )

    period_row = db.fetch_one(conn, "SELECT period_start, period_end FROM pay_periods WHERE id = ?", (pay_period_id,))
    period_hdr = ""
    if period_row:
        period_hdr = f"  Period: {period_row['period_start']} – {period_row['period_end']}  (Week {week_number})"

    extraction_log = [
        f"Travel PDF: {orig_name}",
        f"  Date range: {pdf_sunday} (Sun) – {saturday_date} (Sat)",
        f"  Current week ending: {current_week_ending}",
        period_hdr,
        f"  Weekly approval ID: {weekly_approval_id}",
        f"",
        f"  Employees: {employee_count} imported, {skipped_count} skipped",
    ] + log_lines

    db.log_audit(
        conn,
        action="import_travel_pdf",
        entity_type="weekly_approvals",
        entity_id=weekly_approval_id,
        new_value=(
            f"week_ending={current_week_ending}, employees={employee_count}, "
            f"skipped={skipped_count}, source_file_id={source_file_id}"
        ),
    )

    return ImportResult(
        success=True,
        source_file_id=source_file_id,
        pay_period_id=pay_period_id,
        weekly_approval_id=weekly_approval_id,
        timesheet_import_id=None,
        employee_count=employee_count,
        skipped_count=skipped_count,
        warnings=warnings,
        errors=errors,
        extraction_log=extraction_log,
    )


# ---------------------------------------------------------------------------
# Timesheet importer
# ---------------------------------------------------------------------------

def import_timesheet(
    conn: Any,
    xlsx_path: str | Path,
    *,
    original_name: str | None = None,
    normalized_name: str | None = None,
    submission_method: str = "imported_file",
) -> ImportResult:
    """Ingest a biweekly employee timesheet workbook.

    Extracts daily labor rows and expense line items from the three tabs
    (Biweekly Time Sheet, Biweekly Expense Report CAD, Biweekly Expense Report USD).

    On re-import of the same employee/period:
      - timesheet_imports is updated in-place
      - timesheet_daily_hours rows are upserted (ON CONFLICT DO UPDATE)
      - timesheet_hours (biweekly totals) is upserted
      - expense_items are deleted and re-inserted
        NOTE: Once receipt linking is implemented, this delete-re-insert must be
        replaced with a reconciliation that preserves existing receipt associations.

    Args:
        conn:               Open database connection.  Caller commits.
        xlsx_path:          Path to the timesheet workbook.
        original_name:      Original incoming filename.
        normalized_name:    Internal normalized filename.
        submission_method:  One of: imported_file | edited_file | manual_attach

    Returns:
        ImportResult (weekly_approval_id will be None for timesheet imports)
    """
    xlsx_path = Path(xlsx_path)
    errors: list[str] = []
    warnings: list[str] = []

    orig_name = original_name or xlsx_path.name

    # 1. Store file
    try:
        source_file_id = db.store_source_file(
            conn,
            source_path=xlsx_path,
            file_type="timesheet",
            original_name=orig_name,
            normalized_name=normalized_name,
        )
    except (FileNotFoundError, ValueError) as exc:
        return ImportResult(
            success=False,
            source_file_id=None,
            pay_period_id=None,
            weekly_approval_id=None,
            timesheet_import_id=None,
            employee_count=0,
            skipped_count=0,
            warnings=warnings,
            errors=[str(exc)],
        )

    # 2. Extract timesheet data
    try:
        ts_data = timesheet_extractor_v2.extract_timesheet(xlsx_path)
    except Exception as exc:
        errors.append(f"Timesheet extraction failed: {exc}")
        return ImportResult(
            success=False,
            source_file_id=source_file_id,
            pay_period_id=None,
            weekly_approval_id=None,
            timesheet_import_id=None,
            employee_count=0,
            skipped_count=0,
            warnings=warnings,
            errors=errors,
        )

    warnings.extend(ts_data.get("warnings", []))

    # 3. Resolve employee
    # Timesheets use the employee's display name from cell H3.
    # Resolution order:
    #   a. Exact match on display_name alias
    #   b. Exact match on any alias type (catches travel_name = display name)
    #   c. Fuzzy match across all alias types (last resort, score >= 80)
    # Warnings are only emitted if the final resolution fails or uses a fuzzy match.
    employee_name = ts_data["employee_name"]

    # Step a — exact display_name alias
    emp = employee_manager.find_employee_by_alias(conn, employee_name, alias_type="display_name")
    if emp:
        employee_id = emp["id"]
    else:
        employee_id = None

        # Step b — exact match on any alias type
        emp = employee_manager.find_employee_by_alias(conn, employee_name, alias_type=None)
        if emp:
            employee_id = emp["id"]
        else:
            # Step c — fuzzy match across all alias types
            emp, score, is_ambiguous = employee_manager.fuzzy_find_employee(
                conn, employee_name, alias_type=None, min_score=80
            )
            if is_ambiguous:
                warnings.append(
                    f"Ambiguous match for {employee_name!r} (score={score}): "
                    "multiple candidates within 5 points — skipped."
                )
            elif emp:
                employee_id = emp["id"]
                warnings.append(
                    f"Fuzzy match: {employee_name!r} → {emp['display_name']!r} (score={score})"
                )
            else:
                warnings.append(
                    f"No employee match for {employee_name!r} — skipped."
                )

    if employee_id is None:
        errors.append(
            f"Employee {employee_name!r} could not be resolved.  "
            "Add the employee via the Employees page and re-import."
        )
        return ImportResult(
            success=False,
            source_file_id=source_file_id,
            pay_period_id=None,
            weekly_approval_id=None,
            timesheet_import_id=None,
            employee_count=0,
            skipped_count=1,
            warnings=warnings,
            errors=errors,
        )

    # 4. Resolve pay period from period_end
    # The extractor returns period_end as a date object (not a string)
    period_end = ts_data["period_end"]
    if isinstance(period_end, str):
        period_end = date.fromisoformat(period_end)
    pay_period_id = _find_or_create_pay_period_from_period_end(conn, period_end)

    # 5. Upsert timesheet_imports
    cursor = conn.execute(
        """
        INSERT INTO timesheet_imports
            (pay_period_id, employee_id, source_file_id, submission_method)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(pay_period_id, employee_id) DO UPDATE SET
            source_file_id    = excluded.source_file_id,
            submission_method = excluded.submission_method,
            imported_at       = CURRENT_TIMESTAMP
        """,
        (pay_period_id, employee_id, source_file_id, submission_method),
    )

    # Retrieve the timesheet_import_id (may have been updated, not inserted)
    ts_import_row = db.fetch_one(
        conn,
        "SELECT id FROM timesheet_imports WHERE pay_period_id = ? AND employee_id = ?",
        (pay_period_id, employee_id),
    )
    timesheet_import_id = ts_import_row["id"]

    # 6. Upsert timesheet_daily_hours
    daily_hours = ts_data.get("daily_hours", [])
    for day_row in daily_hours:
        # Extractor returns work_date as a date object; store as ISO string for SQLite
        work_date = day_row["work_date"]
        if work_date is None:
            # A row with no date is unusable; it was already flagged in extractor warnings
            continue
        work_date_str = str(work_date)

        conn.execute(
            """
            INSERT INTO timesheet_daily_hours
                (timesheet_import_id, employee_id, work_date,
                 reg_hours, ot1_hours, ot2_hours, drive_hours,
                 sick_hours, vacation_hours, holiday_hours, nonbillable_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(timesheet_import_id, work_date) DO UPDATE SET
                reg_hours         = excluded.reg_hours,
                ot1_hours         = excluded.ot1_hours,
                ot2_hours         = excluded.ot2_hours,
                drive_hours       = excluded.drive_hours,
                sick_hours        = excluded.sick_hours,
                vacation_hours    = excluded.vacation_hours,
                holiday_hours     = excluded.holiday_hours,
                nonbillable_hours = excluded.nonbillable_hours
            """,
            (
                timesheet_import_id,
                employee_id,
                work_date_str,
                day_row.get("reg_hours", 0.0),
                day_row.get("ot1_hours", 0.0),
                day_row.get("ot2_hours", 0.0),
                day_row.get("drive_hours", 0.0),
                day_row.get("sick_hours", 0.0),
                day_row.get("vacation_hours", 0.0),
                day_row.get("holiday_hours", 0.0),
                day_row.get("nonbillable_hours", 0.0),
            ),
        )

    # 7. Upsert timesheet_hours (biweekly totals)
    totals = ts_data.get("totals", {})
    conn.execute(
        """
        INSERT INTO timesheet_hours
            (pay_period_id, employee_id,
             reg_hours, ot1_hours, ot2_hours, drive_hours,
             sick_hours, vacation_hours, holiday_hours, nonbillable_hours,
             source_file_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pay_period_id, employee_id) DO UPDATE SET
            reg_hours        = excluded.reg_hours,
            ot1_hours        = excluded.ot1_hours,
            ot2_hours        = excluded.ot2_hours,
            drive_hours      = excluded.drive_hours,
            sick_hours       = excluded.sick_hours,
            vacation_hours   = excluded.vacation_hours,
            holiday_hours    = excluded.holiday_hours,
            nonbillable_hours = excluded.nonbillable_hours,
            source_file_id   = excluded.source_file_id,
            imported_at      = CURRENT_TIMESTAMP
        """,
        (
            pay_period_id,
            employee_id,
            totals.get("reg_hours", 0.0),
            totals.get("ot1_hours", 0.0),
            totals.get("ot2_hours", 0.0),
            totals.get("drive_hours", 0.0),
            totals.get("sick_hours", 0.0),
            totals.get("vacation_hours", 0.0),
            totals.get("holiday_hours", 0.0),
            totals.get("nonbillable_hours", 0.0),
            source_file_id,
        ),
    )

    # 8. Upsert expense_items
    #    Delete existing items and re-insert from latest extraction.
    #    Once receipt linking is implemented, replace this with a diff-based
    #    reconciliation that preserves expense_receipts associations.
    conn.execute(
        "DELETE FROM expense_items WHERE pay_period_id = ? AND employee_id = ?",
        (pay_period_id, employee_id),
    )

    expenses_cad = ts_data.get("expenses_cad", [])
    expenses_usd = ts_data.get("expenses_usd", [])

    for exp in expenses_cad:
        _insert_expense_item(conn, pay_period_id, employee_id, "CAD", exp, source_file_id)

    for exp in expenses_usd:
        _insert_expense_item(conn, pay_period_id, employee_id, "USD", exp, source_file_id)

    db.log_audit(
        conn,
        action="import_timesheet",
        entity_type="timesheet_imports",
        entity_id=timesheet_import_id,
        new_value=(
            f"employee={employee_name!r}, period_end={period_end}, "
            f"daily_rows={len(daily_hours)}, "
            f"expenses_cad={len(expenses_cad)}, expenses_usd={len(expenses_usd)}, "
            f"source_file_id={source_file_id}"
        ),
    )

    # Build extraction log
    period_row = db.fetch_one(conn, "SELECT period_start, period_end FROM pay_periods WHERE id = ?", (pay_period_id,))
    period_hdr = f"  Period: {period_row['period_start']} – {period_row['period_end']}" if period_row else ""

    emp_row = db.fetch_one(conn, "SELECT display_name FROM employees WHERE id = ?", (employee_id,))
    display_name = emp_row["display_name"] if emp_row else employee_name

    exp_cad_total = sum(float(e.get("amount", 0)) for e in expenses_cad)
    exp_usd_total = sum(float(e.get("amount", 0)) for e in expenses_usd)

    extraction_log = [
        f"Timesheet: {orig_name}",
        f"  Employee: {employee_name} → {display_name}",
        period_hdr,
        f"  Timesheet import ID: {timesheet_import_id}",
        f"",
        f"  Biweekly totals:",
        f"    REG={totals.get('reg_hours', 0.0):.2f}"
        f"  OT={totals.get('ot1_hours', 0.0):.2f}"
        f"  OT2={totals.get('ot2_hours', 0.0):.2f}"
        f"  Drive={totals.get('drive_hours', 0.0):.2f}",
        f"    Sick={totals.get('sick_hours', 0.0):.2f}"
        f"  Vacation={totals.get('vacation_hours', 0.0):.2f}"
        f"  Holiday={totals.get('holiday_hours', 0.0):.2f}",
        f"  Daily rows stored: {len(daily_hours)}",
    ]

    if expenses_cad:
        extraction_log.append(f"  Expenses CAD: {len(expenses_cad)} item(s)  total={exp_cad_total:.2f}")
        for e in expenses_cad:
            extraction_log.append(
                f"    {e.get('work_date') or 'undated':>10}  {e.get('category','?'):20}  {float(e.get('amount',0)):.2f}"
            )
    else:
        extraction_log.append("  Expenses CAD: none")

    if expenses_usd:
        extraction_log.append(f"  Expenses USD: {len(expenses_usd)} item(s)  total={exp_usd_total:.2f}")
        for e in expenses_usd:
            extraction_log.append(
                f"    {e.get('work_date') or 'undated':>10}  {e.get('category','?'):20}  {float(e.get('amount',0)):.2f}"
            )
    else:
        extraction_log.append("  Expenses USD: none")

    return ImportResult(
        success=True,
        source_file_id=source_file_id,
        pay_period_id=pay_period_id,
        weekly_approval_id=None,
        timesheet_import_id=timesheet_import_id,
        employee_count=1,
        skipped_count=0,
        warnings=warnings,
        errors=errors,
        extraction_log=extraction_log,
    )


# ---------------------------------------------------------------------------
# Expense item helper
# ---------------------------------------------------------------------------

def _insert_expense_item(
    conn: Any,
    pay_period_id: int,
    employee_id: int,
    currency: str,
    exp: dict,
    source_file_id: int,
) -> None:
    """Insert a single expense_items row from an extracted expense dict.

    The expense dict shape is the same as returned by timesheet_extractor_v2:
    {
        "date":        str (ISO) | None,
        "category":    str (canonical category name),
        "description": str | None,
        "amount":      float,
        "quantity":    float | None,
    }

    Receipt status and billing status are set automatically based on whether the
    category requires a receipt (config.PER_DIEM_CATEGORIES).

    Args:
        conn:           Open database connection.
        pay_period_id:  pay_periods.id
        employee_id:    employees.id
        currency:       "CAD" or "USD"
        exp:            Expense dict from the extractor.
        source_file_id: source_files.id of the originating timesheet.
    """
    category = exp.get("category", "")
    requires_receipt = category not in config.PER_DIEM_CATEGORIES

    if requires_receipt:
        receipt_status    = "missing"
        billing_status    = "blocked_missing_receipt"
        reimbursement_status = "submitted"
    else:
        receipt_status    = "not_required"
        billing_status    = "ready_for_billing"
        reimbursement_status = "ready_for_reimbursement"

    # Extractor returns work_date as a date object or None; convert to string for SQLite
    work_date = exp.get("work_date")
    work_date_str = str(work_date) if work_date is not None else None

    conn.execute(
        """
        INSERT INTO expense_items
            (pay_period_id, employee_id, work_date, currency, category,
             description, amount, quantity,
             requires_receipt, receipt_status,
             reimbursement_status, billing_status,
             source_file_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pay_period_id,
            employee_id,
            work_date_str,
            currency,
            category,
            exp.get("description"),
            exp.get("amount", 0.0),
            exp.get("quantity"),
            1 if requires_receipt else 0,
            receipt_status,
            reimbursement_status,
            billing_status,
            source_file_id,
        ),
    )
