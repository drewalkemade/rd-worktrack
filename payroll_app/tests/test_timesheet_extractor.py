"""
test_timesheet_extractor.py — Fixture-based tests for timesheet_extractor_v2.

Tests verify expected output against example employee timesheets.

Fixture files:
  DTrifTS_17_20260329.xlsx  — Daniel Trif, 2026-03-16 to 2026-03-29
  FMoldovan_20260329.xlsx   — Florin Moldovan (empty labor hours — just expenses?)
  JJeremiasTS_16_20260329.xlsx  — Jerry Jeremias
  EmpTS - HAndkilde - 20260329.xlsx — Henry Andkilde (internal employee)
"""

from datetime import date
from pathlib import Path

import pytest

from payroll_app.extractors.timesheet_extractor_v2 import extract_timesheet

FIXTURES = Path(__file__).parent / "fixtures"

TRIF_FILE     = FIXTURES / "DTrifTS_17_20260329.xlsx"
MOLDOVAN_FILE = FIXTURES / "FMoldovan_20260329.xlsx"
JEREMIAS_FILE = FIXTURES / "JJeremiasTS_16_20260329.xlsx"
ANDKILDE_FILE = FIXTURES / "EmpTS - HAndkilde - 20260329.xlsx"


# ---------------------------------------------------------------------------
# Daniel Trif — known values from inspecting the workbook
# Daily labor:
#   Row 9  Mon 2026-03-16: Reg=12
#   Row 10 Tue 2026-03-17: Reg=12
#   Row 11 Wed 2026-03-18: Reg=6, Drive=4
#   Row 12 Thu 2026-03-19: (nothing)
#   Row 13 Fri 2026-03-20: (nothing)
#   Row 14 Sat 2026-03-21: Reg=8, Drive=4
#   Row 15 Sun 2026-03-22: OT2=12
#   Row 16 Mon 2026-03-23: Reg=12
#   Row 17 Tue 2026-03-24: Reg=12
#   Row 18 Wed 2026-03-25: Reg=12
#   Row 19 Thu 2026-03-26: Reg=4, OT1=8
#   Row 20 Fri 2026-03-27: OT1=12
#   Row 21 Sat 2026-03-28: OT1=12
#   Row 22 Sun 2026-03-29: OT2=12
# Totals: Reg=78, OT1=32, OT2=24, Drive=8
# CAD expenses: various per diem rows
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def trif_data():
    return extract_timesheet(TRIF_FILE)


def test_fixture_files_exist():
    for path in [TRIF_FILE, MOLDOVAN_FILE, JEREMIAS_FILE, ANDKILDE_FILE]:
        assert path.exists(), f"Fixture missing: {path}"


class TestDanielTrif:

    def test_employee_name(self, trif_data):
        assert trif_data["employee_name"] == "Daniel Trif"

    def test_period_dates(self, trif_data):
        assert trif_data["period_start"] == date(2026, 3, 16)
        assert trif_data["period_end"]   == date(2026, 3, 29)

    def test_exactly_14_daily_rows(self, trif_data):
        assert len(trif_data["daily_hours"]) == 14, \
            f"Expected 14 daily rows, got {len(trif_data['daily_hours'])}"

    def test_first_day_is_monday(self, trif_data):
        first = trif_data["daily_hours"][0]
        assert first["day_name"] == "Monday"
        assert first["work_date"] == date(2026, 3, 16)

    def test_last_day_is_second_sunday(self, trif_data):
        """The second Sunday (end of period) must be included."""
        last = trif_data["daily_hours"][-1]
        assert last["day_name"] == "Sunday"
        assert last["work_date"] == date(2026, 3, 29)

    def test_biweekly_totals(self, trif_data):
        totals = trif_data["totals"]
        assert totals["reg_hours"]   == pytest.approx(78.0, abs=0.01)
        assert totals["ot1_hours"]   == pytest.approx(32.0, abs=0.01)
        assert totals["ot2_hours"]   == pytest.approx(24.0, abs=0.01)
        assert totals["drive_hours"] == pytest.approx(8.0,  abs=0.01)

    def test_totals_match_flag(self, trif_data):
        assert trif_data["totals_match"] is True, \
            f"Totals mismatch: {trif_data['warnings']}"

    def test_specific_daily_rows(self, trif_data):
        rows = {r["work_date"]: r for r in trif_data["daily_hours"]}

        # Mon Mar 16: Reg=12
        row_0316 = rows[date(2026, 3, 16)]
        assert row_0316["reg_hours"] == 12.0

        # Wed Mar 18: Reg=6, Drive=4
        row_0318 = rows[date(2026, 3, 18)]
        assert row_0318["reg_hours"]   == 6.0
        assert row_0318["drive_hours"] == 4.0

        # Sun Mar 22 (first Sunday): OT2=12
        row_0322 = rows[date(2026, 3, 22)]
        assert row_0322["ot2_hours"] == 12.0

        # Thu Mar 26: Reg=4, OT1=8
        row_0326 = rows[date(2026, 3, 26)]
        assert row_0326["reg_hours"]  == 4.0
        assert row_0326["ot1_hours"]  == 8.0

        # Sun Mar 29 (second Sunday): OT2=12
        row_0329 = rows[date(2026, 3, 29)]
        assert row_0329["ot2_hours"] == 12.0

    def test_cad_expenses_present(self, trif_data):
        assert len(trif_data["expenses_cad"]) > 0

    def test_per_diem_does_not_require_receipt(self, trif_data):
        for exp in trif_data["expenses_cad"]:
            if exp["category"] in ("per_diem_travel", "per_diem_full"):
                assert exp["requires_receipt"] is False, \
                    f"Per diem should not require receipt: {exp}"

    def test_non_per_diem_requires_receipt(self, trif_data):
        for exp in trif_data["expenses_cad"]:
            if exp["category"] not in ("per_diem_travel", "per_diem_full"):
                assert exp["requires_receipt"] is True, \
                    f"Non-per-diem should require receipt: {exp}"

    def test_cad_expense_amounts_positive(self, trif_data):
        for exp in trif_data["expenses_cad"]:
            assert exp["amount"] > 0, f"Zero/negative expense amount: {exp}"

    def test_expense_dates_in_period(self, trif_data):
        for exp in trif_data["expenses_cad"] + trif_data["expenses_usd"]:
            if exp["work_date"] is not None:
                assert trif_data["period_start"] <= exp["work_date"] <= trif_data["period_end"], \
                    f"Expense date {exp['work_date']} outside period"

    def test_no_source_file_error(self, trif_data):
        assert "error" not in trif_data


