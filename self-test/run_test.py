#!/usr/bin/env python3
"""
End-to-end regression suite for rd-worktrack pipeline.

Dynamically computes expected values from DB / source documents — no
hardcoded dollar amounts or employee names.  Designed to be run, fail,
trigger app fixes, and be re-run until all assertions pass.

Requirements:
  - FastAPI backend running at http://localhost:8000
  - Test data in self-test/1-timesheets/, 2-approved-hours/, 3-receipts/,
    5-export-timesheet/

Usage (from repo root):
    source .venv/bin/activate
    python self-test/run_test.py 2>&1 | tee self-test/last_run.log
"""

import csv
import sys
import traceback
from pathlib import Path
from datetime import date, timedelta

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import requests
except ImportError:
    print("ERROR: requests not installed.  pip install requests")
    sys.exit(1)

from payroll_app.database import db
from payroll_app.pipeline import importer, weekly_verifier, reconciler, cheque_run_writer
from payroll_app.extractors import receipt_ingest

BASE = "http://localhost:8000"
ST   = REPO / "self-test"

# ---------------------------------------------------------------------------
# Billing rate constants (business rules, not test-specific)
# ---------------------------------------------------------------------------
RATE_REG      = 72.00
RATE_OT1      = 93.60
RATE_OT2     = 122.40
RATE_TRAVEL   = 72.00
RATE_PER_DIEM = 70.00
HST_RATE      = 0.13

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0

def ok(msg: str) -> None:
    global _pass
    _pass += 1
    print(f"  ✓ {msg}")

def fail(msg: str, got=None, want=None) -> None:
    global _fail
    _fail += 1
    lines = [f"  ✗ {msg}"]
    if got  is not None: lines.append(f"      got:  {got!r}")
    if want is not None: lines.append(f"      want: {want!r}")
    print("\n".join(lines))

def section(title: str) -> None:
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

def check_eq(label: str, got, want, tol=None) -> None:
    if tol is not None:
        if abs(float(got) - float(want)) <= tol:
            ok(label)
        else:
            fail(label, got=round(float(got), 4), want=f"{want} ±{tol}")
    else:
        if got == want:
            ok(label)
        else:
            fail(label, got=got, want=want)

def check_in(label: str, needle, haystack) -> None:
    if needle in haystack:
        ok(label)
    else:
        fail(label, got=f"{needle!r} not in collection", want=f"present in {list(haystack)[:8]}")

def check_not_in(label: str, needle, haystack) -> None:
    if needle not in haystack:
        ok(label)
    else:
        fail(label, got=f"{needle!r} unexpectedly found in collection")

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(path: str, **kw):
    r = requests.get(f"{BASE}{path}", timeout=30, **kw)
    r.raise_for_status()
    return r.json()

def _post(path: str, **kw):
    r = requests.post(f"{BASE}{path}", timeout=30, **kw)
    r.raise_for_status()
    return r.json()

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _conn():
    return db.get_connection()

def _wa_id(conn, period_id: int, week_num: int):
    row = db.fetch_one(conn,
        "SELECT id FROM weekly_approvals WHERE pay_period_id = ? AND week_number = ?",
        (period_id, week_num))
    return row["id"] if row else None

# ---------------------------------------------------------------------------
# Step 0 — Prerequisites
# ---------------------------------------------------------------------------

def step0_prerequisites() -> None:
    section("Step 0 — Prerequisites")

    try:
        r = requests.get(f"{BASE}/api/health", timeout=5)
        if r.status_code == 200:
            ok("FastAPI health check")
        else:
            fail("FastAPI health check", got=r.status_code, want=200)
            print("\n  Start the backend first:")
            print("    source .venv/bin/activate")
            print("    uvicorn payroll_app.api.main:app --reload --port 8000")
            sys.exit(1)
    except Exception as e:
        fail(f"FastAPI unreachable: {e}")
        print("\n  Start the backend first:")
        print("    source .venv/bin/activate")
        print("    uvicorn payroll_app.api.main:app --reload --port 8000")
        sys.exit(1)

    ts_dir   = ST / "1-timesheets"
    pdf_dir  = ST / "2-approved-hours"
    rec_dir  = ST / "3-receipts"
    ref_dir  = ST / "5-export-timesheet"

    expected_files = [
        *ts_dir.glob("*.xlsx"),
        pdf_dir / "R&D_260322-xxxxx.pdf",
        pdf_dir / "R&D_260322-Travel.pdf",
        pdf_dir / "R&D_260329-xxxxx.pdf",
        pdf_dir / "R&D_260329-Travel.pdf",
        *rec_dir.glob("*.PNG"),
        ref_dir / "timesheet_20260329.csv",
    ]
    for p in expected_files:
        if p.exists():
            ok(f"File exists: {p.name}")
        else:
            fail(f"Missing file: {p}")

    ts_files = sorted(ts_dir.glob("*.xlsx"))
    check_eq("8 timesheet XLSX files present", len(ts_files), 8)

