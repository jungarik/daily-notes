-- 0016_path_two_levels: normalize existing note paths to the vault rule enforced
-- at enrichment time — a predefined PARA root folder plus AT MOST one sub-folder
-- (two levels maximum).
--
--   * paths nested deeper than two levels are trimmed to their first two segments
--   * a first segment that is not one of the known root folders is reset to 'Inbox'
--     (this includes retired roots such as Knowledge and Daily_notes)
--   * the root folder's casing is canonicalized to match config.ROOT_FOLDERS
--   * NULL paths (notes not enriched yet) are left untouched
--
-- Root folders — PARA + Inbox only (must match config.ROOT_FOLDERS):
--   Inbox, Projects, Areas, Resources, Archive
--
-- Data-only change (no schema change). It rewrites the `path` column in place, so
-- take a database snapshot before running if you want to preserve the original,
-- deeper paths — the trimmed sub-levels are not recoverable from this migration.

WITH parsed AS (
    SELECT
        id,
        -- canonical (case-corrected) root folder, or NULL when it is not a known root
        CASE lower(btrim(split_part(path, '/', 1)))
            WHEN 'inbox'     THEN 'Inbox'
            WHEN 'projects'  THEN 'Projects'
            WHEN 'areas'     THEN 'Areas'
            WHEN 'resources' THEN 'Resources'
            WHEN 'archive'   THEN 'Archive'
            ELSE NULL
        END AS root,
        NULLIF(btrim(split_part(path, '/', 2)), '') AS sub
    FROM notes
    WHERE path IS NOT NULL AND btrim(path) <> ''
),
target AS (
    SELECT
        id,
        CASE
            WHEN root IS NULL THEN 'Inbox'            -- unknown/retired root -> default
            WHEN sub  IS NULL THEN root               -- root folder only
            ELSE root || '/' || sub                   -- root + exactly one sub-folder
        END AS new_path
    FROM parsed
)
UPDATE notes n
SET path = t.new_path
FROM target t
WHERE n.id = t.id
  AND n.path IS DISTINCT FROM t.new_path;   -- skip rows that already comply
