-- Base schema. Applied on every boot; all statements are idempotent so it is
-- safe to re-run against an existing database.
--
-- Later structural changes live in the numbered migrations next to this file.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
  group_id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  avatar_url TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  last_synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS keyword_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  display_text TEXT NOT NULL,
  pattern TEXT NOT NULL,
  match_mode TEXT NOT NULL DEFAULT 'literal_search',
  ignore_case INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_keyword_rules_active_text
  ON keyword_rules(display_text) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS group_keyword_bindings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id TEXT NOT NULL REFERENCES groups(group_id),
  keyword_id INTEGER NOT NULL REFERENCES keyword_rules(id),
  enabled INTEGER NOT NULL DEFAULT 0,
  cooldown_seconds INTEGER NOT NULL DEFAULT 60,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(group_id, keyword_id)
);

CREATE TABLE IF NOT EXISTS keyword_hits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id TEXT NOT NULL REFERENCES groups(group_id),
  group_name TEXT NOT NULL DEFAULT '',
  sender_id TEXT NOT NULL,
  sender_name TEXT NOT NULL DEFAULT '',
  keyword_id INTEGER REFERENCES keyword_rules(id),
  keyword_text_snapshot TEXT NOT NULL,
  message_json TEXT NOT NULL,
  message_text TEXT NOT NULL,
  message_id TEXT NOT NULL,
  hit_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  notify_status TEXT NOT NULL DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_keyword_hits_group_time
  ON keyword_hits(group_id, hit_at DESC);

CREATE TABLE IF NOT EXISTS notification_destinations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK(kind IN ('qq', 'email')),
  address TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(kind, address)
);

CREATE TABLE IF NOT EXISTS group_notification_settings (
  group_id TEXT PRIMARY KEY REFERENCES groups(group_id),
  qq_enabled INTEGER NOT NULL DEFAULT 0,
  email_enabled INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notification_destination_bindings (
  group_id TEXT NOT NULL REFERENCES groups(group_id),
  destination_id INTEGER NOT NULL REFERENCES notification_destinations(id),
  PRIMARY KEY(group_id, destination_id)
);

CREATE TABLE IF NOT EXISTS keyword_notification_bindings (
  keyword_id INTEGER NOT NULL REFERENCES keyword_rules(id),
  destination_id INTEGER NOT NULL REFERENCES notification_destinations(id),
  enabled INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(keyword_id, destination_id)
);

CREATE TABLE IF NOT EXISTS keyword_message_cooldowns (
  message_fingerprint TEXT PRIMARY KEY,
  occurrence_count INTEGER NOT NULL DEFAULT 1,
  last_seen_at REAL NOT NULL,
  cooldown_until REAL
);

CREATE INDEX IF NOT EXISTS idx_keyword_message_cooldowns_until
  ON keyword_message_cooldowns(cooldown_until);

CREATE INDEX IF NOT EXISTS idx_keyword_message_cooldowns_seen
  ON keyword_message_cooldowns(last_seen_at);

CREATE TABLE IF NOT EXISTS sender_message_cooldowns (
  sender_id TEXT PRIMARY KEY,
  triggered_at REAL NOT NULL,
  cooldown_until REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sender_message_cooldowns_until
  ON sender_message_cooldowns(cooldown_until);

CREATE TABLE IF NOT EXISTS broadcast_tasks (
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

CREATE TABLE IF NOT EXISTS broadcast_task_groups (
  task_id TEXT NOT NULL REFERENCES broadcast_tasks(id),
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

CREATE INDEX IF NOT EXISTS idx_broadcast_task_groups_due
  ON broadcast_task_groups(status, scheduled_at);

CREATE TABLE IF NOT EXISTS notification_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hit_id INTEGER NOT NULL REFERENCES keyword_hits(id),
  destination_id INTEGER NOT NULL REFERENCES notification_destinations(id),
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_error TEXT,
  sent_at TEXT,
  UNIQUE(hit_id, destination_id)
);

CREATE INDEX IF NOT EXISTS idx_notification_jobs_due
  ON notification_jobs(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  status_code INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
  ON audit_logs(created_at DESC);