# ---------------------------------------------------------------------------
# Step 1 — Clear Imported Data
# ---------------------------------------------------------------------------

def step1_clear() -> None:
    section("Step 1 — Clear Imported Data")

    _post("/api/debug/clear-imported-data")
    ok("POST /api/debug/clear-imported-data → 200")

    stats = _get("/api/debug/stats")
    tables = stats.get("tables", stats)  # handle both {tables:{}} and flat dict
    for key in ("timesheet_daily_hours", "customer_daily_hours", "travel_hours",
                "expense_items", "weekly_approvals", "weekly_employee_verification"):
        count = tables.get(key, -1)
        check_eq(f"{key} = 0 after clear", count, 0)

# ---------------------------------------------------------------------------
# Step 2 — Import Timesheets
# ---------------------------------------------------------------------------

def step2_import_timesheets() -> None:
    section("Step 2 — Import Timesheets (8 files)")

    ts_files = sorted((ST / "1-timesheets").glob("*.xlsx"))

    for xlsx in ts_files:
        conn = _conn()
        try:
            result = importer.import_timesheet(conn, xlsx)
            conn.commit()
            if result.success:
                ok(f"Imported {xlsx.name}")
            else:
                fail(f"Import failed: {xlsx.name}", got=result.errors)
        except Exception as e:
            fail(f"Exception importing {xlsx.name}", got=str(e))
        finally:
            conn.close()

    conn = _conn()
    try:
        count = db.fetch_one(conn, "SELECT COUNT(*) AS n FROM timesheet_daily_hours")["n"]
        if count > 0:
            ok(f"timesheet_daily_hours populated ({count} rows)")
        else:
            fail("timesheet_daily_hours is empty after import")

        unmatched = db.fetch_all(conn,
            "SELECT DISTINCT display_name FROM employees "
            "WHERE UPPER(display_name) LIKE '%UNKNOWN%'")
        if not unmatched:
            ok("No UNKNOWN employees in database")
        else:
            for r in unmatched:
                fail(f"Unmatched employee: {r['display_name']}")
    finally:
        conn.close()

    # Idempotency — re-import, row count must not grow
    conn = _conn()
    count_before = db.fetch_one(conn, "SELECT COUNT(*) AS n FROM timesheet_daily_hours")["n"]
    conn.close()

    for xlsx in ts_files:
        conn = _conn()
        try:
            importer.import_timesheet(conn, xlsx)
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    conn = _conn()
    count_after = db.fetch_one(conn, "SELECT COUNT(*) AS n FROM timesheet_daily_hours")["n"]
    conn.close()
    check_eq("Import idempotency: row count stable", count_after, count_before)

# ---------------------------------------------------------------------------
# Steps 3 & 4 — Import Payroll + Travel PDFs
# ---------------------------------------------------------------------------

def _import_week_pdfs(week_ending_str: str, label: str) -> None:
    pdf_dir  = ST / "2-approved-hours"
    date_tag = week_ending_str.replace("-", "")[2:]   # "2026-03-22" → "260322"

    payroll_pdf = next(pdf_dir.glob(f"R&D_{date_tag}-xxxxx.pdf"), None)
    travel_pdf  = next(pdf_dir.glob(f"R&D_{date_tag}-Travel.pdf"), None)

    if payroll_pdf is None:
        fail(f"{label}: payroll PDF not found (R&D_{date_tag}-xxxxx.pdf)")
        return
    if travel_pdf is None:
        fail(f"{label}: travel PDF not found (R&D_{date_tag}-Travel.pdf)")
        return

    conn = _conn()
    try:
        r1 = importer.import_payroll_pdf(conn, payroll_pdf, week_ending_str)
        if r1.success:
            ok(f"{label}: imported payroll PDF")
        else:
            fail(f"{label}: payroll PDF import", got=r1.errors)

        r2 = importer.import_travel_pdf(conn, travel_pdf)
        if r2.success:
            ok(f"{label}: imported travel PDF")
        else:
            fail(f"{label}: travel PDF import", got=r2.errors)

        conn.commit()

        row = db.fetch_one(conn,
            "SELECT COUNT(*) AS n FROM weekly_approvals WHERE week_ending = ?",
            (week_ending_str,))
        check_eq(f"{label}: weekly_approvals row for {week_ending_str}", row["n"], 1)
    except Exception as e:
        fail(f"{label}: exception during import", got=str(e))
        traceback.print_exc()
    finally:
        conn.close()


