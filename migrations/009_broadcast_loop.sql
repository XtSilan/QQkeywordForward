-- Auto-looping broadcast tasks.
--
-- A looping task re-sends the whole schedule once a round finishes instead of
-- completing. ``loop_total`` counts rounds *including* the first one (0 means
-- the task never loops, which is what every existing task gets), and
-- ``loop_current`` is the round currently in flight (1-based). The gap between
-- rounds is separate from the per-group delay so an operator can pace a round
-- tightly while leaving a long pause before the next one.
-- Guards live in app/db.py (broadcast_tasks.loop_total).

BEGIN;

ALTER TABLE broadcast_tasks ADD COLUMN loop_total INTEGER NOT NULL DEFAULT 0;
ALTER TABLE broadcast_tasks ADD COLUMN loop_current INTEGER NOT NULL DEFAULT 0;
ALTER TABLE broadcast_tasks ADD COLUMN loop_interval_seconds INTEGER NOT NULL DEFAULT 60;

COMMIT;