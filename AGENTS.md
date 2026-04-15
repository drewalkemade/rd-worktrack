# R&D Controls Corp — Timesheet Ecosystem

**Company:** R&D Controls Corp (co-owned by Drew Alkemade and Rick)
**Project:** Full ecosystem rework — replacing the current manual payroll / billing / reimbursement workflow with a React + FastAPI app
**Repo:** `F:\GitHub\rd-worktrack` (WSL: `/mnt/f/GitHub/rd-worktrack`)
**Source of truth plan:** `PLAN.md` (in this repo)
**Backup plan file:** `/home/drew/.claude/plans/frolicking-forging-sphinx.md`

---

## What This Project Does

Automates and controls four linked workflows:
1. Weekly customer-approved labor/travel intake for billing
2. Biweekly employee timesheet intake for payroll
3. Biweekly payroll reconciliation and Sage 50 payroll export
4. Employee expense reimbursement + receipt tracking + customer-billable expense support

This project affects:
- payroll
- customer billing
- employee expense reimbursement
- tax/audit support

Accuracy and traceability matter more than speed.
Code simplicity and debuggability matter more than cleverness.

---

## Pay Cadence — Critical

- **Customer payroll PDFs arrive weekly** for a Mon–Sun work week
- **Customer travel PDFs arrive weekly** but are formatted Sun–Sat
- **Employee timesheets are biweekly** — one `.xlsx` covers 14 days
- **Payroll cheque runs are biweekly** — both weekly approvals are needed before reconciliation
- **Employee expense reimbursement is separate from payroll** and usually happens later, by expense cheque

---

## Current Business Controls — Critical

The current system includes an important manual weekly verification step in:
- `Centerline Profit - 2026.xlsm` → `RawData`

Today, the owner:
- visually compares weekly approved hours against the corresponding week in the employee timesheet
- highlights rows **brown** when expenses or additional checking may be needed
- highlights rows **blue** once that employee/week has been visually verified
- writes manual notes beside an employee when the weekly expense situation does not fit `RawData` well

These visual controls are real business logic and must be replaced with structured application state, not removed.

---

## Engineering Principles

Prefer:
- explicit, verbose, debug-friendly code
- small modules with obvious responsibilities
- straightforward SQL and workbook logic
- readable validation and audit trails

Avoid:
- abstraction-heavy design
- compact code that is hard to debug
- hidden business logic

The system should be structured cleanly enough that it could later be taught step-by-step as a course.

---

## Files In This Directory

| File | Purpose |
|------|---------|
| `PLAN.md` | Active source of truth for architecture, workflow, and implementation sequencing |
| `EmpTS - 20260329.xlsx` | Current employee timesheet template: labor + CAD/USD expense tabs |
| `R&D_260329-xxxxx.pdf` | Sample weekly customer payroll approval PDF |
| `R&D_260329-Travel.pdf` | Sample weekly customer travel PDF |
| `PayrollChequeRun_v00.xlsm` | Payroll engine: Time Log, Current, Worksheet |
| `Centerline Profit - 2026.xlsm` | Billing tracker and current weekly visual verification board |
| `example/` | Sample employee timesheets and legacy CSV outputs |
| `example-expense/2020_EmployeeExpenses.xlsx` | Current manual employee expense staging workbook before Sage 50 entry |
| `example-invoice/` | Sample customer invoice + sample receipt files |
| `python-payroll_data_extract/` | Existing legacy Tkinter/Python extractor app used as reference/fallback |

---

## File Naming Reality

Centerline sends PDFs with long descriptive names, for example:
- `R&D Controls Payroll Approval 2026-04-07 09.26.42.pdf`
- `Contractor Travel Hrs - March 29-April 4, 2026.pdf`

For internal filing efficiency, they are manually renamed to:
- `R&D_YYMMDD-xxxxx.pdf`
- `R&D_YYMMDD-Travel.pdf`

The future app should support ingesting the original filenames while preserving the internal normalized naming convention.

---

## Target Architecture

```text
payroll_app/
├── app.py                          # legacy Streamlit entry (archived; no longer primary)
├── config.py
├── api/
│   ├── __init__.py
│   └── main.py                     # FastAPI backend (port 8000)
├── database/
│   ├── db.py
│   ├── schema.sql
│   ├── migrations/
│   └── employee_manager.py
├── extractors/
│   ├── pdf_parser_v2.py
│   ├── travel_parser.py
│   ├── timesheet_extractor_v2.py
│   └── receipt_ingest.py
├── pipeline/
│   ├── importer.py
│   ├── weekly_verifier.py
│   ├── reconciler.py
│   ├── cheque_run_writer.py
│   ├── profit_tracker_writer.py
│   ├── expense_exporter.py
│   └── exporter.py
├── pages/                          # archived Streamlit pages (prefixed with _)
│   ├── 0_Workboard.py
│   ├── _1_Dashboard.py … _7_Reports.py
└── frontend/                       # React + Vite (port 5173)
    ├── src/
    │   ├── main.jsx
    │   ├── App.jsx                  # root: topbar + canvas + side panel
    │   ├── canvas.jsx               # React Flow canvas (20 nodes, 22 edges)
    │   ├── api.js                   # Axios client → FastAPI
    │   ├── index.css
    │   ├── nodes/WorkboardNode.jsx
    │   └── panels/
    │       ├── EmployeesPanel.jsx
    │       └── TimesheetsPanel.jsx
    └── package.json
```

