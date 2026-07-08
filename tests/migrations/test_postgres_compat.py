from teamarr.database.postgres_compat import DBRow, PostgresConnectionWrapper, StaticCursorWrapper


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
