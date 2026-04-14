"""
reconciler.py — Biweekly payroll reconciliation.

Runs after both weekly_approvals for a pay period are in and their
weekly_employee_verification rows are complete.

What it does
------------
For each employee in the pay period, this module:
  1. Sums the customer-approved hours across both weeks (week1 + week2).
  2. Reads the employee's biweekly timesheet totals.
  3. Compares approved vs submitted for reg, ot, dbl, and drive hours.
  4. Computes `final_*` values — initially equal to the approved hours (the
     customer's approval is authoritative for billable employees).
  5. Stores a reconciliation row with ts_*, cust_*, and final_* values.
  6. Sets status = 'pending' | 'variance' | 'approved'.

Status rules
------------
  pending    — no variance detected, ready for the owner to approve
  variance   — approved vs submitted hours differ beyond tolerance;
               requires owner review before period can be exported
  approved   — owner has manually approved the final values (required before
               the cheque run can be written or the period exported)
  exported   — the period has been exported to the payroll workbook and Sage 50

Internal employees
------------------
Employees with assignment_type = 'internal' bypass customer approval entirely.
For them:
  - cust_* values are all 0
  - final_* values come directly from the timesheet totals
  - There is no approval requirement for the hours themselves (no customer
    sign-off), but the owner still needs to approve before export

Blocking rules
--------------
  run_reconciliation() raises ReconciliationBlockedError if:
    - Either weekly_approval for the period has unverified employees
      (status = 'pending' or 'needs_review' in weekly_employee_verification)
    - Unless force=True is passed (for re-running after manual fixes)

Public entry points
-------------------
  run_reconciliation(conn, pay_period_id, *, force=False)
      Compute and upsert reconciliation rows for all employees in the period.
      Returns a ReconciliationSummary.

  get_reconciliation(conn, pay_period_id)
      Return all reconciliation rows for a period, enriched with names.

  approve_reconciliation(conn, pay_period_id, employee_id, *, notes=None, approved_by=None)
      Mark a specific employee's reconciliation row as approved.

  approve_all(conn, pay_period_id, *, notes=None, approved_by=None)
      Approve all non-variance rows for the period.
"""

import dataclasses
from typing import Any

from payroll_app import config
from payroll_app.database import db


# ---------------------------------------------------------------------------
# Hour comparison tolerance
# ---------------------------------------------------------------------------