def step3_import_week1_pdfs() -> None:
    section("Step 3 — Import Week 1 PDFs (w/e 2026-03-22)")
    _import_week_pdfs("2026-03-22", "Week 1")


def step4_import_week2_pdfs() -> None:
    section("Step 4 — Import Week 2 PDFs (w/e 2026-03-29)")
    _import_week_pdfs("2026-03-29", "Week 2")

# ---------------------------------------------------------------------------
# Step 5 — Resolve Period ID
# ---------------------------------------------------------------------------

def step5_resolve_period() -> int:
    section("Step 5 — Resolve Period ID")

    conn = _conn()
    try:
        row = db.fetch_one(conn,
            "SELECT id, period_start, period_end FROM pay_periods "
            "WHERE period_end = '2026-03-29'")
    finally:
        conn.close()

    if not row:
        fail("pay_period with period_end=2026-03-29 not found — was import successful?")
        sys.exit(1)

    period_id = row["id"]
    ok(f"Period ID = {period_id} ({row['period_start']} – {row['period_end']})")

    conn = _conn()
    try:
        weeks = db.fetch_all(conn,
            "SELECT week_number, week_ending FROM weekly_approvals "
            "WHERE pay_period_id = ? ORDER BY week_number",
            (period_id,))
    finally:
        conn.close()

    check_eq("Both weeks present in weekly_approvals", len(weeks), 2)
    for w in weeks:
        ok(f"  Week {w['week_number']}: week_ending={w['week_ending']}")

    return period_id

# ---------------------------------------------------------------------------
# Step 6 — Run Verification + Travel Spot Check
# ---------------------------------------------------------------------------

def step6_run_verification(period_id: int) -> None:
    section("Step 6 — Run Verification (Both Weeks)")

    for wk in [1, 2]:
        conn = _conn()
        try:
            wa_id = _wa_id(conn, period_id, wk)
            if not wa_id:
                fail(f"Week {wk}: no weekly_approval found")
                continue
            weekly_verifier.run_weekly_verification(conn, wa_id)
            conn.commit()
            ok(f"Week {wk}: verification run (wa_id={wa_id})")
        except Exception as e:
            fail(f"Week {wk}: verification failed", got=str(e))
            traceback.print_exc()
        finally:
            conn.close()

    # Travel subtraction spot check:
    # For any employee who has travel hours in Week 1, verify that the
    # day-comparison API returns approved_hours = max(0, pdf_total - travel_day)
    day_comp = _get(f"/api/periods/{period_id}/weeks/1/day-comparison")

    travel_checks = 0
    for emp in day_comp.get("employees", []):
        for d in emp.get("days", []):
            pdf_total  = d.get("approved_total")  or 0
            travel_day = d.get("approved_travel_day") or 0
            if travel_day > 0 and pdf_total > 0:
                expected_labor = max(0.0, round(float(pdf_total) - float(travel_day), 4))
                got_labor      = round(float(d.get("approved_hours") or 0), 4)
                check_eq(
                    f"Travel subtraction: {emp['display_name']} {d['date']} "
                    f"(pdf={pdf_total}h − travel={travel_day}h)",
                    got_labor,
                    expected_labor,
                    tol=0.005,
                )
                travel_checks += 1
                if travel_checks >= 5:
                    break
        if travel_checks >= 5:
            break

    if travel_checks == 0:
        fail("No travel days found for spot check — travel import may have failed")
    else:
        ok(f"Travel spot check: verified {travel_checks} days")

# ---------------------------------------------------------------------------
# Step 7 — Auto-Resolve All Mismatches
# ---------------------------------------------------------------------------

