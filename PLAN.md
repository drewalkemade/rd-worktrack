# Timesheet Ecosystem Rework — Implementation Plan

## Status

This file is the active source of truth for the project.

Repo: `C:\Users\RD Controls\Desktop\apps\streamlit\rd-worktrack`

Backup plan file:
- `/home/drew/.claude/plans/frolicking-forging-sphinx.md`

**Current phase: Phase 3 — Streamlit UI**

### Phase 1 — Complete (2026-04-14)

All Phase 1 deliverables are done and 62/62 tests pass.

### Phase 2 — Complete (2026-04-14)

All Phase 2 deliverables are done and 178/178 tests pass (5 skipped — non-per-diem receipt
tests that require fixture timesheets with non-per-diem expenses).

Phase 2 deliverables:

| File | Description |
|------|-------------|
| `pipeline/importer.py` | Ingests payroll PDFs, travel PDFs, timesheets; idempotent; handles Sunday travel boundary |
| `pipeline/weekly_verifier.py` | Per-employee/per-week comparison; replaces brown/blue highlight; set_verified() |
| `pipeline/reconciler.py` | Biweekly reconciliation; blocking check; approve_reconciliation(); approve_all() |
| `pipeline/expense_exporter.py` | Expense summaries, line items, receipt tracking, mark_reimbursed() |
| `pipeline/cheque_run_writer.py` | Writes to PayrollChequeRun_v00.xlsm (Time Log D–Q, W); export_sage50_csv() |
| `pipeline/profit_tracker_writer.py` | Writes to rebuilt .xlsx (AE1 preserved; light-yellow expense flag) |
| `extractors/receipt_ingest.py` | Receipt normalisation, storage, linking to expense_items |
| `tests/test_importer.py` | 40 tests |
| `tests/test_weekly_verifier.py` | 22 tests |
| `tests/test_reconciler.py` | 22 tests |
| `tests/test_expense_exporter.py` | 13 tests + 5 skipped |
| `tests/test_workbook_writers.py` | 19 tests |

Key design decisions made in Phase 2:

- **Pay-period creation**: `_find_or_create_pay_period()` tries week1 match → week2 match →
  prior-week-as-week1 upgrade → create-as-week1.  This handles out-of-order PDF imports.
- **Timesheet period matching**: also falls back to week1_ending match when a week2 PDF was
  imported first and incorrectly assigned as week1.
- **Employee resolution for timesheets**: tries `display_name` alias → broad all-type search
  → fuzzy across all types. This handles names registered as `travel_name` only.
- **Reconciliation blocking**: `run_reconciliation()` raises `ReconciliationBlockedError` unless
  all weekly_employee_verification rows are in 'verified' status or `force=True`.
- **Internal employees**: bypass customer approval; `final_*` = timesheet totals; `cust_*` = 0.
- **Expense items on re-import**: delete-and-reinsert (receipt links not yet implemented).
- **profit_tracker_writer**: targets `Centerline_Profit_Rebuilt.xlsx` in project root;
  creates the file on first write; idempotent via weekly_approval_id + employee_id tracking.

Key findings from Phase 1:

- **Billing workbook gate FAILED** — openpyxl cannot open `Centerline Profit - 2026.xlsm`
  (`Nested.from_tree()` error, likely a pivot table or cache compatibility issue).
  Decision: `profit_tracker_writer.py` must target a rebuilt `.xlsx`, not the `.xlsm` directly.
  The `.xlsm` remains the reference; writes go to a parallel rebuilt workbook.

- **Full Centerline employee list confirmed from PDF parsing** (9 employees, 2 pages):

  | Display Name       | PDF Name            | PDF ID | Centerline ID |
  |--------------------|---------------------|--------|---------------|
  | Jeremy Atkinson    | ATKINSON, JEREMY    | E8022  | 8022          |
  | Jeremy Wiseman     | WISEMAN, JEREMY     | E8031  | 8031          |
  | Richard Renwick    | RENWICK, RICHARD    | E8041  | 8041          |
  | Jerry Jeremias     | JEREMIAS, JERRY     | E8174  | 8174          |
  | Daniel Trif        | TRIF, DANIEL        | E8190  | 8190          |
  | Zachary Ebbinghaus | EBBINGHAUS, ZACHARY | E8395  | 8395          |
  | Jarrett Zorzi      | ZORZI, JARRETT      | E8611  | 8611          |
  | Florin Moldovan    | MOLDOVAN, FLORIN    | E8650  | 8650          |
  | Yousof Saleh       | SALEH, YOUSOF       | E8668  | 8668          |

  Note: Atkinson, Wiseman, Renwick do not have example timesheets in `example/` —
  they may be legacy or part-time employees not currently submitting timesheets to R&D.
  The system must not assume all PDF employees have timesheets.

- **PDF page-boundary handling is generic** — the parser carries employee state across pages
  without assuming which employee spans the boundary. Any employee can be last on page 1.

- **Timesheet employee name has trailing space** — "Henry Andkilde " in `H3`.
  The extractor strips it; the alias table includes both variants.

---

## Context

**Company:** R&D Controls Corp (co-owned by Drew Alkemade and Rick)

The current system is a set of connected manual workflows used to:
- bill Centerline weekly
- pay employees biweekly
- reimburse employee expenses separately from payroll
- collect and retain supporting receipts for billing, internal records, and tax/audit support

