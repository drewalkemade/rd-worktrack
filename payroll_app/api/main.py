"""
payroll_app/api/main.py — FastAPI backend for the React workboard.

Thin wrapper around the existing pipeline modules.  All business logic
stays in pipeline/.  This file only handles HTTP plumbing.

Run with:
    source .venv/bin/activate
    uvicorn payroll_app.api.main:app --reload --port 8000
"""

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is on the path when run via uvicorn
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from payroll_app.database import db, employee_manager
from payroll_app.pipeline import importer, weekly_verifier, reconciler, cheque_run_writer

app = FastAPI(title="R&D Controls Payroll API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── DB dependency helper ────────────────────────────────────────────────────

def _get_conn():
    return db.get_connection()


# ═══════════════════════════════════════════════════════════════════════════════
# Employees
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/employees")
def list_employees():
    """Return all employees with their aliases and current assignment."""
    conn = _get_conn()
    try:
        employees = db.fetch_all(conn, """
            SELECT e.id, e.display_name, e.pdf_name, e.pdf_id,
                   e.centerline_id, e.active,
                   ea.assignment_type, ea.customer_code
            FROM employees e
            LEFT JOIN employee_assignments ea ON ea.employee_id = e.id
              AND ea.effective_start = (
                SELECT MAX(ea2.effective_start)
                FROM employee_assignments ea2
                WHERE ea2.employee_id = e.id
              )
            WHERE e.active = 1
            ORDER BY e.display_name
        """)

        result = []
        for emp in employees:
            aliases = db.fetch_all(conn,
                "SELECT alias_type, alias_value FROM employee_aliases WHERE employee_id = ? ORDER BY alias_type",
                (emp["id"],))
            result.append({
                "id":              emp["id"],
                "display_name":    emp["display_name"],
                "pdf_name":        emp["pdf_name"],
                "pdf_id":          emp["pdf_id"],
                "centerline_id":   emp["centerline_id"],
                "active":          emp["active"],
                "assignment_type": emp["assignment_type"],
                "customer_code":   emp["customer_code"],
                "aliases":         [dict(a) for a in aliases],
            })
        return result
    finally:
        conn.close()


@app.put("/api/employees/{employee_id}")
def update_employee(employee_id: int, body: dict):
    """Update basic employee fields (display_name, active, etc.)."""
    allowed = {"display_name", "active", "pdf_name", "pdf_id", "centerline_id"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    conn = _get_conn()
    try:
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE employees SET {sets} WHERE id = ?",
            (*updates.values(), employee_id),
        )
        db.log_audit(conn, action="update_employee", entity_type="employees",
                     entity_id=employee_id, new_value=str(updates))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/employees/{employee_id}/aliases")
def add_alias(employee_id: int, body: dict):
    alias_type  = body.get("alias_type", "").strip()
    alias_value = body.get("alias_value", "").strip()
    if not alias_type or not alias_value:
        raise HTTPException(400, "alias_type and alias_value required")
    conn = _get_conn()
    try:
        employee_manager.add_alias(conn, employee_id, alias_type, alias_value)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/employees/{employee_id}/aliases")
def delete_alias(employee_id: int, body: dict):
    alias_type  = body.get("alias_type", "").strip()
    alias_value = body.get("alias_value", "").strip()
    conn = _get_conn()
    try:
        conn.execute(
            "DELETE FROM employee_aliases WHERE employee_id = ? AND alias_type = ? AND alias_value = ?",
            (employee_id, alias_type, alias_value),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Pay periods
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/periods")
def list_periods():
    conn = _get_conn()
    try:
        rows = db.fetch_all(conn, """
            SELECT id, period_start, period_end, week1_ending, week2_ending, status
            FROM pay_periods
            ORDER BY week1_ending DESC
            LIMIT 30
        """)
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/periods/{period_id}")
def get_period(period_id: int):
    conn = _get_conn()
    try:
        row = db.fetch_one(conn, "SELECT * FROM pay_periods WHERE id = ?", (period_id,))
        if not row:
            raise HTTPException(404, "Period not found")
        return dict(row)
    finally:
        conn.close()


@app.get("/api/periods/{period_id}/node-states")
def get_node_states(period_id: int):
    """Return completion state for every canvas node for this period."""
    conn = _get_conn()
    try:
        period = db.fetch_one(conn, "SELECT * FROM pay_periods WHERE id = ?", (period_id,))
        if not period:
            raise HTTPException(404, "Period not found")

        states = _compute_node_states(conn, period_id,
                                      period["week1_ending"], period["week2_ending"])
        return states
    finally:
        conn.close()


def _compute_node_states(conn, period_id, week1_ending, week2_ending) -> dict:
    s = {}
    node_ids = [
        "employees", "timesheets",
        "w1_payroll_pdf", "w1_travel_pdf", "w1_approved_hours",
        "w1_receipts", "w1_reconcile", "w1_invoice", "w1_invoice_export",
        "w2_payroll_pdf", "w2_travel_pdf", "w2_approved_hours",
        "w2_receipts", "w2_reconcile", "w2_invoice", "w2_invoice_export",
        "merge", "modified_timesheets",
        "export_sage50", "export_summary", "export_drewedit",
    ]
    for nid in node_ids:
        s[nid] = "idle"

    # Employees always complete if any exist
    emp_count = db.fetch_one(conn, "SELECT COUNT(*) as n FROM employees WHERE active = 1")
    if emp_count and emp_count["n"] > 0:
        s["employees"] = "complete"

    # Timesheets
    ts = db.fetch_one(conn,
        "SELECT COUNT(*) as n FROM timesheet_imports WHERE pay_period_id = ?", (period_id,))
    if ts and ts["n"] > 0:
        s["timesheets"] = "complete"

    for wk_num, wk_key in [(1, "w1"), (2, "w2")]:
        wa = db.fetch_one(conn,
            "SELECT id, payroll_pdf_file, travel_pdf_file FROM weekly_approvals "
            "WHERE pay_period_id = ? AND week_number = ?", (period_id, wk_num))
        if not wa:
            continue
        wa_id = wa["id"]
        if wa["payroll_pdf_file"]:
            s[f"{wk_key}_payroll_pdf"] = "complete"
        if wa["travel_pdf_file"]:
            s[f"{wk_key}_travel_pdf"] = "complete"
        ch = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM customer_hours WHERE weekly_approval_id = ?", (wa_id,))
        if ch and ch["n"] > 0:
            s[f"{wk_key}_approved_hours"] = "complete"
        exp = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM expense_items WHERE pay_period_id = ?", (period_id,))
        if exp and exp["n"] > 0:
            s[f"{wk_key}_receipts"] = "partial"
        total_v = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM weekly_employee_verification WHERE weekly_approval_id = ?",
            (wa_id,))
        pending_v = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM weekly_employee_verification "
            "WHERE weekly_approval_id = ? AND status != 'verified'", (wa_id,))
        if total_v and total_v["n"] > 0:
            s[f"{wk_key}_reconcile"] = "complete" if (pending_v and pending_v["n"] == 0) else "partial"

    recon = db.fetch_one(conn,
        "SELECT COUNT(*) as n, SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) as approved "
        "FROM reconciliation WHERE pay_period_id = ?", (period_id,))
    if recon and recon["n"] and recon["n"] > 0:
        s["merge"] = "partial"
        s["modified_timesheets"] = "partial"
        if recon["approved"] == recon["n"]:
            s["merge"] = "complete"
            s["modified_timesheets"] = "complete"
            for k in ["w1_invoice", "w2_invoice", "w1_invoice_export", "w2_invoice_export",
                      "export_sage50", "export_summary", "export_drewedit"]:
                s[k] = "complete"

    return s


