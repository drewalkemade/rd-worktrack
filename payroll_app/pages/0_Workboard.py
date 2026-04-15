"""
0_Workboard.py — Visual payroll workflow canvas.

A single page that replaces all previous Streamlit pages.  The canvas shows the
complete two-week payroll workflow as coloured, status-aware nodes connected by
bezier curves.  Selecting a node from the picker below opens its detail panel where
the actual import/run/export controls live.

Layout
------
  Top:      Period selector
  Middle:   HTML/SVG canvas (visual overview, not interactive for navigation)
  Below:    Node selector (selectbox) → detail panel

Node selection uses st.session_state so file-upload state is never lost on rerun.
The canvas is regenerated each rerun to reflect current DB state (node status badges).
"""

import sys
import json
import tempfile
from pathlib import Path
from datetime import date, timedelta
from io import BytesIO

import streamlit as st
import streamlit.components.v1 as components

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from payroll_app.database import db
from payroll_app.pipeline import importer, reconciler, cheque_run_writer, weekly_verifier

st.set_page_config(
    page_title="R&D Controls — Workboard",
    layout="wide",
    page_icon="⚙️",
    initial_sidebar_state="collapsed",
)

# ─── CSS — tighten page chrome ─────────────────────────────────────────────────
st.markdown("""
<style>
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
.block-container { padding-top: 0.75rem; padding-bottom: 1rem; max-width: 100%; }
</style>
""", unsafe_allow_html=True)

# ─── Session state defaults ─────────────────────────────────────────────────────
if "selected_node" not in st.session_state:
    st.session_state.selected_node = "timesheets"


# ═══════════════════════════════════════════════════════════════════════════════
# Node layout definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Each node: (id, display_label, color, x, y, w, h, week_badge)
# Canvas is 1620 × 615 px.
_NODES = [
    # ── Shared ──────────────────────────────────────────────────────────────────
    ("timesheets",         "Timesheets",          "green",   18, 205, 138, 200, None),
    # ── Week 1 (top lane) ───────────────────────────────────────────────────────
    ("w1_payroll_pdf",     "Payroll PDF",         "blue",   175,  45, 128,  60, "Wk 1"),
    ("w1_travel_pdf",      "Travel PDF",          "blue",   175, 120, 128,  60, "Wk 1"),
    ("w1_approved_hours",  "Approved Hours",      "blue",   323,  45, 152, 145, "Wk 1"),
    ("w1_receipts",        "Receipts",            "red",    495,  20, 112,  72, "Wk 1"),
    ("w1_reconcile",       "Reconcile",           "orange", 492, 105, 155, 145, "Wk 1"),
    ("w1_invoice",         "Verified Invoice",    "green",  665,  45, 152, 145, "Wk 1"),
    ("w1_invoice_export",  "Invoice Export",      "green",  837,  38, 142,  68, "Wk 1"),
    # ── Week 2 (bottom lane) ────────────────────────────────────────────────────
    ("w2_payroll_pdf",     "Payroll PDF",         "blue",   175, 405, 128,  60, "Wk 2"),
    ("w2_travel_pdf",      "Travel PDF",          "blue",   175, 480, 128,  60, "Wk 2"),
    ("w2_approved_hours",  "Approved Hours",      "blue",   323, 405, 152, 145, "Wk 2"),
    ("w2_receipts",        "Receipts",            "red",    495, 378, 112,  72, "Wk 2"),
    ("w2_reconcile",       "Reconcile",           "orange", 492, 465, 155, 145, "Wk 2"),
    ("w2_invoice",         "Verified Invoice",    "green",  665, 405, 152, 145, "Wk 2"),
    ("w2_invoice_export",  "Invoice Export",      "green",  837, 398, 142,  68, "Wk 2"),
    # ── Merge and payroll exports ────────────────────────────────────────────────
    ("merge",              "Merge Reconciliation","teal",   997, 210, 162, 158, None),
    ("modified_timesheets","Modified Timesheets", "teal",  1180, 210, 152, 145, None),
    ("export_sage50",      "Sage50 CSV",          "green", 1354, 132, 152,  62, None),
    ("export_summary",     "Summary CSV",         "green", 1354, 212, 152,  62, None),
    ("export_drewedit",    "DrewEdit XLSX",       "green", 1354, 292, 152,  62, None),
]

# Build a lookup: node_id → (x, y, w, h)
_NODE_GEOM = {n[0]: (n[3], n[4], n[5], n[6]) for n in _NODES}


def _port_out(nid):
    """Right-edge centre of a node (output port)."""
    x, y, w, h = _NODE_GEOM[nid]
    return x + w, y + h // 2


def _port_in(nid):
    """Left-edge centre of a node (input port)."""
    x, y, _, h = _NODE_GEOM[nid]
    return x, y + h // 2


def _bezier(sx, sy, tx, ty) -> str:
    offset = max(55, int(abs(tx - sx) * 0.42))
    if tx >= sx:
        c1x, c1y = sx + offset, sy
        c2x, c2y = tx - offset, ty
    else:
        # Backward arc: curve up/around
        c1x, c1y = sx + offset, sy - 35
        c2x, c2y = tx - offset, ty - 35
    return f"M {sx},{sy} C {c1x},{c1y} {c2x},{c2y} {tx},{ty}"


