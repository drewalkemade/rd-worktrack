"""
5_Expenses.py — Employee expense reimbursement tracking.

Shows per-employee expense line items for a selected pay period.
The owner can:
  - View all expense lines with receipt and reimbursement status
  - Mark receipts received (clears the blocking state)
  - Mark an employee's expenses as reimbursed (after receipt is on file)
  - See which items are blocking billing or reimbursement

Expense types:
  Per diem — no receipt required; auto-ready for reimbursement
  All other categories — receipt required before reimbursement or billing
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from payroll_app import config
from payroll_app.database import db
from payroll_app.pipeline import expense_exporter

st.set_page_config(page_title="Expenses — R&D Controls", layout="wide")

st.title("Expenses")
st.caption(
    "Employee expense reimbursement tracking. "
    "Per-diem expenses do not require receipts. "
    "All other expenses require a receipt before reimbursement or billing."
)

# ---------------------------------------------------------------------------
# Period selector
# ---------------------------------------------------------------------------

conn = db.get_connection()
try:
    pay_periods = db.fetch_all(
        conn,
        """
        SELECT
            pp.id,
            pp.period_start,
            pp.period_end,
            (SELECT COUNT(*) FROM expense_items ei WHERE ei.pay_period_id = pp.id) AS expense_count,
            (SELECT COUNT(*) FROM expense_items ei WHERE ei.pay_period_id = pp.id
             AND ei.receipt_status = 'missing') AS missing_receipt_count
        FROM pay_periods pp
        ORDER BY pp.period_end DESC
        """,
    )
finally:
    conn.close()

if not pay_periods:
    st.warning("No pay periods found. Import timesheets first.")
    st.stop()

def _period_label(pp) -> str:
    missing = pp["missing_receipt_count"]
    flag = f"  ⚠ {missing} receipt(s) missing" if missing else ""
    return f"{pp['period_start']} → {pp['period_end']}  ({pp['expense_count']} items){flag}"

selected_idx = st.selectbox(
    "Pay period",
    options=range(len(pay_periods)),
    format_func=lambda i: _period_label(pay_periods[i]),
    index=0,
)
selected_period = pay_periods[selected_idx]
pay_period_id   = selected_period["id"]

st.divider()

# ---------------------------------------------------------------------------
# Load expense data
# ---------------------------------------------------------------------------

conn = db.get_connection()
try:
    summaries = expense_exporter.get_expense_summary(conn, pay_period_id)
    all_items  = expense_exporter.get_expense_detail(conn, pay_period_id)
    blocked    = expense_exporter.get_reimbursement_blocked(conn, pay_period_id)
finally:
    conn.close()

if not summaries:
    st.info("No expense items found for this period.")
    st.stop()

# ---------------------------------------------------------------------------
# Receipt backlog warning
# ---------------------------------------------------------------------------

if blocked:
    st.warning(
        f"**{len(blocked)} expense item(s) blocked** — receipt required before billing or reimbursement."
    )
    with st.expander("View blocked items"):
        for item in blocked:
            st.write(
                f"• **{item.display_name}** — {item.category} "
                f"({'CAD' if item.currency == 'CAD' else 'USD'} ${item.amount:.2f}) "
                f"on {item.work_date or '—'}"
            )

st.divider()

# ---------------------------------------------------------------------------
# Per-employee summary table
# ---------------------------------------------------------------------------

st.subheader("Summary by Employee")

hdr = st.columns([3, 1.5, 1.5, 1.5, 1.5, 2])
hdr[0].markdown("**Employee**")
hdr[1].markdown("**CAD Total**")
hdr[2].markdown("**CAD Ready**")
hdr[3].markdown("**CAD Blocked**")
hdr[4].markdown("**CAD Reimbursed**")
hdr[5].markdown("**Items**")

st.divider()

for s in summaries:
    row = st.columns([3, 1.5, 1.5, 1.5, 1.5, 2])
    row[0].write(s.display_name)
    row[1].write(f"${s.cad_total:.2f}")
    row[2].write(f"${s.cad_ready_for_reimburse:.2f}")
    if s.cad_blocked_missing_receipt > 0:
        row[3].markdown(f"⚠️ **${s.cad_blocked_missing_receipt:.2f}**")
    else:
        row[3].write("$0.00")
    row[4].write(f"${s.cad_reimbursed:.2f}")
    items_flag = f"⚠️ {s.items_missing_receipt} missing" if s.items_missing_receipt else f"{s.items_total} items"
    row[5].write(items_flag)

    if s.usd_total > 0:
        usd_row = st.columns([3, 1.5, 1.5, 1.5, 1.5, 2])
        usd_row[0].write(f"  *({s.display_name} — USD)*")
        usd_row[1].write(f"USD ${s.usd_total:.2f}")
        usd_row[2].write(f"USD ${s.usd_ready_for_reimburse:.2f}")
        if s.usd_blocked_missing_receipt > 0:
            usd_row[3].markdown(f"⚠️ **USD ${s.usd_blocked_missing_receipt:.2f}**")
        else:
            usd_row[3].write("$0.00")
        usd_row[4].write(f"USD ${s.usd_reimbursed:.2f}")

st.divider()

# ---------------------------------------------------------------------------
# Per-employee expense detail + actions
# ---------------------------------------------------------------------------

st.subheader("Line Items")

# Group items by employee
from collections import defaultdict
by_employee: dict[str, list] = defaultdict(list)
for item in all_items:
    by_employee[item.display_name].append(item)

for emp_name, items in sorted(by_employee.items()):
    with st.expander(f"{emp_name}  ({len(items)} items)"):

        for item in items:
            item_cols = st.columns([1.5, 1.5, 1, 1, 1.5, 1.5, 1.5, 2])
            item_cols[0].write(item.work_date or "—")
            item_cols[1].write(item.category.replace("_", " "))
            item_cols[2].write(item.currency)
            item_cols[3].write(f"${item.amount:.2f}")

            # Receipt status
            if item.receipt_status == "not_required":
                item_cols[4].write("✅ no receipt req.")
            elif item.receipt_status == "received":
                item_cols[4].write("✅ receipt on file")
            else:
                item_cols[4].markdown("⚠️ **receipt missing**")

            # Reimbursement status
            reimb_map = {
                "submitted":               "⏳ submitted",
                "ready_for_reimbursement": "🟢 ready",
                "reimbursed":              "✅ reimbursed",
            }
            item_cols[5].write(reimb_map.get(item.reimbursement_status, item.reimbursement_status))

            # Billing status
            bill_map = {
                "submitted":               "⏳ submitted",
                "blocked_missing_receipt": "⛔ blocked",
                "ready_for_billing":       "🟢 ready",
                "billed":                  "✅ billed",
            }
            item_cols[6].write(bill_map.get(item.billing_status, item.billing_status))

            # Mark receipt received button (only for missing)
            if item.receipt_status == "missing":
                if item_cols[7].button("Mark Receipt Received", key=f"receipt_{item.id}"):
                    conn = db.get_connection()
                    try:
                        expense_exporter.mark_receipt_received(conn, item.id)
                        conn.commit()
                    finally:
                        conn.close()
                    st.rerun()
            else:
                item_cols[7].write("")

        st.divider()

        # Mark all ready-for-reimbursement as reimbursed for this employee
        employee_id = items[0].employee_id
        summary = next((s for s in summaries if s.employee_id == employee_id), None)

        if summary and summary.cad_ready_for_reimburse > 0:
            reimb_note_key = f"reimb_note_{employee_id}"
            note_val = st.text_input(
                "Reimbursement note (optional)",
                key=reimb_note_key,
                placeholder="e.g. Expense cheque #1234 issued.",
            )
            if st.button(
                f"Mark CAD ${summary.cad_ready_for_reimburse:.2f} as Reimbursed",
                key=f"reimb_cad_{employee_id}",
            ):
                conn = db.get_connection()
                try:
                    n = expense_exporter.mark_reimbursed(
                        conn,
                        pay_period_id,
                        employee_id,
                        currency="CAD",
                        notes=note_val.strip() or None,
                    )
                    conn.commit()
                finally:
                    conn.close()
                st.success(f"Marked {n} item(s) as reimbursed.")
                st.rerun()

        if summary and summary.usd_ready_for_reimburse > 0:
            if st.button(
                f"Mark USD ${summary.usd_ready_for_reimburse:.2f} as Reimbursed",
                key=f"reimb_usd_{employee_id}",
            ):
                conn = db.get_connection()
                try:
                    n = expense_exporter.mark_reimbursed(
                        conn,
                        pay_period_id,
                        employee_id,
                        currency="USD",
                    )
                    conn.commit()
                finally:
                    conn.close()
                st.success(f"Marked {n} USD item(s) as reimbursed.")
                st.rerun()