Accuracy matters. This system affects:
- payroll
- customer billing
- employee reimbursements
- tax handling and audit support

The replacement system must be conservative, traceable, and testable.

---

## Operational Cadence

- Customer labor approval is **weekly**
- Customer travel approval is **weekly**
- Employee timesheets are **biweekly**
- Employee expense reports are **biweekly**
- Payroll cheque runs are **biweekly**
- Employee expense reimbursements are **separate from payroll** and usually happen about **30 days later**

---

## Current-State Workflow

### 1. Weekly customer approval intake

Centerline sends files with long human-readable names such as:
- `R&D Controls Payroll Approval 2026-04-07 09.26.42.pdf`
- `Contractor Travel Hrs - March 29-April 4, 2026.pdf`

For internal filing efficiency, those files are manually renamed to:
- `R&D_YYMMDD-xxxxx.pdf`
- `R&D_YYMMDD-Travel.pdf`

These renamed files are the operational inputs used in the rest of the workflow.

### 2. Weekly billing-side labor/travel entry

For each week:
- approved labor hours are extracted from `R&D_YYMMDD-xxxxx.pdf`
- travel hours are reviewed from `R&D_YYMMDD-Travel.pdf`
- weekly approved billable data is entered into `Centerline Profit - 2026.xlsm`

Files in use:
- `R&D_YYMMDD-xxxxx.pdf`
- `R&D_YYMMDD-Travel.pdf`
- `Centerline Profit - 2026.xlsm`

Sheets in use:
- `RawData`
- `Invoice`
- `Weekly`

### 3. Weekly visual verification in `RawData`

Although employee timesheets are biweekly, employees are expected to keep each week filled out weekly so the owner can visually compare week-by-week.

For each employee for each week, the owner visually checks:
- approved weekly labor hours from the payroll approval PDF
- approved weekly travel hours from the travel PDF
- that same week’s entries in the employee timesheet
- whether per diem appears to apply
- whether additional expenses may exist

Files in use:
- `Centerline Profit - 2026.xlsm` → `RawData`
- employee `.xlsx` → `Biweekly Time Sheet`
- employee `.xlsx` → `Biweekly Expense Report CAD`
- employee `.xlsx` → `Biweekly Expense Report USD`

Manual visual control states today:
- brown row highlight = possible expense / needs verification
- blue row highlight = visually checked / verified
- manual note beside employee name = expense situation does not fit `RawData` well

This visual control process is real business logic and must be replaced with structured application state.

### 4. Biweekly employee timesheet submission

Employees submit one Excel workbook for the 14-day period.

Primary file format:
- `EmpTS - YYYYMMDD.xlsx`

Sheets in use:
- `Biweekly Time Sheet`
- `Biweekly Expense Report CAD`
- `Biweekly Expense Report USD`
- `Accounting Use Only`

The timesheet workbook is the upstream source for both:
- submitted labor hours
- per diem and employee expenses

### 5. Biweekly payroll preparation

Once both weekly customer approvals exist for the pay period:
- employee submitted labor is extracted from the biweekly timesheets
- weekly customer-approved labor/travel is summed across both weeks
- submitted vs approved hours are entered into `PayrollChequeRun_v00.xlsm`
- mismatches are investigated manually

File in use:
- `PayrollChequeRun_v00.xlsm`

Sheets in use:
- `Time Log`
- `Current`
- `Worksheet`

Columns in use in `Time Log`:
- `D–L` = submitted timesheet hours
- `N–Q` = customer-approved hours
- `W` = wage rate
- `X:AC` = formulas, must not be overwritten

Internal employees:
- Andkilde
- Rahbar

These employees bypass customer approval and go timesheet → payroll only.

### 6. Payroll export

Payroll is exported from:
- `PayrollChequeRun_v00.xlsm` → `Current` → `V1:AC50`

The output path must remain:
- `C:\Users\Alkemade\OneDrive\02 R&D Controls Corp\_Employees\_Timesheets\timesheet_YYYYMMDD.csv`

This CSV is imported into Sage 50 for payroll.

### 7. Employee expense reimbursement workflow

Employee expenses are **not** paid through payroll.

Instead:
- each employee is also set up as a vendor in Sage 50
- employee expenses are reimbursed by separate expense cheque
- no payroll taxes are deducted
- reimbursement usually happens about 30 days later because of processing time

The owner currently stages expense totals in:
- `example-expense/2020_EmployeeExpenses.xlsx`

That workbook is used to get all employee expense totals into one place before manual Sage 50 entry.

### 8. Receipt workflow

Per diem:
- always comes from the expense tabs
- does not require receipts

Everything else:
- generally requires receipts
- should not be reimbursed without receipt
- should not be billed to Centerline without receipt

Receipts arrive as arbitrary image/PDF filenames and are manually:
- chased down from employees if missing
- renamed to `<NAME>_<TYPE>_<DATE>.<extension>`
- sometimes resized/compressed

Receipts are needed for:
- internal records
- customer billing support
- tax/audit support

### 9. Customer billing of expenses

Most employee expenses are billable back to Centerline.

The customer invoice can include:
- labor
- travel
- per diem
- named reimbursable expenses

Reference file:
- `example-invoice/R&D - CENTERLINE Invoice 2721.pdf`

Reference receipts:
- files in `example-invoice/`

---

## Problems With The Current System

