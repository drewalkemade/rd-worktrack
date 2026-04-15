#!/usr/bin/env python3
"""
bulk_import.py — Import all testing/ pay periods into the database.

Run from the repo root:
    python testing/bulk_import.py [--period 20260329] [--dry-run]

Processes period directories under testing/ in chronological order.

For each directory the script imports:
  1. Payroll PDFs  (both weeks, week_ending derived from filename)
  2. Travel PDFs   (both weeks where present)
  3. Timesheets    (_DrewEdit.xlsx preferred over original when both exist)

Edge-case handling:
  - UPDATE payroll PDFs (R&D_YYMMDD-xxxxx-UPDATE.pdf) are imported after
    the original; the upsert overwrites the earlier values.
  - If no travel PDF exists for a week, that week's travel is simply absent.
  - _DrewEdit timesheets replace the original for the same employee/period.

Exit code: 0 if all imports succeeded, 1 if any errors occurred.
"""

import argparse
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent          # testing/
REPO_ROOT    = SCRIPT_DIR.parent                         # rd-worktrack/
TESTING_ROOT = SCRIPT_DIR

sys.path.insert(0, str(REPO_ROOT))

from payroll_app import config
from payroll_app.database import db, employee_manager
from payroll_app.pipeline import importer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _yymm_to_date(yymm: str) -> date:
    """Convert a 6-digit YYMMDD string to a date.  e.g. '260329' → 2026-03-29."""
    yy = int(yymm[:2])
    mm = int(yymm[2:4])
    dd = int(yymm[4:6])
    yyyy = 2000 + yy   # safe for 2000-2099
    return date(yyyy, mm, dd)


def _payroll_week_ending(pdf_name: str) -> date | None:
    """Extract the week_ending Sunday from a payroll PDF filename.

    Accepts:  R&D_260329-xxxxx.pdf  or  R&D_260329-xxxxx-UPDATE.pdf
    Returns:  date(2026, 3, 29)     or  None if pattern not matched.
    """
    m = re.match(r"R&D_(\d{6})-xxxxx", pdf_name)
    if m:
        return _yymm_to_date(m.group(1))
    return None


def _is_drewdit(path: Path) -> bool:
    return "_DrewEdit" in path.stem


def _collect_timesheets(period_dir: Path) -> list[Path]:
    """Return the timesheets to import for this period.

    When both an original and a _DrewEdit version exist for the same base name
    (same stem minus the '_DrewEdit' suffix), the DrewEdit wins.  Each unique
    employee file is returned exactly once.
    """
    all_xlsx = list(period_dir.glob("*.xlsx"))

    # Build a map: base_stem → preferred path
    # base_stem = stem with _DrewEdit removed
    preferred: dict[str, Path] = {}

    for p in sorted(all_xlsx):
        base = p.stem.replace("_DrewEdit", "")
        if base not in preferred or _is_drewdit(p):
            preferred[base] = p

    return sorted(preferred.values())


# ── Colour / formatting ───────────────────────────────────────────────────────

def _ok(msg: str)   -> None: print(f"  \033[32m✓\033[0m  {msg}")
def _warn(msg: str) -> None: print(f"  \033[33m⚠\033[0m  {msg}")
def _err(msg: str)  -> None: print(f"  \033[31m✗\033[0m  {msg}")
def _skip(msg: str) -> None: print(f"  \033[90m–\033[0m  {msg}")


# ── Per-file import wrappers ──────────────────────────────────────────────────

def _import_payroll(conn, pdf_path: Path, week_ending: date, dry_run: bool) -> bool:
    if dry_run:
        _skip(f"[dry-run] payroll  {pdf_path.name}  (week {week_ending})")
        return True
    result = importer.import_payroll_pdf(
        conn,
        pdf_path=pdf_path,
        week_ending_date=week_ending,
        original_name=pdf_path.name,
        normalized_name=pdf_path.name,
    )
    conn.commit()
    if result.success:
        _ok(
            f"payroll  {pdf_path.name}  →  "
            f"{result.employee_count} employees"
            + (f"  ({result.skipped_count} skipped)" if result.skipped_count else "")
        )
        for w in result.warnings:
            _warn(w)
        for line in result.extraction_log:
            if line.strip().startswith(("OK", "SKIP")):
                print(f"         {line.strip()}")
    else:
        for e in result.errors:
            _err(f"payroll  {pdf_path.name}: {e}")
        for w in result.warnings:
            _warn(w)
    return result.success


