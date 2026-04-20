# Node: Invoice

**Canvas IDs:** `w1_invoice`, `w2_invoice`  
**Color:** Green  
**Panel:** `InvoicePanel.jsx` (stub)  
**API:** TBD

---

## Purpose

Produce the **weekly** customer invoice data for a single Mon–Sun business week, for entry into Sage 50. Sage 50 prints and sends the invoice to Centerline (Windsor) Limited.

The app's job is to compute the correct quantities and amounts for each line item — the actual invoice document is printed by Sage 50.

---

## Real Invoice Structure (Invoice 2719 — week ending 03/22/2026)

### Header (static / config)
```
R&D Controls Corp.
1201 Outram Avenue, LaSalle, Ontario N9J 3R9, Canada
HST# 83448 1400 RT0001
Terms: Net 30
Sold to / Ship to: Centerline (Windsor) Limited, 415 Morton Drive, Windsor, Ontario N9J 3T8
```

### Line Items — Per Employee

Every employee gets exactly **6 standard line types**, always listed in order even if quantity = 0:

| Item No. | Description | Unit Price | Notes |
|---|---|---|---|
| `005-1-2026-001` | Centerline - Standard - Regular | $72.00/h | |
| `005-1-2026-002` | Centerline - Standard - Overtime 1 | $93.60/h | 1.3× regular |
| `005-1-2026-003` | Centerline - Standard - Overtime 2 | $122.40/h | 1.7× regular |
| `005-1-2026-100` | Centerline - Standard - Travel | $72.00/h | Always = regular rate |
| `005-0-2025-101` | Centerline Per Diem | $70.00/day | Quantity = number of days |
| `005-0-2025-102` | Centerline Expenses | actual $ | One line per receipt |

Plus **one line per expense receipt** using item `005-0-2025-102` with a description suffix, e.g.:
- `Centerline Expenses - Luggage` @ $49.24
- `Centerline Expenses - Fuel` @ $87.00

Zero-quantity rows are listed with unit price only (no amount column value) — they must still appear for every employee.

### Totals
- **Subtotal**: sum of all employee line amounts
- **HST 13% (code H)**: subtotal × 0.13
- **Total**: subtotal + HST
- **Amount Paid**: 0.00
- **Amount Owing**: = Total

---

## Billing Rates (current)

| Type | Rate | Billing Rule |
|---|---|---|
| Regular | $72.00/h | Qualifying work hours ≤ weekly OT threshold |
| Overtime 1 | $93.60/h | Qualifying work hours over OT threshold (1st tier) |
| Overtime 2 | $122.40/h | Double-time work (statutory holidays, etc.) |
| Travel | $72.00/h | Always regular rate regardless of day |
| Per Diem | $70.00/day | Count of per-diem days from expense tabs |
| Expenses | actual | Per-receipt, net of HST |

Rates are stored per-employee (or per-customer) and are effective-dated.

---

## What the App Must Produce

For Sage 50 entry, the app needs to output per employee per week:
- `reg_hours` — qualifying regular hours (post-reclassification for this week)
- `ot1_hours` — OT1 hours
- `ot2_hours` — OT2 / double-time hours
- `travel_hours` — total travel hours (billed at regular rate)
- `per_diem_days` — count of per-diem days from expense tab
- List of `(expense_description, amount)` tuples for non-per-diem expenses with receipts attached

From these, Sage 50 calculates amounts and prints the invoice.

---

## Inputs

- The week must be fully **Verified** (all employees signed off)
- **Reclassification** must be complete for this week (REG/OT/DBL correctly computed)
- **Receipts** must be `received` or `deferred` for all non-per-diem expenses

---

## Outputs

- Feeds into → **Invoice Export**

---

## Status

Currently a stub node. The data model for billing rates needs to be added to the schema. Implementation after Merge/Reconcile is complete.
