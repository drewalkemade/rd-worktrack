# Node: Resolve

**Canvas IDs:** `w1_correct`, `w2_correct`  
**Color:** Orange  
**Panel:** `ResolvePanel.jsx`  
**API:** `POST /api/periods/{id}/weeks/{wk}/correct`, `GET /api/periods/{id}/weeks/{wk}/corrections`

---

## Purpose

Per-day source adjudication for employees where the adjusted approved hours differ from the employee's timesheet. The owner explicitly chooses which source is authoritative for each mismatched day. Nothing is written to Excel here — decisions are persisted to `correction_log` and applied later by the DrewEdit export node.

---

## What It Does

- Shows each employee with a variance (status = `needs_review`)
- For each mismatched day, displays:
  - Approved side: raw PDF total → adjusted labor (e.g. `10.00h PDF − 4.00h travel`)
  - Timesheet side: labor hours (reg + OT) + drive hours shown separately as context
  - Δ difference
- Owner picks one of two resolutions per day:
  - **Approved is correct** → CL hours win; DrewEdit will rewrite the timesheet cell and add a generated note
  - **Timesheet is correct** → Employee hours stand; no XLSX change needed
- For Sunday-missing cases, "Timesheet is correct" requires confirming the employee's name (recorded in `correction_log.confirmed_with`)

---

## Resolution Storage

Each resolution is stored in `correction_log` with:
- `employee_id`, `work_date`, `weekly_approval_id`
- `correction_type`: `approved_wins` | `timesheet_wins`
- `approved_total_hours`, `timesheet_total_hours`, `difference`
- `is_sunday_missing`, `confirmed_with` (Sunday only)
- `generated_note`: auto-generated text that will be written into the DrewEdit XLSX

---

## After Resolving

- Re-run **Compare** (re-runs verification) to confirm all variances cleared
- Then proceed to **Verify** (manual owner sign-off per employee)
- The **DrewEdit XLSX** export node will apply all `approved_wins` corrections to the employee's timesheet and write the generated notes

---

## Inputs

- Feeds from → **Compare** (employees with `needs_review` status and per-day mismatch data)

---

## Outputs

- Feeds into → **Verify** (unblocks employees once all days are resolved)

---

## Status Indicators

- "X variances" per employee section header
- `✓ all resolved` once all days in the section have been adjudicated
- Global "✓ All variances resolved" banner when every `needs_review` employee is complete
