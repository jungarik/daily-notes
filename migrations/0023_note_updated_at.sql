-- 0023_note_updated_at: when a note was last changed.
--
-- `created_at` has been on the table since the start; there was no modified
-- time, and nine separate UPDATE statements (the bot, the editor, the ⋮ menu,
-- the enricher, the classifier) write to `notes`. A trigger is the one place
-- that sees every one of them, so nothing can forget to set it.
ALTER TABLE notes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Backfill before the trigger exists. Earlier edits were never recorded, so the
-- honest value for an existing note is "not changed since it was created" —
-- not the moment this migration ran.
UPDATE notes SET updated_at = created_at;

-- Bump only when the row actually changed: an editor save that writes back
-- identical text, path and tags is not a modification.
CREATE OR REPLACE FUNCTION notes_touch_updated_at() RETURNS trigger AS $$
BEGIN
    IF NEW IS DISTINCT FROM OLD THEN
        NEW.updated_at = now();
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS notes_touch_updated_at ON notes;

CREATE TRIGGER notes_touch_updated_at
    BEFORE UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION notes_touch_updated_at();
