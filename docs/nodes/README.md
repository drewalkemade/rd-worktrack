# Workboard Node Definitions

Each file defines one logical node type on the React Flow canvas. Per-week nodes (w1_X / w2_X) share a single definition file.

| File | Node(s) | Color | Status |
|---|---|---|---|
| [employees.md](employees.md) | `employees` | Purple | ✓ Working |
| [timesheets.md](timesheets.md) | `timesheets` | Green | ✓ Working |
| [payroll_pdf.md](payroll_pdf.md) | `w1_payroll_pdf`, `w2_payroll_pdf` | Blue | ✓ Working |
| [travel_pdf.md](travel_pdf.md) | `w1_travel_pdf`, `w2_travel_pdf` | Blue | ✓ Working |
| [approved_hours.md](approved_hours.md) | `w1_approved_hours`, `w2_approved_hours` | Blue | ✓ Working |
| [receipts.md](receipts.md) | `w1_receipts`, `w2_receipts` | Red | ✓ Working |
| [compare.md](compare.md) | `w1_compare`, `w2_compare` | Orange | ✓ Working |
| [resolve.md](resolve.md) | `w1_correct`, `w2_correct` | Orange | ✓ Working |
| [verify.md](verify.md) | `w1_verify`, `w2_verify` | Orange | ✓ Working |
| [invoice.md](invoice.md) | `w1_invoice`, `w2_invoice` | Green | Stub |
| [invoice_export.md](invoice_export.md) | `w1_invoice_export`, `w2_invoice_export` | Green | Stub |
| [merge.md](merge.md) | `merge` | Teal | Stub |
| [modified_timesheets.md](modified_timesheets.md) | `modified_timesheets` | Teal | Stub |
| [export.md](export.md) | `export_sage50`, `export_summary`, `export_drewedit` | Green | Stub |

## Canvas Flow (left to right)

```
Employees ──────────────────────────────────────────────────────────────────────────────────────────┐
                                                                                                      │
Timesheets ──────────────────────────────────────────────────────────────────────────────────────────│─┐
                                                                                                      │ │
                         ┌── Wk 1 ──────────────────────────────────────────────────────────────┐    │ │
Payroll PDF (Wk1) ──┐    │                                                                       │    │ │
Travel PDF (Wk1) ───┼──► Approved Hours ──► Compare ──► Resolve ──► Verify ──► Invoice ──► Inv. Export ─┼─┐
Employees ──────────┘    │                                                               ▲         │    │ │ │
Timesheets ──────────────┘                                          Receipts ────────────┘         │    │ │ │
                                                                                                   │    │ │ │
                         ┌── Wk 2 ──────────────────────────────────────────────────────────────┐ │    │ │ │
Payroll PDF (Wk2) ──┐    │                                                                       │ │    │ │ │
Travel PDF (Wk2) ───┼──► Approved Hours ──► Compare ──► Resolve ──► Verify ──► Invoice ──► Inv. Export ─┼─┘ │
Employees ──────────┘    │                                               ▲              │         │ │    │   │
Timesheets ──────────────┘                              Receipts ────────┘              │         │ │    │   │
                                                                                        └─────────┼─┘    │   │
                                                                                                  │      │   │
                                                                                               Merge ◄──┘   │
                                                                                                  │          │
                                                                                     Modified Timesheets ◄──┘
                                                                                       │         │         │
                                                                                   Sage50 CSV  Summary  DrewEdit XLSX
```
