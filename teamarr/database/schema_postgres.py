"""Build PostgreSQL-compatible schema SQL from the canonical SQLite schema."""

from __future__ import annotations

import re


_TRIGGER_RE = re.compile(
    r"""
    CREATE\s+TRIGGER\s+IF\s+NOT\s+EXISTS\s+
    (?P<trigger>\w+)\s+
    AFTER\s+UPDATE\s+ON\s+(?P<table>\w+)\s+
    BEGIN\s+
    UPDATE\s+(?P=table)\s+SET\s+updated_at\s*=\s*CURRENT_TIMESTAMP\s+WHERE\s+id\s*=\s*NEW\.id;
    \s*END;
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)


def build_postgres_schema(sqlite_schema_sql: str) -> str:
    """Convert the SQLite schema file into PostgreSQL-compatible SQL."""
    schema_sql = sqlite_schema_sql
    trigger_defs: list[tuple[str, str]] = []

    def capture_trigger(match: re.Match[str]) -> str:
        trigger_defs.append((match.group("trigger"), match.group("table")))
        return ""

    schema_sql = _TRIGGER_RE.sub(capture_trigger, schema_sql)
    schema_sql = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        schema_sql,
        flags=re.IGNORECASE,
    )
    schema_sql = re.sub(r"\bBOOLEAN\s+DEFAULT\s+1\b", "BOOLEAN DEFAULT TRUE", schema_sql)
    schema_sql = re.sub(r"\bBOOLEAN\s+DEFAULT\s+0\b", "BOOLEAN DEFAULT FALSE", schema_sql)
    schema_sql = re.sub(r"\benabled\s+INTEGER\s+DEFAULT\s+1\b", "enabled BOOLEAN DEFAULT TRUE", schema_sql)
    schema_sql = re.sub(
        r"\bimport_enabled\s+INTEGER\s+DEFAULT\s+0\b",
        "import_enabled BOOLEAN DEFAULT FALSE",
        schema_sql,
    )
    schema_sql = _translate_schema_boolean_predicates(schema_sql)
    schema_sql = re.sub(r"(\w+)\s+COLLATE\s+NOCASE", r"LOWER(\1)", schema_sql)
    schema_sql = schema_sql.replace(" JSON DEFAULT ", " JSONB DEFAULT ")
    schema_sql = re.sub(r"\bJSON\b", "JSONB", schema_sql)
    schema_sql = _translate_insert_or_ignore(schema_sql)
    schema_sql = _translate_schema_upserts(schema_sql)

    prefix = """
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
""".strip()

    trigger_sql = "\n\n".join(
        f"""DROP TRIGGER IF EXISTS {trigger_name} ON {table_name};
CREATE TRIGGER {trigger_name}
BEFORE UPDATE ON {table_name}
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();"""
        for trigger_name, table_name in trigger_defs
    )

    parts = [prefix, schema_sql.strip()]
    if trigger_sql:
        parts.append(trigger_sql)
    return "\n\n".join(part for part in parts if part) + "\n"


def _translate_schema_boolean_predicates(sql: str) -> str:
    boolean_columns = {
        match.group(1)
        for match in re.finditer(r"^\s*(\w+)\s+BOOLEAN\b", sql, flags=re.IGNORECASE | re.MULTILINE)
    }
    translated = sql
    for column_name in boolean_columns:
        translated = re.sub(
            rf"\b{re.escape(column_name)}\s*=\s*1\b",
            f"{column_name} = TRUE",
            translated,
            flags=re.IGNORECASE,
        )
        translated = re.sub(
            rf"\b{re.escape(column_name)}\s*=\s*0\b",
            f"{column_name} = FALSE",
            translated,
            flags=re.IGNORECASE,
        )
    return translated


def _translate_insert_or_ignore(sql: str) -> str:
    return re.sub(
        r"INSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)(.*?);",
        lambda match: f"INSERT INTO {match.group(1)}{match.group(2)} ON CONFLICT DO NOTHING;",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _translate_schema_upserts(sql: str) -> str:
    replacements = {
        "sports": ("sport_code", ["display_name"]),
        "leagues": (
            "league_code",
            [
                "provider",
                "provider_league_id",
                "provider_league_name",
                "display_name",
                "sport",
                "logo_url",
                "logo_url_dark",
                "import_enabled",
                "league_alias",
                "league_id",
                "event_type",
                "gracenote_category",
                "fallback_provider",
                "fallback_league_id",
                "tsdb_tier",
            ],
        ),
    }

    for table_name, (conflict_target, update_columns) in replacements.items():
        sql = re.sub(
            rf"INSERT\s+OR\s+REPLACE\s+INTO\s+{table_name}\s*\((?P<columns>.*?)\)\s*VALUES\s*(?P<values>.*?);",
            lambda match: _build_upsert_sql(
                table_name,
                match.group("columns"),
                match.group("values"),
                conflict_target,
                update_columns,
            ),
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )

    return sql


def _build_upsert_sql(
    table_name: str,
    columns_sql: str,
    values_sql: str,
    conflict_target: str,
    update_columns: list[str],
) -> str:
    set_sql = ",\n    ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    return (
        f"INSERT INTO {table_name} ({columns_sql}) VALUES {values_sql}\n"
        f"ON CONFLICT ({conflict_target}) DO UPDATE SET\n    {set_sql};"
    )
