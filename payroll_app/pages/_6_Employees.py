"""
6_Employees.py — Employee roster, alias management, and assignment history.

This is a reference / admin page.  The owner can:
  - See all employees in a summary table.
  - Expand any employee to inspect their aliases and assignment history.
  - Add a new alias for an employee via a small form.

No clever abstractions — all queries are written out explicitly so they are
easy to read and debug.
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from payroll_app.database import db
from payroll_app.database import employee_manager

st.set_page_config(page_title="Employees — R&D Controls", layout="wide")

st.title("Employees")
st.caption(
    "Employee roster, PDF/travel name aliases, and assignment history.  "
    "Use this page to inspect identity mappings and add new aliases when a "
    "PDF or travel document uses an unexpected name variant."
)

# ---------------------------------------------------------------------------
# Load the full roster — sorted by display_name, never hardcoded order
# ---------------------------------------------------------------------------

conn = db.get_connection()
try:
    employees = db.fetch_all(
        conn,
        """
        SELECT
            id,
            display_name,
            pdf_name,
            pdf_id,
            centerline_id,
            active
        FROM employees
        ORDER BY display_name ASC
        """,
    )
finally:
    conn.close()

if not employees:
    st.warning(
        "No employees found in the database.  "
        "Run the seed step (employee_manager.seed_employees) to populate the roster."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Summary roster table
# ---------------------------------------------------------------------------

st.subheader("Roster")

# Build a plain list of dicts so st.dataframe renders cleanly
roster_rows = []
for emp in employees:
    # Derive assignment type from the most recent open assignment — we will
    # fetch this individually per employee in the detail section, but for the
    # summary table we want a single-pass query instead of N+1 queries.
    roster_rows.append(
        {
            "Name":           emp["display_name"],
            "PDF Name":       emp["pdf_name"] or "—",
            "Centerline ID":  str(emp["centerline_id"]) if emp["centerline_id"] else "—",
            "Active":         "Yes" if emp["active"] else "No",
        }
    )

st.dataframe(
    roster_rows,
    use_container_width=True,
    hide_index=True,
)

st.divider()

# ---------------------------------------------------------------------------
# Per-employee detail expanders
# ---------------------------------------------------------------------------

st.subheader("Employee Detail")
st.caption("Expand an employee row to see their aliases, assignment history, and add a new alias.")

ALIAS_TYPES = [
    "pdf_name",
    "travel_name",
    "display_name",
    "expense_code",
    "receipt_filename",
]

for emp in employees:
    emp_id = emp["id"]
    emp_name = emp["display_name"]

    with st.expander(emp_name):

        # ----------------------------------------------------------------
        # Core identity fields
        # ----------------------------------------------------------------
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("**Source-of-truth identity**")
            st.write(f"**Display name:** {emp['display_name']}")
            st.write(f"**PDF name:** {emp['pdf_name'] or '— (no payroll PDF)'}")
            st.write(f"**PDF ID:** {emp['pdf_id'] or '— (no payroll PDF)'}")
            st.write(f"**Centerline ID:** {emp['centerline_id'] or '— (internal)'}")
            st.write(f"**Active:** {'Yes' if emp['active'] else 'No'}")

        # ----------------------------------------------------------------
        # Aliases table
        # ----------------------------------------------------------------
        with col_right:
            st.markdown("**Aliases**")

            conn = db.get_connection()
            try:
                aliases = db.fetch_all(
                    conn,
                    """
                    SELECT alias_type, alias_value
                    FROM employee_aliases
                    WHERE employee_id = ?
                    ORDER BY alias_type ASC, alias_value ASC
                    """,
                    (emp_id,),
                )
            finally:
                conn.close()

            if aliases:
                alias_rows = [
                    {"Type": row["alias_type"], "Value": row["alias_value"]}
                    for row in aliases
                ]
                st.dataframe(alias_rows, use_container_width=True, hide_index=True)
            else:
                st.info("No aliases registered for this employee.")

        # ----------------------------------------------------------------
        # Assignment history
        # ----------------------------------------------------------------
        st.markdown("**Assignment history**")

        conn = db.get_connection()
        try:
            assignments = db.fetch_all(
                conn,
                """
                SELECT
                    assignment_type,
                    customer_code,
                    effective_start,
                    effective_end,
                    notes
                FROM employee_assignments
                WHERE employee_id = ?
                ORDER BY effective_start DESC
                """,
                (emp_id,),
            )
        finally:
            conn.close()

        if assignments:
            assignment_rows = []
            for row in assignments:
                assignment_rows.append(
                    {
                        "Type":          row["assignment_type"],
                        "Customer Code": row["customer_code"] or "—",
                        "Start":         row["effective_start"],
                        "End":           row["effective_end"] or "current",
                        "Notes":         row["notes"] or "",
                    }
                )
            st.dataframe(assignment_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No assignment records found for this employee.")

        # ----------------------------------------------------------------
        # Add Alias form
        # ----------------------------------------------------------------
        st.markdown("**Add alias**")
        st.caption(
            "Use this when a PDF or travel document uses a name that is not yet "
            "registered.  The alias will be used for all future automatic matching."
        )

        # Use a unique form key per employee to avoid Streamlit key collisions
        form_key = f"add_alias_form_{emp_id}"

        with st.form(key=form_key, clear_on_submit=True):
            alias_type_input = st.selectbox(
                "Alias type",
                options=ALIAS_TYPES,
                help=(
                    "pdf_name — name exactly as it appears in a payroll approval PDF\n"
                    "travel_name — name exactly as it appears in a travel PDF\n"
                    "display_name — human-readable variant (spaces, capitalisation)\n"
                    "expense_code — legacy code used in expense workbooks\n"
                    "receipt_filename — prefix used in scanned receipt filenames"
                ),
                key=f"alias_type_{emp_id}",
            )
            alias_value_input = st.text_input(
                "Alias value",
                placeholder="e.g. TRIF, DANIEL  or  Daniel Trif  or  DTRIF",
                key=f"alias_value_{emp_id}",
            )
            submitted = st.form_submit_button("Add alias")

        if submitted:
            alias_value_stripped = alias_value_input.strip()

            if not alias_value_stripped:
                st.error("Alias value cannot be blank.  Enter the exact text to match.")
            else:
                conn = db.get_connection()
                try:
                    # Check whether this exact alias already exists to give a
                    # clear message rather than silently swallowing the conflict.
                    existing = db.fetch_one(
                        conn,
                        """
                        SELECT ea.id, e.display_name
                        FROM employee_aliases ea
                        JOIN employees e ON e.id = ea.employee_id
                        WHERE ea.alias_type = ? AND ea.alias_value = ?
                        """,
                        (alias_type_input, alias_value_stripped),
                    )

                    if existing:
                        if existing["display_name"] == emp_name:
                            st.warning(
                                f"The alias ({alias_type_input}: "
                                f'"{alias_value_stripped}") is already registered '
                                f"for {emp_name}.  No change made."
                            )
                        else:
                            st.error(
                                f"Conflict: ({alias_type_input}: "
                                f'"{alias_value_stripped}") is already registered '
                                f"for **{existing['display_name']}**, not {emp_name}.  "
                                f"Resolve the conflict before adding this alias."
                            )
                    else:
                        employee_manager.add_alias(
                            conn,
                            emp_id,
                            alias_type_input,
                            alias_value_stripped,
                        )
                        db.log_audit(
                            conn,
                            action="add_alias",
                            entity_type="employee_aliases",
                            entity_id=emp_id,
                            new_value=f"{alias_type_input}:{alias_value_stripped}",
                        )
                        conn.commit()
                        st.success(
                            f"Alias added: ({alias_type_input}: "
                            f'"{alias_value_stripped}") for {emp_name}.'
                        )
                        st.rerun()
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    st.error(f"Database error while adding alias: {exc}")
                finally:
                    conn.close()
