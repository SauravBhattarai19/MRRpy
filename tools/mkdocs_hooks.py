# -*- coding: utf-8 -*-
"""
mkdocs_hooks.py — build-time helpers for the MRRpy documentation site.

Registered in ``mkdocs.yml`` under ``hooks:``.  Two pieces of syntax are
expanded in every page of ``docsite/``:

``<!-- settings: NAME NAME ... -->``  (on a line of its own)
    becomes a reference table of those ``Config`` settings, in the style of
    the GSSHA wiki's project-file card tables: setting, value, default and a
    description with every choice (and its integer code) and when the setting
    applies.  The text comes from the parameter catalogue
    (``MRRpy/config_schema.py``), so the manual always says exactly what the
    wizard, the notebook form and ``MRRpy explain`` say.  Each setting must be
    documented in exactly one table; ``tests/test_docs.py`` checks that every
    catalogued setting is.

``<!-- settings-index -->``
    becomes an A–Z list of every setting with a link to its table.

``[[NAME]]``
    becomes a link to the table row of setting NAME, from any page.
"""

import os
import posixpath
import re

import yaml

TABLE = re.compile(r"^<!--\s*settings:\s*(.*?)\s*-->[ \t]*$", re.M)
INDEX = re.compile(r"^<!--\s*settings-index\s*-->[ \t]*$", re.M)
LINK = re.compile(r"\[\[([A-Z][A-Z0-9_]+)\]\]")
INLINE_CODE = re.compile(r"(`[^`\n]*`)")
FENCE = re.compile(r"^([ \t]*)(```|~~~).*?^\1\2[ \t]*$", re.M | re.S)

_KIND_TEXT = {
    "text": "text",
    "file": "file path",
    "folder": "folder path",
    "float": "number",
    "int": "whole number",
    "bool": "`true` or `false`",
    "choice": "one choice: its name or its code",
    "multichoice": "a list of choices (names or codes)",
    "latlon": "`[latitude, longitude]` in degrees",
    "bbox": "`[west, south, east, north]` in degrees",
    "datetime": "`\"YYYY-MM-DD HH:MM\"`",
    "crs": "`\"EPSG:<code>\"` (a projection in metres)",
    "order_table": "`{stream order: value}`",
    "points": "a list of points",
    "qbf": "empty, a number (m³/s) or a formula",
    "channel_n": "empty, a number, `{order: n}`, `[[elevation, n], …]` or a raster path",
    "hg": "a preset name or `{w_a, w_b, d_a, d_b}`",
}


# ═════════════════════════════════════════════════════════════════════════════
# Where each setting is documented
# ═════════════════════════════════════════════════════════════════════════════
def _strip_code(text):
    """*text* with fenced code blocks blanked out (markers there are examples)."""
    return FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def scan(docs_dir):
    """
    {setting name: page path relative to *docs_dir*} for every settings table.

    Raises ValueError for an unknown name or a setting placed in two tables.
    """
    from MRRpy import config_schema as S

    where = {}
    for root, _dirs, files in os.walk(docs_dir):
        for fn in sorted(files):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, docs_dir).replace(os.sep, "/")
            with open(path, encoding="utf-8") as f:
                text = _strip_code(f.read())
            for m in TABLE.finditer(text):
                for name in m.group(1).split():
                    if name not in S.PARAM_BY_NAME:
                        raise ValueError(f"{rel}: unknown setting {name!r} in a settings table")
                    if name in where:
                        raise ValueError(f"{name} is documented twice: {where[name]} and {rel}")
                    where[name] = rel
    return where


def page_titles(docs_dir, pages):
    """{page path: its first '# ' heading} for *pages*."""
    titles = {}
    for rel in set(pages):
        with open(os.path.join(docs_dir, rel), encoding="utf-8") as f:
            for line in f:
                if line.startswith("# "):
                    titles[rel] = line[2:].strip()
                    break
    return titles


def _href(where, name, page):
    """Relative link from *page* to the row of setting *name*."""
    target = where[name]
    rel = posixpath.relpath(target, posixpath.dirname(page) or ".")
    return f"{rel}#{name}"


# ═════════════════════════════════════════════════════════════════════════════
# Table cells
# ═════════════════════════════════════════════════════════════════════════════
def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", "<br>")


def _yaml_value(value):
    from MRRpy.interactive.render import plain

    return yaml.safe_dump(plain(value), default_flow_style=True, width=1000,
                          allow_unicode=True, sort_keys=False).strip().removesuffix("\n...").strip()


def _num(v):
    from MRRpy.config_schema import _g

    return _g(v)


def value_text(p):
    """What kind of value a setting takes, with its unit, range and an example."""
    text = _KIND_TEXT.get(p.kind, p.kind)
    if p.kind in ("float", "int"):
        limits = []
        if p.min is not None:
            limits.append(("> " if p.min_exclusive else "≥ ") + _num(p.min))
        if p.max is not None:
            limits.append("≤ " + _num(p.max))
        if limits:
            text += ", " + " and ".join(limits)
    if p.unit and p.kind not in ("latlon", "bbox"):
        text += f"<br>unit: {p.unit}"
    if p.example is not None and p.kind not in ("bool", "choice", "multichoice"):
        text += f"<br>e.g. `{_yaml_value(p.example)}`"
    return text


