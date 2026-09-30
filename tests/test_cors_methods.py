"""The CORS allow-list has to cover every verb the routers serve.

The Mini App is a separate origin, so every non-simple request is preceded by a
preflight. `CORSMiddleware` answers a preflight for an unlisted method with
**400 before the route is reached** — so adding an endpoint with a new verb and
forgetting this line produces a broken feature with a perfectly correct route
behind it. That is exactly how `DELETE /api/contextmenu/notes/{id}` shipped
dead: the handler, its tests and its UI were all right, and the browser never
got past OPTIONS.

Read as source rather than executed: FastAPI is not installed in every
environment this suite runs in, and the question here is a property of the
files.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN = ROOT / "api" / "main.py"

# Verbs a browser can send without a preflight anyway; the middleware still has
# to list them, but their absence would not produce this failure mode.
SIMPLE = {"GET", "HEAD", "POST"}


def _allowed_methods() -> set[str]:
    source = MAIN.read_text(encoding="utf-8")
    listed = re.search(r"allow_methods=\[([^\]]*)\]", source).group(1)

    return set(re.findall(r'"([A-Z]+)"', listed))


def _served_methods() -> dict[str, set[str]]:
    """Every `@router.<verb>` across the API, grouped by the file serving it."""
    served = {}

    for path in (ROOT / "api").rglob("endpoints.py"):
        verbs = set(re.findall(r"@router\.(get|post|put|patch|delete)\(",
                               path.read_text(encoding="utf-8")))

        if verbs:
            served[str(path.relative_to(ROOT)).replace("\\", "/")] = {
                verb.upper() for verb in verbs
            }

    return served


class CorsMethodTests(unittest.TestCase):
    def test_every_served_verb_is_allowed(self):
        allowed = _allowed_methods()
        missing = {
            source: sorted(verbs - allowed)
            for source, verbs in _served_methods().items()
            if verbs - allowed
        }

        self.assertEqual({}, missing,
                         "these verbs would fail CORS preflight with 400")

    def test_options_is_allowed(self):
        """The preflight itself. Without it the middleware cannot answer."""
        self.assertIn("OPTIONS", _allowed_methods())

    def test_delete_is_allowed(self):
        """Named explicitly because it is the one that broke, and because a
        generic check passes trivially if the routers ever lose their DELETE."""
        self.assertIn("DELETE", _allowed_methods())

    def test_the_routers_are_actually_being_read(self):
        """Guards the guard: a typo in the rglob or the regex would make
        `_served_methods` empty and every assertion above vacuous."""
        served = _served_methods()

        self.assertGreater(len(served), 5)
        self.assertIn("api/contextmenu/endpoints.py", served)
        self.assertIn("DELETE", served["api/contextmenu/endpoints.py"])

    def test_nothing_is_allowed_that_no_router_serves(self):
        """Not a security boundary — auth is per-request — but an allow-list
        naming verbs nothing answers is a stale line that outlives its reason."""
        served = set().union(*_served_methods().values())
        extra = _allowed_methods() - served - SIMPLE - {"OPTIONS"}

        self.assertEqual(set(), extra)


if __name__ == "__main__":
    unittest.main()
