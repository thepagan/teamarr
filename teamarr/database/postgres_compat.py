"""PostgreSQL compatibility helpers for the SQLite-oriented database layer."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import date, datetime, time
from typing import Any

_INSERT_TABLE_RE = re.compile(r"^\s*INSERT\s+INTO\s+(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
_PRAGMA_TABLE_INFO_RE = re.compile(r"^\s*PRAGMA\s+table_info\((?P<table>[^)]+)\)\s*$", re.IGNORECASE)
_SQLITE_MASTER_TABLE_RE = re.compile(
    r"""
    ^\s*SELECT\s+(?P<select>.+?)
    \s+FROM\s+sqlite_master
    \s+WHERE\s+type\s*=\s*'table'
    (?:\s+AND\s+name\s*=\s*(?P<name>('([^']|\\')*')|\?))?
    .*$
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


class DBRow(Mapping[str, Any]):
    """sqlite3.Row-like mapping with integer access."""

    def __init__(self, columns: Sequence[str], values: Sequence[Any]):
        self._columns = list(columns)
        self._values = [_normalize_value(value) for value in values]
        self._by_name = {column: idx for idx, column in enumerate(self._columns)}

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._by_name[key]]

    def __iter__(self) -> Iterator[str]:
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)

    def keys(self):
        return self._columns

    def get(self, key: str, default: Any = None) -> Any:
        return self[key] if key in self._by_name else default


