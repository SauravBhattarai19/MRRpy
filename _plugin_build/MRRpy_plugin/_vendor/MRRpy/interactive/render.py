# -*- coding: utf-8 -*-
"""
render.py
=========
Turn a ``Config`` into text people can read: a commented YAML file, the
equivalent Python code, a plain-language run summary, and per-setting help.
Pure Python (PyYAML only) — used by the CLI, the terminal wizard and the
Jupyter form alike.
"""

import datetime as _dt
import os
import pprint
import textwrap

from .. import config_schema as S
from ..config import Config

_WIDTH = 79


# ═════════════════════════════════════════════════════════════════════════════
# YAML
# ═════════════════════════════════════════════════════════════════════════════
class Unrepresentable(ValueError):
    """A value (e.g. a Python function) that a YAML/JSON file cannot hold."""


def plain(value):
    """*value* as YAML/JSON-safe builtins (tuples → lists); raises Unrepresentable."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if hasattr(value, "item") and not isinstance(value, (list, tuple, dict)):
        return value.item()                               # numpy scalar
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, (str, int)) or isinstance(k, bool):
                raise Unrepresentable(f"dictionary key {k!r}")
            out[k] = plain(v)
        return out
    raise Unrepresentable(type(value).__name__)


def yaml_entry(name, value):
    """'NAME: value' as YAML, flow style for short lists/mappings ([27.6, 85.3])."""
    import yaml

    data = plain(value)

    def flow(x):
        return yaml.safe_dump(x, default_flow_style=True, width=1000,
                              allow_unicode=True, sort_keys=False).strip()

    def leafy(x):
        items = x.values() if isinstance(x, dict) else x
        return all(not isinstance(i, (list, dict)) for i in items)

    if isinstance(data, (list, dict)) and data and leafy(data):
        return f"{name}: {flow(data)}"
    if isinstance(data, list) and data and all(isinstance(i, (list, dict)) for i in data):
        return f"{name}:\n" + "\n".join(f"  - {flow(i)}" for i in data)
    return yaml.safe_dump({name: data}, default_flow_style=False, width=1000,
                          allow_unicode=True, sort_keys=False).strip()


def _comment(text, indent="# "):
    return [indent + line if line else indent.rstrip()
            for line in textwrap.wrap(text, _WIDTH - len(indent)) or [""]]


def param_notes(p, values=None):
    """Short extra lines about a param: choices, what empty means, when it applies."""
    notes = []
    if p.kind in ("choice", "multichoice"):
        notes.append("Choices (name or number): " + ", ".join(
            f"{i}={c}" for i, (c, _) in enumerate(S.choices_for(p))))
        if p.kind == "multichoice":
            notes[-1] += "  — a list"
    elif p.kind in ("qbf", "channel_n", "hg"):
        notes.append("Forms: " + "; ".join(m.label for m in S.modes_for(p)))
    elif p.kind == "points":
        keys = "name, lat, lon" + (", csv" if p.needs_csv else "")
        notes.append(f"A list of points, each {{{keys}}} (optional: "
                     "snap_to_channel, snap_radius_cells; or row/col, easting/northing).")
    elif p.kind == "order_table":
        notes.append("A mapping {stream order: value}.")
    if p.optional and p.none_label:
        notes.append(f"null means: {p.none_label}.")
    if values is not None and not S.is_visible(p, values):
        notes.append(f"Not used with your current choices (applies when "
                     f"{S.condition_text(p)}).")
    return notes


def render_yaml(cfg, full=True, title=None, source="MRRpy init-config"):
    """
    A commented YAML config for *cfg*, grouped by section.

    full=True   every setting, with its explanation (a complete reference file).
    full=False  only the settings that matter for these choices (basic ones)
                plus anything changed from the defaults — a short, readable file.
    """
    values = S.values_of(cfg)
    changed = S.config_changes(cfg)
    lines = []
    lines += [f"# {title or 'MRRpy configuration'}",
              f"# Written by `{source}` on {_dt.date.today().isoformat()}.",
              "#",
              "#   Check it:              MRRpy validate -c <this file>",
              "#   Run it:                MRRpy run -c <this file>",
              "#   Explain a setting:     MRRpy explain <NAME>",
              "#   Change it by questions: MRRpy wizard --edit <this file>",
              "#",
              "# Settings with a fixed list of options accept the name or its number.",
              "# Relative paths are relative to the folder you run MRRpy from."]
    skipped = 0
    for sec in S.SECTIONS:
        params = [p for p in S.PARAMS if p.section == sec.key]
        if not full:
            keep = [p for p in params
                    if p.name in changed
                    or (p.level == "basic" and S.is_visible(p, values))]
            skipped += len(params) - len(keep)
            params = keep
        if not params:
            continue
        lines += ["", "", "# " + "=" * (_WIDTH - 2),
                  f"# {S.SECTIONS.index(sec) + 1}. {sec.title}",
                  *_comment(sec.intro),
                  "# " + "=" * (_WIDTH - 2)]
        for p in params:
            value = getattr(cfg, p.name)
            if _is_builtin_file(p, value):
                lines.append("")
                lines += _comment(f"{p.title} — {p.help}")
                lines.append(f"# {p.name}: <the table shipped with MRRpy>   "
                             "(uncomment and give a path to use your own)")
                continue
            lines.append("")
            lines += _comment(f"{p.title} — {p.help}")
            for note in param_notes(p, values):
                lines += _comment(note, "#   ")
            try:
                lines += yaml_entry(p.name, value).splitlines()
            except Unrepresentable as exc:
                lines += _comment(f"{p.name} is set to a Python {exc} that a YAML file "
                                  "cannot hold; set it in Python instead.", "# ")
                lines.append(f"# {p.name}: <python value>")
    if not full and skipped:
        lines += ["", "",
                  f"# The other {skipped} settings keep their defaults. To see and edit "
                  "them all:",
                  "#   MRRpy init-config --full -o all_settings.yaml     (every setting, "
                  "explained)",
                  "#   MRRpy wizard --edit <this file> --advanced"]
    return "\n".join(lines) + "\n"


def _is_builtin_file(p, value):
    """A default file that ships inside the package (machine-specific path)."""
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return (p.kind == "file" and isinstance(value, str) and value == p.default
            and os.path.isabs(value) and value.startswith(pkg))


def save_yaml(cfg, path, full=False, **kw):
    """Write render_yaml(cfg) to *path* (creating its folder); returns the path."""
    path = os.path.expanduser(str(path))
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_yaml(cfg, full=full, **kw))
    return path


# ═════════════════════════════════════════════════════════════════════════════
# Python
# ═════════════════════════════════════════════════════════════════════════════
def to_python(cfg, run=True):
    """Python code that rebuilds *cfg* (only the settings changed from the defaults)."""
    changed = S.config_changes(cfg)
    out = ["from MRRpy import Config, run_pipeline", "", "cfg = Config("]
    later = []
    for name, value in changed.items():
        if callable(value):
            later.append(f"# cfg.{name} = ...   # your custom Python rule (not shown)")
            continue
        text = pprint.pformat(value, width=70, sort_dicts=False)
        text = text.replace("\n", "\n" + " " * (5 + len(name)))
        out.append(f"    {name}={text},")
    out.append(")")
    out += later
    out.append("cfg.update_output_paths()   # place every output file in OUTPUT_DIR")
    if run:
        out += ["cfg.validate()              # stops with a clear message if something is wrong",
                "results = run_pipeline(cfg)"]
    return "\n".join(out) + "\n"


# ═════════════════════════════════════════════════════════════════════════════
# Plain-language summary
# ═════════════════════════════════════════════════════════════════════════════
def _fmt(v):
    return S._g(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def describe_run(cfg):
    """A few plain sentences saying what this configuration will do."""
    v = S.values_of(cfg)
    out = []

    # Terrain
    if v["DEM_PATH"]:
        out.append(f"Terrain: the DEM file {v['DEM_PATH']}.")
    elif v["DEM_BOUNDS_WGS84"]:
        w, s, e, n = v["DEM_BOUNDS_WGS84"]
        res = f" at {_fmt(v['DEM_SCALE_M'])} m" if v["DEM_SCALE_M"] else ""
        out.append(f"Terrain: download {v['DEM_SOURCE']}{res} for longitude "
                   f"{_fmt(w)} to {_fmt(e)}, latitude {_fmt(s)} to {_fmt(n)}.")
    else:
        out.append("Terrain: not set yet — give a DEM file or an area to download.")
    lat, lon = v["OUTPUT_POINT"]
    out.append(f"Outlet: latitude {_fmt(lat)}, longitude {_fmt(lon)}; the grid uses "
               f"{v['TARGET_CRS_EPSG']}.")

    # Rain
    m = v["PRECIP_METHOD"]
    inflows = v["ROUTING_INFLOW_BC"] or []
    if m == "uniform":
        i, d = float(v["RAIN_INTENSITY_MM_HR"]), float(v["RAIN_DURATION_HOURS"])
        if i > 0 and d > 0:
            out.append(f"Rain: {_fmt(i)} mm/h for {_fmt(d)} h everywhere "
                       f"({_fmt(round(i * d, 3))} mm in total).")
        elif inflows:
            out.append("Rain: none — only the inflow hydrographs are routed.")
        else:
            out.append("Rain: none, and no inflow hydrograph — nothing will flow.")
    elif m in ("thiessen", "idw"):
        how = "nearest gauge" if m == "thiessen" else "distance-weighted"
        out.append(f"Rain: gauge records ({how}) from "
                   f"{v['PRECIP_TIMESERIES_FILE'] or '(rainfall CSV not set)'}.")
    else:
        start = v["EVENT_START_UTC"] or "(storm start not set)"
        out.append(f"Rain: NASA IMERG satellite rain from {start} UTC.")
    if v["RAIN_SNOW_ELEV_LOW"] is not None or v["RAIN_SNOW_ELEV_HIGH"] is not None:
        out.append(f"Snow: precipitation above {_fmt(v['RAIN_SNOW_ELEV_HIGH'])} m is "
                   "treated as snow and does not run off.")

    # Runoff
    r = v["RUNOFF_SOURCE"]
    if r == "none":
        out.append("Runoff: all rain runs off (no infiltration losses).")
    elif r == "coefficient":
        out.append(f"Runoff: fixed runoff fractions from {v['RUNOFF_COEFFICIENT_PATH'] or '(raster not set)'}.")
    elif r == "raster":
        out.append(f"Runoff: runoff maps listed in {v['RUNOFF_RASTER_MANIFEST'] or '(list not set)'}.")
    elif r == "scs_cn":
        src = {"scalar": f"CN {_fmt(v['RUNOFF_CN'])} everywhere",
               "gee": "the GCN250 global map",
               "raster": f"the map {v['RUNOFF_CN_PATH'] or '(not set)'}"}[v["RUNOFF_CN_SOURCE"]]
        wet = {"i": "dry", "ii": "normal", "iii": "wet"}[v["RUNOFF_CN_AMC"]]
        out.append(f"Runoff: SCS curve number from {src}, {wet} soil.")
    else:
        names = {"impervious": "paved areas", "infiltration_excess":
                 "infiltration excess (Green-Ampt)",
                 "saturation_excess": "saturation excess (VSA-OPM)"}
        mech = [names[x] for x in v["RUNOFF_MECHANISMS"]]
        out.append("Runoff: physical — " + (", ".join(mech) or "no process selected") + ".")

    # Surface and channels
    n_src = v["MANNINGS_N_SOURCE"]
    ground = (f"Manning's n {_fmt(v['MANNINGS_N'])} on the ground" if n_src == "scalar"
              else f"Manning's n from the {n_src} map")
    ch_mode = S.mode_of(S.param("MANNINGS_N_CHANNEL"), v["MANNINGS_N_CHANNEL"])
    channel = {"off": "the same in rivers", "value": f"{_fmt(v['MANNINGS_N_CHANNEL'])} in rivers",
               "order": "a value per stream order in rivers",
               "elevation": "values by elevation in rivers",
               "raster": "a raster in rivers", "custom": "a custom rule in rivers"}[ch_mode]
    out.append(f"Roughness: {ground}, {channel}.")
    if v["CHANNEL_ROUTING"]:
        area = v["CHANNEL_MIN_AREA_KM2"]
        where = (f"cells draining more than {_fmt(area)} km²" if area is not None
                 else "the top 1 % of cells by drainage area")
        g = v["CHANNEL_GEOMETRY"]
        if g == "discharge":
            q = v["CHANNEL_QBF_M3S"]
            kind = S.mode_of(S.param("CHANNEL_QBF_M3S"), q)
            size = {"auto": "the automatic global bankfull-flow estimate",
                    "value": f"a bankfull flow of {_fmt(q)} m³/s",
                    "formula": f"the bankfull-flow formula {q}"}[kind]
        elif g == "area":
            hg = v["CHANNEL_HG"]
            size = f"the {hg if isinstance(hg, str) else 'custom'} width/depth curve"
        else:
            size = "the stream-order tables"
        out.append(f"Rivers: {where}, sized from {size}.")
    else:
        out.append("Rivers: no separate channel; water spreads over whole cells.")

    # Routing
    every = int(v["OUTPUT_INTERVAL_SECONDS"])
    every_txt = f"{_fmt(every / 60)} min" if every % 60 == 0 else f"{every} s"
    out.append(f"Routing: {v['ROUTING_SCHEME']} for {_fmt(v['TOTAL_SIMULATION_TIME_HOURS'])} h, "
               f"results every {every_txt}.")
    if inflows:
        out.append(f"Inflows: {len(inflows)} upstream hydrograph(s).")
    gauges = v["ROUTING_GAUGES"] or []
    extra = []
    if gauges:
        extra.append(f"{len(gauges)} virtual gauge(s)")
    if v["SAVE_FIELDS"]:
        extra.append("maps of " + ", ".join(v["FIELD_VARS"]))
    out.append("Outputs: the outlet hydrograph" + ("".join(", " + x for x in extra))
               + f", in {v['OUTPUT_DIR']}.")
    out.append(f"Computer: {v['BACKEND'].upper()}.")

    uses = S.earth_engine_uses(v)
    project = v["GEE_PROJECT"] or os.environ.get("GEE_PROJECT")
    need = [w for w, req in uses if req]
    maybe = [w for w, req in uses if not req]
    if need:
        state = f"project {project}" if project else "PROJECT NOT SET"
        out.append(f"Earth Engine ({state}): needed for " + ", ".join(need) + ".")
    if maybe:
        out.append("Earth Engine (optional): " + ", ".join(maybe) + ".")
    if not uses:
        out.append("Runs fully offline (no Earth Engine downloads).")
    return out


# ═════════════════════════════════════════════════════════════════════════════
# Help on one setting, or a search
# ═════════════════════════════════════════════════════════════════════════════
def explain_param(p):
    """A help card for one parameter."""
    sec = S.SECTION_BY_KEY[p.section]
    default = p.default
    lines = [f"{p.name} — {p.title}",
             f"  Section: {sec.title} ({p.level})", ""]
    lines += ["  " + ln for ln in textwrap.wrap(p.help, _WIDTH - 2)]
    lines.append("")
    if p.kind in ("choice", "multichoice"):
        lines.append("  Choices (type the name or the number):")
        lines += [f"    {i}  {label}" for i, (_c, label) in enumerate(S.choices_for(p))]
    elif p.kind in ("qbf", "channel_n", "hg"):
        lines.append("  Forms it can take:")
        for m in S.modes_for(p):
            lines.append(f"    - {m.label}")
        if p.kind == "qbf":
            from ..core.routing.qbf import describe_presets
            lines += ["  Formula presets:"] + ["  " + ln for ln in describe_presets().splitlines()]
    shown = S.format_value(p, default) if default not in (None, "") else (p.none_label or "empty")
    lines.append(f"  Default: {shown}")
    if p.min is not None or p.max is not None:
        rng = []
        if p.min is not None:
            rng.append(f"{'more than' if p.min_exclusive else 'at least'} {p.min:g}")
        if p.max is not None:
            rng.append(f"at most {p.max:g}")
        lines.append("  Allowed: " + " and ".join(rng))
    if p.optional and p.none_label:
        lines.append(f"  Empty (null) means: {p.none_label}")
    lines.append(f"  Applies when: {S.condition_text(p)}")
    try:
        example = p.example if p.example is not None else default
        y = yaml_entry(p.name, example)
        lines.append(f"  Example in a YAML file:  {y.splitlines()[0]}")
        lines += [f"                           {ln}" for ln in y.splitlines()[1:]]
    except Unrepresentable:
        pass
    return "\n".join(lines)


def search_params(query):
    """Params whose name, label or help mention every word of *query* (ranked)."""
    words = [w.lower() for w in str(query).replace("_", " ").split() if w]
    scored = []
    for p in S.PARAMS:
        name = p.name.lower().replace("_", " ")
        text = f"{name} {p.label.lower()} {p.help.lower()}"
        if all(w in text for w in words):
            score = sum(3 if w in name else 2 if w in p.label.lower() else 1 for w in words)
            scored.append((-score, S.PARAMS.index(p), p))
    return [p for *_r, p in sorted(scored)]


def explain(query):
    """
    Help text for a setting name, or a search over all settings.

        explain("ROUTING_SCHEME")   # one setting, in detail
        explain("manning")          # every setting that mentions Manning
    """
    q = str(query).strip()
    if not q:
        return "Give a setting name (e.g. ROUTING_SCHEME) or a word to search for."
    if q.upper() in S._BY_UPPER:
        return explain_param(S._BY_UPPER[q.upper()])
    if q.upper() in S.NOT_ASKED:
        return f"{q.upper()} is not set by hand: {S.NOT_ASKED[q.upper()]}."
    hits = search_params(q)
    if not hits:
        try:
            S.param(q)
        except KeyError as exc:
            return str(exc).strip("'\"") + " (Try a single word, e.g. 'rain'.)"
    lines = [f"Settings matching {q!r}:"]
    width = max(len(p.name) for p in hits)
    for p in hits:
        lines.append(f"  {p.name:<{width}}  {p.title}")
    lines.append("")
    lines.append("For details: MRRpy explain <NAME>")
    return "\n".join(lines)


def list_settings(level=None):
    """Every catalogued setting, grouped by section (for `MRRpy explain --all`)."""
    lines = []
    for i, sec in enumerate(S.SECTIONS, 1):
        lines.append(f"{i}. {sec.title}")
        for p in S.PARAMS:
            if p.section == sec.key and (level is None or p.level == level):
                tag = "" if p.level == "basic" else "  (advanced)"
                lines.append(f"   {p.name:<32} {p.title}{tag}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def default_config():
    """A fresh Config with every default (convenience for the front-ends)."""
    return Config()
