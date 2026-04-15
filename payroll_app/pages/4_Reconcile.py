"""
4_Reconcile.py — Biweekly payroll reconciliation and invoice table.

Workflow:
  1. Select a pay period.
  2. Review the pre-flight state — are both weeks verified? Is travel accounted for?
  3. Run (or re-run) reconciliation to compute final payroll hours.
  4. Review per-employee results; approve individual rows or all pending at once.
  5. Export the invoice table once all employees are approved.

Travel notes:
  If a weekly approval has no travel PDF, an "Assume from Timesheet" section
  appears here.  Each assumption requires a written note (why no PDF was received).
"""

import io
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from payroll_app import config
from payroll_app.database import db
from payroll_app.pipeline import reconciler, weekly_verifier

st.set_page_config(page_title="Reconcile — R&D Controls", layout="wide")

st.title("Reconcile")
st.caption(
    "Run biweekly reconciliation, approve employee final hours, "
    "and export the invoice table for Centerline."
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
            (SELECT COUNT(*) FROM reconciliation r WHERE r.pay_period_id = pp.id) AS recon_rows,
            (SELECT COUNT(*) FROM reconciliation r WHERE r.pay_period_id = pp.id
             AND r.status = 'approved') AS approved_rows,
            (SELECT COUNT(*) FROM reconciliation r WHERE r.pay_period_id = pp.id
             AND r.status = 'variance') AS variance_rows
        FROM pay_periods pp
        ORDER BY pp.period_end DESC
        """,
    )
finally:
    conn.close()

if not pay_periods:
    st.warning("No pay periods found. Import payroll PDFs first.")
    st.stop()

# Build display labels with status suffix
def _period_label(pp) -> str:
    start = pp["period_start"]
    end   = pp["period_end"]
    rows  = pp["recon_rows"]
    appr  = pp["approved_rows"]
    var   = pp["variance_rows"]
    if rows == 0:
        tag = "no recon"
    elif var > 0:
        tag = f"⚠ {var} variance"
    elif appr < rows:
        tag = f"{appr}/{rows} approved"
    else:
        tag = "✓ all approved"
    return f"{start} → {end}  [{tag}]"

period_labels = [_period_label(pp) for pp in pay_periods]

# Default to first period with un-approved rows, otherwise first
default_idx = 0
for i, pp in enumerate(pay_periods):
    if pp["recon_rows"] == 0 or pp["approved_rows"] < pp["recon_rows"]:
        default_idx = i
        break

selected_idx = st.selectbox(
    "Pay period",
    options=range(len(pay_periods)),
    format_func=lambda i: period_labels[i],
    index=default_idx,
)
selected_period = pay_periods[selected_idx]
pay_period_id   = selected_period["id"]

st.divider()


# ---------------------------------------------------------------------------
# Load period overview (weeks, travel, verification)
# ---------------------------------------------------------------------------

conn = db.get_connection()
try:
    weekly_approvals = db.fetch_all(
        conn,
        """
        SELECT
            wa.id,
            wa.week_number,
            wa.week_ending,
            wa.payroll_pdf_file,
            wa.travel_pdf_file,
            (SELECT COUNT(*) FROM weekly_employee_verification v
             WHERE v.weekly_approval_id = wa.id) AS verif_total,
            (SELECT COUNT(*) FROM weekly_employee_verification v
             WHERE v.weekly_approval_id = wa.id AND v.status = 'verified') AS verified_count,
            (SELECT COUNT(*) FROM weekly_employee_verification v
             WHERE v.weekly_approval_id = wa.id AND v.status = 'needs_review') AS needs_review_count
        FROM weekly_approvals wa
        WHERE wa.pay_period_id = ?
        ORDER BY wa.week_number
        """,
        (pay_period_id,),
    )

    timesheet_count = db.fetch_one(
        conn,
        "SELECT COUNT(*) AS n FROM timesheet_imports WHERE pay_period_id = ?",
        (pay_period_id,),
    )["n"]

finally:
    conn.close()


# ---------------------------------------------------------------------------
# Period overview cards
# ---------------------------------------------------------------------------

st.subheader("Period Overview")

week_cols = st.columns(len(weekly_approvals) + 1)

for col_idx, wa in enumerate(weekly_approvals):
    with week_cols[col_idx]:
        verif_pct = (
            f"{wa['verified_count']}/{wa['verif_total']} verified"
            if wa["verif_total"] > 0
            else "no verifications"
        )
        verif_ok = (
            wa["verif_total"] > 0
            and wa["needs_review_count"] == 0
            and wa["verified_count"] == wa["verif_total"]
        )
        verif_icon = "✅" if verif_ok else ("⚠️" if wa["needs_review_count"] > 0 else "🔲")

        payroll_name = wa["payroll_pdf_file"] or "—"
        travel_name  = wa["travel_pdf_file"]  or None

        st.markdown(f"**Week {wa['week_number']}** — ending {wa['week_ending']}")
        st.markdown(f"Payroll: `{payroll_name}`")
        if travel_name:
            st.markdown(f"Travel: `{travel_name}`  ✅")
        else:
            st.markdown("Travel: *(no PDF)* ⚠️")
        st.markdown(f"Verification: {verif_icon} {verif_pct}")

with week_cols[-1]:
    st.markdown("**Timesheets**")
    st.metric("Imported", timesheet_count)

st.divider()


# ---------------------------------------------------------------------------
# Travel assumption: one expander per week with no travel PDF
# ---------------------------------------------------------------------------

weeks_without_travel = [wa for wa in weekly_approvals if not wa["travel_pdf_file"]]

if weeks_without_travel:
    st.subheader("Missing Travel PDFs")
    st.caption(
        "These weeks have no travel PDF. "
        "If employees had drive hours, use the form below to assume travel from their timesheets. "
        "A written note is required."
    )

    for wa in weeks_without_travel:
        wa_id   = wa["id"]
        wa_end  = wa["week_ending"]
        wa_week = wa["week_number"]

        with st.expander(f"Week {wa_week} (ending {wa_end}) — Assume Travel from Timesheet"):

            # Show employees who have drive hours in their timesheets for this week
            conn = db.get_connection()
            try:
                employees_with_drive = db.fetch_all(
                    conn,
                    """
                    SELECT e.id, e.display_name,
                           SUM(td.drive_hours) AS total_drive
                    FROM timesheet_days td
                    JOIN employees e ON e.id = td.employee_id
                    JOIN timesheet_hours th
                        ON th.employee_id = td.employee_id
                       AND th.pay_period_id = (
                               SELECT pay_period_id FROM weekly_approvals WHERE id = ?
                           )
                    WHERE td.work_date BETWEEN
                          DATE(?, '-6 days') AND ?
                      AND td.drive_hours > 0
                    GROUP BY e.id, e.display_name
                    ORDER BY e.display_name
                    """,
                    (wa_id, wa_end, wa_end),
                )

                # Also check which employees already have a travel row for this week
                existing_travel = db.fetch_all(
                    conn,
                    """
                    SELECT th.employee_id, e.display_name,
                           th.current_week_total, th.current_sun_status,
                           th.current_sun_hours_assumed
                    FROM travel_hours th
                    JOIN employees e ON e.id = th.employee_id
                    WHERE th.weekly_approval_id = ?
                    """,
                    (wa_id,),
                )
            finally:
                conn.close()

            existing_travel_map = {r["employee_id"]: r for r in existing_travel}

            if not employees_with_drive:
                st.info("No employees with timesheet drive hours found for this week.")
            else:
                st.write("Employees with drive hours in their timesheets:")
                for emp in employees_with_drive:
                    travel_row = existing_travel_map.get(emp["id"])
                    if travel_row:
                        status = travel_row["current_sun_status"]
                        if status == "assumed_from_timesheet":
                            st.write(
                                f"  ✅ **{emp['display_name']}** — already assumed "
                                f"({travel_row['current_week_total']:.1f} hr + "
                                f"{travel_row['current_sun_hours_assumed']:.1f} hr Sun)"
                            )
                            continue
                    st.write(
                        f"  🔲 **{emp['display_name']}** — "
                        f"{emp['total_drive']:.1f} hr drive in timesheet"
                    )

            assume_note_key = f"assume_note_{wa_id}"
            note_val = st.text_input(
                "Note (required — explain why no travel PDF was received)",
                key=assume_note_key,
                placeholder="e.g. Centerline did not send a travel PDF for this week.",
            )

            if st.button(
                f"Assume travel from timesheets for Week {wa_week}",
                key=f"assume_btn_{wa_id}",
                disabled=not note_val.strip(),
            ):
                if not note_val.strip():
                    st.error("A note is required before assuming travel.")
                else:
                    conn = db.get_connection()
                    try:
                        assumed_count = 0
                        skipped_count = 0
                        errors: list[str] = []
                        for emp in employees_with_drive:
                            travel_row = existing_travel_map.get(emp["id"])
                            if travel_row and travel_row["current_sun_status"] == "assumed_from_timesheet":
                                skipped_count += 1
                                continue
                            try:
                                weekly_verifier.assume_travel_from_timesheet(
                                    conn,
                                    wa_id,
                                    emp["id"],
                                    note=note_val.strip(),
                                )
                                assumed_count += 1
                            except ValueError as exc:
                                errors.append(f"{emp['display_name']}: {exc}")

                        conn.commit()
                    finally:
                        conn.close()

                    if assumed_count > 0:
                        st.success(f"Assumed travel for {assumed_count} employee(s).")
                    if skipped_count > 0:
                        st.info(f"{skipped_count} employee(s) already had assumed travel (skipped).")
                    for err in errors:
                        st.error(err)
                    st.rerun()

    st.divider()


# ---------------------------------------------------------------------------
# Run / Re-run reconciliation
# ---------------------------------------------------------------------------

st.subheader("Reconciliation")

conn = db.get_connection()
try:
    existing_recon = db.fetch_all(
        conn,
        "SELECT status FROM reconciliation WHERE pay_period_id = ?",
        (pay_period_id,),
    )
finally:
    conn.close()

recon_run = len(existing_recon) > 0
all_approved = recon_run and all(r["status"] in ("approved", "exported") for r in existing_recon)
has_variance = any(r["status"] == "variance" for r in existing_recon)

btn_col, info_col = st.columns([2, 5])

with btn_col:
    if not recon_run:
        run_btn = st.button("▶ Run Reconciliation", type="primary")
        force_run = False
    else:
        run_btn   = st.button("↺ Re-run Reconciliation")
        force_run = st.checkbox("Force re-run (overrides approved rows)", value=False)

with info_col:
    if not recon_run:
        st.info("Reconciliation has not been run for this period yet.")
    elif has_variance:
        var_n = sum(1 for r in existing_recon if r["status"] == "variance")
        st.warning(f"{var_n} employee(s) have variance — review required before approving.")
    elif all_approved:
        st.success("All employees approved. Ready to export invoice table.")
    else:
        pend_n = sum(1 for r in existing_recon if r["status"] == "pending")
        st.info(f"{pend_n} employee(s) pending approval.")

if run_btn:
    conn = db.get_connection()
    try:
        try:
            summary = reconciler.run_reconciliation(
                conn,
                pay_period_id,
                force=force_run,
            )
            conn.commit()
            st.success(
                f"Reconciliation complete — {summary.total_employees} employees: "
                f"{summary.variance_count} variance, "
                f"{summary.pending_count} pending, "
                f"{summary.approved_count} already approved."
            )
            for w in summary.warnings:
                st.warning(w)
        except reconciler.ReconciliationBlockedError as exc:
            st.error(str(exc))
    finally:
        conn.close()
    st.rerun()


# ---------------------------------------------------------------------------
# Reconciliation table
# ---------------------------------------------------------------------------

if not recon_run:
    st.stop()

conn = db.get_connection()
try:
    recon_rows = reconciler.get_reconciliation(conn, pay_period_id)
finally:
    conn.close()

if not recon_rows:
    st.info("No reconciliation rows found.")
    st.stop()

st.markdown("**Per-employee results** — approved hours are final payroll values.")

# Table header
hdr = st.columns([2.5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1.5, 2])
hdr[0].markdown("**Employee**")
hdr[1].markdown("**TS Reg**")
hdr[2].markdown("**TS OT**")
hdr[3].markdown("**TS DT**")
hdr[4].markdown("**Cust Reg**")
hdr[5].markdown("**Cust OT**")
hdr[6].markdown("**Cust DT**")
hdr[7].markdown("**Travel**")
hdr[8].markdown("**Final Reg**")
hdr[9].markdown("**Final OT**")
hdr[10].markdown("**Final DT**")
hdr[11].markdown("**Status**")
hdr[12].markdown("**Action**")

st.divider()

def _fmt(v: float) -> str:
    return f"{v:.2f}" if v else "—"

def _status_badge(status: str) -> str:
    return {
        "pending":  "🟡 pending",
        "variance": "🔴 variance",
        "approved": "✅ approved",
        "exported": "📤 exported",
    }.get(status, status)


for row in recon_rows:
    is_variance = row.status == "variance"
    is_approved = row.status in ("approved", "exported")

    # Highlight variance rows
    if is_variance:
        st.markdown(
            '<div style="background:#fff3cd; border-left:4px solid #f0a500; '
            'padding:2px 6px; margin:2px 0; border-radius:2px;">',
            unsafe_allow_html=True,
        )

    cols = st.columns([2.5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1.5, 2])
    cols[0].write(row.display_name)
    cols[1].write(_fmt(row.ts_reg))
    cols[2].write(_fmt(row.ts_ot))
    cols[3].write(_fmt(row.ts_dbl))
    cols[4].write(_fmt(row.cust_reg))
    cols[5].write(_fmt(row.cust_ot))
    cols[6].write(_fmt(row.cust_dbl))
    cols[7].write(_fmt(row.final_drive))
    cols[8].write(_fmt(row.final_reg))
    cols[9].write(_fmt(row.final_ot))
    cols[10].write(_fmt(row.final_dbl))
    cols[11].write(_status_badge(row.status))

    with cols[12]:
        if not is_approved:
            approve_key = f"approve_{row.employee_id}"
            if st.button("Approve", key=approve_key, type="primary" if not is_variance else "secondary"):
                conn = db.get_connection()
                try:
                    reconciler.approve_reconciliation(
                        conn,
                        pay_period_id,
                        row.employee_id,
                        approved_by="Drew",
                    )
                    conn.commit()
                finally:
                    conn.close()
                st.rerun()
        else:
            st.write("—")

    if is_variance:
        # Show variance detail below the row
        var_details = []
        if abs(row.reg_variance) > 0.01:
            var_details.append(f"Reg Δ {row.reg_variance:+.2f}")
        if abs(row.ot_variance) > 0.01:
            var_details.append(f"OT Δ {row.ot_variance:+.2f}")
        if abs(row.dbl_variance) > 0.01:
            var_details.append(f"DT Δ {row.dbl_variance:+.2f}")
        detail_str = "  |  ".join(var_details)
        st.caption(f"⚠ Variance: {detail_str} — Approved hours used for payroll; timesheet differs.")
        st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# ---------------------------------------------------------------------------
# Approve All Pending
# ---------------------------------------------------------------------------

pending_rows = [r for r in recon_rows if r.status == "pending"]
variance_rows = [r for r in recon_rows if r.status == "variance"]

if pending_rows or variance_rows:
    approve_col, note_col = st.columns([2, 5])
    with note_col:
        bulk_note = st.text_input(
            "Approval note (optional)",
            key="bulk_approve_note",
            placeholder="e.g. Both weeks reviewed, no issues.",
        )
    with approve_col:
        btn_label = f"Approve All Pending ({len(pending_rows)})"
        if variance_rows:
            st.caption(
                f"{len(variance_rows)} variance row(s) must be approved individually above."
            )
        if st.button(btn_label, disabled=len(pending_rows) == 0):
            conn = db.get_connection()
            try:
                approved_n = reconciler.approve_all(
                    conn,
                    pay_period_id,
                    notes=bulk_note.strip() or None,
                    approved_by="Drew",
                )
                conn.commit()
            finally:
                conn.close()
            st.success(f"Approved {approved_n} employee(s).")
            st.rerun()

    st.divider()


# ---------------------------------------------------------------------------
# Invoice Table
# ---------------------------------------------------------------------------

st.subheader("Invoice Table")

if not all_approved:
    unapproved_n = sum(1 for r in recon_rows if r.status not in ("approved", "exported"))
    st.info(
        f"{unapproved_n} employee(s) are not yet approved. "
        "Approve all employees above to unlock the invoice table."
    )
    st.stop()


def _get_invoice_data(conn, pay_period_id: int) -> list[dict]:
    """Build invoice line items for all billable employees in the period.

    Returns a list of row dicts with keys:
        employee, item_no, unit, qty, description, tax, unit_price, amount

    Rows with qty == 0 are included (shown as blank in the invoice).
    One section per billable employee, sorted by display_name.
    """
    recon_rows_local = reconciler.get_reconciliation(conn, pay_period_id)

    # Per-diem totals: sum of quantity where category is per-diem, CAD only
    perdiem_rows = db.fetch_all(
        conn,
        f"""
        SELECT ei.employee_id, SUM(ei.quantity) AS total_days
        FROM expense_items ei
        WHERE ei.pay_period_id = ?
          AND ei.category IN ({','.join('?' * len(config.PER_DIEM_CATEGORIES))})
          AND ei.currency = 'CAD'
        GROUP BY ei.employee_id
        """,
        (pay_period_id, *config.PER_DIEM_CATEGORIES),
    )
    perdiem_map = {r["employee_id"]: float(r["total_days"] or 0) for r in perdiem_rows}

    # Non-per-diem billable expenses (CAD, ready to bill or already billed)
    expense_rows = db.fetch_all(
        conn,
        f"""
        SELECT ei.employee_id, ei.category, ei.description, ei.amount
        FROM expense_items ei
        WHERE ei.pay_period_id = ?
          AND ei.category NOT IN ({','.join('?' * len(config.PER_DIEM_CATEGORIES))})
          AND ei.currency = 'CAD'
          AND ei.billing_status IN ('ready_for_billing', 'billed')
        ORDER BY ei.employee_id, ei.work_date, ei.category
        """,
        (pay_period_id, *config.PER_DIEM_CATEGORIES),
    )
    # Group by employee_id
    expense_map: dict[int, list[dict]] = {}
    for row in expense_rows:
        eid = row["employee_id"]
        expense_map.setdefault(eid, []).append(dict(row))

    lines: list[dict] = []

    billable_rows = [r for r in recon_rows_local if r.assignment_type == config.ASSIGNMENT_BILLABLE]

    for emp in billable_rows:
        eid = emp.employee_id
        name = emp.display_name

        def _line(item_no, description, qty, unit_price):
            amount = round(qty * unit_price, 2) if qty else None
            return {
                "employee":   name,
                "item_no":    item_no,
                "unit":       "Each",
                "qty":        qty if qty else None,
                "description": description,
                "tax":        "H",
                "unit_price": unit_price,
                "amount":     amount,
            }

        lines.append(_line(config.INVOICE_ITEM_REG,    "Centerline - Standard - Regular",    emp.final_reg,   config.CENTERLINE_RATE_REG))
        lines.append(_line(config.INVOICE_ITEM_OT1,    "Centerline - Standard - Overtime 1", emp.final_ot,    config.CENTERLINE_RATE_OT1))
        lines.append(_line(config.INVOICE_ITEM_OT2,    "Centerline - Standard - Overtime 2", emp.final_dbl,   config.CENTERLINE_RATE_OT2))
        lines.append(_line(config.INVOICE_ITEM_TRAVEL, "Centerline - Standard - Travel",     emp.final_drive, config.CENTERLINE_RATE_TRAVEL))

        perdiem_days = perdiem_map.get(eid, 0.0)
        lines.append(_line(config.INVOICE_ITEM_PERDIEM, "Centerline Per Diem", perdiem_days, config.CENTERLINE_RATE_PERDIEM))

        # Expenses — one line each
        for exp in expense_map.get(eid, []):
            cat_label = exp["category"].replace("_", " ").title()
            desc      = exp["description"] or cat_label
            lines.append({
                "employee":    name,
                "item_no":     config.INVOICE_ITEM_EXPENSE,
                "unit":        "Each",
                "qty":         1.0,
                "description": f"Centerline Expenses - {desc}",
                "tax":         "H",
                "unit_price":  round(float(exp["amount"]), 2),
                "amount":      round(float(exp["amount"]), 2),
            })
        # Always include a blank expenses placeholder if no expense lines
        if not expense_map.get(eid):
            lines.append({
                "employee":    name,
                "item_no":     config.INVOICE_ITEM_EXPENSE,
                "unit":        "Each",
                "qty":         None,
                "description": "Centerline Expenses",
                "tax":         "H",
                "unit_price":  1.00,
                "amount":      None,
            })

    return lines


conn = db.get_connection()
try:
    invoice_lines = _get_invoice_data(conn, pay_period_id)
finally:
    conn.close()

# Compute subtotal, HST, total
subtotal = sum(line["amount"] for line in invoice_lines if line["amount"])
hst      = round(subtotal * config.HST_RATE, 2)
total    = round(subtotal + hst, 2)

# ---------------------------------------------------------------------------
# Display invoice table
# ---------------------------------------------------------------------------

st.caption(
    "This table matches the invoice format for Centerline. "
    "Enter these values into Sage 50 / your invoicing software in this order."
)

# Column headers
inv_hdr = st.columns([2.5, 2, 1, 1.5, 3.5, 0.5, 1.2, 1.5])
inv_hdr[0].markdown("**Employee**")
inv_hdr[1].markdown("**Item No.**")
inv_hdr[2].markdown("**Unit**")
inv_hdr[3].markdown("**Qty**")
inv_hdr[4].markdown("**Description**")
inv_hdr[5].markdown("**Tax**")
inv_hdr[6].markdown("**Unit Price**")
inv_hdr[7].markdown("**Amount**")

st.divider()

last_employee = None
for line in invoice_lines:
    if line["employee"] != last_employee:
        st.markdown(f"**★ {line['employee']}**")
        last_employee = line["employee"]

    cols = st.columns([2.5, 2, 1, 1.5, 3.5, 0.5, 1.2, 1.5])
    cols[0].write("")                                   # employee column left blank on line rows
    cols[1].write(line["item_no"])
    cols[2].write(line["unit"])
    cols[3].write(f"{line['qty']:.2f}" if line["qty"] else "")
    cols[4].write(line["description"])
    cols[5].write(line["tax"])
    cols[6].write(f"{line['unit_price']:.2f}")
    cols[7].write(f"{line['amount']:.2f}" if line["amount"] else "")

st.divider()

# Totals
tot_cols = st.columns([2.5, 2, 1, 1.5, 3.5, 0.5, 1.2, 1.5])
tot_cols[4].markdown("**Subtotal:**")
tot_cols[7].markdown(f"**{subtotal:,.2f}**")

hst_row = st.columns([2.5, 2, 1, 1.5, 3.5, 0.5, 1.2, 1.5])
hst_row[4].markdown("**HST (13%):**")
hst_row[7].markdown(f"**{hst:,.2f}**")

final_row = st.columns([2.5, 2, 1, 1.5, 3.5, 0.5, 1.2, 1.5])
final_row[4].markdown("**Total Amount Owing:**")
final_row[7].markdown(f"**{total:,.2f}**")

st.divider()

# ---------------------------------------------------------------------------
# Checksums
# ---------------------------------------------------------------------------

st.subheader("Checksums")
st.caption("Verify these against your invoice software totals before sending.")

billable_rows_final = [r for r in recon_rows if r.assignment_type == config.ASSIGNMENT_BILLABLE]

chk_cols = st.columns(6)
chk_cols[0].metric("Total Reg Hrs",    f"{sum(r.final_reg   for r in billable_rows_final):.2f}")
chk_cols[1].metric("Total OT1 Hrs",    f"{sum(r.final_ot    for r in billable_rows_final):.2f}")
chk_cols[2].metric("Total OT2 Hrs",    f"{sum(r.final_dbl   for r in billable_rows_final):.2f}")
chk_cols[3].metric("Total Travel Hrs", f"{sum(r.final_drive for r in billable_rows_final):.2f}")
chk_cols[4].metric("Subtotal (pre-HST)", f"${subtotal:,.2f}")
chk_cols[5].metric("Total Owing",        f"${total:,.2f}")

st.divider()

# ---------------------------------------------------------------------------
# Export invoice table to CSV
# ---------------------------------------------------------------------------

st.subheader("Export")

def _build_csv(lines: list[dict], subtotal: float, hst: float, total: float) -> bytes:
    """Build a CSV representation of the invoice table."""
    import csv as _csv

    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["Employee", "Item No.", "Unit", "Qty", "Description", "Tax", "Unit Price", "Amount"])

    current_emp = None
    for line in lines:
        if line["employee"] != current_emp:
            writer.writerow([f"*** {line['employee']}"])
            current_emp = line["employee"]
        writer.writerow([
            "",
            line["item_no"],
            line["unit"],
            f"{line['qty']:.2f}" if line["qty"] else "",
            line["description"],
            line["tax"],
            f"{line['unit_price']:.2f}",
            f"{line['amount']:.2f}" if line["amount"] else "",
        ])

    writer.writerow([])
    writer.writerow(["", "", "", "", "Subtotal:", "", "", f"{subtotal:.2f}"])
    writer.writerow(["", "", "", "", f"HST ({config.HST_RATE*100:.0f}%):", "", "", f"{hst:.2f}"])
    writer.writerow(["", "", "", "", "Total Amount Owing:", "", "", f"{total:.2f}"])

    return buf.getvalue().encode("utf-8-sig")   # BOM for Excel compatibility


period_end_str = selected_period["period_end"].replace("-", "")
csv_data = _build_csv(invoice_lines, subtotal, hst, total)

st.download_button(
    label="Download Invoice Table (CSV)",
    data=csv_data,
    file_name=f"invoice_table_{period_end_str}.csv",
    mime="text/csv",
)