**To run:**
```bash
# Terminal 1 — backend
source .venv/bin/activate
uvicorn payroll_app.api.main:app --reload --port 8000

# Terminal 2 — frontend
cd payroll_app/frontend && npm run dev
# opens http://localhost:5173
```

---

## Key Technical Decisions

**SQLite** is the source of truth.

**Daily timesheet detail is required.**
- Employee timesheets are biweekly
- Weekly billing verification depends on week-by-week comparison
- Therefore daily timesheet rows must be stored as first-class data, not just biweekly totals

**Weekly verification is a first-class workflow.**
- Replace brown/blue highlighting in `RawData` with structured per-employee/per-week verification state

**Employee identity needs alias support.**
- Payroll PDF names
- Travel PDF names
- Display names
- Legacy expense codes
- Receipt filenames

**Travel PDF handling needs special treatment.**
1. It contains all vendors, not just R&D Controls employees
2. Its date range is Sun–Sat while the business week is Mon–Sun
3. Sunday travel belongs to the prior Mon–Sun week
4. The second Sunday of a pay period may need to be assumed from the employee timesheet until the next travel PDF arrives

**Expense reimbursement is separate from payroll.**
- Employees are reimbursed by separate expense cheque
- They are set up as vendors in Sage 50
- Non-per-diem expenses require receipts before reimbursement

**Per diem and other expenses are distinct.**
- Per diem always comes from the employee expense tabs
- Per diem does not require receipts
- Non-per-diem expenses generally require receipts
- Most employee expenses are billable back to Centerline

**Manual overrides are allowed but must be explicit.**
- Never silently overwrite money-affecting values
- Require notes/audit for payroll, billing, reimbursement, or identity overrides

**Employee assignment is effective-dated, not hardcoded.**
- Employees can move between internal and Centerline-billable work over time
- New employees, returning employees, and terminated employees must be supported without rewriting history

**Employee-side template validation is part of the design.**
- Future template improvements should include clearer expense handling, `Fuel`, `Other`, and warning/validation support
- Examples include offsite/per diem checks, receipt-required warnings, and late-submission flags

**Source document access is required.**
- The app should let the owner open payroll PDFs, travel PDFs, employee timesheets, and receipts directly from review workflows
- This supports manual inspection, screenshots, and fast issue resolution

**Manual timesheet corrections should preserve the original file.**
- If the owner edits an employee timesheet, the system should save a separate edited copy rather than overwriting the source
- Edited copies should use a clear owner-edit naming convention such as `*_DrewEdit.xlsx`
- The app should record what changed and audit the edit

**Reporting is a first-class feature.**
- The app should support operational dashboards, profit reporting, and manual-verification queues
- Reports should include blocked items, receipt backlog, variances, and employee/overall profitability

**The billing workbook is higher risk than the payroll workbook.**
- `PayrollChequeRun_v00.xlsm` remains the payroll output workbook
- `Centerline Profit - 2026.xlsm` — the Phase 1 safety gate FAILED (openpyxl cannot open it)
- `profit_tracker_writer.py` must write to a rebuilt `.xlsx` target, not the `.xlsm` directly

---

## Known Employees (confirmed from PDF parsing, 2026-04-14)

| Display Name       | PDF Name            | PDF ID | Centerline ID | Type      | Notes                      |
|--------------------|---------------------|--------|---------------|-----------|----------------------------|
| Jeremy Atkinson    | ATKINSON, JEREMY    | E8022  | 8022          | Billable  | No R&D timesheet           |
| Jeremy Wiseman     | WISEMAN, JEREMY     | E8031  | 8031          | Billable  | No R&D timesheet           |
| Richard Renwick    | RENWICK, RICHARD    | E8041  | 8041          | Billable  | No R&D timesheet           |
| Jerry Jeremias     | JEREMIAS, JERRY     | E8174  | 8174          | Billable  |                            |
| Daniel Trif        | TRIF, DANIEL        | E8190  | 8190          | Billable  |                            |
| Zachary Ebbinghaus | EBBINGHAUS, ZACHARY | E8395  | 8395          | Billable  |                            |
| Jarrett Zorzi      | ZORZI, JARRETT      | E8611  | 8611          | Billable  |                            |
| Florin Moldovan    | MOLDOVAN, FLORIN    | E8650  | 8650          | Billable  |                            |
| Yousof Saleh       | SALEH, YOUSOF       | E8668  | 8668          | Billable  |                            |
| Paul Robertson     | ROBERTSON, PAUL     | E8473  | 8473          | Billable  | Active Dec 2025 – Mar 2026 |
| Henry Andkilde     | (none)              | —      | —             | Internal  |                            |
| Matina Rahbar      | (none)              | —      | —             | Internal  |                            |

