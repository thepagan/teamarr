from teamarr.database.schema_postgres import build_postgres_schema


def test_league_upsert_boolean_values_with_parenthesized_strings():
    sqlite_schema = """
    CREATE TABLE leagues (
        league_code TEXT PRIMARY KEY,
        display_name TEXT,
        import_enabled INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1
    );

    INSERT OR REPLACE INTO leagues (
        league_code,
        display_name,
        import_enabled,
        enabled
    ) VALUES
        ('nbl', 'National Basketball League (Australia)', 1, 1),
        ('other', 'Other League', 0, 1);
    """

    postgres_schema = build_postgres_schema(sqlite_schema)

    assert "('nbl', 'National Basketball League (Australia)', TRUE, TRUE)" in postgres_schema
    assert "('other', 'Other League', FALSE, TRUE)" in postgres_schema
