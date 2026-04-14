"""
test_travel_parser.py — Fixture-based tests for travel_parser.

Tests verify expected output against the sample travel PDF
R&D_260329-Travel.pdf (week covering March 22–28, 2026).

Known expected values from manual inspection of the PDF:
  Zachary Ebbinghaus: Wed=3.5, total=3.5
  Jarrett Zorzi:      Mon=4.0, Thu=4.0, total=8.0
  Florin Moldovan:    Tue=6.0, Thu=7.0, Fri=2.5, total=15.5

Date range in PDF: March 22 (Sunday) – March 28 (Saturday), 2026.
  - Sunday March 22 → prior week (March 16–22)
  - Monday March 23 through Saturday March 28 → current week (March 23–29)
"""

from pathlib import Path

import pytest

from payroll_app.extractors.travel_parser import parse_travel_pdf

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "R&D_260329-Travel.pdf"


_EXPECTED = {
    "Zachary Ebbinghaus": {
        "sun_hours": 0.0,
        "mon_hours": 0.0,
        "tue_hours": 0.0,
        "wed_hours": 3.5,
        "thu_hours": 0.0,
        "fri_hours": 0.0,
        "sat_hours": 0.0,
        "pdf_total": 3.5,
        "current_week_total": 3.5,
        "prior_sun_hours":    0.0,
    },
    "Jarrett Zorzi": {
        "sun_hours": 0.0,
        "mon_hours": 4.0,
        "tue_hours": 0.0,
        "wed_hours": 0.0,
        "thu_hours": 4.0,
        "fri_hours": 0.0,
        "sat_hours": 0.0,
        "pdf_total": 8.0,
        "current_week_total": 8.0,
        "prior_sun_hours":    0.0,
    },
    "Florin Moldovan": {
        "sun_hours": 0.0,
        "mon_hours": 0.0,
        "tue_hours": 6.0,
        "wed_hours": 0.0,
        "thu_hours": 7.0,
        "fri_hours": 2.5,
        "sat_hours": 0.0,
        "pdf_total": 15.5,
        "current_week_total": 15.5,
        "prior_sun_hours":    0.0,
    },
}

# The Moldovan name in the PDF has "Has" appended due to PDF layout — we
# test that the parser captures the right values regardless of the exact name.
_MOLDOVAN_VARIANTS = {"Florin Moldovan", "Florin Moldovan Has"}


@pytest.fixture(scope="module")
def parsed_travel():
    rows, warnings = parse_travel_pdf(FIXTURE_PDF)
    return rows, warnings


def test_fixture_exists():
    assert FIXTURE_PDF.exists(), f"Fixture PDF missing: {FIXTURE_PDF}"


def test_returns_rd_rows_only(parsed_travel):
    rows, _ = parsed_travel
    for row in rows:
        assert row["company"] in {"R&D", "R&D Controls", "R&D Controls Corp"}, \
            f"Non-R&D row returned: {row['company']!r}"


def test_row_count(parsed_travel):
    rows, _ = parsed_travel
    # Three R&D employees in this fixture
    assert len(rows) == 3, f"Expected 3 R&D rows, got {len(rows)}: {[r['raw_name'] for r in rows]}"


def test_week_dates_present(parsed_travel):
    rows, _ = parsed_travel
    for row in rows:
        assert row["week_start_date"] == "2026-03-23", \
            f"Week start should be 2026-03-23, got {row['week_start_date']!r}"
        assert row["week_end_date"] == "2026-03-28", \
            f"Week end should be 2026-03-28, got {row['week_end_date']!r}"
        assert row["pdf_sunday_date"] == "2026-03-22", \
            f"PDF Sunday should be 2026-03-22, got {row['pdf_sunday_date']!r}"


def test_prior_sunday_hours_zeroed_for_all(parsed_travel):
    """In this specific PDF, no employee has Sunday travel — prior_sun_hours = 0."""
    rows, _ = parsed_travel
    for row in rows:
        assert row["prior_sun_hours"] == 0.0, \
            f"{row['raw_name']!r}: unexpected prior_sun_hours {row['prior_sun_hours']}"


def test_ebbinghaus_hours(parsed_travel):
    rows, _ = parsed_travel
    row_map = {r["raw_name"]: r for r in rows}
    assert "Zachary Ebbinghaus" in row_map
    row = row_map["Zachary Ebbinghaus"]
    exp = _EXPECTED["Zachary Ebbinghaus"]
    _assert_hours(row, exp)


def test_zorzi_hours(parsed_travel):
    rows, _ = parsed_travel
    row_map = {r["raw_name"]: r for r in rows}
    assert "Jarrett Zorzi" in row_map
    row = row_map["Jarrett Zorzi"]
    exp = _EXPECTED["Jarrett Zorzi"]
    _assert_hours(row, exp)


def test_moldovan_hours(parsed_travel):
    rows, _ = parsed_travel
    row_map = {r["raw_name"]: r for r in rows}
    # Moldovan's name may have "Has" suffix from PDF layout
    moldovan_row = None
    for name, row in row_map.items():
        if "Moldovan" in name:
            moldovan_row = row
            break
    assert moldovan_row is not None, f"Moldovan not found in rows: {list(row_map.keys())}"
    exp = _EXPECTED["Florin Moldovan"]
    _assert_hours(moldovan_row, exp)


def test_current_week_totals(parsed_travel):
    rows, _ = parsed_travel
    for row in rows:
        expected_total = sum([
            row["mon_hours"], row["tue_hours"], row["wed_hours"],
            row["thu_hours"], row["fri_hours"], row["sat_hours"],
        ])
        assert row["current_week_total"] == pytest.approx(expected_total, abs=0.01), \
            f"{row['raw_name']!r}: current_week_total mismatch"


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_travel_pdf("/nonexistent/travel.pdf")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _assert_hours(row: dict, expected: dict) -> None:
    for field in ["sun_hours", "mon_hours", "tue_hours", "wed_hours",
                  "thu_hours", "fri_hours", "sat_hours",
                  "pdf_total", "current_week_total", "prior_sun_hours"]:
        assert row[field] == pytest.approx(expected[field], abs=0.01), \
            f"{row['raw_name']!r} {field}: expected {expected[field]}, got {row[field]}"
