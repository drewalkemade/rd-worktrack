"""
3_Weekly_Verification.py — Per-employee, per-week verification page.

Replaces the manual brown/blue row highlight logic in RawData with structured
verification state: pending | needs_review | verified.

For each employee in a selected weekly approval the page shows:
  - Customer-approved labor hours (reg / OT / dbl)
  - Employee-submitted timesheet hours for the same Mon–Sun week
  - Variance indicators (zero is good; non-zero triggers needs_review)
  - Approved travel hours (Mon–Sat) and Sunday travel status
  - Per-diem count and any non-per-diem expense flags
  - Current status (pending / needs_review / verified)

The owner can:
  - Run verification for any weekly approval (compute/refresh all rows)
  - Mark individual employees as verified (with an optional note)
  - Mark all pending/needs_review rows verified at once (with a note)
  - Open the source PDF or timesheet directly from the row

Workflow:
  1. Select a weekly approval from the dropdown.
  2. Click "Run Verification" to compute/refresh all rows.
  3. Review the table — rows needing attention are highlighted.
  4. Mark individual rows verified, or use "Verify All" for a clean week.
"""

import sys
from datetime import date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from payroll_app.database import db
from payroll_app.pipeline import weekly_verifier

st.set_page_config(page_title="Weekly Verification — R&D Controls", layout="wide")

st.title("Weekly Verification")
st.caption(
    "Compare customer-approved hours against employee-submitted timesheet hours, "
    "per employee per week."
)

# ---------------------------------------------------------------------------
# Load weekly approvals for the selector
# ---------------------------------------------------------------------------

conn = db.get_connection()
try:
    weekly_approvals = db.fetch_all(
        conn,
        """
        SELECT
            wa.id,
            wa.week_ending,
            wa.week_number,
            pp.period_start,
            pp.period_end,
            wa.payroll_pdf_file,
            wa.travel_pdf_file,
            (SELECT COUNT(*) FROM weekly_employee_verification v
             WHERE v.weekly_approval_id = wa.id) AS verif_count,
            (SELECT COUNT(*) FROM weekly_employee_verification v
             WHERE v.weekly_approval_id = wa.id AND v.status = 'verified') AS verified_count,
            (SELECT COUNT(*) FROM weekly_employee_verification v
             WHERE v.weekly_approval_id = wa.id AND v.status = 'needs_review') AS needs_review_count
        FROM weekly_approvals wa
        JOIN pay_periods pp ON pp.id = wa.pay_period_id
        ORDER BY wa.week_ending DESC
        """,
    )
finally:
    conn.close()

