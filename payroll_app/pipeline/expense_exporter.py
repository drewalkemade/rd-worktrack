"""
expense_exporter.py — Employee expense reimbursement export.

Replaces the manual staging workbook (2020_EmployeeExpenses.xlsx) with a
structured export that supports both per-employee summaries and full line-item
detail.

Context
-------
Employee expenses are NOT paid through payroll.  Each employee is also a
Sage 50 vendor, and expenses are reimbursed by a separate expense cheque
(no payroll taxes).  Reimbursement usually happens about 30 days after the
pay period ends.

The Sage 50 expense entry is practically one total per employee per period
(vendor bill entry), so the exported summary matches that workflow while
preserving full detail in the database.

Per-diem expenses never require a receipt.  All other expense categories
require a receipt before the expense can be either reimbursed or billed.

Receipt status states
---------------------
  not_required  — per-diem category; no receipt ever needed
  missing       — receipt required but not yet received
  received      — receipt on file

Reimbursement status states
---------------------------
  submitted             — extracted from timesheet; awaiting approval
  ready_for_reimbursement — receipt received (or not required); can be paid
  reimbursed            — expense cheque has been issued

Billing status states (for customer-billable expenses)
-------------------------------------------------------
  submitted               — extracted from timesheet
  blocked_missing_receipt — receipt required but missing
  ready_for_billing       — receipt on file (or not required)
  billed                  — included in customer invoice

Public entry points
-------------------
  get_expense_summary(conn, pay_period_id)
      Return per-employee expense totals for a period (CAD and USD separately).

  get_expense_detail(conn, pay_period_id, employee_id=None)
      Return full expense line items for a period, optionally filtered by employee.

  mark_receipt_received(conn, expense_item_id, *, source_file_id=None, note=None)
      Record that a receipt has been received for an expense item.
      Updates receipt_status → 'received' and billing/reimbursement statuses.

  mark_reimbursed(conn, pay_period_id, employee_id, *, currency, notes=None)
      Mark all ready_for_reimbursement expenses as reimbursed for an employee/period/currency.

  get_reimbursement_blocked(conn, pay_period_id)
      Return all expense items that are blocked (missing receipt) for a period.
"""

import dataclasses
from typing import Any

from payroll_app.database import db


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class EmployeeExpenseSummary:
    """Per-employee expense summary for one pay period."""
    employee_id:    int
    display_name:   str
    pay_period_id:  int
    period_start:   str
    period_end:     str
    # CAD totals by status
    cad_total:                  float
    cad_ready_for_reimburse:    float   # receipt received or not required
    cad_blocked_missing_receipt: float  # waiting on receipt
    cad_reimbursed:             float
    # USD totals by status
    usd_total:                  float
    usd_ready_for_reimburse:    float
    usd_blocked_missing_receipt: float
    usd_reimbursed:             float
    # Counts
    items_total:        int
    items_missing_receipt: int


