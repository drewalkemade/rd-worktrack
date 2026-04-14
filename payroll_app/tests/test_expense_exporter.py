"""
test_expense_exporter.py — Tests for pipeline/expense_exporter.py.
"""

import sqlite3
from pathlib import Path

import pytest

from payroll_app import config
from payroll_app.database import db, employee_manager
from payroll_app.pipeline.importer import import_timesheet
from payroll_app.pipeline.expense_exporter import (
    get_expense_summary,
    get_expense_detail,
    mark_receipt_received,
    mark_reimbursed,
    get_reimbursement_blocked,
    EmployeeExpenseSummary,
    ExpenseLineItem,
)

FIXTURES = Path(__file__).parent / "fixtures"
TRIF_TS = FIXTURES / "DTrifTS_17_20260329.xlsx"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SOURCE_FILES_DIR", tmp_path)
    monkeypatch.setattr(config, "PAYROLL_PDF_DIR",  tmp_path / "payroll_pdfs")
    monkeypatch.setattr(config, "TRAVEL_PDF_DIR",   tmp_path / "travel_pdfs")
    monkeypatch.setattr(config, "TIMESHEET_DIR",    tmp_path / "timesheets")
    monkeypatch.setattr(config, "RECEIPT_DIR",      tmp_path / "receipts")

    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    db.initialize_database(c)
    employee_manager.seed_employees(c)
    yield c
    c.close()


