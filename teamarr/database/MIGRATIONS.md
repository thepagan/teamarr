# Database Migrations

How database schema changes work in Teamarr v2.

## Architecture

```
Startup (init_db):
  1. Verify integrity / V1 detection
  2. Structural pre-migrations (column renames, table rebuilds)
  3. Schema reconciliation ← compares real DB against schema.sql
  4. conn.executescript(schema.sql) ← creates missing tables, seeds data
  5. Data migrations (_run_migrations) ← transforms existing data
  6. Seed TSDB cache
```

### Key Files

| File | Purpose |
|------|---------|
| `schema.sql` | Single source of truth for all table/column definitions |
| `reconciliation.py` | Compares real DB against in-memory reference, adds missing columns |
| `connection.py` | `init_db()` startup flow + `_run_migrations()` data migrations |
| `checkpoint_v43.py` | Consolidates v2-v43 migrations into single idempotent operation |

## Adding a New Column

**Just add it to `schema.sql`.** That's it.

```sql
CREATE TABLE IF NOT EXISTS settings (
    ...
    my_new_setting TEXT DEFAULT 'default_value',  -- ADD THIS
    schema_version INTEGER DEFAULT 72             -- BUMP THIS
);
```

Schema reconciliation runs every startup. It creates an in-memory reference
database from `schema.sql`, compares each real table against it via
`PRAGMA table_info`, and adds any missing columns via `ALTER TABLE ADD COLUMN`.

No migration block needed. No pre-migration function needed.

## Adding a Data Migration

When you need to **transform existing data** (not just add a column):

1. Add column to `schema.sql` (reconciliation handles the column)
2. Bump `schema_version DEFAULT` in `schema.sql`
3. Add a versioned block in `_run_migrations()`:

```python
if current_version < 72:
    # Column already exists (added by reconciliation or schema.sql).
    # Transform existing data:
    conn.execute("UPDATE settings SET new_col = old_col * 2 WHERE new_col IS NULL")

    conn.execute("UPDATE settings SET schema_version = 72 WHERE id = 1")
    logger.info("[MIGRATE] Schema upgraded to version 72 (description)")
    current_version = 72
```

If the data migration READS from a column it also adds, include an
`_add_column_if_not_exists` call as a safety net (tests may call
`_run_migrations` without reconciliation).

## Table Rebuild (CHECK Constraint Changes)

SQLite bakes CHECK constraints at CREATE TABLE time. To change them:

1. Add a pre-migration in `init_db()` that backs up the table and drops it
2. `executescript` recreates it with new constraints from `schema.sql`
3. Add a restore block in `_run_migrations` keyed on backup table existence

See `_migrate_settings_for_v65` as the reference pattern.

## Best Practices

**DO:** Use idempotent operations
```python
_add_column_if_not_exists(conn, "table", "column", "TYPE DEFAULT value")
conn.execute("INSERT OR IGNORE INTO ...")
conn.execute("UPDATE ... WHERE col IS NULL")  # Only update if not already set
```

**DON'T:** Add columns with non-constant defaults
```python
# BAD: SQLite can't ALTER TABLE ADD COLUMN with CURRENT_TIMESTAMP default
# GOOD: Use NULL default, populate separately
_add_column_if_not_exists(conn, "t", "created_at", "TIMESTAMP")
conn.execute("UPDATE t SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
```

## Reconciliation Details

`reconciliation.py` — `reconcile_schema(conn, schema_sql)`:

1. Creates in-memory reference DB from `schema.sql`
2. Gets tables from both real and reference DBs
3. For tables in both: compares columns via `PRAGMA table_info`
4. Adds missing columns with type and DEFAULT from reference
5. Skips tables not in real DB (executescript creates them)
6. Skips extra columns in real DB (doesn't drop anything)
7. Skips internal tables (names starting with `_`)

Self-healing: any missing column — from bugs, partial migrations, version
corruption — gets automatically repaired on next startup.

## Troubleshooting

### "no such column" errors
Schema reconciliation should prevent this. If it happens, check that
`reconcile_schema` runs before `executescript` in `init_db()`.

### Migration runs but changes aren't visible
Check that `schema_version` is being updated in the migration block.

### User reports partial migration
Reconciliation self-heals column gaps. For data migration issues,
the versioned blocks are idempotent and can be re-run safely.
