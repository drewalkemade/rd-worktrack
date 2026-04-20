"""
weekly_verifier.py — Per-employee, per-week comparison and verification state.

Replaces the manual brown/blue highlight logic in the RawData spreadsheet with
structured status records in weekly_employee_verification.

What it does
------------
For each employee in a given weekly_approval, this module:
  1. Reads the customer-approved hours for that week (from customer_hours and
     travel_hours).
  2. Reads the employee's submitted timesheet daily rows for the same 7-day span.
  3. Compares approved vs submitted hours and flags variances.
  4. Checks whether any non-per-diem expenses exist for that week.
  5. Populates (or updates) the weekly_employee_verification row with:
       - side-by-side approved vs timesheet values
       - needs_expense_review flag
       - simple_per_diem_count (number of per-diem expense days)
       - status = 'pending' | 'needs_review' | 'verified'
  6. Flags any Sunday travel situation that is still provisional.

The 'needs_review' status is assigned automatically when:
  - reg/ot/dbl hours mismatch between approved and timesheet
  - non-per-diem expenses are present (receipt situation unclear)
  - travel Sunday is provisional (pending next PDF)

The 'verified' status is set manually by the owner via the app.

Public entry points
-------------------
  run_weekly_verification(conn, weekly_approval_id)
      Compute and upsert verification rows for all employees in a weekly_approval.
      Returns a VerificationSummary.

  get_verification_status(conn, weekly_approval_id)
      Return all weekly_employee_verification rows for a given weekly_approval,
      enriched with employee display names.

  set_verified(conn, weekly_approval_id, employee_id, *, note=None)
      Mark a specific employee/week as manually verified by the owner.
"""

import dataclasses
from datetime import date, timedelta
from typing import Any

from payroll_app.database import db


# ---------------------------------------------------------------------------
# Hour comparison tolerance
# Approved hours are integer or half-hour increments; timesheet hours are
# decimal.  A 0.01-hour tolerance avoids floating-point noise.
# ---------------------------------------------------------------------------

_HOUR_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class EmployeeVerification:
    """Single employee/week verification snapshot."""
    employee_id:           int
    display_name:          str
    # Timesheet hours for this specific week (Mon–Sun span)
    timesheet_week_reg:          float
    timesheet_week_ot1:          float
    timesheet_week_ot2:          float
    timesheet_week_drive:        float
    timesheet_week_sick:         float
    timesheet_week_vacation:     float
    timesheet_week_holiday:      float
    timesheet_week_nonbillable:  float
    # Customer-approved hours for this week
    approved_reg:          float
    approved_ot:           float
    approved_dbl:          float
    approved_travel:       float   # Mon–Sat from travel_hours.current_week_total
    # Variance flags
    reg_variance:          float   # approved_reg  − timesheet_week_reg
    ot_variance:           float   # approved_ot   − timesheet_week_ot1
    dbl_variance:          float   # approved_dbl  − timesheet_week_ot2
    # Expense indicators
    needs_expense_review:  bool
    simple_per_diem_count: float   # total per-diem expense days this week
    extra_expense_note:    str | None
    # Sunday travel status for this week
    travel_sun_status:     str     # confirmed | pending_next_pdf | assumed_from_timesheet | n/a
    travel_sun_hours:      float   # confirmed or assumed Sunday travel hours
    # Overall status
    status:                str     # pending | needs_review | verified
    verified_at:           str | None


