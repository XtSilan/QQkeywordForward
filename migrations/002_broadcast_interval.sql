-- Widen the broadcast interval constraint from >= 12s to >= 5s.
--
-- SQLite cannot alter a CHECK constraint in place, so the table is rebuilt.
-- Guarded in app/db.py by inspecting sqlite_master for the old constraint.

BEGIN;

CREATE TABLE broadcast_tasks_new (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  message_json TEXT NOT NULL,
  interval_seconds INTEGER NOT NULL CHECK(interval_seconds >= 5),
  group_cooldown_seconds INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',
  total_count INTEGER NOT NULL DEFAULT 0,
  sent_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT 'webui',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TEXT,
  finished_at TEXT,
  cancelled_at TEXT
);

CREATE TABLE broadcast_task_groups_new (
  task_id TEXT NOT NULL REFERENCES broadcast_tasks_new(id),
  group_id TEXT NOT NULL REFERENCES groups(group_id),
  status TEXT NOT NULL DEFAULT 'queued',
  scheduled_at TEXT NOT NULL,
  sent_at TEXT,
  message_id TEXT,
  error_code TEXT,
  error_text TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(task_id, group_id)
);

INSERT INTO broadcast_tasks_new SELECT * FROM broadcast_tasks;
INSERT INTO broadcast_task_groups_new SELECT * FROM broadcast_task_groups;

DROP TABLE broadcast_task_groups;
DROP TABLE broadcast_tasks;

ALTER TABLE broadcast_tasks_new RENAME TO broadcast_tasks;
ALTER TABLE broadcast_task_groups_new RENAME TO broadcast_task_groups;

CREATE INDEX idx_broadcast_task_groups_due
  ON broadcast_task_groups(status, scheduled_at);

COMMIT;
