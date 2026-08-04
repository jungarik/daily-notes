-- 0007_drop_reminder_text: a reminder's text is the note's text, read by joining
-- messages on message_id, so the duplicated column is no longer stored. Also
-- make message_id NOT NULL since it's now required for that join.

ALTER TABLE reminders DROP COLUMN IF EXISTS text;
ALTER TABLE reminders ALTER COLUMN message_id SET NOT NULL;