_CONNECTIONS = [
    ("timesheets",        "w1_approved_hours"),
    ("timesheets",        "w2_approved_hours"),
    ("w1_payroll_pdf",    "w1_approved_hours"),
    ("w1_travel_pdf",     "w1_approved_hours"),
    ("w1_approved_hours", "w1_reconcile"),
    ("w1_receipts",       "w1_reconcile"),
    ("w1_reconcile",      "w1_invoice"),
    ("w1_invoice",        "w1_invoice_export"),
    ("w1_invoice_export", "merge"),
    ("w2_payroll_pdf",    "w2_approved_hours"),
    ("w2_travel_pdf",     "w2_approved_hours"),
    ("w2_approved_hours", "w2_reconcile"),
    ("w2_receipts",       "w2_reconcile"),
    ("w2_reconcile",      "w2_invoice"),
    ("w2_invoice",        "w2_invoice_export"),
    ("w2_invoice_export", "merge"),
    ("merge",             "modified_timesheets"),
    ("modified_timesheets", "export_sage50"),
    ("modified_timesheets", "export_summary"),
    ("modified_timesheets", "export_drewedit"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# DB — node state computation
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_node_states(conn, period_id, week1_ending, week2_ending) -> dict:
    """Return a dict mapping each node_id → 'idle' | 'complete' | 'partial'."""
    s = {n[0]: "idle" for n in _NODES}
    if not period_id:
        return s

    # Timesheets
    ts = db.fetch_one(conn,
        "SELECT COUNT(*) as n FROM timesheet_imports WHERE pay_period_id = ?",
        (period_id,))
    if ts and ts["n"] > 0:
        s["timesheets"] = "complete"

    for wk_num, wk_key in [(1, "w1"), (2, "w2")]:
        wa = db.fetch_one(conn,
            "SELECT id, payroll_pdf_file, travel_pdf_file FROM weekly_approvals "
            "WHERE pay_period_id = ? AND week_number = ?",
            (period_id, wk_num))
        if not wa:
            continue

        wa_id = wa["id"]

        if wa["payroll_pdf_file"]:
            s[f"{wk_key}_payroll_pdf"] = "complete"

        if wa["travel_pdf_file"]:
            s[f"{wk_key}_travel_pdf"] = "complete"

        # Customer hours imported → approved hours node
        ch = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM customer_hours WHERE weekly_approval_id = ?",
            (wa_id,))
        if ch and ch["n"] > 0:
            s[f"{wk_key}_approved_hours"] = "complete"

        # Expense items for employees in this period
        exp = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM expense_items WHERE pay_period_id = ?",
            (period_id,))
        if exp and exp["n"] > 0:
            s[f"{wk_key}_receipts"] = "partial"  # items exist; receipts may be missing

        # Verification status
        total_v = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM weekly_employee_verification "
            "WHERE weekly_approval_id = ?", (wa_id,))
        pending_v = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM weekly_employee_verification "
            "WHERE weekly_approval_id = ? AND status != 'verified'", (wa_id,))
        if total_v and total_v["n"] > 0:
            if pending_v and pending_v["n"] == 0:
                s[f"{wk_key}_reconcile"] = "complete"
            else:
                s[f"{wk_key}_reconcile"] = "partial"

    # Reconciliation rows → invoice and merge
    recon_count = db.fetch_one(conn,
        "SELECT COUNT(*) as n FROM reconciliation WHERE pay_period_id = ?",
        (period_id,))
    if recon_count and recon_count["n"] > 0:
        s["merge"] = "partial"
        s["modified_timesheets"] = "partial"

    approved_recon = db.fetch_one(conn,
        "SELECT COUNT(*) as n FROM reconciliation "
        "WHERE pay_period_id = ? AND status = 'approved'",
        (period_id,))
    if approved_recon and approved_recon["n"] > 0:
        total_recon = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM reconciliation WHERE pay_period_id = ?",
            (period_id,))
        if total_recon and approved_recon["n"] == total_recon["n"]:
            s["merge"] = "complete"
            s["modified_timesheets"] = "complete"
            s["w1_invoice"] = "complete"
            s["w2_invoice"] = "complete"
            s["w1_invoice_export"] = "complete"
            s["w2_invoice_export"] = "complete"
            s["export_sage50"] = "complete"
            s["export_summary"] = "complete"
            s["export_drewedit"] = "complete"

    return s


# ═══════════════════════════════════════════════════════════════════════════════
# Canvas HTML builder
# ═══════════════════════════════════════════════════════════════════════════════

_HEADER_COLORS = {
    "green":  "#276749",
    "blue":   "#2b5282",
    "orange": "#c05621",
    "teal":   "#285e61",
    "red":    "#9b2c2c",
}

_STATE_ICON = {
    "idle":     "",
    "partial":  " ◑",
    "complete": " ✓",
}