def default_text(p):
    from MRRpy.interactive.render import _is_builtin_file

    value = p.default
    if _is_builtin_file(p, value):
        return f"the table that ships with MRRpy (`{os.path.basename(value)}`)"
    if value is None:
        return "empty (`null`)"
    if value == "":
        return "empty"
    return f"`{_yaml_value(value)}`"


def _choice_lines(p):
    from MRRpy import config_schema as S

    lines = []
    for code, (value, label) in enumerate(S.choices_for(p)):
        rest = label.split(" — ", 1)[1] if " — " in label else ""
        line = f"`{code}` · `{value}`"
        if rest:
            line += f" — {rest}"
        lines.append(line)
    return lines


def _condition_md(p, where, page):
    """'applies when' in words, with every setting name linked."""
    from MRRpy import config_schema as S

    text = S.condition_text(p)
    if text == "always":
        return ""

    def link(m):
        name = m.group(0)
        if name in where:
            return f"[`{name}`]({_href(where, name, page)})"
        return f"`{name}`"

    names = sorted(S.PARAM_BY_NAME, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b")
    return pattern.sub(link, text)


def description(p, where, page):
    from MRRpy import config_schema as S

    parts = [p.help]
    if p.kind in ("choice", "multichoice"):
        head = "**Choices** (pick one)" if p.kind == "choice" else "**Choices** (any combination)"
        parts.append(head + ":<br>" + "<br>".join(_choice_lines(p)))
    elif p.kind in ("qbf", "channel_n", "hg"):
        parts.append("**Forms:** " + "; ".join(m.label for m in S.modes_for(p)) + ".")
    elif p.kind == "points":
        keys = "`name`, `lat`, `lon`" + (", `csv`" if p.needs_csv else "")
        parts.append(f"Each point has {keys}; optional `snap_to_channel` (default true) and "
                     "`snap_radius_cells`. Instead of `lat`/`lon` you can give `row`/`col` "
                     "or `easting`/`northing`.")
    if p.optional and p.none_label:
        parts.append(f"Empty (`null`) means: {p.none_label}.")
    cond = _condition_md(p, where, page)
    if cond:
        parts.append(f"**Applies when** {cond}.")
    return "<br><br>".join(_cell(x) for x in parts)


def settings_table(names, where, page):
    """Markdown table for the settings *names*, as shown on *page*."""
    from MRRpy import config_schema as S

    rows = ["| Setting | Value | Default | Description |",
            "|---|---|---|---|"]
    for name in names:
        p = S.param(name)
        setting = f'<span id="{p.name}"></span>**`{p.name}`**<br>{_cell(p.label)}'
        if p.level == "advanced":
            setting += "<br>*advanced*"
        rows.append("| " + " | ".join([setting, _cell(value_text(p)), _cell(default_text(p)),
                                       description(p, where, page)]) + " |")
    return "\n".join(rows)


def settings_index(where, titles, page):
    """A–Z table of every setting, linked to the page that documents it."""
    from MRRpy import config_schema as S

    rows = ["| Setting | What it is | Documented in |", "|---|---|---|"]
    for name in sorted(where):
        p = S.param(name)
        target = where[name]
        rows.append(f"| [`{name}`]({_href(where, name, page)}) | {_cell(p.label)} | "
                    f"{_cell(titles.get(target, target))} |")
    return "\n".join(rows)


def expand(markdown, page, where, titles):
    """Expand the settings syntax in one page's *markdown* (code blocks untouched)."""
    pieces, last = [], 0
    for m in FENCE.finditer(markdown):
        pieces.append((markdown[last:m.start()], True))
        pieces.append((m.group(0), False))
        last = m.end()
    pieces.append((markdown[last:], True))

    def table(m):
        return settings_table(m.group(1).split(), where, page)

    def link(m):
        name = m.group(1)
        if name not in where:
            raise ValueError(f"{page}: [[{name}]] is not a documented setting")
        return f"[`{name}`]({_href(where, name, page)})"

    out = []
    for text, is_prose in pieces:
        if is_prose:
            text = TABLE.sub(table, text)
            text = INDEX.sub(lambda m: settings_index(where, titles, page), text)
            # [[NAME]] outside `inline code` only
            parts = INLINE_CODE.split(text)
            parts[::2] = [LINK.sub(link, p) for p in parts[::2]]
            text = "".join(parts)
        out.append(text)
    return "".join(out)


# ═════════════════════════════════════════════════════════════════════════════
# MkDocs hooks
# ═════════════════════════════════════════════════════════════════════════════
_STATE = {}


def on_config(config, **kwargs):
    docs_dir = config["docs_dir"]
    where = scan(docs_dir)
    _STATE["where"] = where
    _STATE["titles"] = page_titles(docs_dir, where.values())
    return config


def on_page_markdown(markdown, page, config, files, **kwargs):
    return expand(markdown, page.file.src_uri, _STATE["where"], _STATE["titles"])