def step7_auto_resolve(period_id: int) -> None:
    section("Step 7 — Auto-Resolve All Mismatches")

    for wk in [1, 2]:
        ver = _get(f"/api/periods/{period_id}/weeks/{wk}/verification")
        needs_review = [r for r in ver.get("rows", []) if r["status"] == "needs_review"]

        if not needs_review:
            ok(f"Week {wk}: no needs_review employees — nothing to resolve")
            continue

        day_comp = _get(f"/api/periods/{period_id}/weeks/{wk}/day-comparison")
        day_map  = {emp["display_name"]: emp["days"]
                    for emp in day_comp.get("employees", [])}

        total_resolved = 0
        for emp_row in needs_review:
            days      = day_map.get(emp_row["display_name"], [])
            mismatches = [
                d for d in days
                if abs(d.get("difference") or 0) >= 0.01
                   or d.get("is_sunday_missing_from_approved")
            ]
            for d in mismatches:
                try:
                    _post(
                        f"/api/periods/{period_id}/weeks/{wk}/corrections/resolve",
                        json={
                            "employee_id":           emp_row["employee_id"],
                            "work_date":             d["date"],
                            "source":                "approved_wins",
                            "approved_total_hours":  d.get("approved_hours") or 0,
                            "timesheet_total_hours": d.get("timesheet_total") or 0,
                            "difference":            d.get("difference") or 0,
                            "clock_in":              d.get("clock_in"),
                            "clock_out":             d.get("clock_out"),
                            "is_sunday_missing":     d.get("is_sunday_missing_from_approved", False),
                        }
                    )
                    total_resolved += 1
                except Exception as e:
                    fail(
                        f"Week {wk}: resolve failed for {emp_row['display_name']} {d['date']}",
                        got=str(e)
                    )

        ok(f"Week {wk}: posted {total_resolved} resolution(s) for "
           f"{len(needs_review)} employee(s)")

        # Re-run verification to reflect corrections
        conn = _conn()
        try:
            wa_id = _wa_id(conn, period_id, wk)
            weekly_verifier.run_weekly_verification(conn, wa_id)
            conn.commit()
        finally:
            conn.close()

# ---------------------------------------------------------------------------
# Step 8 — Attach Florin's Receipts + Per-Diem Counts + Boundary Checks
# ---------------------------------------------------------------------------