def _import_travel(conn, pdf_path: Path, dry_run: bool) -> bool:
    if dry_run:
        _skip(f"[dry-run] travel   {pdf_path.name}")
        return True
    result = importer.import_travel_pdf(
        conn,
        pdf_path=pdf_path,
        original_name=pdf_path.name,
        normalized_name=pdf_path.name,
    )
    conn.commit()
    if result.success:
        _ok(
            f"travel   {pdf_path.name}  →  "
            f"{result.employee_count} employees"
            + (f"  ({result.skipped_count} skipped)" if result.skipped_count else "")
        )
        for w in result.warnings:
            _warn(w)
    else:
        for e in result.errors:
            _err(f"travel   {pdf_path.name}: {e}")
        for w in result.warnings:
            _warn(w)
    return result.success


def _import_timesheet(conn, xlsx_path: Path, dry_run: bool) -> bool:
    if dry_run:
        edit_flag = " [DrewEdit]" if _is_drewdit(xlsx_path) else ""
        _skip(f"[dry-run] timesheet  {xlsx_path.name}{edit_flag}")
        return True
    result = importer.import_timesheet(
        conn,
        xlsx_path=xlsx_path,
        original_name=xlsx_path.name,
        normalized_name=None,
    )
    conn.commit()
    if result.success:
        edit_flag = " [DrewEdit]" if _is_drewdit(xlsx_path) else ""
        _ok(
            f"timesheet  {xlsx_path.name}{edit_flag}"
            + (f"  REG={_ts_total(result.extraction_log, 'REG')}"
               f"  OT={_ts_total(result.extraction_log, 'OT')}" if result.extraction_log else "")
        )
        for w in result.warnings:
            _warn(w)
    else:
        for e in result.errors:
            _err(f"timesheet  {xlsx_path.name}: {e}")
        for w in result.warnings:
            _warn(w)
    return result.success


def _ts_total(log_lines: list[str], label: str) -> str:
    """Extract a total value from the extraction log lines, e.g. 'REG=80.00'."""
    for line in log_lines:
        m = re.search(rf"{label}=([\d.]+)", line)
        if m:
            return m.group(1)
    return "?"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk-import testing/ pay periods.")
    parser.add_argument(
        "--period", metavar="YYYYMMDD",
        help="Import only this period directory (e.g. 20260329).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be imported without touching the database.",
    )
    args = parser.parse_args()

    # Collect period directories in chronological order
    all_dirs = sorted(
        d for d in TESTING_ROOT.iterdir()
        if d.is_dir() and re.match(r"\d{8}$", d.name)
    )

    if args.period:
        all_dirs = [d for d in all_dirs if d.name == args.period]
        if not all_dirs:
            print(f"Period directory not found: {args.period}")
            return 1

    # Open DB and seed employees
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db.initialize_database(conn)
    employee_manager.seed_employees(conn)
    conn.commit()

    total_ok    = 0
    total_err   = 0
    total_warn  = 0

    for period_dir in all_dirs:
        print(f"\n{'─' * 60}")
        print(f"Period: {period_dir.name}")
        print(f"{'─' * 60}")

        pdfs = sorted(period_dir.glob("*.pdf"))

        # --- Payroll PDFs (xxxxx pattern) ---
        payroll_pdfs = [p for p in pdfs if "-xxxxx" in p.name]
        for pdf in payroll_pdfs:
            week_ending = _payroll_week_ending(pdf.name)
            if week_ending is None:
                _warn(f"Could not determine week_ending from {pdf.name!r} — skipped.")
                total_warn += 1
                continue
            ok = _import_payroll(conn, pdf, week_ending, args.dry_run)
            if ok:
                total_ok += 1
            else:
                total_err += 1

        # --- Travel PDFs ---
        travel_pdfs = [p for p in pdfs if "-Travel" in p.name]
        for pdf in travel_pdfs:
            ok = _import_travel(conn, pdf, args.dry_run)
            if ok:
                total_ok += 1
            else:
                total_err += 1

        # --- Timesheets ---
        timesheets = _collect_timesheets(period_dir)
        for xlsx in timesheets:
            ok = _import_timesheet(conn, xlsx, args.dry_run)
            if ok:
                total_ok += 1
            else:
                total_err += 1

    conn.close()

    print(f"\n{'═' * 60}")
    print(f"Done.  {total_ok} OK   {total_err} errors   {total_warn} warnings")
    print(f"{'═' * 60}")

    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
