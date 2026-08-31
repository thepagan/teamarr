"""Build PostgreSQL-compatible schema SQL from the canonical SQLite schema."""

from __future__ import annotations

import re
from collections.abc import Callable


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
        "sports": ("sport_code", ["display_name"], []),
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
                "enabled",
            ],
            ["import_enabled", "enabled"],
        ),
    }

    for table_name, (conflict_target, update_columns, boolean_columns) in replacements.items():
        sql = _translate_table_upserts(
            sql,
            table_name,
            conflict_target,
            update_columns,
            boolean_columns,
        )

    return sql


def _translate_table_upserts(
    sql: str,
    table_name: str,
    conflict_target: str,
    update_columns: list[str],
    boolean_columns: list[str],
) -> str:
    pattern = re.compile(
        rf"INSERT\s+OR\s+REPLACE\s+INTO\s+{table_name}\s*"
        r"\((?P<columns>.*?)\)\s*VALUES",
        flags=re.IGNORECASE | re.DOTALL,
    )
    output: list[str] = []
    cursor = 0

    while match := pattern.search(sql, cursor):
        values_start = match.end()
        statement_end = _find_sql_statement_end(sql, values_start)
        values_sql = sql[values_start:statement_end].strip()
        replacement = _build_upsert_sql(
            table_name,
            match.group("columns"),
            values_sql,
            conflict_target,
            update_columns,
            boolean_columns,
        )
        output.append(sql[cursor:match.start()])
        output.append(replacement)
        cursor = statement_end + 1

    output.append(sql[cursor:])
    return "".join(output)


def _find_sql_statement_end(sql: str, start: int) -> int:
    in_single = False
    in_double = False
    in_line_comment = False
    i = start

    while i < len(sql):
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < len(sql) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            i += 1
            continue

        if not in_single and not in_double and char == "-" and next_char == "-":
            in_line_comment = True
            i += 2
            continue

        if char == "'" and not in_double:
            if in_single and next_char == "'":
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue

        if char == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if char == ";" and not in_single and not in_double:
            return i

        i += 1

    raise ValueError("Unterminated INSERT OR REPLACE statement in schema.sql")


def _build_upsert_sql(
    table_name: str,
    columns_sql: str,
    values_sql: str,
    conflict_target: str,
    update_columns: list[str],
    boolean_columns: list[str],
) -> str:
    columns = [column.strip() for column in columns_sql.split(",")]
    translated_values = _translate_upsert_boolean_values(values_sql, columns, set(boolean_columns))
    set_sql = ",\n    ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    return (
        f"INSERT INTO {table_name} ({columns_sql}) VALUES {translated_values}\n"
        f"ON CONFLICT ({conflict_target}) DO UPDATE SET\n    {set_sql};"
    )


def _translate_upsert_boolean_values(
    values_sql: str,
    columns: list[str],
    boolean_columns: set[str],
) -> str:
    if not boolean_columns:
        return values_sql

    boolean_indexes = {index for index, column in enumerate(columns) if column in boolean_columns}
    if not boolean_indexes:
        return values_sql

    def translate_tuple(inner: str) -> str:
        parts = _split_sql_csv(inner)
        for index in boolean_indexes:
            if index >= len(parts):
                continue
            token = parts[index].strip()
            if token == "1":
                parts[index] = "TRUE"
            elif token == "0":
                parts[index] = "FALSE"
        return "(" + ", ".join(parts) + ")"

    return _rewrite_top_level_value_tuples(values_sql, translate_tuple)


def _rewrite_top_level_value_tuples(
    values_sql: str,
    translate_tuple: Callable[[str], str],
) -> str:
    output: list[str] = []
    i = 0
    in_line_comment = False

    while i < len(values_sql):
        char = values_sql[i]
        next_char = values_sql[i + 1] if i + 1 < len(values_sql) else ""

        if in_line_comment:
            output.append(char)
            if char == "\n":
                in_line_comment = False
            i += 1
            continue

        if char == "-" and next_char == "-":
            output.extend((char, next_char))
            in_line_comment = True
            i += 2
            continue

        if values_sql[i] != "(":
            output.append(values_sql[i])
            i += 1
            continue

        start = i
        depth = 0
        in_single = False
        in_double = False
        in_line_comment = False

        while i < len(values_sql):
            char = values_sql[i]
            next_char = values_sql[i + 1] if i + 1 < len(values_sql) else ""

            if in_line_comment:
                if char == "\n":
                    in_line_comment = False
                i += 1
                continue

            if not in_single and not in_double and char == "-" and next_char == "-":
                in_line_comment = True
                i += 2
                continue

            if char == "'" and not in_double:
                if in_single and next_char == "'":
                    i += 2
                    continue
                in_single = not in_single
                i += 1
                continue

            if char == '"' and not in_single:
                in_double = not in_double
                i += 1
                continue

            if not in_single and not in_double:
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        output.append(translate_tuple(values_sql[start + 1 : i]))
                        i += 1
                        break

            i += 1
        else:
            output.append(values_sql[start:])
            break

    return "".join(output)


def _split_sql_csv(sql: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False

    for char in sql:
        if char == "'" and not in_double:
            in_single = not in_single
            current.append(char)
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            current.append(char)
            continue
        if char == "," and not in_single and not in_double:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)

    if current:
        parts.append("".join(current).strip())

    return parts