Note: Atkinson/Wiseman/Renwick appear in the Centerline PDF but do not submit timesheets to R&D.
The system must not assume all PDF employees have timesheets.

Travel notes:
- Some weeks have no travel PDF — normal; travel defaults to 0/n/a.
- `assume_travel_from_timesheet()` in `weekly_verifier` handles this case; requires a note.

## Testing

`testing/` contains 10 real pay periods (Dec 2025 – Apr 2026).

```
python testing/bulk_import.py              # load all 10 periods
python testing/bulk_import.py --period 20260329
python testing/bulk_import.py --dry-run
```

- Prefers `_DrewEdit.xlsx` over originals.
- Derives week_ending from PDF filename (YYMMDD = Sunday date of payroll week / Sunday start of travel range).
- UPDATE PDFs import cleanly on top of originals.

---

## Implementation Priorities

- **Phase 1** ✓ DONE — schema, source-file ingestion, workbook validation gate, extractor rewrites, regression tests
- **Phase 2** ✓ DONE — importer, weekly verifier, reconciler, payroll writer, expense exporter, receipt tracking; + travel reclassification, assume_travel_from_timesheet(), extraction log, Paul Robertson, bulk_import.py (198 tests)
- **Phase 3** ✓ DONE — all 7 Streamlit pages: Dashboard (+ Danger Zone DB clear), Import, Weekly Verification (sick/vacation/holiday/nonbillable columns), Reconcile (invoice table + CSV export), Expenses, Employees, Reports (payroll export + Sage 50 CSV); Sage 50 export rewritten from DB with UTF-16 encoding + sage50_name alias; travel aliases added for Atkinson/Wiseman/Renwick
- **Phase 4** ← CURRENT — Streamlit deprecated; React + FastAPI workboard built; EmployeesPanel (inline-edit grid + aliases), TimesheetsPanel (XLSX upload + Wk1/Wk2 hours + expenses), ApprovedHoursPanel (payroll PDF + travel PDF import, verification table with colour-grouped columns, per-row verify with required note for needs_review), resizable side panel, Vite polling for WSL; next: Reconcile node

The weekly verification workflow is not optional and should not be deferred behind cosmetic UI work.

---

## Agents

### code-reviewer

Use the `code-reviewer` agent when:
- A new pipeline module or page is complete and ready for a second-opinion review
- A change touches money-affecting logic (hours, rates, expense amounts, Sage 50 export)
- A change modifies verification, reconciliation, or override behavior
- You want to check that a new Streamlit page correctly uses the pipeline API without adding hidden business logic inside the page itself

The reviewer should check:
- Correctness against the pipeline API (importer, weekly_verifier, reconciler, expense_exporter)
- That no money-affecting values are silently overwritten
- That all manual overrides require a note
- That source files are not mutated (only copied)
- That employee sort order is never hardcoded
- That per-diem vs non-per-diem expense handling is respected

---

## Do Not

- Do not change the Sage 50 payroll CSV output path
- Do not overwrite formula columns in `RawData`
- Do not overwrite formula columns in `Time Log`
- Do not disturb `AE1` in `Centerline Profit - 2026.xlsm`
- Do not remove VBA from `PayrollChequeRun_v00.xlsm`
- Do not silently discard ambiguous employee matches
- Do not reimburse non-per-diem expenses without receipts
- Do not bill non-per-diem expenses without receipts
- Do not hardcode employee sort order in application logic
- Do not silently apply manual overrides without note/audit
- Do not overwrite original source timesheets when making manual corrections

---

## Stack

**Backend (Python)**
```text
pdfplumber>=0.11.0
openpyxl>=3.1.2
pandas>=2.2.0
fastapi
uvicorn[standard]
python-multipart
rapidfuzz
pytest
sqlite3
```

**Frontend (Node)**
```text
react + vite
@xyflow/react   (React Flow v12 — node canvas)
axios
```

Streamlit is archived — all 7 pages prefixed with `_` and no longer the primary UI.

Use `PLAN.md` for the detailed workflow, schema direction, sequencing, and control requirements.
