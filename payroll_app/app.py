"""
app.py — R&D Controls Corp Timesheet Ecosystem

Entry point for the Streamlit application.

Run with:
    streamlit run payroll_app/app.py

This file:
  - Sets the global page configuration
  - Initialises the database on first run
  - Displays a landing page with overall system status
  - Relies on Streamlit's multi-page file convention (pages/ directory)
"""

import sys
from pathlib import Path

# Streamlit adds the script's own directory to sys.path, not the project root.
# Insert the project root (parent of payroll_app/) so the payroll_app package
# is importable regardless of what directory the user ran streamlit from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import sqlite3
from datetime import date

import streamlit as st

from payroll_app import config
from payroll_app.database import db, employee_manager

# ---------------------------------------------------------------------------
# Page configuration — must be the first Streamlit call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="R&D Controls — Timesheet Ecosystem",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Database initialisation
# Runs every time the app loads; schema uses IF NOT EXISTS so it is safe.
# ---------------------------------------------------------------------------

@st.cache_resource
def _init_db() -> None:
    """Initialise the database schema and seed employee data once per session."""
    config.ensure_source_dirs()
    conn = db.get_connection()
    try:
        db.initialize_database(conn)
        employee_manager.seed_employees(conn)
        conn.commit()
    finally:
        conn.close()


_init_db()


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

st.title("R&D Controls Corp — Timesheet Ecosystem")
st.caption("Payroll · Billing · Expenses · Receipts")

st.divider()

# --- System status overview ---

conn = db.get_connection()
try:
    # Open pay periods
    open_periods = db.fetch_all(
        conn,
        "SELECT id, period_start, period_end, week1_ending, week2_ending, status FROM pay_periods ORDER BY period_start DESC LIMIT 5",
    )

    # Pending verification rows
    pending_verif = db.fetch_one(
        conn,
        "SELECT COUNT(*) AS cnt FROM weekly_employee_verification WHERE status = 'pending'",
    )
    needs_review_verif = db.fetch_one(
        conn,
        "SELECT COUNT(*) AS cnt FROM weekly_employee_verification WHERE status = 'needs_review'",
    )

    # Reconciliation summary
    pending_recon = db.fetch_one(
        conn,
        "SELECT COUNT(*) AS cnt FROM reconciliation WHERE status IN ('pending', 'variance')",
    )

    # Expense receipt backlog
    missing_receipts = db.fetch_one(
        conn,
        "SELECT COUNT(*) AS cnt FROM expense_items WHERE requires_receipt = 1 AND receipt_status = 'missing'",
    )

    # Weekly approvals without a paired timesheet
    weekly_approvals_total = db.fetch_one(
        conn,
        "SELECT COUNT(*) AS cnt FROM weekly_approvals",
    )

finally:
    conn.close()

# --- KPI cards ---

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric(
        label="Open Pay Periods",
        value=len([p for p in open_periods if p["status"] == "open"]) if open_periods else 0,
    )

with col2:
    pending_cnt = pending_verif["cnt"] if pending_verif else 0
    needs_review_cnt = needs_review_verif["cnt"] if needs_review_verif else 0
    st.metric(
        label="Verification — Needs Review",
        value=needs_review_cnt,
        delta=f"{pending_cnt} pending" if pending_cnt else None,
        delta_color="off",
    )

with col3:
    recon_cnt = pending_recon["cnt"] if pending_recon else 0
    st.metric(
        label="Reconciliation — Open",
        value=recon_cnt,
    )

with col4:
    receipt_cnt = missing_receipts["cnt"] if missing_receipts else 0
    st.metric(
        label="Missing Receipts",
        value=receipt_cnt,
        delta_color="inverse" if receipt_cnt > 0 else "off",
    )

with col5:
    wa_cnt = weekly_approvals_total["cnt"] if weekly_approvals_total else 0
    st.metric(
        label="Weekly Approvals Imported",
        value=wa_cnt,
    )

st.divider()

# --- Recent pay periods table ---

st.subheader("Recent Pay Periods")

if open_periods:
    rows = []
    for p in open_periods:
        rows.append({
            "Period Start":   p["period_start"],
            "Period End":     p["period_end"],
            "Week 1 Ending":  p["week1_ending"],
            "Week 2 Ending":  p["week2_ending"] or "—",
            "Status":         p["status"],
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.info("No pay periods found. Use the **Import** page to ingest a payroll PDF.")

st.divider()

# --- Navigation hints ---

st.markdown("""
**Navigation** (use the sidebar):

| Page | Purpose |
|------|---------|
| Import | Ingest payroll PDFs, travel PDFs, and employee timesheets |
| Weekly Verification | Compare approved vs submitted hours per employee per week |
| Reconcile | Biweekly payroll reconciliation and approval |
| Expenses | Employee expense reimbursement and receipt tracking |
| Employees | Employee identities, aliases, rates, and assignments |
| Reports | Payroll export, expense summaries, profit views |
""")