- Weekly billing entry is manual
- Weekly visual verification is manual and encoded as cell colors and notes
- PDF parsing is brittle
- Travel handling has a week-boundary problem
- Timesheet extraction currently only trusts totals and not daily structure
- Expense reimbursement is staged in a separate manual workbook
- Receipt tracking is manual and easy to lose track of
- Complex expenses do not fit `RawData` well
- Billing, payroll, reimbursement, and receipt states are not unified

---

## Design Goals

- Preserve source data and make all downstream outputs reproducible
- Store daily employee timesheet detail as first-class data
- Support weekly billing and biweekly payroll from the same underlying records
- Replace brown/blue highlight logic with explicit verification state
- Make expenses and receipts first-class workflow objects
- Keep employee reimbursement separate from payroll
- Preserve existing Excel/Sage 50 compatibility where needed
- Be idempotent and auditable
- Require review for any ambiguous or incomplete payroll/billing-affecting data
- Prefer simple, explicit, debug-friendly code over clever abstractions
- Make the system teachable enough that it can later be turned into a step-by-step course

---

## Engineering Principles

This project should optimize for:
- readability
- traceability
- debuggability
- auditability
- maintainability
- teachability

Code should generally be:
- explicit rather than clever
- verbose rather than compressed
- easy to step through in a debugger
- easy to explain module-by-module
- organized so each workflow stage is understandable on its own

Avoid:
- unnecessary abstraction layers
- overly generic frameworks inside the business logic
- dense helper indirection that hides business rules
- compact code that is harder to debug than to write

Preferred implementation style:
- small modules with clear responsibilities
- straightforward SQL and DB helpers
- explicit parsing and transformation steps
- explicit validation and logging around file boundaries
- tests that read like worked examples
- Streamlit pages that are boring in code structure but clear in behavior

Long-term teaching goal:
- the final system should be structured well enough that it can be explained as a course, lesson by lesson, from first principles

---

## Target Architecture

```text
CUSTOMER INPUTS (weekly)              EMPLOYEE INPUTS (biweekly)
  Payroll approval PDF                  Timesheet workbook
  Travel PDF                            + expense tabs
           |                                   |
           v                                   v
  extraction + normalization          extraction + normalization
           \___________________   __________________/
                               \ /
                                v
                      SQLite source of truth
                                |
            _________________________________________________
           |                    |               |             |
           v                    v               v             v
    Weekly verification    Payroll flow   Expense flow   Billing flow
           |                    |               |             |
           v                    v               v             v
      owner review        Sage 50 payroll   Sage 50      Centerline invoice
      per employee/week       CSV           expense data   support / RawData
```

---

## Project Structure

```text
timesheet/
├── PLAN.md
├── CLAUDE.md
├── payroll_app/
│   ├── app.py
│   ├── config.py
│   ├── database/
│   │   ├── db.py
│   │   ├── schema.sql
│   │   ├── migrations/
│   │   └── employee_manager.py
│   ├── extractors/
│   │   ├── pdf_parser_v2.py
│   │   ├── travel_parser.py
│   │   ├── timesheet_extractor_v2.py
│   │   └── receipt_ingest.py
│   ├── pipeline/
│   │   ├── importer.py
│   │   ├── weekly_verifier.py
│   │   ├── reconciler.py
│   │   ├── cheque_run_writer.py
│   │   ├── profit_tracker_writer.py
│   │   ├── expense_exporter.py
│   │   └── exporter.py
│   ├── pages/
│   │   ├── 1_Dashboard.py
│   │   ├── 2_Import.py
│   │   ├── 3_Weekly_Verification.py
│   │   ├── 4_Reconcile.py
│   │   ├── 5_Expenses.py
│   │   ├── 6_Employees.py
│   │   └── 7_Reports.py
│   └── tests/
│       ├── fixtures/
│       ├── test_pdf_parser.py
│       ├── test_travel_parser.py
│       ├── test_timesheet_extractor.py
│       ├── test_weekly_verifier.py
│       ├── test_reconciler.py
│       ├── test_expense_exporter.py
│       └── test_workbook_writers.py
├── python-payroll_data_extract/
├── example/
├── example-expense/
└── example-invoice/
```

---

## Data Model

### Core identity tables

```sql
CREATE TABLE employees (
    id               INTEGER PRIMARY KEY,
    display_name     TEXT NOT NULL,
    pdf_name         TEXT,
    pdf_id           TEXT,
    centerline_id    INTEGER,
    expense_code     TEXT,     -- e.g. FMOLDOVAN / DTRIF if needed for legacy mapping
    active           BOOLEAN DEFAULT 1,
    hired_date       DATE,
    terminated_date  DATE
);

CREATE TABLE employee_aliases (
    id               INTEGER PRIMARY KEY,
    employee_id      INTEGER NOT NULL REFERENCES employees(id),
    alias_type       TEXT NOT NULL,   -- pdf_name | travel_name | receipt_name | expense_code
    alias_value      TEXT NOT NULL,
    UNIQUE(alias_type, alias_value)
);

CREATE TABLE employee_rates (
    id                INTEGER PRIMARY KEY,
    employee_id       INTEGER NOT NULL REFERENCES employees(id),
    effective_date    DATE NOT NULL,
    base_rate         DECIMAL,
    ot_multiplier     DECIMAL DEFAULT 1.3,
    dbl_multiplier    DECIMAL DEFAULT 1.7,
    bill_rate         DECIMAL,
    benefit_fixed     DECIMAL,
    benefit_variable  DECIMAL
);

CREATE TABLE employee_assignments (
    id                INTEGER PRIMARY KEY,
    employee_id       INTEGER NOT NULL REFERENCES employees(id),
    customer_code     TEXT,              -- e.g. CENTERLINE; null for internal/overhead
    assignment_type   TEXT NOT NULL,     -- internal | billable
    effective_start   DATE NOT NULL,
    effective_end     DATE,
    notes             TEXT
);
```