# ═══════════════════════════════════════════════════════════════════════════════
# Timesheet import + Week 1 hours
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/import/timesheets")
async def import_timesheets(files: list[UploadFile] = File(...)):
    """Upload one or more biweekly timesheet XLSX files and import them."""
    conn = _get_conn()
    results = []
    period_id = None

    try:
        for f in files:
            content = await f.read()
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                result = importer.import_timesheet(
                    conn, tmp_path,
                    original_name=f.filename,
                    normalized_name=f.filename,
                )
                if result.pay_period_id:
                    period_id = result.pay_period_id
                results.append({
                    "filename":       f.filename,
                    "success":        result.success,
                    "employee_count": result.employee_count,
                    "skipped":        result.skipped_count,
                    "warnings":       result.warnings,
                    "errors":         result.errors,
                    "extraction_log": result.extraction_log,
                })
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        conn.commit()
        return {"period_id": period_id, "files": results}
    finally:
        conn.close()


@app.get("/api/periods/{period_id}/week1-hours")
def get_week1_hours(period_id: int):
    """Return per-employee Week 1 hours (Mon–Sun of week1_ending).

    Output columns match timesheet_export CSV:
      Ending, Employee, REG, OT1, OT2, Drive, Sick, Vacation, Holiday, NonBill
    """
    conn = _get_conn()
    try:
        period = db.fetch_one(conn,
            "SELECT week1_ending FROM pay_periods WHERE id = ?", (period_id,))
        if not period or not period["week1_ending"]:
            raise HTTPException(404, "Period or week1_ending not found")

        week1_end   = date.fromisoformat(period["week1_ending"])
        week1_start = week1_end - timedelta(days=6)   # Monday

        rows = db.fetch_all(conn, """
            SELECT e.display_name,
                   SUM(tdh.reg_hours)         as reg,
                   SUM(tdh.ot1_hours)         as ot1,
                   SUM(tdh.ot2_hours)         as ot2,
                   SUM(tdh.drive_hours)       as drive,
                   SUM(tdh.sick_hours)        as sick,
                   SUM(tdh.vacation_hours)    as vacation,
                   SUM(tdh.holiday_hours)     as holiday,
                   SUM(tdh.nonbillable_hours) as nonbill
            FROM timesheet_daily_hours tdh
            JOIN timesheet_imports ti ON ti.id = tdh.timesheet_import_id
            JOIN employees e ON e.id = tdh.employee_id
            WHERE ti.pay_period_id = ?
              AND tdh.work_date >= ?
              AND tdh.work_date <= ?
            GROUP BY tdh.employee_id
            ORDER BY e.display_name
        """, (period_id, str(week1_start), str(week1_end)))

        return {
            "week1_ending": str(week1_end),
            "week1_start":  str(week1_start),
            "rows": [{
                "employee":  r["display_name"],
                "reg":       round(r["reg"]      or 0, 2),
                "ot1":       round(r["ot1"]      or 0, 2),
                "ot2":       round(r["ot2"]      or 0, 2),
                "drive":     round(r["drive"]    or 0, 2),
                "sick":      round(r["sick"]     or 0, 2),
                "vacation":  round(r["vacation"] or 0, 2),
                "holiday":   round(r["holiday"]  or 0, 2),
                "nonbill":   round(r["nonbill"]  or 0, 2),
            } for r in rows],
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
def health():
    return {"status": "ok"}
