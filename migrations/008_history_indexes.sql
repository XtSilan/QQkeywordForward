-- History listing performance.
--
-- The history page orders every hit by ``hit_at`` across all groups, but the
-- only index on keyword_hits was (group_id, hit_at), so a global listing always
-- needed a temporary B-tree sort and the old parameterised
-- ``(? IS NULL OR group_id=?)`` predicate defeated that index even when a group
-- filter *was* supplied. Guards live in app/db.py (idx_keyword_hits_hit_at).
--
-- Also seeds the history retention knob read by the dispatch sweeper. Zero
-- (the default) keeps every hit, so nothing is deleted unless an operator
-- explicitly opts in.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_keyword_hits_hit_at
  ON keyword_hits(hit_at DESC);

INSERT OR IGNORE INTO app_meta(key, value) VALUES ('history_retention_days', '0');

COMMIT;