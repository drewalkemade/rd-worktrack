"""
test_pdf_parser.py — Fixture-based tests for pdf_parser_v2.

Tests verify expected output against the sample payroll PDF
R&D_260329-xxxxx.pdf (week ending 2026-03-29).

Full employee list and verified expected values (9 employees across 2 pages):

  PDF totals line format:  TOTAL TOTAL TOTAL REG OT DBL ??? TOTAL TOTAL
  (The first three and last two values are attendance totals; REG/OT/DBL are columns 4-6.)

  ATKINSON, JEREMY   (E8022):  totals=49:00 → REG=40.00, OT=9.00,   DBL=0.00
  WISEMAN, JEREMY    (E8031):  totals=40:00 → REG=40.00, OT=0.00,   DBL=0.00
  RENWICK, RICHARD   (E8041):  totals=0:00  → REG=0.00,  OT=0.00,   DBL=0.00
  JEREMIAS, JERRY    (E8174):  totals=33:45 → REG=33.75, OT=0.00,   DBL=0.00
  TRIF, DANIEL       (E8190):  totals=84:00 → REG=40.00, OT=32.00,  DBL=12.00
  EBBINGHAUS, ZACHARY(E8395):  totals=33:30 → REG=33.50, OT=0.00,   DBL=0.00
  ZORZI, JARRETT     (E8611):  totals=45:30 → REG=40.00, OT=5.50,   DBL=0.00
  MOLDOVAN, FLORIN   (E8650):  totals=72:45 → REG=40.00, OT=20.75,  DBL=12.00  (spans pages)
  SALEH, YOUSOF      (E8668):  totals=34:00 → REG=34.00, OT=0.00,   DBL=0.00

Note: 9:00 → 9.0; 20:45 → 20.75; 32:00 → 32.0; 33:30 → 33.5; 33:45 → 33.75; 5:30 → 5.5
"""

from pathlib import Path

import pytest

from payroll_app.extractors.pdf_parser_v2 import parse_payroll_pdf

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "R&D_260329-xxxxx.pdf"

# Expected per-employee totals (employee_name key is title-cased pdf_name)
_EXPECTED = {
    "Atkinson, Jeremy":   {"centerline_id": 8022, "reg_hours": 40.0,  "ot_hours": 9.0,   "dbl_hours": 0.0},
    "Wiseman, Jeremy":    {"centerline_id": 8031, "reg_hours": 40.0,  "ot_hours": 0.0,   "dbl_hours": 0.0},
    "Renwick, Richard":   {"centerline_id": 8041, "reg_hours": 0.0,   "ot_hours": 0.0,   "dbl_hours": 0.0},
    "Jeremias, Jerry":    {"centerline_id": 8174, "reg_hours": 33.75, "ot_hours": 0.0,   "dbl_hours": 0.0},
    "Trif, Daniel":       {"centerline_id": 8190, "reg_hours": 40.0,  "ot_hours": 32.0,  "dbl_hours": 12.0},
    "Ebbinghaus, Zachary":{"centerline_id": 8395, "reg_hours": 33.5,  "ot_hours": 0.0,   "dbl_hours": 0.0},
    "Zorzi, Jarrett":     {"centerline_id": 8611, "reg_hours": 40.0,  "ot_hours": 5.5,   "dbl_hours": 0.0},
    "Moldovan, Florin":   {"centerline_id": 8650, "reg_hours": 40.0,  "ot_hours": 20.75, "dbl_hours": 12.0},
    "Saleh, Yousof":      {"centerline_id": 8668, "reg_hours": 34.0,  "ot_hours": 0.0,   "dbl_hours": 0.0},
}


@pytest.fixture(scope="module")
def parsed_pdf():
    """Parse the fixture PDF once and share across all tests in this module."""
    employees, warnings = parse_payroll_pdf(FIXTURE_PDF)
    return employees, warnings


def test_fixture_exists():
    assert FIXTURE_PDF.exists(), f"Fixture PDF missing: {FIXTURE_PDF}"


def test_returns_employees(parsed_pdf):
    employees, _ = parsed_pdf
    assert len(employees) == 9, f"Expected 9 employees, got {len(employees)}"


