"""
config.py — Application-wide paths and constants.

All paths resolve relative to the project root so nothing is hardcoded to a
specific machine outside of the Sage 50 export path, which is a non-negotiable
business requirement.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root — the directory that contains payroll_app/ and PLAN.md
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_PATH = PROJECT_ROOT / "payroll_app" / "database" / "payroll.db"

# ---------------------------------------------------------------------------
# Source-file storage
# Source files (PDFs, timesheets, receipts) are copied here on import so the
# app always has access to the originals.
# ---------------------------------------------------------------------------

SOURCE_FILES_DIR = PROJECT_ROOT / "payroll_app" / "data" / "source_files"

PAYROLL_PDF_DIR   = SOURCE_FILES_DIR / "payroll_pdfs"
TRAVEL_PDF_DIR    = SOURCE_FILES_DIR / "travel_pdfs"
TIMESHEET_DIR     = SOURCE_FILES_DIR / "timesheets"
RECEIPT_DIR       = SOURCE_FILES_DIR / "receipts"

# ---------------------------------------------------------------------------
# Sage 50 payroll CSV export
# This path is a non-negotiable business requirement and must not change.
# ---------------------------------------------------------------------------

SAGE50_PAYROLL_CSV_PATH = Path(
    r"C:\Users\Alkemade\OneDrive\02 R&D Controls Corp\_Employees\_Timesheets"
)


def sage50_csv_filename(period_end_date: str) -> Path:
    """Return the full Sage 50 CSV output path for a given period end date.

    Args:
        period_end_date: Date string in YYYYMMDD format (e.g. '20260329').

    Returns:
        Full path to the timesheet CSV file.
    """
    return SAGE50_PAYROLL_CSV_PATH / f"timesheet_{period_end_date}.csv"


# ---------------------------------------------------------------------------
# Reference workbooks — these are written by the app, never read for source truth
# ---------------------------------------------------------------------------

PAYROLL_CHEQUE_RUN_WORKBOOK = PROJECT_ROOT / "PayrollChequeRun_v00.xlsm"
CENTERLINE_PROFIT_WORKBOOK  = PROJECT_ROOT / "Centerline Profit - 2026.xlsm"

# ---------------------------------------------------------------------------
# Timesheet template
# ---------------------------------------------------------------------------

TIMESHEET_TEMPLATE = PROJECT_ROOT / "EmpTS - 20260329.xlsx"

# ---------------------------------------------------------------------------
# Business constants
# ---------------------------------------------------------------------------

# Centerline customer code used in employee_assignments
CENTERLINE_CUSTOMER_CODE = "CENTERLINE"

# Internal assignment type value
ASSIGNMENT_INTERNAL  = "internal"
ASSIGNMENT_BILLABLE  = "billable"

# Employees that bypass customer approval (internal-only payroll)
INTERNAL_EMPLOYEE_DISPLAY_NAMES = {"Henry Andkilde", "Matina Rahbar"}

# Per-diem does not require a receipt — all other expense categories do
PER_DIEM_CATEGORIES = {"per_diem_travel", "per_diem_full"}

# Expense categories available in the current timesheet template
EXPENSE_CATEGORIES_CAD = [
    "per_diem_travel",
    "per_diem_full",
    "lodging",
    "lodging_per_receipt",
    "luggage",
    "car_rental",
    "tolls",
    "vehicle_maintenance",
    "parking_fees",
    "taxi",
    "mileage",
]

EXPENSE_CATEGORIES_USD = EXPENSE_CATEGORIES_CAD  # same structure

# Column letters in the timesheet expense tabs for each category (cols D-N)
EXPENSE_COL_LETTERS = ["D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N"]

# ---------------------------------------------------------------------------
# Workbook cell references — do not change without updating the workbook
# ---------------------------------------------------------------------------

# PayrollChequeRun_v00.xlsm → Time Log
TIMELOG_SUBMITTED_COLS   = list("DEFGHIJKL")   # D–L: submitted timesheet hours
TIMELOG_APPROVED_COLS    = list("NOPQ")        # N–Q: customer-approved hours
TIMELOG_WAGE_RATE_COL    = "W"
TIMELOG_FORMULA_COLS     = ["X", "Y", "Z", "AA", "AB", "AC"]  # must not be overwritten

# PayrollChequeRun_v00.xlsm → Current
CURRENT_EXPORT_RANGE     = "V1:AC50"

# Centerline Profit - 2026.xlsm — protected cell
PROFIT_TRACKER_PROTECTED_CELL = "AE1"


def ensure_source_dirs() -> None:
    """Create source-file storage directories if they do not already exist."""
    for directory in [PAYROLL_PDF_DIR, TRAVEL_PDF_DIR, TIMESHEET_DIR, RECEIPT_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