class StaticCursorWrapper:
    """Cursor wrapper for emulated metadata queries."""

    def __init__(self, rows: list[DBRow]):
        self._rows = rows
        self._index = 0
        self.rowcount = len(rows)
        self.lastrowid = None
        self.description = None

    def fetchone(self) -> DBRow | None:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self) -> list[DBRow]:
        rows = self._rows[self._index :]
        self._index = len(self._rows)
        return rows

    def fetchmany(self, size: int | None = None) -> list[DBRow]:
        size = size or 1
        rows = self._rows[self._index : self._index + size]
        self._index += len(rows)
        return rows

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class PostgresCursorWrapper:
    """sqlite-style cursor adapter for psycopg2 cursors."""

    def __init__(self, connection: "PostgresConnectionWrapper", cursor: Any):
        self._connection = connection
        self._cursor = cursor
        self.lastrowid = None

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def execute(self, query: str, params: Sequence[Any] | None = None):
        meta_cursor = self._connection._maybe_handle_sqlite_metadata(query, params)
        if meta_cursor is not None:
            return meta_cursor

        translated = self._connection._translate_query(
            query,
            translate_placeholders=params is not None,
        )

        if params is None:
            self._cursor.execute(translated)
        else:
            self._cursor.execute(translated, tuple(params))

        if query.lstrip().upper().startswith("INSERT"):
            self.lastrowid = self._connection._fetch_lastrowid(self._cursor, query)

        return self

    def executemany(self, query: str, param_sets: Iterable[Sequence[Any]]):
        param_sets = list(param_sets)
        translated = self._connection._translate_query(
            query,
            translate_placeholders=bool(param_sets),
        )
        self._cursor.executemany(translated, param_sets)
        self.lastrowid = None
        return self

    def fetchone(self) -> DBRow | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in self._cursor.description or ()]
        return DBRow(columns, row)

    def fetchall(self) -> list[DBRow]:
        rows = self._cursor.fetchall()
        if not rows:
            return []
        columns = [desc[0] for desc in self._cursor.description or ()]
        return [DBRow(columns, row) for row in rows]

    def fetchmany(self, size: int | None = None) -> list[DBRow]:
        rows = self._cursor.fetchmany(size)
        if not rows:
            return []
        columns = [desc[0] for desc in self._cursor.description or ()]
        return [DBRow(columns, row) for row in rows]

    def close(self) -> None:
        self._cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class PostgresConnectionWrapper:
    """sqlite-like adapter on top of a psycopg2 connection."""

    dialect = "postgres"

    def __init__(self, raw_connection: Any):
        self._raw_connection = raw_connection
        self._serial_pk_cache: dict[str, bool] = {}
        self._column_type_cache: dict[str, dict[str, str]] | None = None

    def cursor(self) -> PostgresCursorWrapper:
        return PostgresCursorWrapper(self, self._raw_connection.cursor())

    def execute(self, query: str, params: Sequence[Any] | None = None):
        cursor = self.cursor()
        return cursor.execute(query, params)

    def executemany(self, query: str, param_sets: Iterable[Sequence[Any]]):
        cursor = self.cursor()
        return cursor.executemany(query, param_sets)

    def executescript(self, script: str):
        cursor = self.cursor()
        cursor.execute(script)
        return cursor

    def commit(self) -> None:
        self._raw_connection.commit()

    def rollback(self) -> None:
        self._raw_connection.rollback()

    def close(self) -> None:
        self._raw_connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()
        return False

    def __getattr__(self, item: str) -> Any:
        return getattr(self._raw_connection, item)

    def _fetch_lastrowid(self, cursor: Any, query: str) -> int | None:
        if cursor.rowcount <= 0:
            return None

        match = _INSERT_TABLE_RE.match(query)
        if not match:
            return None

        table_name = match.group("table")
        if not self._table_has_serial_primary_key(table_name):
            return None

        try:
            cursor.execute("SELECT LASTVAL()")
            row = cursor.fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None

    def _table_has_serial_primary_key(self, table_name: str) -> bool:
        cached = self._serial_pk_cache.get(table_name)
        if cached is not None:
            return cached

        with self._raw_connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = %s
                      AND column_name = 'id'
                      AND column_default LIKE 'nextval%%'
                )
                """,
                (table_name,),
            )
            result = bool(cur.fetchone()[0])

        self._serial_pk_cache[table_name] = result
        return result

    def _get_column_types(self) -> dict[str, dict[str, str]]:
        if self._column_type_cache is not None:
            return self._column_type_cache

        with self._raw_connection.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                """
            )
            column_types: dict[str, dict[str, str]] = {}
            for table_name, column_name, data_type in cur.fetchall():
                column_types.setdefault(table_name, {})[column_name] = data_type
            self._column_type_cache = column_types

        return self._column_type_cache

    def _maybe_handle_sqlite_metadata(
        self,
        query: str,
        params: Sequence[Any] | None,
    ) -> StaticCursorWrapper | None:
        stripped = query.strip()
        upper = stripped.upper()

        if upper.startswith("PRAGMA JOURNAL_MODE") or upper.startswith("PRAGMA BUSY_TIMEOUT"):
            return StaticCursorWrapper([])
        if upper.startswith("PRAGMA FOREIGN_KEYS"):
            return StaticCursorWrapper([])
        if upper == "PRAGMA INTEGRITY_CHECK":
            return StaticCursorWrapper([DBRow(["integrity_check"], ["ok"])])

        pragma_match = _PRAGMA_TABLE_INFO_RE.match(stripped)
        if pragma_match:
            table_name = pragma_match.group("table").strip("'\"")
            return self._table_info_cursor(table_name)

        sqlite_master_match = _SQLITE_MASTER_TABLE_RE.match(stripped)
        if sqlite_master_match:
            name_expr = sqlite_master_match.group("name")
            table_name = None
            if name_expr == "?" and params:
                table_name = str(params[0])
            elif name_expr:
                table_name = name_expr.strip("'")
            return self._sqlite_master_cursor(sqlite_master_match.group("select"), table_name)

        return None

    def _table_info_cursor(self, table_name: str) -> StaticCursorWrapper:
        with self._raw_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default,
                    c.ordinal_position,
                    EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON tc.constraint_name = kcu.constraint_name
                         AND tc.table_schema = kcu.table_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_schema = c.table_schema
                          AND tc.table_name = c.table_name
                          AND kcu.column_name = c.column_name
                    )
                FROM information_schema.columns c
                WHERE c.table_schema = current_schema()
                  AND c.table_name = %s
                ORDER BY c.ordinal_position
                """,
                (table_name,),
            )
            rows = cur.fetchall()

        wrapped = [
            DBRow(
                ["cid", "name", "type", "notnull", "dflt_value", "pk"],
                [ordinal - 1, name, data_type, 0 if is_nullable == "YES" else 1, default, 1 if is_pk else 0],
            )
            for name, data_type, is_nullable, default, ordinal, is_pk in rows
        ]
        return StaticCursorWrapper(wrapped)

    def _sqlite_master_cursor(self, select_expr: str, table_name: str | None) -> StaticCursorWrapper:
        select_expr = " ".join(select_expr.split()).upper()
        if table_name is None:
            with self._raw_connection.cursor() as cur:
                cur.execute(
                    """
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = current_schema()
                    ORDER BY tablename
                    LIMIT 100
                    """
                )
                names = [row[0] for row in cur.fetchall()]
            return StaticCursorWrapper([DBRow(["name"], [name]) for name in names])

        with self._raw_connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = current_schema()
                      AND tablename = %s
                )
                """,
                (table_name,),
            )
            exists = bool(cur.fetchone()[0])

        if select_expr == "NAME":
            return StaticCursorWrapper([DBRow(["name"], [table_name])] if exists else [])
        if select_expr.startswith("COUNT(*)"):
            return StaticCursorWrapper([DBRow(["COUNT(*)"], [1 if exists else 0])])
        return StaticCursorWrapper([])

    def _translate_query(self, query: str, *, translate_placeholders: bool = True) -> str:
        translated = query
        translated = _translate_insert_or_ignore(translated)
        translated = _translate_datetime_calls(translated)
        translated = _translate_group_concat(translated)
        translated = translated.replace(
            "strftime('%Y-%m-%d %H:%M', started_at)",
            "TO_CHAR(started_at, 'YYYY-MM-DD HH24:MI')",
        )
        translated = self._translate_boolean_comparisons(translated)
        if translate_placeholders:
            translated = _translate_placeholders(translated)
        return translated

    def _translate_boolean_comparisons(self, query: str) -> str:
        aliases = self._extract_query_tables(query)

        def replace_qualified(match: re.Match[str]) -> str:
            alias = match.group("alias")
            column = match.group("column")
            operator = match.group("operator")
            value = match.group("value")
            table_name = aliases.get(alias.lower())
            if table_name is None:
                return match.group(0)
            translated_value = self._translate_boolean_literal(table_name, column, value)
            if translated_value is None:
                return match.group(0)
            return f"{alias}.{column} {operator} {translated_value}"

        def replace_unqualified(match: re.Match[str]) -> str:
            column = match.group("column")
            operator = match.group("operator")
            value = match.group("value")
            table_name = self._resolve_unqualified_table(column, aliases)
            if table_name is None:
                return match.group(0)
            translated_value = self._translate_boolean_literal(table_name, column, value)
            if translated_value is None:
                return match.group(0)
            return f"{column} {operator} {translated_value}"

        translated = re.sub(
            r"(?P<alias>[a-zA-Z_][a-zA-Z0-9_]*)\.(?P<column>[a-zA-Z_][a-zA-Z0-9_]*)\s*"
            r"(?P<operator>=|!=|<>)\s*(?P<value>TRUE|FALSE|0|1)\b",
            replace_qualified,
            query,
            flags=re.IGNORECASE,
        )
        translated = re.sub(
            r"(?<!\.)\b(?P<column>[a-zA-Z_][a-zA-Z0-9_]*)\s*"
            r"(?P<operator>=|!=|<>)\s*(?P<value>TRUE|FALSE|0|1)\b",
            replace_unqualified,
            translated,
            flags=re.IGNORECASE,
        )
        return translated

    def _extract_query_tables(self, query: str) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for match in re.finditer(
            r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([a-zA-Z_][a-zA-Z0-9_]*)"
            r"(?:\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?",
            query,
            flags=re.IGNORECASE,
        ):
            table_name = match.group(1)
            alias = match.group(2) or table_name
            aliases[table_name.lower()] = table_name
            aliases[alias.lower()] = table_name
        return aliases

    def _resolve_unqualified_table(self, column_name: str, aliases: dict[str, str]) -> str | None:
        candidate_tables = {
            table_name
            for table_name in set(aliases.values())
            if column_name in self._get_column_types().get(table_name, {})
        }
        if len(candidate_tables) == 1:
            return next(iter(candidate_tables))
        return None

    def _translate_boolean_literal(
        self,
        table_name: str,
        column_name: str,
        value: str,
    ) -> str | None:
        data_type = self._get_column_types().get(table_name, {}).get(column_name)
        if data_type is None:
            return None

        literal = value.upper()
        if data_type == "boolean":
            if literal == "1":
                return "TRUE"
            if literal == "0":
                return "FALSE"
            return None

        if data_type in {"smallint", "integer", "bigint"}:
            if literal == "TRUE":
                return "1"
            if literal == "FALSE":
                return "0"
            return None

        return None


