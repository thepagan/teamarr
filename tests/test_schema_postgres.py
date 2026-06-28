"""Tests for PostgreSQL schema conversion."""

from pathlib import Path

from teamarr.database.schema_postgres import build_postgres_schema


def test_league_upsert_ignores_semicolons_in_comments():
    schema_sql = (Path(__file__).parent.parent / "teamarr" / "database" / "schema.sql").read_text()

    postgres_sql = build_postgres_schema(schema_sql)

    f1_index = postgres_sql.index("('f1', 'espn', 'racing/f1'")
    conflict_index = postgres_sql.index("ON CONFLICT (league_code) DO UPDATE SET")
    stream_cache_index = postgres_sql.index("CREATE TABLE IF NOT EXISTS stream_match_cache")

    assert f1_index < conflict_index < stream_cache_index
    assert "enabled = EXCLUDED.enabled;" in postgres_sql
    assert "the others are seeded\nON CONFLICT" not in postgres_sql
