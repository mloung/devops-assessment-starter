#!/usr/bin/env python3
"""Backfill orders.currency for historical rows, in small batches.

Idempotent and resumable: each batch is its own transaction and only ever
targets rows still needing backfill (currency IS NULL), so progress lives in
the data itself. A crash mid-run loses no progress -- re-running (with no
--max-batches) simply continues from wherever it stopped.
"""
import argparse
import os
import sys
import time

import psycopg

DB_URL = os.environ["DB_URL"]
DEFAULT_CURRENCY = "ZAR"
DEFAULT_BATCH_SIZE = 500


def backfill(batch_size: int = DEFAULT_BATCH_SIZE, max_batches: int | None = None, sleep_seconds: float = 0.0) -> int:
    batches_done = 0
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        while max_batches is None or batches_done < max_batches:
            with conn.transaction():
                updated = conn.execute(
                    """
                    UPDATE orders SET currency = %s
                    WHERE id IN (
                        SELECT id FROM orders WHERE currency IS NULL
                        LIMIT %s FOR UPDATE SKIP LOCKED
                    )
                    """,
                    (DEFAULT_CURRENCY, batch_size),
                ).rowcount
            batches_done += 1
            print(f"Batch {batches_done}: backfilled {updated} row(s)")
            if updated == 0:
                print("Backfill complete.")
                return 0
            if sleep_seconds:
                time.sleep(sleep_seconds)

    print(f"Stopped after {batches_done} batch(es) (max-batches reached) -- re-run to continue.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-batches", type=int, default=None, help="stop after N batches (simulates a crash, for testing resumability)")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds to sleep between batches")
    args = parser.parse_args()
    return backfill(batch_size=args.batch_size, max_batches=args.max_batches, sleep_seconds=args.sleep)


if __name__ == "__main__":
    sys.exit(main())
