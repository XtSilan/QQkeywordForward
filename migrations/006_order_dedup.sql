-- Order-fingerprint dedup: replace text/sender cooldown tables with per-order
-- state, add message idempotency table, and extend notification_jobs with
-- priority/expiry columns (consumed by the dispatcher in a later phase).
-- Guarded in app/db.py by checking for the orders/msgs tables and the
-- notification_jobs.priority column.

BEGIN;

CREATE TABLE IF NOT EXISTS orders (
  fp TEXT PRIMARY KEY,
  dest TEXT NOT NULL DEFAULT '',
  day TEXT NOT NULL DEFAULT '',
  box TEXT NOT NULL DEFAULT '',
  wt TEXT NOT NULL DEFAULT '',
  core TEXT NOT NULL DEFAULT '',
  phones TEXT NOT NULL DEFAULT '',
  last_seen REAL NOT NULL,
  sent_at REAL,
  n_push INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_orders_dest_day
  ON orders(dest, day);

-- Idempotency for NapCat reconnect replays: (group, message id) is unique.
CREATE TABLE IF NOT EXISTS msgs (
  gid TEXT NOT NULL,
  mid TEXT NOT NULL,
  seen_at REAL NOT NULL,
  PRIMARY KEY(gid, mid)
);

ALTER TABLE notification_jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 1;
ALTER TABLE notification_jobs ADD COLUMN expires_at TEXT;

DROP TABLE IF EXISTS keyword_message_cooldowns;
DROP TABLE IF EXISTS sender_message_cooldowns;

INSERT OR IGNORE INTO app_meta(key, value) VALUES ('alert_dedup_enabled', '1');
INSERT OR IGNORE INTO app_meta(key, value) VALUES ('alert_similarity_threshold', '0.8');
INSERT OR IGNORE INTO app_meta(key, value) VALUES ('alert_order_window_minutes', '60');
INSERT OR IGNORE INTO app_meta(key, value) VALUES ('alert_max_push_per_order', '2');
INSERT OR IGNORE INTO app_meta(key, value) VALUES ('alert_new_phone_repush', '1');
INSERT OR IGNORE INTO app_meta(key, value) VALUES ('alert_ad_filter_enabled', '1');
INSERT OR IGNORE INTO app_meta(key, value) VALUES ('alert_ad_keywords', '招工,日结,时薪,暑假工');

COMMIT;