def step8_attach_receipts(period_id: int) -> None:
    section("Step 8 — Attach Receipts + Per-Diem + Boundary Checks")

    rec_dir = ST / "3-receipts"
    png_files = sorted(rec_dir.glob("*.PNG"))

    if not png_files:
        fail("No PNG receipt files found in self-test/3-receipts/")
        return

    ok(f"Found {len(png_files)} receipt PNG(s) in self-test/3-receipts/")

    # Fetch all expense items that require receipts for this period
    receipts_data = _get(f"/api/periods/{period_id}/receipts")
    all_items     = receipts_data.get("items", [])

    if not all_items:
        fail("No expense items requiring receipts found for this period")
        return

    # Build (employee_display_name, work_date) → item_id map
    date_emp_to_item: dict[tuple[str, str], dict] = {}
    for item in all_items:
        key = (item.get("employee", ""), item.get("work_date", ""))
        date_emp_to_item[key] = item

    # Build (work_date) → item_id for matching PNG files
    # PNG naming convention: <employee>_<category>_<MM>_<DD>_<YYYY>.PNG
    date_to_items: dict[str, list[dict]] = {}
    for item in all_items:
        wd = item.get("work_date", "")
        if wd:
            date_to_items.setdefault(wd, []).append(item)

    ok(f"{len(all_items)} expense item(s) found across {len(date_to_items)} date(s)")

    # Week boundary check — each item should be tagged to the correct week
    for item in all_items:
        wd  = item.get("work_date", "")
        wk  = item.get("week_num")
        if wd and wk is not None:
            if wd <= "2026-03-22":
                check_eq(f"Boundary: {item.get('employee','')} {wd} → Week 1", wk, 1)
            elif wd <= "2026-03-29":
                check_eq(f"Boundary: {item.get('employee','')} {wd} → Week 2", wk, 2)

    # Attach each PNG to its matching expense item by date
    attached = 0
    for png in png_files:
        # Extract date from filename (format: *_MM_DD_YYYY.PNG)
        parts = png.stem.split("_")
        try:
            month = int(parts[-3])
            day   = int(parts[-2])
            year  = int(parts[-1])
            work_date = f"{year:04d}-{month:02d}-{day:02d}"
        except (IndexError, ValueError):
            fail(f"Cannot parse date from filename: {png.name}")
            continue

        # Find matching missing item for this date
        candidates = [
            i for i in date_to_items.get(work_date, [])
            if i.get("receipt_status") == "missing"
        ]
        if not candidates:
            fail(f"No missing expense item for {work_date} (file: {png.name})",
                 got="no match", want=f"item with work_date={work_date!r}")
            continue

        item_id = candidates[0]["id"]
        conn = _conn()
        try:
            result = receipt_ingest.ingest_receipt(conn, png, item_id,
                                                   original_name=png.name)
            conn.commit()
            if result.success:
                ok(f"Attached {png.name} → expense item {item_id} ({work_date})")
                attached += 1
            else:
                fail(f"Receipt ingest failed: {png.name}", got=result.errors)
        except Exception as e:
            fail(f"Exception attaching {png.name}", got=str(e))
        finally:
            conn.close()

    ok(f"Attached {attached} of {len(png_files)} receipt(s)")

    # Verify all are received (none missing)
    receipts_after = _get(f"/api/periods/{period_id}/receipts")
    still_missing  = [i for i in receipts_after.get("items", [])
                      if i.get("receipt_status") == "missing"]
    received       = [i for i in receipts_after.get("items", [])
                      if i.get("receipt_status") == "received"]
    deferred       = [i for i in receipts_after.get("items", [])
                      if i.get("receipt_status") == "deferred"]

    if still_missing:
        for i in still_missing:
            fail(f"Still missing receipt: {i.get('employee','')} {i.get('work_date','')} "
                 f"{i.get('category','')}")
    else:
        ok(f"All receipts accounted for ({len(received)} received, {len(deferred)} deferred)")

    # Per-diem count check — query DB, then verify invoice line reflects same count
    for wk in [1, 2]:
        inv = _get(f"/api/periods/{period_id}/weeks/{wk}/invoice-preview")
        for emp in inv.get("employees", []):
            pd_line = next(
                (ln for ln in emp.get("lines", [])
                 if "per diem" in ln.get("description", "").lower()),
                None
            )
            if pd_line is None:
                fail(f"Week {wk}: {emp['display_name']} has no per-diem line")
                continue

            # Compare invoice per-diem qty to DB value
            conn = _conn()
            try:
                wa_id = _wa_id(conn, period_id, wk)
                db_row = db.fetch_one(conn,
                    "SELECT simple_per_diem_count FROM weekly_employee_verification "
                    "WHERE weekly_approval_id = ? AND employee_id = ?",
                    (wa_id, emp["employee_id"]))
                if db_row:
                    db_count = float(db_row["simple_per_diem_count"] or 0)
                    invoice_qty = float(pd_line.get("qty") or 0)
                    check_eq(
                        f"Week {wk}: {emp['display_name']} per-diem qty matches DB",
                        round(invoice_qty, 2),
                        round(db_count, 2),
                    )
            finally:
                conn.close()

# ---------------------------------------------------------------------------
# Step 9 — Verify All Employees
# ---------------------------------------------------------------------------

def step9_verify_all(period_id: int) -> None:
    section("Step 9 — Verify All Employees (Both Weeks)")

    for wk in [1, 2]:
        ver = _get(f"/api/periods/{period_id}/weeks/{wk}/verification")
        rows = ver.get("rows", [])

        conn = _conn()
        try:
            wa_id = _wa_id(conn, period_id, wk)
            for r in rows:
                if r["status"] != "verified":
                    try:
                        weekly_verifier.set_verified(conn, wa_id, r["employee_id"])
                        ok(f"Week {wk}: verified {r['display_name']}")
                    except Exception as e:
                        fail(f"Week {wk}: could not verify {r['display_name']}", got=str(e))
            conn.commit()
        finally:
            conn.close()

        # Confirm all verified via API
        ver2      = _get(f"/api/periods/{period_id}/weeks/{wk}/verification")
        unverified = [r for r in ver2.get("rows", []) if r["status"] != "verified"]
        if not unverified:
            ok(f"Week {wk}: all {len(ver2.get('rows', []))} employee(s) verified")
        else:
            fail(f"Week {wk}: {len(unverified)} employee(s) not verified",
                 got=[r["display_name"] for r in unverified])

# ---------------------------------------------------------------------------
# Step 10 & 11 — Invoice Preview Checks (dynamic — expected from DB)
# ---------------------------------------------------------------------------

