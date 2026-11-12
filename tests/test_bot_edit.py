"""The bot's ✏️ Edit button, and the removal of Atomize.

Edit replaces a note's text. A bot cannot pre-fill the user's input field, so the
button sends a force-reply prompt that quotes the current text and the reply
becomes the new text. The section's helper cannot be imported here (its database
layer needs psycopg), so this reads source like the other section tests.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SECTION = ROOT / "api" / "telegram_bot"
HELPER = (SECTION / "helper.py").read_text(encoding="utf-8")
ENDPOINTS = (SECTION / "endpoints.py").read_text(encoding="utf-8")
SCHEMAS = (SECTION / "schemas.py").read_text(encoding="utf-8")
BOT = (ROOT / "capture" / "Telegram_Bot" / "bot.py").read_text(encoding="utf-8")
CLIENT = (ROOT / "capture" / "Telegram_Bot" / "api_client.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "config.py").read_text(encoding="utf-8")
LOCALES = json.loads((ROOT / "locales.json").read_text(encoding="utf-8"))


def _edit_body() -> str:
    return HELPER.split("def edit_note", 1)[1].split("\ndef ", 1)[0]


class EditApiTests(unittest.TestCase):
    def test_the_routes(self):
        self.assertIn('@router.post("/notes/{note_id}/edit"', ENDPOINTS)
        self.assertIn('@router.get("/notes/{note_id}/text"', ENDPOINTS)

    def test_edit_is_owner_scoped_and_404s_for_a_stranger(self):
        body = _edit_body()

        self.assertIn("db.get_note_for_user(user_id, note_id)", body)
        self.assertIn('return ("not_found", None)', body)
        self.assertIn("status_code=404", ENDPOINTS.split("def edit(", 1)[1])

    def test_blank_text_is_refused_with_422(self):
        self.assertIn('return ("empty", None)', _edit_body())
        self.assertIn("status_code=422", ENDPOINTS.split("def edit(", 1)[1])
        self.assertIn("min_length=1, max_length=20000", SCHEMAS.split("class EditNoteRequest", 1)[1])

    def test_chunks_are_built_before_anything_is_written(self):
        body = _edit_body()

        self.assertLess(body.index("_build_chunks(clean)"), body.index("db.set_text("))
        self.assertLess(body.index("db.set_text("), body.index("db.delete_chunks("))
        self.assertLess(body.index("db.delete_chunks("), body.index("db.save_chunks("))

    def test_path_links_and_reminders_are_not_touched(self):
        body = _edit_body()

        for call in ("db.set_path", "db.toggle_link", "db.add_link", "db.create_reminder"):
            self.assertNotIn(call, body)

    def test_the_answer_carries_the_path_for_the_right_keyboard(self):
        self.assertIn('return ("ok", {"text": clean, "path": note["path"]})', _edit_body())

    def test_reading_the_text_is_owner_scoped(self):
        body = HELPER.split("def note_text", 1)[1].split("\ndef ", 1)[0]

        self.assertIn("db.get_note_for_user(user_id, note_id)", body)


class EditBotTests(unittest.TestCase):
    def test_edit_is_on_the_draft_and_the_filed_keyboards(self):
        capture = BOT.split("def _capture_keyboard", 1)[1].split("def _meta_line", 1)[0]
        filed = BOT.split("def _filed_keyboard", 1)[1].split("\ndef ", 1)[0]

        for keyboard in (capture, filed):
            self.assertIn('t(locale, "btn_edit"), callback_data=f"x:{note_id}"', keyboard)

    def test_the_prompt_quotes_the_current_text_with_a_force_reply(self):
        body = BOT.split("async def on_edit", 1)[1].split("async def ", 1)[0]

        self.assertIn("api.get_note_text(note_id, user_id)", body)
        self.assertIn("ForceReply(selective=True)", body)
        self.assertIn("current[:EDIT_PROMPT_CHARS]", body)
        self.assertIn("pending_edit[prompt.message_id]", body)

    def test_the_prompt_quote_fits_a_telegram_message(self):
        limit = int(re.search(r"EDIT_PROMPT_CHARS = (\d+)", BOT).group(1))

        self.assertLessEqual(limit + len(LOCALES["en"]["edit_prompt"]) + len(LOCALES["uk"]["edit_prompt"]), 4096)

    def test_the_pending_map_is_bounded(self):
        body = BOT.split("async def on_edit", 1)[1].split("async def ", 1)[0]

        self.assertIn("len(pending_edit) > 200", body)

    def test_a_reply_to_the_prompt_is_routed_before_it_becomes_a_note(self):
        body = BOT.split("async def handle_message", 1)[1].split("async def ", 1)[0]

        self.assertLess(body.index("pending_edit"), body.index("api.capture_text"))

    def test_the_reply_redraws_with_the_matching_keyboard(self):
        body = BOT.split("async def _apply_edit", 1)[1].split("async def ", 1)[0]

        self.assertIn("api.edit_note(info[\"note_id\"], msg.text", body)
        self.assertIn("_filed_keyboard(info[\"note_id\"], locale)", body)
        self.assertIn("_capture_keyboard(info[\"note_id\"], locale)", body)
        self.assertIn('edited.get("path")', body)

    def test_the_handler_is_registered(self):
        self.assertIn('CallbackQueryHandler(on_edit, pattern=r"^x:")', BOT)

    def test_locales_have_the_edit_strings(self):
        for locale, table in LOCALES.items():
            with self.subTest(locale=locale):
                for key in ("btn_edit", "edit_prompt", "edited"):
                    self.assertIn(key, table)

                self.assertIn("{text}", table["edit_prompt"])


class AtomizeRemovedTests(unittest.TestCase):
    def test_nothing_of_it_is_left(self):
        for source in (HELPER, ENDPOINTS, SCHEMAS, BOT, CLIENT, CONFIG):
            self.assertNotRegex(source, r"(?i)atomiz")

        for locale, table in LOCALES.items():
            with self.subTest(locale=locale):
                self.assertFalse([key for key in table if "atomize" in key])

    def test_the_old_callback_is_not_registered(self):
        self.assertNotIn('pattern=r"^a:"', BOT)


if __name__ == "__main__":
    unittest.main()
