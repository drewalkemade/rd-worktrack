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


@app.get("/api/periods/{period_id}/week2-hours")
def get_week2_hours(period_id: int):
    """Return per-employee Week 2 hours (Mon–Sun of week2_ending).

    Week 2 start = week1_ending + 1 day.
    Week 2 end   = week1_ending + 7 days  (== week2_ending when present).
    """
    conn = _get_conn()
    try:
        period = db.fetch_one(conn,
            "SELECT week1_ending, week2_ending FROM pay_periods WHERE id = ?", (period_id,))
        if not period or not period["week1_ending"]:
            raise HTTPException(404, "Period not found")

        week1_end = date.fromisoformat(period["week1_ending"])
        week2_start = week1_end + timedelta(days=1)   # Monday of week 2
        week2_end   = week1_end + timedelta(days=7)   # Sunday of week 2

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
        """, (period_id, str(week2_start), str(week2_end)))

        return {
            "week2_ending": period["week2_ending"] or str(week2_end),
            "week2_start":  str(week2_start),
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
# Approved hours — payroll PDF + travel PDF import + weekly verification
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/periods/{period_id}/weeks/{week_num}")
def get_week(period_id: int, week_num: int):
    """Return the weekly_approval record for this period/week (import status)."""
    conn = _get_conn()
    try:
        row = db.fetch_one(conn,
            "SELECT * FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not row:
            return {"exists": False}
        return {"exists": True, **dict(row)}
    finally:
        conn.close()


@app.post("/api/import/payroll-pdf")
async def import_payroll_pdf_endpoint(
    file: UploadFile = File(...),
    period_id: int   = Form(...),
    week_num: int    = Form(...),
):
    """Upload a payroll approval PDF and import it for the given period/week."""
    conn = _get_conn()
    try:
        period = db.fetch_one(conn,
            "SELECT week1_ending, week2_ending FROM pay_periods WHERE id = ?", (period_id,))
        if not period:
            raise HTTPException(404, "Period not found")

        week_ending_str = period["week1_ending"] if week_num == 1 else period["week2_ending"]
        if not week_ending_str:
            raise HTTPException(400, f"week{week_num}_ending not set on this period")

        content = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = importer.import_payroll_pdf(
                conn, tmp_path,
                week_ending_date=week_ending_str,
                original_name=file.filename,
                normalized_name=file.filename,
            )
            conn.commit()
            return {
                "success":            result.success,
                "weekly_approval_id": result.weekly_approval_id,
                "employee_count":     result.employee_count,
                "skipped":            result.skipped_count,
                "warnings":           result.warnings,
                "errors":             result.errors,
                "extraction_log":     result.extraction_log,
            }
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    finally:
        conn.close()


@app.post("/api/import/travel-pdf")
async def import_travel_pdf_endpoint(
    file: UploadFile = File(...),
    period_id: int   = Form(...),
    week_num: int    = Form(...),
):
    """Upload a travel PDF and import it (date range is parsed from the PDF itself)."""
    conn = _get_conn()
    try:
        content = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = importer.import_travel_pdf(
                conn, tmp_path,
                original_name=file.filename,
                normalized_name=file.filename,
            )
            conn.commit()
            return {
                "success":            result.success,
                "weekly_approval_id": result.weekly_approval_id,
                "employee_count":     result.employee_count,
                "skipped":            result.skipped_count,
                "warnings":           result.warnings,
                "errors":             result.errors,
                "extraction_log":     result.extraction_log,
            }
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    finally:
        conn.close()


@app.post("/api/periods/{period_id}/weeks/{week_num}/verify")
def run_verification(period_id: int, week_num: int):
    """Run weekly_verifier for this period/week. Creates/updates verification rows."""
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            raise HTTPException(404, "No weekly_approval found — import a payroll PDF first")

        summary = weekly_verifier.run_weekly_verification(conn, wa["id"])
        conn.commit()
        return {
            "weekly_approval_id":    summary.weekly_approval_id,
            "total_employees":       summary.total_employees,
            "needs_review_count":    summary.needs_review_count,
            "pending_count":         summary.pending_count,
            "verified_count":        summary.verified_count,
            "provisional_sunday":    summary.provisonal_sunday_count,
            "warnings":              summary.warnings,
        }
    finally:
        conn.close()


@app.get("/api/periods/{period_id}/weeks/{week_num}/verification")
def get_verification(period_id: int, week_num: int):
    """Return all verification rows for this period/week."""
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            return {"rows": []}

        rows = weekly_verifier.get_verification_status(conn, wa["id"])
        return {
            "weekly_approval_id": wa["id"],
            "rows": [{
                "employee_id":             r.employee_id,
                "display_name":            r.display_name,
                "approved_reg":            r.approved_reg,
                "approved_ot":             r.approved_ot,
                "approved_dbl":            r.approved_dbl,
                "approved_travel":         r.approved_travel,
                "timesheet_reg":           r.timesheet_week_reg,
                "timesheet_ot1":           r.timesheet_week_ot1,
                "timesheet_ot2":           r.timesheet_week_ot2,
                "timesheet_drive":         r.timesheet_week_drive,
                "timesheet_sick":          r.timesheet_week_sick,
                "timesheet_vacation":      r.timesheet_week_vacation,
                "timesheet_holiday":       r.timesheet_week_holiday,
                "timesheet_nonbill":       r.timesheet_week_nonbillable,
                "reg_variance":            r.reg_variance,
                "ot_variance":             r.ot_variance,
                "dbl_variance":            r.dbl_variance,
                "needs_expense_review":    r.needs_expense_review,
                "per_diem_count":          r.simple_per_diem_count,
                "extra_expense_note":      r.extra_expense_note,
                "travel_sun_status":       r.travel_sun_status,
                "travel_sun_hours":        r.travel_sun_hours,
                "status":                  r.status,
                "verified_at":             r.verified_at,
            } for r in rows],
        }
    finally:
        conn.close()


@app.post("/api/periods/{period_id}/weeks/{week_num}/set-verified/{employee_id}")
def set_employee_verified(period_id: int, week_num: int, employee_id: int, body: dict = {}):
    """Mark a specific employee/week as verified."""
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            raise HTTPException(404, "No weekly_approval found")

        weekly_verifier.set_verified(conn, wa["id"], employee_id, note=body.get("note"))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/periods/{period_id}/expenses")
def get_period_expenses(period_id: int):
    """Return all expense_items for the period, tagged with week 1 or 2.

    Items with no work_date are included under week = null.
    Ordered by employee name, then work_date.
    """
    conn = _get_conn()
    try:
        period = db.fetch_one(conn,
            "SELECT week1_ending FROM pay_periods WHERE id = ?", (period_id,))
        if not period or not period["week1_ending"]:
            raise HTTPException(404, "Period not found")

        week1_end   = date.fromisoformat(period["week1_ending"])
        week1_start = week1_end - timedelta(days=6)
        week2_start = week1_end + timedelta(days=1)
        week2_end   = week1_end + timedelta(days=7)

        rows = db.fetch_all(conn, """
            SELECT e.display_name  AS employee,
                   ei.work_date,
                   ei.category,
                   ei.description,
                   ei.currency,
                   ei.amount,
                   ei.quantity,
                   ei.requires_receipt,
                   ei.receipt_status,
                   ei.reimbursement_status,
                   ei.billing_status
            FROM expense_items ei
            JOIN employees e ON e.id = ei.employee_id
            WHERE ei.pay_period_id = ?
            ORDER BY e.display_name, ei.work_date
        """, (period_id,))

        items = []
        for r in rows:
            wd = r["work_date"]
            if wd:
                d = date.fromisoformat(wd)
                if week1_start <= d <= week1_end:
                    week = 1
                elif week2_start <= d <= week2_end:
                    week = 2
                else:
                    week = None
            else:
                week = None

            items.append({
                "week":                 week,
                "employee":             r["employee"],
                "work_date":            wd,
                "category":             r["category"],
                "description":          r["description"],
                "currency":             r["currency"],
                "amount":               float(r["amount"] or 0),
                "quantity":             float(r["quantity"] or 1),
                "requires_receipt":     bool(r["requires_receipt"]),
                "receipt_status":       r["receipt_status"],
                "reimbursement_status": r["reimbursement_status"],
                "billing_status":       r["billing_status"],
            })

        return {"week1_ending": str(week1_end), "items": items}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
def health():
    return {"status": "ok"}
