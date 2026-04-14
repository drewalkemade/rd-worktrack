# R&D Controls Corp — Timesheet Ecosystem

**Company:** R&D Controls Corp (co-owned by Drew Alkemade and Rick)
**Project:** Full ecosystem rework — replacing the current manual payroll / billing / reimbursement workflow with a local Streamlit app
**Repo:** `C:\Users\RD Controls\Desktop\apps\streamlit\rd-worktrack` (WSL: `/mnt/c/Users/RD Controls/Desktop/apps/streamlit/rd-worktrack`)
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
├── app.py
├── config.py
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
└── pages/
    ├── 1_Dashboard.py
    ├── 2_Import.py
    ├── 3_Weekly_Verification.py
    ├── 4_Reconcile.py
    ├── 5_Expenses.py
    ├── 6_Employees.py
    └── 7_Reports.py
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

| Display Name       | PDF Name            | PDF ID | Centerline ID | Type      |
|--------------------|---------------------|--------|---------------|-----------|
| Jeremy Atkinson    | ATKINSON, JEREMY    | E8022  | 8022          | Billable  |
| Jeremy Wiseman     | WISEMAN, JEREMY     | E8031  | 8031          | Billable  |
| Richard Renwick    | RENWICK, RICHARD    | E8041  | 8041          | Billable  |
| Jerry Jeremias     | JEREMIAS, JERRY     | E8174  | 8174          | Billable  |
| Daniel Trif        | TRIF, DANIEL        | E8190  | 8190          | Billable  |
| Zachary Ebbinghaus | EBBINGHAUS, ZACHARY | E8395  | 8395          | Billable  |
| Jarrett Zorzi      | ZORZI, JARRETT      | E8611  | 8611          | Billable  |
| Florin Moldovan    | MOLDOVAN, FLORIN    | E8650  | 8650          | Billable  |
| Yousof Saleh       | SALEH, YOUSOF       | E8668  | 8668          | Billable  |
| Henry Andkilde     | (none)              | —      | —             | Internal  |
| Matina Rahbar      | (none)              | —      | —             | Internal  |

Note: Atkinson, Wiseman, Renwick appear in the Centerline PDF but have no timesheets
in `example/` — the system must not assume all PDF employees have submitted timesheets.

---

## Implementation Priorities

- **Phase 1** ✓ DONE — schema, source-file ingestion, workbook validation gate, extractor rewrites, regression tests
- **Phase 2** ✓ DONE — importer, weekly verifier, reconciler, payroll writer, expense exporter, receipt tracking (178 tests)
- **Phase 3** ← CURRENT — Streamlit UI, starting with Import and Weekly Verification
- **Phase 4** — template improvements, richer reporting, optional lateness/exception hooks, receipt-image polish, audit coverage, multi-customer hooks

The weekly verification workflow is not optional and should not be deferred behind cosmetic UI work.

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

```text
pdfplumber>=0.11.0
openpyxl>=3.1.2
pandas>=2.2.0
streamlit
rapidfuzz
pytest
sqlite3
```

Use `PLAN.md` for the detailed workflow, schema direction, sequencing, and control requirements.
