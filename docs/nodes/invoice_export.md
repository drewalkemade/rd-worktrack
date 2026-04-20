# Node: Invoice Export

**Canvas IDs:** `w1_invoice_export`, `w2_invoice_export`  
**Color:** Green  
**Panel:** `InvoiceExportPanel.jsx` (stub)  
**API:** TBD

---

## Purpose

Export the finalized weekly invoice data in a format ready for entry into Sage 50. The invoice document itself is printed by Sage 50 — this node produces the data that gets keyed in (or imported).

---

## What It Produces

A structured summary per employee containing all the values needed to enter the invoice into Sage 50:

```
Employee: Daniel Trif
  005-1-2026-001  Regular          38.0 h  ×  $72.00  =  $2,736.00
  005-1-2026-002  Overtime 1        0.0 h  ×  $93.60  =  —
  005-1-2026-003  Overtime 2       12.0 h  × $122.40  =  $1,468.80
  005-1-2026-100  Travel            8.0 h  ×  $72.00  =  $576.00
  005-0-2025-101  Per Diem          5.0 days × $70.00 =  $350.00
  005-0-2025-102  Expenses          —  (no expenses this period)
```

Output formats:
- **On-screen summary** — for manual Sage 50 entry
- **CSV export** — for bulk import if Sage 50 supports it

---

## Item Number Scheme

Item numbers include a year component and may be updated annually:
- Labor/travel: `005-1-YYYY-NNN` (e.g. `005-1-2026-001`)
- Per diem / expenses: `005-0-YYYY-NNN` (e.g. `005-0-2025-101`)

The app must store these as configurable values, not hardcoded.

---

## Zero-Quantity Lines

All 6 standard line types must be included for every employee, even when quantity = 0. Sage 50 needs the full line set to print the invoice in the correct format.

---

## HST

All line items carry tax code `H` (HST 13%). The app displays the pre-HST amounts; Sage 50 calculates and adds HST on print.

---

## Inputs

- Feeds from → **Invoice** (computed biweekly totals per employee)

---

## Outputs

- Feeds into → **Merge** (invoice export completion gates the merge step)

---

## Status

Currently a stub node. Implemented after Invoice is complete.