@dataclasses.dataclass
class VerificationSummary:
    """Summary of run_weekly_verification() results."""
    weekly_approval_id:     int
    week_ending:            date
    total_employees:        int
    needs_review_count:     int
    pending_count:          int
    verified_count:         int
    provisonal_sunday_count: int   # employees whose Sunday travel is still provisional
    warnings:               list[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _corrections_cover_all_variances(
    conn: Any,
    weekly_approval_id: int,
    employee_id: int,
    week_start: date,
    week_end: date,
    pay_period_id: int,
    has_timesheet: bool,
) -> bool:
    """Return True if every day-level variance for this employee/week has a
    resolved correction_log entry, meaning the owner has explicitly adjudicated
    every mismatch via the Resolve node.

    Also returns True if there are no day-level mismatches at all (e.g. an
    employee who appears in approved hours but had zero activity both sides).
    """
    # Approved daily hours for this employee this week
    approved_rows = db.fetch_all(conn, """
        SELECT work_date, total_hours
        FROM customer_daily_hours
        WHERE weekly_approval_id = ? AND employee_id = ?
          AND work_date BETWEEN ? AND ?
    """, (weekly_approval_id, employee_id, str(week_start), str(week_end)))

    # Per-day travel hours from travel PDF (mon_hours–sat_hours + confirmed Sunday).
    # Subtracted from approved total before comparing to timesheet labor.
    travel_row = db.fetch_one(conn, """
        SELECT mon_hours, tue_hours, wed_hours, thu_hours, fri_hours, sat_hours,
               current_sun_hours_assumed, current_sun_status
        FROM travel_hours
        WHERE weekly_approval_id = ? AND employee_id = ?
    """, (weekly_approval_id, employee_id))

    travel_by_date: dict = {}
    if travel_row:
        _day_cols = [
            ("mon_hours", 0), ("tue_hours", 1), ("wed_hours", 2),
            ("thu_hours", 3), ("fri_hours", 4), ("sat_hours", 5),
        ]
        for col, offset in _day_cols:
            d = str(week_start + timedelta(days=offset))
            travel_by_date[d] = float(travel_row[col] or 0)
        sun_status = travel_row["current_sun_status"] or "pending_next_pdf"
        if sun_status in ("confirmed", "assumed_from_timesheet"):
            travel_by_date[str(week_end)] = float(travel_row["current_sun_hours_assumed"] or 0)

    # Timesheet daily labor hours only — drive_hours excluded because the approved
    # total from the payroll PDF already includes travel (subtracted separately above).
    ts_rows = db.fetch_all(conn, """
        SELECT tdh.work_date,
               COALESCE(tdh.reg_hours, 0) + COALESCE(tdh.ot1_hours, 0)
               + COALESCE(tdh.ot2_hours, 0)
               AS work_hours
        FROM timesheet_daily_hours tdh
        JOIN timesheet_imports ti ON ti.id = tdh.timesheet_import_id
        WHERE ti.pay_period_id = ? AND ti.employee_id = ?
          AND tdh.work_date BETWEEN ? AND ?
    """, (pay_period_id, employee_id, str(week_start), str(week_end)))

    ts_map       = {r["work_date"]: float(r["work_hours"] or 0) for r in ts_rows}
    # approved_map: labor only (raw PDF total minus per-day travel)
    approved_map = {
        r["work_date"]: max(0.0, float(r["total_hours"] or 0) - travel_by_date.get(r["work_date"], 0.0))
        for r in approved_rows
    }

    mismatched: set[str] = set()

    # Approved days that differ from timesheet
    for work_date, app_hrs in approved_map.items():
        ts_hrs = ts_map.get(work_date, 0.0)
        if abs(app_hrs - ts_hrs) > _HOUR_TOLERANCE:
            mismatched.add(work_date)

    # Timesheet-only days (not in approved) — only relevant when employee has a timesheet
    if has_timesheet:
        for work_date, ts_hrs in ts_map.items():
            if work_date not in approved_map and ts_hrs > _HOUR_TOLERANCE:
                mismatched.add(work_date)

    if not mismatched:
        return True

    resolved_rows = db.fetch_all(conn, """
        SELECT work_date FROM correction_log
        WHERE weekly_approval_id = ? AND employee_id = ? AND status = 'resolved'
    """, (weekly_approval_id, employee_id))
    resolved_dates = {r["work_date"] for r in resolved_rows}

    return mismatched.issubset(resolved_dates)


def _week_date_range(week_ending: date) -> tuple[date, date]:
    """Return (week_start, week_end) for a Mon–Sun business week.

    Args:
        week_ending: The Sunday that ends the week.

    Returns:
        (monday_date, sunday_date)
    """
    week_start = week_ending - timedelta(days=6)
    return week_start, week_ending


def _sum_timesheet_hours_for_week(
    conn: Any,
    employee_id: int,
    pay_period_id: int,
    week_start: date,
    week_end: date,
) -> dict[str, float]:
    """Sum timesheet daily hours for a specific Mon–Sun week.

    Looks up the timesheet_import for (pay_period_id, employee_id), then
    sums timesheet_daily_hours rows where work_date falls in [week_start, week_end].

    Returns a dict with keys: reg, ot1, ot2, drive, sick, vacation, holiday,
    nonbillable (zero for all if no timesheet found).
    """
    empty = {
        "reg": 0.0, "ot1": 0.0, "ot2": 0.0, "drive": 0.0,
        "sick": 0.0, "vacation": 0.0, "holiday": 0.0, "nonbillable": 0.0,
    }

    ts_import = db.fetch_one(
        conn,
        "SELECT id FROM timesheet_imports WHERE pay_period_id = ? AND employee_id = ?",
        (pay_period_id, employee_id),
    )
    if not ts_import:
        return empty

    rows = db.fetch_all(
        conn,
        """
        SELECT reg_hours, ot1_hours, ot2_hours, drive_hours,
               sick_hours, vacation_hours, holiday_hours, nonbillable_hours
        FROM timesheet_daily_hours
        WHERE timesheet_import_id = ?
          AND work_date BETWEEN ? AND ?
        """,
        (ts_import["id"], str(week_start), str(week_end)),
    )

    return {
        "reg":         sum(r["reg_hours"]         for r in rows),
        "ot1":         sum(r["ot1_hours"]         for r in rows),
        "ot2":         sum(r["ot2_hours"]         for r in rows),
        "drive":       sum(r["drive_hours"]       for r in rows),
        "sick":        sum(r["sick_hours"]        for r in rows),
        "vacation":    sum(r["vacation_hours"]    for r in rows),
        "holiday":     sum(r["holiday_hours"]     for r in rows),
        "nonbillable": sum(r["nonbillable_hours"] for r in rows),
    }


def _get_approved_hours(
    conn: Any,
    weekly_approval_id: int,
    employee_id: int,
) -> dict[str, float]:
    """Return approved labor hours for a given weekly_approval/employee pair.

    Returns: {"reg": ..., "ot": ..., "dbl": ...} (zero if no record).
    """
    row = db.fetch_one(
        conn,
        "SELECT reg_hours, ot_hours, dbl_hours FROM customer_hours WHERE weekly_approval_id = ? AND employee_id = ?",
        (weekly_approval_id, employee_id),
    )
    if not row:
        return {"reg": 0.0, "ot": 0.0, "dbl": 0.0}
    return {
        "reg": float(row["reg_hours"] or 0),
        "ot":  float(row["ot_hours"]  or 0),
        "dbl": float(row["dbl_hours"] or 0),
    }


def _get_travel_hours(
    conn: Any,
    weekly_approval_id: int,
    employee_id: int,
) -> tuple[float, str, float]:
    """Return travel hours and Sunday status for a given weekly_approval/employee.

    Returns:
        (current_week_total, current_sun_status, current_sun_hours)
        current_week_total: Mon–Sat travel hours for this week.
        current_sun_status: confirmed | pending_next_pdf | assumed_from_timesheet | n/a
        current_sun_hours:  Confirmed or assumed Sunday travel hours (0 if n/a).
    """
    row = db.fetch_one(
        conn,
        """
        SELECT current_week_total, current_sun_status, current_sun_hours_assumed
        FROM travel_hours
        WHERE weekly_approval_id = ? AND employee_id = ?
        """,
        (weekly_approval_id, employee_id),
    )
    if not row:
        return 0.0, "n/a", 0.0

    return (
        float(row["current_week_total"] or 0),
        row["current_sun_status"] or "n/a",
        float(row["current_sun_hours_assumed"] or 0),
    )


def _get_expense_summary_for_week(
    conn: Any,
    employee_id: int,
    pay_period_id: int,
    week_start: date,
    week_end: date,
) -> tuple[bool, float, str | None]:
    """Return expense indicators for a specific employee/week.

    Looks at expense_items for the employee/period where work_date falls in the
    Mon–Sun window.

    Returns:
        (needs_expense_review, per_diem_count, extra_expense_note)
        needs_expense_review: True if any non-per-diem expense items exist for this week.
        per_diem_count:       Sum of per-diem expense amounts (as a day count proxy).
        extra_expense_note:   Short description of non-per-diem categories present, or None.
    """
    rows = db.fetch_all(
        conn,
        """
        SELECT category, amount, requires_receipt, receipt_status
        FROM expense_items
        WHERE pay_period_id = ?
          AND employee_id = ?
          AND (work_date IS NULL OR (work_date BETWEEN ? AND ?))
        """,
        (pay_period_id, employee_id, str(week_start), str(week_end)),
    )

    per_diem_categories = {"per_diem_travel", "per_diem_full"}
    per_diem_total = 0.0
    non_per_diem_categories: set[str] = set()

    for row in rows:
        if row["category"] in per_diem_categories:
            # Treat each per-diem expense row as 1 day (amount is the per-diem rate)
            per_diem_total += 1.0
        elif row["amount"] and float(row["amount"]) > 0:
            # Only flag if the receipt is still missing (not received or deferred)
            status = row["receipt_status"] or "missing"
            if status not in ("received", "deferred"):
                non_per_diem_categories.add(row["category"])

    needs_review = len(non_per_diem_categories) > 0
    extra_note = (
        "Non-per-diem expenses: " + ", ".join(sorted(non_per_diem_categories))
        if needs_review else None
    )

    return needs_review, per_diem_total, extra_note


def _determine_status(
    reg_variance: float,
    ot_variance: float,
    dbl_variance: float,
    needs_expense_review: bool,
    sun_status: str,
    has_timesheet: bool,
) -> str:
    """Determine the auto-computed verification status.

    Returns 'needs_review' if any of:
      - reg/ot/dbl approved vs timesheet mismatch beyond tolerance
      - non-per-diem expenses exist
      - travel Sunday is provisional

    Returns 'pending' otherwise (owner must still confirm).
    Note: 'verified' is only ever set manually by the owner.
    """
    if not has_timesheet:
        # No timesheet submitted — the week is effectively unverifiable automatically;
        # flag it so the owner can note whether this is expected (e.g. no-show week).
        return "needs_review"

    if (
        abs(reg_variance) > _HOUR_TOLERANCE
        or abs(ot_variance) > _HOUR_TOLERANCE
        or abs(dbl_variance) > _HOUR_TOLERANCE
    ):
        return "needs_review"

    if needs_expense_review:
        return "needs_review"

    if sun_status == "pending_next_pdf":
        return "needs_review"

    return "pending"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_weekly_verification(
    conn: Any,
    weekly_approval_id: int,
) -> VerificationSummary:
    """Compute and upsert weekly_employee_verification rows for all employees
    in a weekly_approval.

    For each employee who has either customer_hours OR a timesheet for this
    period, a verification row is computed and stored.  The status is set
    automatically to 'pending' or 'needs_review'; it becomes 'verified' only
    when the owner manually confirms it.

    If a verification row already exists for an employee/week, it is updated
    unless its status is already 'verified' — verified rows are never
    automatically downgraded.

    Args:
        conn:                Open database connection.  Caller commits.
        weekly_approval_id:  weekly_approvals.id to verify.

    Returns:
        VerificationSummary
    """
    warnings: list[str] = []

    wa = db.fetch_one(
        conn,
        "SELECT * FROM weekly_approvals WHERE id = ?",
        (weekly_approval_id,),
    )
    if not wa:
        return VerificationSummary(
            weekly_approval_id=weekly_approval_id,
            week_ending=date.today(),
            total_employees=0,
            needs_review_count=0,
            pending_count=0,
            verified_count=0,
            provisonal_sunday_count=0,
            warnings=[f"weekly_approval_id={weekly_approval_id} not found."],
        )

    week_ending   = date.fromisoformat(wa["week_ending"])
    pay_period_id = wa["pay_period_id"]
    week_start, week_end = _week_date_range(week_ending)

    # Collect all employee IDs relevant to this week:
    # - Any employee with approved customer hours
    # - Any employee with a timesheet import for the pay period
    employee_ids_from_approved = {
        row["employee_id"]
        for row in db.fetch_all(
            conn,
            "SELECT DISTINCT employee_id FROM customer_hours WHERE weekly_approval_id = ?",
            (weekly_approval_id,),
        )
    }
    employee_ids_from_timesheets = {
        row["employee_id"]
        for row in db.fetch_all(
            conn,
            "SELECT DISTINCT employee_id FROM timesheet_imports WHERE pay_period_id = ?",
            (pay_period_id,),
        )
    }

    all_employee_ids = employee_ids_from_approved | employee_ids_from_timesheets

    if not all_employee_ids:
        warnings.append(
            f"No employees found for weekly_approval_id={weekly_approval_id}.  "
            "Import payroll PDFs and timesheets before running verification."
        )
        return VerificationSummary(
            weekly_approval_id=weekly_approval_id,
            week_ending=week_ending,
            total_employees=0,
            needs_review_count=0,
            pending_count=0,
            verified_count=0,
            provisonal_sunday_count=0,
            warnings=warnings,
        )

    needs_review_count    = 0
    pending_count         = 0
    verified_count        = 0
    provisional_sun_count = 0

    for employee_id in sorted(all_employee_ids):

        # Existing verification row (if any)
        existing = db.fetch_one(
            conn,
            "SELECT id, status FROM weekly_employee_verification WHERE weekly_approval_id = ? AND employee_id = ?",
            (weekly_approval_id, employee_id),
        )
        # Never downgrade a manually-verified row
        if existing and existing["status"] == "verified":
            verified_count += 1
            continue

        # --- Approved hours ---
        approved = _get_approved_hours(conn, weekly_approval_id, employee_id)

        # --- Travel hours ---
        travel_total, sun_status, sun_hours = _get_travel_hours(
            conn, weekly_approval_id, employee_id
        )

        # --- Timesheet hours for this specific week ---
        has_timesheet = db.fetch_one(
            conn,
            "SELECT id FROM timesheet_imports WHERE pay_period_id = ? AND employee_id = ?",
            (pay_period_id, employee_id),
        ) is not None

        ts_hours = _sum_timesheet_hours_for_week(
            conn, employee_id, pay_period_id, week_start, week_end
        )

        # --- Expense summary for this week ---
        needs_exp_review, per_diem_count, extra_note = _get_expense_summary_for_week(
            conn, employee_id, pay_period_id, week_start, week_end
        )

        # --- Variances ---
        reg_variance = approved["reg"] - ts_hours["reg"]
        ot_variance  = approved["ot"]  - ts_hours["ot1"]
        dbl_variance = approved["dbl"] - ts_hours["ot2"]

        # --- Status ---
        status = _determine_status(
            reg_variance, ot_variance, dbl_variance,
            needs_exp_review, sun_status, has_timesheet,
        )

        # If the only reason for needs_review is hour variances (not expense
        # review or provisional Sunday), check whether the owner has resolved
        # every mismatched day via the Resolve node.  If so, treat as pending.
        if (
            status == "needs_review"
            and not needs_exp_review
            and sun_status != "pending_next_pdf"
        ):
            if _corrections_cover_all_variances(
                conn, weekly_approval_id, employee_id,
                week_start, week_end, pay_period_id, has_timesheet,
            ):
                status = "pending"

        # --- Upsert verification row ---
        conn.execute(
            """
            INSERT INTO weekly_employee_verification
                (weekly_approval_id, employee_id,
                 timesheet_week_reg, timesheet_week_ot1, timesheet_week_ot2, timesheet_week_drive,
                 approved_reg, approved_ot, approved_dbl, approved_travel,
                 needs_expense_review, simple_per_diem_count, extra_expense_note,
                 status,
                 timesheet_week_sick, timesheet_week_vacation,
                 timesheet_week_holiday, timesheet_week_nonbillable)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(weekly_approval_id, employee_id) DO UPDATE SET
                timesheet_week_reg         = excluded.timesheet_week_reg,
                timesheet_week_ot1         = excluded.timesheet_week_ot1,
                timesheet_week_ot2         = excluded.timesheet_week_ot2,
                timesheet_week_drive       = excluded.timesheet_week_drive,
                approved_reg               = excluded.approved_reg,
                approved_ot                = excluded.approved_ot,
                approved_dbl               = excluded.approved_dbl,
                approved_travel            = excluded.approved_travel,
                needs_expense_review       = excluded.needs_expense_review,
                simple_per_diem_count      = excluded.simple_per_diem_count,
                extra_expense_note         = excluded.extra_expense_note,
                status                     = excluded.status,
                timesheet_week_sick        = excluded.timesheet_week_sick,
                timesheet_week_vacation    = excluded.timesheet_week_vacation,
                timesheet_week_holiday     = excluded.timesheet_week_holiday,
                timesheet_week_nonbillable = excluded.timesheet_week_nonbillable
            """,
            (
                weekly_approval_id,
                employee_id,
                ts_hours["reg"],
                ts_hours["ot1"],
                ts_hours["ot2"],
                ts_hours["drive"],
                approved["reg"],
                approved["ot"],
                approved["dbl"],
                travel_total,
                1 if needs_exp_review else 0,
                per_diem_count,
                extra_note,
                status,
                ts_hours["sick"],
                ts_hours["vacation"],
                ts_hours["holiday"],
                ts_hours["nonbillable"],
            ),
        )

        if status == "needs_review":
            needs_review_count += 1
        else:
            pending_count += 1

        if sun_status == "pending_next_pdf":
            provisional_sun_count += 1

    db.log_audit(
        conn,
        action="run_weekly_verification",
        entity_type="weekly_approvals",
        entity_id=weekly_approval_id,
        new_value=(
            f"week_ending={week_ending}, total={len(all_employee_ids)}, "
            f"needs_review={needs_review_count}, pending={pending_count}, "
            f"provisional_sun={provisional_sun_count}"
        ),
    )

    return VerificationSummary(
        weekly_approval_id=weekly_approval_id,
        week_ending=week_ending,
        total_employees=len(all_employee_ids),
        needs_review_count=needs_review_count,
        pending_count=pending_count,
        verified_count=verified_count,
        provisonal_sunday_count=provisional_sun_count,
        warnings=warnings,
    )


def get_verification_status(
    conn: Any,
    weekly_approval_id: int,
) -> list[EmployeeVerification]:
    """Return all verification rows for a weekly_approval, enriched with display names.

    Args:
        conn:                Open database connection.
        weekly_approval_id:  weekly_approvals.id

    Returns:
        List of EmployeeVerification dataclasses, sorted by employee display_name.
    """
    rows = db.fetch_all(
        conn,
        """
        SELECT v.*, e.display_name
        FROM weekly_employee_verification v
        JOIN employees e ON e.id = v.employee_id
        WHERE v.weekly_approval_id = ?
        ORDER BY e.display_name
        """,
        (weekly_approval_id,),
    )

    # For Sunday status, enrich from travel_hours
    wa = db.fetch_one(conn, "SELECT pay_period_id FROM weekly_approvals WHERE id = ?", (weekly_approval_id,))

    result: list[EmployeeVerification] = []
    for row in rows:
        _, sun_status, sun_hours = _get_travel_hours(
            conn, weekly_approval_id, row["employee_id"]
        )

        approved_ot  = float(row["approved_ot"]  or 0)
        ts_ot1       = float(row["timesheet_week_ot1"] or 0)
        approved_dbl = float(row["approved_dbl"]  or 0)
        ts_ot2       = float(row["timesheet_week_ot2"] or 0)

        result.append(EmployeeVerification(
            employee_id                = row["employee_id"],
            display_name               = row["display_name"],
            timesheet_week_reg         = float(row["timesheet_week_reg"]         or 0),
            timesheet_week_ot1         = float(row["timesheet_week_ot1"]         or 0),
            timesheet_week_ot2         = float(row["timesheet_week_ot2"]         or 0),
            timesheet_week_drive       = float(row["timesheet_week_drive"]       or 0),
            timesheet_week_sick        = float(row["timesheet_week_sick"]        or 0),
            timesheet_week_vacation    = float(row["timesheet_week_vacation"]    or 0),
            timesheet_week_holiday     = float(row["timesheet_week_holiday"]     or 0),
            timesheet_week_nonbillable = float(row["timesheet_week_nonbillable"] or 0),
            approved_reg               = float(row["approved_reg"]               or 0),
            approved_ot                = approved_ot,
            approved_dbl               = approved_dbl,
            approved_travel            = float(row["approved_travel"]            or 0),
            reg_variance               = float(row["approved_reg"] or 0) - float(row["timesheet_week_reg"] or 0),
            ot_variance                = approved_ot  - ts_ot1,
            dbl_variance               = approved_dbl - ts_ot2,
            needs_expense_review       = bool(row["needs_expense_review"]),
            simple_per_diem_count      = float(row["simple_per_diem_count"]      or 0),
            extra_expense_note         = row["extra_expense_note"],
            travel_sun_status          = sun_status,
            travel_sun_hours           = sun_hours,
            status                     = row["status"],
            verified_at                = row["verified_at"],
        ))

    return result


def assume_travel_from_timesheet(
    conn: Any,
    weekly_approval_id: int,
    employee_id: int,
    *,
    note: str | None = None,
) -> None:
    """Record that travel hours for this employee/week are assumed from their timesheet.

    Used when Centerline does not provide a travel PDF for the week.  The
    employee's timesheet drive hours become the travel total for reconciliation
    purposes.  Sets current_sun_status = 'assumed_from_timesheet' on the
    travel_hours row (creating a skeleton row if none exists).

    Non-Sunday drive hours (Mon–Sat) are copied from the timesheet to
    current_week_total.  The owner must supply a note explaining why no travel
    PDF was available.

    Args:
        conn:                Open database connection.  Caller commits.
        weekly_approval_id:  weekly_approvals.id
        employee_id:         employees.id
        note:                Required — reason travel PDF was not available.

    Raises:
        ValueError if the weekly_approval or employee does not exist, or if
        the employee has no timesheet drive hours to draw from.
    """
    if not note or not note.strip():
        raise ValueError("A note is required when assuming travel from timesheet.")

    wa = db.fetch_one(
        conn,
        "SELECT id, pay_period_id, week_ending FROM weekly_approvals WHERE id = ?",
        (weekly_approval_id,),
    )
    if not wa:
        raise ValueError(f"weekly_approval_id={weekly_approval_id} not found.")

    pay_period_id = wa["pay_period_id"]
    week_ending   = date.fromisoformat(wa["week_ending"])
    week_start, week_end = _week_date_range(week_ending)

    # Sum timesheet drive hours for this Mon–Sun window
    ts_import = db.fetch_one(
        conn,
        "SELECT id FROM timesheet_imports WHERE pay_period_id = ? AND employee_id = ?",
        (pay_period_id, employee_id),
    )
    if not ts_import:
        raise ValueError(
            f"No timesheet found for employee_id={employee_id}, "
            f"pay_period_id={pay_period_id}.  Cannot assume travel from timesheet."
        )

    drive_rows = db.fetch_all(
        conn,
        """
        SELECT work_date, drive_hours
        FROM timesheet_daily_hours
        WHERE timesheet_import_id = ?
          AND work_date BETWEEN ? AND ?
          AND drive_hours > 0
        """,
        (ts_import["id"], str(week_start), str(week_end)),
    )

    # Separate Sunday from Mon–Sat
    sun_date = str(week_end)     # week_end IS the Sunday
    mon_sat_total = 0.0
    sun_total     = 0.0
    for row in drive_rows:
        if row["work_date"] == sun_date:
            sun_total += float(row["drive_hours"] or 0)
        else:
            mon_sat_total += float(row["drive_hours"] or 0)

    if mon_sat_total == 0.0 and sun_total == 0.0:
        raise ValueError(
            f"Employee id={employee_id} has no drive hours in their timesheet "
            f"for week {week_start} – {week_end}."
        )

    sun_status = "assumed_from_timesheet" if sun_total > 0 else "n/a"
    full_note  = f"Assumed from timesheet (no travel PDF available). {note.strip()}"

    existing = db.fetch_one(
        conn,
        "SELECT id FROM travel_hours WHERE weekly_approval_id = ? AND employee_id = ?",
        (weekly_approval_id, employee_id),
    )

    if existing:
        conn.execute(
            """
            UPDATE travel_hours
            SET current_week_total        = ?,
                current_sun_status        = ?,
                current_sun_hours_assumed = ?,
                current_sun_note          = ?
            WHERE id = ?
            """,
            (mon_sat_total, sun_status, sun_total, full_note, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO travel_hours
                (weekly_approval_id, employee_id,
                 current_week_total, current_sun_status,
                 current_sun_hours_assumed, current_sun_note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (weekly_approval_id, employee_id,
             mon_sat_total, sun_status, sun_total, full_note),
        )

    db.log_audit(
        conn,
        action="assume_travel_from_timesheet",
        entity_type="travel_hours",
        entity_id=existing["id"] if existing else None,
        new_value=(
            f"employee_id={employee_id}, wa_id={weekly_approval_id}, "
            f"mon_sat={mon_sat_total}, sun={sun_total}, status={sun_status!r}, "
            f"note={note!r}"
        ),
    )


def set_verified(
    conn: Any,
    weekly_approval_id: int,
    employee_id: int,
    *,
    note: str | None = None,
) -> None:
    """Mark an employee/week as manually verified by the owner.

    Sets status = 'verified' and records verified_at timestamp.
    An optional note is appended to extra_expense_note.

    This is the only way status ever becomes 'verified' — it is never set
    automatically.

    Args:
        conn:                Open database connection.  Caller commits.
        weekly_approval_id:  weekly_approvals.id
        employee_id:         employees.id
        note:                Optional owner note (appended to extra_expense_note).
    """
    existing = db.fetch_one(
        conn,
        "SELECT id, extra_expense_note FROM weekly_employee_verification WHERE weekly_approval_id = ? AND employee_id = ?",
        (weekly_approval_id, employee_id),
    )

    if not existing:
        raise ValueError(
            f"No verification row for weekly_approval_id={weekly_approval_id}, "
            f"employee_id={employee_id}.  Run run_weekly_verification() first."
        )

    combined_note = existing["extra_expense_note"]
    if note:
        if combined_note:
            combined_note = f"{combined_note} | Owner: {note}"
        else:
            combined_note = f"Owner: {note}"

    conn.execute(
        """
        UPDATE weekly_employee_verification
        SET status = 'verified', verified_at = CURRENT_TIMESTAMP, extra_expense_note = ?
        WHERE id = ?
        """,
        (combined_note, existing["id"]),
    )

    db.log_audit(
        conn,
        action="set_verified",
        entity_type="weekly_employee_verification",
        entity_id=existing["id"],
        old_value="pending_or_needs_review",
        new_value=f"verified note={note!r}",
    )
