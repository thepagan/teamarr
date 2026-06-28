"""Schema introspection helpers for backup restore.

Lives in the database layer so route handlers stay thin: they raise plain
exceptions (ValueError) and let the API layer convert to HTTP responses.
"""

import sqlite3
from pathlib import Path


def validate_backup_file(path: Path) -> None:
    """Validate an uploaded SQLite file is a Teamarr-shaped backup.

    Raises:
        ValueError: file is not a valid SQLite database, or is missing the
            required `settings` table (proxy for "this is one of ours").
    """
    try:
        conn = sqlite3.connect(str(path))
    except sqlite3.DatabaseError as e:
        raise ValueError(f"Invalid SQLite database: {e}") from e

    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        )
        if not cursor.fetchone():
            raise ValueError("Invalid backup file: missing required tables")
    finally:
        conn.close()
