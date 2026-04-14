"""
receipt_ingest.py — Receipt file ingestion and normalisation.

Receipts arrive as arbitrary files with arbitrary filenames (photos, PDFs,
screenshots).  This module normalises them to a consistent naming convention,
copies them into the receipt store, and links them to the relevant expense_items
row.

Normalised filename convention
-------------------------------
  <EMPLOYEE>_<CATEGORY>_<DATE>.<ext>

  Examples:
    DTRIF_lodging_2026-03-24.jpg
    FMOLDOVAN_car_rental_2026-03-18.pdf
    JJEREMIAS_tolls_2026-03-20.png

  Rules:
    - EMPLOYEE: employee expense code if set, else first-initial + last-name
                in uppercase (e.g. "Daniel Trif" → "DTRIF")
    - CATEGORY: canonical expense category (e.g. "lodging", "car_rental")
    - DATE: ISO date of the expense (YYYY-MM-DD), or 'undated' if unknown
    - Extension: lowercased original extension

Receipt linking
---------------
A receipt is linked to one expense_items row.  Once linked:
  - expense_items.receipt_status → 'received'
  - expense_items.reimbursement_status → 'ready_for_reimbursement' (if was 'submitted')
  - expense_items.billing_status → 'ready_for_billing' (if was 'blocked_missing_receipt')

Public entry points
-------------------
  ingest_receipt(conn, receipt_path, expense_item_id, *, original_name=None)
      Copy the receipt into the store, normalise the filename, link to the
      expense item, and update receipt/billing/reimbursement statuses.
      Returns an IngestReceiptResult.

  suggest_normalized_name(display_name, category, work_date, original_ext)
      Return a suggested normalised filename (no file I/O).

  get_receipts_for_period(conn, pay_period_id, employee_id=None)
      Return all expense_receipts rows for a period, optionally filtered.
"""

import dataclasses
import re
from pathlib import Path
from typing import Any

from payroll_app.database import db
from payroll_app.pipeline.expense_exporter import mark_receipt_received


# ---------------------------------------------------------------------------
# Name normalisation helpers
# ---------------------------------------------------------------------------

def _employee_prefix(display_name: str, expense_code: str | None = None) -> str:
    """Return a short uppercase employee prefix for the receipt filename.

    Uses expense_code if set (e.g. "DTRIF"), otherwise derives first-initial +
    last-name from display_name (e.g. "Daniel Trif" → "DTRIF").

    Args:
        display_name:  Employee's display name (e.g. "Daniel Trif").
        expense_code:  Employee's expense_code from the DB, if any.

    Returns:
        Uppercase string suitable for use in a filename.
    """
    if expense_code:
        return re.sub(r"[^A-Z0-9]", "", expense_code.upper())

    # Derive from display_name: first initial + last name
    parts = display_name.strip().split()
    if len(parts) >= 2:
        prefix = parts[0][0] + parts[-1]
    elif parts:
        prefix = parts[0]
    else:
        prefix = "UNKNOWN"

    return re.sub(r"[^A-Z0-9]", "", prefix.upper())


def suggest_normalized_name(
    display_name: str,
    category: str,
    work_date: str | None,
    original_ext: str,
    *,
    expense_code: str | None = None,
) -> str:
    """Return a suggested normalised receipt filename.

    Args:
        display_name:  Employee display name (e.g. "Daniel Trif").
        category:      Canonical expense category (e.g. "lodging").
        work_date:     ISO date string (e.g. "2026-03-24"), or None.
        original_ext:  File extension including dot (e.g. ".jpg").
        expense_code:  Optional expense code override.

    Returns:
        Normalised filename string (no directory path).
    """
    prefix   = _employee_prefix(display_name, expense_code)
    cat_slug = re.sub(r"[^a-z0-9_]", "_", category.lower())
    date_str = work_date or "undated"
    ext      = original_ext.lower().lstrip(".")

    return f"{prefix}_{cat_slug}_{date_str}.{ext}"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class IngestReceiptResult:
    """Result of ingest_receipt()."""
    success:           bool
    source_file_id:    int | None
    expense_item_id:   int
    normalized_name:   str | None
    stored_path:       str | None
    warnings:          list[str]
    errors:            list[str]


