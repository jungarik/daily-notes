"""Every webapp source file has to parse.

The rest of the webapp suite compares strings in the source, which is how a
JSX slip in `PathWheel.jsx` — a comment left beside its sibling inside a
`{cond && (...)}`, which JSX needs one root for — shipped green and failed
only in the deploy's `vite build`. esbuild is the parser that build uses, so
this runs each file through it. Skipped when the webapp's dependencies are not
installed (`npm ci` in `browser/webapp`), the same way the node-backed tests
skip without node.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

WEBAPP = Path(__file__).parents[1] / "browser" / "webapp"
ESBUILD = WEBAPP / "node_modules" / ".bin" / "esbuild"
SOURCES = sorted((WEBAPP / "src").rglob("*.js")) + sorted((WEBAPP / "src").rglob("*.jsx"))


@unittest.skipUnless(shutil.which("node") and ESBUILD.exists(),
                     "esbuild is not installed (npm ci in browser/webapp)")
class WebappCompilesTests(unittest.TestCase):
    def test_every_source_file_parses(self):
        for source in SOURCES:
            with self.subTest(file=source.relative_to(WEBAPP).as_posix()):
                done = subprocess.run(
                    [str(ESBUILD), str(source), "--loader:.js=jsx", "--log-level=error"],
                    capture_output=True, text=True)

                self.assertEqual(0, done.returncode, done.stderr)


if __name__ == "__main__":
    unittest.main()
