-- Drop the per-keyword column from the duplicate-message cooldown table so the
-- fingerprint is the sole key. Guarded in app/db.py by inspecting the columns
-- of keyword_message_cooldowns.

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