### Period tables

```sql
CREATE TABLE pay_periods (
    id                 INTEGER PRIMARY KEY,
    period_start       DATE NOT NULL,
    period_end         DATE NOT NULL,
    week1_ending       DATE NOT NULL,
    week2_ending       DATE NOT NULL,
    status             TEXT DEFAULT 'open'
);

CREATE TABLE weekly_approvals (
    id                 INTEGER PRIMARY KEY,
    pay_period_id      INTEGER NOT NULL REFERENCES pay_periods(id),
    week_ending        DATE NOT NULL,
    week_number        INTEGER NOT NULL,
    payroll_pdf_file   TEXT,
    travel_pdf_file    TEXT,
    imported_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    verified_at        DATETIME,
    UNIQUE(pay_period_id, week_number)
);
```

### Raw source ingestion

```sql
CREATE TABLE source_files (
    id                 INTEGER PRIMARY KEY,
    file_type          TEXT NOT NULL,   -- payroll_pdf | travel_pdf | timesheet | receipt
    original_name      TEXT NOT NULL,
    normalized_name    TEXT,
    path               TEXT NOT NULL,
    sha256             TEXT,
    supersedes_source_file_id INTEGER REFERENCES source_files(id),
    edit_label         TEXT,
    imported_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Customer-approved hours

```sql
CREATE TABLE customer_hours (
    id                 INTEGER PRIMARY KEY,
    weekly_approval_id INTEGER NOT NULL REFERENCES weekly_approvals(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    reg_hours          DECIMAL DEFAULT 0,
    ot_hours           DECIMAL DEFAULT 0,
    dbl_hours          DECIMAL DEFAULT 0,
    source_file_id     INTEGER REFERENCES source_files(id),
    UNIQUE(weekly_approval_id, employee_id)
);

CREATE TABLE travel_hours (
    id                 INTEGER PRIMARY KEY,
    weekly_approval_id INTEGER NOT NULL REFERENCES weekly_approvals(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    sun_hours          DECIMAL DEFAULT 0,
    mon_hours          DECIMAL DEFAULT 0,
    tue_hours          DECIMAL DEFAULT 0,
    wed_hours          DECIMAL DEFAULT 0,
    thu_hours          DECIMAL DEFAULT 0,
    fri_hours          DECIMAL DEFAULT 0,
    sat_hours          DECIMAL DEFAULT 0,
    current_week_total DECIMAL DEFAULT 0,   -- Mon-Sat for this weekly approval
    prior_week_sun_applied BOOLEAN DEFAULT 0,
    current_sun_status TEXT DEFAULT 'pending_next_pdf', -- confirmed | assumed_from_timesheet | pending_next_pdf | needs_employee_confirmation
    current_sun_hours_assumed DECIMAL DEFAULT 0,
    current_sun_note   TEXT,
    source_file_id     INTEGER REFERENCES source_files(id),
    UNIQUE(weekly_approval_id, employee_id)
);
```

### Employee submitted hours

```sql
CREATE TABLE timesheet_imports (
    id                 INTEGER PRIMARY KEY,
    pay_period_id      INTEGER NOT NULL REFERENCES pay_periods(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    source_file_id     INTEGER REFERENCES source_files(id),
    submitted_at       DATETIME,
    late_submission    BOOLEAN DEFAULT 0,
    submission_method  TEXT, -- imported_file | edited_file | manual_attach
    imported_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pay_period_id, employee_id)
);

CREATE TABLE timesheet_daily_hours (
    id                 INTEGER PRIMARY KEY,
    timesheet_import_id INTEGER NOT NULL REFERENCES timesheet_imports(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    work_date          DATE NOT NULL,
    reg_hours          DECIMAL DEFAULT 0,
    ot1_hours          DECIMAL DEFAULT 0,
    ot2_hours          DECIMAL DEFAULT 0,
    drive_hours        DECIMAL DEFAULT 0,
    sick_hours         DECIMAL DEFAULT 0,
    vacation_hours     DECIMAL DEFAULT 0,
    holiday_hours      DECIMAL DEFAULT 0,
    nonbillable_hours  DECIMAL DEFAULT 0,
    UNIQUE(timesheet_import_id, work_date)
);

CREATE TABLE timesheet_hours (
    id                 INTEGER PRIMARY KEY,
    pay_period_id      INTEGER NOT NULL REFERENCES pay_periods(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    reg_hours          DECIMAL DEFAULT 0,
    ot1_hours          DECIMAL DEFAULT 0,
    ot2_hours          DECIMAL DEFAULT 0,
    drive_hours        DECIMAL DEFAULT 0,
    sick_hours         DECIMAL DEFAULT 0,
    vacation_hours     DECIMAL DEFAULT 0,
    holiday_hours      DECIMAL DEFAULT 0,
    nonbillable_hours  DECIMAL DEFAULT 0,
    source_file_id     INTEGER REFERENCES source_files(id),
    imported_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pay_period_id, employee_id)
);
```

### Weekly verification state

```sql
CREATE TABLE weekly_employee_verification (
    id                    INTEGER PRIMARY KEY,
    weekly_approval_id    INTEGER NOT NULL REFERENCES weekly_approvals(id),
    employee_id           INTEGER NOT NULL REFERENCES employees(id),
    timesheet_week_reg    DECIMAL DEFAULT 0,
    timesheet_week_ot1    DECIMAL DEFAULT 0,
    timesheet_week_ot2    DECIMAL DEFAULT 0,
    timesheet_week_drive  DECIMAL DEFAULT 0,
    approved_reg          DECIMAL DEFAULT 0,
    approved_ot           DECIMAL DEFAULT 0,
    approved_dbl          DECIMAL DEFAULT 0,
    approved_travel       DECIMAL DEFAULT 0,
    needs_expense_review  BOOLEAN DEFAULT 0,
    simple_per_diem_count DECIMAL DEFAULT 0,
    extra_expense_note    TEXT,
    status                TEXT NOT NULL DEFAULT 'pending', -- pending | needs_review | verified
    verified_at           DATETIME,
    UNIQUE(weekly_approval_id, employee_id)
);
```

### Reconciliation

```sql
CREATE TABLE reconciliation (
    id                 INTEGER PRIMARY KEY,
    pay_period_id      INTEGER NOT NULL REFERENCES pay_periods(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    ts_reg             DECIMAL,
    cust_reg           DECIMAL,
    final_reg          DECIMAL,
    ts_ot              DECIMAL,
    cust_ot            DECIMAL,
    final_ot           DECIMAL,
    ts_dbl             DECIMAL,
    cust_dbl           DECIMAL,
    final_dbl          DECIMAL,
    ts_drive           DECIMAL,
    cust_drive         DECIMAL,
    final_drive        DECIMAL,
    status             TEXT,
    notes              TEXT,
    approved_by        TEXT,
    approved_at        DATETIME,
    UNIQUE(pay_period_id, employee_id)
);
```

### Expenses and receipts

```sql
CREATE TABLE expense_items (
    id                  INTEGER PRIMARY KEY,
    pay_period_id       INTEGER NOT NULL REFERENCES pay_periods(id),
    employee_id         INTEGER NOT NULL REFERENCES employees(id),
    work_date           DATE,
    currency            TEXT NOT NULL,     -- CAD | USD
    category            TEXT NOT NULL,     -- per_diem_travel | per_diem_full | lodging | fuel | tools | other | etc
    description         TEXT,
    amount              DECIMAL NOT NULL,
    quantity            DECIMAL,
    requires_receipt    BOOLEAN NOT NULL DEFAULT 1,
    receipt_status      TEXT NOT NULL DEFAULT 'missing', -- not_required | missing | received
    reimbursement_status TEXT NOT NULL DEFAULT 'submitted', -- submitted | ready_for_reimbursement | reimbursed
    billing_status      TEXT NOT NULL DEFAULT 'submitted', -- submitted | blocked_missing_receipt | ready_for_billing | billed
    source_file_id      INTEGER REFERENCES source_files(id)
);

CREATE TABLE expense_receipts (
    id                  INTEGER PRIMARY KEY,
    expense_item_id     INTEGER NOT NULL REFERENCES expense_items(id),
    source_file_id      INTEGER REFERENCES source_files(id),
    original_filename   TEXT NOT NULL,
    normalized_filename TEXT,
    stored_path         TEXT NOT NULL,
    sha256              TEXT,
    resized             BOOLEAN DEFAULT 0,
    received_at         DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Audit

```sql
CREATE TABLE audit_log (
    id                  INTEGER PRIMARY KEY,
    timestamp           DATETIME DEFAULT CURRENT_TIMESTAMP,
    action              TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    entity_id           INTEGER,
    old_value           TEXT,
    new_value           TEXT
);

CREATE TABLE source_file_edits (
    id                  INTEGER PRIMARY KEY,
    original_source_file_id INTEGER NOT NULL REFERENCES source_files(id),
    edited_source_file_id   INTEGER NOT NULL REFERENCES source_files(id),
    editor_name         TEXT NOT NULL,
    edited_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    change_summary      TEXT NOT NULL
);
```

---

## Extractors

### 1. `pdf_parser_v2.py`

Requirements:
- replace hardcoded `times[3]`, `times[4]`, `times[5]`
- use semantic header detection with `pdfplumber.extract_words()`
- preserve current correct behavior on sample PDFs
- extract employee totals reliably even if columns shift
- extract daily row detail where practical, including clock/start-time level fields and exception indicators for future reporting hooks

Reference:
- `python-payroll_data_extract/pdf_parser.py`

### 2. `travel_parser.py`

Requirements:
- parse `R&D_YYMMDD-Travel.pdf`
- normalize/resolve employee names using aliases
- never silently discard ambiguous rows
- handle Sunday belonging to the prior Mon-Sun week

### 3. `timesheet_extractor_v2.py`

Requirements:
- extract daily labor rows from the real 14-day grid
- note: daily range must include the second Sunday; do not assume rows `9–21`
- extract totals
- extract expense rows from CAD/USD tabs
- support current workbook structure, including formula-driven totals
- support future employee-facing validation hooks and submission metadata

Reference:
- `python-payroll_data_extract/timesheet_extractor.py`
- `EmpTS - 20260329.xlsx`

### 4. `receipt_ingest.py`

Requirements:
- ingest arbitrary receipt files
- normalize names to `<NAME>_<TYPE>_<DATE>.<extension>`
- link receipts to expense items
- optional resize/compression, but only after core tracking works

### 5. Source document access

Requirements:
- keep imported source files accessible on disk
- store normalized source paths in the DB
- allow the app to open payroll PDFs, travel PDFs, timesheets, and receipts directly
- support quick navigation from verification/reconciliation/expense rows to backing files
- support local manual review and screenshot workflows

---

## Pipeline Components

### 1. `importer.py`

Responsibilities:
- ingest source files
- normalize names
- hash files
- create or update period records
- upsert extracted data idempotently

### 2. `weekly_verifier.py`

Responsibilities:
- compute weekly employee comparison from:
  - customer-approved weekly hours
  - timesheet daily rows for that specific week
  - weekly expense presence
- surface Sunday travel cases that are provisional until the following travel PDF arrives
- replace brown/blue highlight logic with structured statuses
- require owner review for rows with possible expense complications

### 3. `reconciler.py`

Responsibilities:
- sum week 1 + week 2 approved hours
- compare against biweekly submitted totals
- store `ts_*`, `cust_*`, and `final_*`
- handle internal employees
- block period approval until required review is complete

### 4. `cheque_run_writer.py`

Responsibilities:
- write submitted hours to `D–L`
- write final approved hours to `N–Q`
- write effective wage rate to `W`
- preserve formulas in `X:AC`
- export payroll CSV exactly as Sage 50 expects

Target workbook:
- `PayrollChequeRun_v00.xlsm`

### 5. `profit_tracker_writer.py`

Responsibilities:
- write weekly approved billable rows into `RawData`
- preserve formula columns
- preserve `AE1`
- support per diem and expense visibility better than the current workbook allows

Target workbook:
- `Centerline Profit - 2026.xlsm` initially as reference
- possible rebuilt `.xlsx` target after validation gate

### 6. `expense_exporter.py`

Responsibilities:
- produce employee reimbursement summaries per employee per period
- support CAD and USD
- preserve detailed line items in DB
- allow summarized output for practical Sage 50 entry

This replaces the role of:
- `example-expense/2020_EmployeeExpenses.xlsx`

### 7. Reporting layer

Responsibilities:
- produce quick-glance operational dashboards
- show overall profit trends
- show per-employee profitability
- expose missing receipts, open variances, and blocked states immediately
- support drill-down from summary cards/charts into detailed tables
- support optional control/reporting hooks such as lateness and exception monitoring

Reporting must come from DB-backed data, not only from workbook formulas.

### 8. Controlled source edit workflow

Requirements:
- if a source employee timesheet must be corrected, preserve the original file
- create a separate edited copy rather than overwriting the original
- default edited filename should indicate owner intervention, e.g. `*_DrewEdit.xlsx`
- record what changed, who changed it, and when
- keep edited files linked to original files in DB/audit records

---

## Workbook Strategy

### Payroll workbook

`PayrollChequeRun_v00.xlsm` remains the operational payroll workbook.

Rules:
- open with `keep_vba=True`
- do not overwrite formula columns
- do not remove VBA
- preserve Sage 50 export compatibility

### Billing workbook

`Centerline Profit - 2026.xlsm` is higher risk.

Observed concerns:
- openpyxl compatibility issues
- pivot/cache baggage
- formula dependencies

Required gate before full writer implementation:
1. prove workbook can be safely opened in automation
2. prove `RawData`, `EmpTbl`, and `AE1` can be addressed safely
3. prove a copied workbook can receive a synthetic append without breaking formulas
4. if not safe, intentionally rebuild to a new `.xlsx` target rather than patching blindly

This validation gate belongs in Phase 1, not late Phase 2.

---

## Expense Model Decisions

- Per diem always comes from the employee expense tabs
- Per diem does not require receipt
- Non-per-diem expenses require receipt
- Non-per-diem expenses cannot be reimbursed without receipt
- Non-per-diem expenses cannot be billed to Centerline without receipt
- Most expenses are billable to Centerline
- Expense reimbursement is separate from payroll
- Sage 50 expense entry is practically per employee per period
- The app must preserve detail even if the exported reimbursement view is summarized

Travel-specific rule:
- approved labor hours are still treated as Mon–Sun from the payroll approval PDF
- travel is the exception because the travel PDF is Sun–Sat
- the second Sunday in a pay period may need to be assumed from the employee timesheet until the next travel PDF arrives
- assumed Sunday travel must remain visible as provisional until confirmed
- those cases may require direct employee verification

Template improvements needed later:
- add `Fuel`
- add `Other`
- keep flexibility for rare categories like tools

---

## UI Plan

### 1. Dashboard

Show:
- active weekly and biweekly states
- payroll state
- expense reimbursement state
- receipt backlog
- billing state

### 2. Import

Support:
- original incoming Centerline filenames
- normalized internal filenames
- weekly payroll PDF import
- weekly travel PDF import
- biweekly timesheet import
- receipt import
- source-document open/view actions

### 3. Weekly Verification

Replace manual `RawData` row colors and notes with:
- pending
- needs expense review
- verified

Per employee per week:
- show approved weekly labor/travel
- show submitted weekly labor from daily timesheet rows
- show per diem/expense presence
- show provisional Sunday travel state when applicable
- allow notes
- allow opening source PDFs and timesheets directly from the row

### 4. Reconcile

Per employee per pay period:
- show submitted totals
- show customer-approved totals
- allow final override
- require note when appropriate
- allow opening source PDFs and timesheets directly from the row

### 5. Expenses

Per employee per period:
- extracted expenses
- receipt requirements
- receipt status
- reimbursement readiness
- billing readiness
- allow opening receipts and source timesheets directly from the row

### 6. Employees

Manage:
- canonical identity
- aliases
- effective-dated customer assignment
- rates
- active state

### 7. Reports

Produce:
- payroll CSV
- employee expense reimbursement summary
- receipt backlog report
- weekly billing support views
- variance history
- overall profit summary
- per-employee profit summary
- trend charts for revenue, cost, and profit
- quick-glance tables for blocked operational items
- manual verification queue
- lateness / exception review report

Recommended quick-glance report views:
- KPI cards for weekly revenue, payroll cost, reimbursable expenses, gross profit, missing receipts, open variances
- weekly status matrix
- profit trend chart over time
- employee profitability chart and sortable table
- receipt backlog table
- reimbursement readiness table
- billing readiness table
- manual verification table for items needing owner review

Document access expectations:
- verification, reconciliation, and expense rows should expose direct source-file access
- payroll PDFs, travel PDFs, timesheets, and receipts should be easy to open from the app

---

## Verification Strategy

This project requires strong regression coverage before UI polish.

### Parser tests

- payroll PDF parser against `R&D_260329-xxxxx.pdf`
- travel parser against `R&D_260329-Travel.pdf`
- expected outputs compared to known fixture expectations

### Timesheet tests

- daily extraction from real example workbooks
- verify the second Sunday is included
- verify totals match derived sums
- verify expense extraction from CAD/USD tabs

### Reconciliation tests

- verify week 1 + week 2 customer sum logic
- verify internal employee behavior
- verify weekly verifier outputs per employee/week
- verify provisional Sunday travel handling and later confirmation

### Workbook tests

- operate only on copied fixture workbooks
- verify intended cells changed
- verify protected formula cells did not change
- verify CSV output shape matches current Sage 50 import expectations

### Source access and edit tests

- verify source-file paths are stored and retrievable
- verify app actions resolve the correct backing files
- verify a controlled timesheet edit creates a separate `DrewEdit`-style file
- verify the original file remains untouched
- verify change summaries are captured in audit data

### Expense tests

- verify per diem requires no receipt
- verify non-per-diem is blocked without receipt
- verify reimbursement summaries aggregate correctly by employee / period / currency

### End-to-end tests

Given:
- weekly payroll PDF
- weekly travel PDF
- employee timesheets
- sample receipts

Verify:
- weekly verification state
- biweekly reconciliation output
- payroll export
- expense reimbursement summary
- billing readiness gates

### Override tests

- verify manual overrides preserve original imported values
- verify overrides require notes for money-affecting changes
- verify override history is visible in audit data
- verify final exports reflect stored override state exactly

---

## Implementation Phases

### Phase 1 — Foundation and control points ✓ DONE (2026-04-14)

1. ✓ Write schema and DB layer
2. ✓ Add source file ingestion and hashing
3. ✓ Add employee aliases and rate seed logic
4. ✓ Validate billing workbook automation safety — FAILED, rebuild required
5. ✓ Rewrite payroll PDF parser
6. ✓ Build travel parser
7. ✓ Refactor timesheet extractor to daily + expense extraction
8. ✓ Design source-document storage and access pattern
9. ✓ Build fixture-based parser tests (62/62 passing)

### Phase 2 — Core pipeline  ← CURRENT

1. Build importer
2. Build weekly verifier
3. Build reconciler
4. Build payroll writer
5. Build expense exporter
6. Build billing writer — targets rebuilt `.xlsx` (not `.xlsm`, gate failed)
7. Build receipt ingest/tracking
8. Build source-document open/view actions
9. Build controlled timesheet edit workflow with `DrewEdit`-style copies and audit trail

### Phase 3 — UI

1. Scaffold app
2. Import page
3. Weekly verification page
4. Reconcile page
5. Expenses page
6. Dashboard
7. Employees page
8. Reports

### Phase 4 — Template and operational polish

1. Improve timesheet template
2. Add `Fuel` and `Other`
3. Optional receipt image resize/compression workflow
4. Add employee-facing template validation and submission checks
5. Add richer reporting dashboards and profit analytics
6. Add lateness/exception reporting hook if daily PDF extraction supports it cleanly
7. Wire audit log to all state changes
8. Add multi-customer hooks

---

## Non-Negotiable Rules

- Do not change the Sage 50 payroll CSV output path
- Do not overwrite formula columns in `RawData`
- Do not overwrite formula columns in `Time Log`
- Do not disturb `AE1` in `RawData`
- Do not remove VBA from `PayrollChequeRun_v00.xlsm`
- Do not silently discard ambiguous employee matches
- Do not reimburse non-per-diem expenses without receipts
- Do not bill non-per-diem expenses without receipts
- Do not hardcode employee display order in application logic
- Do not silently apply manual overrides without note/audit

---

## Key Reference Files

- `CLAUDE.md`
- `PLAN.md`
- `EmpTS - 20260329.xlsx`
- `PayrollChequeRun_v00.xlsm`
- `Centerline Profit - 2026.xlsm`
- `R&D_260329-xxxxx.pdf`
- `R&D_260329-Travel.pdf`
- `example/`
- `example-expense/2020_EmployeeExpenses.xlsx`
- `example-invoice/R&D - CENTERLINE Invoice 2721.pdf`
- `python-payroll_data_extract/pdf_parser.py`
- `python-payroll_data_extract/timesheet_extractor.py`
- `python-payroll_data_extract/payroll_extractor.py`

---

## Employee Lifecycle Requirements

The system must support employee changes without rewriting history.

Required capabilities:
- add new employees
- deactivate employees who quit
- reactivate returning employees
- move employees between internal and Centerline-billable work
- allow currently internal employees such as Henry or Matina to become billable later
- allow current billable employees to move back to internal work later
- preserve historical rates and assignments by effective date

This must be modeled with effective-dated assignment records, not hardcoded special cases.

Operationally, "internal employee" vs "Centerline billable employee" is not a permanent identity trait. It is a time-bound assignment state.

---

## Manual Override Requirements

Manual overrides are allowed, but they must never be silent.

Typical override cases:
- final payroll hours differ from submitted or approved source values
- Sunday travel is assumed, then later corrected
- per diem counts are adjusted
- expense category or amount is corrected
- employee identity mapping is manually resolved
- billable vs non-billable treatment is manually corrected

For any money-affecting override, the system should store:
- original value
- final value
- reason / note
- who made the change
- when the change was made
- which workflow it affects: payroll, billing, reimbursement, reporting

UI expectations:
- overridden records should be visibly marked
- overrides should appear in reports
- exports must be reproducible from stored override state

Audit expectations:
- all overrides should write to `audit_log`
- a note should be required for money-affecting overrides

---

## Employee Template And Validation Requirements

The employee timesheet workbook should eventually be improved, but the first requirement is to reduce avoidable owner cleanup.

Desired template improvements:
- add an `Offsite` checkbox or equivalent daily indicator
- add `Fuel`
- add `Other`
- keep flexibility for unusual reimbursable categories like tools
- improve employee-facing clarity around per diem and receipt expectations

Desired employee-side validation / warnings:
- offsite checked but no per diem entered
- per diem entered on a day that may not make sense
- non-per-diem expense entered but receipt not included / declared
- totals mismatch between daily rows and summary rows
- suspicious expense entry across CAD and USD
- timesheet submitted after the Monday 10:00 AM cutoff

Important nuance:
- not all offsite work gets per diem
- therefore some validations should be warnings, not hard blocks

Recommended rule types:
- blocking errors for structural problems
- warnings for business-rule suspicions
- late flag for submission after the cutoff

Submission metadata to capture:
- submitted_at
- late_submission flag
- optional employee confirmation that required receipts are included

Operational expectation:
- the first implementation should run these validations at import time inside the app
- later template enhancements may surface similar warnings to employees before submission
- import-time validation remains the required control even if workbook-side validation is later added

---

## Reporting Requirements

The app should provide both operational and financial reporting.

### Quick-glance operational reporting

At minimum, the dashboard should show:
- this week billed revenue
- current pay period payroll cost
- estimated gross profit
- open payroll variances
- missing receipts
- expenses waiting for reimbursement
- billing-ready vs blocked counts
- open manual verification items, including provisional Sunday travel cases
- late submissions
- possible lateness / exception items if enabled

### Financial reporting

The system should support:
- overall profit by week, month, quarter, and year
- per-employee profit by week, month, quarter, and year
- revenue vs payroll cost trends
- reimbursable expense visibility
- billed vs not-yet-billed expense visibility
- employee profit leaderboard / ranking

### Recommended report outputs

- Executive summary
- Weekly operations report
- Employee profitability report
- Payroll variance report
- Expense and receipt report
- Billing readiness report
- Manual verification report
- Late submission report
- Possible lateness / exception report

### Visual reporting guidance

Prefer:
- KPI cards for top metrics
- line charts for trend over time
- stacked bars for revenue/cost/profit composition
- horizontal bars for employee profit comparisons
- dense sortable tables for operational queues
- click-through drill-down from charts/cards into filtered detail tables

### Manual verification reporting

The app must provide a report or queue for items that still need owner review, including:
- provisional Sunday travel assumed from the employee timesheet
- Sunday travel pending confirmation from the next travel PDF
- Sunday travel requiring employee confirmation
- weekly rows marked as needing expense review
- payroll variances
- blocked non-per-diem expenses due to missing receipts

### Optional lateness / exception reporting

If daily payroll-PDF extraction supports it cleanly, the app should provide a non-blocking report for possible lateness and exception review.

Examples:
- employee starts later than the expected shift start
- the payroll approval PDF shows an exception indicator such as `Except = 1`

This should be treated as a review signal, not a payroll-blocking rule.

Desired output fields:
- employee
- date
- observed start time
- expected start time if known
- minutes late if derivable
- exception flag
- confidence / reason
- reviewed status

This feature is useful but lower priority than payroll, billing, reimbursement, receipt gating, and weekly verification correctness.