@pytest.fixture()
def imported_period(conn):
    """Import Trif's timesheet and return (conn, pay_period_id, employee_id)."""
    result = import_timesheet(conn, TRIF_TS)
    emp_id = db.fetch_one(conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'")["id"]
    return conn, result.pay_period_id, emp_id


class TestGetExpenseSummary:

    def test_returns_summaries(self, imported_period):
        conn, pay_period_id, _ = imported_period
        summaries = get_expense_summary(conn, pay_period_id)
        assert len(summaries) >= 1
        assert all(isinstance(s, EmployeeExpenseSummary) for s in summaries)

    def test_trif_has_expenses(self, imported_period):
        conn, pay_period_id, _ = imported_period
        summaries = get_expense_summary(conn, pay_period_id)
        trif = next((s for s in summaries if "Trif" in s.display_name), None)
        assert trif is not None
        assert trif.items_total >= 1

    def test_cad_total_positive(self, imported_period):
        conn, pay_period_id, _ = imported_period
        summaries = get_expense_summary(conn, pay_period_id)
        trif = next((s for s in summaries if "Trif" in s.display_name), None)
        if trif:
            assert trif.cad_total >= 0.0

    def test_sorted_by_display_name(self, imported_period):
        conn, pay_period_id, _ = imported_period
        summaries = get_expense_summary(conn, pay_period_id)
        names = [s.display_name for s in summaries]
        assert names == sorted(names)

    def test_empty_period_returns_empty(self, conn):
        conn.execute(
            "INSERT INTO pay_periods (period_start, period_end, week1_ending, week2_ending) VALUES ('2020-01-06', '2020-01-19', '2020-01-12', '2020-01-19')"
        )
        pid = db.fetch_one(conn, "SELECT last_insert_rowid() AS id")["id"]
        summaries = get_expense_summary(conn, pid)
        assert summaries == []


class TestGetExpenseDetail:

    def test_returns_line_items(self, imported_period):
        conn, pay_period_id, _ = imported_period
        items = get_expense_detail(conn, pay_period_id)
        assert len(items) >= 1
        assert all(isinstance(i, ExpenseLineItem) for i in items)

    def test_filtered_by_employee(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        items = get_expense_detail(conn, pay_period_id, employee_id=emp_id)
        assert all(i.employee_id == emp_id for i in items)

    def test_per_diem_has_not_required_receipt_status(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        items = get_expense_detail(conn, pay_period_id, employee_id=emp_id)
        per_diem = [i for i in items if i.category in ("per_diem_travel", "per_diem_full")]
        for item in per_diem:
            assert item.receipt_status == "not_required"
            assert item.requires_receipt is False

    def test_non_per_diem_has_missing_receipt_status(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        items = get_expense_detail(conn, pay_period_id, employee_id=emp_id)
        non_per_diem = [
            i for i in items
            if i.category not in ("per_diem_travel", "per_diem_full")
        ]
        for item in non_per_diem:
            assert item.receipt_status == "missing"
            assert item.requires_receipt is True


class TestMarkReceiptReceived:

    def test_updates_receipt_status(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        items = get_expense_detail(conn, pay_period_id, employee_id=emp_id)
        non_per_diem = [i for i in items if i.requires_receipt]
        if not non_per_diem:
            pytest.skip("No non-per-diem expenses in Trif fixture")

        target = non_per_diem[0]
        mark_receipt_received(conn, target.id)

        row = db.fetch_one(conn, "SELECT receipt_status FROM expense_items WHERE id = ?", (target.id,))
        assert row["receipt_status"] == "received"

    def test_updates_billing_status(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        items = get_expense_detail(conn, pay_period_id, employee_id=emp_id)
        non_per_diem = [i for i in items if i.requires_receipt]
        if not non_per_diem:
            pytest.skip("No non-per-diem expenses in fixture")

        target = non_per_diem[0]
        mark_receipt_received(conn, target.id)

        row = db.fetch_one(conn, "SELECT billing_status FROM expense_items WHERE id = ?", (target.id,))
        assert row["billing_status"] == "ready_for_billing"

    def test_updates_reimbursement_status(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        items = get_expense_detail(conn, pay_period_id, employee_id=emp_id)
        non_per_diem = [i for i in items if i.requires_receipt]
        if not non_per_diem:
            pytest.skip("No non-per-diem expenses in fixture")

        target = non_per_diem[0]
        mark_receipt_received(conn, target.id)

        row = db.fetch_one(conn, "SELECT reimbursement_status FROM expense_items WHERE id = ?", (target.id,))
        assert row["reimbursement_status"] == "ready_for_reimbursement"

    def test_invalid_id_raises(self, conn):
        with pytest.raises(ValueError, match="not found"):
            mark_receipt_received(conn, 9999)

    def test_audit_log_created(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        items = get_expense_detail(conn, pay_period_id, employee_id=emp_id)
        non_per_diem = [i for i in items if i.requires_receipt]
        if not non_per_diem:
            pytest.skip("No non-per-diem expenses in fixture")

        mark_receipt_received(conn, non_per_diem[0].id)
        row = db.fetch_one(conn, "SELECT * FROM audit_log WHERE action = 'mark_receipt_received'")
        assert row is not None


class TestMarkReimbursed:

    def _make_ready(self, conn, pay_period_id, emp_id, currency="CAD"):
        """Mark all per-diem items as ready_for_reimbursement (they already are)."""
        items = get_expense_detail(conn, pay_period_id, employee_id=emp_id)
        ready = [i for i in items if i.reimbursement_status == "ready_for_reimbursement" and i.currency == currency]
        return ready

    def test_marks_ready_items_as_reimbursed(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        ready = self._make_ready(conn, pay_period_id, emp_id)
        if not ready:
            pytest.skip("No ready_for_reimbursement items in fixture")

        n = mark_reimbursed(conn, pay_period_id, emp_id, currency="CAD")
        assert n == len(ready)

        rows = db.fetch_all(
            conn,
            "SELECT reimbursement_status FROM expense_items WHERE pay_period_id = ? AND employee_id = ? AND currency = 'CAD'",
            (pay_period_id, emp_id),
        )
        for row in rows:
            if row["reimbursement_status"] != "submitted":
                assert row["reimbursement_status"] in ("reimbursed", "ready_for_reimbursement", "submitted")

    def test_does_not_mark_missing_receipt_items(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        items = get_expense_detail(conn, pay_period_id, employee_id=emp_id)
        missing = [i for i in items if i.receipt_status == "missing"]
        if not missing:
            pytest.skip("No missing-receipt items in fixture")

        mark_reimbursed(conn, pay_period_id, emp_id, currency="CAD")

        for item in missing:
            row = db.fetch_one(conn, "SELECT reimbursement_status FROM expense_items WHERE id = ?", (item.id,))
            assert row["reimbursement_status"] != "reimbursed"


class TestGetReimbursementBlocked:

    def test_returns_missing_receipt_items(self, imported_period):
        conn, pay_period_id, _ = imported_period
        blocked = get_reimbursement_blocked(conn, pay_period_id)
        assert all(isinstance(b, ExpenseLineItem) for b in blocked)
        assert all(b.receipt_status == "missing" for b in blocked)

    def test_empty_after_all_receipts_received(self, imported_period):
        conn, pay_period_id, emp_id = imported_period
        blocked = get_reimbursement_blocked(conn, pay_period_id)
        for item in blocked:
            mark_receipt_received(conn, item.id)

        blocked_after = get_reimbursement_blocked(conn, pay_period_id)
        assert blocked_after == []
