-- 0017_user_username: a username belongs to the person, not to each note.
-- Move `username` from notes onto the users row (one per user), backfilling the
-- most recent known username, then drop the per-note column.

ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;

-- Backfill: latest (highest note id) non-empty username per user.
UPDATE users u
SET username = sub.username
FROM (
    SELECT DISTINCT ON (user_id) user_id, username
    FROM notes
    WHERE username IS NOT NULL AND btrim(username) <> ''
    ORDER BY user_id, id DESC
) sub
WHERE u.id = sub.user_id AND u.username IS NULL;

ALTER TABLE notes DROP COLUMN IF EXISTS username;
