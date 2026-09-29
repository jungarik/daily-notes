-- delete_draft_notes.sql — one-off cleanup of dead drafts.
--
-- A note with no `path` is not in the vault: it was captured and never
-- enriched, and `feed`, `explorer`, `mapview` and `search` all omit it. Such a
-- note is a draft, and a draft that nothing else points at is dead weight.
--
-- Two things keep a draft alive, and both are checked below:
--
--   * a link — a note someone curated a connection to is not dead, whatever
--     its path says (the same guard `api/telegram_bot/db.delete_if_bare`
--     applies behind the bot's ✕ button);
--   * a reminder still to come — `scheduled`, `postponed` or mid-delivery
--     (`sending`) with `remind_at` in the future. Once that time has passed the
--     reminder has fired (or was abandoned) and the draft goes with it, which
--     is the "due reminders" half of this script.
--
-- HOW TO RUN IT
--
-- Three independent statements. Run them ONE AT A TIME, in order — highlight a
-- statement and execute just that. Each is self-contained: no transaction block,
-- no temp table, no state carried from the previous one, so it behaves the same
-- in psql, the Railway console, pgAdmin and DBeaver regardless of how the client
-- handles autocommit.
--
-- The selection predicate is repeated verbatim in all three. That duplication is
-- deliberate — it is what makes each statement runnable on its own. If you edit
-- the predicate (see "Optional narrowing" below), edit it in ALL THREE or step 3
-- will delete a different set than step 1 showed you.


-- ============================================================================
-- 1. PREVIEW — what would go
-- ============================================================================

SELECT n.id,
       n.user_id,
       n.created_at,
       (SELECT count(*) FROM reminders r WHERE r.note_id = n.id) AS reminders,
       left(regexp_replace(coalesce(n.text, ''), '\s+', ' ', 'g'), 80) AS preview
FROM notes n
WHERE (n.path IS NULL OR btrim(n.path) = '')
  AND NOT EXISTS (SELECT 1 FROM note_links l
                  WHERE l.from_note_id = n.id OR l.to_note_id = n.id)
  AND NOT EXISTS (SELECT 1 FROM reminders r
                  WHERE r.note_id = n.id
                    AND r.status IN ('scheduled', 'postponed', 'sending')
                    AND r.remind_at >= now())
  -- Optional narrowing — uncomment in ALL THREE statements:
  -- AND n.user_id = 1                              -- one user only
  -- AND n.created_at < now() - interval '7 days'   -- give drafts a grace period
ORDER BY n.created_at;


-- ============================================================================
-- 2. BUCKET OBJECTS about to be orphaned — SAVE THIS OUTPUT
-- ============================================================================
-- The database cascades: note_chunks, note_attachments, note_links and
-- reminders all reference notes ON DELETE CASCADE. Object storage does not.
-- These keys stay in the bucket, costing money, unless something removes them —
-- `file_store.delete_object(key)` is what does. After step 3 there is no record
-- left of which keys belonged to the deleted notes, so copy this out first.
--
-- Zero rows here is a normal answer: it means no draft had a photo or a voice
-- message, and nothing needs cleaning up in S3.

SELECT 'attachment' AS kind, a.storage_key AS key, a.note_id
FROM note_attachments a
JOIN notes n ON n.id = a.note_id
WHERE (n.path IS NULL OR btrim(n.path) = '')
  AND NOT EXISTS (SELECT 1 FROM note_links l
                  WHERE l.from_note_id = n.id OR l.to_note_id = n.id)
  AND NOT EXISTS (SELECT 1 FROM reminders r
                  WHERE r.note_id = n.id
                    AND r.status IN ('scheduled', 'postponed', 'sending')
                    AND r.remind_at >= now())
  -- AND n.user_id = 1
  -- AND n.created_at < now() - interval '7 days'

UNION ALL

SELECT 'voice', n.audio_key, n.id
FROM notes n
WHERE n.audio_key IS NOT NULL
  AND (n.path IS NULL OR btrim(n.path) = '')
  AND NOT EXISTS (SELECT 1 FROM note_links l
                  WHERE l.from_note_id = n.id OR l.to_note_id = n.id)
  AND NOT EXISTS (SELECT 1 FROM reminders r
                  WHERE r.note_id = n.id
                    AND r.status IN ('scheduled', 'postponed', 'sending')
                    AND r.remind_at >= now())
  -- AND n.user_id = 1
  -- AND n.created_at < now() - interval '7 days'

ORDER BY 1, 3;


-- ============================================================================
-- 3. DELETE — this one commits. There is no undo.
-- ============================================================================
-- Run only after step 1 shows the right rows and step 2's keys are saved.
--
-- The DELETE sits in a data-modifying CTE so the statement's last act is a
-- count: several clients render only the final result set, and a bare DELETE
-- returns none, which reads as "nothing happened" when the opposite is true.
--
-- Deleting a draft deletes its reminder history with it — fired reminders
-- included — because `reminders.note_id` cascades. That follows from the rule,
-- but it is gone for good.

WITH deleted AS (
    DELETE FROM notes n
    WHERE (n.path IS NULL OR btrim(n.path) = '')
      AND NOT EXISTS (SELECT 1 FROM note_links l
                      WHERE l.from_note_id = n.id OR l.to_note_id = n.id)
      AND NOT EXISTS (SELECT 1 FROM reminders r
                      WHERE r.note_id = n.id
                        AND r.status IN ('scheduled', 'postponed', 'sending')
                        AND r.remind_at >= now())
      -- AND n.user_id = 1
      -- AND n.created_at < now() - interval '7 days'
    RETURNING id
)
SELECT count(*) AS notes_deleted FROM deleted;
