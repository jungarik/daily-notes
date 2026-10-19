-- 0024_note_is_favorite: a note the user has starred.
--
-- A plain flag, NOT NULL with a default so every existing note reads as "not a
-- favourite" without a backfill. The `notes_touch_updated_at` trigger (0023)
-- sees this column like any other, so starring a note counts as modifying it.
ALTER TABLE notes ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN NOT NULL DEFAULT false;
