from pathlib import Path
import sqlite3
from contextlib import contextmanager

from app.settings import get_settings


SCHEMA = """
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
"""


def _migrate_broadcast_interval(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='broadcast_tasks'"
    ).fetchone()
    normalized = "".join((row[0] if row and row[0] else "").lower().split())
    if "check(interval_seconds>=12)" not in normalized:
        return

    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executescript(
        """
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
        """
    )
    connection.execute("PRAGMA foreign_keys = ON")


def _migrate_duplicate_message_cooldowns(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(keyword_message_cooldowns)"
        ).fetchall()
    }
    if "keyword_id" not in columns:
        return

    connection.executescript(
        """
        BEGIN;
        DROP INDEX IF EXISTS idx_keyword_message_cooldowns_until;
        CREATE TABLE keyword_message_cooldowns_new (
          message_fingerprint TEXT PRIMARY KEY,
          occurrence_count INTEGER NOT NULL DEFAULT 1,
          last_seen_at REAL NOT NULL,
          cooldown_until REAL
        );
        INSERT INTO keyword_message_cooldowns_new(
          message_fingerprint, occurrence_count, last_seen_at, cooldown_until
        )
        SELECT message_fingerprint, MAX(occurrence_count), MAX(last_seen_at), MAX(cooldown_until)
        FROM keyword_message_cooldowns
        GROUP BY message_fingerprint;
        DROP TABLE keyword_message_cooldowns;
        ALTER TABLE keyword_message_cooldowns_new RENAME TO keyword_message_cooldowns;
        CREATE INDEX idx_keyword_message_cooldowns_until
          ON keyword_message_cooldowns(cooldown_until);
        CREATE INDEX idx_keyword_message_cooldowns_seen
          ON keyword_message_cooldowns(last_seen_at);
        COMMIT;
        """
    )


def init_db() -> None:
    settings = get_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as connection:
        connection.executescript(SCHEMA)
        _migrate_broadcast_interval(connection)
        _migrate_duplicate_message_cooldowns(connection)
        connection.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('config_revision', '1')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('duplicate_message_threshold', '2')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('duplicate_message_cooldown_seconds', '600')"
        )
        default_upgrade = connection.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) "
            "VALUES ('duplicate_message_filter_defaults_v2', 'applied')"
        )
        if default_upgrade.rowcount:
            connection.execute(
                "UPDATE app_meta SET value='2' WHERE key='duplicate_message_threshold'"
            )
        connection.commit()


@contextmanager
def connection():
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def config_revision() -> int:
    with connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'config_revision'"
        ).fetchone()
        return int(row["value"]) if row else 0


def bump_config_revision() -> int:
    with connection() as conn:
        current = config_revision()
        next_value = current + 1
        conn.execute(
            "INSERT INTO app_meta(key, value) VALUES ('config_revision', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(next_value),),
        )
        return next_value
