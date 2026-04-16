-- schema.sql
-- SQLite schema for the R&D Controls payroll ecosystem.
-- Run this once via db.initialize_database() to set up a fresh database.
-- All ALTER TABLE migrations go in database/migrations/ as numbered SQL files.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Core identity tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS employees (
    id               INTEGER PRIMARY KEY,
    display_name     TEXT NOT NULL,
    pdf_name         TEXT,                      -- e.g. "TRIF, DANIEL"
    pdf_id           TEXT,                      -- e.g. "E8190"
    centerline_id    INTEGER,                   -- numeric portion of the PDF ID
    expense_code     TEXT,                      -- legacy code if needed (e.g. FMOLDOVAN)
    active           BOOLEAN NOT NULL DEFAULT 1,
    hired_date       DATE,
    terminated_date  DATE
);

CREATE TABLE IF NOT EXISTS employee_aliases (
    id               INTEGER PRIMARY KEY,
    employee_id      INTEGER NOT NULL REFERENCES employees(id),
    alias_type       TEXT NOT NULL,             -- pdf_name | travel_name | receipt_name | expense_code | display_name
    alias_value      TEXT NOT NULL,
    UNIQUE(alias_type, alias_value)
);

CREATE TABLE IF NOT EXISTS employee_rates (
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

CREATE TABLE IF NOT EXISTS employee_assignments (
    id                INTEGER PRIMARY KEY,
    employee_id       INTEGER NOT NULL REFERENCES employees(id),
    customer_code     TEXT,                     -- e.g. "CENTERLINE"; NULL for internal/overhead
    assignment_type   TEXT NOT NULL,            -- internal | billable
    effective_start   DATE NOT NULL,
    effective_end     DATE,
    notes             TEXT
);

-- ---------------------------------------------------------------------------
-- Period tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pay_periods (
    id                 INTEGER PRIMARY KEY,
    period_start       DATE NOT NULL,
    period_end         DATE NOT NULL,
    week1_ending       DATE NOT NULL,
    week2_ending       DATE NOT NULL,
    status             TEXT NOT NULL DEFAULT 'open'   -- open | reconciled | exported
);

CREATE TABLE IF NOT EXISTS weekly_approvals (
    id                 INTEGER PRIMARY KEY,
    pay_period_id      INTEGER NOT NULL REFERENCES pay_periods(id),
    week_ending        DATE NOT NULL,
    week_number        INTEGER NOT NULL,              -- 1 or 2 within the pay period
    payroll_pdf_file   TEXT,
    travel_pdf_file    TEXT,
    imported_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    verified_at        DATETIME,
    UNIQUE(pay_period_id, week_number)
);

-- ---------------------------------------------------------------------------
-- Raw source file ingestion
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source_files (
    id                           INTEGER PRIMARY KEY,
    file_type                    TEXT NOT NULL,       -- payroll_pdf | travel_pdf | timesheet | receipt
    original_name                TEXT NOT NULL,
    normalized_name              TEXT,
    path                         TEXT NOT NULL,       -- path to stored copy in SOURCE_FILES_DIR
    sha256                       TEXT,
    supersedes_source_file_id    INTEGER REFERENCES source_files(id),
    edit_label                   TEXT,                -- e.g. "DrewEdit" for owner-corrected timesheets
    imported_at                  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Customer-approved hours (from payroll approval PDF)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS customer_hours (
    id                 INTEGER PRIMARY KEY,
    weekly_approval_id INTEGER NOT NULL REFERENCES weekly_approvals(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    reg_hours          DECIMAL NOT NULL DEFAULT 0,
    ot_hours           DECIMAL NOT NULL DEFAULT 0,
    dbl_hours          DECIMAL NOT NULL DEFAULT 0,
    source_file_id     INTEGER REFERENCES source_files(id),
    UNIQUE(weekly_approval_id, employee_id)
);

-- Daily detail rows from the payroll approval PDF.
-- The parser extracts clock-in, clock-out, total hours, and pay class per day.
-- These are stored here so the Reconcile panel can do day-level comparisons.
CREATE TABLE IF NOT EXISTS customer_daily_hours (
    id                 INTEGER PRIMARY KEY,
    weekly_approval_id INTEGER NOT NULL REFERENCES weekly_approvals(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    work_date          DATE NOT NULL,
    day_name           TEXT NOT NULL,
    clock_in           TEXT,
    clock_out          TEXT,
    total_hours        DECIMAL NOT NULL DEFAULT 0,
    is_dbl_day         BOOLEAN NOT NULL DEFAULT 0,
    source_file_id     INTEGER REFERENCES source_files(id),
    UNIQUE(weekly_approval_id, employee_id, work_date)
);

-- ---------------------------------------------------------------------------
-- Travel hours (from travel PDF)
-- The travel PDF is Sun–Sat but the business week is Mon–Sun.
-- Sunday always belongs to the prior Mon–Sun week.
-- The second Sunday in a pay period is provisional until the next travel PDF.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS travel_hours (
    id                          INTEGER PRIMARY KEY,
    weekly_approval_id          INTEGER NOT NULL REFERENCES weekly_approvals(id),
    employee_id                 INTEGER NOT NULL REFERENCES employees(id),
    -- raw hours from the travel PDF columns
    sun_hours                   DECIMAL NOT NULL DEFAULT 0,
    mon_hours                   DECIMAL NOT NULL DEFAULT 0,
    tue_hours                   DECIMAL NOT NULL DEFAULT 0,
    wed_hours                   DECIMAL NOT NULL DEFAULT 0,
    thu_hours                   DECIMAL NOT NULL DEFAULT 0,
    fri_hours                   DECIMAL NOT NULL DEFAULT 0,
    sat_hours                   DECIMAL NOT NULL DEFAULT 0,
    -- derived business totals
    current_week_total          DECIMAL NOT NULL DEFAULT 0,    -- Mon–Sat for this weekly approval
    prior_week_sun_applied      BOOLEAN NOT NULL DEFAULT 0,    -- Sunday was applied to prior week
    current_sun_status          TEXT NOT NULL DEFAULT 'pending_next_pdf',
        -- confirmed | assumed_from_timesheet | pending_next_pdf | needs_employee_confirmation
    current_sun_hours_assumed   DECIMAL NOT NULL DEFAULT 0,
    current_sun_note            TEXT,
    source_file_id              INTEGER REFERENCES source_files(id),
    UNIQUE(weekly_approval_id, employee_id)
);

-- ---------------------------------------------------------------------------
-- Employee submitted hours (from timesheet workbooks)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS timesheet_imports (
    id                 INTEGER PRIMARY KEY,
    pay_period_id      INTEGER NOT NULL REFERENCES pay_periods(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    source_file_id     INTEGER REFERENCES source_files(id),
    submitted_at       DATETIME,
    late_submission    BOOLEAN NOT NULL DEFAULT 0,
    submission_method  TEXT,    -- imported_file | edited_file | manual_attach
    imported_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pay_period_id, employee_id)
);

-- One row per calendar day per timesheet import
CREATE TABLE IF NOT EXISTS timesheet_daily_hours (
    id                      INTEGER PRIMARY KEY,
    timesheet_import_id     INTEGER NOT NULL REFERENCES timesheet_imports(id),
    employee_id             INTEGER NOT NULL REFERENCES employees(id),
    work_date               DATE NOT NULL,
    reg_hours               DECIMAL NOT NULL DEFAULT 0,
    ot1_hours               DECIMAL NOT NULL DEFAULT 0,
    ot2_hours               DECIMAL NOT NULL DEFAULT 0,
    drive_hours             DECIMAL NOT NULL DEFAULT 0,
    sick_hours              DECIMAL NOT NULL DEFAULT 0,
    vacation_hours          DECIMAL NOT NULL DEFAULT 0,
    holiday_hours           DECIMAL NOT NULL DEFAULT 0,
    nonbillable_hours       DECIMAL NOT NULL DEFAULT 0,
    UNIQUE(timesheet_import_id, work_date)
);

-- Biweekly totals row (derived from daily rows, stored for fast lookup)
CREATE TABLE IF NOT EXISTS timesheet_hours (
    id                 INTEGER PRIMARY KEY,
    pay_period_id      INTEGER NOT NULL REFERENCES pay_periods(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    reg_hours          DECIMAL NOT NULL DEFAULT 0,
    ot1_hours          DECIMAL NOT NULL DEFAULT 0,
    ot2_hours          DECIMAL NOT NULL DEFAULT 0,
    drive_hours        DECIMAL NOT NULL DEFAULT 0,
    sick_hours         DECIMAL NOT NULL DEFAULT 0,
    vacation_hours     DECIMAL NOT NULL DEFAULT 0,
    holiday_hours      DECIMAL NOT NULL DEFAULT 0,
    nonbillable_hours  DECIMAL NOT NULL DEFAULT 0,
    source_file_id     INTEGER REFERENCES source_files(id),
    imported_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pay_period_id, employee_id)
);

-- ---------------------------------------------------------------------------
-- Weekly verification state
-- Replaces brown/blue highlight logic in RawData with structured status.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS weekly_employee_verification (
    id                    INTEGER PRIMARY KEY,
    weekly_approval_id    INTEGER NOT NULL REFERENCES weekly_approvals(id),
    employee_id           INTEGER NOT NULL REFERENCES employees(id),
    -- timesheet hours for this specific week (summed from daily rows)
    timesheet_week_reg         DECIMAL NOT NULL DEFAULT 0,
    timesheet_week_ot1         DECIMAL NOT NULL DEFAULT 0,
    timesheet_week_ot2         DECIMAL NOT NULL DEFAULT 0,
    timesheet_week_drive       DECIMAL NOT NULL DEFAULT 0,
    timesheet_week_sick        DECIMAL NOT NULL DEFAULT 0,
    timesheet_week_vacation    DECIMAL NOT NULL DEFAULT 0,
    timesheet_week_holiday     DECIMAL NOT NULL DEFAULT 0,
    timesheet_week_nonbillable DECIMAL NOT NULL DEFAULT 0,
    -- customer-approved hours for this week
    approved_reg          DECIMAL NOT NULL DEFAULT 0,
    approved_ot           DECIMAL NOT NULL DEFAULT 0,
    approved_dbl          DECIMAL NOT NULL DEFAULT 0,
    approved_travel       DECIMAL NOT NULL DEFAULT 0,
    -- expense indicators
    needs_expense_review  BOOLEAN NOT NULL DEFAULT 0,
    simple_per_diem_count DECIMAL NOT NULL DEFAULT 0,
    extra_expense_note    TEXT,
    -- verification status (replaces brown/blue highlight)
    status                TEXT NOT NULL DEFAULT 'pending',  -- pending | needs_review | verified
    verified_at           DATETIME,
    UNIQUE(weekly_approval_id, employee_id)
);

-- ---------------------------------------------------------------------------
-- Reconciliation (biweekly)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reconciliation (
    id                 INTEGER PRIMARY KEY,
    pay_period_id      INTEGER NOT NULL REFERENCES pay_periods(id),
    employee_id        INTEGER NOT NULL REFERENCES employees(id),
    -- timesheet-submitted hours
    ts_reg             DECIMAL,
    ts_ot              DECIMAL,
    ts_dbl             DECIMAL,
    ts_drive           DECIMAL,
    -- customer-approved hours (sum of both weeks)
    cust_reg           DECIMAL,
    cust_ot            DECIMAL,
    cust_dbl           DECIMAL,
    cust_drive         DECIMAL,
    -- final hours used for payroll (may include manual override)
    final_reg          DECIMAL,
    final_ot           DECIMAL,
    final_dbl          DECIMAL,
    final_drive        DECIMAL,
    -- state
    status             TEXT,   -- pending | variance | approved | exported
    notes              TEXT,
    approved_by        TEXT,
    approved_at        DATETIME,
    UNIQUE(pay_period_id, employee_id)
);

-- ---------------------------------------------------------------------------
-- Expenses and receipts
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS expense_items (
    id                    INTEGER PRIMARY KEY,
    pay_period_id         INTEGER NOT NULL REFERENCES pay_periods(id),
    employee_id           INTEGER NOT NULL REFERENCES employees(id),
    work_date             DATE,
    currency              TEXT NOT NULL,    -- CAD | USD
    category              TEXT NOT NULL,    -- per_diem_travel | per_diem_full | lodging | ...
    description           TEXT,
    amount                DECIMAL NOT NULL,
    quantity              DECIMAL,
    requires_receipt      BOOLEAN NOT NULL DEFAULT 1,
    receipt_status        TEXT NOT NULL DEFAULT 'missing',              -- not_required | missing | received
    reimbursement_status  TEXT NOT NULL DEFAULT 'submitted',            -- submitted | ready_for_reimbursement | reimbursed
    billing_status        TEXT NOT NULL DEFAULT 'submitted',            -- submitted | blocked_missing_receipt | ready_for_billing | billed
    source_file_id        INTEGER REFERENCES source_files(id)
);

CREATE TABLE IF NOT EXISTS expense_receipts (
    id                   INTEGER PRIMARY KEY,
    expense_item_id      INTEGER NOT NULL REFERENCES expense_items(id),
    source_file_id       INTEGER REFERENCES source_files(id),
    original_filename    TEXT NOT NULL,
    normalized_filename  TEXT,
    stored_path          TEXT NOT NULL,
    sha256               TEXT,
    resized              BOOLEAN NOT NULL DEFAULT 0,
    received_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Audit
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY,
    timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP,
    action       TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    entity_id    INTEGER,
    old_value    TEXT,
    new_value    TEXT
);

-- Tracks owner-initiated edits to source timesheets.
-- The edited copy is a separate file; the original is never overwritten.
CREATE TABLE IF NOT EXISTS source_file_edits (
    id                          INTEGER PRIMARY KEY,
    original_source_file_id     INTEGER NOT NULL REFERENCES source_files(id),
    edited_source_file_id       INTEGER NOT NULL REFERENCES source_files(id),
    editor_name                 TEXT NOT NULL,
    edited_at                   DATETIME DEFAULT CURRENT_TIMESTAMP,
    change_summary              TEXT NOT NULL
);
