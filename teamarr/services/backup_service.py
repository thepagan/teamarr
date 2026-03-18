"""Backup service for database backup operations.

Provides functionality for:
- Creating manual and scheduled backups
- Listing existing backups with metadata
- Deleting backups (with protection support)
- Protecting/unprotecting backups from rotation
- Rotating old backups based on max count
"""

import logging
import re
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BackupInfo:
    """Information about a backup file."""

    filename: str
    filepath: str
    size_bytes: int
    created_at: datetime
    is_protected: bool
    backup_type: str  # 'scheduled' or 'manual'


@dataclass
class BackupResult:
    """Result of a backup operation."""

    success: bool
    filename: str | None = None
    filepath: str | None = None
    size_bytes: int | None = None
    error: str | None = None


@dataclass
class RotationResult:
    """Result of backup rotation."""

    deleted_count: int
    deleted_files: list[str]
    kept_count: int
    protected_count: int


class BackupService:
    """Service for managing database backups.

    Backups are backend-native database copies stored in a configurable directory.
    Protected backups have a .protected marker file alongside them.

    Naming convention:
    - Scheduled: teamarr_scheduled_YYYYMMDD_HHMMSS.db
    - Manual: teamarr_manual_YYYYMMDD_HHMMSS.db
    - PostgreSQL manual/scheduled backups use .sql instead of .db
    """

    def __init__(
        self,
        db_factory: Callable[[], Any],
        backup_path: str = "./data/backups",
    ):
        """Initialize backup service.

        Args:
            db_factory: Factory function returning database connection context manager
            backup_path: Directory for storing backups
        """
        self._db_factory = db_factory
        self._backup_path = Path(backup_path)

    def _ensure_backup_dir(self) -> None:
        """Ensure backup directory exists."""
        self._backup_path.mkdir(parents=True, exist_ok=True)

    def _get_db_path(self) -> Path:
        """Get the current database file path."""
        from teamarr.database.connection import DEFAULT_DB_PATH

        return DEFAULT_DB_PATH

    def _is_postgres(self) -> bool:
        """Return whether the active backend is PostgreSQL."""
        from teamarr.database.connection import _is_postgres_url, get_database_url

        return _is_postgres_url(get_database_url())

    def _get_database_url(self) -> str | None:
        """Return the active DATABASE_URL, if any."""
        from teamarr.database.connection import get_database_url

        return get_database_url()

    def _get_backup_extension(self) -> str:
        """Return the backup file extension for the active backend."""
        return ".sql" if self._is_postgres() else ".db"

    def _generate_filename(self, backup_type: str) -> str:
        """Generate backup filename with timestamp.

        Args:
            backup_type: 'scheduled' or 'manual'

        Returns:
            Filename like 'teamarr_manual_20240115_143052.db' or '.sql'
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"teamarr_{backup_type}_{timestamp}{self._get_backup_extension()}"

    def _get_protected_marker_path(self, backup_path: Path) -> Path:
        """Get path to protection marker file.

        Args:
            backup_path: Path to backup file

        Returns:
            Path to .protected marker file
        """
        return backup_path.with_suffix(f"{backup_path.suffix}.protected")

    def _is_protected(self, backup_path: Path) -> bool:
        """Check if a backup is protected.

        Args:
            backup_path: Path to backup file

        Returns:
            True if protected
        """
        return self._get_protected_marker_path(backup_path).exists()

    def _parse_backup_filename(self, filename: str) -> tuple[str, datetime] | None:
        """Parse backup filename to extract type and timestamp.

        Args:
            filename: Backup filename

        Returns:
            Tuple of (backup_type, datetime) or None if invalid
        """
        if not filename.startswith("teamarr_"):
            return None
        suffix = Path(filename).suffix
        if suffix not in {".db", ".sql"}:
            return None

        try:
            # teamarr_TYPE_YYYYMMDD_HHMMSS.(db|sql)
            parts = Path(filename).stem[8:].split("_")
            if len(parts) < 3:
                return None

            backup_type = parts[0]
            if backup_type not in ("scheduled", "manual"):
                return None

            date_str = parts[1]
            time_str = parts[2]
            dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            return (backup_type, dt)
        except (ValueError, IndexError):
            return None

    def create_backup(self, manual: bool = True) -> BackupResult:
        """Create a new backup of the database.

        Args:
            manual: True for manual backup, False for scheduled

        Returns:
            BackupResult with success status and file info
        """
        self._ensure_backup_dir()

        backup_type = "manual" if manual else "scheduled"
        filename = self._generate_filename(backup_type)
        backup_filepath = self._backup_path / filename

        try:
            if self._is_postgres():
                self._create_postgres_backup(backup_filepath)
            else:
                self._create_sqlite_backup(backup_filepath)

            # Get file size
            size_bytes = backup_filepath.stat().st_size

            logger.info(
                "[BACKUP] Created %s backup: %s (%d bytes)",
                backup_type,
                filename,
                size_bytes,
            )

            return BackupResult(
                success=True,
                filename=filename,
                filepath=str(backup_filepath),
                size_bytes=size_bytes,
            )

        except Exception as e:
            logger.error("[BACKUP] Failed to create backup: %s", e)
            # Clean up partial backup if it exists
            if backup_filepath.exists():
                backup_filepath.unlink()
            return BackupResult(
                success=False,
                error=str(e),
            )

    def _create_sqlite_backup(self, backup_filepath: Path) -> None:
        """Create a SQLite file backup."""
        db_path = self._get_db_path()

        if not db_path.exists():
            raise FileNotFoundError(f"Database file not found: {db_path}")

        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(backup_filepath))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    def _create_postgres_backup(self, backup_filepath: Path) -> None:
        """Create a PostgreSQL SQL dump using pg_dump."""
        database_url = self._get_database_url()
        if not database_url:
            raise RuntimeError("DATABASE_URL is not configured for PostgreSQL backup")

        self._run_postgres_command(
            [
                "pg_dump",
                f"--file={backup_filepath}",
                f"--dbname={database_url}",
                "--format=plain",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
            ],
            action="create PostgreSQL backup",
        )

    def _run_postgres_command(self, command: list[str], *, action: str) -> None:
        """Run a PostgreSQL client command and raise a friendly error on failure."""
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            tool = Path(command[0]).name
            raise RuntimeError(
                f"{tool} is not installed in the Teamarr runtime. Install PostgreSQL client tools to {action}."
            ) from exc

        if result.returncode == 0:
            return

        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"Failed to {action}: {detail}")

    def list_backups(self) -> list[BackupInfo]:
        """List all backup files with metadata.

        Returns:
            List of BackupInfo sorted by creation time (newest first)
        """
        self._ensure_backup_dir()

        backups = []
        for pattern in ("teamarr_*.db", "teamarr_*.sql"):
            for file_path in self._backup_path.glob(pattern):
                parsed = self._parse_backup_filename(file_path.name)
                if not parsed:
                    continue

                backup_type, created_at = parsed

                try:
                    stat = file_path.stat()
                    backups.append(
                        BackupInfo(
                            filename=file_path.name,
                            filepath=str(file_path),
                            size_bytes=stat.st_size,
                            created_at=created_at,
                            is_protected=self._is_protected(file_path),
                            backup_type=backup_type,
                        )
                    )
                except OSError:
                    continue

        # Sort by creation time, newest first
        backups.sort(key=lambda b: b.created_at, reverse=True)
        return backups

    def delete_backup(self, filename: str, force: bool = False) -> bool:
        """Delete a backup file.

        Args:
            filename: Backup filename
            force: If True, delete even if protected

        Returns:
            True if deleted, False if not found or protected
        """
        backup_path = self._backup_path / filename

        if not backup_path.exists():
            logger.warning("[BACKUP] Backup not found: %s", filename)
            return False

        if not force and self._is_protected(backup_path):
            logger.warning("[BACKUP] Cannot delete protected backup: %s", filename)
            return False

        try:
            # Remove backup file
            backup_path.unlink()

            # Remove protection marker if exists
            marker_path = self._get_protected_marker_path(backup_path)
            if marker_path.exists():
                marker_path.unlink()

            logger.info("[BACKUP] Deleted backup: %s", filename)
            return True

        except OSError as e:
            logger.error("[BACKUP] Failed to delete backup %s: %s", filename, e)
            return False

    def protect_backup(self, filename: str) -> bool:
        """Protect a backup from rotation deletion.

        Args:
            filename: Backup filename

        Returns:
            True if protected, False if not found
        """
        backup_path = self._backup_path / filename

        if not backup_path.exists():
            logger.warning("[BACKUP] Backup not found: %s", filename)
            return False

        marker_path = self._get_protected_marker_path(backup_path)

        try:
            marker_path.touch()
            logger.info("[BACKUP] Protected backup: %s", filename)
            return True
        except OSError as e:
            logger.error("[BACKUP] Failed to protect backup %s: %s", filename, e)
            return False

    def unprotect_backup(self, filename: str) -> bool:
        """Remove protection from a backup.

        Args:
            filename: Backup filename

        Returns:
            True if unprotected, False if not found or not protected
        """
        backup_path = self._backup_path / filename

        if not backup_path.exists():
            logger.warning("[BACKUP] Backup not found: %s", filename)
            return False

        marker_path = self._get_protected_marker_path(backup_path)

        if not marker_path.exists():
            logger.debug("[BACKUP] Backup already unprotected: %s", filename)
            return True

        try:
            marker_path.unlink()
            logger.info("[BACKUP] Unprotected backup: %s", filename)
            return True
        except OSError as e:
            logger.error("[BACKUP] Failed to unprotect backup %s: %s", filename, e)
            return False

    def rotate_backups(self, max_count: int) -> RotationResult:
        """Delete oldest unprotected backups exceeding max count.

        Protected backups don't count toward the limit and are never deleted.

        Args:
            max_count: Maximum number of unprotected backups to keep

        Returns:
            RotationResult with deletion stats
        """
        backups = self.list_backups()

        # Separate protected and unprotected
        protected = [b for b in backups if b.is_protected]
        unprotected = [b for b in backups if not b.is_protected]

        # Unprotected are already sorted newest first
        to_delete = unprotected[max_count:]
        deleted_files = []

        for backup in to_delete:
            if self.delete_backup(backup.filename):
                deleted_files.append(backup.filename)

        result = RotationResult(
            deleted_count=len(deleted_files),
            deleted_files=deleted_files,
            kept_count=min(len(unprotected), max_count),
            protected_count=len(protected),
        )

        if deleted_files:
            logger.info(
                "[BACKUP] Rotation complete: deleted %d, kept %d, protected %d",
                result.deleted_count,
                result.kept_count,
                result.protected_count,
            )

        return result

    def restore_backup(self, filename: str) -> tuple[bool, str, str | None]:
        """Restore database from a backup file.

        Creates a pre-restore backup in the configured backup directory,
        validates the backup file is valid SQLite, then replaces the active DB.

        Args:
            filename: Backup filename to restore from

        Returns:
            Tuple of (success, message, pre_restore_backup_path)
        """
        backup_path = self._backup_path / filename
        if not backup_path.exists():
            return False, "Backup not found", None

        return self.restore_backup_from_path(backup_path)

    def restore_backup_from_path(self, backup_path: Path) -> tuple[bool, str, str | None]:
        """Restore the active database from a backup file path."""
        if self._is_postgres():
            if backup_path.suffix.lower() == ".db":
                return self._import_sqlite_backup_into_postgres(backup_path)
            return self._restore_postgres_backup(backup_path)
        return self._restore_sqlite_backup(backup_path)

    def _restore_sqlite_backup(self, backup_path: Path) -> tuple[bool, str, str | None]:
        """Restore the SQLite database from a backup file."""

        # Validate the backup is a valid SQLite database
        try:
            conn = sqlite3.connect(str(backup_path))
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            if result[0] != "ok":
                return False, f"Backup file failed integrity check: {result[0]}", None
        except sqlite3.DatabaseError as e:
            return False, f"Backup file is not a valid SQLite database: {e}", None

        db_path = self._get_db_path()

        # Create pre-restore backup in the configured backup directory
        pre_restore_path = None
        if db_path.exists():
            self._ensure_backup_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_path = self._backup_path / f"teamarr_pre_restore_{timestamp}.db"
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(str(pre_restore_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            logger.info("[RESTORE] Created pre-restore backup at %s", pre_restore_path)

        # Validate passes — copy backup to active DB path
        src = sqlite3.connect(str(backup_path))
        dst = sqlite3.connect(str(db_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        logger.info("[RESTORE] Database restored from %s", backup_path.name)
        return (
            True,
            "Database restored. Please restart the application for changes to take effect.",
            str(pre_restore_path) if pre_restore_path else None,
        )

    def _restore_postgres_backup(self, backup_path: Path) -> tuple[bool, str, str | None]:
        """Restore PostgreSQL from a SQL dump file."""
        if backup_path.suffix.lower() != ".sql":
            return False, "PostgreSQL restore requires a .sql backup file", None

        if not backup_path.exists() or backup_path.stat().st_size == 0:
            return False, "Backup file is empty or missing", None

        pre_restore_path = None
        try:
            self._ensure_backup_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_path = self._backup_path / f"teamarr_pre_restore_{timestamp}.sql"
            self._create_postgres_backup(pre_restore_path)
            logger.info("[RESTORE] Created pre-restore backup at %s", pre_restore_path)

            database_url = self._get_database_url()
            if not database_url:
                return False, "DATABASE_URL is not configured for PostgreSQL restore", None

            self._run_postgres_command(
                [
                    "psql",
                    f"--dbname={database_url}",
                    "--single-transaction",
                    "--set",
                    "ON_ERROR_STOP=1",
                    "--file",
                    str(backup_path),
                ],
                action="restore PostgreSQL backup",
            )
        except Exception as e:
            logger.error("[RESTORE] Failed to restore PostgreSQL backup %s: %s", backup_path.name, e)
            return False, str(e), str(pre_restore_path) if pre_restore_path else None

        logger.info("[RESTORE] PostgreSQL database restored from %s", backup_path.name)
        return (
            True,
            "Database restored. Please restart the application for changes to take effect.",
            str(pre_restore_path) if pre_restore_path else None,
        )

    def _import_sqlite_backup_into_postgres(self, backup_path: Path) -> tuple[bool, str, str | None]:
        """Import a SQLite Teamarr backup into the active PostgreSQL database."""
        try:
            source_conn = sqlite3.connect(str(backup_path))
            source_conn.row_factory = sqlite3.Row
        except sqlite3.DatabaseError as exc:
            return False, f"Invalid SQLite database: {exc}", None

        pre_restore_path = None
        try:
            settings_row = source_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
            ).fetchone()
            if not settings_row:
                return False, "Invalid backup file: missing required Teamarr tables", None

            self._ensure_backup_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_path = self._backup_path / f"teamarr_pre_restore_{timestamp}.sql"
            self._create_postgres_backup(pre_restore_path)
            logger.info("[RESTORE] Created pre-restore backup at %s", pre_restore_path)

            source_tables = self._get_sqlite_tables(source_conn)

            with self._db_factory() as conn:
                target_tables = self._get_postgres_tables(conn)
                common_tables = [table for table in source_tables if table in target_tables]

                self._truncate_postgres_tables(conn, target_tables)

                import_order = self._toposort_sqlite_tables(source_conn, common_tables)
                for table_name in import_order:
                    self._copy_sqlite_table_to_postgres(source_conn, conn, table_name)

                self._reset_postgres_sequences(conn, common_tables)
        except Exception as exc:
            logger.error("[RESTORE] Failed to import SQLite backup %s into PostgreSQL: %s", backup_path.name, exc)
            return False, str(exc), str(pre_restore_path) if pre_restore_path else None
        finally:
            source_conn.close()

        logger.info("[RESTORE] Imported SQLite backup %s into PostgreSQL", backup_path.name)
        return (
            True,
            "SQLite backup imported into PostgreSQL. Please restart the application for changes to take effect.",
            str(pre_restore_path) if pre_restore_path else None,
        )

    def _get_sqlite_tables(self, conn: sqlite3.Connection) -> list[str]:
        """Return user tables from a SQLite backup in stable schema order."""
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY rowid
            """
        ).fetchall()
        return [row["name"] for row in rows]

    def _get_postgres_tables(self, conn: Any) -> list[str]:
        """Return user tables in the active PostgreSQL schema."""
        rows = conn.execute(
            """
            SELECT tablename AS table_name
            FROM pg_catalog.pg_tables
            WHERE schemaname = current_schema()
            ORDER BY tablename
            """
        ).fetchall()
        return [row["table_name"] for row in rows]

    def _toposort_sqlite_tables(
        self,
        sqlite_conn: sqlite3.Connection,
        tables: list[str],
    ) -> list[str]:
        """Order tables so referenced parents are imported before children."""
        table_set = set(tables)
        deps: dict[str, set[str]] = {table: set() for table in tables}
        reverse_deps: dict[str, set[str]] = {table: set() for table in tables}

        for table in tables:
            pragma_table = table.replace('"', '""')
            fk_rows = sqlite_conn.execute(f'PRAGMA foreign_key_list("{pragma_table}")').fetchall()
            for fk in fk_rows:
                parent = fk["table"]
                if parent in table_set and parent != table:
                    deps[table].add(parent)
                    reverse_deps[parent].add(table)

        ready = sorted(table for table, parents in deps.items() if not parents)
        ordered: list[str] = []

        while ready:
            table = ready.pop(0)
            ordered.append(table)
            for child in sorted(reverse_deps[table]):
                deps[child].discard(table)
                if not deps[child] and child not in ordered and child not in ready:
                    ready.append(child)

        if len(ordered) != len(tables):
            remaining = [table for table in tables if table not in ordered]
            ordered.extend(remaining)

        return ordered

    def _truncate_postgres_tables(self, conn: Any, table_names: list[str]) -> None:
        """Remove all existing PostgreSQL data before restore/import."""
        if not table_names:
            return
        quoted_tables = ", ".join(self._quote_ident(table_name) for table_name in table_names)
        conn.execute(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE")

    def _copy_sqlite_table_to_postgres(
        self,
        source_conn: sqlite3.Connection,
        target_conn: Any,
        table_name: str,
    ) -> None:
        """Copy all rows from a SQLite table into PostgreSQL."""
        pragma_table = table_name.replace('"', '""')
        columns = [
            row["name"]
            for row in source_conn.execute(f'PRAGMA table_info("{pragma_table}")').fetchall()
        ]
        if not columns:
            return

        selected_columns = ", ".join(self._quote_ident(column_name) for column_name in columns)
        source_rows = source_conn.execute(
            f'SELECT {selected_columns} FROM "{pragma_table}"'
        ).fetchall()
        if not source_rows:
            return

        insert_columns = ", ".join(self._quote_ident(column_name) for column_name in columns)
        placeholders = ", ".join("?" for _ in columns)
        insert_sql = (
            f"INSERT INTO {self._quote_ident(table_name)} ({insert_columns}) "
            f"VALUES ({placeholders})"
        )
        target_conn.executemany(insert_sql, [tuple(row[column] for column in columns) for row in source_rows])

    def _reset_postgres_sequences(self, conn: Any, table_names: list[str]) -> None:
        """Reset PostgreSQL sequences to match imported explicit IDs."""
        for table_name in table_names:
            if not self._table_has_integer_id_column(conn, table_name):
                continue
            quoted_table = self._quote_ident(table_name)
            conn.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{table_name}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {quoted_table}), 1),
                    (SELECT COUNT(*) > 0 FROM {quoted_table})
                )
                WHERE pg_get_serial_sequence('{table_name}', 'id') IS NOT NULL
                """
            )

    def _table_has_integer_id_column(self, conn: Any, table_name: str) -> bool:
        """Return whether a PostgreSQL table has an integer-like id column."""
        row = conn.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ?
              AND column_name = 'id'
            """,
            (table_name,),
        ).fetchone()
        return bool(row and row["data_type"] in {"smallint", "integer", "bigint"})

    def _quote_ident(self, identifier: str) -> str:
        """Quote a SQL identifier for PostgreSQL/SQLite."""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
            raise ValueError(f"Invalid SQL identifier: {identifier}")
        return f'"{identifier}"'

    def get_backup_filepath(self, filename: str) -> Path | None:
        """Get full path to a backup file.

        Args:
            filename: Backup filename

        Returns:
            Path if exists, None otherwise
        """
        backup_path = self._backup_path / filename
        if backup_path.exists():
            return backup_path
        return None


def create_backup_service(
    db_factory: Callable[[], Any],
    backup_path: str | None = None,
) -> BackupService:
    """Factory function to create backup service.

    Args:
        db_factory: Database connection factory
        backup_path: Optional backup directory path (uses settings if None)

    Returns:
        Configured BackupService instance
    """
    if backup_path is None:
        # Get path from settings
        from teamarr.database.settings import get_backup_settings

        with db_factory() as conn:
            settings = get_backup_settings(conn)
            backup_path = settings.path

    return BackupService(db_factory, backup_path)
