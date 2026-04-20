# Node: Timesheets

**Canvas ID:** `timesheets`  
**Color:** Green  
**Panel:** `TimesheetsPanel.jsx`  
**API:** `GET /api/periods/{id}/timesheets`, `POST /api/periods/{id}/import-timesheet`

---

## Purpose

Import and review employee-submitted biweekly timesheets (`.xlsx` workbooks). One timesheet covers 14 days (two full Mon–Sun business weeks).

---

## What It Does

- Accepts `.xlsx` timesheet files via drag-and-drop or file picker (one per employee)
- Parses the timesheet using `timesheet_extractor_v2.py`
- Stores daily rows into `timesheet_daily_hours` (one row per employee per day)
- Displays per-employee summary: REG / OT1 / OT2 / Drive / Sick / Vacation / Holiday / Non-billable hours
- Shows import warnings for missing expected columns, unexpected values, etc.

---

## Business Rules

- Daily rows are stored as first-class data — weekly comparison depends on day-level granularity
- If the owner has corrected a timesheet, the `_DrewEdit.xlsx` version is preferred over the original
- Original source files are never overwritten — corrected versions use `*_DrewEdit.xlsx` naming
- Both weeks of the pay period must be importable from a single timesheet file

---

## Inputs

- Feeds from → **Employees** (employee resolution)

---

## Outputs

- Feeds into → **Approved Hours** Wk 1 & 2 (for the week-date filter in Compare)
- Feeds into → **Compare** Wk 1 & 2 (timesheet side of comparison)
- Feeds into → **Receipts** Wk 1 & 2 (drive hours used for per-diem checks)

---

## Status Indicators

- Number of timesheets imported vs employees expected
- Warning badge if any employee is missing a timesheet
