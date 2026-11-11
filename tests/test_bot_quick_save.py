"""The Telegram bot's quick capture: a draft, then 💾 Save into the Inbox.

A captured note has no path — the existing "not in the vault yet" state — and
Save gives it the user's localised Inbox root, with no model call, no title and
no type. The section's helper cannot be imported here (its database layer needs
psycopg), so this reads the source, like the other section tests.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SECTION = ROOT / "api" / "telegram_bot"
HELPER = (SECTION / "helper.py").read_text(encoding="utf-8")
DB_SOURCE = (SECTION / "db.py").read_text(encoding="utf-8")
ENDPOINTS = (SECTION / "endpoints.py").read_text(encoding="utf-8")
BOT = (ROOT / "capture" / "Telegram_Bot" / "bot.py").read_text(encoding="utf-8")
CLIENT = (ROOT / "capture" / "Telegram_Bot" / "api_client.py").read_text(encoding="utf-8")
LOCALES = json.loads((ROOT / "locales.json").read_text(encoding="utf-8"))


class SaveTests(unittest.TestCase):
    def test_save_files_a_draft_in_the_localised_inbox(self):
        body = HELPER.split("def save_note", 1)[1].split("\n# =====", 1)[0]

        self.assertIn("_, inbox = _localized_roots(user_id)", body)
        self.assertIn("db.set_path(note_id, inbox)", body)

    def test_save_is_owner_scoped_and_returns_not_found(self):
        body = HELPER.split("def save_note", 1)[1]

        self.assertIn("db.get_note_for_user(user_id, note_id)", body)
        self.assertIn('return ("not_found", None)', body)

    def test_a_filed_note_keeps_its_path(self):
        body = HELPER.split("def save_note", 1)[1].split("\n# =====", 1)[0]

        self.assertRegex(body, r"if not note\[\"path\"\]:\n\s+_, inbox")

    def test_no_model_call_in_save(self):
        body = HELPER.split("def save_note", 1)[1].split("\n# =====", 1)[0]

        for name in ("get_client", "chat.completions", "_embed"):
            self.assertNotIn(name, body)

    def test_the_inbox_is_the_default_root(self):
        self.assertIn("i18n.t(locale, config.DEFAULT_ROOT_FOLDER_KEY)", HELPER)


class RemovedEnrichmentTests(unittest.TestCase):
    def test_the_classifier_prompt_and_writers_are_gone(self):
        for name in ("_enrich(", "enrich_note", "_normalize", "_root_block", "_vocabulary",
                     "_neighbour_hint", "_similar_block", "ENRICH_LLM_MODEL"):
            with self.subTest(name=name):
                self.assertNotIn(name, HELPER)

        for name in ("set_enrichment", "similar_notes", "set_metadata", "list_tags"):
            with self.subTest(name=name):
                self.assertNotIn(name, DB_SOURCE)

    def test_the_enrich_route_became_save(self):
        self.assertNotIn("/enrich", ENDPOINTS + CLIENT)
        self.assertIn('@router.post("/notes/{note_id}/save"', ENDPOINTS)
        self.assertIn("/notes/{note_id}/save", CLIENT)

    def test_link_suggestions_are_untouched(self):
        self.assertIn("def link_candidates", HELPER)
        self.assertIn("_TAG_BOOST", HELPER)


class BotTests(unittest.TestCase):
    def test_the_capture_keyboard_offers_save_not_enrich(self):
        keyboard = BOT.split("def _capture_keyboard", 1)[1].split("def _meta_line", 1)[0]

        self.assertIn('t(locale, "btn_save"), callback_data=f"s:{note_id}"', keyboard)
        self.assertNotIn("btn_enrich", BOT)

    def test_polish_atomize_cancel_are_unchanged(self):
        keyboard = BOT.split("def _capture_keyboard", 1)[1].split("def _meta_line", 1)[0]

        for button in ('"btn_atomize"', '"btn_polish"', '"btn_cancel"'):
            self.assertIn(button, keyboard)

    def test_old_enrich_buttons_still_route_to_save(self):
        self.assertIn('CallbackQueryHandler(on_save, pattern=r"^[es]:")', BOT)

    def test_save_shows_the_filed_keyboard_with_change_path_and_link(self):
        body = BOT.split("async def on_save", 1)[1].split("async def ", 1)[0]
        keyboard = BOT.split("def _filed_keyboard", 1)[1].split("def ", 1)[0]

        self.assertIn("_filed_keyboard(note_id, locale)", body)
        self.assertIn("btn_change_path", keyboard)
        self.assertIn("btn_link", keyboard)

    def test_a_failed_save_restores_the_save_button(self):
        body = BOT.split("async def on_save", 1)[1].split("async def ", 1)[0]

        self.assertIn("_capture_keyboard(note_id, locale)", body)

    def test_the_message_shows_only_what_the_note_has(self):
        line = BOT.split("def _meta_line", 1)[1].split("async def ", 1)[0]

        self.assertIn('meta.get("title")', line)
        self.assertIn('meta.get("path")', line)
        self.assertNotRegex(line, r"tags|priority")


class LocaleTests(unittest.TestCase):
    def test_both_languages_have_save_and_not_enrich(self):
        for locale, table in LOCALES.items():
            with self.subTest(locale=locale):
                self.assertIn("btn_save", table)
                self.assertNotIn("btn_enrich", table)
                self.assertNotIn("enriching", table)

    def test_capture_replies_say_draft(self):
        self.assertIn("Draft", LOCALES["en"]["saved"])
        self.assertTrue(re.search("Чернетка", LOCALES["uk"]["saved"]))


if __name__ == "__main__":
    unittest.main()
