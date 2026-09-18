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
"""


def init_db() -> None:
    settings = get_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('config_revision', '1')"
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