@dataclasses.dataclass
class ExpenseLineItem:
    """Single expense line item."""
    id:                   int
    employee_id:          int
    display_name:         str
    pay_period_id:        int
    work_date:            str | None
    currency:             str
    category:             str
    description:          str | None
    amount:               float
    quantity:             float | None
    requires_receipt:     bool
    receipt_status:       str
    reimbursement_status: str
    billing_status:       str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_expense_summary(
    conn: Any,
    pay_period_id: int,
) -> list[EmployeeExpenseSummary]:
    """Return per-employee expense totals for a pay period.

    Results are sorted by employee display_name.

    Args:
        conn:           Open database connection.
        pay_period_id:  pay_periods.id

    Returns:
        List of EmployeeExpenseSummary, one per employee with expenses.
    """
    period = db.fetch_one(
        conn,
        "SELECT period_start, period_end FROM pay_periods WHERE id = ?",
        (pay_period_id,),
    )
    period_start = period["period_start"] if period else ""
    period_end   = period["period_end"]   if period else ""

    # Fetch all expense items for the period joined with employee names
    rows = db.fetch_all(
        conn,
        """
        SELECT ei.employee_id, e.display_name,
               ei.currency, ei.amount,
               ei.receipt_status, ei.reimbursement_status, ei.billing_status,
               ei.requires_receipt
        FROM expense_items ei
        JOIN employees e ON e.id = ei.employee_id
        WHERE ei.pay_period_id = ?
        ORDER BY e.display_name, ei.currency, ei.category
        """,
        (pay_period_id,),
    )

    # Group by employee
    employees: dict[int, dict] = {}
    for row in rows:
        eid = row["employee_id"]
        if eid not in employees:
            employees[eid] = {
                "display_name": row["display_name"],
                "cad": {"total": 0.0, "ready": 0.0, "blocked": 0.0, "reimbursed": 0.0},
                "usd": {"total": 0.0, "ready": 0.0, "blocked": 0.0, "reimbursed": 0.0},
                "items_total": 0,
                "items_missing": 0,
            }

        amount = float(row["amount"] or 0)
        currency = (row["currency"] or "CAD").upper()
        bucket = employees[eid]["cad"] if currency == "CAD" else employees[eid]["usd"]

        bucket["total"] += amount
        employees[eid]["items_total"] += 1

        if row["reimbursement_status"] == "reimbursed":
            bucket["reimbursed"] += amount
        elif row["receipt_status"] in ("not_required", "received"):
            bucket["ready"] += amount
        elif row["receipt_status"] == "missing":
            bucket["blocked"] += amount
            employees[eid]["items_missing"] += 1

    result: list[EmployeeExpenseSummary] = []
    for eid, data in employees.items():
        result.append(EmployeeExpenseSummary(
            employee_id   = eid,
            display_name  = data["display_name"],
            pay_period_id = pay_period_id,
            period_start  = period_start,
            period_end    = period_end,
            cad_total                   = data["cad"]["total"],
            cad_ready_for_reimburse     = data["cad"]["ready"],
            cad_blocked_missing_receipt = data["cad"]["blocked"],
            cad_reimbursed              = data["cad"]["reimbursed"],
            usd_total                   = data["usd"]["total"],
            usd_ready_for_reimburse     = data["usd"]["ready"],
            usd_blocked_missing_receipt = data["usd"]["blocked"],
            usd_reimbursed              = data["usd"]["reimbursed"],
            items_total                 = data["items_total"],
            items_missing_receipt       = data["items_missing"],
        ))

    result.sort(key=lambda s: s.display_name)
    return result


def get_expense_detail(
    conn: Any,
    pay_period_id: int,
    employee_id: int | None = None,
) -> list[ExpenseLineItem]:
    """Return full expense line items for a period.

    Args:
        conn:           Open database connection.
        pay_period_id:  pay_periods.id
        employee_id:    If provided, filter to one employee.

    Returns:
        List of ExpenseLineItem, sorted by employee name, work_date, category.
    """
    if employee_id is not None:
        rows = db.fetch_all(
            conn,
            """
            SELECT ei.*, e.display_name
            FROM expense_items ei
            JOIN employees e ON e.id = ei.employee_id
            WHERE ei.pay_period_id = ? AND ei.employee_id = ?
            ORDER BY e.display_name, ei.work_date, ei.category
            """,
            (pay_period_id, employee_id),
        )
    else:
        rows = db.fetch_all(
            conn,
            """
            SELECT ei.*, e.display_name
            FROM expense_items ei
            JOIN employees e ON e.id = ei.employee_id
            WHERE ei.pay_period_id = ?
            ORDER BY e.display_name, ei.work_date, ei.category
            """,
            (pay_period_id,),
        )

    return [
        ExpenseLineItem(
            id                   = row["id"],
            employee_id          = row["employee_id"],
            display_name         = row["display_name"],
            pay_period_id        = pay_period_id,
            work_date            = row["work_date"],
            currency             = row["currency"],
            category             = row["category"],
            description          = row["description"],
            amount               = float(row["amount"] or 0),
            quantity             = float(row["quantity"]) if row["quantity"] is not None else None,
            requires_receipt     = bool(row["requires_receipt"]),
            receipt_status       = row["receipt_status"],
            reimbursement_status = row["reimbursement_status"],
            billing_status       = row["billing_status"],
        )
        for row in rows
    ]


