from contextlib import contextmanager
from types import SimpleNamespace

from teamarr.database import connection
from teamarr.database.postgres_compat import (
    DBRow,
    PostgresConnectionWrapper,
    PostgresCursorWrapper,
    StaticCursorWrapper,
)


def _wrapper_with_columns(columns: dict[str, dict[str, str]]) -> PostgresConnectionWrapper:
    wrapper = object.__new__(PostgresConnectionWrapper)
    wrapper._raw_connection = None
    wrapper._serial_pk_cache = {}
    wrapper._column_type_cache = columns
    return wrapper


def test_insert_literal_boolean_values_are_translated_for_postgres():
    wrapper = _wrapper_with_columns(
        {
            "stream_match_cache": {
                "fingerprint": "text",
                "event_id": "text",
                "match_method": "text",
                "user_corrected": "boolean",
            }
        }
    )

    translated = wrapper._translate_query(
        """
        INSERT INTO stream_match_cache
            (fingerprint, event_id, match_method, user_corrected)
        VALUES (?, ?, 'fuzzy', 0)
        ON CONFLICT (fingerprint)
        DO UPDATE SET
            match_method = excluded.match_method,
            user_corrected = 1
        WHERE user_corrected = 0
        """
    )

    assert "VALUES (%s, %s, 'fuzzy', FALSE)" in translated
    assert "user_corrected = TRUE" in translated
    assert "WHERE user_corrected = FALSE" in translated


def test_insert_boolean_translation_ignores_sql_line_comment_contents():
    wrapper = _wrapper_with_columns(
        {
            "stream_match_cache": {
                "fingerprint": "text",
                "user_corrected": "boolean",
            }
        }
    )

    translated = wrapper._translate_query(
        """
        INSERT INTO stream_match_cache (fingerprint, user_corrected) VALUES
            ('before', 0),
            -- Women's rows may mention ; RETURNING (anything) in prose.
            ('after', 1)
        ON CONFLICT (fingerprint) DO UPDATE SET user_corrected = 0
        """
    )

    assert "('before', FALSE)" in translated
    assert "('after', TRUE)" in translated
    assert "-- Women's rows may mention ; RETURNING (anything) in prose." in translated
    assert "ON CONFLICT (fingerprint) DO UPDATE SET user_corrected = FALSE" in translated


def test_static_cursor_wrapper_supports_sqlite_style_iteration():
    cursor = StaticCursorWrapper(
        [
            DBRow(["cid", "name"], [0, "id"]),
            DBRow(["cid", "name"], [1, "channel_number_locked"]),
        ]
    )

    cols = {row[1] for row in cursor}

    assert cols == {"id", "channel_number_locked"}
    assert cursor.fetchone() is None


def test_postgres_cursor_wrapper_supports_sqlite_style_iteration():
    class RawCursor:
        description = [("m3u_group_id",)]
        rowcount = 2

        def __init__(self):
            self.rows = iter([(10,), (20,)])

        def fetchone(self):
            return next(self.rows, None)

    cursor = PostgresCursorWrapper(None, RawCursor())

    group_ids = {row[0] for row in cursor}

    assert group_ids == {10, 20}
    assert cursor.fetchone() is None


def test_update_literal_boolean_values_are_translated_for_postgres():
    wrapper = _wrapper_with_columns(
        {
            "settings": {
                "id": "integer",
                "force_channel_relayout_pending": "boolean",
                "schema_version": "integer",
            }
        }
    )

    translated = wrapper._translate_query(
        """
        UPDATE settings
        SET force_channel_relayout_pending = 1,
            schema_version = 1
        WHERE id = 1
        """
    )

    assert "force_channel_relayout_pending = TRUE" in translated
    assert "schema_version = 1" in translated
    assert "WHERE id = 1" in translated


def test_boolean_coalesce_literals_are_translated_for_postgres():
    wrapper = _wrapper_with_columns(
        {
            "event_epg_groups": {
                "enabled": "boolean",
                "source_missing": "integer",
                "is_channel_source": "boolean",
            }
        }
    )

    translated = wrapper._translate_query(
        """
        SELECT id
        FROM event_epg_groups
        WHERE enabled = 1
          AND source_missing = 1
          AND COALESCE(is_channel_source, 0) = 0
        """
    )

    assert "enabled = TRUE" in translated
    assert "source_missing = 1" in translated
    assert "COALESCE(is_channel_source, FALSE) = FALSE" in translated