_HOUR_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ReconciliationBlockedError(Exception):
    """Raised when reconciliation cannot run because weekly verification is incomplete."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class EmployeeReconciliation:
    """Single employee biweekly reconciliation snapshot."""
    employee_id:    int
    display_name:   str
    assignment_type: str         # billable | internal
    # Timesheet-submitted totals (biweekly)
    ts_reg:         float
    ts_ot:          float
    ts_dbl:         float
    ts_drive:       float
    # Customer-approved totals (sum of both weeks)
    cust_reg:       float
    cust_ot:        float
    cust_dbl:       float
    cust_drive:     float        # approved travel for the period
    # Final values used for payroll
    final_reg:      float
    final_ot:       float
    final_dbl:      float
    final_drive:    float
    # Variances (approved − submitted)
    reg_variance:   float
    ot_variance:    float
    dbl_variance:   float
    drive_variance: float
    # State
    status:         str          # pending | variance | approved | exported
    notes:          str | None
    approved_by:    str | None
    approved_at:    str | None


@dataclasses.dataclass
class ReconciliationSummary:
    """Summary of run_reconciliation() results."""
    pay_period_id:   int
    period_start:    str
    period_end:      str
    total_employees: int
    variance_count:  int
    pending_count:   int
    approved_count:  int
    warnings:        list[str]


# ---------------------------------------------------------------------------
# Blocking check
# ---------------------------------------------------------------------------

def _check_verification_complete(conn: Any, pay_period_id: int) -> list[str]:
    """Return a list of blocking reasons if weekly verification is incomplete.

    Returns an empty list if all employees across both weekly_approvals are
    either verified or have no pending/needs_review rows.
    """
    blocks: list[str] = []

    weekly_approvals = db.fetch_all(
        conn,
        "SELECT id, week_ending, week_number FROM weekly_approvals WHERE pay_period_id = ?",
        (pay_period_id,),
    )

    for wa in weekly_approvals:
        unverified = db.fetch_all(
            conn,
            """
            SELECT wev.employee_id, e.display_name, wev.status
            FROM weekly_employee_verification wev
            JOIN employees e ON e.id = wev.employee_id
            WHERE wev.weekly_approval_id = ?
              AND wev.status IN ('pending', 'needs_review')
            """,
            (wa["id"],),
        )
        for row in unverified:
            blocks.append(
                f"Week {wa['week_number']} (ending {wa['week_ending']}): "
                f"{row['display_name']} has unverified status={row['status']!r}."
            )

    return blocks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sum_approved_hours(
    conn: Any,
    pay_period_id: int,
    employee_id: int,
) -> dict[str, float]:
    """Sum customer_hours across both weekly_approvals for the period.

    Returns: {"reg": ..., "ot": ..., "dbl": ...}
    """
    rows = db.fetch_all(
        conn,
        """
        SELECT ch.reg_hours, ch.ot_hours, ch.dbl_hours
        FROM customer_hours ch
        JOIN weekly_approvals wa ON wa.id = ch.weekly_approval_id
        WHERE wa.pay_period_id = ? AND ch.employee_id = ?
        """,
        (pay_period_id, employee_id),
    )
    return {
        "reg": sum(float(r["reg_hours"] or 0) for r in rows),
        "ot":  sum(float(r["ot_hours"]  or 0) for r in rows),
        "dbl": sum(float(r["dbl_hours"] or 0) for r in rows),
    }


def _sum_approved_travel(
    conn: Any,
    pay_period_id: int,
    employee_id: int,
) -> float:
    """Sum confirmed travel hours (Mon–Sat per week) across both weekly_approvals."""
    rows = db.fetch_all(
        conn,
        """
        SELECT th.current_week_total
        FROM travel_hours th
        JOIN weekly_approvals wa ON wa.id = th.weekly_approval_id
        WHERE wa.pay_period_id = ? AND th.employee_id = ?
        """,
        (pay_period_id, employee_id),
    )
    return sum(float(r["current_week_total"] or 0) for r in rows)


def _get_timesheet_totals(
    conn: Any,
    pay_period_id: int,
    employee_id: int,
) -> dict[str, float]:
    """Return biweekly timesheet totals for an employee/period.

    Returns: {"reg": ..., "ot": ..., "dbl": ..., "drive": ...} (zero if no timesheet).
    """
    row = db.fetch_one(
        conn,
        """
        SELECT reg_hours, ot1_hours, ot2_hours, drive_hours
        FROM timesheet_hours
        WHERE pay_period_id = ? AND employee_id = ?
        """,
        (pay_period_id, employee_id),
    )
    if not row:
        return {"reg": 0.0, "ot": 0.0, "dbl": 0.0, "drive": 0.0}
    return {
        "reg":   float(row["reg_hours"]  or 0),
        "ot":    float(row["ot1_hours"]  or 0),
        "dbl":   float(row["ot2_hours"]  or 0),   # OT2 maps to payroll double-time
        "drive": float(row["drive_hours"] or 0),
    }


def _get_assignment_type(conn: Any, employee_id: int, period_end: str) -> str:
    """Return the employee's assignment type effective on period_end.

    Returns "billable" or "internal" (defaults to "billable" if no record).
    """
    row = db.fetch_one(
        conn,
        """
        SELECT assignment_type
        FROM employee_assignments
        WHERE employee_id = ?
          AND effective_start <= ?
          AND (effective_end IS NULL OR effective_end >= ?)
        ORDER BY effective_start DESC
        LIMIT 1
        """,
        (employee_id, period_end, period_end),
    )
    return row["assignment_type"] if row else "billable"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_reconciliation(
    conn: Any,
    pay_period_id: int,
    *,
    force: bool = False,
) -> ReconciliationSummary:
    """Compute and upsert reconciliation rows for all employees in the pay period.

    Blocking:
        Raises ReconciliationBlockedError if any weekly_employee_verification rows
        are still in 'pending' or 'needs_review' status, unless force=True.

    Final values:
        For billable employees: final_* = approved (customer approval is authoritative).
        For internal employees: final_* = timesheet totals (no customer approval).

    Status assignment:
        variance  — approved vs timesheet differs beyond tolerance (billable only)
        pending   — values agree; waiting for owner to explicitly approve
        approved  — only set manually via approve_reconciliation()

    An existing row is updated unless its status is 'approved' or 'exported'.
    Approved/exported rows are never automatically overwritten.

    Args:
        conn:           Open database connection.  Caller commits.
        pay_period_id:  pay_periods.id
        force:          Skip the blocking check (use for manual re-runs after fixes).

    Returns:
        ReconciliationSummary

    Raises:
        ReconciliationBlockedError
        ValueError if pay_period_id does not exist
    """
    warnings: list[str] = []

    period = db.fetch_one(
        conn,
        "SELECT * FROM pay_periods WHERE id = ?",
        (pay_period_id,),
    )
    if not period:
        raise ValueError(f"pay_period_id={pay_period_id} not found.")

    period_start = period["period_start"]
    period_end   = period["period_end"]

    # Blocking check
    if not force:
        blocks = _check_verification_complete(conn, pay_period_id)
        if blocks:
            raise ReconciliationBlockedError(
                "Weekly verification incomplete.  Resolve the following before reconciling:\n"
                + "\n".join(f"  • {b}" for b in blocks)
            )

    # Collect all employee IDs:
    # - approved hours (customer_hours across both weeks)
    # - submitted timesheets
    employee_ids_approved = {
        row["employee_id"]
        for row in db.fetch_all(
            conn,
            """
            SELECT DISTINCT ch.employee_id
            FROM customer_hours ch
            JOIN weekly_approvals wa ON wa.id = ch.weekly_approval_id
            WHERE wa.pay_period_id = ?
            """,
            (pay_period_id,),
        )
    }
    employee_ids_timesheets = {
        row["employee_id"]
        for row in db.fetch_all(
            conn,
            "SELECT DISTINCT employee_id FROM timesheet_imports WHERE pay_period_id = ?",
            (pay_period_id,),
        )
    }

    all_employee_ids = employee_ids_approved | employee_ids_timesheets

    variance_count  = 0
    pending_count   = 0
    approved_count  = 0

    for employee_id in sorted(all_employee_ids):

        # Skip already-approved or exported rows unless force=True
        existing = db.fetch_one(
            conn,
            "SELECT id, status FROM reconciliation WHERE pay_period_id = ? AND employee_id = ?",
            (pay_period_id, employee_id),
        )
        if existing and existing["status"] in ("approved", "exported") and not force:
            if existing["status"] == "approved":
                approved_count += 1
            continue

        assignment_type = _get_assignment_type(conn, employee_id, period_end)

        ts    = _get_timesheet_totals(conn, pay_period_id, employee_id)
        cust  = _sum_approved_hours(conn, pay_period_id, employee_id)
        cust_drive = _sum_approved_travel(conn, pay_period_id, employee_id)

        if assignment_type == config.ASSIGNMENT_INTERNAL:
            # Internal employees: final values = timesheet (no customer sign-off)
            final_reg   = ts["reg"]
            final_ot    = ts["ot"]
            final_dbl   = ts["dbl"]
            final_drive = ts["drive"]
            # No customer approval requirement → use 0 for cust_* display
            cust = {"reg": 0.0, "ot": 0.0, "dbl": 0.0}
            cust_drive  = 0.0
        else:
            # Billable employees: final values = customer-approved
            final_reg   = cust["reg"]
            final_ot    = cust["ot"]
            final_dbl   = cust["dbl"]
            final_drive = cust_drive

        # Variance check (billable only — compare approved vs submitted)
        has_variance = False
        if assignment_type != config.ASSIGNMENT_INTERNAL:
            has_variance = (
                abs(cust["reg"]  - ts["reg"])   > _HOUR_TOLERANCE
                or abs(cust["ot"]   - ts["ot"])    > _HOUR_TOLERANCE
                or abs(cust["dbl"]  - ts["dbl"])   > _HOUR_TOLERANCE
            )
            if not ts and any(v > 0 for v in cust.values()):
                # Approved hours but no timesheet submitted
                has_variance = True
                warnings.append(
                    f"Employee id={employee_id}: approved hours but no timesheet found."
                )

        status = "variance" if has_variance else "pending"

        conn.execute(
            """
            INSERT INTO reconciliation
                (pay_period_id, employee_id,
                 ts_reg, ts_ot, ts_dbl, ts_drive,
                 cust_reg, cust_ot, cust_dbl, cust_drive,
                 final_reg, final_ot, final_dbl, final_drive,
                 status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pay_period_id, employee_id) DO UPDATE SET
                ts_reg      = excluded.ts_reg,
                ts_ot       = excluded.ts_ot,
                ts_dbl      = excluded.ts_dbl,
                ts_drive    = excluded.ts_drive,
                cust_reg    = excluded.cust_reg,
                cust_ot     = excluded.cust_ot,
                cust_dbl    = excluded.cust_dbl,
                cust_drive  = excluded.cust_drive,
                final_reg   = excluded.final_reg,
                final_ot    = excluded.final_ot,
                final_dbl   = excluded.final_dbl,
                final_drive = excluded.final_drive,
                status      = excluded.status
            """,
            (
                pay_period_id, employee_id,
                ts["reg"],  ts["ot"],  ts["dbl"],  ts["drive"],
                cust["reg"], cust["ot"], cust["dbl"], cust_drive,
                final_reg, final_ot, final_dbl, final_drive,
                status,
            ),
        )

        if status == "variance":
            variance_count += 1
        else:
            pending_count += 1

    db.log_audit(
        conn,
        action="run_reconciliation",
        entity_type="pay_periods",
        entity_id=pay_period_id,
        new_value=(
            f"period={period_start}/{period_end}, total={len(all_employee_ids)}, "
            f"variance={variance_count}, pending={pending_count}, force={force}"
        ),
    )

    return ReconciliationSummary(
        pay_period_id=pay_period_id,
        period_start=period_start,
        period_end=period_end,
        total_employees=len(all_employee_ids),
        variance_count=variance_count,
        pending_count=pending_count,
        approved_count=approved_count,
        warnings=warnings,
    )


def get_reconciliation(
    conn: Any,
    pay_period_id: int,
) -> list[EmployeeReconciliation]:
    """Return all reconciliation rows for a period, enriched with employee info.

    Args:
        conn:           Open database connection.
        pay_period_id:  pay_periods.id

    Returns:
        List of EmployeeReconciliation dataclasses, sorted by display_name.
    """
    rows = db.fetch_all(
        conn,
        """
        SELECT r.*, e.display_name
        FROM reconciliation r
        JOIN employees e ON e.id = r.employee_id
        WHERE r.pay_period_id = ?
        ORDER BY e.display_name
        """,
        (pay_period_id,),
    )

    period = db.fetch_one(conn, "SELECT period_end FROM pay_periods WHERE id = ?", (pay_period_id,))
    period_end = period["period_end"] if period else ""

    result: list[EmployeeReconciliation] = []
    for row in rows:
        assignment_type = _get_assignment_type(conn, row["employee_id"], period_end)

        ts_reg  = float(row["ts_reg"]   or 0)
        ts_ot   = float(row["ts_ot"]    or 0)
        ts_dbl  = float(row["ts_dbl"]   or 0)
        ts_drv  = float(row["ts_drive"] or 0)
        cu_reg  = float(row["cust_reg"]   or 0)
        cu_ot   = float(row["cust_ot"]    or 0)
        cu_dbl  = float(row["cust_dbl"]   or 0)
        cu_drv  = float(row["cust_drive"] or 0)

        result.append(EmployeeReconciliation(
            employee_id    = row["employee_id"],
            display_name   = row["display_name"],
            assignment_type= assignment_type,
            ts_reg         = ts_reg,
            ts_ot          = ts_ot,
            ts_dbl         = ts_dbl,
            ts_drive       = ts_drv,
            cust_reg       = cu_reg,
            cust_ot        = cu_ot,
            cust_dbl       = cu_dbl,
            cust_drive     = cu_drv,
            final_reg      = float(row["final_reg"]   or 0),
            final_ot       = float(row["final_ot"]    or 0),
            final_dbl      = float(row["final_dbl"]   or 0),
            final_drive    = float(row["final_drive"] or 0),
            reg_variance   = cu_reg - ts_reg,
            ot_variance    = cu_ot  - ts_ot,
            dbl_variance   = cu_dbl - ts_dbl,
            drive_variance = cu_drv - ts_drv,
            status         = row["status"],
            notes          = row["notes"],
            approved_by    = row["approved_by"],
            approved_at    = row["approved_at"],
        ))

    return result


def approve_reconciliation(
    conn: Any,
    pay_period_id: int,
    employee_id: int,
    *,
    notes: str | None = None,
    approved_by: str | None = None,
) -> None:
    """Mark a specific employee's reconciliation row as approved.

    This is required before the cheque run can be written for this employee.
    Approval records who approved and when.

    Args:
        conn:           Open database connection.  Caller commits.
        pay_period_id:  pay_periods.id
        employee_id:    employees.id
        notes:          Optional context note.
        approved_by:    Name or identifier of the approver.

    Raises:
        ValueError if no reconciliation row exists for this employee/period.
    """
    existing = db.fetch_one(
        conn,
        "SELECT id FROM reconciliation WHERE pay_period_id = ? AND employee_id = ?",
        (pay_period_id, employee_id),
    )
    if not existing:
        raise ValueError(
            f"No reconciliation row for pay_period_id={pay_period_id}, employee_id={employee_id}. "
            "Run run_reconciliation() first."
        )

    conn.execute(
        """
        UPDATE reconciliation
        SET status = 'approved', notes = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (notes, approved_by, existing["id"]),
    )

    db.log_audit(
        conn,
        action="approve_reconciliation",
        entity_type="reconciliation",
        entity_id=existing["id"],
        new_value=f"approved_by={approved_by!r}, notes={notes!r}",
    )


def approve_all(
    conn: Any,
    pay_period_id: int,
    *,
    notes: str | None = None,
    approved_by: str | None = None,
) -> int:
    """Approve all non-variance reconciliation rows for the period.

    Rows with status = 'variance' are not approved by this function — each
    variance must be individually reviewed and approved.

    Args:
        conn:           Open database connection.  Caller commits.
        pay_period_id:  pay_periods.id
        notes:          Applied to all rows approved here.
        approved_by:    Name/identifier of the approver.

    Returns:
        Number of rows approved.
    """
    pending_rows = db.fetch_all(
        conn,
        "SELECT id, employee_id FROM reconciliation WHERE pay_period_id = ? AND status = 'pending'",
        (pay_period_id,),
    )

    for row in pending_rows:
        approve_reconciliation(
            conn,
            pay_period_id,
            row["employee_id"],
            notes=notes,
            approved_by=approved_by,
        )

    return len(pending_rows)
