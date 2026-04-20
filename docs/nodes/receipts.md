# Node: Receipts

**Canvas IDs:** `w1_receipts`, `w2_receipts`  
**Color:** Red  
**Panel:** `ReceiptsPanel.jsx`  
**API:** `GET /api/periods/{id}/receipts?week_num={wk}`, `POST /api/periods/{id}/expenses/{exp_id}/attach-receipt`, `POST /api/periods/{id}/expenses/{exp_id}/defer`

---

## Purpose

Receipt collection and tracking for non-per-diem employee expenses within a specific week. Non-per-diem expenses cannot be reimbursed or billed until a receipt is attached or explicitly deferred.

---

## What It Does

- Lists all non-per-diem expense line items for employees in the selected week
- Per item: shows employee, category, amount, and current receipt status
- Each item has its own drop zone for attaching a receipt file
- Each item has a **Defer** button with an optional reason note
- Displays a summary bar: missing / received / deferred counts
- Shows "✓ All receipts accounted for" when `missing_count === 0`

---

## Receipt Statuses

| Status | Meaning |
|---|---|
| `missing` | No receipt attached; not deferred. Blocks billing/reimbursement. |
| `received` | Receipt file attached. Ready to bill/reimburse. |
| `deferred` | Explicitly deferred to a later period (with optional reason). Does not block. |
| `not_required` | Per-diem or admin-waived. Never blocks. |

---

## Business Rules

- **Per-diem expenses** never require receipts — they do not appear in this node
- Non-per-diem expenses require a receipt before the expense can be reimbursed or billed to Centerline
- An expense can be deferred (with a note) when the receipt is not yet available — this clears the blocking flag for that item
- Receipt files are stored under `cfg.RECEIPT_DIR` with a safe filename: `{period_id}_{expense_id}_{original_filename}`
- The original filename is preserved in `expense_receipts.original_filename` for audit purposes

---

## Week Filtering

Receipts are filtered to show only expenses with dates falling within the specific week (Mon–Sun). Week 1 and Week 2 receipts are separate nodes showing separate data.

---

## Inputs

- Feeds from → **Timesheets** (expense line items from employee timesheets)

---

## Outputs

- Feeds into → **Verify** (Receipts is a gate before Verify; missing receipts show ⚠ in Verify)

---

## Status Indicators

- Red: receipts missing
- Yellow: all accounted for (received or deferred)
- Green: no non-per-diem expenses this week
