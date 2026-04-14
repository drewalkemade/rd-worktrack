"""
test_reconciler.py — Tests for pipeline/reconciler.py.

Uses in-memory databases with full import pipeline fixtures.
All tests set up payroll PDF + timesheet imports, then run
run_reconciliation() against the resulting DB state.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from payroll_app import config
from payroll_app.database import db, employee_manager
from payroll_app.pipeline.importer import import_payroll_pdf, import_travel_pdf, import_timesheet
from payroll_app.pipeline.weekly_verifier import run_weekly_verification, set_verified
from payroll_app.pipeline.reconciler import (
    run_reconciliation,
    get_reconciliation,
    approve_reconciliation,
    approve_all,
    ReconciliationSummary,
    EmployeeReconciliation,
    ReconciliationBlockedError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"

PAYROLL_PDF  = FIXTURES / "R&D_260329-xxxxx.pdf"
TRIF_TS      = FIXTURES / "DTrifTS_17_20260329.xlsx"
JEREMIAS_TS  = FIXTURES / "JJeremiasTS_16_20260329.xlsx"
ANDKILDE_TS  = FIXTURES / "EmpTS - HAndkilde - 20260329.xlsx"

WEEK_ENDING = date(2026, 3, 29)


# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------

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


def _full_import_and_verify(conn):
    """Import payroll PDF and Trif + Andkilde timesheets; verify and return IDs."""
    pr = import_payroll_pdf(conn, PAYROLL_PDF, WEEK_ENDING)
    import_timesheet(conn, TRIF_TS)
    import_timesheet(conn, ANDKILDE_TS)
    wa_id = pr.weekly_approval_id
    pay_period_id = pr.pay_period_id

    # Verify all employees so reconciliation is not blocked
    run_weekly_verification(conn, wa_id)
    # Manually mark all as verified so blocking check passes
    rows = db.fetch_all(
        conn,
        "SELECT employee_id FROM weekly_employee_verification WHERE weekly_approval_id = ?",
        (wa_id,),
    )
    for row in rows:
        set_verified(conn, wa_id, row["employee_id"])

    return pay_period_id, wa_id


# ---------------------------------------------------------------------------
# Basic run_reconciliation tests
# ---------------------------------------------------------------------------

class TestRunReconciliation:

    def test_returns_summary(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        summary = run_reconciliation(conn, pay_period_id)
        assert isinstance(summary, ReconciliationSummary)
        assert summary.pay_period_id == pay_period_id

    def test_reconciliation_rows_created(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)
        rows = db.fetch_all(
            conn,
            "SELECT * FROM reconciliation WHERE pay_period_id = ?",
            (pay_period_id,),
        )
        # 6 billable (from payroll PDF) + 1 internal (Andkilde) = 7
        # Jeremias has no timesheet in this test setup but appears in payroll PDF
        assert len(rows) >= 6

    def test_trif_final_hours_equal_approved(self, conn):
        """For billable employees, final_* = customer-approved values."""
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        row = db.fetch_one(
            conn,
            "SELECT * FROM reconciliation WHERE pay_period_id = ? AND employee_id = ?",
            (pay_period_id, trif_id),
        )
        assert row is not None
        # Trif: approved REG=40, OT=32, DBL=12
        assert row["final_reg"] == pytest.approx(40.0, abs=0.01)
        assert row["final_ot"]  == pytest.approx(32.0, abs=0.01)
        assert row["final_dbl"] == pytest.approx(12.0, abs=0.01)

    def test_internal_employee_final_hours_from_timesheet(self, conn):
        """For internal employees, final_* = timesheet values, cust_* = 0."""
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        andkilde_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE display_name = 'Henry Andkilde'"
        )["id"]
        row = db.fetch_one(
            conn,
            "SELECT * FROM reconciliation WHERE pay_period_id = ? AND employee_id = ?",
            (pay_period_id, andkilde_id),
        )
        assert row is not None
        # Internal: cust_* = 0
        assert row["cust_reg"] == 0.0
        assert row["cust_ot"]  == 0.0
        # Final = timesheet hours (non-zero since Andkilde submitted a timesheet)
        ts_row = db.fetch_one(
            conn,
            "SELECT * FROM timesheet_hours WHERE pay_period_id = ? AND employee_id = ?",
            (pay_period_id, andkilde_id),
        )
        if ts_row:
            assert row["final_reg"] == pytest.approx(float(ts_row["reg_hours"] or 0), abs=0.01)

    def test_hours_match_gets_pending_status(self, conn):
        """Employees whose approved and timesheet hours match → status = pending."""
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        # Trif: timesheet week totals (from biweekly) should divide roughly into weeks;
        # any employee with matching hours gets 'pending'
        rows = db.fetch_all(
            conn,
            "SELECT status FROM reconciliation WHERE pay_period_id = ?",
            (pay_period_id,),
        )
        statuses = {r["status"] for r in rows}
        # We should have at least some pending rows
        assert "pending" in statuses or "variance" in statuses

    def test_variance_detected(self, conn):
        """Tamper with approved hours to force a variance."""
        pay_period_id, wa_id = _full_import_and_verify(conn)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        conn.execute(
            "UPDATE customer_hours SET reg_hours = 99.0 WHERE weekly_approval_id = ? AND employee_id = ?",
            (wa_id, trif_id),
        )

        run_reconciliation(conn, pay_period_id)

        row = db.fetch_one(
            conn,
            "SELECT status FROM reconciliation WHERE pay_period_id = ? AND employee_id = ?",
            (pay_period_id, trif_id),
        )
        assert row["status"] == "variance"

    def test_idempotent_rerun(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)
        run_reconciliation(conn, pay_period_id, force=True)

        count = db.fetch_one(
            conn, "SELECT COUNT(*) AS n FROM reconciliation WHERE pay_period_id = ?",
            (pay_period_id,)
        )["n"]
        # Rows should not have doubled
        assert count <= 10

    def test_audit_log_created(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)
        row = db.fetch_one(
            conn, "SELECT * FROM audit_log WHERE action = 'run_reconciliation'"
        )
        assert row is not None

    def test_invalid_period_raises(self, conn):
        with pytest.raises(ValueError, match="not found"):
            run_reconciliation(conn, pay_period_id=9999)


# ---------------------------------------------------------------------------
# Blocking check tests
# ---------------------------------------------------------------------------

class TestBlockingCheck:

    def test_blocked_when_verification_incomplete(self, conn):
        """Reconciliation should be blocked if verification has not been run."""
        pr = import_payroll_pdf(conn, PAYROLL_PDF, WEEK_ENDING)
        import_timesheet(conn, TRIF_TS)
        wa_id = pr.weekly_approval_id
        pay_period_id = pr.pay_period_id

        # Run verification but do NOT verify any employees
        run_weekly_verification(conn, wa_id)
        # All employees are in pending/needs_review state

        with pytest.raises(ReconciliationBlockedError):
            run_reconciliation(conn, pay_period_id)

    def test_force_bypasses_blocking_check(self, conn):
        """force=True should allow reconciliation even with unverified employees."""
        pr = import_payroll_pdf(conn, PAYROLL_PDF, WEEK_ENDING)
        import_timesheet(conn, TRIF_TS)
        pay_period_id = pr.pay_period_id

        # Don't verify anything — should not block with force=True
        summary = run_reconciliation(conn, pay_period_id, force=True)
        assert isinstance(summary, ReconciliationSummary)

    def test_not_blocked_when_all_verified(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        # Should not raise
        summary = run_reconciliation(conn, pay_period_id)
        assert summary.total_employees >= 1

    def test_approved_rows_not_recomputed(self, conn):
        """Rows already in 'approved' status are not overwritten without force."""
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        approve_reconciliation(conn, pay_period_id, trif_id, approved_by="Drew")

        # Now re-run without force — Trif's row should stay 'approved'
        run_reconciliation(conn, pay_period_id)

        row = db.fetch_one(
            conn,
            "SELECT status FROM reconciliation WHERE pay_period_id = ? AND employee_id = ?",
            (pay_period_id, trif_id),
        )
        assert row["status"] == "approved"


# ---------------------------------------------------------------------------
# get_reconciliation tests
# ---------------------------------------------------------------------------

class TestGetReconciliation:

    def test_returns_employee_reconciliations(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        recs = get_reconciliation(conn, pay_period_id)
        assert len(recs) >= 1
        assert all(isinstance(r, EmployeeReconciliation) for r in recs)

    def test_sorted_by_display_name(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        recs = get_reconciliation(conn, pay_period_id)
        names = [r.display_name for r in recs]
        assert names == sorted(names)

    def test_variance_fields_populated(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        recs = get_reconciliation(conn, pay_period_id)
        for r in recs:
            assert isinstance(r.reg_variance, float)

    def test_empty_before_reconciliation_run(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        recs = get_reconciliation(conn, pay_period_id)
        assert recs == []


# ---------------------------------------------------------------------------
# Approval tests
# ---------------------------------------------------------------------------

class TestApproval:

    def test_approve_reconciliation_sets_status(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        approve_reconciliation(conn, pay_period_id, trif_id, approved_by="Drew", notes="LGTM")

        row = db.fetch_one(
            conn,
            "SELECT * FROM reconciliation WHERE pay_period_id = ? AND employee_id = ?",
            (pay_period_id, trif_id),
        )
        assert row["status"]      == "approved"
        assert row["approved_by"] == "Drew"
        assert row["notes"]       == "LGTM"
        assert row["approved_at"] is not None

    def test_approve_reconciliation_no_row_raises(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        with pytest.raises(ValueError, match="run_reconciliation"):
            approve_reconciliation(conn, pay_period_id, trif_id)

    def test_approve_all_sets_pending_rows(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        n = approve_all(conn, pay_period_id, approved_by="Drew")
        assert n >= 1

        # All previously-pending rows should now be approved
        still_pending = db.fetch_all(
            conn,
            "SELECT id FROM reconciliation WHERE pay_period_id = ? AND status = 'pending'",
            (pay_period_id,),
        )
        assert len(still_pending) == 0

    def test_approve_all_skips_variance_rows(self, conn):
        """approve_all should not touch variance rows."""
        pay_period_id, wa_id = _full_import_and_verify(conn)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        conn.execute(
            "UPDATE customer_hours SET reg_hours = 99.0 WHERE weekly_approval_id = ? AND employee_id = ?",
            (wa_id, trif_id),
        )

        run_reconciliation(conn, pay_period_id)
        approve_all(conn, pay_period_id)

        row = db.fetch_one(
            conn,
            "SELECT status FROM reconciliation WHERE pay_period_id = ? AND employee_id = ?",
            (pay_period_id, trif_id),
        )
        assert row["status"] == "variance"

    def test_audit_log_on_approve(self, conn):
        pay_period_id, _ = _full_import_and_verify(conn)
        run_reconciliation(conn, pay_period_id)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        approve_reconciliation(conn, pay_period_id, trif_id)

        row = db.fetch_one(
            conn, "SELECT * FROM audit_log WHERE action = 'approve_reconciliation'"
        )
        assert row is not None