def test_qualified_upsert_boolean_guard_is_translated_for_postgres():
    wrapper = _wrapper_with_columns(
        {
            "stream_match_cache": {
                "fingerprint": "text",
                "event_id": "text",
                "user_corrected": "boolean",
            }
        }
    )

    translated = wrapper._translate_query(
        """
        INSERT INTO stream_match_cache
            (fingerprint, event_id, user_corrected)
        VALUES (?, ?, 0)
        ON CONFLICT (fingerprint)
        DO UPDATE SET
            event_id = excluded.event_id
        WHERE stream_match_cache.user_corrected = 0
        """
    )

    assert "VALUES (%s, %s, FALSE)" in translated
    assert "WHERE stream_match_cache.user_corrected = FALSE" in translated


def test_managed_team_channel_boolean_alias_is_translated_for_postgres():
    wrapper = _wrapper_with_columns(
        {
            "teams": {
                "id": "integer",
                "active": "boolean",
                "managed_channel_enabled": "boolean",
            },
            "managed_team_channels": {
                "team_id": "integer",
                "dispatcharr_channel_id": "integer",
            },
        }
    )

    translated = wrapper._translate_query(
        """
        SELECT t.id
        FROM teams t
        LEFT JOIN managed_team_channels mtc ON mtc.team_id = t.id
        WHERE t.managed_channel_enabled = 1 AND t.active = 1
        """
    )

    assert "t.managed_channel_enabled = TRUE" in translated
    assert "t.active = TRUE" in translated


def test_race_feed_boolean_update_and_insert_are_translated_for_postgres():
    wrapper = _wrapper_with_columns(
        {
            "race_feeds": {
                "league": "text",
                "feed_key": "text",
                "enabled": "boolean",
                "managed": "boolean",
            }
        }
    )

    update_sql = wrapper._translate_query(
        "UPDATE race_feeds SET enabled = 0 WHERE managed = 1"
    )
    insert_sql = wrapper._translate_query(
        """
        INSERT INTO race_feeds (league, feed_key, enabled, managed)
        VALUES (?, ?, 1, 1)
        """
    )

    assert "SET enabled = FALSE" in update_sql
    assert "WHERE managed = TRUE" in update_sql
    assert "VALUES (%s, %s, TRUE, TRUE)" in insert_sql


def test_null_safe_parameter_comparisons_are_translated_for_postgres():
    wrapper = _wrapper_with_columns({})

    translated = wrapper._translate_query(
        """
        UPDATE managed_channel_streams
        SET m3u_account_name = ?
        WHERE m3u_account_name IS NOT ?
          OR attach_at IS ?
          OR removed_at IS NOT NULL
        """
    )

    assert "m3u_account_name IS DISTINCT FROM %s" in translated
    assert "attach_at IS NOT DISTINCT FROM %s" in translated
    assert "removed_at IS NOT NULL" in translated


def test_postgres_init_runs_structural_migrations_before_schema(monkeypatch):
    calls = []

    class FakeConnection:
        def executescript(self, _script):
            calls.append("schema")

        def execute(self, _query, _params=None):
            return StaticCursorWrapper([])

        def commit(self):
            calls.append("commit")

    @contextmanager
    def fake_get_db(_db_path=None):
        yield FakeConnection()

    monkeypatch.setattr(connection, "get_database_url", lambda: "postgresql://test")
    monkeypatch.setattr(connection, "get_db", fake_get_db)
    monkeypatch.setattr(connection, "build_postgres_schema", lambda _sql: "SCHEMA")
    monkeypatch.setattr(
        connection,
        "run_pre_migrations",
        lambda _conn: calls.append("pre_migrations"),
    )
    monkeypatch.setattr(connection, "_normalize_postgres_schema", lambda _conn: None)
    monkeypatch.setattr(connection, "_run_migrations", lambda _conn: None)
    monkeypatch.setattr(connection, "_seed_tsdb_cache_if_needed", lambda _conn: None)
    monkeypatch.setattr(
        connection,
        "_maybe_auto_import_sqlite_into_postgres",
        lambda _conn, _path: None,
    )

    from teamarr.database import reconciliation

    monkeypatch.setattr(
        reconciliation,
        "reconcile_schema",
        lambda _conn, _sql: SimpleNamespace(
            columns_added=0, columns_by_table={}, errors=[]
        ),
    )

    connection.init_db()

    assert calls[:2] == ["pre_migrations", "schema"]