def _expected_invoice_from_db(conn, period_id: int, wk: int) -> dict:
    """Compute expected invoice subtotals directly from DB verification + expenses.

    This is independent of the invoice-preview API so we can catch calculation bugs.
    """
    wa_id = _wa_id(conn, period_id, wk)
    wa_row = db.fetch_one(conn, "SELECT week_ending FROM weekly_approvals WHERE id = ?", (wa_id,))
    if not wa_row:
        return {}

    week_end   = date.fromisoformat(str(wa_row["week_ending"]))
    week_start = week_end - timedelta(days=6)

    # Billable employees + verified hours for this week
    ver_rows = db.fetch_all(conn, """
        SELECT v.employee_id, e.display_name,
               v.approved_reg, v.approved_ot, v.approved_dbl, v.approved_travel,
               v.simple_per_diem_count
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
    """, (wa_id, str(week_end), str(week_start)))

    # Non-per-diem expenses with receipts received or deferred (same filter as API)
    exp_rows = db.fetch_all(conn, """
        SELECT ei.employee_id, COALESCE(ei.quantity, 1) AS quantity,
               COALESCE(ei.amount, 0) AS amount
        FROM expense_items ei
        WHERE ei.pay_period_id = ?
          AND ei.work_date BETWEEN ? AND ?
          AND ei.category NOT IN ('per_diem_travel', 'per_diem_full')
          AND ei.receipt_status IN ('received', 'deferred')
    """, (period_id, str(week_start), str(week_end)))

    exp_by_emp: dict[int, float] = {}
    for ex in exp_rows:
        emp_id = ex["employee_id"]
        exp_by_emp[emp_id] = exp_by_emp.get(emp_id, 0) + round(
            float(ex["quantity"]) * float(ex["amount"]), 2)

    expected: dict[str, dict] = {}
    grand_subtotal = 0.0

    for r in ver_rows:
        reg   = float(r["approved_reg"]    or 0)
        ot1   = float(r["approved_ot"]     or 0)
        ot2   = float(r["approved_dbl"]    or 0)
        trav  = float(r["approved_travel"] or 0)
        perd  = float(r["simple_per_diem_count"] or 0)
        exps  = exp_by_emp.get(r["employee_id"], 0.0)

        subtotal = round(
            reg  * RATE_REG
            + ot1  * RATE_OT1
            + ot2  * RATE_OT2
            + trav * RATE_TRAVEL
            + perd * RATE_PER_DIEM
            + exps,
            2
        )
        grand_subtotal += subtotal
        expected[r["display_name"]] = {
            "reg": reg, "ot1": ot1, "ot2": ot2, "travel": trav,
            "per_diem": perd, "expenses": exps, "subtotal": subtotal,
        }

    grand_subtotal = round(grand_subtotal, 2)
    hst_amount     = round(grand_subtotal * HST_RATE, 2)

    return {
        "employees":   expected,
        "subtotal":    grand_subtotal,
        "hst_amount":  hst_amount,
        "total":       round(grand_subtotal + hst_amount, 2),
    }


def _check_invoice(period_id: int, wk: int) -> None:
    conn = _conn()
    try:
        expected = _expected_invoice_from_db(conn, period_id, wk)
    finally:
        conn.close()

    if not expected.get("employees"):
        fail(f"Week {wk}: no billable verified employees found in DB — nothing to check")
        return

    api_data = _get(f"/api/periods/{period_id}/weeks/{wk}/invoice-preview")

    check_eq(f"Week {wk}: all_verified", api_data.get("all_verified"), True)

    # Internal employees must be absent
    api_emp_names = {e["display_name"] for e in api_data.get("employees", [])}
    conn = _conn()
    try:
        internal = db.fetch_all(conn, """
            SELECT DISTINCT e.display_name
            FROM employees e
            JOIN employee_assignments ea ON ea.employee_id = e.id
            WHERE ea.assignment_type = 'internal'
        """)
    finally:
        conn.close()
    for row in internal:
        check_not_in(
            f"Week {wk}: internal employee {row['display_name']!r} excluded from invoice",
            row["display_name"],
            api_emp_names,
        )

    # Per-employee subtotals: DB-computed vs API
    api_emp_map = {e["display_name"]: e for e in api_data.get("employees", [])}

    for name, vals in expected["employees"].items():
        api_emp = api_emp_map.get(name)
        if api_emp is None:
            fail(f"Week {wk}: {name!r} missing from invoice-preview",
                 got="absent", want="present")
            continue

        check_eq(
            f"Week {wk}: {name} subtotal (DB-computed vs API)",
            round(float(api_emp.get("subtotal", 0)), 2),
            round(vals["subtotal"], 2),
            tol=0.015,
        )

        # 6 lines minimum: regular/ot1/ot2/travel/per_diem + expense placeholder
        total_lines = len(api_emp.get("lines", []))
        if total_lines >= 6:
            ok(f"Week {wk}: {name} has {total_lines} invoice lines (≥6)")
        else:
            fail(f"Week {wk}: {name} has too few invoice lines", got=total_lines, want="≥6")

    # Grand totals: DB-computed vs API
    check_eq(f"Week {wk}: subtotal (DB vs API)",
             round(float(api_data.get("subtotal", 0)), 2),
             expected["subtotal"],
             tol=0.015)
    check_eq(f"Week {wk}: hst_amount (DB vs API)",
             round(float(api_data.get("hst_amount", 0)), 2),
             expected["hst_amount"],
             tol=0.015)
    check_eq(f"Week {wk}: total (DB vs API)",
             round(float(api_data.get("total", 0)), 2),
             expected["total"],
             tol=0.015)

    print(f"  Invoice Week {wk} summary: subtotal={expected['subtotal']:.2f} "
          f"hst={expected['hst_amount']:.2f} total={expected['total']:.2f}")


