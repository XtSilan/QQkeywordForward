-- Add keyword_rules.sort_order so the WebUI can persist a manual drag order and
-- an A-Z order. Guarded in app/db.py by inspecting keyword_rules columns.
--
-- Existing rows are seeded oldest-id-first so the list keeps a stable order
-- without anyone having to touch the UI.

BEGIN;

ALTER TABLE keyword_rules ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;

UPDATE keyword_rules SET sort_order = (SELECT COUNT(*) FROM keyword_rules AS k
  WHERE k.id < keyword_rules.id) + 1 WHERE sort_order = 0;

COMMIT;
