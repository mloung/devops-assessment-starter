#!/usr/bin/env python3
"""Apply, revert, and inspect SQL migrations in migrations/sql/.

Convention: migrations/sql/<version>.up.sql + migrations/sql/<version>.down.sql.
Applied versions are tracked in a schema_migrations table. A version's SQL
and its schema_migrations row change (insert on up, delete on down) run in
the same transaction, so a crash mid-file never leaves a version recorded as
applied when it only half-ran -- `status` always reflects what actually ran.

Usage:
    run_migrations.py up [target]   # apply pending migrations (up to target, if given)
    run_migrations.py down <version>
    run_migrations.py status
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg

DB_URL = os.environ["DB_URL"]
MIGRATIONS_DIR = Path(__file__).parent / "sql"


def version_of(up_path: Path) -> str:
    return up_path.name.removesuffix(".up.sql")


def ensure_tracking_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def up(target: str | None = None) -> int:
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        ensure_tracking_table(conn)
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

        pending = sorted(
            p for p in MIGRATIONS_DIR.glob("*.up.sql") if version_of(p) not in applied
        )
        if not pending:
            print("No pending migrations.")
            return 0

        for path in pending:
            version = version_of(path)
            print(f"Applying {version} ...")
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            print(f"Applied {version}")
            if target and version == target:
                break
    return 0


def down(version: str) -> int:
    down_path = MIGRATIONS_DIR / f"{version}.down.sql"
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        ensure_tracking_table(conn)
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        if version not in applied:
            print(f"{version} is not applied; nothing to do.")
            return 0
        if not down_path.exists():
            print(f"No down file for {version} ({down_path.name} not found).", file=sys.stderr)
            return 1

        print(f"Reverting {version} ...")
        with conn.transaction():
            conn.execute(down_path.read_text())
            conn.execute("DELETE FROM schema_migrations WHERE version = %s", (version,))
        print(f"Reverted {version}")
    return 0


def status() -> int:
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        ensure_tracking_table(conn)
        applied = dict(conn.execute("SELECT version, applied_at FROM schema_migrations").fetchall())

    for path in sorted(MIGRATIONS_DIR.glob("*.up.sql")):
        version = version_of(path)
        if version in applied:
            print(f"[applied {applied[version]}] {version}")
        else:
            print(f"[pending]          {version}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    up_parser = sub.add_parser("up", help="apply pending migrations")
    up_parser.add_argument("target", nargs="?", default=None, help="stop after applying this version")

    down_parser = sub.add_parser("down", help="revert one applied migration")
    down_parser.add_argument("version", help="version to revert")

    sub.add_parser("status", help="show applied/pending migrations")

    args = parser.parse_args()
    if args.command == "up":
        return up(args.target)
    if args.command == "down":
        return down(args.version)
    return status()


if __name__ == "__main__":
    sys.exit(main())
