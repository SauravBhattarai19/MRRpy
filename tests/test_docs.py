"""
The documentation site (docsite/) stays complete and correct:

* every catalogued setting is explained in exactly one settings table of the
  user manual (``<!-- settings: … -->``, expanded by tools/mkdocs_hooks.py);
* every ``[[NAME]]`` link points at a documented setting;
* every YAML block is a valid MRRpy configuration and every Python block parses;
* with mkdocs installed, the site builds with ``--strict`` (no broken links).
"""

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import textwrap

import pytest
import yaml

from MRRpy import Config
from MRRpy import config_schema as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docsite")


def _hooks():
    spec = importlib.util.spec_from_file_location(
        "mkdocs_hooks", os.path.join(ROOT, "tools", "mkdocs_hooks.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pages():
    for root, _dirs, files in os.walk(DOCS):
        for fn in sorted(files):
            if fn.endswith(".md"):
                path = os.path.join(root, fn)
                yield os.path.relpath(path, DOCS).replace(os.sep, "/"), open(path, encoding="utf-8").read()


_BLOCK = re.compile(r"^([ \t]*)```(\w+)[^\n]*\n(.*?)^\1```[ \t]*$", re.M | re.S)


def _blocks(lang):
    for page, text in _pages():
        for m in _BLOCK.finditer(text):
            if m.group(2) == lang:
                body = textwrap.dedent("\n".join(
                    line[len(m.group(1)):] if line.startswith(m.group(1)) else line
                    for line in m.group(3).splitlines()))
                yield page, body


def test_every_setting_is_documented_once():
    where = _hooks().scan(DOCS)                      # raises on unknown names / duplicates
    missing = [p.name for p in S.PARAMS if p.name not in where]
    assert not missing, f"settings missing from the manual's tables: {missing}"
    outside = {n: page for n, page in where.items() if not page.startswith("manual/")}
    assert not outside, f"settings tables outside the user manual: {outside}"


def test_pages_expand():
    hooks = _hooks()
    where = hooks.scan(DOCS)
    titles = hooks.page_titles(DOCS, where.values())
    for page, text in _pages():
        out = hooks.expand(text, page, where, titles)   # raises on an unknown [[NAME]]
        rest = hooks._strip_code(out)
        assert not hooks.TABLE.search(rest) and not hooks.INDEX.search(rest), page


def test_yaml_blocks_are_valid_configs():
    n = 0
    for page, body in _blocks("yaml"):
        data = yaml.safe_load(body)
        assert isinstance(data, dict), f"{page}: a YAML block is not a mapping"
        try:
            Config.from_dict(data)
        except Exception as exc:                      # noqa: BLE001 — report which block
            pytest.fail(f"{page}: invalid configuration block {list(data)}: {exc}")
        n += 1
    assert n >= 10


def test_python_blocks_parse():
    for page, body in _blocks("python"):
        try:
            ast.parse(body)
        except SyntaxError as exc:
            pytest.fail(f"{page}: Python block does not parse: {exc}\n{body}")


@pytest.mark.skipif(shutil.which("mkdocs") is None and importlib.util.find_spec("mkdocs") is None,
                    reason="mkdocs not installed (pip install -r docs-requirements.txt)")
def test_site_builds_strict(tmp_path):
    for mod in ("material", "mkdocstrings"):
        if importlib.util.find_spec(mod) is None:
            pytest.skip(f"{mod} not installed")
    res = subprocess.run([sys.executable, "-m", "mkdocs", "build", "--strict", "-q",
                          "-d", str(tmp_path / "site")],
                         cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
