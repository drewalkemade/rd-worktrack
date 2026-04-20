# Node: Approved Hours

**Canvas IDs:** `w1_approved_hours`, `w2_approved_hours`  
**Color:** Blue  
**Panel:** `ApprovedHoursPanel.jsx`  
**API:** `GET /api/periods/{id}/weeks/{wk}/approved-hours`, `POST /api/periods/{id}/import-payroll-pdf`, `POST /api/periods/{id}/import-travel-pdf`

---

## Purpose

Import and review customer-approved hours for a single business week (Mon–Sun). Combines the payroll PDF (total hours per day) with the travel PDF (per-day travel breakdown) to produce the **adjusted approved hours** — the canonical labor hours carried forward into Compare and Resolve.

---

## What It Does

- Accepts the weekly Payroll PDF and Travel PDF via drag-and-drop or file picker
- Parses payroll PDF using `pdf_parser_v2.py` → stores into `customer_hours` and `customer_daily_hours`
- Parses travel PDF using `travel_parser.py` → stores into `travel_hours`
- Displays three sections:
  1. **Adjusted Approved Hours** — per-employee, per-day: `labor = PDF total − travel_day`
  2. **Payroll PDF Extract** — raw clock-in/out rows as parsed
  3. **Travel PDF Extract** — raw per-day travel hours (Sun–Sat range)

---

## Travel Time Rules (Critical)

Travel hours are extracted from the Travel PDF and must be treated separately throughout the system:

| Property | Rule |
|---|---|
| Paid as | Always Regular Time |
| Counts toward OT threshold | ❌ No |
| Sunday travel | Regular Time (even though Sunday work = Double Time) |
| OT threshold (normal week) | 40 qualifying work hours (travel excluded) |
| OT threshold (holiday week) | 32 qualifying work hours (travel excluded) |

When adjusting timesheets: if hours shift between work and travel, the OT calculation must be recomputed. Full REG/OT/DBL reclassification accounting for travel happens in the **Reconcile** node.

---

## Travel PDF Date Handling

The travel PDF covers **Sun–Sat**, while the business week is **Mon–Sun**:

- `sun_hours` from the travel PDF = Sunday at the *start* of the Sun–Sat range → belongs to the **prior** business week
- `mon_hours` through `sat_hours` → current business week Mon–Sat
- `current_sun_hours_assumed` → Sunday at the *end* of the business week, populated from the **following** week's travel PDF `sun_hours`, or assumed from the employee timesheet drive hours (requires a note)
- If no travel PDF is available for a week, travel defaults to 0

---

## Adjusted Approved Hours (canonical)

```
labor_day  = max(0, pdf_total_day − travel_day)
labor_week = sum(labor_day for each day)
```

These are the numbers carried forward to **Compare** (vs timesheet labor) and **Resolve** (per-day adjudication).

---

## Inputs

- Feeds from → **Employees** (name resolution)
- Feeds from → **Timesheets** (week date context)
- Feeds from → **Payroll PDF** drop zone (w1_payroll_pdf / w2_payroll_pdf)
- Feeds from → **Travel PDF** drop zone (w1_travel_pdf / w2_travel_pdf)

---

## Outputs

- Feeds into → **Compare** (adjusted labor hours for day-level comparison)

---

## Status Indicators

- Green: both payroll PDF and travel PDF imported
- Yellow: payroll PDF imported, no travel PDF (travel defaults to 0)
- Red/empty: no payroll PDF imported
