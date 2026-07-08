"""Database connection management.

Defaults to SQLite and switches to PostgreSQL when DATABASE_URL points to a
PostgreSQL backend.
"""

import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    import psycopg2
except Exception:  # pragma: no cover - optional dependency
    psycopg2 = None

from teamarr.database.migrations import _run_migrations, run_pre_migrations
from teamarr.database.postgres_compat import PostgresConnectionWrapper
from teamarr.database.schema_postgres import build_postgres_schema

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "teamarr.db"

# Schema file location
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def resolve_db_path(db_path: Path | str | None) -> Path:
    """Explicit argument > DATABASE_PATH env var > repo default.

    Read at call time (not import time) so tests can redirect the database
    with monkeypatch.setenv before touching any connection helper.
    """
    if db_path:
        return Path(db_path)
    env_path = os.environ.get("DATABASE_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def get_database_url() -> str | None:
    """Return DATABASE_URL from the environment if configured."""
    value = os.getenv("DATABASE_URL")
    return value.strip() if value else None


def _is_postgres_url(database_url: str | None) -> bool:
    """Check whether DATABASE_URL points to PostgreSQL."""
    if not database_url:
        return False
    lowered = database_url.lower()
    return lowered.startswith("postgres://") or lowered.startswith("postgresql://")


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection | Any:
    """Get a database connection.

    Args:
        db_path: Path to database file. Uses DATABASE_PATH env var or
            DEFAULT_DB_PATH if not specified.

    Returns:
        SQLite connection by default, or PostgreSQL wrapper when DATABASE_URL is configured.
    """
    database_url = get_database_url()
    if _is_postgres_url(database_url):
        if psycopg2 is None:
            raise RuntimeError(
                "DATABASE_URL points to PostgreSQL, but psycopg2 is not installed. "
                "Install a PostgreSQL driver before using this backend."
            )

        raw_conn = psycopg2.connect(database_url)
        raw_conn.autocommit = False
        return PostgresConnectionWrapper(raw_conn)

    path = resolve_db_path(db_path)

    # timeout=30: Wait up to 30 seconds if database is locked by another connection
    # check_same_thread=False: Allow connection to be used across threads (required for FastAPI)
    conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Enable Write-Ahead Logging for better concurrent access
    # WAL allows readers to not block writers and vice versa
    conn.execute("PRAGMA journal_mode=WAL")

    # Wait up to 30 seconds if a table is locked (milliseconds)
    conn.execute("PRAGMA busy_timeout=30000")

    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


@contextmanager
def get_db(db_path: Path | str | None = None) -> Generator[sqlite3.Connection | Any, None, None]:
    """Context manager for database connections.

    Usage:
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM teams")
            teams = cursor.fetchall()
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize database with schema.

    Creates tables if they don't exist. Safe to call multiple times.
    Also seeds TSDB cache from distributed seed file if needed.

    Args:
        db_path: Path to database file. Uses DEFAULT_DB_PATH if not specified.

    Raises:
        RuntimeError: If database file exists but is not a valid V2 database
    """
    path = resolve_db_path(db_path)
    database_url = get_database_url()

    if _is_postgres_url(database_url):
        sqlite_schema_sql = SCHEMA_PATH.read_text()
        schema_sql = build_postgres_schema(sqlite_schema_sql)

        with get_db(db_path) as conn:
            conn.executescript(schema_sql)
            _normalize_postgres_schema(conn)

            from teamarr.database.reconciliation import reconcile_schema

            result = reconcile_schema(conn, sqlite_schema_sql)
            if result.columns_added > 0:
                logger.info(
                    "[RECONCILE] Added %d missing columns across %d tables",
                    result.columns_added,
                    len(result.columns_by_table),
                )
            if result.errors:
                for err in result.errors:
                    logger.warning("[RECONCILE] %s", err)

            _run_migrations(conn)
            _seed_tsdb_cache_if_needed(conn)
            conn.execute("SELECT id FROM settings LIMIT 1")
            # PostgreSQL DDL is transactional. Commit before opening a second
            # connection for bootstrap import so the new schema is visible.
            conn.commit()
            _maybe_auto_import_sqlite_into_postgres(conn, path)

        logger.info("[DB] PostgreSQL schema initialized")
        return

    schema_sql = SCHEMA_PATH.read_text()
    try:
        with get_db(db_path) as conn:
            # First, verify this is a valid V2-compatible database by checking integrity
            # and querying a core table. This catches both corruption AND V1 databases.
            _verify_database_integrity(conn, path)

            # Structural pre-migrations (renames, table rebuilds) — these
            # can't be handled by reconciliation; see database/migrations/pre.py
            run_pre_migrations(conn)

            # ================================================================
            # Schema reconciliation — ensures ALL columns match schema.sql.
            # Replaces all individual _add_*_column_if_needed functions.
            # Adding a new column is now: just add it to schema.sql.
            # ================================================================
            from teamarr.database.reconciliation import reconcile_schema

            result = reconcile_schema(conn, schema_sql)
            if result.columns_added > 0:
                logger.info(
                    "[RECONCILE] Added %d missing columns across %d tables",
                    result.columns_added,
                    len(result.columns_by_table),
                )
            if result.errors:
                for err in result.errors:
                    logger.warning("[RECONCILE] %s", err)

            # Apply schema (creates tables if missing, INSERT OR REPLACE updates seed data)
            conn.executescript(schema_sql)
            # Run data migrations for existing databases
            _run_migrations(conn)
            # Seed TSDB cache if empty or incomplete
            _seed_tsdb_cache_if_needed(conn)

            # Final verification: ensure settings table exists and is queryable
            conn.execute("SELECT id FROM settings LIMIT 1")
    except sqlite3.DatabaseError as e:
        if "file is not a database" in str(e):
            logger.error(
                f"Database file '{path}' exists but is not compatible with Teamarr V2. "
                "This usually means you're trying to use a V1 database. "
                "V2 requires a fresh database - please either:\n"
                "  1. Use a different data directory for V2, or\n"
                "  2. Backup and delete the existing database file"
            )
            raise RuntimeError(
                f"Incompatible database file at '{path}'. "
                "V2 is not compatible with V1 databases. "
                "Please use a fresh data directory or delete the existing database."
            ) from e
        raise


def _verify_database_integrity(conn: sqlite3.Connection, path: Path) -> None:
    """Verify database is valid and compatible with V2.

    Catches:
    1. Corrupt database files ("file is not a database")
    2. V1 databases — V1 is no longer supported. The presence of V1-specific
       tables raises immediately with instructions to delete or relocate.

    Raises:
        RuntimeError: If database is a V1 database
        sqlite3.DatabaseError: If database file is corrupt
    """
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 100")
        existing_tables = {row["name"] for row in cursor.fetchall()}
    except sqlite3.DatabaseError:
        raise

    v1_indicators = {
        "schedule_cache",
        "league_config",
        "h2h_cache",
        "error_log",
        "soccer_cache_meta",
        "team_stats_cache",
    }
    v1_tables_found = v1_indicators & existing_tables

    if v1_tables_found:
        raise RuntimeError(
            f"Database file '{path}' is a V1 (Teamarr 1.x) database "
            f"(found V1-specific tables: {sorted(v1_tables_found)}). "
            "V1 is no longer supported. Move or delete the database file and "
            "restart Teamarr to initialize a fresh V2 database."
        )


def _normalize_postgres_schema(conn: Any) -> None:
    """Normalize PostgreSQL column types for legacy SQLite-style definitions."""
    if not getattr(conn, "dialect", None) == "postgres":
        return

    columns = conn.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'leagues'
          AND column_name IN ('enabled', 'import_enabled')
        """
    ).fetchall()

    for row in columns:
        if row["data_type"] == "integer":
            default_literal = "TRUE" if row["column_name"] == "enabled" else "FALSE"
            conn.execute(
                f"""
                ALTER TABLE leagues
                ALTER COLUMN {row["column_name"]} DROP DEFAULT
                """
            )
            conn.execute(
                f"""
                ALTER TABLE leagues
                ALTER COLUMN {row["column_name"]} TYPE BOOLEAN
                USING ({row["column_name"]} <> 0)
                """
            )
            conn.execute(
                f"""
                ALTER TABLE leagues
                ALTER COLUMN {row["column_name"]} SET DEFAULT {default_literal}
                """
            )


def _maybe_auto_import_sqlite_into_postgres(conn: Any, sqlite_path: Path) -> None:
    """Bootstrap an empty PostgreSQL DB from an existing SQLite DB if present."""
    try:
        if not sqlite_path.exists():
            return
        if not _postgres_is_bootstrap_empty(conn):
            return
    except Exception as exc:
        logger.debug("[DB] Skipping PostgreSQL bootstrap import check: %s", exc)
        return

    try:
        from teamarr.services.backup_service import create_backup_service

        logger.info("[DB] Empty PostgreSQL database detected; importing %s", sqlite_path)
        backup_service = create_backup_service(get_db)
        imported = backup_service.import_sqlite_database(sqlite_path, conn)
        logger.info("[DB] Imported %d rows from SQLite into PostgreSQL", imported)
    except Exception as exc:
        logger.warning("[DB] PostgreSQL bootstrap import failed: %s", exc)


def _postgres_is_bootstrap_empty(conn: Any) -> bool:
    """Return True if PostgreSQL has schema but no user data yet."""
    rows = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM teams) AS teams_count,
            (SELECT COUNT(*) FROM event_epg_groups) AS groups_count,
            (SELECT COUNT(*) FROM managed_channels) AS channels_count
        """
    ).fetchone()
    return bool(
        rows
        and rows["teams_count"] == 0
        and rows["groups_count"] == 0
        and rows["channels_count"] == 0
    )


def _seed_tsdb_cache_if_needed(conn: sqlite3.Connection) -> None:
    """Seed TSDB cache from distributed seed file if needed."""
    from teamarr.database.seed import seed_if_needed

    result = seed_if_needed(conn)
    if result and result.get("seeded"):
        logger.info(
            f"Seeded TSDB cache: {result.get('teams_added', 0)} teams, "
            f"{result.get('leagues_added', 0)} leagues"
        )




def reset_db(db_path: Path | str | None = None) -> None:
    """Reset database - drops all tables and reinitializes.

    WARNING: This deletes all data!

    Args:
        db_path: Path to database file. Uses DATABASE_PATH env var or
            DEFAULT_DB_PATH if not specified.
    """
    if _is_postgres_url(get_database_url()):
        with get_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = current_schema()
                """
            ).fetchall()
            for row in rows:
                conn.execute(f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE')

        init_db(db_path)
        return

    path = resolve_db_path(db_path)
    if path.exists():
        path.unlink()

    init_db(path)
