-- Adds retry backoff default + last_status to schedules.
ALTER TABLE schedules ADD COLUMN last_error TEXT;