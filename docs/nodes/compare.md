# Node: Compare

**Canvas IDs:** `w1_compare`, `w2_compare`  
**Color:** Orange  
**Panel:** `ComparePanel.jsx`  
**API:** `GET /api/periods/{id}/weeks/{wk}/verification`, `POST /api/periods/{id}/weeks/{wk}/verify`, `GET /api/periods/{id}/weeks/{wk}/day-comparison`

---

## Purpose

Side-by-side comparison of **adjusted approved hours** (from the Approved Hours node) against **employee timesheet hours** for the same week. Runs the weekly verification engine and surfaces variances that require adjudication in the Resolve node.

---

## What It Does

- Calls `run_weekly_verification()` to compute per-employee verification state
- Displays a weekly summary table: employee | approved REG/OT/DBL/Travel | timesheet REG/OT1/OT2/Drive | variance
- Each row is expandable to show per-day approved hours (clock-in/out) vs timesheet hours
- Assigns per-employee status:
  - `pending` — not yet compared or verified
  - `needs_review` — variance detected between approved and timesheet
  - `verified` — owner has manually confirmed this employee/week

---

## Comparison Logic

The comparison uses **adjusted approved hours** — payroll PDF daily total minus per-day travel hours from the travel PDF:

```
approved_labor_day = max(0, pdf_total_day − travel_day)
timesheet_labor    = reg_hours + ot1_hours + ot2_hours   (drive_hours excluded)
difference         = approved_labor_day − timesheet_labor
```

`drive_hours` from the timesheet is NOT included in the comparison — the approved side already accounts for travel via the travel PDF subtraction.

---

## Variance Threshold

A day is flagged as a mismatch when `|difference| ≥ 0.01` hours.

---

## Sunday Special Case

Sunday exists in the employee timesheet but may be absent from the payroll PDF (travel PDF covers the prior Sunday). When Sunday has timesheet hours but no approved entry, it is flagged as `is_sunday_missing_from_approved`. This flows to the Resolve node for adjudication.

---

## Expense Review Flag

If an employee has non-per-diem expenses with receipts still in `missing` status (not `received` or `deferred`), the `needs_expense_review` flag is set. This is advisory — it does not block verification.

---

## Inputs

- Feeds from → **Approved Hours** (adjusted labor hours per day)
- Feeds from → **Timesheets** (employee daily rows)

---

## Outputs

- Feeds into → **Resolve** (employees with `needs_review` status)
- Feeds into → **Verify** (all employees after variances are resolved)

---

## Status Indicators

- `✓ verified` count / total employees
- `needs_review` count (unresolved variances)
