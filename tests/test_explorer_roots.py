"""The vault's root order: one source of truth, and the roster that carries it.

The Explorer and the filter sheet build their trees from localised path strings
and have no notion of a root key, so `Архів` can only be known to belong last if
the server says so. These pin that the roster is complete, ordered, localised,
and derived from `config.ROOT_FOLDERS` rather than restated per section.

The JS comparator that consumes the roster is covered in
`tests/test_root_order_js.py`, which runs the real module under node.
"""

import sys
import types
import unittest
from unittest.mock import patch

# `api.*.db` imports the shared psycopg pool at module load, which is absent
# here. Stub it just long enough to import the modules under test, then take it
# back out of `sys.modules`: leaving a fake `db` behind changes how *other* test
# modules import, which is a real way for one file to alter another's result.
_had_db = "db" in sys.modules

if not _had_db:
    _stub = types.ModuleType("db")
    _stub.cursor = lambda: None
    sys.modules["db"] = _stub

import config                                    # noqa: E402
import i18n                                      # noqa: E402
from api.explorer import helper as explorer      # noqa: E402
from api.header import helper as header          # noqa: E402
from common import helper as common              # noqa: E402

if not _had_db:
    del sys.modules["db"]


def _roots(language):
    with patch.object(explorer.db, "get_language", return_value=language):
        return explorer.list_roots(7)


class OrderSourceTests(unittest.TestCase):
    def test_every_root_declares_an_order_and_a_description(self):
        """Both halves are required: a root missing `order` would sort
        arbitrarily, one missing `description` breaks the classifier prompt."""
        for key, root in config.ROOT_FOLDERS.items():
            with self.subTest(root=key):
                self.assertIn("order", root)
                self.assertIn("description", root)

    def test_orders_are_unique(self):
        """Two roots sharing a number makes their relative order arbitrary —
        the exact thing explicit numbers were added to prevent."""
        orders = [root["order"] for root in config.ROOT_FOLDERS.values()]

        self.assertEqual(len(orders), len(set(orders)))

    def test_the_canonical_order(self):
        self.assertEqual(
            ("folder_inbox", "folder_projects", "folder_areas",
             "folder_resources", "folder_archive"),
            common.order_root_keys())

    def test_order_comes_from_the_numbers_not_the_line_positions(self):
        """Reversing the dict must not reverse the vault: the numbers decide."""
        reversed_dict = dict(reversed(list(config.ROOT_FOLDERS.items())))

        with patch.object(config, "ROOT_FOLDERS", reversed_dict):
            self.assertEqual("folder_inbox", common.order_root_keys()[0])


class RosterTests(unittest.TestCase):
    def test_all_five_roots_in_order(self):
        """Every root, including Archive: this is the vault's roster, not one
        screen's selection."""
        self.assertEqual(
            ["folder_inbox", "folder_projects", "folder_areas",
             "folder_resources", "folder_archive"],
            [root["key"] for root in _roots("uk")])

    def test_labels_are_localised(self):
        by_key = {root["key"]: root["label"] for root in _roots("uk")}

        self.assertEqual("Вхідні", by_key["folder_inbox"])
        self.assertEqual("Архів", by_key["folder_archive"])

    def test_no_stored_language_falls_back_to_ukrainian(self):
        """Only the bot writes `users.language`. Spelled out rather than
        derived from the constant, which would pass for any value."""
        self.assertEqual("uk", explorer.FALLBACK_LOCALE)
        self.assertEqual("Вхідні", _roots(None)[0]["label"])

    def test_the_roster_does_not_depend_on_the_vault_having_notes(self):
        """It is the set of roots that exist, not the ones in use — an empty
        vault still needs an ordered tree to render into."""
        self.assertEqual(5, len(_roots("uk")))


class HeaderSharesTheSourceTests(unittest.TestCase):
    """The header reports a prefix of the roster. Two lists declaring root
    order is how the Explorer and the header drift apart."""

    def test_the_header_reports_the_first_roots_of_the_roster(self):
        with patch.object(header.db, "get_language", return_value="uk"), \
                patch.object(header.db, "count_root_entries", return_value={}):
            reported = [entry["key"] for entry in header.stats(7)["stats"]]

        self.assertEqual(list(common.order_root_keys()[:4]), reported)

    def test_reordering_the_vault_reorders_the_header(self):
        """The proof they share a source: move Areas ahead of Projects in
        config and the header follows without being touched."""
        moved = {key: dict(root) for key, root in config.ROOT_FOLDERS.items()}
        moved["folder_areas"]["order"] = 15

        with patch.object(config, "ROOT_FOLDERS", moved), \
                patch.object(header.db, "get_language", return_value="uk"), \
                patch.object(header.db, "count_root_entries", return_value={}):
            reported = [entry["key"] for entry in header.stats(7)["stats"]]

        self.assertEqual("folder_areas", reported[1])


class DescriptionConsumerTests(unittest.TestCase):
    """The value shape changed from a string to a dict, so the two call sites
    that read the description have to keep working."""

    def test_localized_root_folders_maps_name_to_description(self):
        roots, default = common.localized_root_folders("uk")

        self.assertEqual("Вхідні", default)
        self.assertEqual(config.ROOT_FOLDERS["folder_archive"]["description"],
                         roots["Архів"])

    def test_it_is_returned_in_canonical_order(self):
        roots, _ = common.localized_root_folders("uk")

        self.assertEqual([i18n.t("uk", key) for key in common.order_root_keys()],
                         list(roots))


if __name__ == "__main__":
    unittest.main()
