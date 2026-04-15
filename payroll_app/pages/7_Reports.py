"""
7_Reports.py — Payroll export, receipt backlog, and period summary reporting.

Three sections:
  1. Payroll Export — write the biweekly PayrollChequeRun workbook and Sage 50 CSV
     for a selected pay period. Both buttons are gated: all reconciliation rows must
     be in 'approved' or 'exported' status before writing is allowed.

  2. Receipt Backlog — show ALL expense items across ALL periods with
     receipt_status = 'missing'. Grouped by period and employee so the owner can
     scan the full outstanding backlog in one place.

  3. Period Summary Table — per-period totals (hours and invoice subtotal) for
     every period that has reconciliation data.

Engineering notes:
  - export_sage50_csv() reads from the PayrollChequeRun workbook that must be
    written first. If the workbook is missing or locked, the error is caught and
    displayed clearly rather than crashing.
  - Button gating is explicit: the gate condition is evaluated in Python and
    st.button() receives disabled=True when the gate is not met. A visible
    explanation is shown in the same column so the owner knows what to fix.
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from payroll_app import config
from payroll_app.database import db
from payroll_app.pipeline import cheque_run_writer, expense_exporter, reconciler

st.set_page_config(page_title="Reports — R&D Controls", layout="wide")

st.title("Reports")
st.caption(
    "Export payroll workbook and Sage 50 CSV, review the receipt backlog, "
    "and check period-level hour and billing totals."
)

# ===========================================================================
# SECTION 1 — Payroll Export
# ===========================================================================

st.header("1. Payroll Export")
st.caption(
    "Write the biweekly PayrollChequeRun workbook and Sage 50 CSV. "
    "Both exports require all reconciliation rows to be approved or exported. "
    "Write the workbook first — the Sage 50 CSV reads from it."
)

# ---------------------------------------------------------------------------
# Period selector — load all periods with reconciliation metadata
# ---------------------------------------------------------------------------

conn = db.get_connection()
try:
    export_periods = db.fetch_all(
        conn,
        """
        SELECT
            pp.id,
            pp.period_start,
            pp.period_end,
            (SELECT COUNT(*) FROM reconciliation r WHERE r.pay_period_id = pp.id) AS recon_rows,
            (SELECT COUNT(*) FROM reconciliation r WHERE r.pay_period_id = pp.id
             AND r.status IN ('approved', 'exported')) AS ready_rows,
            (SELECT COUNT(*) FROM reconciliation r WHERE r.pay_period_id = pp.id
             AND r.status = 'exported') AS exported_rows
        FROM pay_periods pp
        WHERE EXISTS (SELECT 1 FROM reconciliation r WHERE r.pay_period_id = pp.id)
        ORDER BY pp.period_end DESC
        """,
    )
finally:
    conn.close()

if not export_periods:
    st.info(
        "No reconciled pay periods found. "
        "Run and approve reconciliation on the Reconcile page first."
    )
else:
    def _export_period_label(pp) -> str:
        start    = pp["period_start"]
        end      = pp["period_end"]
        total    = pp["recon_rows"]
        ready    = pp["ready_rows"]
        exported = pp["exported_rows"]
        if ready < total:
            tag = f"{ready}/{total} approved — not ready"
        elif exported == total:
            tag = "all exported"
        else:
            tag = "all approved — ready to export"
        return f"{start} → {end}  [{tag}]"

    export_labels = [_export_period_label(pp) for pp in export_periods]

    # Default to most recent period where all rows are approved but not yet all exported
    default_export_idx = 0
    for i, pp in enumerate(export_periods):
        if pp["ready_rows"] == pp["recon_rows"] and pp["exported_rows"] < pp["recon_rows"]:
            default_export_idx = i
            break

    export_selected_idx = st.selectbox(
        "Pay period (export)",
        options=range(len(export_periods)),
        format_func=lambda i: export_labels[i],
        index=default_export_idx,
        key="export_period_selector",
    )
    export_period     = export_periods[export_selected_idx]
    export_period_id  = export_period["id"]
    period_end_str    = export_period["period_end"]  # YYYY-MM-DD
    period_end_yyyymmdd = period_end_str.replace("-", "")

    all_approved_for_export = (
        export_period["recon_rows"] > 0
        and export_period["ready_rows"] == export_period["recon_rows"]
    )

    # ---------------------------------------------------------------------------
    # Reconciliation status snapshot for selected export period
    # ---------------------------------------------------------------------------

    st.subheader("Reconciliation Status")
    st.caption(
        "All employees must be in 'approved' or 'exported' status before exporting. "
        "Use the Reconcile page to approve any pending or variance rows."
    )

    conn = db.get_connection()
    try:
        recon_rows_for_export = reconciler.get_reconciliation(conn, export_period_id)
    finally:
        conn.close()

    if recon_rows_for_export:
        # Compact summary table
        hdr_cols = st.columns([3, 1.5, 1.5, 1.5, 1.5, 2])
        hdr_cols[0].markdown("**Employee**")
        hdr_cols[1].markdown("**Reg**")
        hdr_cols[2].markdown("**OT**")
        hdr_cols[3].markdown("**DT**")
        hdr_cols[4].markdown("**Travel**")
        hdr_cols[5].markdown("**Status**")

        st.divider()

        _status_icon = {
            "pending":  "🟡 pending",
            "variance": "🔴 variance",
            "approved": "✅ approved",
            "exported": "📤 exported",
        }

        total_reg   = 0.0
        total_ot    = 0.0
        total_dbl   = 0.0
        total_drive = 0.0

        for row in recon_rows_for_export:
            r_cols = st.columns([3, 1.5, 1.5, 1.5, 1.5, 2])
            r_cols[0].write(row.display_name)
            r_cols[1].write(f"{row.final_reg:.2f}"   if row.final_reg   else "—")
            r_cols[2].write(f"{row.final_ot:.2f}"    if row.final_ot    else "—")
            r_cols[3].write(f"{row.final_dbl:.2f}"   if row.final_dbl   else "—")
            r_cols[4].write(f"{row.final_drive:.2f}" if row.final_drive else "—")
            r_cols[5].write(_status_icon.get(row.status, row.status))

            if row.assignment_type == config.ASSIGNMENT_BILLABLE:
                total_reg   += row.final_reg   or 0.0
                total_ot    += row.final_ot    or 0.0
                total_dbl   += row.final_dbl   or 0.0
                total_drive += row.final_drive or 0.0

        st.divider()

        # Key metrics for the period
        invoice_subtotal = (
            total_reg   * config.CENTERLINE_RATE_REG
            + total_ot  * config.CENTERLINE_RATE_OT1
            + total_dbl * config.CENTERLINE_RATE_OT2
            + total_drive * config.CENTERLINE_RATE_TRAVEL
        )

        metric_cols = st.columns(5)
        metric_cols[0].metric("Billable Reg Hrs",    f"{total_reg:.2f}")
        metric_cols[1].metric("Billable OT Hrs",     f"{total_ot:.2f}")
        metric_cols[2].metric("Billable DT Hrs",     f"{total_dbl:.2f}")
        metric_cols[3].metric("Billable Travel Hrs", f"{total_drive:.2f}")
        metric_cols[4].metric("Invoice Subtotal",    f"${invoice_subtotal:,.2f}")

    st.divider()

    # ---------------------------------------------------------------------------
    # Write Cheque Run Workbook button
    # ---------------------------------------------------------------------------

    st.subheader("Write Cheque Run Workbook")

    workbook_path = config.PAYROLL_CHEQUE_RUN_WORKBOOK

    btn_col_1, info_col_1 = st.columns([3, 5])

    with info_col_1:
        st.caption(f"Target workbook: `{workbook_path}`")
        if not all_approved_for_export:
            unapproved_n = export_period["recon_rows"] - export_period["ready_rows"]
            st.warning(
                f"{unapproved_n} employee(s) are not yet approved. "
                "All rows must be approved or exported before writing."
            )
        else:
            st.success(
                "All reconciliation rows are approved or exported. "
                "Ready to write the cheque run workbook."
            )

    with btn_col_1:
        dry_run_flag = st.checkbox("Dry run (preview only — do not write)", key="dry_run_flag")

        write_btn = st.button(
            "Write Cheque Run Workbook",
            disabled=not all_approved_for_export,
            type="primary" if all_approved_for_export else "secondary",
            key="write_cheque_run_btn",
        )

    if write_btn:
        conn = db.get_connection()
        try:
            result = cheque_run_writer.write_cheque_run(
                conn,
                export_period_id,
                workbook_path=workbook_path,
                dry_run=dry_run_flag,
            )
        finally:
            conn.close()

        if result.success:
            if dry_run_flag:
                st.info(
                    f"Dry run complete — {result.rows_written} row(s) would be written. "
                    "No file was modified."
                )
            else:
                st.success(
                    f"Cheque run written successfully — {result.rows_written} row(s) written "
                    f"to `{workbook_path}`."
                )
        else:
            st.error(
                f"Cheque run write FAILED — {len(result.errors)} error(s). "
                "See details below."
            )

        if result.warnings:
            with st.expander(f"Warnings ({len(result.warnings)})"):
                for w in result.warnings:
                    st.warning(w)

        if result.errors:
            with st.expander(f"Errors ({len(result.errors)})", expanded=True):
                for e in result.errors:
                    st.error(e)

    st.divider()

    # ---------------------------------------------------------------------------
    # Export Sage 50 CSV button
    # ---------------------------------------------------------------------------

    st.subheader("Export Sage 50 CSV")

    sage50_target = config.sage50_csv_filename(period_end_yyyymmdd)

    btn_col_2, info_col_2 = st.columns([3, 5])

    with info_col_2:
        st.caption(f"Target CSV: `{sage50_target}`")
        st.caption(
            "The Sage 50 CSV reads directly from the cheque run workbook. "
            "Write the workbook first — if it is missing or locked, the export will fail."
        )
        if not all_approved_for_export:
            st.warning(
                "All reconciliation rows must be approved or exported before exporting "
                "the Sage 50 CSV."
            )

    with btn_col_2:
        sage50_btn = st.button(
            "Export Sage 50 CSV",
            disabled=not all_approved_for_export,
            type="primary" if all_approved_for_export else "secondary",
            key="export_sage50_btn",
        )

    if sage50_btn:
        conn = db.get_connection()
        try:
            try:
                output_path = cheque_run_writer.export_sage50_csv(
                    conn,
                    export_period_id,
                    period_end_date=period_end_yyyymmdd,
                    workbook_path=workbook_path,
                )
                st.success(f"Sage 50 CSV exported successfully.")
                st.info(f"File written to: `{output_path}`")
            except FileNotFoundError as exc:
                st.error(
                    "Export failed — the PayrollChequeRun workbook was not found. "
                    "Write the cheque run workbook first, then re-run the Sage 50 export."
                )
                st.caption(f"Detail: {exc}")
            except PermissionError as exc:
                st.error(
                    "Export failed — the workbook is open or locked. "
                    "Close the PayrollChequeRun workbook in Excel and try again."
                )
                st.caption(f"Detail: {exc}")
            except Exception as exc:
                st.error(f"Export failed with an unexpected error: {exc}")
                st.caption(
                    "Check that the workbook has been written for this period and that "
                    "the Sage 50 export directory exists and is writable."
                )
        finally:
            conn.close()


st.divider()

# ===========================================================================
# SECTION 2 — Receipt Backlog (all periods)
# ===========================================================================

st.header("2. Receipt Backlog")
st.caption(
    "All expense items across all pay periods with receipt_status = 'missing'. "
    "Non-per-diem expenses cannot be reimbursed or billed until a receipt is on file. "
    "Use the Expenses page to mark individual receipts as received."
)

conn = db.get_connection()
try:
    backlog_rows = db.fetch_all(
        conn,
        """
        SELECT
            pp.period_start,
            pp.period_end,
            e.display_name,
            ei.work_date,
            ei.category,
            ei.currency,
            ei.amount,
            ei.receipt_status,
            ei.billing_status,
            ei.reimbursement_status
        FROM expense_items ei
        JOIN pay_periods pp ON pp.id = ei.pay_period_id
        JOIN employees e    ON e.id  = ei.employee_id
        WHERE ei.receipt_status = 'missing'
        ORDER BY pp.period_end DESC, e.display_name, ei.work_date, ei.category
        """,
    )
finally:
    conn.close()

if not backlog_rows:
    st.success("No receipts outstanding. All expense items have receipts on file.")
else:
    # Summary metric
    backlog_metric_cols = st.columns(3)
    backlog_metric_cols[0].metric("Items Missing Receipts", len(backlog_rows))

    cad_total = sum(
        float(r["amount"]) for r in backlog_rows if r["currency"] == "CAD"
    )
    usd_total = sum(
        float(r["amount"]) for r in backlog_rows if r["currency"] == "USD"
    )
    backlog_metric_cols[1].metric("CAD Outstanding", f"${cad_total:,.2f}")
    if usd_total > 0:
        backlog_metric_cols[2].metric("USD Outstanding", f"USD ${usd_total:,.2f}")

    st.divider()

    # Group by period then employee for scannable display
    # Build a dict: (period_start, period_end) -> employee_name -> [rows]
    from collections import defaultdict

    period_groups: dict[tuple, dict[str, list]] = {}
    for row in backlog_rows:
        period_key = (row["period_start"], row["period_end"])
        if period_key not in period_groups:
            period_groups[period_key] = defaultdict(list)
        period_groups[period_key][row["display_name"]].append(row)

    # Table header (shown once above all groups)
    tbl_hdr = st.columns([2.5, 2.5, 1.5, 2, 1, 1.5])
    tbl_hdr[0].markdown("**Period**")
    tbl_hdr[1].markdown("**Employee**")
    tbl_hdr[2].markdown("**Date**")
    tbl_hdr[3].markdown("**Category**")
    tbl_hdr[4].markdown("**Currency**")
    tbl_hdr[5].markdown("**Amount**")

    st.divider()

    for (period_start, period_end), emp_groups in period_groups.items():
        period_label = f"{period_start} → {period_end}"
        period_shown = False  # print period label only on first row of each period

        for emp_name, items in sorted(emp_groups.items()):
            emp_shown = False  # print employee name only on first row per employee

            for item in items:
                row_cols = st.columns([2.5, 2.5, 1.5, 2, 1, 1.5])

                # Period cell — only on first row of period
                if not period_shown:
                    row_cols[0].markdown(f"**{period_label}**")
                    period_shown = True
                else:
                    row_cols[0].write("")

                # Employee cell — only on first row per employee within period
                if not emp_shown:
                    row_cols[1].write(emp_name)
                    emp_shown = True
                else:
                    row_cols[1].write("")

                row_cols[2].write(item["work_date"] or "—")
                row_cols[3].write(item["category"].replace("_", " "))
                row_cols[4].write(item["currency"])
                row_cols[5].write(f"${float(item['amount']):.2f}")

        # Thin visual separator between periods
        st.markdown(
            '<hr style="margin:4px 0; border-top:1px dashed #ccc;">',
            unsafe_allow_html=True,
        )


st.divider()

# ===========================================================================
# SECTION 3 — Period Summary Table
# ===========================================================================

st.header("3. Period Summary")
st.caption(
    "Per-period totals for all periods with reconciliation data. "
    "Invoice subtotal is computed from billable employees only "
    f"(Reg × ${config.CENTERLINE_RATE_REG:.2f}, "
    f"OT × ${config.CENTERLINE_RATE_OT1:.2f}, "
    f"DT × ${config.CENTERLINE_RATE_OT2:.2f}, "
    f"Travel × ${config.CENTERLINE_RATE_TRAVEL:.2f}). "
    "HST is not included in this column."
)

conn = db.get_connection()
try:
    summary_periods = db.fetch_all(
        conn,
        """
        SELECT
            pp.id,
            pp.period_start,
            pp.period_end
        FROM pay_periods pp
        WHERE EXISTS (SELECT 1 FROM reconciliation r WHERE r.pay_period_id = pp.id)
        ORDER BY pp.period_end DESC
        """,
    )

    # For each period, pull per-employee reconciliation totals
    # We only need billable rows for the invoice subtotal, but we show
    # all-employee totals for the hours columns.
    period_summaries: list[dict] = []

    for pp in summary_periods:
        pp_id = pp["id"]

        # Total hours across ALL employees
        totals_all = db.fetch_one(
            conn,
            """
            SELECT
                COALESCE(SUM(final_reg),   0) AS total_reg,
                COALESCE(SUM(final_ot),    0) AS total_ot,
                COALESCE(SUM(final_dbl),   0) AS total_dbl,
                COALESCE(SUM(final_drive), 0) AS total_drive,
                COUNT(*) AS employee_count,
                SUM(CASE WHEN status IN ('approved', 'exported') THEN 1 ELSE 0 END) AS approved_count,
                SUM(CASE WHEN status = 'exported' THEN 1 ELSE 0 END) AS exported_count
            FROM reconciliation
            WHERE pay_period_id = ?
            """,
            (pp_id,),
        )

        # Billable hours only (for invoice subtotal)
        totals_billable = db.fetch_one(
            conn,
            """
            SELECT
                COALESCE(SUM(r.final_reg),   0) AS bill_reg,
                COALESCE(SUM(r.final_ot),    0) AS bill_ot,
                COALESCE(SUM(r.final_dbl),   0) AS bill_dbl,
                COALESCE(SUM(r.final_drive), 0) AS bill_drive
            FROM reconciliation r
            JOIN employees e ON e.id = r.employee_id
            JOIN employee_assignments ea
                ON ea.employee_id = e.id
               AND ea.assignment_type = ?
               AND ea.effective_start <= ?
               AND (ea.effective_end IS NULL OR ea.effective_end >= ?)
            WHERE r.pay_period_id = ?
            """,
            (
                config.ASSIGNMENT_BILLABLE,
                pp["period_end"],
                pp["period_start"],
                pp_id,
            ),
        )

        # Invoice subtotal (billable only, before HST)
        bill_reg   = float(totals_billable["bill_reg"]   or 0)
        bill_ot    = float(totals_billable["bill_ot"]    or 0)
        bill_dbl   = float(totals_billable["bill_dbl"]   or 0)
        bill_drive = float(totals_billable["bill_drive"] or 0)

        invoice_subtotal = (
            bill_reg   * config.CENTERLINE_RATE_REG
            + bill_ot  * config.CENTERLINE_RATE_OT1
            + bill_dbl * config.CENTERLINE_RATE_OT2
            + bill_drive * config.CENTERLINE_RATE_TRAVEL
        )

        total_n    = totals_all["employee_count"] or 0
        approved_n = totals_all["approved_count"] or 0
        exported_n = totals_all["exported_count"] or 0

        if exported_n == total_n:
            status_tag = "exported"
        elif approved_n == total_n:
            status_tag = "approved"
        elif approved_n > 0:
            status_tag = f"{approved_n}/{total_n} approved"
        else:
            status_tag = "pending"

        period_summaries.append(
            {
                "period_start":      pp["period_start"],
                "period_end":        pp["period_end"],
                "total_reg":         float(totals_all["total_reg"]   or 0),
                "total_ot":          float(totals_all["total_ot"]    or 0),
                "total_dbl":         float(totals_all["total_dbl"]   or 0),
                "total_drive":       float(totals_all["total_drive"] or 0),
                "invoice_subtotal":  invoice_subtotal,
                "employee_count":    total_n,
                "status_tag":        status_tag,
            }
        )

finally:
    conn.close()

if not period_summaries:
    st.info("No reconciled periods found yet.")
else:
    # Header row
    sum_hdr = st.columns([2.5, 1.2, 1.2, 1.2, 1.5, 2, 1.5, 1.5])
    sum_hdr[0].markdown("**Period**")
    sum_hdr[1].markdown("**Total Reg**")
    sum_hdr[2].markdown("**Total OT**")
    sum_hdr[3].markdown("**Total DT**")
    sum_hdr[4].markdown("**Total Travel**")
    sum_hdr[5].markdown("**Invoice Subtotal**")
    sum_hdr[6].markdown("**Employees**")
    sum_hdr[7].markdown("**Status**")

    st.divider()

    for ps in period_summaries:
        s_cols = st.columns([2.5, 1.2, 1.2, 1.2, 1.5, 2, 1.5, 1.5])
        s_cols[0].write(f"{ps['period_start']} → {ps['period_end']}")
        s_cols[1].write(f"{ps['total_reg']:.2f}")
        s_cols[2].write(f"{ps['total_ot']:.2f}")
        s_cols[3].write(f"{ps['total_dbl']:.2f}")
        s_cols[4].write(f"{ps['total_drive']:.2f}")
        s_cols[5].write(f"${ps['invoice_subtotal']:,.2f}")
        s_cols[6].write(str(ps["employee_count"]))
        s_cols[7].write(ps["status_tag"])

    st.divider()

    # Grand totals across all periods
    grand_reg    = sum(ps["total_reg"]        for ps in period_summaries)
    grand_ot     = sum(ps["total_ot"]         for ps in period_summaries)
    grand_dbl    = sum(ps["total_dbl"]        for ps in period_summaries)
    grand_drive  = sum(ps["total_drive"]      for ps in period_summaries)
    grand_inv    = sum(ps["invoice_subtotal"] for ps in period_summaries)

    st.subheader("All-Periods Totals")
    grand_cols = st.columns(5)
    grand_cols[0].metric("Total Reg Hrs (all periods)",    f"{grand_reg:.2f}")
    grand_cols[1].metric("Total OT Hrs (all periods)",     f"{grand_ot:.2f}")
    grand_cols[2].metric("Total DT Hrs (all periods)",     f"{grand_dbl:.2f}")
    grand_cols[3].metric("Total Travel Hrs (all periods)", f"{grand_drive:.2f}")
    grand_cols[4].metric("Total Invoice Subtotal",         f"${grand_inv:,.2f}")