def step10_invoice_week1(period_id: int) -> None:
    section("Step 10 — Invoice Week 1")
    _check_invoice(period_id, 1)


def step11_invoice_week2(period_id: int) -> None:
    section("Step 11 — Invoice Week 2")
    _check_invoice(period_id, 2)

# ---------------------------------------------------------------------------
# Step 12 — Reconciliation + Sage 50 Export
# ---------------------------------------------------------------------------

def _parse_sage50_csv(path: Path) -> dict[str, dict[str, float]]:
    """Parse a Sage 50 CSV (UTF-16) into {name: {income_type: hours}}."""
    result: dict[str, dict[str, float]] = {}
    with open(path, encoding="utf-16") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name   = (row.get("Name") or "").strip()
            income = (row.get("Income") or "").strip()
            hours  = float(row.get("Hours") or 0)
            if name and income:
                result.setdefault(name, {})[income] = hours
    return result


def _expected_sage50_from_db(conn, period_id: int) -> dict[str, dict[str, float]]:
    """Compute expected Sage 50 rows from reconciliation + timesheet data.

    Mirrors cheque_run_writer.export_sage50_csv():
      - final_reg/ot/dbl/drive come from reconciliation
      - holiday and nonbillable come from timesheet_hours (same source as writer)
    All 6 income types included per employee (matching the writer's _INCOME_TYPES).
    """
    rows = db.fetch_all(conn, """
        SELECT r.employee_id, r.final_reg, r.final_ot, r.final_dbl, r.final_drive,
               e.display_name,
               COALESCE(th.holiday_hours, 0)     AS holiday_hours,
               COALESCE(th.nonbillable_hours, 0) AS nonbillable_hours,
               (SELECT alias_value FROM employee_aliases ea2
                WHERE ea2.employee_id = r.employee_id
                  AND ea2.alias_type = 'sage50_name'
                LIMIT 1) AS sage50_name
        FROM reconciliation r
        JOIN employees e ON e.id = r.employee_id
        LEFT JOIN timesheet_hours th
               ON th.employee_id = r.employee_id
              AND th.pay_period_id = r.pay_period_id
        WHERE r.pay_period_id = ?
          AND r.status IN ('approved', 'exported')
        ORDER BY e.display_name
    """, (period_id,))

    expected: dict[str, dict[str, float]] = {}
    for r in rows:
        name = (r["sage50_name"] or r["display_name"]).strip()
        expected[name] = {
            "Regular":      float(r["final_reg"]        or 0),
            "Overtime 1":   float(r["final_ot"]         or 0),
            "Overtime 2":   float(r["final_dbl"]        or 0),
            "Drive":        float(r["final_drive"]      or 0),
            "Holiday":      float(r["holiday_hours"]    or 0),
            "Non-Billable": float(r["nonbillable_hours"]or 0),
        }
    return expected


