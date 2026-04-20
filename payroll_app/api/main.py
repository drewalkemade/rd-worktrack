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

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is on the path when run via uvicorn
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from payroll_app.database import db, employee_manager
from payroll_app.pipeline import importer, weekly_verifier, reconciler, cheque_run_writer
from payroll_app import config as cfg

app = FastAPI(title="R&D Controls Payroll API")


@app.on_event("startup")
def _startup():
    conn = db.get_connection()
    try:
        db.initialize_database(conn)
    finally:
        conn.close()


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
        "w1_receipts", "w1_compare", "w1_correct", "w1_verify",
        "w1_invoice", "w1_invoice_export",
        "w2_payroll_pdf", "w2_travel_pdf", "w2_approved_hours",
        "w2_receipts", "w2_compare", "w2_correct", "w2_verify",
        "w2_invoice", "w2_invoice_export",
        "merge", "modified_timesheets",
        "export_sage50", "export_summary", "export_drewedit",
    ]
    def _s(state, summary=None):
        """Return a node state dict. summary defaults to a readable label."""
        default_summary = {"idle": "No data yet", "partial": "In progress", "complete": "Complete"}
        return {"state": state, "summary": summary or default_summary.get(state, state)}

    for nid in node_ids:
        s[nid] = _s("idle")

    # Employees always complete if any exist
    emp_count = db.fetch_one(conn, "SELECT COUNT(*) as n FROM employees WHERE active = 1")
    if emp_count and emp_count["n"] > 0:
        s["employees"] = _s("complete")

    # Timesheets
    ts = db.fetch_one(conn,
        "SELECT COUNT(*) as n FROM timesheet_imports WHERE pay_period_id = ?", (period_id,))
    if ts and ts["n"] > 0:
        s["timesheets"] = _s("complete")

    for wk_num, wk_key in [(1, "w1"), (2, "w2")]:
        wa = db.fetch_one(conn,
            "SELECT id, payroll_pdf_file, travel_pdf_file FROM weekly_approvals "
            "WHERE pay_period_id = ? AND week_number = ?", (period_id, wk_num))
        if not wa:
            continue
        wa_id = wa["id"]

        # PDF nodes — show filename as summary when loaded
        if wa["payroll_pdf_file"]:
            s[f"{wk_key}_payroll_pdf"] = _s("complete", wa["payroll_pdf_file"])
        if wa["travel_pdf_file"]:
            s[f"{wk_key}_travel_pdf"] = _s("complete", wa["travel_pdf_file"])

        # Approved Hours — complete once customer_hours rows exist
        ch = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM customer_hours WHERE weekly_approval_id = ?", (wa_id,))
        if ch and ch["n"] > 0:
            s[f"{wk_key}_approved_hours"] = _s("complete")

        # Receipts — partial when any receipts required; complete when all received
        exp_all = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM expense_items "
            "WHERE pay_period_id = ? AND requires_receipt = 1", (period_id,))
        exp_missing = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM expense_items "
            "WHERE pay_period_id = ? AND requires_receipt = 1 "
            "AND receipt_status NOT IN ('received', 'deferred')",
            (period_id,))
        if exp_all and exp_all["n"] > 0:
            receipt_state = "complete" if (exp_missing and exp_missing["n"] == 0) else "partial"
            s[f"{wk_key}_receipts"] = _s(receipt_state)

        # Compare — partial once verification rows exist; complete if all verified
        total_v = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM weekly_employee_verification "
            "WHERE weekly_approval_id = ?", (wa_id,))
        pending_v = db.fetch_one(conn,
            "SELECT COUNT(*) as n FROM weekly_employee_verification "
            "WHERE weekly_approval_id = ? AND status != 'verified'", (wa_id,))
        if total_v and total_v["n"] > 0:
            # Compare is "complete" once verification has been run (rows exist)
            s[f"{wk_key}_compare"] = _s("complete")
            # Verify is "complete" if all rows are verified, "partial" otherwise
            verify_state = "complete" if (pending_v and pending_v["n"] == 0) else "partial"
            s[f"{wk_key}_verify"] = _s(verify_state)
            # Resolve — idle if no corrections logged; partial if in progress;
            # complete if no needs_review employees remain
            needs_rev = db.fetch_one(conn,
                "SELECT COUNT(*) as n FROM weekly_employee_verification "
                "WHERE weekly_approval_id = ? AND status = 'needs_review'", (wa_id,))
            corr_ct = db.fetch_one(conn,
                "SELECT COUNT(*) as n FROM correction_log "
                "WHERE weekly_approval_id = ?", (wa_id,))
            if corr_ct and corr_ct["n"] > 0:
                if needs_rev and needs_rev["n"] == 0:
                    s[f"{wk_key}_correct"] = _s("complete")
                else:
                    s[f"{wk_key}_correct"] = _s("partial")
            else:
                s[f"{wk_key}_correct"] = _s("idle")

    recon = db.fetch_one(conn,
        "SELECT COUNT(*) as n, SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) as approved "
        "FROM reconciliation WHERE pay_period_id = ?", (period_id,))
    if recon and recon["n"] and recon["n"] > 0:
        s["merge"] = _s("partial")
        s["modified_timesheets"] = _s("partial")
        if recon["approved"] == recon["n"]:
            s["merge"] = _s("complete")
            s["modified_timesheets"] = _s("complete")
            for k in ["w1_invoice", "w2_invoice", "w1_invoice_export", "w2_invoice_export",
                      "export_sage50", "export_summary", "export_drewedit"]:
                s[k] = _s("complete")

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
# Invoice preview — per-week billable hours + amounts ready for Sage 50 entry
# ═══════════════════════════════════════════════════════════════════════════════

