"""Integration tests proving the migration's safety properties against a real
Postgres: reversibility (up/down) and mid-run-failure recovery (a simulated
crash mid-backfill, resumed to completion).

Drives the real scripts via subprocess -- no mocking -- against DB_URL.
"""
import os
import subprocess
import sys
from pathlib import Path

import psycopg

DB_URL = os.environ["DB_URL"]
MIGRATIONS_DIR = Path(__file__).parent.parent


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [sys.executable, str(MIGRATIONS_DIR / script), *args],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{script} {args} failed:\n{result.stdout}\n{result.stderr}"
    return result


def null_currency_count(conn) -> int:
    return conn.execute("SELECT count(*) FROM orders WHERE currency IS NULL").fetchone()[0]


def constraint_exists(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pg_constraint WHERE conname = 'orders_currency_not_null'"
    ).fetchone()
    return row is not None


def currency_column_exists(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'orders' AND column_name = 'currency'"
    ).fetchone()
    return row is not None


def test_expand_backfill_contract_and_reverse_cycle():
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        # Known baseline: idempotent no-ops if these aren't currently applied.
        run("run_migrations.py", "down", "0002_make_currency_not_null")
        run("run_migrations.py", "down", "0001_add_currency_column")
        assert not currency_column_exists(conn)

        # Expand: every row starts out NULL.
        run("run_migrations.py", "up", "0001_add_currency_column")
        total = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
        assert null_currency_count(conn) == total

        # Simulated mid-run crash: stop after one small batch.
        run("backfill_currency.py", "--batch-size", "5", "--max-batches", "1")
        remaining = null_currency_count(conn)
        assert 0 < remaining < total, "expected a genuinely partial backfill"

        # Resume: re-running with no limit finishes the job.
        run("backfill_currency.py", "--batch-size", "5")
        assert null_currency_count(conn) == 0

        # Contract only succeeds once the backfill has actually finished.
        run("run_migrations.py", "up", "0002_make_currency_not_null")
        assert constraint_exists(conn)

        # Reversible: down path removes the constraint, then the column.
        run("run_migrations.py", "down", "0002_make_currency_not_null")
        assert not constraint_exists(conn)
        run("run_migrations.py", "down", "0001_add_currency_column")
        assert not currency_column_exists(conn)
