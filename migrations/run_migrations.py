#!/usr/bin/env python3
"""Apply pending SQL migrations in migrations/sql/ to DB_URL.

Tracks applied versions in a schema_migrations table so re-runs are a no-op
and a half-applied file (if the process dies mid-migration) is never marked
as done, since the file's SQL and its schema_migrations insert run in the
same transaction.
"""
import os
import sys
from pathlib import Path

import psycopg

DB_URL = os.environ["DB_URL"]
MIGRATIONS_DIR = Path(__file__).parent / "sql"


def main() -> int:
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

        pending = sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.name not in applied)
        if not pending:
            print("No pending migrations.")
            return 0

        for path in pending:
            print(f"Applying {path.name} ...")
            sql = path.read_text()
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            print(f"Applied {path.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