# Current billing rates (from Invoice 2719, week ending 2026-03-22).
# These should become configurable via a billing_rates table in a future phase.
_BILLING_RATES = {
    "regular":  72.00,
    "ot1":      93.60,
    "ot2":     122.40,
    "travel":   72.00,
    "per_diem": 70.00,
}
_ITEM_CODES = {
    "regular":  "005-1-2026-001",
    "ot1":      "005-1-2026-002",
    "ot2":      "005-1-2026-003",
    "travel":   "005-1-2026-100",
    "per_diem": "005-0-2025-101",
    "expense":  "005-0-2025-102",
}
_HST_RATE = 0.13


@app.get("/api/periods/{period_id}/weeks/{week_num}/invoice-preview")
def get_invoice_preview(period_id: int, week_num: int):
    """Return per-employee invoice line items for a single business week.

    Only billable employees (assignment_type = 'billable') are included.
    Internal employees (Henry, Matina, etc.) are excluded.
    All 6 standard line types appear per employee even when qty = 0 (Sage 50 requires them).
    Non-per-diem expenses with receipts received or deferred get individual lines.
    """
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id, week_ending FROM weekly_approvals "
            "WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            return {"employees": [], "subtotal": 0, "hst_amount": 0, "total": 0,
                    "week_ending": None, "all_verified": False}

        wa_id      = wa["id"]
        week_end   = date.fromisoformat(str(wa["week_ending"]))
        week_start = week_end - timedelta(days=6)

        # Verification rows — only billable employees (check current assignment)
        ver_rows = db.fetch_all(conn, """
            SELECT v.employee_id, e.display_name,
                   v.approved_reg, v.approved_ot, v.approved_dbl, v.approved_travel,
                   v.simple_per_diem_count, v.status
            FROM weekly_employee_verification v
            JOIN employees e ON e.id = v.employee_id
            WHERE v.weekly_approval_id = ?
              AND EXISTS (
                SELECT 1 FROM employee_assignments ea
                WHERE ea.employee_id = v.employee_id
                  AND ea.assignment_type = 'billable'
                  AND ea.effective_start <= ?
                  AND (ea.effective_end IS NULL OR ea.effective_end >= ?)
              )
            ORDER BY e.display_name
        """, (wa_id, str(week_end), str(week_start)))

        all_verified = len(ver_rows) > 0 and all(r["status"] == "verified" for r in ver_rows)

        # Non-per-diem expenses per employee for this week (receipt received or deferred)
        exp_rows = db.fetch_all(conn, """
            SELECT ei.employee_id, ei.description, ei.amount, ei.quantity,
                   ei.category, ei.receipt_status
            FROM expense_items ei
            WHERE ei.pay_period_id = ?
              AND ei.work_date BETWEEN ? AND ?
              AND ei.category NOT IN ('per_diem_travel', 'per_diem_full')
              AND ei.receipt_status IN ('received', 'deferred')
            ORDER BY ei.employee_id, ei.id
        """, (period_id, str(week_start), str(week_end)))

        exp_by_emp: dict = {}
        for ex in exp_rows:
            exp_by_emp.setdefault(ex["employee_id"], []).append(ex)

        result_employees = []
        grand_subtotal = 0.0

        for r in ver_rows:
            emp_id = r["employee_id"]
            reg    = float(r["approved_reg"]    or 0)
            ot1    = float(r["approved_ot"]     or 0)
            ot2    = float(r["approved_dbl"]    or 0)
            trav   = float(r["approved_travel"] or 0)
            perd   = float(r["simple_per_diem_count"] or 0)

            def _line(key, desc, qty, rate):
                amt = round(qty * rate, 2) if qty > 0 else 0.0
                return {
                    "item_no":    _ITEM_CODES[key],
                    "description": desc,
                    "qty":        qty,
                    "unit_price": rate,
                    "amount":     amt,
                    "is_zero":    qty == 0,
                }

            lines = [
                _line("regular",  "Centerline - Standard - Regular",    reg,  _BILLING_RATES["regular"]),
                _line("ot1",      "Centerline - Standard - Overtime 1",  ot1,  _BILLING_RATES["ot1"]),
                _line("ot2",      "Centerline - Standard - Overtime 2",  ot2,  _BILLING_RATES["ot2"]),
                _line("travel",   "Centerline - Standard - Travel",      trav, _BILLING_RATES["travel"]),
                _line("per_diem", "Centerline Per Diem",                 perd, _BILLING_RATES["per_diem"]),
            ]

            # Expense lines — one per receipt; fall back to placeholder line if none
            emp_expenses = exp_by_emp.get(emp_id, [])
            if emp_expenses:
                for ex in emp_expenses:
                    desc = "Centerline Expenses"
                    if ex["description"]:
                        desc += f" - {ex['description']}"
                    qty    = float(ex["quantity"] or 1)
                    price  = float(ex["amount"])
                    amount = round(qty * price, 2)
                    lines.append({
                        "item_no":     _ITEM_CODES["expense"],
                        "description": desc,
                        "qty":         qty,
                        "unit_price":  price,
                        "amount":      amount,
                        "is_zero":     False,
                    })
            else:
                # Placeholder expense line (required by Sage 50 format even when 0)
                lines.append({
                    "item_no":     _ITEM_CODES["expense"],
                    "description": "Centerline Expenses",
                    "qty":         0,
                    "unit_price":  1.00,
                    "amount":      0.0,
                    "is_zero":     True,
                })

            emp_subtotal = sum(ln["amount"] for ln in lines)
            grand_subtotal += emp_subtotal

            result_employees.append({
                "employee_id":  emp_id,
                "display_name": r["display_name"],
                "status":       r["status"],
                "lines":        lines,
                "subtotal":     round(emp_subtotal, 2),
            })

        hst_amount = round(grand_subtotal * _HST_RATE, 2)
        return {
            "week_ending":   str(week_end),
            "all_verified":  all_verified,
            "hst_rate":      _HST_RATE,
            "subtotal":      round(grand_subtotal, 2),
            "hst_amount":    hst_amount,
            "total":         round(grand_subtotal + hst_amount, 2),
            "employees":     result_employees,
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Approved Hours — structured data view (no verification logic)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/periods/{period_id}/weeks/{week_num}/approved-hours")
def get_approved_hours(period_id: int, week_num: int):
    """Return customer_hours + customer_daily_hours + travel_hours for a given week.

    Returns three datasets:
      rows        — per-employee summary (reg/ot/dbl from payroll PDF, travel total)
      rows[].daily — per-day with pdf_total, travel_day, labor_day (pdf - travel)
      travel_rows  — raw per-day travel PDF data for each employee (Mon–Sat + Sun prior)

    Used by the Approved Hours panel to show:
      1. Adjusted approved hours (labor = PDF total − travel)
      2. Raw payroll PDF extract
      3. Raw travel PDF extract
    """
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id, week_ending, payroll_pdf_file, travel_pdf_file "
            "FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            return {"rows": [], "travel_rows": [], "week_ending": None,
                    "week_start": None, "payroll_pdf": None, "travel_pdf": None}

        wa_id      = wa["id"]
        week_end   = date.fromisoformat(str(wa["week_ending"]))
        week_start = week_end - timedelta(days=6)

        # Weekly approved totals per employee (from payroll PDF)
        hours = db.fetch_all(conn, """
            SELECT e.id as employee_id, e.display_name,
                   ch.reg_hours, ch.ot_hours, ch.dbl_hours
            FROM customer_hours ch
            JOIN employees e ON e.id = ch.employee_id
            WHERE ch.weekly_approval_id = ?
            ORDER BY e.display_name
        """, (wa_id,))

        # Weekly travel totals per employee (from travel PDF)
        travel = db.fetch_all(conn, """
            SELECT e.display_name,
                   th.sun_hours, th.mon_hours, th.tue_hours, th.wed_hours,
                   th.thu_hours, th.fri_hours, th.sat_hours,
                   th.current_week_total, th.current_sun_status,
                   th.current_sun_hours_assumed
            FROM travel_hours th
            JOIN employees e ON e.id = th.employee_id
            WHERE th.weekly_approval_id = ?
            ORDER BY e.display_name
        """, (wa_id,))

        # Daily approved hours per employee (from payroll PDF clock-in/out rows)
        daily = db.fetch_all(conn, """
            SELECT e.display_name,
                   cdh.work_date, cdh.day_name,
                   cdh.clock_in, cdh.clock_out,
                   cdh.total_hours, cdh.is_dbl_day
            FROM customer_daily_hours cdh
            JOIN employees e ON e.id = cdh.employee_id
            WHERE cdh.weekly_approval_id = ?
            ORDER BY e.display_name, cdh.work_date
        """, (wa_id,))

        # Build per-employee per-day travel lookup: {name: {date_str: travel_hrs}}
        _day_col_offsets = [
            ("mon_hours", 0), ("tue_hours", 1), ("wed_hours", 2),
            ("thu_hours", 3), ("fri_hours", 4), ("sat_hours", 5),
        ]
        travel_day_map: dict = {}   # {display_name: {date_str: float}}
        travel_rows_out = []

        for t in travel:
            name = t["display_name"]
            emp_travel: dict = {}
            for col, offset in _day_col_offsets:
                emp_travel[str(week_start + timedelta(days=offset))] = float(t[col] or 0)
            sun_status = t["current_sun_status"] or "pending_next_pdf"
            if sun_status in ("confirmed", "assumed_from_timesheet"):
                emp_travel[str(week_end)] = float(t["current_sun_hours_assumed"] or 0)
            else:
                emp_travel[str(week_end)] = 0.0
            travel_day_map[name] = emp_travel

            # Raw travel PDF table row (for visual reference section)
            travel_rows_out.append({
                "employee":         name,
                "sun_prior":        float(t["sun_hours"] or 0),
                "mon":              float(t["mon_hours"] or 0),
                "tue":              float(t["tue_hours"] or 0),
                "wed":              float(t["wed_hours"] or 0),
                "thu":              float(t["thu_hours"] or 0),
                "fri":              float(t["fri_hours"] or 0),
                "sat":              float(t["sat_hours"] or 0),
                "current_sun":      float(t["current_sun_hours_assumed"] or 0),
                "current_sun_status": sun_status,
                "week_total":       float(t["current_week_total"] or 0),
            })

        # Build employee map keyed by display_name
        emp_map: dict = {}
        for h in hours:
            name = h["display_name"]
            emp_map[name] = {
                "employee":    name,
                "employee_id": h["employee_id"],
                "reg":         float(h["reg_hours"] or 0),
                "ot":          float(h["ot_hours"]  or 0),
                "dbl":         float(h["dbl_hours"] or 0),
                "travel":      0.0,
                "sun_status":  None,
                "daily":       [],
            }

        travel_summary = {t["display_name"]: t for t in travel}
        for name, t in travel_summary.items():
            if name not in emp_map:
                emp_map[name] = {
                    "employee": name, "employee_id": None,
                    "reg": 0, "ot": 0, "dbl": 0, "travel": 0.0,
                    "sun_status": None, "daily": [],
                }
            emp_map[name]["travel"]     = float(t["current_week_total"] or 0)
            emp_map[name]["sun_status"] = t["current_sun_status"]

        for d in daily:
            name    = d["display_name"]
            pdf_tot = float(d["total_hours"] or 0)
            trav_d  = travel_day_map.get(name, {}).get(str(d["work_date"]), 0.0)
            labor_d = max(0.0, pdf_tot - trav_d)
            if name not in emp_map:
                emp_map[name] = {
                    "employee": name, "employee_id": None,
                    "reg": 0, "ot": 0, "dbl": 0, "travel": 0.0,
                    "sun_status": None, "daily": [],
                }
            emp_map[name]["daily"].append({
                "date":       str(d["work_date"]),
                "day_name":   d["day_name"],
                "clock_in":   d["clock_in"],
                "clock_out":  d["clock_out"],
                "pdf_total":  pdf_tot,
                "travel_day": trav_d,
                "labor_day":  labor_d,
                "is_dbl_day": bool(d["is_dbl_day"]),
            })

        return {
            "week_ending":  str(wa["week_ending"]),
            "week_start":   str(week_start),
            "payroll_pdf":  wa["payroll_pdf_file"],
            "travel_pdf":   wa["travel_pdf_file"],
            "rows":         list(emp_map.values()),
            "travel_rows":  travel_rows_out,
        }
    finally:
        conn.close()


