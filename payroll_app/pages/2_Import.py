"""
2_Import.py — Source file ingestion page.

Supports:
  - Payroll approval PDF (weekly, one per week-ending Sunday)
  - Travel hours PDF (weekly, Sun–Sat range from Centerline)
  - Employee timesheet workbook (biweekly .xlsx)

Centerline sends files with long human-readable names.
The app accepts the original filename and lets the owner provide the
normalized internal name (R&D_YYMMDD-xxxxx.pdf / R&D_YYMMDD-Travel.pdf).

Each import:
  1. Saves the file to disk in the source-file store.
  2. Parses it with the relevant extractor.
  3. Resolves employee identities.
  4. Creates or updates pay period and weekly approval records.
  5. Upserts all extracted data idempotently.
  6. Shows a result summary with any warnings or errors.

After import the page shows the most recent source files in the DB.
"""

import tempfile
import sys
from datetime import date, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from payroll_app import config
from payroll_app.database import db
from payroll_app.pipeline import importer

st.set_page_config(page_title="Import — R&D Controls", layout="wide")

st.title("Import")
st.caption("Ingest payroll PDFs, travel PDFs, and employee timesheets into the database.")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _most_recent_sunday_on_or_before(d: date) -> date:
    """Return the most recent Sunday on or before d (0=Mon … 6=Sun)."""
    days_since_sunday = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sunday)


def _show_result(result) -> None:
    """Display an ImportResult in a consistent format."""
    if result.errors:
        for err in result.errors:
            st.error(err)

    if result.success:
        st.success(
            f"Import complete — {result.employee_count} employee record(s) imported"
            + (f", {result.skipped_count} skipped" if result.skipped_count else "")
            + "."
        )
        if result.source_file_id:
            st.caption(f"Source file ID: {result.source_file_id}")
        if result.pay_period_id:
            st.caption(f"Pay period ID: {result.pay_period_id}")
        if result.weekly_approval_id:
            st.caption(f"Weekly approval ID: {result.weekly_approval_id}")
        if result.timesheet_import_id:
            st.caption(f"Timesheet import ID: {result.timesheet_import_id}")

    if result.warnings:
        with st.expander(f"Warnings ({len(result.warnings)})", expanded=len(result.warnings) > 0):
            for w in result.warnings:
                st.warning(w)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_payroll, tab_travel, tab_timesheet, tab_history = st.tabs([
    "Payroll PDF",
    "Travel PDF",
    "Timesheet",
    "Import History",
])


# ===========================================================================
# Tab 1 — Payroll PDF
# ===========================================================================

with tab_payroll:
    st.subheader("Payroll Approval PDF")
    st.markdown(
        "Centerline sends these as e.g. `R&D Controls Payroll Approval 2026-04-07 09.26.42.pdf`. "
        "Upload the file and enter the week-ending Sunday date."
    )

    payroll_file = st.file_uploader(
        "Choose payroll approval PDF",
        type=["pdf"],
        key="payroll_uploader",
        help="The weekly customer payroll approval PDF from Centerline.",
    )

    col_date, col_norm = st.columns([1, 2])

    with col_date:
        default_week_end = _most_recent_sunday_on_or_before(date.today())
        payroll_week_end = st.date_input(
            "Week-ending Sunday",
            value=default_week_end,
            key="payroll_week_end",
            help="The Sunday that ends the Mon–Sun work week for this PDF.",
        )

    with col_norm:
        if payroll_file and payroll_week_end:
            yymm = payroll_week_end.strftime("%y%m%d")
            suggested_norm = f"R&D_{yymm}-xxxxx.pdf"
        else:
            suggested_norm = "R&D_YYMMDD-xxxxx.pdf"

        payroll_norm_name = st.text_input(
            "Normalized internal filename",
            value=suggested_norm,
            key="payroll_norm_name",
            help="Internal filing name. Leave as suggested or edit if needed.",
        )

    if payroll_file:
        if not isinstance(payroll_week_end, date):
            st.warning("Please select a valid week-ending Sunday date.")
        elif payroll_week_end.weekday() != 6:
            st.warning(
                f"{payroll_week_end.strftime('%A %Y-%m-%d')} is not a Sunday. "
                "The week-ending date must be a Sunday."
            )
        else:
            if st.button("Import Payroll PDF", type="primary", key="btn_import_payroll"):
                with st.spinner("Importing payroll PDF…"):
                    # Write uploaded bytes to a temp file
                    suffix = Path(payroll_file.name).suffix or ".pdf"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(payroll_file.read())
                        tmp_path = Path(tmp.name)

                    conn = db.get_connection()
                    try:
                        result = importer.import_payroll_pdf(
                            conn,
                            pdf_path=tmp_path,
                            week_ending_date=payroll_week_end,
                            original_name=payroll_file.name,
                            normalized_name=payroll_norm_name.strip() or None,
                        )
                        conn.commit()
                    except Exception as exc:
                        conn.rollback()
                        st.error(f"Import failed: {exc}")
                        result = None
                    finally:
                        conn.close()
                        tmp_path.unlink(missing_ok=True)

                if result:
                    _show_result(result)


