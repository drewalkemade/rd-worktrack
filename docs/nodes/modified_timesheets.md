# Node: Modified Timesheets

**Canvas ID:** `modified_timesheets`  
**Color:** Teal  
**Panel:** `ModifiedTimesheetsPanel.jsx` (stub)  
**API:** TBD — `POST /api/periods/{id}/generate-drewedit`

---

## Purpose

Generates corrected employee timesheet files (`*_DrewEdit.xlsx`) for any employee whose Resolve node decisions included `approved_wins` corrections. Preserves the original source timesheet — corrections are written to a separate copy.

---

## What It Does (planned)

- Queries `correction_log` for all `approved_wins` decisions in this pay period
- For each affected employee:
  - Copies the original `.xlsx` timesheet
  - Renames the copy as `{employee}_DrewEdit.xlsx`
  - Overwrites the corrected day cells with the approved values
  - Inserts the `generated_note` from `correction_log` into the appropriate note cell
- Records the DrewEdit file path in `source_files` with `file_type = 'drewedit_timesheet'`
- Never modifies the original source timesheet

---

## Business Rules

- Original source files are **never overwritten**
- If a `_DrewEdit.xlsx` already exists for an employee, it is used as the base (not the original)
- The generated note format is standardized so it can be audited and understood without the app
- This node produces no output on its own — it gates the three export nodes

---

## Inputs

- Feeds from → **Merge** (reconciliation must be complete before DrewEdit generation)

---

## Outputs

- Feeds into → **Sage50 CSV**, **Summary CSV**, **DrewEdit XLSX** (all three export nodes)

---

## Status

Currently a stub node. `pipeline/drewedit_writer.py` is not yet implemented.