def test_no_fatal_warnings(parsed_pdf):
    """Parser should not produce warnings that indicate data loss."""
    _, warnings = parsed_pdf
    fatal_warnings = [w for w in warnings if "no totals row" in w.lower()]
    assert not fatal_warnings, f"Fatal warnings: {fatal_warnings}"


def test_employee_ids_are_unique(parsed_pdf):
    employees, _ = parsed_pdf
    ids = [e["centerline_id"] for e in employees]
    assert len(ids) == len(set(ids)), f"Duplicate employee IDs: {ids}"


@pytest.mark.parametrize("employee_name, expected", _EXPECTED.items())
def test_employee_hours(parsed_pdf, employee_name, expected):
    employees, _ = parsed_pdf
    emp_map = {e["employee_name"]: e for e in employees}

    assert employee_name in emp_map, (
        f"Employee {employee_name!r} not found. "
        f"Found: {list(emp_map.keys())}"
    )

    emp = emp_map[employee_name]
    assert emp["centerline_id"] == expected["centerline_id"]
    assert emp["reg_hours"] == pytest.approx(expected["reg_hours"], abs=0.01), \
        f"{employee_name} REG: expected {expected['reg_hours']}, got {emp['reg_hours']}"
    assert emp["ot_hours"] == pytest.approx(expected["ot_hours"], abs=0.01), \
        f"{employee_name} OT: expected {expected['ot_hours']}, got {emp['ot_hours']}"
    assert emp["dbl_hours"] == pytest.approx(expected["dbl_hours"], abs=0.01), \
        f"{employee_name} DBL: expected {expected['dbl_hours']}, got {emp['dbl_hours']}"


def test_pdf_ids_formatted_correctly(parsed_pdf):
    employees, _ = parsed_pdf
    for emp in employees:
        assert emp["pdf_id"].startswith("E"), f"pdf_id should start with 'E': {emp['pdf_id']}"
        assert emp["pdf_id"][1:].isdigit(), f"pdf_id suffix should be numeric: {emp['pdf_id']}"


def test_daily_rows_present(parsed_pdf):
    """Each employee should have at least 1 daily row extracted."""
    employees, _ = parsed_pdf
    for emp in employees:
        assert len(emp["daily_rows"]) >= 1, (
            f"Employee {emp['employee_name']!r} has no daily rows."
        )


def test_daily_rows_have_day_names(parsed_pdf):
    employees, _ = parsed_pdf
    valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
                  "Monday", "Tuesday", "Wednesday", "Thursday",
                  "Friday", "Saturday", "Sunday"}
    for emp in employees:
        for row in emp["daily_rows"]:
            assert row["day_name"] in valid_days, (
                f"Unexpected day_name {row['day_name']!r} for {emp['employee_name']!r}"
            )


def test_trif_daily_row_count(parsed_pdf):
    """Daniel Trif worked Mon–Sun (7 days), all on page 1.
    He should have 7 daily rows captured.
    """
    employees, _ = parsed_pdf
    emp_map = {e["employee_name"]: e for e in employees}
    trif = emp_map.get("Trif, Daniel")
    assert trif is not None, "Trif, Daniel not found in parsed employees"
    assert len(trif["daily_rows"]) == 7, (
        f"Expected 7 daily rows for Trif (Mon-Sun), got {len(trif['daily_rows'])}"
    )


def test_moldovan_spans_pages(parsed_pdf):
    """In this specific fixture PDF, Florin Moldovan is the last employee on page 1
    (Mon only) and continues on page 2 (Tue-Sun).  The parser carries state across
    pages generically — any employee could be at the page boundary in future PDFs.
    This test verifies the cross-page mechanism works, not that it is always Moldovan.
    """
    employees, _ = parsed_pdf
    emp_map = {e["employee_name"]: e for e in employees}
    moldovan = emp_map.get("Moldovan, Florin")
    assert moldovan is not None, "Moldovan, Florin not found in parsed employees"
    assert len(moldovan["daily_rows"]) == 7, (
        f"Expected 7 daily rows for Moldovan (cross-page), got {len(moldovan['daily_rows'])}"
    )


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_payroll_pdf("/nonexistent/path.pdf")
