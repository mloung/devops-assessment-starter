# Migrations

Evolves the baseline `orders` table (`../schema.sql`) with an expand/backfill/contract
rollout of a `currency` column. See the top-level `README.md` ("Database migration —
safety reasoning") for the full write-up: why each step is safe under live traffic,
and how a mid-run failure is detected and recovered without restoring from a backup.

- `run_migrations.py` — applies/reverts versioned SQL files in `sql/`, tracked in a
  `schema_migrations` table (`up [target]`, `down <version>`, `status`).
- `backfill_currency.py` — batched, idempotent backfill of historical rows.
- `sql/0001_add_currency_column.{up,down}.sql` — expand.
- `sql/0002_make_currency_not_null.{up,down}.sql` — contract.
- `tests/test_migrations.py` — proves the reversibility and crash-resume properties
  end-to-end against a real Postgres.
