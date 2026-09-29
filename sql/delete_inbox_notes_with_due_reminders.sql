-- delete_inbox_notes_with_due_reminders.sql — clear out Inbox notes whose
-- reminder has already come and gone.
--
-- READ THIS FIRST. This is not the draft cleanup. Those notes had no `path` and
-- were invisible in every view — deleting them removed nothing you could see.
-- These notes ARE in the vault: they appear in the feed, the explorer, the map
-- and search, and you filed them (or enrichment filed them for you) under
-- Вхідні. Take a database snapshot before running step 3.
--
-- WHAT COUNTS AS A MATCH
--
--   * path is the Inbox root — 'Вхідні', the `folder_inbox` key for the `uk`
--     locale. Paths are stored localised, so an `en` vault spells the same
--     folder 'Inbox'; change ROOT below if you need that one.
--   * the note HAS at least one reminder, and
--   * none of its reminders is still to come — nothing `scheduled`,
--     `postponed` or `sending` with `remind_at >= now()`.
--
-- A note in Вхідні with no reminder at all is NOT matched: it is an unsorted
-- note, not a spent one. A note with one fired reminder and one still pending
-- is NOT matched either — the pending one is the whole reason it still matters.
--
-- HOW TO RUN IT
--
-- Four independent statements. Run them ONE AT A TIME, in order. Each is
-- self-contained — no transaction block, no temp table, no state carried
-- between them — so it behaves the same in psql, the Railway console, pgAdmin
-- and DBeaver whatever they do about autocommit.
--
-- The predicate is repeated verbatim in statements 2–4. That duplication is
-- what makes each one runnable alone. If you change the root or add a filter,
-- change it in ALL THREE or step 4 deletes a different set than step 2 showed.


-- ============================================================================
-- 0. CENSUS — decide the scope with numbers rather than by guessing
-- ============================================================================
-- `root_exactly` is what statements 2–4 target as written. `under_a_subfolder`
-- counts notes at Вхідні/<something>, which the predicate below does NOT match.
-- If that number is non-zero and you want those gone too, see the widening note
-- under statement 2.

SELECT count(*) FILTER (WHERE n.path = 'Вхідні')                        AS root_exactly,
       count(*) FILTER (WHERE n.path LIKE 'Вхідні/%')                   AS under_a_subfolder,
       count(*) FILTER (WHERE n.path = 'Вхідні'
                          AND EXISTS (SELECT 1 FROM reminders r
                                      WHERE r.note_id = n.id))          AS root_with_any_reminder,
       count(*) FILTER (WHERE n.path = 'Вхідні'
                          AND EXISTS (SELECT 1 FROM reminders r
                                      WHERE r.note_id = n.id
                                        AND r.status IN ('scheduled', 'postponed', 'sending')
                                        AND r.remind_at >= now()))      AS root_with_a_live_reminder
FROM notes n;


-- ============================================================================
-- 1. PREVIEW — the exact rows statement 4 will delete
-- ============================================================================
-- `has_link` is reported, not filtered on: a note something links to is curated,
-- and you may want to spare it. If any row shows true and you want links to
-- protect a note, add this to statements 2–4:
--
--   AND NOT EXISTS (SELECT 1 FROM note_links l
--                   WHERE l.from_note_id = n.id OR l.to_note_id = n.id)
--
-- To widen the match to sub-folders, replace `n.path = 'Вхідні'` with
-- `(n.path = 'Вхідні' OR n.path LIKE 'Вхідні/%')` in statements 2–4.

SELECT n.id,
       n.user_id,
       n.created_at,
       n.title,
       (SELECT count(*) FROM reminders r WHERE r.note_id = n.id)         AS reminders,
       (SELECT max(r.remind_at) FROM reminders r WHERE r.note_id = n.id) AS last_remind_at,
       EXISTS (SELECT 1 FROM note_links l
               WHERE l.from_note_id = n.id OR l.to_note_id = n.id)       AS has_link,
       left(regexp_replace(coalesce(n.text, ''), '\s+', ' ', 'g'), 80)   AS preview
FROM notes n
WHERE n.path = 'Вхідні'
  AND EXISTS (SELECT 1 FROM reminders r WHERE r.note_id = n.id)
  AND NOT EXISTS (SELECT 1 FROM reminders r
                  WHERE r.note_id = n.id
                    AND r.status IN ('scheduled', 'postponed', 'sending')
                    AND r.remind_at >= now())
ORDER BY n.created_at;


-- ============================================================================
-- 2. BUCKET OBJECTS about to be orphaned — SAVE THIS OUTPUT
-- ============================================================================
-- The database cascades; object storage does not. These keys stay in the bucket
-- unless `file_store.delete_object(key)` removes them, and after step 4 there is
-- no record of which note they belonged to. Zero rows means no matched note had
-- a photo or a voice message.

SELECT 'attachment' AS kind, a.storage_key AS key, a.note_id
FROM note_attachments a
JOIN notes n ON n.id = a.note_id
WHERE n.path = 'Вхідні'
  AND EXISTS (SELECT 1 FROM reminders r WHERE r.note_id = n.id)
  AND NOT EXISTS (SELECT 1 FROM reminders r
                  WHERE r.note_id = n.id
                    AND r.status IN ('scheduled', 'postponed', 'sending')
                    AND r.remind_at >= now())

UNION ALL

SELECT 'voice', n.audio_key, n.id
FROM notes n
WHERE n.audio_key IS NOT NULL
  AND n.path = 'Вхідні'
  AND EXISTS (SELECT 1 FROM reminders r WHERE r.note_id = n.id)
  AND NOT EXISTS (SELECT 1 FROM reminders r
                  WHERE r.note_id = n.id
                    AND r.status IN ('scheduled', 'postponed', 'sending')
                    AND r.remind_at >= now())

ORDER BY 1, 3;


-- ============================================================================
-- 3. DELETE — commits on execution. There is no undo.
-- ============================================================================
-- Run only after step 1 shows the right rows and step 2's keys are saved.
--
-- Cascades take note_chunks, note_attachments, note_links and reminders with
-- the note. The reminder history goes too, fired rows included — that is the
-- point here, but it is not recoverable.
--
-- The DELETE sits in a data-modifying CTE so the statement ends in a count:
-- several clients show only the last result set, and a bare DELETE returns
-- none, which reads as "nothing happened" when the opposite is true.

WITH deleted AS (
    DELETE FROM notes n
    WHERE n.path = 'Вхідні'
      AND EXISTS (SELECT 1 FROM reminders r WHERE r.note_id = n.id)
      AND NOT EXISTS (SELECT 1 FROM reminders r
                      WHERE r.note_id = n.id
                        AND r.status IN ('scheduled', 'postponed', 'sending')
                        AND r.remind_at >= now())
    RETURNING id
)
SELECT count(*) AS notes_deleted FROM deleted;
