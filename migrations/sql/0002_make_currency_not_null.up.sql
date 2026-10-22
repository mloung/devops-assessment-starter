-- Contract: enforce NOT NULL without a blocking full-table-rewrite lock.
-- NOT VALID adds the constraint instantly (only blocks new violations);
-- VALIDATE CONSTRAINT then scans existing rows under a SHARE UPDATE
-- EXCLUSIVE lock, which still allows concurrent reads/writes.
-- This fails loudly if any row still has a NULL currency, i.e. if run
-- before the backfill has actually completed -- intentional.
ALTER TABLE orders ADD CONSTRAINT orders_currency_not_null CHECK (currency IS NOT NULL) NOT VALID;
ALTER TABLE orders VALIDATE CONSTRAINT orders_currency_not_null;
ALTER TABLE orders ALTER COLUMN currency SET DEFAULT 'ZAR';