def _build_canvas_html(node_states: dict, selected: str,
                        week1_ending: str, week2_ending: str) -> str:
    """Generate the full HTML/SVG canvas string."""

    # ── SVG connection paths ──────────────────────────────────────────────────
    svg_paths = []
    for src, tgt in _CONNECTIONS:
        sx, sy = _port_out(src)
        tx, ty = _port_in(tgt)
        d = _bezier(sx, sy, tx, ty)
        # colour the curve by target node state
        state = node_states.get(tgt, "idle")
        stroke = "#48bb78" if state == "complete" else "#9ca3af" if state == "idle" else "#ed8936"
        svg_paths.append(
            f'<path d="{d}" stroke="{stroke}" stroke-width="2" '
            f'fill="none" marker-end="url(#arr)"/>'
        )
    svg_content = "\n      ".join(svg_paths)

    # ── Node HTML blocks ──────────────────────────────────────────────────────
    node_blocks = []
    for (nid, title, color, x, y, w, h, badge) in _NODES:
        state = node_states.get(nid, "idle")
        is_selected = nid == selected
        hdr_color = _HEADER_COLORS[color]
        state_icon = _STATE_ICON[state]
        opacity = "1.0" if state != "idle" else "0.72"
        border = "3px solid #805ad5" if is_selected else "2px solid transparent"
        shadow = ("0 0 0 4px rgba(128,90,213,0.35), 0 3px 10px rgba(0,0,0,0.25)"
                  if is_selected else "0 2px 8px rgba(0,0,0,0.18)")

        # Body text: dates for file-input nodes, summary for others
        if nid == "w1_payroll_pdf":
            body = f'<div class="nb">Week ending<br><b>{week1_ending or "—"}</b></div>'
        elif nid == "w2_payroll_pdf":
            body = f'<div class="nb">Week ending<br><b>{week2_ending or "—"}</b></div>'
        elif nid == "w1_travel_pdf":
            body = f'<div class="nb">Sun–Sat range<br>ending {week1_ending or "—"}</div>'
        elif nid == "w2_travel_pdf":
            body = f'<div class="nb">Sun–Sat range<br>ending {week2_ending or "—"}</div>'
        elif nid == "timesheets":
            body = '<div class="nb">Biweekly XLSX<br>covers both weeks<br>auto-split by date</div>'
        elif nid == "merge":
            body = '<div class="nb">Combines Week 1 + Week 2<br>into biweekly payroll</div>'
        else:
            body = f'<div class="nb">{"✓ Done" if state == "complete" else "◑ In progress" if state == "partial" else "Waiting"}</div>'

        badge_html = (f'<span class="wbadge">{badge}</span>' if badge else "")

        # Highlight ring for selected state
        ring_style = ""
        if is_selected:
            ring_style = "box-shadow: 0 0 0 3px #805ad5 inset;"

        node_blocks.append(f"""
    <div style="position:absolute; left:{x}px; top:{y}px; width:{w}px;
                border-radius:8px; background:#1e2535; border:{border};
                box-shadow:{shadow}; opacity:{opacity}; cursor:pointer;
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                transition:opacity 0.15s;">
      <div style="background:{hdr_color}; border-radius:6px 6px 0 0;
                  padding:5px 7px; display:flex; justify-content:space-between;
                  align-items:center;">
        <span style="color:white; font-size:10.5px; font-weight:700;
                     letter-spacing:0.2px; white-space:nowrap; overflow:hidden;
                     text-overflow:ellipsis; max-width:{w-55}px;">{title}</span>
        <span style="display:flex; gap:4px; align-items:center; flex-shrink:0;">
          {badge_html}
          <span style="color:rgba(255,255,255,0.9); font-size:11px; font-weight:bold;">{state_icon}</span>
        </span>
      </div>
      <div style="padding:5px 7px; min-height:28px;">{body}</div>
    </div>""")

    nodes_html = "\n".join(node_blocks)

    # ── Lane labels ────────────────────────────────────────────────────────────
    lane_labels = """
    <div style="position:absolute; left:175px; top:10px; font-size:9.5px;
                color:#9ca3af; font-weight:600; letter-spacing:0.8px;
                text-transform:uppercase; font-family:-apple-system,sans-serif;">
      WEEK 1 — BILLING LANE
    </div>
    <div style="position:absolute; left:175px; top:372px; font-size:9.5px;
                color:#9ca3af; font-weight:600; letter-spacing:0.8px;
                text-transform:uppercase; font-family:-apple-system,sans-serif;">
      WEEK 2 — BILLING LANE (+7 days)
    </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: transparent; overflow: hidden; }}
.nb {{ color: #9ca3af; font-size: 9.5px; line-height: 1.4; padding-top: 1px; }}
.nb b {{ color: #e2e8f0; }}
.wbadge {{
  font-size: 7.5px; background: rgba(0,0,0,0.3); color: rgba(255,255,255,0.8);
  padding: 1px 4px; border-radius: 3px; font-weight: 600; white-space: nowrap;
}}
</style>
</head>
<body>
<div style="position:relative; width:1520px; height:610px;
            background:#0d1117;
            background-image: radial-gradient(#ffffff14 1px, transparent 1px);
            background-size: 22px 22px;
            border-radius:10px; overflow:hidden;">

  <!-- Connection curves -->
  <svg style="position:absolute; top:0; left:0; pointer-events:none; overflow:visible;"
       width="1520" height="610">
    <defs>
      <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4"
              markerWidth="5" markerHeight="5" orient="auto">
        <path d="M 0 0 L 8 4 L 0 8 z" fill="#9ca3af"/>
      </marker>
    </defs>
    {svg_content}
  </svg>

  <!-- Lane labels -->
  {lane_labels}

  <!-- Nodes -->
  {nodes_html}

</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# Detail panels — one per node
# ═══════════════════════════════════════════════════════════════════════════════

def _save_upload_to_tmp(file_obj, suffix: str) -> str:
    """Write an uploaded file to a temp path and return the path string."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(file_obj.read())
    tmp.close()
    return tmp.name


def _panel_timesheets(conn, period_id):
    st.subheader("📋 Timesheets")
    st.caption(
        "Upload one or more biweekly employee timesheet XLSX files. "
        "The importer auto-splits daily hours into Week 1 and Week 2 by date."
    )

    uploaded = st.file_uploader(
        "Employee timesheet files (.xlsx)",
        type=["xlsx"],
        accept_multiple_files=True,
        key="upload_timesheets",
    )

    if uploaded:
        if st.button("▶  Import Timesheets", type="primary"):
            results = []
            for f in uploaded:
                tmp_path = _save_upload_to_tmp(f, ".xlsx")
                try:
                    result = importer.import_timesheet(
                        conn, tmp_path,
                        original_name=f.name,
                        normalized_name=f.name,
                    )
                    results.append((f.name, result))
                except Exception as exc:
                    st.error(f"{f.name}: {exc}")
                finally:
                    Path(tmp_path).unlink(missing_ok=True)

            conn.commit()
            for fname, r in results:
                if r.success:
                    st.success(f"✓ {fname} — {r.employee_count} employee(s) imported")
                else:
                    st.error(f"✗ {fname} — " + "; ".join(r.errors))
                if r.warnings:
                    for w in r.warnings:
                        st.warning(w)
                if r.extraction_log:
                    with st.expander("Extraction log"):
                        st.code("\n".join(r.extraction_log))
            st.rerun()

    # Show existing import summary
    if period_id:
        rows = db.fetch_all(conn, """
            SELECT e.display_name, ti.imported_at,
                   th.reg_hours, th.ot1_hours, th.ot2_hours,
                   th.drive_hours, th.sick_hours, th.vacation_hours,
                   th.holiday_hours, th.nonbillable_hours
            FROM timesheet_imports ti
            JOIN employees e ON e.id = ti.employee_id
            LEFT JOIN timesheet_hours th
                   ON th.pay_period_id = ti.pay_period_id
                  AND th.employee_id = ti.employee_id
            WHERE ti.pay_period_id = ?
            ORDER BY e.display_name
        """, (period_id,))
        if rows:
            st.markdown("**Imported timesheet data:**")
            import pandas as pd
            df = pd.DataFrame([dict(r) for r in rows])
            df.rename(columns={
                "display_name": "Employee",
                "reg_hours": "REG", "ot1_hours": "OT1", "ot2_hours": "OT2",
                "drive_hours": "Drive", "sick_hours": "Sick",
                "vacation_hours": "Vacation", "holiday_hours": "Holiday",
                "nonbillable_hours": "Non-Bill", "imported_at": "Imported",
            }, inplace=True)
            st.dataframe(df, use_container_width=True, hide_index=True)