# ===========================================================================
# Tab 2 — Travel PDF
# ===========================================================================

with tab_travel:
    st.subheader("Travel Hours PDF")
    st.markdown(
        "Centerline sends these as e.g. `Contractor Travel Hrs - March 29-April 4, 2026.pdf`. "
        "The travel PDF is formatted Sun–Sat. The app handles the Sunday boundary automatically."
    )

    travel_file = st.file_uploader(
        "Choose travel hours PDF",
        type=["pdf"],
        key="travel_uploader",
        help="The weekly Centerline travel hours PDF.",
    )

    col_tnorm, _ = st.columns([2, 1])

    with col_tnorm:
        travel_norm_name = st.text_input(
            "Normalized internal filename",
            value="R&D_YYMMDD-Travel.pdf",
            key="travel_norm_name",
            help="Internal filing name. e.g. R&D_260329-Travel.pdf",
        )

    if travel_file:
        if st.button("Import Travel PDF", type="primary", key="btn_import_travel"):
            with st.spinner("Importing travel PDF…"):
                suffix = Path(travel_file.name).suffix or ".pdf"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(travel_file.read())
                    tmp_path = Path(tmp.name)

                conn = db.get_connection()
                try:
                    result = importer.import_travel_pdf(
                        conn,
                        pdf_path=tmp_path,
                        original_name=travel_file.name,
                        normalized_name=travel_norm_name.strip() or None,
                    )
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    st.error(f"Import failed: {exc}")
                    result = None
                finally:
                    conn.close()
                    tmp_path.unlink(missing_ok=True)

            if result:
                _show_result(result)


# ===========================================================================
# Tab 3 — Timesheet
# ===========================================================================

with tab_timesheet:
    st.subheader("Employee Timesheet")
    st.markdown(
        "Upload an employee biweekly timesheet workbook (`.xlsx`). "
        "The period end date and employee name are read from the workbook itself."
    )

    ts_file = st.file_uploader(
        "Choose timesheet workbook",
        type=["xlsx"],
        key="ts_uploader",
        help="Employee biweekly timesheet in the standard template format.",
    )

    col_tsnorm, _ = st.columns([2, 1])

    with col_tsnorm:
        ts_norm_name = st.text_input(
            "Normalized internal filename (optional)",
            value="",
            placeholder="Leave blank to use the original filename",
            key="ts_norm_name",
            help="Override the stored filename if needed. Usually leave blank.",
        )

    if ts_file:
        if st.button("Import Timesheet", type="primary", key="btn_import_ts"):
            with st.spinner("Importing timesheet…"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp.write(ts_file.read())
                    tmp_path = Path(tmp.name)

                conn = db.get_connection()
                try:
                    result = importer.import_timesheet(
                        conn,
                        xlsx_path=tmp_path,
                        original_name=ts_file.name,
                        normalized_name=ts_norm_name.strip() or None,
                    )
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    st.error(f"Import failed: {exc}")
                    result = None
                finally:
                    conn.close()
                    tmp_path.unlink(missing_ok=True)

            if result:
                _show_result(result)


# ===========================================================================
# Tab 4 — Import History
# ===========================================================================

with tab_history:
    st.subheader("Import History")

    conn = db.get_connection()
    try:
        files = db.fetch_all(
            conn,
            """
            SELECT
                sf.id,
                sf.file_type,
                sf.original_name,
                sf.normalized_name,
                sf.path,
                sf.imported_at,
                sf.edit_label
            FROM source_files sf
            ORDER BY sf.imported_at DESC
            LIMIT 50
            """,
        )
    finally:
        conn.close()

    if files:
        rows = []
        for f in files:
            rows.append({
                "ID":             f["id"],
                "Type":           f["file_type"],
                "Original Name":  f["original_name"],
                "Stored As":      f["normalized_name"] or f["original_name"],
                "Edit Label":     f["edit_label"] or "",
                "Imported At":    f["imported_at"],
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

        st.caption(f"Showing most recent 50 of all imported files.")

        # Source document access
        st.divider()
        st.markdown("**Open a source document**")
        file_id = st.number_input(
            "Source file ID",
            min_value=1,
            step=1,
            key="open_file_id",
            help="Enter the ID from the table above.",
        )
        if st.button("Show path", key="btn_show_path"):
            conn = db.get_connection()
            try:
                row = db.fetch_one(
                    conn,
                    "SELECT path, original_name FROM source_files WHERE id = ?",
                    (int(file_id),),
                )
            finally:
                conn.close()

            if row:
                st.code(row["path"])
                st.caption(
                    f"Original name: {row['original_name']}  \n"
                    "Copy the path above to open the file in your file manager or PDF viewer."
                )
            else:
                st.warning(f"No source file with ID {int(file_id)} found.")
    else:
        st.info("No files have been imported yet.")
