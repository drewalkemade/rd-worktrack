"""
1_Dashboard.py — Operational dashboard.

Shows a quick-glance view of current payroll and billing state:
  - Open pay periods and their status
  - Verification completion per week
  - Reconciliation status per period
  - Missing receipt count
  - Recent audit activity
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from payroll_app.database import db

st.set_page_config(page_title="Dashboard — R&D Controls", layout="wide")

st.title("Dashboard")
st.caption("Live operational view — payroll, billing, expenses, receipts.")

# ---------------------------------------------------------------------------
# Load all summary data in a single connection
# ---------------------------------------------------------------------------

conn = db.get_connection()
try:
    open_periods = db.fetch_all(
        conn,
        """
        SELECT
            pp.id,
            pp.period_start,
            pp.period_end,
            pp.week1_ending,
            pp.week2_ending,
            pp.status,
            -- Weekly approval presence
            (SELECT COUNT(*) FROM weekly_approvals wa WHERE wa.pay_period_id = pp.id) AS approval_count,
            -- Verification completion (week 1)
            (SELECT COUNT(*) FROM weekly_approvals wa
              JOIN weekly_employee_verification v ON v.weekly_approval_id = wa.id
             WHERE wa.pay_period_id = pp.id AND wa.week_number = 1 AND v.status = 'verified') AS w1_verified,
            (SELECT COUNT(*) FROM weekly_approvals wa
              JOIN weekly_employee_verification v ON v.weekly_approval_id = wa.id
             WHERE wa.pay_period_id = pp.id AND wa.week_number = 1) AS w1_total,
            (SELECT COUNT(*) FROM weekly_approvals wa
              JOIN weekly_employee_verification v ON v.weekly_approval_id = wa.id
             WHERE wa.pay_period_id = pp.id AND wa.week_number = 1 AND v.status = 'needs_review') AS w1_needs_review,
            -- Verification completion (week 2)
            (SELECT COUNT(*) FROM weekly_approvals wa
              JOIN weekly_employee_verification v ON v.weekly_approval_id = wa.id
             WHERE wa.pay_period_id = pp.id AND wa.week_number = 2 AND v.status = 'verified') AS w2_verified,
            (SELECT COUNT(*) FROM weekly_approvals wa
              JOIN weekly_employee_verification v ON v.weekly_approval_id = wa.id
             WHERE wa.pay_period_id = pp.id AND wa.week_number = 2) AS w2_total,
            (SELECT COUNT(*) FROM weekly_approvals wa
              JOIN weekly_employee_verification v ON v.weekly_approval_id = wa.id
             WHERE wa.pay_period_id = pp.id AND wa.week_number = 2 AND v.status = 'needs_review') AS w2_needs_review,
            -- Reconciliation
            (SELECT COUNT(*) FROM reconciliation r WHERE r.pay_period_id = pp.id) AS recon_count,
            (SELECT COUNT(*) FROM reconciliation r WHERE r.pay_period_id = pp.id AND r.status = 'approved') AS recon_approved,
            (SELECT COUNT(*) FROM reconciliation r WHERE r.pay_period_id = pp.id AND r.status = 'variance') AS recon_variance
        FROM pay_periods pp
        ORDER BY pp.period_start DESC
        LIMIT 10
        """,
    )

    missing_receipts = db.fetch_all(
        conn,
        """
        SELECT
            e.display_name,
            COUNT(*) AS missing_count,
            SUM(ei.amount) AS total_amount,
            ei.currency
        FROM expense_items ei
        JOIN employees e ON e.id = ei.employee_id
        WHERE ei.requires_receipt = 1 AND ei.receipt_status = 'missing'
        GROUP BY ei.employee_id, ei.currency
        ORDER BY e.display_name
        """,
    )

    recent_audit = db.fetch_all(
        conn,
        """
        SELECT action, entity_type, entity_id, new_value, timestamp
        FROM audit_log
        ORDER BY timestamp DESC
        LIMIT 20
        """,
    )

finally:
    conn.close()

# ---------------------------------------------------------------------------
# Pay periods status table
# ---------------------------------------------------------------------------

st.subheader("Pay Periods")

if open_periods:
    for pp in open_periods:
        with st.container(border=True):
            hcol1, hcol2 = st.columns([3, 1])
            with hcol1:
                st.markdown(f"**{pp['period_start']} — {pp['period_end']}**")
            with hcol2:
                if pp["status"] == "open":
                    st.info("Open")
                elif pp["status"] == "exported":
                    st.success("Exported")
                else:
                    st.caption(pp["status"])

            cols = st.columns(5)

            # Week 1 approval
            with cols[0]:
                if pp["approval_count"] >= 1:
                    st.caption("Week 1 approval")
                    st.success(f"Imported  (ending {pp['week1_ending']})")
                else:
                    st.caption("Week 1 approval")
                    st.warning("Not imported")

            # Week 1 verification
            with cols[1]:
                w1t = pp["w1_total"] or 0
                w1v = pp["w1_verified"] or 0
                w1r = pp["w1_needs_review"] or 0
                st.caption("Week 1 verification")
                if w1t == 0:
                    st.info("No rows yet")
                elif w1v == w1t:
                    st.success(f"All verified ({w1t})")
                elif w1r > 0:
                    st.warning(f"{w1v}/{w1t} verified — {w1r} needs review")
                else:
                    st.info(f"{w1v}/{w1t} verified")

            # Week 2 approval
            with cols[2]:
                if pp["approval_count"] >= 2:
                    st.caption("Week 2 approval")
                    st.success(f"Imported  (ending {pp['week2_ending']})")
                else:
                    st.caption("Week 2 approval")
                    st.warning("Not imported")

            # Week 2 verification
            with cols[3]:
                w2t = pp["w2_total"] or 0
                w2v = pp["w2_verified"] or 0
                w2r = pp["w2_needs_review"] or 0
                st.caption("Week 2 verification")
                if w2t == 0:
                    st.info("No rows yet")
                elif w2v == w2t:
                    st.success(f"All verified ({w2t})")
                elif w2r > 0:
                    st.warning(f"{w2v}/{w2t} verified — {w2r} needs review")
                else:
                    st.info(f"{w2v}/{w2t} verified")

            # Reconciliation
            with cols[4]:
                rc = pp["recon_count"] or 0
                ra = pp["recon_approved"] or 0
                rv = pp["recon_variance"] or 0
                st.caption("Reconciliation")
                if rc == 0:
                    st.info("Not run")
                elif rv > 0:
                    st.warning(f"{rv} variance(s)  ({ra}/{rc} approved)")
                elif ra == rc:
                    st.success(f"All approved ({rc})")
                else:
                    st.info(f"{ra}/{rc} approved")

else:
    st.info("No pay periods found. Use the **Import** page to ingest a payroll PDF.")

# ---------------------------------------------------------------------------
# Receipt backlog
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Missing Receipts")

if missing_receipts:
    rows = [
        {
            "Employee":       r["display_name"],
            "Missing Count":  r["missing_count"],
            "Total Amount":   f"{r['total_amount']:.2f}" if r["total_amount"] else "—",
            "Currency":       r["currency"],
        }
        for r in missing_receipts
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.success("No missing receipts.")

# ---------------------------------------------------------------------------
# Recent audit log
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Recent Activity")

if recent_audit:
    with st.expander("Audit log — last 20 entries", expanded=False):
        rows = [
            {
                "Timestamp":   r["timestamp"],
                "Action":      r["action"],
                "Entity":      r["entity_type"],
                "ID":          r["entity_id"],
                "Detail":      (r["new_value"] or "")[:120],
            }
            for r in recent_audit
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.info("No audit activity recorded yet.")
