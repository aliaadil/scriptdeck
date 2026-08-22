-- Migration 018: persist the exact command each run was invoked with.
--
-- Without this column the only way to reconcile "what the script's
-- argparse said it expected" against "what we asked it to run" is to
-- re-resolve the trigger params by hand. Capture the final argv as
-- a single space-joined string for human-readability; nobody is
-- expected to parse it back into tokens.
ALTER TABLE runs ADD COLUMN command TEXT;
