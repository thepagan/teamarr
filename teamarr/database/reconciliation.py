"""Schema reconciliation — ensures all table columns match schema.sql.

Uses an in-memory reference database created from schema.sql to determine
the expected schema, then adds any missing columns to the real database.
This eliminates the need for version-gated column additions in migrations.

Adding a new column is now: just add it to schema.sql's CREATE TABLE.
Reconciliation handles existing databases automatically on next startup.
"""

import logging
import sqlite3
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Tables to skip during reconciliation (internal/temporary)
_SKIP_TABLES = frozenset({"sqlite_sequence"})


@dataclass
class ReconcileResult:
    """Result of a schema reconciliation run."""

    tables_checked: int = 0
    columns_added: int = 0
    columns_by_table: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def reconcile_schema(
    conn: sqlite3.Connection, schema_sql: str
) -> ReconcileResult:
    """Ensure all table columns match schema.sql definitions.

    Creates an in-memory reference database from schema.sql, then compares
    each real table's columns against it. Missing columns are added via
    ALTER TABLE ADD COLUMN.

    Args:
        conn: Real database connection
        schema_sql: Contents of schema.sql

    Returns:
        ReconcileResult with counts and details
    """
    result = ReconcileResult()

    # Build reference schema in memory
    try:
        ref = sqlite3.connect(":memory:")
        ref.row_factory = sqlite3.Row
        ref.executescript(schema_sql)
    except Exception as e:
        logger.error("[RECONCILE] Failed to create reference schema: %s", e)
        result.errors.append(f"Reference schema failed: {e}")
        return result

    try:
        # Get tables from the real database
        real_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'"
            ).fetchall()
        }

        # Get tables from the reference
        ref_tables = {
            row[0]
            for row in ref.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'"
            ).fetchall()
        }

        # Only reconcile tables that exist in both
        common_tables = (real_tables & ref_tables) - _SKIP_TABLES

        for table in sorted(common_tables):
            result.tables_checked += 1
            added = _reconcile_table(conn, ref, table, result)
            if added:
                result.columns_by_table[table] = added
                result.columns_added += len(added)

    finally:
        ref.close()

    return result


def _reconcile_table(
    conn: sqlite3.Connection,
    ref: sqlite3.Connection,
    table: str,
    result: ReconcileResult,
) -> list[str]:
    """Reconcile a single table's columns against the reference.

    Returns list of column names that were added.
    """
    # Get actual columns
    actual_cols = {
        row["name"] for row in conn.execute(f"PRAGMA table_info([{table}])").fetchall()
    }
    if not actual_cols:
        return []  # Table exists but has no columns (shouldn't happen)

    # Get expected columns from reference
    ref_cols = ref.execute(f"PRAGMA table_info([{table}])").fetchall()

    added = []
    for col in ref_cols:
        col_name = col["name"]
        if col_name in actual_cols:
            continue

        # Build column definition for ALTER TABLE ADD COLUMN
        col_type = col["type"] or ""
        default = col["dflt_value"]

        col_def = col_type
        if default is not None:
            col_def += f" DEFAULT {default}"

        try:
            conn.execute(
                f"ALTER TABLE [{table}] ADD COLUMN [{col_name}] {col_def}"
            )
            added.append(col_name)
            logger.info(
                "[RECONCILE] Added %s.%s (%s)", table, col_name, col_def
            )
        except sqlite3.OperationalError as e:
            msg = f"Failed to add {table}.{col_name}: {e}"
            result.errors.append(msg)
            logger.warning("[RECONCILE] %s", msg)

    return added
