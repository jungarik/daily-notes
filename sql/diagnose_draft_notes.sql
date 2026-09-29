-- diagnose_draft_notes.sql — why the draft cleanup matches nothing.
--
-- READ-ONLY. Nothing here writes.
--
-- IMPORTANT: run the blocks ONE AT A TIME. Several clients (the Railway query
-- console, pgAdmin's single-result pane, DBeaver's default) render only one
-- result set per execution, so running the whole file shows you one block and
-- silently discards the rest. Highlight a block, execute, read, move on.
--
-- Block A cannot return zero rows and cannot fail, whatever state the database
-- is in. If block A shows nothing, the problem is the client or the connection,
-- not the data — see the note at the bottom.


-- ============================================================================
-- A. What am I actually connected to?
-- ============================================================================
-- `to_regclass` returns NULL instead of raising when a table is absent, so this
-- is safe to run against an empty or half-migrated database.
--
-- Read it for:
--   * `notes` = << NOT FOUND >>        -> wrong database, or migrations never ran
--   * `messages (pre-0014)` = present  -> migrations stopped before 0014, and the
--                                         notes table is still called `messages`
--   * a `search_path` without the schema that holds the tables

SELECT 'connected to'              AS item,
       current_database() || '  as  ' || current_user AS value
UNION ALL SELECT 'search_path',    current_setting('search_path')
UNION ALL SELECT 'current_schema', current_schema()
UNION ALL SELECT 'server now',     now()::text || '   (TimeZone ' || current_setting('TimeZone') || ')'
UNION ALL SELECT 'notes',          coalesce(to_regclass('notes')::text, '<< NOT FOUND >>')
UNION ALL SELECT 'reminders',      coalesce(to_regclass('reminders')::text, '<< NOT FOUND >>')
UNION ALL SELECT 'note_links',     coalesce(to_regclass('note_links')::text, '<< NOT FOUND >>')
UNION ALL SELECT 'schema_migrations', coalesce(to_regclass('schema_migrations')::text, '<< NOT FOUND >>')
UNION ALL SELECT 'messages (pre-0014)', coalesce(to_regclass('messages')::text, 'absent — good, 0014 ran')
UNION ALL SELECT 'tables in this schema',
       (SELECT coalesce(string_agg(tablename, ', ' ORDER BY tablename), '<< none >>')
        FROM pg_tables WHERE schemaname = current_schema());


-- ============================================================================
-- B. Did the migrations run, and how far?
-- ============================================================================
-- The last row should be 0022_agent_states. Run this only if block A found
-- schema_migrations; otherwise it raises, which is itself the answer.

SELECT version, applied_at
FROM schema_migrations
ORDER BY version;


-- ============================================================================
-- C. Does `notes` hold anything?
-- ============================================================================
-- Always one row. `rows = 0` means this database is empty — the usual cause is
-- being pointed at a local or staging instance rather than the one the bot
-- writes to.

SELECT count(*)                                                    AS rows,
       count(DISTINCT user_id)                                     AS users,
       count(*) FILTER (WHERE path IS NULL)                        AS path_null,
       count(*) FILTER (WHERE path = '')                           AS path_empty_string,
       count(*) FILTER (WHERE path IS NOT NULL AND btrim(path) = '') AS path_whitespace_only,
       count(*) FILTER (WHERE path IN ('None', 'null', 'NULL', 'undefined')) AS path_literal_none,
       count(*) FILTER (WHERE path IS NOT NULL AND btrim(path) <> '') AS path_filed,
       min(created_at)                                             AS oldest,
       max(created_at)                                             AS newest
FROM notes;


-- ============================================================================
-- D. What is actually stored in `path`?
-- ============================================================================
-- The census above only tests the shapes I guessed at. This shows every value
-- as a quoted literal, so a trailing space or a stringified None is visible
-- rather than inferred. Zero rows here means the table is empty.

SELECT coalesce(quote_literal(path), 'NULL')  AS path_value,
       count(*)                               AS notes
FROM notes
GROUP BY path
ORDER BY notes DESC, path_value
LIMIT 50;


-- ============================================================================
-- E. If C shows drafts: which guard is holding each one?
-- ============================================================================
-- A draft is deleted only when both flags are false.

SELECT n.id,
       n.user_id,
       n.created_at,
       EXISTS (SELECT 1 FROM note_links l
               WHERE l.from_note_id = n.id OR l.to_note_id = n.id)   AS has_link,
       EXISTS (SELECT 1 FROM reminders r
               WHERE r.note_id = n.id
                 AND r.status IN ('scheduled', 'postponed', 'sending')
                 AND r.remind_at >= now())                           AS has_live_reminder,
       (SELECT count(*) FROM reminders r WHERE r.note_id = n.id)     AS reminders_total,
       (SELECT max(r.remind_at) FROM reminders r WHERE r.note_id = n.id) AS latest_remind_at,
       left(regexp_replace(coalesce(n.text, ''), '\s+', ' ', 'g'), 60)   AS preview
FROM notes n
WHERE n.path IS NULL OR btrim(n.path) = ''
ORDER BY n.created_at;


-- ============================================================================
-- F. Reminder statuses across the whole table
-- ============================================================================
-- Sanity check on the values the guard matches, and on where `now()` falls
-- relative to them. Always at least one row if any reminder exists.

SELECT status,
       count(*)                                    AS n,
       count(*) FILTER (WHERE remind_at >= now())  AS still_to_come,
       min(remind_at)                              AS earliest,
       max(remind_at)                              AS latest
FROM reminders
GROUP BY status
ORDER BY status;


-- ============================================================================
-- If block A itself showed nothing
-- ============================================================================
-- Then no statement in this file reached the server. In order of likelihood:
--
--   1. The client ran only one statement (usually the last, or the one under
--      the cursor) and showed you its empty grid. Highlight block A alone and
--      execute just that.
--   2. The connection is to a different database than DATABASE_URL points at.
--      Block A's first row settles it — compare against the Railway Postgres
--      service the API and bot use.
--   3. The statement errored and the client put the message in a tab you are
--      not looking at. Check the messages/notifications pane.