@app.get("/api/periods/{period_id}/weeks/{week_num}/day-comparison")
def get_day_comparison(period_id: int, week_num: int):
    """Return per-employee, per-day comparison of approved hours vs timesheet hours.

    Used by the Compare panel to show expandable day rows.
    Approved hours come from customer_daily_hours (payroll PDF).
    Timesheet hours come from timesheet_daily_hours (employee XLSX).
    Only days where at least one source has hours are included.
    Sunday-missing flag is set when Sunday exists in timesheet but not in approved.
    """
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id, week_ending FROM weekly_approvals "
            "WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            return {"employees": [], "week_ending": None, "week_start": None}

        week_end   = date.fromisoformat(str(wa["week_ending"]))
        week_start = week_end - timedelta(days=6)   # Monday
        wa_id      = wa["id"]

        # Approved daily hours from payroll PDF
        approved_rows = db.fetch_all(conn, """
            SELECT e.display_name, cdh.work_date, cdh.day_name,
                   cdh.clock_in, cdh.clock_out, cdh.total_hours, cdh.is_dbl_day
            FROM customer_daily_hours cdh
            JOIN employees e ON e.id = cdh.employee_id
            WHERE cdh.weekly_approval_id = ?
            ORDER BY e.display_name, cdh.work_date
        """, (wa_id,))

        # Timesheet daily hours for this week (no day_name column — derived from date)
        ts_rows = db.fetch_all(conn, """
            SELECT e.display_name, tdh.work_date,
                   tdh.reg_hours, tdh.ot1_hours, tdh.ot2_hours,
                   tdh.drive_hours, tdh.sick_hours, tdh.vacation_hours,
                   tdh.holiday_hours, tdh.nonbillable_hours
            FROM timesheet_daily_hours tdh
            JOIN timesheet_imports ti ON ti.id = tdh.timesheet_import_id
            JOIN employees e ON e.id = tdh.employee_id
            WHERE ti.pay_period_id = ?
              AND tdh.work_date >= ? AND tdh.work_date <= ?
            ORDER BY e.display_name, tdh.work_date
        """, (period_id, str(week_start), str(week_end)))

        # Build lookup maps: {employee: {date_str: row}}
        approved_map: dict = {}
        for r in approved_rows:
            approved_map.setdefault(r["display_name"], {})[str(r["work_date"])] = r

        ts_map: dict = {}
        for r in ts_rows:
            ts_map.setdefault(r["display_name"], {})[str(r["work_date"])] = r

        # Per-day travel hours map: {display_name: {date_str: travel_hours}}
        # mon_hours–sat_hours map to Mon–Sat of this business week.
        # Sunday travel (week_end) comes from current_sun_hours_assumed once confirmed/assumed.
        travel_rows = db.fetch_all(conn, """
            SELECT e.display_name,
                   th.mon_hours, th.tue_hours, th.wed_hours,
                   th.thu_hours, th.fri_hours, th.sat_hours,
                   th.current_sun_hours_assumed, th.current_sun_status
            FROM travel_hours th
            JOIN employees e ON e.id = th.employee_id
            WHERE th.weekly_approval_id = ?
        """, (wa_id,))

        _day_col_offsets = [
            ("mon_hours", 0), ("tue_hours", 1), ("wed_hours", 2),
            ("thu_hours", 3), ("fri_hours", 4), ("sat_hours", 5),
        ]
        travel_map: dict = {}
        for tr in travel_rows:
            emp_travel: dict = {}
            for col, offset in _day_col_offsets:
                emp_travel[str(week_start + timedelta(days=offset))] = float(tr[col] or 0)
            sun_status = tr["current_sun_status"] or "pending_next_pdf"
            if sun_status in ("confirmed", "assumed_from_timesheet"):
                emp_travel[str(week_end)] = float(tr["current_sun_hours_assumed"] or 0)
            else:
                emp_travel[str(week_end)] = 0.0
            travel_map[tr["display_name"]] = emp_travel

        all_employees = sorted(set(list(approved_map) + list(ts_map)))
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        result = []
        for emp in all_employees:
            days = []
            has_mismatch = False
            mismatch_count = 0

            for i in range(7):
                d         = str(week_start + timedelta(days=i))
                day_name  = day_labels[i]
                is_sunday = (i == 6)

                app_r = approved_map.get(emp, {}).get(d)
                ts_r  = ts_map.get(emp, {}).get(d)

                # approved_total: raw PDF total (labor + travel combined)
                # approved_travel_day: travel hours for this day from travel PDF
                # approved_labor: what we compare to timesheet (PDF total minus travel)
                approved_total = float(app_r["total_hours"] or 0) if app_r else 0.0
                travel_day     = travel_map.get(emp, {}).get(d, 0.0)
                approved_labor = max(0.0, approved_total - travel_day)

                # Timesheet labor only — drive_hours are NOT included because the
                # approved side already has travel accounted for via the travel PDF.
                ts_work = 0.0
                if ts_r:
                    ts_work = (float(ts_r["reg_hours"] or 0) +
                               float(ts_r["ot1_hours"] or 0) +
                               float(ts_r["ot2_hours"] or 0))

                # Skip days where both sides are empty
                ts_any = ts_work > 0
                if not ts_any and ts_r:
                    ts_any = any(float(ts_r[c] or 0) > 0
                                 for c in ("drive_hours","sick_hours","vacation_hours",
                                           "holiday_hours","nonbillable_hours"))
                if approved_total == 0 and not ts_any:
                    continue

                diff = round(approved_labor - ts_work, 2)
                is_mismatch = abs(diff) >= 0.01
                is_sun_missing = is_sunday and ts_work > 0 and app_r is None

                if is_mismatch or is_sun_missing:
                    has_mismatch = True
                    mismatch_count += 1

                days.append({
                    "date":               d,
                    "day_name":           day_name,
                    "is_sunday":          is_sunday,
                    "approved_total":     approved_total,
                    "approved_travel_day": travel_day,
                    "approved_hours":     approved_labor,
                    "clock_in":           app_r["clock_in"]  if app_r else None,
                    "clock_out":          app_r["clock_out"] if app_r else None,
                    "is_dbl_day":         bool(app_r["is_dbl_day"]) if app_r else False,
                    "timesheet_total":    round(ts_work, 2),
                    "timesheet_reg":      float(ts_r["reg_hours"]  or 0) if ts_r else 0.0,
                    "timesheet_ot1":      float(ts_r["ot1_hours"]  or 0) if ts_r else 0.0,
                    "timesheet_ot2":      float(ts_r["ot2_hours"]  or 0) if ts_r else 0.0,
                    "timesheet_drive":    float(ts_r["drive_hours"] or 0) if ts_r else 0.0,
                    "difference":         diff,
                    "in_approved":        app_r is not None,
                    "in_timesheet":       ts_r  is not None,
                    "is_sunday_missing_from_approved": is_sun_missing,
                })

            if days:
                result.append({
                    "display_name":  emp,
                    "has_mismatch":  has_mismatch,
                    "mismatch_count": mismatch_count,
                    "days":          days,
                })

        return {
            "week_ending": str(week_end),
            "week_start":  str(week_start),
            "employees":   result,
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Corrections — identify mismatches, Sunday overrides, correction log
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/periods/{period_id}/weeks/{week_num}/corrections")
def get_corrections(period_id: int, week_num: int):
    """Return all correction_log entries for this week."""
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            return {"corrections": []}

        rows = db.fetch_all(conn, """
            SELECT cl.id, e.display_name, cl.work_date,
                   cl.approved_total_hours, cl.timesheet_total_hours, cl.difference,
                   cl.clock_in, cl.clock_out, cl.generated_note,
                   cl.correction_type, cl.confirmed_with, cl.status,
                   cl.identified_at, cl.applied_at
            FROM correction_log cl
            JOIN employees e ON e.id = cl.employee_id
            WHERE cl.weekly_approval_id = ?
            ORDER BY e.display_name, cl.work_date
        """, (wa["id"],))

        return {"corrections": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.post("/api/periods/{period_id}/weeks/{week_num}/corrections/identify")
def identify_correction(period_id: int, week_num: int, body: dict = {}):
    """Record that a day-level mismatch has been identified and noted.

    This does NOT change any timesheet data — the owner still needs to
    manually correct the XLSX and re-import via the Timesheets node.
    The generated_note should be copied into the corrected timesheet row.
    """
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            raise HTTPException(404, "No weekly_approval found")

        employee_id = body.get("employee_id")
        work_date   = body.get("work_date")
        if not employee_id or not work_date:
            raise HTTPException(400, "employee_id and work_date are required")

        conn.execute("""
            INSERT INTO correction_log
                (employee_id, weekly_approval_id, work_date,
                 approved_total_hours, timesheet_total_hours, difference,
                 clock_in, clock_out, generated_note,
                 correction_type, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved_hours', 'identified')
            ON CONFLICT(weekly_approval_id, employee_id, work_date) DO UPDATE SET
                approved_total_hours  = excluded.approved_total_hours,
                timesheet_total_hours = excluded.timesheet_total_hours,
                difference            = excluded.difference,
                clock_in              = excluded.clock_in,
                clock_out             = excluded.clock_out,
                generated_note        = excluded.generated_note,
                status                = 'identified',
                identified_at         = CURRENT_TIMESTAMP
        """, (
            employee_id,
            wa["id"],
            work_date,
            body.get("approved_total_hours"),
            body.get("timesheet_total_hours"),
            body.get("difference"),
            body.get("clock_in"),
            body.get("clock_out"),
            body.get("generated_note"),
        ))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/periods/{period_id}/weeks/{week_num}/corrections/sunday-override")
def apply_sunday_override(period_id: int, week_num: int, body: dict = {}):
    """Record a Sunday override — Centerline missed Sunday but employee confirmed it.

    This marks the correction_log entry as type='sunday_override' with
    confirmed_with set to the employee's name (as told to the owner).
    The timesheet Sunday hours are treated as correct; no Excel edit needed.
    """
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            raise HTTPException(404, "No weekly_approval found")

        employee_id   = body.get("employee_id")
        work_date     = body.get("work_date")
        confirmed_with = body.get("confirmed_with", "").strip()
        if not employee_id or not work_date:
            raise HTTPException(400, "employee_id and work_date are required")
        if not confirmed_with:
            raise HTTPException(400, "confirmed_with (employee name) is required for Sunday override")

        conn.execute("""
            INSERT INTO correction_log
                (employee_id, weekly_approval_id, work_date,
                 approved_total_hours, timesheet_total_hours, difference,
                 generated_note, correction_type, confirmed_with, status)
            VALUES (?, ?, ?, 0, ?, ?, ?, 'sunday_override', ?, 'confirmed')
            ON CONFLICT(weekly_approval_id, employee_id, work_date) DO UPDATE SET
                correction_type = 'sunday_override',
                confirmed_with  = excluded.confirmed_with,
                timesheet_total_hours = excluded.timesheet_total_hours,
                difference      = excluded.difference,
                generated_note  = excluded.generated_note,
                status          = 'confirmed',
                applied_at      = CURRENT_TIMESTAMP
        """, (
            employee_id,
            wa["id"],
            work_date,
            body.get("timesheet_total_hours"),
            body.get("difference"),
            body.get("generated_note"),
            confirmed_with,
        ))
        conn.commit()

        # Also update weekly_employee_verification to reflect the override
        # so the variance clears when verification is re-run
        weekly_verifier.set_verified(
            conn, wa["id"], employee_id,
            note=f"Sunday override confirmed with {confirmed_with}"
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/periods/{period_id}/weeks/{week_num}/corrections/resolve")
def resolve_correction(period_id: int, week_num: int, body: dict = Body(default={})):
    """Record a source adjudication decision for a mismatched day.

    source = 'approved_wins': CL hours are authoritative for this day.
             DrewEdit export will update the employee XLSX and add a note.
    source = 'timesheet_wins': Employee hours stand; no XLSX change needed.
             For Sunday-missing cases, confirmed_with (employee name) is required.
    """
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            raise HTTPException(404, "No weekly_approval found")

        employee_id = body.get("employee_id")
        work_date   = body.get("work_date")
        source      = body.get("source")

        if not employee_id or not work_date:
            raise HTTPException(400, "employee_id and work_date are required")
        if source not in ("approved_wins", "timesheet_wins"):
            raise HTTPException(400, "source must be 'approved_wins' or 'timesheet_wins'")

        confirmed_with    = (body.get("confirmed_with") or "").strip()
        is_sunday_missing = body.get("is_sunday_missing", False)

        if source == "timesheet_wins" and is_sunday_missing and not confirmed_with:
            raise HTTPException(400, "confirmed_with is required when timesheet wins for a Sunday-missing case")

        approved_hrs = body.get("approved_total_hours") or 0
        ts_hrs       = body.get("timesheet_total_hours") or 0
        clock_in     = body.get("clock_in")
        clock_out    = body.get("clock_out")

        if source == "approved_wins":
            if clock_in and clock_out:
                note = f"Centerline Approved {float(approved_hrs):.2f}hrs ({clock_in}-{clock_out})"
            elif approved_hrs:
                note = f"Centerline Approved {float(approved_hrs):.2f}hrs"
            else:
                note = "Sunday removed — not in Centerline approved hours"
        else:
            if confirmed_with:
                note = f"Sunday confirmed with {confirmed_with} — timesheet override"
            else:
                note = "Timesheet confirmed — employee hours used"

        conn.execute("""
            INSERT INTO correction_log
                (employee_id, weekly_approval_id, work_date,
                 approved_total_hours, timesheet_total_hours, difference,
                 clock_in, clock_out, generated_note,
                 correction_type, confirmed_with, status, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'resolved', CURRENT_TIMESTAMP)
            ON CONFLICT(weekly_approval_id, employee_id, work_date) DO UPDATE SET
                approved_total_hours  = excluded.approved_total_hours,
                timesheet_total_hours = excluded.timesheet_total_hours,
                difference            = excluded.difference,
                clock_in              = excluded.clock_in,
                clock_out             = excluded.clock_out,
                generated_note        = excluded.generated_note,
                correction_type       = excluded.correction_type,
                confirmed_with        = excluded.confirmed_with,
                status                = 'resolved',
                applied_at            = CURRENT_TIMESTAMP
        """, (
            employee_id, wa["id"], work_date,
            approved_hrs, ts_hrs, body.get("difference"),
            clock_in, clock_out, note,
            source, confirmed_with or None,
        ))
        conn.commit()
        return {"ok": True, "note": note}
    finally:
        conn.close()


@app.get("/api/periods/{period_id}/weeks/{week_num}/travel-hours")
def get_travel_hours(period_id: int, week_num: int):
    """Return per-employee travel hours for a given week, day by day.

    Used by the Travel PDF panel to show only what was extracted from the
    travel PDF — Mon through Sat raw hours plus the Sunday attribution.
    """
    conn = _get_conn()
    try:
        wa = db.fetch_one(conn,
            "SELECT id, week_ending, travel_pdf_file "
            "FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
            (period_id, week_num))
        if not wa:
            return {"rows": [], "week_ending": None, "travel_pdf": None}

        rows = db.fetch_all(conn, """
            SELECT e.display_name,
                   th.mon_hours, th.tue_hours, th.wed_hours,
                   th.thu_hours, th.fri_hours, th.sat_hours,
                   th.sun_hours, th.current_week_total,
                   th.current_sun_status, th.current_sun_hours_assumed,
                   th.prior_week_sun_applied
            FROM travel_hours th
            JOIN employees e ON e.id = th.employee_id
            WHERE th.weekly_approval_id = ?
            ORDER BY e.display_name
        """, (wa["id"],))

        return {
            "week_ending": str(wa["week_ending"]),
            "travel_pdf":  wa["travel_pdf_file"],
            "rows": [{
                "employee":              r["display_name"],
                "mon":                   float(r["mon_hours"] or 0),
                "tue":                   float(r["tue_hours"] or 0),
                "wed":                   float(r["wed_hours"] or 0),
                "thu":                   float(r["thu_hours"] or 0),
                "fri":                   float(r["fri_hours"] or 0),
                "sat":                   float(r["sat_hours"] or 0),
                "sun":                   float(r["sun_hours"] or 0),
                "week_total":            float(r["current_week_total"] or 0),
                "sun_status":            r["current_sun_status"],
                "sun_hours_assumed":     float(r["current_sun_hours_assumed"] or 0),
                "prior_week_sun_applied": bool(r["prior_week_sun_applied"]),
            } for r in rows],
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Receipts — required receipt checklist for a period
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/periods/{period_id}/receipts")
def get_receipts(period_id: int, week_num: int = None):
    """Return expense items that require receipts, optionally filtered to one week."""
    conn = _get_conn()
    try:
        week_start = week_end = None
        if week_num:
            period = db.fetch_one(conn,
                "SELECT week1_ending, week2_ending FROM pay_periods WHERE id = ?",
                (period_id,))
            if period:
                if week_num == 1 and period["week1_ending"]:
                    wk_end   = date.fromisoformat(period["week1_ending"])
                    wk_start = wk_end - timedelta(days=6)
                    week_start, week_end = str(wk_start), str(wk_end)
                elif week_num == 2 and period["week2_ending"]:
                    wk_end   = date.fromisoformat(period["week2_ending"])
                    wk_start = wk_end - timedelta(days=6)
                    week_start, week_end = str(wk_start), str(wk_end)

        if week_start and week_end:
            rows = db.fetch_all(conn, """
                SELECT ei.id, e.display_name as employee,
                       ei.work_date, ei.category, ei.description,
                       ei.amount, ei.currency,
                       ei.receipt_status, ei.billing_status, ei.reimbursement_status
                FROM expense_items ei
                JOIN employees e ON e.id = ei.employee_id
                WHERE ei.pay_period_id = ? AND ei.requires_receipt = 1
                  AND ei.work_date >= ? AND ei.work_date <= ?
                ORDER BY e.display_name, ei.work_date
            """, (period_id, week_start, week_end))
        else:
            rows = db.fetch_all(conn, """
                SELECT ei.id, e.display_name as employee,
                       ei.work_date, ei.category, ei.description,
                       ei.amount, ei.currency,
                       ei.receipt_status, ei.billing_status, ei.reimbursement_status
                FROM expense_items ei
                JOIN employees e ON e.id = ei.employee_id
                WHERE ei.pay_period_id = ? AND ei.requires_receipt = 1
                ORDER BY e.display_name, ei.work_date
            """, (period_id,))

        items = [{
            "id":                   r["id"],
            "employee":             r["employee"],
            "work_date":            r["work_date"],
            "category":             r["category"],
            "description":          r["description"],
            "amount":               float(r["amount"]),
            "currency":             r["currency"],
            "receipt_status":       r["receipt_status"],
            "billing_status":       r["billing_status"],
            "reimbursement_status": r["reimbursement_status"],
        } for r in rows]

        return {
            "items":          items,
            "total_count":    len(items),
            "missing_count":  sum(1 for r in rows if r["receipt_status"] == "missing"),
            "received_count": sum(1 for r in rows if r["receipt_status"] == "received"),
            "deferred_count": sum(1 for r in rows if r["receipt_status"] == "deferred"),
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/periods/{period_id}/expenses/{expense_id}/attach-receipt")
def attach_receipt(period_id: int, expense_id: int,
                   file: UploadFile = File(...)):
    """Attach a receipt file to an expense item and mark it received."""
    conn = _get_conn()
    try:
        row = db.fetch_one(conn,
            "SELECT id FROM expense_items WHERE id = ? AND pay_period_id = ?",
            (expense_id, period_id))
        if not row:
            raise HTTPException(404, "Expense item not found")

        cfg.ensure_source_dirs()
        safe_name = f"{period_id}_{expense_id}_{file.filename}"
        dest = cfg.RECEIPT_DIR / safe_name
        content = file.file.read()
        dest.write_bytes(content)

        conn.execute("""
            INSERT INTO expense_receipts
                (expense_item_id, original_filename, stored_path, received_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (expense_id, file.filename, str(dest)))
        conn.execute(
            "UPDATE expense_items SET receipt_status = 'received' WHERE id = ?",
            (expense_id,))
        conn.commit()
        return {"status": "ok", "expense_id": expense_id, "filename": file.filename}
    finally:
        conn.close()


@app.post("/api/periods/{period_id}/expenses/{expense_id}/defer")
def defer_receipt(period_id: int, expense_id: int, body: dict = Body(default={})):
    """Defer a missing receipt to the next period."""
    conn = _get_conn()
    try:
        row = db.fetch_one(conn,
            "SELECT id FROM expense_items WHERE id = ? AND pay_period_id = ?",
            (expense_id, period_id))
        if not row:
            raise HTTPException(404, "Expense item not found")
        note = body.get("note", "")
        conn.execute(
            "UPDATE expense_items SET receipt_status = 'deferred', description = CASE "
            "WHEN ? != '' THEN COALESCE(description, '') || ' [deferred: ' || ? || ']' "
            "ELSE description END WHERE id = ?",
            (note, note, expense_id))
        conn.commit()
        return {"status": "ok", "expense_id": expense_id}
    finally:
        conn.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════════
# Debug / dev tools  (never call these in production)
# ═══════════════════════════════════════════════════════════════════════════════

# Tables that hold imported payroll / timesheet / expense data — ordered so that
# child tables are deleted before the parent tables they reference.
# Deletion order matters: children before parents (foreign key constraints).
_IMPORTED_DATA_TABLES = [
    "audit_log",
    "source_file_edits",
    "expense_receipts",
    "expense_items",
    "correction_log",
    "reconciliation",
    "weekly_employee_verification",
    "timesheet_daily_hours",
    "timesheet_hours",
    "timesheet_imports",
    "customer_daily_hours",
    "travel_hours",
    "customer_hours",
    "weekly_approvals",
    "pay_periods",
    "source_files",
]

# Employee-side tables (only wiped on full reset).
_EMPLOYEE_TABLES = [
    "employee_assignments",
    "employee_rates",
    "employee_aliases",
    "employees",
]


@app.get("/api/debug/stats")
def debug_stats():
    """Return row counts for every major table — useful for a quick DB overview."""
    all_tables = _EMPLOYEE_TABLES + _IMPORTED_DATA_TABLES
    conn = _get_conn()
    try:
        counts = {}
        for table in all_tables:
            row = db.fetch_one(conn, f"SELECT COUNT(*) AS n FROM {table}")
            counts[table] = row["n"] if row else 0
        return {"tables": counts}
    finally:
        conn.close()


@app.post("/api/debug/clear-imported-data")
def debug_clear_imported_data():
    """Delete all imported payroll/timesheet/expense data.

    Employees, aliases, rates, and assignments are preserved so you don't
    have to re-enter the employee roster after a test wipe.
    """
    conn = _get_conn()
    try:
        for table in _IMPORTED_DATA_TABLES:
            conn.execute(f"DELETE FROM {table}")
        db.log_audit(conn, action="debug_clear_imported_data",
                     entity_type="system", entity_id=None,
                     new_value="all imported data deleted via debug endpoint")
        conn.commit()
        return {"ok": True, "cleared": _IMPORTED_DATA_TABLES}
    finally:
        conn.close()


@app.post("/api/debug/clear-and-reseed")
def debug_clear_and_reseed():
    """Delete everything — including employees — then re-seed from defaults.

    Use this to get back to a completely clean state matching the seed data
    in employee_manager.py.
    """
    conn = _get_conn()
    try:
        # Wipe imported data first (child tables), then employee tables.
        for table in _IMPORTED_DATA_TABLES + _EMPLOYEE_TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

        # Re-run schema (idempotent) then re-seed employees.
        db.initialize_database(conn)
        employee_manager.seed_employees(conn)
        conn.commit()
        return {"ok": True, "message": "Database cleared and re-seeded with default employees"}
    finally:
        conn.close()