def _translate_insert_or_ignore(query: str) -> str:
    if not re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", query, re.IGNORECASE):
        return query

    translated = re.sub(
        r"INSERT\s+OR\s+IGNORE\s+INTO",
        "INSERT INTO",
        query,
        flags=re.IGNORECASE,
    ).rstrip()
    suffix = ";" if translated.endswith(";") else ""
    if suffix:
        translated = translated[:-1]
    return f"{translated} ON CONFLICT DO NOTHING{suffix}"


def _translate_datetime_calls(query: str) -> str:
    translated = re.sub(
        r"datetime\('now'\s*,\s*'([^']+)'\s*\)",
        lambda match: f"(CURRENT_TIMESTAMP + INTERVAL '{match.group(1)}')",
        query,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"datetime\('now'\s*,\s*\?\s*\|\|\s*' days'\s*\)",
        "(CURRENT_TIMESTAMP + (? || ' days')::interval)",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"datetime\('now'\)",
        "CURRENT_TIMESTAMP",
        translated,
        flags=re.IGNORECASE,
    )
    return translated


def _translate_group_concat(query: str) -> str:
    translated = re.sub(
        r"GROUP_CONCAT\(([^,()]+)\)",
        r"STRING_AGG(CAST(\1 AS TEXT), ',')",
        query,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"GROUP_CONCAT\(([^,()]+),\s*([^)]+)\)",
        r"STRING_AGG(CAST(\1 AS TEXT), \2)",
        translated,
        flags=re.IGNORECASE,
    )
    return translated


def _translate_placeholders(query: str) -> str:
    output: list[str] = []
    in_single = False
    in_double = False

    for char in query:
        if char == "'" and not in_double:
            in_single = not in_single
            output.append(char)
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            output.append(char)
            continue
        if char == "?" and not in_single and not in_double:
            output.append("%s")
            continue
        output.append(char)

    return "".join(output)