def mark_receipt_received(
    conn: Any,
    expense_item_id: int,
    *,
    source_file_id: int | None = None,
    note: str | None = None,
) -> None:
    """Record that a receipt has been received for an expense item.

    Updates:
      - receipt_status          → 'received'
      - reimbursement_status    → 'ready_for_reimbursement'  (if currently 'submitted')
      - billing_status          → 'ready_for_billing'        (if currently 'blocked_missing_receipt')

    Optionally links a source_file_id (the stored receipt file).

    Args:
        conn:             Open database connection.  Caller commits.
        expense_item_id:  expense_items.id
        source_file_id:   Optional source_files.id of the receipt file.
        note:             Optional note recorded in the audit log.

    Raises:
        ValueError if expense_item_id does not exist.
    """
    existing = db.fetch_one(
        conn,
        "SELECT * FROM expense_items WHERE id = ?",
        (expense_item_id,),
    )
    if not existing:
        raise ValueError(f"expense_item_id={expense_item_id} not found.")

    old_receipt_status = existing["receipt_status"]

    conn.execute(
        """
        UPDATE expense_items
        SET receipt_status          = 'received',
            reimbursement_status    = CASE
                WHEN reimbursement_status = 'submitted' THEN 'ready_for_reimbursement'
                ELSE reimbursement_status
            END,
            billing_status          = CASE
                WHEN billing_status = 'blocked_missing_receipt' THEN 'ready_for_billing'
                ELSE billing_status
            END,
            source_file_id          = COALESCE(?, source_file_id)
        WHERE id = ?
        """,
        (source_file_id, expense_item_id),
    )

    db.log_audit(
        conn,
        action="mark_receipt_received",
        entity_type="expense_items",
        entity_id=expense_item_id,
        old_value=f"receipt_status={old_receipt_status!r}",
        new_value=f"receipt_status='received' note={note!r}",
    )


def mark_reimbursed(
    conn: Any,
    pay_period_id: int,
    employee_id: int,
    *,
    currency: str,
    notes: str | None = None,
) -> int:
    """Mark all ready_for_reimbursement expenses as reimbursed for an employee/period/currency.

    Only updates rows where reimbursement_status = 'ready_for_reimbursement'.
    Items that are still missing receipts are not updated.

    Args:
        conn:           Open database connection.  Caller commits.
        pay_period_id:  pay_periods.id
        employee_id:    employees.id
        currency:       'CAD' or 'USD'
        notes:          Optional note for the audit log.

    Returns:
        Number of expense items marked as reimbursed.
    """
    rows = db.fetch_all(
        conn,
        """
        SELECT id FROM expense_items
        WHERE pay_period_id = ? AND employee_id = ? AND currency = ?
          AND reimbursement_status = 'ready_for_reimbursement'
        """,
        (pay_period_id, employee_id, currency.upper()),
    )

    for row in rows:
        conn.execute(
            "UPDATE expense_items SET reimbursement_status = 'reimbursed' WHERE id = ?",
            (row["id"],),
        )
        db.log_audit(
            conn,
            action="mark_reimbursed",
            entity_type="expense_items",
            entity_id=row["id"],
            old_value="ready_for_reimbursement",
            new_value=f"reimbursed notes={notes!r}",
        )

    return len(rows)


def get_reimbursement_blocked(
    conn: Any,
    pay_period_id: int,
) -> list[ExpenseLineItem]:
    """Return all expense items blocked due to missing receipts for a period.

    These items cannot be reimbursed or billed until a receipt is received.

    Args:
        conn:           Open database connection.
        pay_period_id:  pay_periods.id

    Returns:
        List of ExpenseLineItem where receipt_status = 'missing'.
    """
    rows = db.fetch_all(
        conn,
        """
        SELECT ei.*, e.display_name
        FROM expense_items ei
        JOIN employees e ON e.id = ei.employee_id
        WHERE ei.pay_period_id = ? AND ei.receipt_status = 'missing'
        ORDER BY e.display_name, ei.work_date, ei.category
        """,
        (pay_period_id,),
    )

    return [
        ExpenseLineItem(
            id                   = row["id"],
            employee_id          = row["employee_id"],
            display_name         = row["display_name"],
            pay_period_id        = pay_period_id,
            work_date            = row["work_date"],
            currency             = row["currency"],
            category             = row["category"],
            description          = row["description"],
            amount               = float(row["amount"] or 0),
            quantity             = float(row["quantity"]) if row["quantity"] is not None else None,
            requires_receipt     = bool(row["requires_receipt"]),
            receipt_status       = row["receipt_status"],
            reimbursement_status = row["reimbursement_status"],
            billing_status       = row["billing_status"],
        )
        for row in rows
    ]
