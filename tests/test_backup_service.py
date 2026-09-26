"""Tests for BackupService, focused on path-traversal hardening.

The API routes validate filenames, but BackupService must independently refuse
to let a caller-supplied filename escape the backup directory (defence in depth
against CodeQL path-injection alerts #10-#25).
"""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from teamarr.services.backup_service import BackupService


@pytest.fixture
def backup_dir(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    return d


@pytest.fixture
def service(backup_dir):
    # db_factory is unused by the filename-handling paths under test.
    return BackupService(db_factory=lambda: None, backup_path=str(backup_dir))


def _make_backup_file(backup_dir: Path, name: str = "teamarr_manual_20240101_000000.db") -> Path:
    p = backup_dir / name
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.close()
    return p


@pytest.mark.parametrize("name", ["../secret.db", "../../etc/passwd", "/etc/passwd", "..", "."])
def test_resolve_backup_file_rejects_traversal(service, name):
    with pytest.raises(ValueError):
        service._resolve_backup_file(name)


def test_resolve_backup_file_accepts_plain_name(service, backup_dir):
    resolved = service._resolve_backup_file("teamarr_manual_20240101_000000.db")
    assert resolved.parent == backup_dir.resolve()
    assert resolved.name == "teamarr_manual_20240101_000000.db"


def test_delete_backup_rejects_traversal(service, backup_dir, tmp_path):
    # A real file outside the backup dir that a traversal name would target.
    outside = tmp_path / "outside.db"
    outside.write_text("keep me")

    assert service.delete_backup("../outside.db") is False
    assert outside.exists(), "traversal filename must not delete files outside backup dir"


def test_delete_backup_works_for_valid_name(service, backup_dir):
    _make_backup_file(backup_dir)
    assert service.delete_backup("teamarr_manual_20240101_000000.db") is True
    assert not (backup_dir / "teamarr_manual_20240101_000000.db").exists()


def test_get_backup_filepath_rejects_traversal(service, tmp_path):
    outside = tmp_path / "outside.db"
    outside.write_text("data")
    assert service.get_backup_filepath("../outside.db") is None


def test_protect_and_unprotect_reject_traversal(service):
    assert service.protect_backup("../secret.db") is False
    assert service.unprotect_backup("../secret.db") is False


def test_restore_backup_rejects_traversal(service):
    success, message, path = service.restore_backup("../../etc/passwd")
    assert success is False
    assert message == "Invalid backup filename"
    assert path is None


def test_postgres_export_creates_valid_portable_sqlite_database(
    backup_dir, tmp_path, monkeypatch
):
    schema_path = tmp_path / "schema.sql"
    schema_path.write_text(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            database_backend TEXT NOT NULL,
            enabled BOOLEAN NOT NULL,
            metadata JSON
        );
        CREATE TABLE children (
            id INTEGER PRIMARY KEY,
            settings_id INTEGER NOT NULL REFERENCES settings(id),
            happened_at TIMESTAMP,
            payload BLOB
        );
        """
    )
    monkeypatch.setattr("teamarr.services.backup_service.SCHEMA_PATH", schema_path)

    source_rows = {
        "settings": [
            {
                "id": 1,
                "database_backend": "postgresql",
                "enabled": True,
                "metadata": {"teams": ["Louisville"]},
            }
        ],
        "children": [
            {
                "id": 7,
                "settings_id": 1,
                "happened_at": datetime(2026, 9, 26, 12, 30, tzinfo=UTC),
                "payload": memoryview(b"data"),
            }
        ],
    }

    class Cursor:
        def __init__(self, rows=()):
            self._rows = list(rows)

        def fetchall(self):
            return self._rows

    class SourceConnection:
        def execute(self, query, params=None):
            normalized = " ".join(query.split())
            if normalized.startswith("BEGIN TRANSACTION"):
                return Cursor()
            if "FROM pg_catalog.pg_tables" in normalized:
                return Cursor(
                    [{"table_name": "settings"}, {"table_name": "children"}]
                )
            if "FROM information_schema.columns" in normalized:
                table = params[0]
                return Cursor(
                    [{"column_name": column} for column in source_rows[table][0]]
                )
            if 'FROM "settings"' in normalized:
                return Cursor(source_rows["settings"])
            if 'FROM "children"' in normalized:
                return Cursor(source_rows["children"])
            raise AssertionError(f"Unexpected SQL: {normalized}")

    @contextmanager
    def db_factory():
        yield SourceConnection()

    service = BackupService(db_factory=db_factory, backup_path=str(backup_dir))
    monkeypatch.setattr(service, "_is_postgres", lambda: True)

    result = service.create_sqlite_export()

    assert result.success is True
    assert result.filename and result.filename.startswith("teamarr_export_")
    assert result.filepath
    export_path = Path(result.filepath)
    assert export_path.with_suffix(".db.protected").exists()

    exported = sqlite3.connect(export_path)
    exported.row_factory = sqlite3.Row
    try:
        settings = exported.execute("SELECT * FROM settings").fetchone()
        child = exported.execute("SELECT * FROM children").fetchone()
        assert settings["database_backend"] == "sqlite"
        assert settings["enabled"] == 1
        assert settings["metadata"] == '{"teams": ["Louisville"]}'
        assert child["settings_id"] == 1
        assert child["happened_at"] == "2026-09-26T12:30:00+00:00"
        assert child["payload"] == b"data"
        assert exported.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert exported.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        exported.close()

    listed = service.list_backups()
    assert len(listed) == 1
    assert listed[0].backup_type == "export"
    assert listed[0].is_protected is True