def step12_sage50(period_id: int) -> None:
    section("Step 12 — Reconciliation + Sage 50 Export")

    # Run reconciliation
    conn = _conn()
    try:
        reconciler.run_reconciliation(conn, period_id, force=True)
        conn.commit()
        ok("Reconciliation complete")
    except Exception as e:
        fail(f"Reconciliation failed: {e}")
        traceback.print_exc()
        conn.close()
        return

    # Approve all reconciliation rows (including variance ones for test purposes)
    try:
        all_recs = db.fetch_all(conn,
            "SELECT employee_id FROM reconciliation WHERE pay_period_id = ?",
            (period_id,))
        for r in all_recs:
            try:
                reconciler.approve_reconciliation(
                    conn, period_id, r["employee_id"],
                    notes="auto-approved by test suite",
                    approved_by="test_run",
                )
            except Exception:
                pass
        conn.commit()
        ok(f"Approved {len(all_recs)} reconciliation row(s)")
    except Exception as e:
        fail(f"Approve reconciliation failed: {e}")
        traceback.print_exc()
    finally:
        conn.close()

    # Export Sage 50 CSV
    conn = _conn()
    try:
        out_path = cheque_run_writer.export_sage50_csv(
            conn, period_id, period_end_date="20260329"
        )
        conn.commit()
        ok(f"Sage 50 CSV exported to: {out_path.name}")
    except Exception as e:
        fail(f"Sage 50 export failed: {e}")
        traceback.print_exc()
        conn.close()
        return

    # Compute expected from DB (now approved)
    expected = _expected_sage50_from_db(conn, period_id)
    conn.close()

    # Check encoding
    try:
        with open(out_path, encoding="utf-16") as fh:
            fh.read()
        ok("Sage 50 CSV is UTF-16 readable")
    except (UnicodeDecodeError, UnicodeError) as e:
        fail("Sage 50 CSV encoding error (expected UTF-16)", got=str(e))
        return

    # Parse generated CSV
    try:
        generated = _parse_sage50_csv(out_path)
        ok(f"Generated Sage 50 CSV: {len(generated)} employee(s)")
    except Exception as e:
        fail(f"Failed to parse generated CSV: {e}")
        return

    # Compare DB-expected vs generated
    all_names = set(expected) | set(generated)
    for name in sorted(all_names):
        exp_emp = expected.get(name, {})
        gen_emp = generated.get(name, {})
        if name not in expected:
            fail(f"Sage 50: {name!r} in generated but not in approved reconciliation")
            continue
        if name not in generated:
            fail(f"Sage 50: {name!r} in approved reconciliation but missing from generated CSV")
            continue
        for income_type in set(exp_emp) | set(gen_emp):
            exp_h = exp_emp.get(income_type, 0.0)
            gen_h = gen_emp.get(income_type, 0.0)
            check_eq(
                f"Sage 50: {name} / {income_type}",
                round(gen_h, 4),
                round(exp_h, 4),
                tol=0.005,
            )

    # Compare generated to reference CSV (canonical expected for this dataset)
    ref_path = ST / "5-export-timesheet" / "timesheet_20260329.csv"
    try:
        reference = _parse_sage50_csv(ref_path)
        ok(f"Reference CSV parsed: {len(reference)} employee(s)")
    except Exception as e:
        fail(f"Failed to parse reference CSV: {e}")
        return

    ref_names = set(reference)
    gen_names = set(generated)

    extra_in_gen = gen_names - ref_names
    missing_from_gen = ref_names - gen_names

    if extra_in_gen:
        for n in sorted(extra_in_gen):
            fail(f"Sage 50 vs reference: {n!r} in generated but not in reference CSV")
    if missing_from_gen:
        for n in sorted(missing_from_gen):
            fail(f"Sage 50 vs reference: {n!r} in reference CSV but missing from generated")

    for name in sorted(ref_names & gen_names):
        ref_emp = reference[name]
        gen_emp = generated[name]
        for income_type in set(ref_emp) | set(gen_emp):
            ref_h = ref_emp.get(income_type, 0.0)
            gen_h = gen_emp.get(income_type, 0.0)
            check_eq(
                f"Sage 50 vs reference: {name} / {income_type}",
                round(gen_h, 4),
                round(ref_h, 4),
                tol=0.005,
            )

    if extra_in_gen or missing_from_gen:
        pass  # already reported above
    else:
        ok(f"Sage 50 CSV matches reference CSV for all {len(ref_names)} employee(s)")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("\nrd-worktrack End-to-End Test Suite")
    print(f"Repo:      {REPO}")
    print(f"Test data: {ST}")

    step0_prerequisites()
    step1_clear()
    step2_import_timesheets()
    step3_import_week1_pdfs()
    step4_import_week2_pdfs()

    period_id = step5_resolve_period()

    step6_run_verification(period_id)
    step7_auto_resolve(period_id)
    step8_attach_receipts(period_id)
    step9_verify_all(period_id)
    step10_invoice_week1(period_id)
    step11_invoice_week2(period_id)
    step12_sage50(period_id)

    section("Results")
    print(f"\n  {_pass} passed  /  {_fail} failed\n")
    if _fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
