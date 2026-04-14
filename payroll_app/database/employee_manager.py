"""
employee_manager.py — Employee identity, alias lookup, and seed data.

Design rules:
  - Alias matching is the only way parsers should resolve employee names.
    Never match by display_name directly in parser code.
  - Fuzzy matching (rapidfuzz) is used only when an exact alias match fails.
    Ambiguous fuzzy matches are never silently accepted; they must be flagged.
  - Seed data reflects the employees known at project kickoff. Add new employees
    through the Employees UI or by calling add_employee() directly.
"""

import sqlite3
from typing import Optional

from rapidfuzz import process as fuzz_process, fuzz

from payroll_app import config
from payroll_app.database import db


# ---------------------------------------------------------------------------
# Seed data
# Known employees as of 2026-03 project kickoff.
# Each entry: (display_name, pdf_name, pdf_id, centerline_id, assignment_type, aliases)
# aliases: list of (alias_type, alias_value) tuples
# ---------------------------------------------------------------------------

_SEED_EMPLOYEES = [
    # ---- Centerline-billable employees ----
    {
        "display_name":   "Daniel Trif",
        "pdf_name":       "TRIF, DANIEL",
        "pdf_id":         "E8190",
        "centerline_id":  8190,
        "assignment":     config.ASSIGNMENT_BILLABLE,
        "aliases": [
            ("pdf_name",    "TRIF, DANIEL"),
            ("travel_name", "Daniel Trif"),
        ],
    },
    {
        "display_name":   "Jerry Jeremias",
        "pdf_name":       "JEREMIAS, JERRY",
        "pdf_id":         "E8174",
        "centerline_id":  8174,
        "assignment":     config.ASSIGNMENT_BILLABLE,
        "aliases": [
            ("pdf_name",    "JEREMIAS, JERRY"),
            ("travel_name", "Jerry Jeremias"),
        ],
    },
    {
        "display_name":   "Yousof Saleh",
        "pdf_name":       "SALEH, YOUSOF",
        "pdf_id":         "E8668",
        "centerline_id":  8668,
        "assignment":     config.ASSIGNMENT_BILLABLE,
        "aliases": [
            ("pdf_name",    "SALEH, YOUSOF"),
            ("travel_name", "Yousof Saleh"),
            ("travel_name", "Saleh, Yousof"),
        ],
    },
    {
        "display_name":   "Florin Moldovan",
        "pdf_name":       "MOLDOVAN, FLORIN",
        "pdf_id":         "E8650",
        "centerline_id":  8650,
        "assignment":     config.ASSIGNMENT_BILLABLE,
        "aliases": [
            ("pdf_name",    "MOLDOVAN, FLORIN"),
            # Travel PDF shows "Florin Moldovan Has" — "Has" is noise from the PDF layout
            ("travel_name", "Florin Moldovan"),
            ("travel_name", "Florin Moldovan Has"),
        ],
    },
    {
        "display_name":   "Jarrett Zorzi",
        "pdf_name":       "ZORZI, JARRETT",
        "pdf_id":         "E8611",
        "centerline_id":  8611,
        "assignment":     config.ASSIGNMENT_BILLABLE,
        "aliases": [
            ("pdf_name",    "ZORZI, JARRETT"),
            ("travel_name", "Jarrett Zorzi"),
        ],
    },
    {
        "display_name":   "Zachary Ebbinghaus",
        "pdf_name":       "EBBINGHAUS, ZACHARY",
        "pdf_id":         "E8395",
        "centerline_id":  8395,
        "assignment":     config.ASSIGNMENT_BILLABLE,
        "aliases": [
            ("pdf_name",    "EBBINGHAUS, ZACHARY"),
            ("travel_name", "Zachary Ebbinghaus"),
        ],
    },
    # ---- Internal employees (bypass customer approval) ----
    {
        "display_name":   "Henry Andkilde",
        "pdf_name":       None,
        "pdf_id":         None,
        "centerline_id":  None,
        "assignment":     config.ASSIGNMENT_INTERNAL,
        "aliases": [
            ("display_name", "Henry Andkilde"),
            ("display_name", "Henry Andkilde "),   # trailing-space variant in timesheet
        ],
    },
    {
        "display_name":   "Matina Rahbar",
        "pdf_name":       None,
        "pdf_id":         None,
        "centerline_id":  None,
        "assignment":     config.ASSIGNMENT_INTERNAL,
        "aliases": [
            ("display_name", "Matina Rahbar"),
        ],
    },
]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed_employees(conn: sqlite3.Connection) -> None:
    """Insert the known employees and their aliases if they do not already exist.

    Safe to call on an already-seeded database — existing rows are skipped
    rather than updated, so manual edits made through the app are preserved.
    """
    for emp_data in _SEED_EMPLOYEES:
        # Check if this employee already exists
        existing = db.fetch_one(
            conn,
            "SELECT id FROM employees WHERE display_name = ?",
            (emp_data["display_name"],),
        )
        if existing:
            emp_id = existing["id"]
        else:
            cursor = conn.execute(
                """
                INSERT INTO employees
                    (display_name, pdf_name, pdf_id, centerline_id, active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (
                    emp_data["display_name"],
                    emp_data["pdf_name"],
                    emp_data["pdf_id"],
                    emp_data["centerline_id"],
                ),
            )
            emp_id = cursor.lastrowid

            # Insert initial assignment record (effective from project start)
            conn.execute(
                """
                INSERT INTO employee_assignments
                    (employee_id, customer_code, assignment_type, effective_start, notes)
                VALUES (?, ?, ?, '2020-01-01', 'Seeded at project kickoff')
                """,
                (
                    emp_id,
                    config.CENTERLINE_CUSTOMER_CODE if emp_data["assignment"] == config.ASSIGNMENT_BILLABLE else None,
                    emp_data["assignment"],
                ),
            )

        # Insert aliases — ignore conflicts (alias already registered)
        for alias_type, alias_value in emp_data["aliases"]:
            try:
                conn.execute(
                    """
                    INSERT INTO employee_aliases (employee_id, alias_type, alias_value)
                    VALUES (?, ?, ?)
                    """,
                    (emp_id, alias_type, alias_value),
                )
            except sqlite3.IntegrityError:
                # Alias already exists — skip
                pass

    conn.commit()


# ---------------------------------------------------------------------------
# Alias lookup
# ---------------------------------------------------------------------------

def find_employee_by_alias(
    conn: sqlite3.Connection,
    alias_value: str,
    alias_type: str | None = None,
) -> Optional[sqlite3.Row]:
    """Look up an employee by an exact alias value.

    Args:
        conn:         Open database connection.
        alias_value:  The alias string to search for (e.g. "TRIF, DANIEL").
        alias_type:   If provided, restricts the search to this alias type
                      (e.g. "pdf_name", "travel_name"). If None, searches all types.

    Returns:
        A Row from the employees table, or None if no exact match found.
    """
    alias_value_stripped = alias_value.strip()

    if alias_type:
        row = db.fetch_one(
            conn,
            """
            SELECT e.*
            FROM employees e
            JOIN employee_aliases a ON a.employee_id = e.id
            WHERE a.alias_type = ? AND a.alias_value = ?
            """,
            (alias_type, alias_value_stripped),
        )
    else:
        row = db.fetch_one(
            conn,
            """
            SELECT e.*
            FROM employees e
            JOIN employee_aliases a ON a.employee_id = e.id
            WHERE a.alias_value = ?
            """,
            (alias_value_stripped,),
        )

    return row


def fuzzy_find_employee(
    conn: sqlite3.Connection,
    name: str,
    alias_type: str | None = None,
    min_score: int = 80,
) -> tuple[Optional[sqlite3.Row], int, bool]:
    """Fuzzy-match a name against all known aliases.

    Always try find_employee_by_alias() before calling this — fuzzy matching
    is the fallback, not the default.

    Args:
        conn:       Open database connection.
        name:       Name string to match (e.g. "Trif, Daniel").
        alias_type: If provided, restricts to aliases of this type.
        min_score:  Minimum rapidfuzz score (0–100) to accept a match.

    Returns:
        A 3-tuple: (employee_row_or_None, score, is_ambiguous).
        - employee_row_or_None: The best matching employee, or None if no match
          above min_score.
        - score: The best score found (0 if no match).
        - is_ambiguous: True if two or more aliases scored within 5 points of
          the best score (indicating the match is uncertain).

    Raises:
        Nothing — ambiguity is reported via the return value, not an exception.
        The caller must decide what to do with an ambiguous match.
    """
    if alias_type:
        rows = db.fetch_all(
            conn,
            "SELECT employee_id, alias_value FROM employee_aliases WHERE alias_type = ?",
            (alias_type,),
        )
    else:
        rows = db.fetch_all(
            conn,
            "SELECT employee_id, alias_value FROM employee_aliases",
        )

    if not rows:
        return None, 0, False

    alias_map = {row["alias_value"]: row["employee_id"] for row in rows}
    choices = list(alias_map.keys())

    results = fuzz_process.extract(
        name.strip(),
        choices,
        scorer=fuzz.WRatio,
        limit=3,
    )

    if not results or results[0][1] < min_score:
        return None, 0, False

    best_match, best_score, _ = results[0]

    # Check for ambiguity: is there a second alias within 5 points?
    is_ambiguous = len(results) > 1 and (best_score - results[1][1]) <= 5

    employee_id = alias_map[best_match]
    employee = db.fetch_one(
        conn,
        "SELECT * FROM employees WHERE id = ?",
        (employee_id,),
    )

    return employee, best_score, is_ambiguous


# ---------------------------------------------------------------------------
# Employee management helpers
# ---------------------------------------------------------------------------

def add_employee(
    conn: sqlite3.Connection,
    *,
    display_name: str,
    pdf_name: str | None = None,
    pdf_id: str | None = None,
    centerline_id: int | None = None,
    assignment_type: str = config.ASSIGNMENT_BILLABLE,
    customer_code: str | None = config.CENTERLINE_CUSTOMER_CODE,
    effective_start: str = "2020-01-01",
) -> int:
    """Add a new employee and their initial assignment.

    Args:
        conn:             Open database connection.
        display_name:     Human-readable full name (e.g. "John Smith").
        pdf_name:         Name as it appears in the payroll PDF (e.g. "SMITH, JOHN").
        pdf_id:           Formatted employee ID (e.g. "E8022").
        centerline_id:    Numeric portion of the Centerline employee ID.
        assignment_type:  "billable" or "internal".
        customer_code:    Customer code for billable employees.
        effective_start:  ISO date string for when the assignment starts.

    Returns:
        The new employee's id.
    """
    cursor = conn.execute(
        """
        INSERT INTO employees (display_name, pdf_name, pdf_id, centerline_id, active)
        VALUES (?, ?, ?, ?, 1)
        """,
        (display_name, pdf_name, pdf_id, centerline_id),
    )
    emp_id = cursor.lastrowid

    conn.execute(
        """
        INSERT INTO employee_assignments
            (employee_id, customer_code, assignment_type, effective_start)
        VALUES (?, ?, ?, ?)
        """,
        (emp_id, customer_code, assignment_type, effective_start),
    )

    if pdf_name:
        conn.execute(
            "INSERT OR IGNORE INTO employee_aliases (employee_id, alias_type, alias_value) VALUES (?, 'pdf_name', ?)",
            (emp_id, pdf_name),
        )

    db.log_audit(
        conn,
        action="add_employee",
        entity_type="employees",
        entity_id=emp_id,
        new_value=display_name,
    )

    return emp_id


def add_alias(
    conn: sqlite3.Connection,
    employee_id: int,
    alias_type: str,
    alias_value: str,
) -> None:
    """Add an alias for an existing employee.

    Args:
        conn:         Open database connection.
        employee_id:  employees.id.
        alias_type:   One of: pdf_name | travel_name | receipt_name | expense_code | display_name
        alias_value:  The alias string.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO employee_aliases (employee_id, alias_type, alias_value)
        VALUES (?, ?, ?)
        """,
        (employee_id, alias_type, alias_value.strip()),
    )


def get_assignment_on_date(
    conn: sqlite3.Connection,
    employee_id: int,
    date: str,
) -> Optional[sqlite3.Row]:
    """Return the active employee_assignments row for a given date.

    Args:
        conn:         Open database connection.
        employee_id:  employees.id.
        date:         ISO date string (YYYY-MM-DD).

    Returns:
        The most recent assignment row effective on or before the given date,
        or None if no assignment exists.
    """
    return db.fetch_one(
        conn,
        """
        SELECT *
        FROM employee_assignments
        WHERE employee_id = ?
          AND effective_start <= ?
          AND (effective_end IS NULL OR effective_end >= ?)
        ORDER BY effective_start DESC
        LIMIT 1
        """,
        (employee_id, date, date),
    )