class TestHenryAndkilde:
    """Henry Andkilde is an internal employee — no customer PDF approval.
    The timesheet should extract cleanly with daily rows.
    """

    @pytest.fixture(scope="class")
    def andkilde_data(self):
        return extract_timesheet(ANDKILDE_FILE)

    def test_employee_name(self, andkilde_data):
        # The timesheet has a trailing space — extractor should strip it
        assert andkilde_data["employee_name"] == "Henry Andkilde"

    def test_period_end(self, andkilde_data):
        assert andkilde_data["period_end"] == date(2026, 3, 29)

    def test_has_14_daily_rows(self, andkilde_data):
        assert len(andkilde_data["daily_hours"]) == 14

    def test_second_sunday_present(self, andkilde_data):
        last = andkilde_data["daily_hours"][-1]
        assert last["work_date"] == date(2026, 3, 29)


class TestMultipleTimesheets:
    """Smoke tests on the other fixture files to verify basic extraction works."""

    @pytest.mark.parametrize("filepath, expected_name", [
        (MOLDOVAN_FILE,  "Florin Moldovan"),
        (JEREMIAS_FILE,  "Jerry Jeremias"),
        (ANDKILDE_FILE,  "Henry Andkilde"),
    ])
    def test_name_extracted(self, filepath, expected_name):
        data = extract_timesheet(filepath)
        assert data["employee_name"] == expected_name

    @pytest.mark.parametrize("filepath", [
        MOLDOVAN_FILE, JEREMIAS_FILE, ANDKILDE_FILE
    ])
    def test_has_14_daily_rows(self, filepath):
        data = extract_timesheet(filepath)
        assert len(data["daily_hours"]) == 14, \
            f"{filepath.name}: expected 14 daily rows, got {len(data['daily_hours'])}"

    @pytest.mark.parametrize("filepath", [
        MOLDOVAN_FILE, JEREMIAS_FILE, ANDKILDE_FILE
    ])
    def test_period_end_is_march_29(self, filepath):
        data = extract_timesheet(filepath)
        assert data["period_end"] == date(2026, 3, 29)

    @pytest.mark.parametrize("filepath", [
        TRIF_FILE, MOLDOVAN_FILE, JEREMIAS_FILE, ANDKILDE_FILE
    ])
    def test_totals_match_or_warned(self, filepath):
        """Either totals match, or there's an explicit warning about it."""
        data = extract_timesheet(filepath)
        if not data["totals_match"]:
            mismatch_warnings = [w for w in data["warnings"] if "mismatch" in w.lower()]
            assert mismatch_warnings, \
                f"{filepath.name}: totals_match=False but no mismatch warning"


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        extract_timesheet("/nonexistent/timesheet.xlsx")
