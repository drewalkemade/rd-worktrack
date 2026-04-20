# Node: Verify

**Canvas IDs:** `w1_verify`, `w2_verify`  
**Color:** Orange  
**Panel:** `VerifyPanel.jsx`  
**API:** `GET /api/periods/{id}/weeks/{wk}/verification`, `POST /api/periods/{id}/weeks/{wk}/set-verified/{employee_id}`

---

## Purpose

Manual owner sign-off per employee per week. Replaces the blue-highlight step in the legacy `RawData` spreadsheet. The owner explicitly confirms that each employee's week has been reviewed and is ready to bill.

---

## What It Does

- Lists all employees in the week with their current status:
  - `pending` — not yet verified
  - `needs_review` — variance detected (see Resolve node) — shows ⚠ Variance badge
  - `verified` — owner has signed off
- Owner clicks **Verify** per employee (or **Verify All** for a batch confirm)
- Verified employees are recorded in `weekly_employee_verification` with a timestamp

---

## Business Rules

- `needs_review` employees are **not hard-blocked** — the owner retains authority to verify them directly (matching the original Excel workflow where the owner could blue-highlight regardless of variance state)
- Employees with a ⚠ Variance badge have unresolved mismatches. The Resolve node should be used to adjudicate these first, but Verify does not enforce it
- An optional note can be attached to any verification (required if overriding a `needs_review`)
- Receipts (non-per-diem expenses) must be `received` or `deferred` before the Receipts node clears — but Verify itself is not blocked by receipt status

---

## Prerequisite Gates

Before the week proceeds to Invoice:
1. All employees must have status `verified` (or the owner must acknowledge any `needs_review` remaining)
2. The Receipts node must show no `missing` receipts (all are `received` or `deferred`)

---

## Inputs

- Feeds from → **Resolve** (resolved variances update employee status to `needs_review` → re-run Compare to clear to `pending` or confirm `verified`)
- Feeds from → **Receipts** (expense review flag; Receipts is an upstream gate)

---

## Outputs

- Feeds into → **Invoice** (weekly sign-off is a prerequisite for billing)

---

## Status Indicators

- `X / Y verified` counter
- `⚠ X needs review` count
- Green border when all employees are verified
