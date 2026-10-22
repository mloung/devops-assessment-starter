-- Expand: add a nullable currency column. Safe under live traffic --
-- old app code (which never references currency) is unaffected, and the
-- column is ready for the new app code to start writing to.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS currency TEXT;