def _panel_payroll_pdf(conn, period_id, week_num: int, week_ending: str | None):
    label = f"Week {week_num}"
    wk_key = f"w{week_num}"
    st.subheader(f"📄 {label} — Payroll PDF")

    # Date picker for week-ending if not known
    if week_ending:
        we_date = date.fromisoformat(week_ending)
        st.info(f"Week ending: **{week_ending}** (Sunday)")
    else:
        st.caption("No period set yet — pick the week-ending Sunday:")
        we_date = st.date_input(
            "Week-ending Sunday",
            value=date.today(),
            key=f"we_date_{wk_key}",
        )
        week_ending = str(we_date)

    uploaded = st.file_uploader(
        f"Payroll approval PDF for {label}",
        type=["pdf"],
        key=f"upload_{wk_key}_payroll",
    )

    if uploaded:
        if st.button(f"▶  Import {label} Payroll PDF", type="primary"):
            tmp_path = _save_upload_to_tmp(uploaded, ".pdf")
            try:
                result = importer.import_payroll_pdf(
                    conn, tmp_path,
                    week_ending_date=we_date,
                    original_name=uploaded.name,
                    normalized_name=uploaded.name,
                )
                conn.commit()
                if result.success:
                    st.success(f"✓ {result.employee_count} employee(s) imported")
                else:
                    for e in result.errors:
                        st.error(e)
                if result.warnings:
                    for w in result.warnings:
                        st.warning(w)
                if result.extraction_log:
                    with st.expander("Extraction log"):
                        st.code("\n".join(result.extraction_log))
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    # Show imported data
    if period_id:
        wa = db.fetch_one(conn,
            "SELECT id, payroll_pdf_file FROM weekly_approvals "
            "WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if wa:
            rows = db.fetch_all(conn, """
                SELECT e.display_name, ch.reg_hours, ch.ot_hours, ch.dbl_hours
                FROM customer_hours ch
                JOIN employees e ON e.id = ch.employee_id
                WHERE ch.weekly_approval_id = ?
                ORDER BY e.display_name
            """, (wa["id"],))
            if rows:
                import pandas as pd
                df = pd.DataFrame([dict(r) for r in rows])
                df.rename(columns={
                    "display_name": "Employee",
                    "reg_hours": "REG", "ot_hours": "OT1", "dbl_hours": "OT2",
                }, inplace=True)
                st.caption(f"Source: {wa['payroll_pdf_file']}")
                st.dataframe(df, use_container_width=True, hide_index=True)


def _panel_travel_pdf(conn, period_id, week_num: int, week_ending: str | None):
    label = f"Week {week_num}"
    wk_key = f"w{week_num}"
    st.subheader(f"✈ {label} — Travel PDF")
    st.caption(
        "The travel PDF is Sun–Sat. Its Sunday hours are applied back to the "
        "prior Mon–Sun week automatically. Some weeks have no travel PDF — that is normal."
    )

    uploaded = st.file_uploader(
        f"Travel PDF for {label}",
        type=["pdf"],
        key=f"upload_{wk_key}_travel",
    )

    if uploaded:
        if st.button(f"▶  Import {label} Travel PDF", type="primary"):
            tmp_path = _save_upload_to_tmp(uploaded, ".pdf")
            try:
                result = importer.import_travel_pdf(
                    conn, tmp_path,
                    original_name=uploaded.name,
                    normalized_name=uploaded.name,
                )
                conn.commit()
                if result.success:
                    st.success(f"✓ {result.employee_count} employee(s) imported")
                else:
                    for e in result.errors:
                        st.error(e)
                if result.warnings:
                    for w in result.warnings:
                        st.warning(w)
                if result.extraction_log:
                    with st.expander("Extraction log"):
                        st.code("\n".join(result.extraction_log))
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    # No travel PDF option
    with st.expander("No travel PDF this week?"):
        st.caption(
            "If Centerline did not send a travel PDF, you can pull drive hours "
            "from the employee timesheet instead. Requires a note."
        )
        if period_id:
            wa = db.fetch_one(conn,
                "SELECT id FROM weekly_approvals "
                "WHERE pay_period_id = ? AND week_number = ?",
                (period_id, week_num))
            if wa:
                assume_note = st.text_input(
                    "Note (required)",
                    placeholder="e.g. No travel PDF received for this week",
                    key=f"assume_note_{wk_key}",
                )
                if st.button("Use timesheet drive hours", key=f"assume_{wk_key}"):
                    if not assume_note.strip():
                        st.error("A note is required.")
                    else:
                        try:
                            # Apply for every employee who has a timesheet import for this period
                            emp_rows = db.fetch_all(conn,
                                "SELECT DISTINCT employee_id FROM timesheet_imports "
                                "WHERE pay_period_id = ("
                                "  SELECT pay_period_id FROM weekly_approvals WHERE id = ?"
                                ")",
                                (wa["id"],))
                            applied = 0
                            for emp in emp_rows:
                                try:
                                    weekly_verifier.assume_travel_from_timesheet(
                                        conn, wa["id"], emp["employee_id"],
                                        note=assume_note.strip(),
                                    )
                                    applied += 1
                                except ValueError:
                                    pass  # employee has no drive hours — skip silently
                            conn.commit()
                            st.success(f"Travel set from timesheet drive hours for {applied} employee(s).")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

    # Show imported travel data
    if period_id:
        wa = db.fetch_one(conn,
            "SELECT id, travel_pdf_file FROM weekly_approvals "
            "WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if wa and wa["travel_pdf_file"]:
            rows = db.fetch_all(conn, """
                SELECT e.display_name,
                       th.sun_hours, th.mon_hours, th.tue_hours, th.wed_hours,
                       th.thu_hours, th.fri_hours, th.sat_hours,
                       th.current_week_total, th.current_sun_status
                FROM travel_hours th
                JOIN employees e ON e.id = th.employee_id
                WHERE th.weekly_approval_id = ?
                ORDER BY e.display_name
            """, (wa["id"],))
            if rows:
                import pandas as pd
                df = pd.DataFrame([dict(r) for r in rows])
                df.rename(columns={
                    "display_name": "Employee",
                    "sun_hours": "Sun", "mon_hours": "Mon", "tue_hours": "Tue",
                    "wed_hours": "Wed", "thu_hours": "Thu", "fri_hours": "Fri",
                    "sat_hours": "Sat", "current_week_total": "Wk Total",
                    "current_sun_status": "Sun Status",
                }, inplace=True)
                st.caption(f"Source: {wa['travel_pdf_file']}")
                st.dataframe(df, use_container_width=True, hide_index=True)


def _panel_approved_hours(conn, period_id, week_num: int):
    label = f"Week {week_num}"
    wk_key = f"w{week_num}"
    st.subheader(f"📊 {label} — Approved Hours")
    st.caption(
        "Side-by-side view of customer-approved hours vs employee timesheet hours. "
        "Mark each employee as verified once you've checked for discrepancies."
    )

    if not period_id:
        st.info("Import a payroll PDF first.")
        return

    wa = db.fetch_one(conn,
        "SELECT id, week_ending FROM weekly_approvals "
        "WHERE pay_period_id = ? AND week_number = ?",
        (period_id, week_num))
    if not wa:
        st.info("No payroll PDF imported for this week yet.")
        return

    wa_id = wa["id"]
    week_ending = wa["week_ending"]

    # Run verification button
    if st.button(f"▶  Run verification for {label}", key=f"run_verif_{wk_key}"):
        try:
            summary = weekly_verifier.run_weekly_verification(conn, wa_id)
            conn.commit()
            st.success(
                f"✓ Verified {summary.verified_count} / {summary.total_count} employees. "
                f"{summary.needs_review_count} need review."
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    rows = db.fetch_all(conn, """
        SELECT e.display_name,
               wev.approved_reg, wev.approved_ot, wev.approved_dbl, wev.approved_travel,
               wev.timesheet_week_reg, wev.timesheet_week_ot1, wev.timesheet_week_ot2,
               wev.timesheet_week_drive,
               wev.timesheet_week_sick, wev.timesheet_week_vacation,
               wev.timesheet_week_holiday, wev.timesheet_week_nonbillable,
               wev.status, wev.needs_expense_review, wev.simple_per_diem_count,
               wev.id as verif_id, wev.employee_id
        FROM weekly_employee_verification wev
        JOIN employees e ON e.id = wev.employee_id
        WHERE wev.weekly_approval_id = ?
        ORDER BY e.display_name
    """, (wa_id,))

    if not rows:
        st.info("Run verification to populate this table.")
        return

    # Verify All button
    col_va, _ = st.columns([2, 6])
    with col_va:
        if st.button("✓  Verify All", key=f"verify_all_{wk_key}"):
            for row in rows:
                weekly_verifier.set_verified(conn, wa_id, row["employee_id"])
            conn.commit()
            st.success("All employees marked verified.")
            st.rerun()

    for row in rows:
        status_icon = {"verified": "🟢", "needs_review": "🟡", "pending": "⚪"}.get(
            row["status"], "⚪"
        )
        with st.expander(f"{status_icon} {row['display_name']}  — {row['status']}", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Customer approved**")
                st.metric("REG", row["approved_reg"])
                st.metric("OT1", row["approved_ot"])
                st.metric("OT2", row["approved_dbl"])
                st.metric("Travel", row["approved_travel"])
            with c2:
                st.markdown("**Timesheet submitted**")
                st.metric("REG", row["timesheet_week_reg"])
                st.metric("OT1", row["timesheet_week_ot1"])
                st.metric("OT2", row["timesheet_week_ot2"])
                st.metric("Drive", row["timesheet_week_drive"])
            non_bill = [
                ("Sick", row["timesheet_week_sick"]),
                ("Vacation", row["timesheet_week_vacation"]),
                ("Holiday", row["timesheet_week_holiday"]),
                ("Non-Bill", row["timesheet_week_nonbillable"]),
            ]
            non_zero = [(l, v) for l, v in non_bill if v and v > 0]
            if non_zero:
                st.caption("Non-billable: " + "  |  ".join(f"{l}: {v}" for l, v in non_zero))
            if row["simple_per_diem_count"]:
                st.caption(f"Per diem days: {row['simple_per_diem_count']}")
            if row["needs_expense_review"]:
                st.warning("Expense review needed")

            if row["status"] != "verified":
                if st.button("✓ Mark Verified", key=f"verif_{row['verif_id']}"):
                    weekly_verifier.set_verified(conn, wa_id, row["employee_id"])
                    conn.commit()
                    st.rerun()


def _panel_reconcile(conn, period_id, week_num: int):
    label = f"Week {week_num}"
    wk_key = f"w{week_num}"
    st.subheader(f"🔄 {label} — Reconcile")
    st.caption(
        "All employees for this week must be marked verified before reconciliation. "
        "Reconciliation computes final hours and flags variances."
    )

    if not period_id:
        st.info("No period selected.")
        return

    wa = db.fetch_one(conn,
        "SELECT id FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
        (period_id, week_num))
    if not wa:
        st.info("No payroll PDF imported for this week yet.")
        return

    pending = db.fetch_one(conn,
        "SELECT COUNT(*) as n FROM weekly_employee_verification "
        "WHERE weekly_approval_id = ? AND status != 'verified'",
        (wa["id"],))
    if pending and pending["n"] > 0:
        st.warning(f"{pending['n']} employee(s) still pending verification. Verify all before reconciling.")
    else:
        st.success("All employees verified — ready to reconcile.")

    from payroll_app.pipeline import reconciler as rec_module
    if st.button(f"▶  Run Reconciliation", key=f"run_recon_{wk_key}", type="primary"):
        try:
            rec_module.run_reconciliation(conn, period_id)
            conn.commit()
            st.success("Reconciliation complete.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    # Show reconciliation rows
    rows = db.fetch_all(conn, """
        SELECT e.display_name,
               r.ts_reg, r.ts_ot, r.ts_dbl, r.ts_drive,
               r.cust_reg, r.cust_ot, r.cust_dbl, r.cust_drive,
               r.final_reg, r.final_ot, r.final_dbl, r.final_drive,
               r.status, r.notes, r.id as recon_id, r.employee_id
        FROM reconciliation r
        JOIN employees e ON e.id = r.employee_id
        WHERE r.pay_period_id = ?
        ORDER BY e.display_name
    """, (period_id,))

    if not rows:
        return

    from payroll_app.pipeline import reconciler as rec_module
    col_aa, _ = st.columns([2, 6])
    with col_aa:
        if st.button("✓  Approve All", key=f"approve_all_{wk_key}"):
            try:
                rec_module.approve_all(conn, period_id)
                conn.commit()
                st.success("All reconciliation rows approved.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    import pandas as pd
    df = pd.DataFrame([dict(r) for r in rows])[[
        "display_name", "ts_reg", "cust_reg", "final_reg",
        "ts_ot", "cust_ot", "final_ot",
        "ts_dbl", "cust_dbl", "final_dbl",
        "ts_drive", "cust_drive", "final_drive",
        "status"
    ]]
    df.columns = [
        "Employee", "TS REG", "Cust REG", "Final REG",
        "TS OT1", "Cust OT1", "Final OT1",
        "TS OT2", "Cust OT2", "Final OT2",
        "TS Drive", "Cust Drive", "Final Drive",
        "Status"
    ]
    st.dataframe(df, use_container_width=True, hide_index=True)


def _panel_invoice(conn, period_id, week_num: int):
    from payroll_app import config
    st.subheader(f"🧾 Week {week_num} — Verified Invoice")
    if not period_id:
        st.info("No period selected.")
        return

    wa = db.fetch_one(conn,
        "SELECT id, week_ending FROM weekly_approvals "
        "WHERE pay_period_id = ? AND week_number = ?",
        (period_id, week_num))
    if not wa:
        st.info("No payroll PDF for this week.")
        return

    rows = db.fetch_all(conn, """
        SELECT e.display_name,
               r.final_reg, r.final_ot, r.final_dbl, r.final_drive,
               r.status
        FROM reconciliation r
        JOIN employees e ON e.id = r.employee_id
        WHERE r.pay_period_id = ?
        ORDER BY e.display_name
    """, (period_id,))

    if not rows:
        st.info("Run reconciliation first.")
        return

    subtotal = 0.0
    for row in rows:
        reg   = (row["final_reg"]   or 0) * config.CENTERLINE_RATE_REG
        ot1   = (row["final_ot"]    or 0) * config.CENTERLINE_RATE_OT1
        ot2   = (row["final_dbl"]   or 0) * config.CENTERLINE_RATE_OT2
        drive = (row["final_drive"] or 0) * config.CENTERLINE_RATE_TRAVEL
        subtotal += reg + ot1 + ot2 + drive

    import pandas as pd
    df = pd.DataFrame([{
        "Employee":  row["display_name"],
        "REG hrs":   row["final_reg"],
        "REG $":     f"${(row['final_reg'] or 0) * config.CENTERLINE_RATE_REG:,.2f}",
        "OT1 hrs":   row["final_ot"],
        "OT1 $":     f"${(row['final_ot'] or 0) * config.CENTERLINE_RATE_OT1:,.2f}",
        "OT2 hrs":   row["final_dbl"],
        "OT2 $":     f"${(row['final_dbl'] or 0) * config.CENTERLINE_RATE_OT2:,.2f}",
        "Travel hrs":row["final_drive"],
        "Travel $":  f"${(row['final_drive'] or 0) * config.CENTERLINE_RATE_TRAVEL:,.2f}",
        "Status":    row["status"],
    } for row in rows])
    st.dataframe(df, use_container_width=True, hide_index=True)

    hst = subtotal * config.HST_RATE
    col1, col2, col3 = st.columns(3)
    col1.metric("Subtotal", f"${subtotal:,.2f}")
    col2.metric("HST (13%)", f"${hst:,.2f}")
    col3.metric("Total", f"${subtotal + hst:,.2f}")


def _panel_invoice_export(conn, period_id, week_num: int):
    from payroll_app import config
    st.subheader(f"📤 Week {week_num} — Invoice Export")

    if not period_id:
        st.info("No period selected.")
        return

    wa = db.fetch_one(conn,
        "SELECT id, week_ending FROM weekly_approvals "
        "WHERE pay_period_id = ? AND week_number = ?",
        (period_id, week_num))
    if not wa:
        st.info("No payroll PDF for this week.")
        return

    rows = db.fetch_all(conn, """
        SELECT e.display_name, r.final_reg, r.final_ot, r.final_dbl, r.final_drive, r.status
        FROM reconciliation r
        JOIN employees e ON e.id = r.employee_id
        WHERE r.pay_period_id = ?
        ORDER BY e.display_name
    """, (period_id,))

    if not rows:
        st.info("No reconciliation data yet.")
        return

    # Build CSV
    import io, csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Item No.", "Description", "Qty", "Unit Price", "Amount", "Tax"])
    for row in rows:
        emp = row["display_name"]
        entries = [
            (config.INVOICE_ITEM_REG,   f"Centerline - Regular - {emp}",   row["final_reg"],   config.CENTERLINE_RATE_REG),
            (config.INVOICE_ITEM_OT1,   f"Centerline - OT1 - {emp}",       row["final_ot"],    config.CENTERLINE_RATE_OT1),
            (config.INVOICE_ITEM_OT2,   f"Centerline - OT2 - {emp}",       row["final_dbl"],   config.CENTERLINE_RATE_OT2),
            (config.INVOICE_ITEM_TRAVEL,f"Centerline - Travel - {emp}",    row["final_drive"], config.CENTERLINE_RATE_TRAVEL),
        ]
        for item, desc, qty, rate in entries:
            amt = (qty or 0) * rate
            writer.writerow([item, desc, qty or 0, rate, f"{amt:.2f}", "H"])
        writer.writerow([])

    csv_bytes = buf.getvalue().encode("utf-8")
    week_label = wa["week_ending"].replace("-", "")
    st.download_button(
        label=f"⬇  Download Invoice CSV (Week {week_num})",
        data=csv_bytes,
        file_name=f"invoice_w{week_num}_{week_label}.csv",
        mime="text/csv",
    )


def _panel_merge(conn, period_id):
    st.subheader("🔗 Merge Reconciliation")
    st.caption(
        "Combines both weeks into the biweekly reconciliation. "
        "Both weeks must have approved reconciliation rows before running the merge."
    )

    if not period_id:
        st.info("No period selected.")
        return

    from payroll_app.pipeline import reconciler as rec_module
    if st.button("▶  Run Full Reconciliation", type="primary"):
        try:
            rec_module.run_reconciliation(conn, period_id)
            conn.commit()
            st.success("Reconciliation complete.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    rows = db.fetch_all(conn, """
        SELECT e.display_name,
               r.final_reg, r.final_ot, r.final_dbl, r.final_drive, r.status
        FROM reconciliation r
        JOIN employees e ON e.id = r.employee_id
        WHERE r.pay_period_id = ?
        ORDER BY e.display_name
    """, (period_id,))

    if rows:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in rows])
        df.columns = ["Employee", "Final REG", "Final OT1", "Final OT2", "Final Drive", "Status"]
        st.dataframe(df, use_container_width=True, hide_index=True)


def _panel_modified_timesheets(conn, period_id, week1_ending, week2_ending):
    st.subheader("📊 Modified Timesheets")
    st.caption("Final biweekly hours per employee after reconciliation and approval.")

    if not period_id:
        st.info("No period selected.")
        return

    rows = db.fetch_all(conn, """
        SELECT e.display_name,
               r.final_reg, r.final_ot, r.final_dbl, r.final_drive,
               r.ts_reg, r.ts_ot, r.ts_dbl, r.ts_drive,
               r.status
        FROM reconciliation r
        JOIN employees e ON e.id = r.employee_id
        WHERE r.pay_period_id = ?
        ORDER BY e.display_name
    """, (period_id,))

    if not rows:
        st.info("No reconciliation data yet. Run reconciliation first.")
        return

    import pandas as pd
    df = pd.DataFrame([dict(r) for r in rows])
    df.columns = [
        "Employee", "Final REG", "Final OT1", "Final OT2", "Final Drive",
        "TS REG", "TS OT1", "TS OT2", "TS Drive", "Status"
    ]
    st.dataframe(df, use_container_width=True, hide_index=True)


def _panel_export_sage50(conn, period_id, week1_ending, week2_ending):
    st.subheader("📥 Export — Sage50 Payroll CSV")
    st.caption(
        "Generates the Sage 50 payroll import CSV. Uses sage50_name alias where set. "
        "Encoding: UTF-16 LE with BOM (required by Sage 50)."
    )

    if not period_id:
        st.info("No period selected.")
        return

    period_end = week2_ending or week1_ending
    if not period_end:
        st.warning("Cannot determine period end date.")
        return

    period_date = period_end.replace("-", "")

    if st.button("▶  Generate Sage50 CSV", type="primary"):
        try:
            out_path = cheque_run_writer.export_sage50_csv(conn, period_id, period_end_date=period_date)
            st.success(f"✓ Written to: {out_path}")

            # Also offer in-browser download
            with open(out_path, "rb") as fh:
                csv_bytes = fh.read()
            st.download_button(
                label="⬇  Download Sage50 CSV",
                data=csv_bytes,
                file_name=Path(out_path).name,
                mime="text/plain",
            )
        except Exception as exc:
            st.error(str(exc))


def _panel_export_summary(conn, period_id, week1_ending, week2_ending):
    st.subheader("📥 Export — Timesheet Summary CSV")
    st.caption("Summary of final hours per employee for the full biweekly period.")

    if not period_id:
        st.info("No period selected.")
        return

    rows = db.fetch_all(conn, """
        SELECT e.display_name,
               r.final_reg, r.final_ot, r.final_dbl, r.final_drive,
               r.ts_reg, r.ts_ot, r.ts_dbl, r.ts_drive
        FROM reconciliation r
        JOIN employees e ON e.id = r.employee_id
        WHERE r.pay_period_id = ?
        ORDER BY e.display_name
    """, (period_id,))

    if not rows:
        st.info("No reconciliation data yet.")
        return

    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Employee", "Final_REG", "Final_OT1", "Final_OT2", "Final_Drive",
                "TS_REG", "TS_OT1", "TS_OT2", "TS_Drive"])
    for r in rows:
        w.writerow([
            r["display_name"],
            r["final_reg"], r["final_ot"], r["final_dbl"], r["final_drive"],
            r["ts_reg"], r["ts_ot"], r["ts_dbl"], r["ts_drive"],
        ])

    period_label = (week2_ending or week1_ending or "unknown").replace("-", "")
    st.download_button(
        label="⬇  Download Summary CSV",
        data=buf.getvalue().encode("utf-8"),
        file_name=f"timesheet_summary_{period_label}.csv",
        mime="text/csv",
    )


def _panel_export_drewedit(conn, period_id):
    st.subheader("📥 Export — DrewEdit XLSX")
    st.info(
        "This export writes final approved hours back into a copy of the employee "
        "timesheet files, saved as *_DrewEdit.xlsx. "
        "This feature is planned for a future phase."
    )


def _panel_receipts(conn, period_id, week_num: int):
    from payroll_app.pipeline import expense_exporter
    st.subheader(f"🧾 Week {week_num} — Receipts & Expenses")
    st.caption("Expense items loaded from employee timesheets. Receipts must be attached before billing.")

    if not period_id:
        st.info("No period selected.")
        return

    rows = db.fetch_all(conn, """
        SELECT e.display_name, ei.work_date, ei.category, ei.description,
               ei.amount, ei.currency, ei.receipt_status, ei.reimbursement_status,
               ei.billing_status, ei.id as item_id
        FROM expense_items ei
        JOIN employees e ON e.id = ei.employee_id
        WHERE ei.pay_period_id = ?
        ORDER BY e.display_name, ei.work_date
    """, (period_id,))

    if not rows:
        st.info("No expense items for this period. Expense data comes from employee timesheet XLSX files.")
        return

    import pandas as pd
    df = pd.DataFrame([dict(r) for r in rows])
    df.rename(columns={
        "display_name": "Employee", "work_date": "Date", "category": "Category",
        "description": "Description", "amount": "Amount", "currency": "Currency",
        "receipt_status": "Receipt", "billing_status": "Billing",
    }, inplace=True)
    st.dataframe(df[[
        "Employee", "Date", "Category", "Description", "Amount", "Currency", "Receipt", "Billing"
    ]], use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Node selector options
# ═══════════════════════════════════════════════════════════════════════════════

_NODE_OPTIONS = {
    "📋 Timesheets":               "timesheets",
    "── Week 1 ──────────────────": None,
    "📄 Week 1 — Payroll PDF":    "w1_payroll_pdf",
    "✈  Week 1 — Travel PDF":     "w1_travel_pdf",
    "📊 Week 1 — Approved Hours": "w1_approved_hours",
    "🧾 Week 1 — Receipts":       "w1_receipts",
    "🔄 Week 1 — Reconcile":      "w1_reconcile",
    "💰 Week 1 — Invoice":        "w1_invoice",
    "📤 Week 1 — Invoice Export": "w1_invoice_export",
    "── Week 2 ──────────────────": None,
    "📄 Week 2 — Payroll PDF":    "w2_payroll_pdf",
    "✈  Week 2 — Travel PDF":     "w2_travel_pdf",
    "📊 Week 2 — Approved Hours": "w2_approved_hours",
    "🧾 Week 2 — Receipts":       "w2_receipts",
    "🔄 Week 2 — Reconcile":      "w2_reconcile",
    "💰 Week 2 — Invoice":        "w2_invoice",
    "📤 Week 2 — Invoice Export": "w2_invoice_export",
    "── Payroll Run ─────────────": None,
    "🔗 Merge Reconciliation":    "merge",
    "📊 Modified Timesheets":     "modified_timesheets",
    "📥 Export — Sage50 CSV":     "export_sage50",
    "📥 Export — Summary CSV":    "export_summary",
    "📥 Export — DrewEdit XLSX":  "export_drewedit",
}

_SELECTABLE = {k: v for k, v in _NODE_OPTIONS.items() if v is not None}
_ID_TO_LABEL = {v: k for k, v in _SELECTABLE.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# Main layout
# ═══════════════════════════════════════════════════════════════════════════════

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_period = st.columns([4, 4])
with col_title:
    st.markdown("### ⚙️ R&D Controls — Payroll Workboard")

conn = db.get_connection()
try:
    periods = db.fetch_all(conn, """
        SELECT id, week1_ending, week2_ending, status
        FROM pay_periods
        ORDER BY week1_ending DESC
        LIMIT 30
    """)
finally:
    conn.close()

if not periods:
    st.info("No pay periods found. Upload a Payroll PDF using the **Timesheets** or **Week 1 — Payroll PDF** node below.")
    period_id    = None
    week1_ending = None
    week2_ending = None
else:
    period_labels = {}
    for p in periods:
        w2_label = p["week2_ending"] or "pending"
        label = f"Wk ending {p['week1_ending']}  +  {w2_label}"
        period_labels[label] = p["id"]

    with col_period:
        if "period_label" not in st.session_state or \
                st.session_state.period_label not in period_labels:
            st.session_state.period_label = list(period_labels.keys())[0]

        chosen_label = st.selectbox(
            "Pay period",
            options=list(period_labels.keys()),
            key="period_label",
            label_visibility="collapsed",
        )

    period_id = period_labels[chosen_label]
    conn = db.get_connection()
    try:
        p_row = db.fetch_one(conn, "SELECT * FROM pay_periods WHERE id = ?", (period_id,))
    finally:
        conn.close()

    week1_ending = p_row["week1_ending"] if p_row else None
    week2_ending = p_row["week2_ending"] if p_row else None

# ── Canvas ────────────────────────────────────────────────────────────────────
conn = db.get_connection()
try:
    node_states = _compute_node_states(conn, period_id, week1_ending, week2_ending)
finally:
    conn.close()

canvas_html = _build_canvas_html(
    node_states,
    st.session_state.selected_node,
    week1_ending or "—",
    week2_ending or "—",
)
components.html(canvas_html, height=630, scrolling=False)

# ── Node selector ─────────────────────────────────────────────────────────────
st.divider()

sel_col, _ = st.columns([3, 5])
with sel_col:
    current_label = _ID_TO_LABEL.get(st.session_state.selected_node, list(_SELECTABLE.keys())[0])
    chosen_node_label = st.selectbox(
        "Open node:",
        options=list(_SELECTABLE.keys()),
        index=list(_SELECTABLE.keys()).index(current_label),
        key="node_picker",
    )
    st.session_state.selected_node = _SELECTABLE[chosen_node_label]

selected = st.session_state.selected_node

# ── Detail panel ──────────────────────────────────────────────────────────────
st.markdown("---")
conn = db.get_connection()
try:
    if selected == "timesheets":
        _panel_timesheets(conn, period_id)

    elif selected == "w1_payroll_pdf":
        _panel_payroll_pdf(conn, period_id, week_num=1, week_ending=week1_ending)

    elif selected == "w1_travel_pdf":
        _panel_travel_pdf(conn, period_id, week_num=1, week_ending=week1_ending)

    elif selected == "w1_approved_hours":
        _panel_approved_hours(conn, period_id, week_num=1)

    elif selected == "w1_receipts":
        _panel_receipts(conn, period_id, week_num=1)

    elif selected == "w1_reconcile":
        _panel_reconcile(conn, period_id, week_num=1)

    elif selected == "w1_invoice":
        _panel_invoice(conn, period_id, week_num=1)

    elif selected == "w1_invoice_export":
        _panel_invoice_export(conn, period_id, week_num=1)

    elif selected == "w2_payroll_pdf":
        _panel_payroll_pdf(conn, period_id, week_num=2, week_ending=week2_ending)

    elif selected == "w2_travel_pdf":
        _panel_travel_pdf(conn, period_id, week_num=2, week_ending=week2_ending)

    elif selected == "w2_approved_hours":
        _panel_approved_hours(conn, period_id, week_num=2)

    elif selected == "w2_receipts":
        _panel_receipts(conn, period_id, week_num=2)

    elif selected == "w2_reconcile":
        _panel_reconcile(conn, period_id, week_num=2)

    elif selected == "w2_invoice":
        _panel_invoice(conn, period_id, week_num=2)

    elif selected == "w2_invoice_export":
        _panel_invoice_export(conn, period_id, week_num=2)

    elif selected == "merge":
        _panel_merge(conn, period_id)

    elif selected == "modified_timesheets":
        _panel_modified_timesheets(conn, period_id, week1_ending, week2_ending)

    elif selected == "export_sage50":
        _panel_export_sage50(conn, period_id, week1_ending, week2_ending)

    elif selected == "export_summary":
        _panel_export_summary(conn, period_id, week1_ending, week2_ending)

    elif selected == "export_drewedit":
        _panel_export_drewedit(conn, period_id)

finally:
    conn.close()
