"""
db.py — Database connection, initialization, and low-level helpers.

Design rules:
  - Every public function accepts a connection as its first argument.
    Callers control transaction scope; nothing auto-commits here.
  - Row factory is set to sqlite3.Row so callers can access columns by name.
  - Schema setup is idempotent (CREATE TABLE IF NOT EXISTS).
  - Migrations are plain numbered SQL files in database/migrations/.
"""

import hashlib
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from payroll_app import config


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    """Open and return a connection to the application database.

    The connection has:
      - Row factory set to sqlite3.Row (column access by name)
      - Foreign key enforcement enabled

    The caller is responsible for calling conn.commit() or conn.rollback()
    and conn.close() when done.
    """
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------

def initialize_database(conn: sqlite3.Connection) -> None:
    """Run schema.sql against the database, then apply any in-code migrations.

    Safe to call on an already-initialized database because all CREATE TABLE
    statements use IF NOT EXISTS.  Column additions use ALTER TABLE with a
    try/except to silently skip columns that already exist.
    """
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()

    # ---------------------------------------------------------------------------
    # In-code migrations — add columns that may not exist in older databases.
    # SQLite raises OperationalError("duplicate column name: ...") if the column
    # already exists; we catch and ignore that specific error.
    # ---------------------------------------------------------------------------
    _new_columns = [
        ("weekly_employee_verification", "timesheet_week_sick",        "DECIMAL NOT NULL DEFAULT 0"),
        ("weekly_employee_verification", "timesheet_week_vacation",    "DECIMAL NOT NULL DEFAULT 0"),
        ("weekly_employee_verification", "timesheet_week_holiday",     "DECIMAL NOT NULL DEFAULT 0"),
        ("weekly_employee_verification", "timesheet_week_nonbillable", "DECIMAL NOT NULL DEFAULT 0"),
    ]
    for table, column, definition in _new_columns:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists — nothing to do.
            pass


# ---------------------------------------------------------------------------
# Source file registration
# ---------------------------------------------------------------------------

def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file.

    Args:
        path: Path to the file.

    Returns:
        Lowercase hex string of the SHA-256 digest.
    """
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def store_source_file(
    conn: sqlite3.Connection,
    *,
    source_path: Path,
    file_type: str,
    original_name: str,
    normalized_name: str | None = None,
    supersedes_id: int | None = None,
    edit_label: str | None = None,
) -> int:
    """Copy a file into the source-file store and register it in the DB.

    The file is copied into the appropriate subdirectory under SOURCE_FILES_DIR.
    A SHA-256 hash is computed before the copy to detect duplicates.

    Args:
        conn:             Open database connection.
        source_path:      Path to the original file on disk.
        file_type:        One of: payroll_pdf | travel_pdf | timesheet | receipt
        original_name:    The file's original (incoming) filename.
        normalized_name:  The internal normalized filename (e.g. R&D_260329-xxxxx.pdf).
        supersedes_id:    source_files.id of the file this one replaces (for edits).
        edit_label:       Short label for owner-edit copies, e.g. "DrewEdit".

    Returns:
        The source_files.id of the newly registered record.

    Raises:
        ValueError: If file_type is not recognized.
        FileNotFoundError: If source_path does not exist.
    """
    valid_types = {"payroll_pdf", "travel_pdf", "timesheet", "receipt"}
    if file_type not in valid_types:
        raise ValueError(f"Unknown file_type {file_type!r}. Must be one of {valid_types}")

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # Determine destination directory
    dest_dir_map = {
        "payroll_pdf": config.PAYROLL_PDF_DIR,
        "travel_pdf":  config.TRAVEL_PDF_DIR,
        "timesheet":   config.TIMESHEET_DIR,
        "receipt":     config.RECEIPT_DIR,
    }
    dest_dir = dest_dir_map[file_type]
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Use normalized name for storage if provided, else original name
    stored_filename = normalized_name or original_name
    dest_path = dest_dir / stored_filename

    # If a file with the same normalized name already exists, suffix with timestamp
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_path = dest_dir / f"{stem}_{timestamp}{suffix}"

    sha256 = hash_file(source_path)
    shutil.copy2(str(source_path), str(dest_path))

    cursor = conn.execute(
        """
        INSERT INTO source_files
            (file_type, original_name, normalized_name, path, sha256,
             supersedes_source_file_id, edit_label)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_type,
            original_name,
            normalized_name,
            str(dest_path),
            sha256,
            supersedes_id,
            edit_label,
        ),
    )
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------

def log_audit(
    conn: sqlite3.Connection,
    *,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    """Insert a row into audit_log.

    Args:
        conn:         Open database connection.
        action:       Short verb describing what happened (e.g. "override_hours").
        entity_type:  Name of the DB table (e.g. "reconciliation").
        entity_id:    Primary key of the affected row, if applicable.
        old_value:    Previous value (serialized as string), if applicable.
        new_value:    New value (serialized as string), if applicable.
    """
    conn.execute(
        """
        INSERT INTO audit_log (action, entity_type, entity_id, old_value, new_value)
        VALUES (?, ?, ?, ?, ?)
        """,
        (action, entity_type, entity_id, old_value, new_value),
    )


# ---------------------------------------------------------------------------
# Generic row fetchers (thin wrappers, keep SQL readable)
# ---------------------------------------------------------------------------

def fetch_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> sqlite3.Row | None:
    """Execute a SELECT and return the first row, or None."""
    return conn.execute(sql, params).fetchone()


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Execute a SELECT and return all rows."""
    return conn.execute(sql, params).fetchall()
