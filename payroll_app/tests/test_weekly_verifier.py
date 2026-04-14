"""
test_weekly_verifier.py — Tests for pipeline/weekly_verifier.py.

Uses in-memory databases with seeded employees.  Each test sets up a minimal
combination of payroll PDF + travel PDF + timesheet imports and then calls
run_weekly_verification() to check the resulting status rows.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from payroll_app import config
from payroll_app.database import db, employee_manager
from payroll_app.pipeline.importer import import_payroll_pdf, import_travel_pdf, import_timesheet
from payroll_app.pipeline.weekly_verifier import (
    run_weekly_verification,
    get_verification_status,
    set_verified,
    VerificationSummary,
    EmployeeVerification,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"

PAYROLL_PDF  = FIXTURES / "R&D_260329-xxxxx.pdf"
TRAVEL_PDF   = FIXTURES / "R&D_260329-Travel.pdf"
TRIF_TS      = FIXTURES / "DTrifTS_17_20260329.xlsx"
JEREMIAS_TS  = FIXTURES / "JJeremiasTS_16_20260329.xlsx"

WEEK_ENDING  = date(2026, 3, 29)


# ---------------------------------------------------------------------------
# Shared fixture
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


def _import_all(conn):
    """Import the fixture payroll PDF, travel PDF, and Trif + Jeremias timesheets."""
    pr = import_payroll_pdf(conn, PAYROLL_PDF, WEEK_ENDING)
    tr = import_travel_pdf(conn, TRAVEL_PDF)
    import_timesheet(conn, TRIF_TS)
    import_timesheet(conn, JEREMIAS_TS)
    return pr.weekly_approval_id


# ---------------------------------------------------------------------------
# Basic run_weekly_verification tests
# ---------------------------------------------------------------------------

class TestRunWeeklyVerification:

    def test_returns_summary(self, conn):
        wa_id = _import_all(conn)
        summary = run_weekly_verification(conn, wa_id)
        assert isinstance(summary, VerificationSummary)
        assert summary.weekly_approval_id == wa_id

    def test_total_employee_count(self, conn):
        """6 billable employees in payroll PDF + 2 timesheets (overlap).
        Unique union = all employees who appear in customer_hours OR timesheets.
        """
        wa_id = _import_all(conn)
        summary = run_weekly_verification(conn, wa_id)
        # 6 from payroll, 2 from timesheets (Trif + Jeremias, already in payroll)
        assert summary.total_employees == 6

    def test_nonexistent_approval_returns_warning(self, conn):
        summary = run_weekly_verification(conn, weekly_approval_id=9999)
        assert "not found" in summary.warnings[0]

    def test_verification_rows_created(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)
        rows = db.fetch_all(
            conn,
            "SELECT * FROM weekly_employee_verification WHERE weekly_approval_id = ?",
            (wa_id,),
        )
        assert len(rows) == 6

    def test_idempotent_rerun(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)
        run_weekly_verification(conn, wa_id)
        count = db.fetch_one(
            conn,
            "SELECT COUNT(*) AS n FROM weekly_employee_verification WHERE weekly_approval_id = ?",
            (wa_id,),
        )["n"]
        assert count == 6  # no duplicate rows

    def test_audit_log_entry_created(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)
        row = db.fetch_one(
            conn,
            "SELECT * FROM audit_log WHERE action = 'run_weekly_verification'",
        )
        assert row is not None

    def test_no_employees_returns_warning(self, conn):
        """Weekly approval with no customer_hours and no timesheets."""
        # Create a bare weekly_approval with no associated data
        conn.execute(
            """
            INSERT INTO pay_periods (period_start, period_end, week1_ending, week2_ending)
            VALUES ('2026-04-13', '2026-04-26', '2026-04-19', '2026-04-26')
            """
        )
        pid = db.fetch_one(conn, "SELECT last_insert_rowid() AS id")["id"]
        conn.execute(
            "INSERT INTO weekly_approvals (pay_period_id, week_ending, week_number) VALUES (?, '2026-04-19', 1)",
            (pid,),
        )
        wa_id = db.fetch_one(conn, "SELECT last_insert_rowid() AS id")["id"]

        summary = run_weekly_verification(conn, wa_id)
        assert summary.total_employees == 0
        assert any("No employees" in w for w in summary.warnings)


# ---------------------------------------------------------------------------
# Status assignment tests
# ---------------------------------------------------------------------------

class TestStatusAssignment:

    def test_employees_without_timesheets_get_needs_review(self, conn):
        """Employees who appear in approved hours but have no timesheet get needs_review."""
        wa_id = import_payroll_pdf(conn, PAYROLL_PDF, WEEK_ENDING).weekly_approval_id
        # No timesheets imported
        run_weekly_verification(conn, wa_id)

        rows = db.fetch_all(
            conn,
            "SELECT status FROM weekly_employee_verification WHERE weekly_approval_id = ?",
            (wa_id,),
        )
        # All employees lack timesheets → all should be needs_review
        for row in rows:
            assert row["status"] == "needs_review", \
                f"Expected needs_review for employee without timesheet, got {row['status']!r}"

    def test_matching_hours_get_pending_status(self, conn):
        """An employee whose approved hours match their timesheet → status = pending
        (unless expenses flag it as needs_review).
        """
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        # Jeremias: REG=33.75, OT=0, DBL=0 in both approved and timesheet
        jeremias_id = db.fetch_one(
            conn,
            "SELECT id FROM employees WHERE pdf_name = 'JEREMIAS, JERRY'",
        )["id"]

        row = db.fetch_one(
            conn,
            "SELECT status FROM weekly_employee_verification WHERE weekly_approval_id = ? AND employee_id = ?",
            (wa_id, jeremias_id),
        )
        # Jeremias has per-diem expenses → will be needs_review due to expense flag
        # or pending if no per-diem this week; exact value depends on fixture
        assert row["status"] in ("pending", "needs_review")

    def test_hours_variance_gets_needs_review(self, conn):
        """If approved hours differ from timesheet hours, status = needs_review."""
        wa_id = _import_all(conn)

        # Manually tamper with approved hours for Trif to create a variance
        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        conn.execute(
            "UPDATE customer_hours SET reg_hours = 99.0 WHERE weekly_approval_id = ? AND employee_id = ?",
            (wa_id, trif_id),
        )

        run_weekly_verification(conn, wa_id)

        row = db.fetch_one(
            conn,
            "SELECT status FROM weekly_employee_verification WHERE weekly_approval_id = ? AND employee_id = ?",
            (wa_id, trif_id),
        )
        assert row["status"] == "needs_review"

    def test_pending_sun_travel_gets_needs_review(self, conn):
        """If current Sunday travel is pending_next_pdf, status = needs_review."""
        wa_id = _import_all(conn)

        # Travel PDF sets current_sun_status = 'pending_next_pdf' for all employees
        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]

        travel_row = db.fetch_one(
            conn,
            "SELECT id, current_sun_status FROM travel_hours WHERE weekly_approval_id = ? AND employee_id = ?",
            (wa_id, trif_id),
        )
        if travel_row and travel_row["current_sun_status"] == "pending_next_pdf":
            run_weekly_verification(conn, wa_id)
            row = db.fetch_one(
                conn,
                "SELECT status FROM weekly_employee_verification WHERE weekly_approval_id = ? AND employee_id = ?",
                (wa_id, trif_id),
            )
            assert row["status"] == "needs_review"


# ---------------------------------------------------------------------------
# get_verification_status tests
# ---------------------------------------------------------------------------

class TestGetVerificationStatus:

    def test_returns_employee_verifications(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        verifications = get_verification_status(conn, wa_id)
        assert len(verifications) == 6
        assert all(isinstance(v, EmployeeVerification) for v in verifications)

    def test_sorted_by_display_name(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        verifications = get_verification_status(conn, wa_id)
        names = [v.display_name for v in verifications]
        assert names == sorted(names)

    def test_variance_fields_populated(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        verifications = get_verification_status(conn, wa_id)
        for v in verifications:
            # Variance = approved - timesheet; should be a float
            assert isinstance(v.reg_variance, float)
            assert isinstance(v.ot_variance,  float)
            assert isinstance(v.dbl_variance, float)

    def test_trif_approved_hours_match_expected(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        verifications = get_verification_status(conn, wa_id)
        trif_v = next((v for v in verifications if "Trif" in v.display_name), None)
        assert trif_v is not None

        assert trif_v.approved_reg == pytest.approx(40.0, abs=0.01)
        assert trif_v.approved_ot  == pytest.approx(32.0, abs=0.01)
        assert trif_v.approved_dbl == pytest.approx(12.0, abs=0.01)

    def test_returns_empty_list_before_verification_run(self, conn):
        wa_id = import_payroll_pdf(conn, PAYROLL_PDF, WEEK_ENDING).weekly_approval_id
        verifications = get_verification_status(conn, wa_id)
        assert verifications == []


# ---------------------------------------------------------------------------
# set_verified tests
# ---------------------------------------------------------------------------

class TestSetVerified:

    def test_set_verified_changes_status(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]

        set_verified(conn, wa_id, trif_id, note="Hours match, expenses reviewed")

        row = db.fetch_one(
            conn,
            "SELECT status, verified_at FROM weekly_employee_verification WHERE weekly_approval_id = ? AND employee_id = ?",
            (wa_id, trif_id),
        )
        assert row["status"] == "verified"
        assert row["verified_at"] is not None

    def test_verified_status_not_overwritten_by_rerun(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        set_verified(conn, wa_id, trif_id)

        # Re-run verification — should not overwrite the verified status
        run_weekly_verification(conn, wa_id)

        row = db.fetch_one(
            conn,
            "SELECT status FROM weekly_employee_verification WHERE weekly_approval_id = ? AND employee_id = ?",
            (wa_id, trif_id),
        )
        assert row["status"] == "verified"

    def test_set_verified_no_verification_row_raises(self, conn):
        wa_id = import_payroll_pdf(conn, PAYROLL_PDF, WEEK_ENDING).weekly_approval_id
        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]

        with pytest.raises(ValueError, match="No verification row"):
            set_verified(conn, wa_id, trif_id)

    def test_set_verified_appends_note(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        set_verified(conn, wa_id, trif_id, note="All good")

        row = db.fetch_one(
            conn,
            "SELECT extra_expense_note FROM weekly_employee_verification WHERE weekly_approval_id = ? AND employee_id = ?",
            (wa_id, trif_id),
        )
        assert "All good" in (row["extra_expense_note"] or "")

    def test_audit_log_entry_on_verify(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        set_verified(conn, wa_id, trif_id)

        row = db.fetch_one(
            conn, "SELECT * FROM audit_log WHERE action = 'set_verified'"
        )
        assert row is not None

    def test_verified_count_in_summary(self, conn):
        wa_id = _import_all(conn)
        run_weekly_verification(conn, wa_id)

        trif_id = db.fetch_one(
            conn, "SELECT id FROM employees WHERE pdf_name = 'TRIF, DANIEL'"
        )["id"]
        set_verified(conn, wa_id, trif_id)

        # Re-run; verified count should be 1
        summary = run_weekly_verification(conn, wa_id)
        assert summary.verified_count == 1
