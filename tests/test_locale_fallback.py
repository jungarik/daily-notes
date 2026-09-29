"""One locale fallback, decided in one place.

`users.language` is written only by the bot's `/lang`, so most users have NULL
and every surface falls back. When each vertical wrote its own
`normalize(x) or DEFAULT_LOCALE` they were free to disagree — and did: the
header labelled a folder «Вхідні» while the bot's enrichment wrote "Inbox" into
the note's path, permanently, because paths are stored localised.

These pin that the fallback is `i18n.resolve_locale` and that nothing reaches
around it.
"""

import re
import unittest
from pathlib import Path
from unittest.mock import patch

import i18n

ROOT = Path(__file__).parents[1]

# Everything that turns a stored language into a locale. `capture/` is excluded:
# the bot reads a locale the API already resolved, so its `or DEFAULT_LOCALE` is
# a missing-key guard rather than a second fallback policy.
SOURCE_DIRS = ("api", "agents", "tools", "common")


class ResolverTests(unittest.TestCase):
    def test_no_stored_language_gives_ukrainian(self):
        self.assertEqual("uk", i18n.resolve_locale(None))
        self.assertEqual("uk", i18n.resolve_locale(""))

    def test_a_stored_language_wins(self):
        self.assertEqual("en", i18n.resolve_locale("en"))
        self.assertEqual("en", i18n.resolve_locale("EN_us"))
        self.assertEqual("uk", i18n.resolve_locale("uk-UA"))

    def test_an_unsupported_language_falls_back_rather_than_raising(self):
        self.assertEqual("uk", i18n.resolve_locale("fr"))

    def test_the_default_is_ukrainian(self):
        """Spelled out, not derived: comparing the constant against itself
        would pass for whatever it were changed to."""
        self.assertEqual("uk", i18n.DEFAULT_LOCALE)

    def test_the_default_root_of_a_fresh_user_is_localised(self):
        """The line that put "Inbox" in people's vaults: with no stored
        language this is what enrichment writes into the path."""
        import config
        from common import helper

        _, default = helper.localized_root_folders(None)

        self.assertEqual("Вхідні", default)
        self.assertEqual("folder_inbox", config.DEFAULT_ROOT_FOLDER_KEY)


class SingleSourceTests(unittest.TestCase):
    def test_nothing_writes_its_own_fallback(self):
        """`normalize(x) or DEFAULT_LOCALE` is the pattern that let two
        surfaces drift apart. There is one resolver; this keeps it that way."""
        offending = []

        for folder in SOURCE_DIRS:
            for path in (ROOT / folder).rglob("*.py"):
                for number, line in enumerate(
                        path.read_text(encoding="utf-8").splitlines(), 1):
                    if re.search(r"normalize\(.*\)\s+or\s+", line):
                        offending.append(f"{path.relative_to(ROOT)}:{number}")

        self.assertEqual([], offending)

    def test_every_vertical_resolves_through_the_one_function(self):
        """Each of these decides a user's locale, and each must ask the same
        question. A new one that forgets is the drift starting again."""
        expected = {
            "api/telegram_bot/helper.py",
            "api/chat_v2/helper.py",
            "api/header/helper.py",
            "api/explorer/helper.py",
            "common/helper.py",
            "tools/finder/list_paths.py",
        }
        found = {
            str(path.relative_to(ROOT)).replace("\\", "/")
            for folder in SOURCE_DIRS
            for path in (ROOT / folder).rglob("*.py")
            if "resolve_locale" in path.read_text(encoding="utf-8")
        }

        self.assertEqual(expected, found)


class OverrideTests(unittest.TestCase):
    """The fallback is a deployment decision, so it has to be settable.

    `DEFAULT_LOCALE` is read at import, so these reload the module — and the
    restoring reload is an `addCleanup`, not a `finally`. A `finally` inside
    the `with` reloads while the patched environment is still in place, which
    leaves the fake value installed for every test that runs afterwards.
    """

    def setUp(self):
        import importlib

        self.addCleanup(importlib.reload, i18n)

    def test_app_default_locale_is_honoured(self):
        import importlib

        with patch.dict("os.environ", {"APP_DEFAULT_LOCALE": "en"}):
            reloaded = importlib.reload(i18n)

            self.assertEqual("en", reloaded.DEFAULT_LOCALE)
            self.assertEqual("en", reloaded.resolve_locale(None))

    def test_the_legacy_variable_still_works(self):
        """An existing deployment sets BOT_DEFAULT_LOCALE; it must not start
        silently meaning something else."""
        import importlib

        with patch.dict("os.environ", {"BOT_DEFAULT_LOCALE": "en"}, clear=False):
            reloaded = importlib.reload(i18n)

            self.assertEqual("en", reloaded.DEFAULT_LOCALE)


if __name__ == "__main__":
    unittest.main()