@dataclasses.dataclass
class ReceiptRecord:
    """Single expense_receipts row enriched with expense and employee details."""
    receipt_id:          int
    expense_item_id:     int
    employee_id:         int
    display_name:        str
    category:            str
    work_date:           str | None
    currency:            str
    amount:              float
    original_filename:   str
    normalized_filename: str | None
    stored_path:         str
    receipt_status:      str
    billing_status:      str
    reimbursement_status: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_receipt(
    conn: Any,
    receipt_path: str | Path,
    expense_item_id: int,
    *,
    original_name: str | None = None,
) -> IngestReceiptResult:
    """Ingest a receipt file: copy, normalise, store, and link to an expense item.

    Steps:
      1. Validate the expense_item_id exists.
      2. Derive a normalised filename from the employee name, category, and date.
      3. Copy the receipt into config.RECEIPT_DIR via db.store_source_file().
      4. Insert an expense_receipts row.
      5. Call mark_receipt_received() to update expense item statuses.

    Args:
        conn:             Open database connection.  Caller commits.
        receipt_path:     Path to the receipt file on disk.
        expense_item_id:  expense_items.id to link this receipt to.
        original_name:    Original filename (defaults to receipt_path.name).

    Returns:
        IngestReceiptResult
    """
    receipt_path = Path(receipt_path)
    warnings:  list[str] = []
    errors:    list[str] = []

    if not receipt_path.exists():
        return IngestReceiptResult(
            success=False,
            source_file_id=None,
            expense_item_id=expense_item_id,
            normalized_name=None,
            stored_path=None,
            warnings=warnings,
            errors=[f"Receipt file not found: {receipt_path}"],
        )

    orig_name = original_name or receipt_path.name

    # Validate expense item and fetch employee info for naming
    expense_row = db.fetch_one(
        conn,
        """
        SELECT ei.*, e.display_name, e.expense_code
        FROM expense_items ei
        JOIN employees e ON e.id = ei.employee_id
        WHERE ei.id = ?
        """,
        (expense_item_id,),
    )
    if not expense_row:
        return IngestReceiptResult(
            success=False,
            source_file_id=None,
            expense_item_id=expense_item_id,
            normalized_name=None,
            stored_path=None,
            warnings=warnings,
            errors=[f"expense_item_id={expense_item_id} not found."],
        )

    if not expense_row["requires_receipt"]:
        warnings.append(
            f"expense_item_id={expense_item_id} (category={expense_row['category']!r}) "
            "does not require a receipt, but one is being attached anyway."
        )

    # Build normalised name
    normalized_name = suggest_normalized_name(
        display_name = expense_row["display_name"],
        category     = expense_row["category"],
        work_date    = expense_row["work_date"],
        original_ext = receipt_path.suffix,
        expense_code = expense_row["expense_code"],
    )

    # Store the file
    try:
        source_file_id = db.store_source_file(
            conn,
            source_path    = receipt_path,
            file_type      = "receipt",
            original_name  = orig_name,
            normalized_name= normalized_name,
        )
    except (FileNotFoundError, ValueError) as exc:
        return IngestReceiptResult(
            success=False,
            source_file_id=None,
            expense_item_id=expense_item_id,
            normalized_name=normalized_name,
            stored_path=None,
            warnings=warnings,
            errors=[str(exc)],
        )

    # Determine stored path
    stored_row = db.fetch_one(conn, "SELECT path FROM source_files WHERE id = ?", (source_file_id,))
    stored_path = stored_row["path"] if stored_row else None

    # Insert expense_receipts row
    conn.execute(
        """
        INSERT INTO expense_receipts
            (expense_item_id, source_file_id, original_filename, normalized_filename, stored_path, sha256)
        SELECT ?, ?, ?, ?, ?, sha256
        FROM source_files WHERE id = ?
        """,
        (expense_item_id, source_file_id, orig_name, normalized_name, stored_path, source_file_id),
    )

    # Update expense item statuses
    mark_receipt_received(conn, expense_item_id, source_file_id=source_file_id)

    db.log_audit(
        conn,
        action="ingest_receipt",
        entity_type="expense_receipts",
        entity_id=expense_item_id,
        new_value=(
            f"original={orig_name!r}, normalized={normalized_name!r}, "
            f"source_file_id={source_file_id}"
        ),
    )

    return IngestReceiptResult(
        success=True,
        source_file_id=source_file_id,
        expense_item_id=expense_item_id,
        normalized_name=normalized_name,
        stored_path=stored_path,
        warnings=warnings,
        errors=errors,
    )


def get_receipts_for_period(
    conn: Any,
    pay_period_id: int,
    employee_id: int | None = None,
) -> list[ReceiptRecord]:
    """Return all receipt records for a pay period, optionally filtered by employee.

    Args:
        conn:           Open database connection.
        pay_period_id:  pay_periods.id
        employee_id:    If provided, filter to one employee.

    Returns:
        List of ReceiptRecord, sorted by employee name, work_date.
    """
    if employee_id is not None:
        rows = db.fetch_all(
            conn,
            """
            SELECT er.*,
                   ei.employee_id, ei.category, ei.work_date, ei.currency,
                   ei.amount, ei.receipt_status, ei.billing_status, ei.reimbursement_status,
                   e.display_name
            FROM expense_receipts er
            JOIN expense_items ei ON ei.id = er.expense_item_id
            JOIN employees e ON e.id = ei.employee_id
            WHERE ei.pay_period_id = ? AND ei.employee_id = ?
            ORDER BY e.display_name, ei.work_date
            """,
            (pay_period_id, employee_id),
        )
    else:
        rows = db.fetch_all(
            conn,
            """
            SELECT er.*,
                   ei.employee_id, ei.category, ei.work_date, ei.currency,
                   ei.amount, ei.receipt_status, ei.billing_status, ei.reimbursement_status,
                   e.display_name
            FROM expense_receipts er
            JOIN expense_items ei ON ei.id = er.expense_item_id
            JOIN employees e ON e.id = ei.employee_id
            WHERE ei.pay_period_id = ?
            ORDER BY e.display_name, ei.work_date
            """,
            (pay_period_id,),
        )

    return [
        ReceiptRecord(
            receipt_id           = row["id"],
            expense_item_id      = row["expense_item_id"],
            employee_id          = row["employee_id"],
            display_name         = row["display_name"],
            category             = row["category"],
            work_date            = row["work_date"],
            currency             = row["currency"],
            amount               = float(row["amount"] or 0),
            original_filename    = row["original_filename"],
            normalized_filename  = row["normalized_filename"],
            stored_path          = row["stored_path"],
            receipt_status       = row["receipt_status"],
            billing_status       = row["billing_status"],
            reimbursement_status = row["reimbursement_status"],
        )
        for row in rows
    ]