if not weekly_approvals:
    st.info(
        "No weekly approvals found. "
        "Use the **Import** page to ingest a payroll PDF first."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Weekly approval selector
# ---------------------------------------------------------------------------

def _approval_label(wa) -> str:
    verif    = wa["verif_count"]
    verified = wa["verified_count"]
    review   = wa["needs_review_count"]
    flag = ""
    if verif > 0:
        flag = f"  [{verified}/{verif} verified"
        if review > 0:
            flag += f", {review} needs review"
        flag += "]"
    return (
        f"Week ending {wa['week_ending']}  (Week {wa['week_number']} "
        f"of period {wa['period_start']} – {wa['period_end']})"
        + flag
    )

approval_options = {_approval_label(wa): wa["id"] for wa in weekly_approvals}
option_labels = list(approval_options.keys())

# Persist the selected weekly approval across reruns (e.g. after marking verified).
# Without this, st.rerun() resets the selectbox to index 0 (most recent week).
if "selected_wa_id" not in st.session_state:
    st.session_state["selected_wa_id"] = approval_options[option_labels[0]]

# Find the index of the currently selected wa_id in the current option list.
# If it's no longer present (e.g. after a DB change), fall back to 0.
current_wa_id = st.session_state["selected_wa_id"]
id_to_label = {v: k for k, v in approval_options.items()}
current_label = id_to_label.get(current_wa_id, option_labels[0])
current_index = option_labels.index(current_label) if current_label in option_labels else 0

selected_label = st.selectbox(
    "Select a weekly approval",
    options=option_labels,
    index=current_index,
    key="wa_selector",
)
selected_wa_id = approval_options[selected_label]
st.session_state["selected_wa_id"] = selected_wa_id

# Show which source files back this approval
conn = db.get_connection()
try:
    wa_row = db.fetch_one(
        conn,
        "SELECT payroll_pdf_file, travel_pdf_file FROM weekly_approvals WHERE id = ?",
        (selected_wa_id,),
    )
finally:
    conn.close()

col_pdf, col_travel = st.columns(2)
with col_pdf:
    st.caption(f"Payroll PDF: {wa_row['payroll_pdf_file'] or '—'}")
with col_travel:
    st.caption(f"Travel PDF: {wa_row['travel_pdf_file'] or '—'}")

st.divider()

# ---------------------------------------------------------------------------
# Run verification button
# ---------------------------------------------------------------------------

col_run, col_info = st.columns([1, 4])

with col_run:
    run_clicked = st.button(
        "Run Verification",
        type="primary",
        key="btn_run_verif",
        help="Compute or refresh verification rows for all employees in this week.",
    )

if run_clicked:
    with st.spinner("Running verification…"):
        conn = db.get_connection()
        try:
            summary = weekly_verifier.run_weekly_verification(conn, selected_wa_id)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            st.error(f"Verification failed: {exc}")
            summary = None
        finally:
            conn.close()

    if summary:
        with col_info:
            st.success(
                f"Verification complete — {summary.total_employees} employee(s)  |  "
                f"{summary.verified_count} verified  |  "
                f"{summary.needs_review_count} needs review  |  "
                f"{summary.pending_count} pending"
                + (
                    f"  |  {summary.provisonal_sunday_count} provisional Sunday"
                    if summary.provisonal_sunday_count else ""
                )
            )
        if summary.warnings:
            for w in summary.warnings:
                st.warning(w)

st.divider()

# ---------------------------------------------------------------------------
# Load and display verification rows
# ---------------------------------------------------------------------------

conn = db.get_connection()
try:
    verif_rows = weekly_verifier.get_verification_status(conn, selected_wa_id)
finally:
    conn.close()

if not verif_rows:
    st.info(
        "No verification rows yet for this week. "
        "Click **Run Verification** above to compute them."
    )
    st.stop()

# Summary bar
total      = len(verif_rows)
verified   = sum(1 for r in verif_rows if r.status == "verified")
needs_rev  = sum(1 for r in verif_rows if r.status == "needs_review")
pending    = sum(1 for r in verif_rows if r.status == "pending")

mcol1, mcol2, mcol3, mcol4 = st.columns(4)
mcol1.metric("Total", total)
mcol2.metric("Verified", verified)
mcol3.metric("Needs Review", needs_rev)
mcol4.metric("Pending", pending)

st.divider()

# ---------------------------------------------------------------------------
# Verify All button
# ---------------------------------------------------------------------------

unverified = [r for r in verif_rows if r.status != "verified"]
if unverified:
    with st.expander("Verify All Remaining", expanded=False):
        st.markdown(
            f"This will mark all **{len(unverified)} unverified** employee(s) as verified "
            "for this week. Only use this when you have reviewed everything manually."
        )
        va_note = st.text_input(
            "Note (required)",
            key="verify_all_note",
            placeholder="e.g. Reviewed all — no issues for this week",
        )
        if st.button("Confirm: Verify All", key="btn_verify_all", type="primary"):
            if not va_note.strip():
                st.warning("Please enter a note before verifying all.")
            else:
                conn = db.get_connection()
                try:
                    for r in unverified:
                        weekly_verifier.set_verified(
                            conn,
                            selected_wa_id,
                            r.employee_id,
                            note=va_note.strip(),
                        )
                    conn.commit()
                    st.success(f"Marked {len(unverified)} employee(s) as verified.")
                    st.rerun()
                except Exception as exc:
                    conn.rollback()
                    st.error(f"Failed: {exc}")
                finally:
                    conn.close()

st.divider()

# ---------------------------------------------------------------------------
# Per-employee verification table
# ---------------------------------------------------------------------------

_STATUS_ICON = {
    "verified":    "✅",
    "needs_review": "🔶",
    "pending":     "⬜",
}

_SUN_STATUS_LABEL = {
    "confirmed":               "Confirmed",
    "assumed_from_timesheet":  "Assumed (from timesheet)",
    "pending_next_pdf":        "Provisional — awaiting next travel PDF",
    "n/a":                     "—",
}

for row in verif_rows:
    icon = _STATUS_ICON.get(row.status, "⬜")

    with st.container(border=True):
        # --- Header row ---
        hcol1, hcol2, hcol3 = st.columns([3, 1, 2])
        with hcol1:
            st.markdown(f"### {icon} {row.display_name}")
        with hcol2:
            status_label = row.status.replace("_", " ").title()
            if row.status == "verified":
                st.success(status_label)
            elif row.status == "needs_review":
                st.warning(status_label)
            else:
                st.info(status_label)
        with hcol3:
            if row.verified_at:
                st.caption(f"Verified at: {row.verified_at}")

        # --- Hours comparison ---
        st.markdown("**Hours comparison**")

        hcols = st.columns([2, 1, 1, 1, 1, 1, 1, 1])
        hcols[0].caption("Category")
        hcols[1].caption("Approved Reg")
        hcols[2].caption("TS Reg")
        hcols[3].caption("Approved OT")
        hcols[4].caption("TS OT1")
        hcols[5].caption("Approved Dbl")
        hcols[6].caption("TS OT2")
        hcols[7].caption("Travel (Mon–Sat)")

        def _fmt(val: float) -> str:
            return f"{val:.2f}" if val != 0 else "—"

        def _var_fmt(val: float) -> str:
            if abs(val) < 0.01:
                return "✓"
            return f"**{val:+.2f}**"

        vcols = st.columns([2, 1, 1, 1, 1, 1, 1, 1])
        vcols[0].markdown("Hours")
        vcols[1].markdown(_fmt(row.approved_reg))
        vcols[2].markdown(_fmt(row.timesheet_week_reg))
        vcols[3].markdown(_fmt(row.approved_ot))
        vcols[4].markdown(_fmt(row.timesheet_week_ot1))
        vcols[5].markdown(_fmt(row.approved_dbl))
        vcols[6].markdown(_fmt(row.timesheet_week_ot2))
        vcols[7].markdown(_fmt(row.approved_travel))

        vcols2 = st.columns([2, 1, 1, 1, 1, 1, 1, 1])
        vcols2[0].caption("Variance (appr − TS)")
        vcols2[1].markdown(_var_fmt(row.reg_variance))
        vcols2[2].markdown("")
        vcols2[3].markdown(_var_fmt(row.ot_variance))
        vcols2[4].markdown("")
        vcols2[5].markdown(_var_fmt(row.dbl_variance))
        vcols2[6].markdown("")
        vcols2[7].markdown("")

        # --- Drive hours ---
        if row.timesheet_week_drive > 0:
            st.caption(f"Drive hours (timesheet): {row.timesheet_week_drive:.2f}")

        # --- Non-billable time types (vacation / sick / holiday / non-billable) ---
        # These have no customer-approved counterpart so they are informational only.
        non_billable_types = [
            ("Sick",         row.timesheet_week_sick),
            ("Vacation",     row.timesheet_week_vacation),
            ("Holiday",      row.timesheet_week_holiday),
            ("Non-billable", row.timesheet_week_nonbillable),
        ]
        non_zero = [(label, val) for label, val in non_billable_types if val > 0]
        if non_zero:
            parts = "  |  ".join(f"{label}: {val:.2f}" for label, val in non_zero)
            st.caption(f"Non-billable time: {parts}")

        # --- Travel Sunday status ---
        sun_label = _SUN_STATUS_LABEL.get(row.travel_sun_status, row.travel_sun_status)
        if row.travel_sun_status not in ("n/a", "confirmed"):
            st.warning(f"Sunday travel: {sun_label}  (assumed hours: {row.travel_sun_hours:.2f})")
        elif row.travel_sun_status == "confirmed" and row.travel_sun_hours > 0:
            st.caption(f"Sunday travel: {sun_label} — {row.travel_sun_hours:.2f} hrs")

        # --- Expenses ---
        if row.needs_expense_review:
            st.warning(
                f"Expense review needed — {row.extra_expense_note or 'non-per-diem expenses present'}"
            )
        if row.simple_per_diem_count > 0:
            st.caption(f"Per diem: {row.simple_per_diem_count:.0f} day(s)")
        if row.extra_expense_note and not row.needs_expense_review:
            st.caption(f"Note: {row.extra_expense_note}")

        # --- Verify action (only when not already verified) ---
        if row.status != "verified":
            st.markdown("---")
            note_key  = f"note_{row.employee_id}"
            btn_key   = f"btn_verify_{row.employee_id}"

            vcol1, vcol2 = st.columns([3, 1])
            with vcol1:
                verify_note = st.text_input(
                    "Note (optional)",
                    key=note_key,
                    placeholder="Add a note before marking verified…",
                    label_visibility="collapsed",
                )
            with vcol2:
                if st.button(f"Mark Verified", key=btn_key):
                    conn = db.get_connection()
                    try:
                        weekly_verifier.set_verified(
                            conn,
                            selected_wa_id,
                            row.employee_id,
                            note=verify_note.strip() or None,
                        )
                        conn.commit()
                        st.success(f"{row.display_name} marked as verified.")
                        st.rerun()
                    except Exception as exc:
                        conn.rollback()
                        st.error(f"Failed: {exc}")
                    finally:
                        conn.close()
