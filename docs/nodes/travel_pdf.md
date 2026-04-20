# Node: Travel PDF

**Canvas IDs:** `w1_travel_pdf`, `w2_travel_pdf`  
**Color:** Blue  
**Panel:** Embedded drop zone inside `ApprovedHoursPanel.jsx`  
**API:** `POST /api/periods/{id}/import-travel-pdf`

---

## Purpose

Drop zone for the weekly customer travel PDF. Centerline issues one travel PDF per business week showing how many travel hours each employee drove, broken out by day across a **Sun–Sat** date range.

---

## What It Does

- Accepts a PDF file (drag-and-drop or click-to-browse)
- Parses using `travel_parser.py`
- Extracts per-employee per-day travel hours: Sun, Mon, Tue, Wed, Thu, Fri, Sat
- Stores into `travel_hours` table (one row per employee per weekly approval)
- Applies the prior-Sunday attribution: `sun_hours` from this PDF belongs to the **prior** business week's `current_sun_hours_assumed`
- `current_week_total` = Mon–Sat hours only (the Sun-start belongs to the prior week)

---

## Date Range Mismatch

The travel PDF covers **Sun–Sat** but the business week is **Mon–Sun**:

| Travel PDF column | Business week attribution |
|---|---|
| `sun_hours` | Prior Mon–Sun week |
| `mon_hours` – `sat_hours` | Current Mon–Sun week |
| Next PDF's `sun_hours` | Current week's `current_sun_hours_assumed` |

If the next week's travel PDF is not yet available, Sunday travel at the end of the business week can be assumed from the employee's timesheet drive hours using `assume_travel_from_timesheet()`. A note is required.

---

## File Naming

Files are named `R&D_YYMMDD-Travel.pdf` where `YYMMDD` is the **Sunday starting** the Sun–Sat range.

---

## When No Travel PDF Exists

Travel defaults to 0 for all employees that week. This is normal — not all weeks have travel. The `current_sun_status` field will remain `pending_next_pdf` until the following week's PDF arrives or travel is assumed from the timesheet.

---

## Inputs

None (file upload entry point)

---

## Outputs

- Feeds into → **Approved Hours** (per-day travel amounts used to separate labor from travel in the adjusted approved hours)
