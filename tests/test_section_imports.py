"""Every section's modules must actually import.

This file exists because of a bug it would have caught: `api/addnote/helper.py`
called `db.replace_chunks(...)` while importing no `db` at all. A `NameError`
on the first save, and the whole suite was green — because every assertion
about that code read the file as *text*, and the one test that imported the
module never called the function.

So: import each vertical's `endpoints`, `helper`, `db` and `schemas` for real,
and walk each module's functions for names that resolve to nothing. The first
catches a bad import or a typo at module level; the second catches a global
used inside a function body, which is exactly where the missed one hid.

`psycopg` and `file_store` are stubbed because they are absent here, and the
stubs are removed afterwards — a fake left in `sys.modules` changes how other
test files import.
"""

import ast
import builtins
import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
API = ROOT / "api"
MODULES = ("endpoints", "helper", "db", "schemas")

# Sections only; `api/main.py` wires FastAPI and `api/telegram_bot` pulls in the
# OpenAI client at import, which is not what this file is about.
SECTIONS = sorted(path.name for path in API.iterdir()
                  if (path / "endpoints.py").exists() and path.name != "telegram_bot")

# FastAPI and pydantic are not installed in every environment this suite runs
# in (`tests/test_cors_methods.py` makes the same allowance), so the *import*
# half skips there. The AST half below needs nothing and runs everywhere — and
# it is the half that catches the bug this file was written for.
HAS_WEB = all(importlib.util.find_spec(name) is not None
              for name in ("fastapi", "pydantic"))


def _stub(name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(name)

    for key, value in attributes.items():
        setattr(module, key, value)

    return module


class _Stubs:
    """Install the absent third-party modules, then take them back out."""

    def __enter__(self):
        self.installed = []

        for name, attributes in (
            ("psycopg", {"connect": lambda *a, **k: None}),
            ("psycopg.types", {}),
            ("psycopg.types.json", {"Json": lambda value: value}),
            ("psycopg_pool", {"ConnectionPool": object}),
        ):
            if name not in sys.modules:
                sys.modules[name] = _stub(name, **attributes)
                self.installed.append(name)

        return self

    def __exit__(self, *exc):
        for name in self.installed:
            sys.modules.pop(name, None)

        # The sections themselves, so the next test file imports them fresh.
        for name in list(sys.modules):
            if name.startswith("api.") or name == "db":
                sys.modules.pop(name, None)

        return False


@unittest.skipUnless(HAS_WEB, "fastapi/pydantic are not installed")
class ImportTests(unittest.TestCase):
    def test_every_section_module_imports(self):
        """Module level: a missing or misspelled import fails here."""
        with _Stubs():
            for section in SECTIONS:
                for name in MODULES:
                    if not (API / section / f"{name}.py").exists():
                        continue

                    with self.subTest(module=f"api.{section}.{name}"):
                        importlib.import_module(f"api.{section}.{name}")


class SectionRosterTests(unittest.TestCase):
    def test_the_sections_were_found(self):
        """A glob that matched nothing would make every test here vacuous."""
        self.assertIn("addnote", SECTIONS)
        self.assertGreater(len(SECTIONS), 5)


class UndefinedNameTests(unittest.TestCase):
    """Names used inside function bodies that nothing provides.

    An import check cannot see these — `db.replace_chunks(...)` inside a
    function is perfectly importable and only fails when called. This walks
    each module's AST, collects what it defines or imports, and flags any
    other bare name that is loaded and is not a builtin or a local.

    Deliberately conservative: it only looks at the *root* of an attribute
    chain (`db` in `db.replace_chunks`) and at plain name loads, which is the
    shape of the bug without the false positives a real type checker would
    need to resolve properly.
    """

    def _undefined(self, path: Path) -> list[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defined = set(dir(builtins))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                defined.update((alias.asname or alias.name.split(".")[0])
                               for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                defined.update((alias.asname or alias.name) for alias in node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
                defined.update(arg.arg for arg in node.args.args)
                defined.update(arg.arg for arg in node.args.kwonlyargs)
            elif isinstance(node, ast.ClassDef):
                defined.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, (ast.comprehension,)):
                for name in ast.walk(node.target):
                    if isinstance(name, ast.Name):
                        defined.add(name.id)

        used = {node.id for node in ast.walk(tree)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}

        return sorted(used - defined)

    def test_no_section_module_uses_a_name_it_does_not_have(self):
        for section in SECTIONS:
            for name in MODULES:
                path = API / section / f"{name}.py"

                if not path.exists():
                    continue

                with self.subTest(module=f"api.{section}.{name}"):
                    self.assertEqual([], self._undefined(path))

    def test_the_check_catches_the_bug_it_was_written_for(self):
        """Guards the guard: a module calling `db.x` without importing `db`
        must be reported, or this file is decoration."""
        with_bug = Path(__file__).parent / ".undefined_probe.py"
        with_bug.write_text("def save(note_id):\n    db.replace_chunks(note_id, [])\n",
                            encoding="utf-8")
        try:
            self.assertIn("db", self._undefined(with_bug))
        finally:
            # Best effort: some sandboxes refuse unlink inside the repo.
            try:
                with_bug.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
