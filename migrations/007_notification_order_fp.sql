-- Link notification jobs back to the order fingerprints that triggered them
-- (one message can carry several orders, so the column holds a comma-joined
-- list). The dispatcher uses it to restore delivered state on send success
-- and to release undelivered orders when a job expires unsent.
-- Guarded in app/db.py by checking for the notification_jobs.order_fp column.

BEGIN;

ALTER TABLE notification_jobs ADD COLUMN order_fp TEXT NOT NULL DEFAULT '';

COMMIT;
