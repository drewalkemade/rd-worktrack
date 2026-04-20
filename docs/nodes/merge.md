# Node: Merge

**Canvas ID:** `merge`  
**Color:** Teal  
**Panel:** `MergePanel.jsx` (stub)  
**API:** `POST /api/periods/{id}/reconcile` (planned)

---

## Purpose

Combines both verified, invoiced weeks into the biweekly reconciliation. Triggers the payroll reconciler which produces the final employee payroll totals ready for `PayrollChequeRun_v00.xlsm` and the Sage 50 export.

---

## What It Does (planned)

- Requires both Week 1 and Week 2 to be fully verified and exported
- Calls `reconciler.reconcile_pay_period()` to:
  - Sum both weeks of approved hours per employee
  - Apply REG/OT/DBL classification rules (40-hour threshold for regular weeks, 32 for holiday weeks)
  - Travel hours excluded from OT threshold accumulation
  - Produce biweekly payroll totals per employee
- Writes results to `reconciled_hours` table
- Marks the pay period as `reconciled`

---

## REG/OT/DBL Classification Rules

| Condition | Classification |
|---|---|
| Qualifying work hours ≤ 40h (normal week) | Regular |
| Qualifying work hours > 40h | OT (1.5×) |
| Statutory holiday day | Double time for hours worked |
| Travel hours | Always Regular (excluded from OT count) |
| Holiday week threshold | 32h instead of 40h |

Note: Reclassification may change how hours from the payroll PDF are classified. The payroll PDF's REG/OT/DBL columns are the customer's classification; the reconciler applies R&D's payroll rules which may differ.

---

## Inputs

- Feeds from → **Invoice Export** Wk 1 and Wk 2 (both weeks must be complete)

---

## Outputs

- Feeds into → **Modified Timesheets**

---

## Status

Currently a stub node. The `reconciler.py` module exists; the API endpoint and panel are not yet built.
