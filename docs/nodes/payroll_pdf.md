# Node: Payroll PDF

**Canvas IDs:** `w1_payroll_pdf`, `w2_payroll_pdf`  
**Color:** Blue  
**Panel:** Embedded drop zone inside `ApprovedHoursPanel.jsx`  
**API:** `POST /api/periods/{id}/import-payroll-pdf`

---

## Purpose

Drop zone for the weekly customer payroll approval PDF. These are Centerline-issued PDFs showing the hours each R&D Controls employee worked that week, with clock-in/clock-out times and a daily total.

---

## What It Does

- Accepts a PDF file (drag-and-drop or click-to-browse)
- Parses using `pdf_parser_v2.py`
- Extracts per-employee daily rows: clock-in, clock-out, total hours, day type (REG/OT/DBL)
- Stores into `customer_daily_hours` and sums into `customer_hours`
- Associates with the correct `weekly_approval` via the `week_ending` date

---

## File Naming

Centerline sends PDFs with long descriptive names (e.g. `R&D Controls Payroll Approval 2026-04-07 09.26.42.pdf`). For internal filing they are renamed to `R&D_YYMMDD-xxxxx.pdf` where `YYMMDD` is the Sunday ending the business week. Both naming formats are supported on import.

---

## Important Notes

- The payroll PDF `total_hours` per day includes **both labor and travel** — travel is not separated at the PDF level
- Travel separation happens in the **Approved Hours** node by subtracting per-day travel from the travel PDF
- Re-importing a payroll PDF performs an UPDATE (upsert) — it does not duplicate records

---

## Inputs

None (file upload entry point)

---

## Outputs

- Feeds into → **Approved Hours** (raw daily data used as the starting point for labor/travel split)
