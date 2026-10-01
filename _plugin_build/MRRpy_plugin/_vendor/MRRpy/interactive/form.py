# -*- coding: utf-8 -*-
"""
form.py
=======
``ConfigForm`` — a step-by-step form (laid out like the QGIS plugin) to build,
check, save and run an MRRpy configuration in Jupyter (JupyterLab, Notebook 7,
VS Code, Colab).  Needs ipywidgets (``pip install MRRpy[notebook]``); the map
picker also uses ipyleaflet when it is installed.

    from MRRpy import ConfigForm
    form = ConfigForm()            # or ConfigForm("run.yaml") to edit a file
    form                           # shows the form

    cfg = form.config              # the Config, ready for run_pipeline(cfg)

The steps are tabs with Next/Back buttons:

    1 Terrain → 2 Coordinate system → 3 Precipitation → 4 Runoff → 5 Routing → 6 Run

Every choice opens its own branch right underneath it, and only while it is
selected — e.g. Precipitation asks *design storm / rain gauges / satellite*
first, and Thiessen-or-IDW appears only for gauges or satellite rain.  The
tree is derived from the parameter catalogue (MRRpy.config_schema), the same
one the terminal wizard uses, so both always offer the same settings.

Accessibility: every input has a real label, every explanation is visible
text (not a hover tooltip), problems are written out in words, long labels
wrap instead of being cut, and everything works from the keyboard.
"""

import contextlib
import html
import io
import os
import time
import traceback

try:
    import ipywidgets as W
except ImportError as exc:   # pragma: no cover - exercised without ipywidgets
    raise ImportError(
        "The notebook form needs ipywidgets: pip install MRRpy[notebook] "
        "(or: pip install ipywidgets).  Without it you can use the text wizard: "
        "from MRRpy.interactive import run_wizard; cfg = run_wizard()"
    ) from exc

from .. import config_schema as S
from ..config import Config
from . import render

_LABEL_WIDTH = "17em"
_FIELD_LAYOUT = dict(width="100%", max_width="46em")
_NONE = "__none__"           # Dropdown can't hold a None option value
_RADIO_MAX = 6               # choices with a branch and ≤ this many options use radio buttons
_LOG_LINES_SHOWN = 400       # the form shows the end of the log; the full log is saved
_LOG_FILE = "mrrpy_run.log"

_CSS = """
<style>
.mrrpy-form .widget-label { white-space: normal !important; overflow: visible !important;
  text-overflow: clip !important; height: auto !important; line-height: 1.3; }
.mrrpy-form .widget-inline-hbox { height: auto !important; align-items: flex-start; }
.mrrpy-form .widget-radio-box { height: auto !important; }
.mrrpy-form .widget-radio-box label { white-space: normal !important; }
.mrrpy-form .mrrpy-help { font-size: 0.92em; opacity: 0.85; margin: 0 0 0.6em 0;
  max-width: 46em; line-height: 1.35; }
.mrrpy-form .mrrpy-msg { font-size: 0.95em; margin: 0 0 0.4em 0; max-width: 46em; }
.mrrpy-form .mrrpy-intro { margin: 0.3em 0 0.8em 0; max-width: 46em; }
.mrrpy-form .mrrpy-branch { margin: 0.1em 0 0.8em 1.6em; padding-left: 0.9em;
  border-left: 3px solid var(--jp-brand-color1, #1976d2); }
.mrrpy-form .mrrpy-block { margin-bottom: 0.6em; }
.mrrpy-form .mrrpy-text { max-height: 28em; overflow: auto; white-space: pre-wrap;
  font-size: 0.85em; margin: 0; padding: 0.5em; max-width: 60em;
  border: 1px solid var(--jp-border-color2, #ccc); }
.mrrpy-form .mrrpy-gee { margin: 0.6em 0; padding: 0.4em 0.8em;
  border: 1px solid var(--jp-border-color1, #999); border-radius: 4px; max-width: 46em; }
</style>
"""


def _esc(text):
    return html.escape(str(text))


_WARN_WORDS = ("[warn]", "failed", "unavailable", "falling back", "fallback", "warning:")


def run_warnings(log_text, limit=12):
    """Lines of a run log that report a failure the model worked around."""
    found = []
    for line in (log_text or "").splitlines():
        low = line.lower()
        if any(w in low for w in _WARN_WORDS) and line.strip() not in found:
            found.append(line.strip())
    if len(found) > limit:
        found = found[:limit] + [f"… and {len(found) - limit} more in the log."]
    return found


def _pre(text):
    """Text shown as-is in a scrollable box (selectable and copyable)."""
    return f'<pre class="mrrpy-text">{_esc(text)}</pre>'


def _duration(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m} min {s} s"
    h, m = divmod(m, 60)
    return f"{h} h {m} min"


class _Kit:
    """
    Layout and style models shared by many widgets of one form.  Every
    ipywidget otherwise gets its own Layout/Style model, and the browser
    (VS Code especially) must rebuild every model before the form appears.
    Widgets whose visibility is toggled keep their own Layout.
    """

    def __init__(self):
        self.input = W.Layout(**_FIELD_LAYOUT)
        self.auto = W.Layout(width="auto")
        self.plain = W.Layout()
        self.help = W.Layout()            # all explanations, shown/hidden together
        self._styles = {}

    def style(self, cls):
        klass = cls.class_traits()["style"].klass
        from ipywidgets.widgets.widget_description import DescriptionStyle
        labelled = cls is not W.Checkbox and issubclass(klass, DescriptionStyle)
        key = (klass, labelled)
        if key not in self._styles:
            self._styles[key] = klass(description_width=_LABEL_WIDTH) if labelled else klass()
        return self._styles[key]


_ACTIVE_KIT = []


def _kit():
    """The kit of the form being built (a fresh one for stand-alone fields)."""
    if not _ACTIVE_KIT:
        _ACTIVE_KIT.append(_Kit())
    return _ACTIVE_KIT[-1]


def _style(cls):
    return _kit().style(cls)


def _html(value="", layout=None):
    return W.HTML(value, layout=layout or _kit().plain, style=_style(W.HTML))


def _shown(widget):
    return widget.layout.display != "none"


def _display(widget, visible):
    widget.layout.display = "" if visible else "none"


# ═════════════════════════════════════════════════════════════════════════════
# Fields — one per parameter kind
# ═════════════════════════════════════════════════════════════════════════════
class Field:
    """A labelled input for one parameter: .box (to display), .get(), .set()."""

    def __init__(self, p, radio=False):
        self.p = p
        self.radio = radio
        self.help = _html(f'<div class="mrrpy-help">{_esc(p.help)}</div>'
                          if p.help else "", layout=_kit().help)
        self.message = _html("")
        self._build()
        self.box = W.VBox(self._parts())

    def _parts(self):
        return [self.row, self.help, self.message]

    # subclasses: _build() sets self.row and self.watch (widgets whose value to observe)
    def get(self):
        raise NotImplementedError

    def set(self, value):
        raise NotImplementedError

    def show_message(self, text, problem=True):
        if not text:
            self.message.value = ""
            return
        prefix = "Problem: " if problem else ""
        role = ' role="alert"' if problem else ""
        self.message.value = f'<div class="mrrpy-msg"{role}>{prefix}{_esc(text)}</div>'

    def validate(self):
        """Return the value, after showing (and re-raising) any problem."""
        try:
            value = self.get()
        except ValueError as exc:
            self.show_message(str(exc))
            raise
        self.show_message("")
        return value


_PLACEHOLDERS = {
    "latlon": "latitude, longitude   e.g. 27.6322, 85.2933",
    "bbox": "west, south, east, north   e.g. 85.1, 27.5, 85.6, 27.9",
    "datetime": "YYYY-MM-DD HH:MM   e.g. 2024-09-27 06:00",
    "crs": "EPSG code, e.g. EPSG:32645",
    "order_table": "one value per stream order, e.g. 3, 5, 8, 12",
    "elev_table": "upper elevation: n, …   e.g. 1500: 0.06, 9000: 0.04",
    "hg_coeffs": "w_a, w_b, d_a, d_b   e.g. 2.7, 0.352, 0.3, 0.213",
    "formula": "e.g. wecs_nepal, global_area, or 1.73 * A ^ 0.606",
    "file": "path to a file",
    "folder": "path to a folder",
}


class TextField(Field):
    def _build(self):
        p = self.p
        placeholder = _PLACEHOLDERS.get(p.kind, "")
        if p.optional and p.none_label:
            placeholder = f"empty = {p.none_label}"
        self.text = W.Text(description=p.title, placeholder=placeholder,
                           continuous_update=False, style=_style(W.Text),
                           layout=_kit().input)
        self.row = self.text
        self.watch = [self.text]

    def get(self):
        return S.parse_value(self.p, self.text.value)

    def set(self, value):
        self.text.value = S.format_value(self.p, value)


class FileField(TextField):
    """A path box that says whether the file exists."""

    def get(self):
        value = super().get()
        if value and isinstance(value, str) and not os.path.exists(value):
            self.show_message(f"Not found (looking from {os.getcwd()}): {value}")
        return value

    def validate(self):
        value = self.get()      # keep the "not found" note; it is a warning, not an error
        if not (value and isinstance(value, str) and not os.path.exists(value)):
            self.show_message("")
        return value


class CrsField(TextField):
    """EPSG box with a button that fills in the outlet's UTM zone."""

    def _build(self):
        super()._build()
        self.suggest = W.Button(description="Use the outlet's UTM zone",
                                layout=_kit().auto)
        self.suggest.on_click(self._use_suggestion)
        self.suggestion = None
        self.row = W.VBox([self.text, self.suggest])

    def update_suggestion(self, values):
        self.suggestion, why = S.suggest_crs(values)
        if self.suggestion:
            self.suggest.description = f"Use {self.suggestion} ({why.split(',')[0]})"
            self.suggest.disabled = (self.suggestion == self.text.value)
        else:
            self.suggest.description = "No UTM zone for this outlet"
            self.suggest.disabled = True

    def _use_suggestion(self, _btn=None):
        if self.suggestion:
            self.text.value = self.suggestion


class NumberField(Field):
    def _build(self):
        p = self.p
        cls = W.IntText if p.kind == "int" else W.FloatText
        self.num = cls(description=p.title, continuous_update=False, style=_style(cls),
                       layout=_kit().input)
        self.row = self.num
        self.watch = [self.num]

    def get(self):
        return S.check_value(self.p, self.num.value)

    def set(self, value):
        self.num.value = value


class BoolField(Field):
    def _build(self):
        self.check = W.Checkbox(description=self.p.title, indent=False,
                                layout=_kit().input)
        self.row = self.check
        self.watch = [self.check]

    def get(self):
        return bool(self.check.value)

    def set(self, value):
        self.check.value = bool(value)


class ChoiceField(Field):
    """A menu, or radio buttons when the choice opens branches (radio=True)."""

    def _build(self):
        p = self.p
        options = [(label, value) for value, label in S.choices_for(p)]
        if p.optional:
            options.insert(0, (p.none_label or "none", _NONE))
        cls = W.RadioButtons if self.radio else W.Dropdown
        self.drop = cls(options=options, description=p.title, style=_style(cls),
                        layout=_kit().input)
        self.row = self.drop
        self.watch = [self.drop]

    def get(self):
        value = self.drop.value
        return S.check_value(self.p, None if value == _NONE else value)

    def set(self, value):
        self.drop.value = _NONE if value is None else value


class GroupedChoiceField(Field):
    """
    A two-level choice (``choice_groups`` in the catalogue): first the group
    (e.g. *rain gauges*), then — only if that group has several options — one
    of them (e.g. *Thiessen* or *IDW*), shown as a branch underneath.
    """

    def _build(self):
        p = self.p
        self.groups = {key: (label, members) for key, label, members in p.choice_groups}
        self.group = W.RadioButtons(options=[(label, key) for key, (label, _m)
                                             in self.groups.items()],
                                    description=p.title, style=_style(W.RadioButtons),
                                    layout=_kit().input)
        self.sub = W.RadioButtons(options=[], description=p.group_title or "Option",
                                  style=_style(W.RadioButtons), layout=_kit().input)
        self.sub_box = W.VBox([self.sub])
        self.sub_box.add_class("mrrpy-branch")
        self._group_changed()
        self.group.observe(self._group_changed, names="value")
        self.row = W.VBox([self.group, self.sub_box])
        self.watch = [self.group, self.sub]

    def members(self, key=None):
        return self.groups[key or self.group.value][1]

    def _group_changed(self, change=None):
        old = self.groups[change["old"]][1] if change and change.get("old") in self.groups else []
        keep = old.index(self.sub.value) if self.sub.value in old else 0
        members = self.members()
        self.sub.options = [(self.p.sub_labels.get(m, m), m) for m in members]
        self.sub.value = members[min(keep, len(members) - 1)]
        _display(self.sub_box, len(members) > 1)

    def get(self):
        members = self.members()
        value = self.sub.value if self.sub.value in members else members[0]
        return S.check_value(self.p, value)

    def set(self, value):
        value = S.check_value(self.p, value)
        key = next(k for k, (_l, m) in self.groups.items() if value in m)
        self.group.value = key
        self.sub.value = value


class MultiField(Field):
    """Tick boxes; each box has a slot where its own branch is shown."""

    def _build(self):
        p = self.p
        self.checks = {value: W.Checkbox(description=label, indent=False,
                                         layout=_kit().auto)
                       for value, label in S.choices_for(p)}
        self.slots = {value: W.VBox([]) for value in self.checks}
        self.heading = _html(f"<b>{_esc(p.title)}</b>")
        self.row = W.VBox([self.heading] + [x for v in self.checks
                                            for x in (self.checks[v], self.slots[v])])
        self.watch = list(self.checks.values())

    def _parts(self):
        items = [x for v in self.checks for x in (self.checks[v], self.slots[v])]
        return [self.heading, self.help] + items + [self.message]

    def get(self):
        return S.check_value(self.p, [v for v, c in self.checks.items() if c.value])

    def set(self, value):
        for v, c in self.checks.items():
            c.value = v in (value or [])


class PointsField(Field):
    def _build(self):
        p = self.p
        layout = "name, latitude, longitude" + (", hydrograph.csv" if p.needs_csv else "")
        self.text = W.Textarea(description=p.title, continuous_update=False,
                               placeholder=f"one point per line:  {layout}",
                               rows=3, style=_style(W.Textarea), layout=_kit().input)
        self.row = self.text
        self.watch = [self.text]

    def get(self):
        return S.parse_value(self.p, self.text.value)

    def set(self, value):
        self.text.value = S.format_value(self.p, value) if value else ""


class CompositeField(Field):
    """Radio buttons for the form of a value, plus the input that form needs
    (bankfull flow: automatic / a number / a formula; channel n; …)."""

    def _build(self):
        p = self.p
        self.modes = {m.key: m for m in S.modes_for(p)}
        self._custom = None
        self.drop = W.RadioButtons(options=self._options(), description=p.title,
                                   style=_style(W.RadioButtons), layout=_kit().input)
        self.subs = {key: make_field(m.sub, sub=True)
                     for key, m in self.modes.items() if m.sub is not None}
        for f in self.subs.values():
            f.help.value = ""                           # the parent help says it all
            f.box.add_class("mrrpy-branch")
        self.row = W.VBox([self.drop] + [f.box for f in self.subs.values()])
        self.watch = [self.drop] + [w for f in self.subs.values() for w in f.watch]
        self.drop.observe(lambda _c: self._show_sub(), names="value")
        self._show_sub()

    def _options(self):
        opts = [(m.label, key) for key, m in self.modes.items()]
        if self._custom is not None:
            opts.append(("Custom rule from your Python config (kept as is)", "custom"))
        return opts

    def _show_sub(self):
        for key, f in self.subs.items():
            _display(f.box, key == self.drop.value)

    def get(self):
        mode = self.drop.value
        if mode == "custom":
            return self._custom
        sub = self.subs[mode].validate() if mode in self.subs else None
        value = S.join_composite(self.p, mode, sub)
        return None if value is None else S.check_value(self.p, value)

    def set(self, value):
        mode, sub = S.split_composite(self.p, value)
        if mode == "custom":
            self._custom = value
            self.drop.options = self._options()
        self.drop.value = mode
        if mode in self.subs and sub is not None:
            self.subs[mode].set(sub)
        self._show_sub()


def make_field(p, sub=False, radio=False):
    """The right Field class for parameter *p*."""
    k = p.kind
    if k == "bool":
        return BoolField(p)
    if k == "choice":
        if p.choice_groups and not sub:
            return GroupedChoiceField(p)
        return ChoiceField(p, radio=radio)
    if k == "multichoice":
        return MultiField(p)
    if k in ("qbf", "channel_n", "hg"):
        return CompositeField(p)
    if k == "points":
        return PointsField(p)
    if k == "crs":
        return CrsField(p)
    if k == "file":
        return FileField(p)
    if k in ("float", "int") and not p.optional and not sub:
        return NumberField(p)
    return TextField(p)


# ═════════════════════════════════════════════════════════════════════════════
# The steps
# ═════════════════════════════════════════════════════════════════════════════
class Step:
    """One tab: which settings it holds, and how they are grouped into blocks."""

    def __init__(self, key, title, intro, blocks, holds):
        self.key, self.title, self.intro = key, title, intro
        self.blocks = blocks          # [(block title, [root setting names])]
        self.holds = holds            # Param → bool


STEPS = [
    Step("terrain", "Terrain",
         "Choose the elevation data (a DEM file you have, or an area to download), "
         "mark the basin outlet, and pick the results folder.",
         [("Elevation data (DEM)", ["__dem__"]),
          ("Basin outlet", ["OUTPUT_POINT"]),
          ("Results folder", ["OUTPUT_DIR"]),
          ("Terrain processing", ["DELINEATION_ENGINE", "DEM_CONDITIONING",
                                  "DEM_LAKE_MASK", "CELL_SIZE"])],
         lambda p: p.section == "project" and p.name not in ("TARGET_CRS_EPSG", "GEE_PROJECT")),
    Step("crs", "Coordinate system",
         "The model works on a grid in metres, so it needs a projected coordinate "
         "system. The UTM zone that contains your outlet is a safe choice.",
         [("Map projection", ["TARGET_CRS_EPSG"])],
         lambda p: p.name == "TARGET_CRS_EPSG"),
    Step("rain", "Precipitation",
         "Where the rain comes from. Pick a source: only the settings it needs "
         "appear underneath it.",
         [("Rain source", ["PRECIP_METHOD"]),
          ("Snow (optional)", ["RAIN_SNOW_ELEV_LOW", "RAIN_SNOW_ELEV_HIGH"])],
         lambda p: p.section == "rain"),
    Step("runoff", "Runoff",
         "How the ground splits rain into runoff and water that soaks in. Pick a "
         "method: only the settings it needs appear underneath it.",
         [("Runoff method", ["RUNOFF_SOURCE"])],
         lambda p: p.section == "runoff"),
    Step("routing", "Routing",
         "How water flows downhill and along the rivers, and for how long to simulate.",
         [("Routing method", ["ROUTING_SCHEME"]),
          ("Simulation time", ["TOTAL_SIMULATION_TIME_HOURS", "OUTPUT_INTERVAL_SECONDS",
                               "TIME_STEP_SECONDS", "ADAPTIVE_TIMESTEP"]),
          ("Ground roughness", ["MANNINGS_N_SOURCE", "MANNINGS_N", "LULC_LOOKUP_CSV",
                                "LCZ_LOOKUP_CSV"]),
          ("River channels", ["CHANNEL_ROUTING", "MANNINGS_N_CHANNEL", "CHANNEL_MIN_AREA_KM2",
                              "CHANNEL_FACCUM_THRESHOLD", "BASEFLOW_SPECIFIC_Q"]),
          ("Water entering from upstream", ["ROUTING_INFLOW_BC"]),
          ("Numerical safeguards", ["MIN_SLOPE", "MIN_DEPTH_M", "MANNING_SLOPE_CAP"])],
         lambda p: p.section in ("routing", "surface")),
    Step("run", "Outputs and run",
         "Extra results to record and the computer to use; then check, save and "
         "run the configuration.",
         [("Extra results", ["ROUTING_GAUGES", "SAVE_FIELDS", "MASS_BALANCE_REPORT"]),
          ("Computer", ["BACKEND"])],
         lambda p: p.section == "outputs"),
]
STEP_BY_KEY = {s.key: s for s in STEPS}


def step_of(p):
    """The Step that shows setting *p* (None for GEE_PROJECT, shown where needed)."""
    if isinstance(p, str):
        p = S.param(p)
    return next((s for s in STEPS if s.holds(p)), None)


_STAGES = [
    ("Delineate the watershed, then route (full run)", ("process_dem", "routing")),
    ("Delineate the watershed only", ("process_dem",)),
    ("Route only (reuse the watershed in the results folder)", ("routing",)),
]


class _LogWriter(io.TextIOBase):
    """Where print() goes during a run: kept in full, shown (throttled) in the form."""

    def __init__(self, form):
        self.form = form

    def write(self, text):
        self.form._log_write(str(text))
        return len(text)

    def flush(self):
        self.form._log_flush()


class _Proxy:
    """A second, linked copy of a field shown in another branch."""

    def __init__(self, p, field, groups):
        self.p, self.field, self.groups = p, field, groups


class ConfigForm:
    """
    A step-by-step form for one MRRpy configuration.

    Parameters
    ----------
    config : Config, str or None
        Start from this Config or config file; None = the defaults.
    path : str, optional
        File name offered by the Save button (default: the loaded file or run.yaml).
    show_help : bool
        Show the explanation under every setting (can be toggled in the form).
    map : bool or None
        Offer the ipyleaflet map picker (None = when ipyleaflet is installed).
    """

    def __init__(self, config=None, path=None, show_help=True, map=None):
        self._loading = False
        self.results = None
        if isinstance(config, (str, os.PathLike)):
            path = path or os.fspath(config)
            config = Config.from_file(os.fspath(config))
        self._base = config if config is not None else Config()
        self.kit = _Kit()
        _ACTIVE_KIT.append(self.kit)
        try:
            self._build_all(path, show_help, map)
        finally:
            _ACTIVE_KIT.remove(self.kit)
        try:                                   # a finished run already in the folder?
            if os.path.isfile(os.path.join(os.path.abspath(self._base.OUTPUT_DIR or "output"),
                                           "hydrograph.csv")):
                self.show_results()
        except Exception:   # noqa: BLE001 — never let old files break the form
            self.results_box.children = []

    def _build_all(self, path, show_help, map):
        self._children = self._tree()
        self.fields = {p.name: make_field(p, radio=self._radio(p)) for p in S.PARAMS}
        self._nodes = {}            # name → node widget (field box + its branch)
        self._containers = []       # (widget, members, title) in post-order
        self._accordion_of = {}     # name → the Accordion its node sits in
        self.proxies = []
        self.gee_boxes = {}
        self.connect_btns = {}
        self.ee_connected = None
        self.run_state = "not run"     # 'not run' | 'running' | 'finished' | 'failed'
        self.log_path = None
        self._log_parts, self._log_file, self._log_last = [], None, 0.0
        self._build(path or "run.yaml", show_help, map)
        self.load(self._base)
        for f in list(self.fields.values()) + [x.field for x in self.proxies]:
            for w in f.watch:
                w.observe(self._on_change, names="value")
        self.dem_mode.observe(self._on_change, names="value")

    # ── Tree ──────────────────────────────────────────────────────────────────
    def _tree(self):
        """{parent name: [(child Param, item, groups or None)]} within each step."""
        kids = {}
        for p in S.PARAMS:
            par = S.parent_of(p)
            if par and step_of(par[0]) is step_of(p):
                kids.setdefault(par[0], []).append((p, par[1], None))
            for name, groups in S.extra_parents(p):
                kids.setdefault(name, []).append((p, None, groups))
        return kids

    def _radio(self, p):
        return (p.kind == "choice" and p.name in self._children
                and len(S.choices_for(p)) <= _RADIO_MAX)

    def _direct(self, p):
        """Shown directly (not folded under 'More options'): basic settings and
        anything that leads to a basic setting."""
        return p.level == "basic" or any(
            self._direct(c) for c, _i, g in self._children.get(p.name, []) if g is None)

    def _roots(self, step):
        return [p for p in S.PARAMS if step.holds(p)
                and not (S.parent_of(p) and step_of(S.parent_of(p)[0]) is step)]

    def _node(self, p, groups=None):
        """The widget for one setting plus the branch of settings it opens."""
        if groups is not None:                       # a linked copy for another branch
            proxy = _Proxy(p, make_field(p), groups)
            proxy.field.help.value = (f'<div class="mrrpy-help">{_esc(p.help)} '
                                      "(The same setting as in the other step.)</div>")
            self.proxies.append(proxy)
            for a, b in zip(self.fields[p.name].watch, proxy.field.watch):
                W.link((a, "value"), (b, "value"))
            return proxy.field.box
        f = self.fields[p.name]
        kids = self._children.get(p.name, [])
        if isinstance(f, MultiField):
            for item, slot in f.slots.items():
                branch = self._branch([k for k in kids if k[1] == item], item)
                slot.children = [branch] if branch else []
            branch = self._branch([k for k in kids if k[1] is None], p.label)
        else:
            branch = self._branch(kids, p.label)
        node = W.VBox([f.box, branch]) if branch else f.box
        self._nodes[p.name] = node
        return node

    def _branch(self, kids, owner):
        if not kids:
            return None
        direct = [k for k in kids if k[2] is not None or self._direct(k[0])]
        folded = [k for k in kids if k not in direct]
        children = [self._node(c, g) for c, _i, g in direct]
        if folded:
            children.append(self._accordion([c for c, _i, _g in folded],
                                            f"More options: {owner}"))
        box = W.VBox(children)
        box.add_class("mrrpy-branch")
        self._containers.append((box, children, None))
        return box

    def _accordion(self, params, title):
        nodes = [self._node(p) for p in params]
        acc = W.Accordion(children=[W.VBox(nodes)], titles=(title,))
        acc.selected_index = None
        for p in params:
            self._accordion_of[p.name] = acc
        self._containers.append((acc, nodes, title))
        return acc

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build(self, path, show_help, want_map):
        intro = _html(
            '<div class="mrrpy-intro"><b>MRRpy configuration.</b> Work through the steps '
            "with the <i>Next</i> buttons (or click a tab). Each choice opens its own "
            "settings underneath it; everything else keeps a sensible default. Step 6 "
            "checks, saves and runs the configuration.</div>")
        self.start = W.Dropdown(options=[(s.label, s.key) for s in S.STARTING_POINTS],
                                description="Starting point", style=_style(W.Dropdown),
                                layout=_kit().input)
        self.start_btn = W.Button(description="Apply starting point",
                                  layout=_kit().auto)
        self.start_btn.on_click(self._apply_start)
        self.load_path = W.Text(description="Load a config file", placeholder="run.yaml",
                                style=_style(W.Text), layout=_kit().input)
        self.load_btn = W.Button(description="Load", layout=_kit().auto)
        self.load_btn.on_click(self._load_clicked)
        self.help_toggle = W.Checkbox(value=show_help, indent=False,
                                      description="Show an explanation under every setting")
        self.help_toggle.observe(lambda _c: self._apply_help(), names="value")
        top = W.VBox([intro, W.HBox([self.start, self.start_btn]),
                      W.HBox([self.load_path, self.load_btn]), self.help_toggle])

        self.dem_mode = W.RadioButtons(
            options=[("I have a DEM file (GeoTIFF)", "file"),
                     ("Download a DEM for an area (Google Earth Engine)", "download")],
            description="Elevation data from", style=_style(W.RadioButtons),
            layout=_kit().input)

        self._build_run_panel(path)
        pages, self.next_btns, self.back_btns = [], [], []
        for i, step in enumerate(STEPS):
            head = _html(f"<h3>Step {i + 1} of {len(STEPS)}: {_esc(step.title)}</h3>"
                          f'<div class="mrrpy-intro">{_esc(step.intro)}</div>')
            blocks = [self._block(step, title, names, want_map)
                      for title, names in step.blocks]
            placed = {n for _t, names in step.blocks for n in names}
            rest = [p for p in self._roots(step) if p.name not in placed
                    and not (step.key == "terrain" and p.name == "DEM_PATH")]
            if rest:
                blocks.append(self._block(step, "Other settings", [p.name for p in rest], False))
            gee = self._gee_box(step)
            extra = [self.run_panel] if step.key == "run" else []
            nav = self._nav(i)
            pages.append(W.VBox([head] + blocks + [gee] + extra + [nav]))
        self.tabs = W.Tab(children=pages,
                          titles=[f"{i + 1} {s.title}" for i, s in enumerate(STEPS)])
        self.status = _html()
        self.widget = W.VBox([_html(_CSS), top, self.tabs, self.status])
        self.widget.add_class("mrrpy-form")
        self._apply_help()

    def _block(self, step, title, names, want_map):
        """A titled group of root settings (and their branches) within a step."""
        heading = _html(f"<h4>{_esc(title)}</h4>")
        if names == ["__dem__"]:
            content = self._dem_block()
            return W.VBox([heading, content])
        params = [S.param(n) for n in names]
        direct = [p for p in params if self._direct(p)]
        folded = [p for p in params if not self._direct(p)]
        if not direct:                             # all optional: one collapsed section
            acc = self._accordion(folded, title)
            box = W.VBox([acc])
            self._containers.append((box, [acc], None))
            return box
        children = [self._node(p) for p in direct]
        if title == "Basin outlet":
            children.append(self._map_panel(want_map))
        if folded:
            children.append(self._accordion(folded, f"More options: {title}"))
        content = W.VBox(children)
        self._containers.append((content, [c for c in children], None))
        box = W.VBox([heading, content])
        box.add_class("mrrpy-block")
        self._containers.append((box, [content], None))
        return box

    def _dem_block(self):
        """'I have a DEM file' / 'Download one' and the branch of each."""
        self.dem_file_branch = W.VBox([self.fields["DEM_PATH"].box])
        self._nodes["DEM_PATH"] = self.dem_file_branch
        kids = self._children.get("DEM_PATH", [])
        direct = [c for c, _i, _g in kids if self._direct(c)]
        folded = [c for c, _i, _g in kids if not self._direct(c)]
        children = [self._node(c) for c in direct]
        children.append(_html('<div class="mrrpy-help">Tip: the map under "Basin outlet" '
                               "can draw this area for you.</div>"))
        if folded:
            children.append(self._accordion(folded, "More options: download"))
        self.dem_download_branch = W.VBox(children)
        for b in (self.dem_file_branch, self.dem_download_branch):
            b.add_class("mrrpy-branch")
        return W.VBox([self.dem_mode, self.dem_file_branch, self.dem_download_branch])

    def _gee_box(self, step):
        """'This step uses Earth Engine — project: [ ]', shown when the step needs it."""
        field = make_field(S.param("GEE_PROJECT"))
        for a, b in zip(self.fields["GEE_PROJECT"].watch, field.watch):
            W.link((a, "value"), (b, "value"))
        field.help.value = ""
        note = _html()
        connect = W.Button(description="Connect to Earth Engine", icon="plug",
                           layout=_kit().auto)
        result = _html()
        connect.on_click(lambda _b: self.check_earth_engine(result))
        box = W.VBox([note, field.box, W.HBox([connect]), result])
        box.add_class("mrrpy-gee")
        self.gee_boxes[step.key] = (box, note, field)
        self.connect_btns[step.key] = (connect, result)
        return box

    def check_earth_engine(self, result=None):
        """Test the Earth Engine connection with the project in the form.

        A button can't show a sign-in prompt, so when this computer has never
        signed in it explains how to (MRRpy.connect_earth_engine in a cell)."""
        from ..gee import auth
        project = self._value("GEE_PROJECT")
        if result is not None:
            result.value = '<div class="mrrpy-msg" role="status">Checking…</div>'
        ok, message = auth.status(project)
        self.ee_connected = ok
        role, prefix = ('role="status"', "") if ok else ('role="alert"', "Problem: ")
        html_msg = f'<div class="mrrpy-msg" {role}>{prefix}{_esc(message)}</div>'
        for _btn, res in self.connect_btns.values():
            res.value = html_msg
        return ok, message

    def _nav(self, i):
        back = W.Button(description=f"‹ Back: {STEPS[i - 1].title}" if i else "‹ Back",
                        disabled=(i == 0), layout=_kit().auto)
        nxt = W.Button(description=(f"Next: {STEPS[i + 1].title} ›" if i + 1 < len(STEPS)
                                    else "Last step"),
                       disabled=(i + 1 == len(STEPS)), button_style="primary",
                       layout=_kit().auto)
        back.on_click(lambda _b: self.go(i - 1))
        nxt.on_click(lambda _b: self.go(i + 1))
        self.back_btns.append(back)
        self.next_btns.append(nxt)
        return W.HBox([back, nxt], layout=W.Layout(margin="1em 0 0 0"))

    def go(self, index):
        """Show step *index* (0-based) or the step with that key."""
        if isinstance(index, str):
            index = [s.key for s in STEPS].index(index)
        self.tabs.selected_index = max(0, min(index, len(STEPS) - 1))

    def _build_run_panel(self, path):
        self.summary_box = _html()
        self.save_path = W.Text(value=path, description="Save as", style=_style(W.Text),
                                layout=_kit().input)
        self.save_all = W.Checkbox(value=False, indent=False,
                                   description="Write every setting (long reference file)")
        self.check_btn = W.Button(description="Check settings", button_style="info")
        self.save_btn = W.Button(description="Save", button_style="success")
        self.yaml_btn = W.Button(description="Show YAML")
        self.python_btn = W.Button(description="Show Python code")
        self.stage = W.Dropdown(options=[(label, i) for i, (label, _s) in enumerate(_STAGES)],
                                description="What to run", style=_style(W.Dropdown),
                                layout=_kit().input)
        self.run_btn = W.Button(description="Run the model", button_style="warning")
        self.progress = W.IntProgress(min=0, max=100, description="Progress",
                                      style=_style(W.IntProgress), layout=W.Layout(display="none"))
        self.state_box = _html('<div class="mrrpy-msg" role="status"><b>Status:</b> '
                                "not run yet.</div>")
        self.results_box = W.VBox([])
        self.results_btn = W.Button(description="Show results and plot the hydrograph",
                                    icon="line-chart", layout=_kit().auto)
        self.results_btn.on_click(lambda _b: self.show_results())
        # Plain HTML text boxes, not ipywidgets.Output: VS Code stops showing a
        # form's updates after it fails to apply one to an Output widget.
        self.log_box = _html(_pre("The model's log appears here when it runs."))
        self.view_box = _html()
        self.check_btn.on_click(lambda _b: self._report_check())
        self.save_btn.on_click(lambda _b: self._save_clicked())
        self.yaml_btn.on_click(lambda _b: self._show_text(self._yaml_text, "YAML"))
        self.python_btn.on_click(lambda _b: self._show_text(self.to_python, "Python"))
        self.run_btn.on_click(lambda _b: self._run_clicked())
        self.run_panel = W.VBox([
            _html("<h4>Summary</h4>"), self.summary_box,
            W.HBox([self.check_btn, self.yaml_btn, self.python_btn]), self.view_box,
            W.HBox([self.save_path, self.save_btn]), self.save_all,
            W.HBox([self.stage, self.run_btn]), self.state_box, self.progress,
            W.HBox([self.results_btn]), self.results_box,
            _html("<h4>Log</h4>"), self.log_box])

    def _map_panel(self, want_map):
        """Optional ipyleaflet picker for the outlet and the download area."""
        self.map = None
        try:
            import ipyleaflet  # noqa: F401
            available = True
        except ImportError:
            available = False
        if want_map is False:
            return W.VBox([])
        if not available:
            note = ("For a clickable map, install ipyleaflet (pip install ipyleaflet) "
                    "and recreate the form. Typing the coordinates works just as well.")
            return _html(f'<div class="mrrpy-help">{_esc(note)}</div>')
        self.map_btn = W.Button(description="Pick the outlet or download area on a map",
                                layout=_kit().auto)
        self.map_box = W.VBox([])
        self.map_btn.on_click(lambda _b: self.show_map())
        return W.VBox([self.map_btn, self.map_box])

    def show_map(self):
        """Create (once) and show the map picker; returns the ipyleaflet Map."""
        import ipyleaflet as L
        if self.map is not None:
            return self.map
        lat, lon = self._value("OUTPUT_POINT", (27.7, 85.3))
        m = L.Map(center=(lat, lon), zoom=9, scroll_wheel_zoom=True,
                  layout=W.Layout(height="380px", max_width="46em"))
        self.marker = L.Marker(location=(lat, lon), draggable=True, title="Basin outlet")
        m.add(self.marker)
        draw = L.DrawControl(polyline={}, polygon={}, circlemarker={}, marker={},
                             rectangle={"shapeOptions": {"weight": 2}})
        draw.on_draw(self._on_draw)
        m.add(draw)
        m.on_interaction(self._on_map_click)
        self.marker.observe(self._on_marker_move, names="location")
        note = _html('<div class="mrrpy-help">Click the map (or drag the marker) to set '
                      "the basin outlet. Draw a rectangle with the square tool to set the "
                      "area to download.</div>")
        self.map_box.children = [note, m]
        self.map = m
        return m

    def _on_map_click(self, **event):
        if event.get("type") == "click":
            lat, lon = event["coordinates"]
            self.set("OUTPUT_POINT", (round(lat, 6), round(lon, 6)))
            if self.map is not None:
                self.marker.location = (lat, lon)

    def _on_marker_move(self, change):
        lat, lon = change["new"]
        self.set("OUTPUT_POINT", (round(lat, 6), round(lon, 6)))

    def _on_draw(self, target=None, action=None, geo_json=None):
        if action not in (None, "created") or not geo_json:
            return
        from ..utils.notebook_map import _bounds_from_geojson_feature
        w, s, e, n = _bounds_from_geojson_feature(geo_json)
        had_file = self.dem_mode.value == "file" and bool(self._value("DEM_PATH"))
        self.dem_mode.value = "download"
        self.set("DEM_BOUNDS_WGS84", tuple(round(x, 5) for x in (w, s, e, n)))
        if had_file:
            self._say("The download area was set from the map, so the form switched to "
                      "downloading a DEM. Your DEM file path is kept if you switch back.")
        else:
            self._say("The download area was set from the map.")

    # ── Values in and out ─────────────────────────────────────────────────────
    def _value(self, name, fallback=None):
        try:
            return self.fields[name].get()
        except ValueError:
            return fallback

    def load(self, config):
        """Fill the form from a Config or a config file path."""
        if isinstance(config, (str, os.PathLike)):
            config = Config.from_file(os.fspath(config))
        self._base = config
        self._loading = True
        try:
            for p in S.PARAMS:
                self.fields[p.name].set(getattr(config, p.name))
            self.dem_mode.value = ("download" if not config.DEM_PATH and config.DEM_BOUNDS_WGS84
                                   else "file")
        finally:
            self._loading = False
        self.refresh()

    def set(self, name, value):
        """Set one setting by name (as if typed in the form)."""
        if self._loading:
            self.fields[S.param(name).name].set(value)
            return
        self.set_values(**{name: value})

    def set_values(self, **values):
        """Set several settings at once: form.set_values(RAIN_INTENSITY_MM_HR=50, …)."""
        self._loading = True
        try:
            for name, value in values.items():
                self.fields[S.param(name).name].set(value)
            if values.get("DEM_PATH"):
                self.dem_mode.value = "file"
            elif "DEM_PATH" in values and values.get("DEM_BOUNDS_WGS84", self._value(
                    "DEM_BOUNDS_WGS84")):
                self.dem_mode.value = "download"
        finally:
            self._loading = False
        self.refresh()

    def field_errors(self):
        """{name: message} for fields whose text can't be read."""
        errors = {}
        for name, f in self.fields.items():
            if name == "DEM_PATH" and self.dem_mode.value == "download":
                continue
            try:
                f.validate()
            except ValueError as exc:
                errors[name] = str(exc)
        return errors

    def _build_config(self, strict=True):
        cfg = Config()
        for p in S.PARAMS:            # copy what the form can't show (e.g. Python rules)
            setattr(cfg, p.name, getattr(self._base, p.name))
        errors = {}
        for p in S.PARAMS:
            try:
                setattr(cfg, p.name, self.fields[p.name].get())
            except ValueError as exc:
                errors[p.name] = str(exc)
        if self.dem_mode.value == "download":
            cfg.DEM_PATH = ""
            errors.pop("DEM_PATH", None)
        cfg.update_output_paths()
        if errors and strict:
            raise ValueError("Some settings in the form can't be read:\n" + "\n".join(
                f"  • {S.param(n).label} ({n}): {m}" for n, m in errors.items()))
        return cfg

    @property
    def config(self):
        """The Config described by the form (ValueError if a field can't be read)."""
        return self._build_config(strict=True)

    def problems(self):
        """Every problem in plain words: unreadable fields, then Config.validate()."""
        errors = self.field_errors()
        out = [f"{S.param(n).label} ({n}): {m}" for n, m in errors.items()]
        out += S.problems(self._build_config(strict=False))
        return out

    def summary(self):
        """What the configuration will do, in plain sentences."""
        return "\n".join(render.describe_run(self._build_config(strict=False)))

    def to_python(self):
        return render.to_python(self.config)

    def _yaml_text(self):
        return render.render_yaml(self.config, full=self.save_all.value,
                                  source="MRRpy ConfigForm")

    def save(self, path=None, full=None):
        """Write the configuration to a YAML (or JSON) file; returns the path."""
        from .wizard import _save
        path = os.path.expanduser(path or self.save_path.value or "run.yaml")
        full = self.save_all.value if full is None else full
        return _save(self.config, path, full, source="MRRpy ConfigForm")

    def run(self, stages=("process_dem", "routing")):
        """
        Run the pipeline with this configuration.

        Everything the model prints is captured into the form's log (and saved
        as mrrpy_run.log in the results folder); the status line says
        Running / Finished / Stopped, and a results summary appears at the end.
        ``form.run_state`` and ``form.results`` hold the outcome for code.
        """
        from ..pipeline import run_pipeline
        cfg = self.config
        folder = os.path.abspath(cfg.OUTPUT_DIR or "output")
        self.results, self.results_box.children = None, []
        self._log_parts, self._log_last = [], 0.0
        self.log_box.value = _pre("Starting…")
        self.progress.layout.display = ""
        self.progress.bar_style = ""
        self.progress.value = 0
        self._set_state("running", "starting…")
        writer = _LogWriter(self)
        started = time.time()
        try:
            os.makedirs(folder, exist_ok=True)
            self.log_path = os.path.join(folder, _LOG_FILE)
            self._log_file = open(self.log_path, "w", encoding="utf-8")
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                self.results = run_pipeline(
                    cfg, stages=stages,
                    on_log=lambda line: writer.write(str(line) + "\n"),
                    on_progress=self._on_progress)
        except BaseException as exc:
            writer.write("\n" + traceback.format_exc())
            self.progress.bar_style = "danger"
            self._set_state("failed", f"{type(exc).__name__}: {exc}")
            raise
        finally:
            self._log_flush(force=True)
            if self._log_file:
                self._log_file.close()
                self._log_file = None
        seconds = time.time() - started
        self.progress.value, self.progress.bar_style = 100, "success"
        self._set_state("finished", f"took {_duration(seconds)}; results in {folder}")
        self._show_results(cfg, folder)
        return self.results

    # ── Run log, state and results ────────────────────────────────────────────
    @property
    def log_text(self):
        """Everything the last run printed."""
        return "".join(self._log_parts)

    def _log_write(self, text):
        self._log_parts.append(text)
        if self._log_file:
            self._log_file.write(text)
        if time.monotonic() - self._log_last > 0.5:
            self._log_flush(force=True)

    def _log_flush(self, force=False):
        if not force and time.monotonic() - self._log_last < 0.5:
            return
        lines = self.log_text.splitlines()
        tail = lines[-_LOG_LINES_SHOWN:]
        if len(lines) > len(tail):
            where = f" ({self.log_path})" if self.log_path else ""
            tail.insert(0, f"… {len(lines) - len(tail)} earlier lines are in the full log{where}")
        self.log_box.value = _pre("\n".join(tail))
        self._log_last = time.monotonic()

    def _on_progress(self, pct):
        self.progress.value = int(pct)
        self._set_state("running", f"{int(pct)} % done")

    def _set_state(self, state, detail="", stamped=True):
        self.run_state = state
        running = state == "running"
        self.run_btn.disabled = running
        self.run_btn.description = "Running…" if running else "Run the model"
        words = {"running": "Running", "finished": "Finished", "failed": "Stopped with an error",
                 "not run": "not run yet"}[state]
        when = time.strftime("%H:%M:%S")
        text = f"<b>Status: {words}</b>"
        if state == "finished":
            text += (f" at {when} — " if stamped else " — ") + f"{_esc(detail)}."
        elif detail:
            text += f" — {_esc(detail)}"
        role = 'role="alert"' if state == "failed" else 'role="status"'
        self.state_box.value = f'<div class="mrrpy-msg" {role}>{text}</div>'

    def show_results(self, folder=None):
        """
        Read the results folder and show what is there: whether the last run
        finished, the peak flow, the water balance, the files and a hydrograph
        plot.  Works for any run — from this form, a cell or `MRRpy run`.
        Returns the hydrograph as a DataFrame (or None).
        """
        folder = os.path.abspath(folder or self._build_config(strict=False).OUTPUT_DIR
                                 or "output")
        if not os.path.isdir(folder):
            self.results_box.children = [_html(
                f'<div class="mrrpy-msg" role="status">No results yet: the folder {_esc(folder)} '
                "does not exist. Run the model first.</div>")]
            return None
        hyd = os.path.join(folder, "hydrograph.csv")
        log = os.path.join(folder, _LOG_FILE)
        text = ""
        if os.path.isfile(log):
            with open(log, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            lines = text.splitlines()
            self.log_box.value = _pre("\n".join(lines[-_LOG_LINES_SHOWN:]))
        if self.run_state != "running":
            if "All stages complete" in text or (os.path.isfile(hyd) and not text):
                stamp = time.strftime("%H:%M:%S on %d %b", time.localtime(
                    os.path.getmtime(hyd if os.path.isfile(hyd) else log)))
                self._set_state("finished", f"results written at {stamp}; in {folder}",
                                stamped=False)
                self.progress.layout.display = "none"
            elif "Traceback" in text:
                self._set_state("failed", f"see the log below ({log})")
            elif text:
                stamp = time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(log)))
                self._set_state("not run", f"the last run did not finish (its log was last "
                                           f"written at {stamp})")
        df = None
        if os.path.isfile(hyd):
            import pandas as pd
            df = pd.read_csv(hyd)
        self._show_results(None, folder, df=df, log_text=text)
        return df

    def _show_results(self, cfg, folder, df=None, log_text=None):
        """Plain facts about the run, any warnings, then a hydrograph picture."""
        facts = []
        warnings_ = run_warnings(self.log_text if log_text is None else log_text)
        if df is None:
            df = (self.results or {}).get("hydrograph_df")
        if df is not None and len(df):
            i = df["Q_m3s"].idxmax()
            facts.append(f"Peak flow at the outlet: {df['Q_m3s'][i]:.4g} m³/s, "
                         f"{df['time_hr'][i]:.3g} h after the start.")
            facts.append(f"Simulated {df['time_hr'].iloc[-1]:.3g} h; flow at the end: "
                         f"{df['Q_m3s'].iloc[-1]:.4g} m³/s.")
        mb = os.path.join(folder, "mass_balance.csv")
        if df is not None and os.path.isfile(mb):
            try:
                import pandas as pd
                rel = float(pd.read_csv(mb)["rel_error"].iloc[-1])
                facts.append(f"Water-balance error: {rel * 100:.2g} % (close to 0 is good).")
            except Exception:   # noqa: BLE001 — the summary is a convenience
                pass
        if df is None or not len(df):
            facts.append("No hydrograph yet (hydrograph.csv is written at the end of the "
                         "routing stage).")
        files = sorted(f for f in os.listdir(folder) if not f.startswith("."))
        facts.append(f"Files in {folder}: " + ", ".join(files) + ".")
        items = "".join(f"<li>{_esc(x)}</li>" for x in facts)
        children = [_html(f"<h4>Results</h4><ul>{items}</ul>")]
        if warnings_:
            lis = "".join(f"<li>{_esc(w)}</li>" for w in warnings_)
            children.append(_html(
                f'<div class="mrrpy-msg" role="alert"><b>Warnings: {len(warnings_)}.</b> The run '
                "finished, but something did not work as asked and the model used a fallback "
                f"(e.g. default soil values). Check these:<ul>{lis}</ul></div>"))
        if df is not None and len(df):
            try:
                from matplotlib.figure import Figure
                from ..plotting import plot_hydrograph
                fig = Figure(figsize=(7, 3.2), dpi=100)
                ax = fig.subplots()
                plot_hydrograph(df, ax=ax)
                ax.set_title("Outlet hydrograph")
                fig.tight_layout()
                buf = io.BytesIO()
                fig.savefig(buf, format="png")
                children.append(W.Image(value=buf.getvalue(), format="png",
                                        layout=W.Layout(max_width="46em")))
            except Exception as exc:   # noqa: BLE001
                children.append(_html(f'<div class="mrrpy-help">(No plot: {_esc(exc)})</div>'))
        self.results_box.children = children

    # ── Reactions ─────────────────────────────────────────────────────────────
    def _on_change(self, _change=None):
        if not self._loading:
            self.refresh()

    def _visible(self, p, values):
        """Is *p*'s main field shown? (Its primary branch must hold.)"""
        if not S.is_visible(p, values):
            return False
        if p.when_any and S.extra_parents(p):
            first = S.parent_of(p)[0]
            groups = [p.when + g for g in p.when_any if (p.when + g)[-1][0] == first]
            return any(S._clauses_hold(g, values) for g in groups)
        return True

    def refresh(self):
        """Show/hide fields and branches for the current choices; update the summary."""
        cfg = self._build_config(strict=False)
        values = S.values_of(cfg)
        download = self.dem_mode.value == "download"
        for p in S.PARAMS:
            f = self.fields[p.name]
            visible = self._visible(p, values)
            if p.name == "DEM_PATH":
                visible = not download
            elif S.parent_of(p) and S.parent_of(p)[0] == "DEM_PATH":
                visible = visible and download
            _display(f.box, visible)
            if p.name in self._nodes:
                _display(self._nodes[p.name], visible)
            if visible:
                try:
                    f.validate()
                except ValueError:
                    pass
        for proxy in self.proxies:
            _display(proxy.field.box, any(S._clauses_hold(g, values) for g in proxy.groups))
        _display(self.dem_file_branch, not download)
        _display(self.dem_download_branch, download)
        for widget, members, title in self._containers:          # children first
            n = sum(_shown(m) for m in members)
            _display(widget, n > 0)
            if title is not None:
                widget.titles = (f"{title} ({n})",)
        self._update_gee(values)
        self.fields["TARGET_CRS_EPSG"].update_suggestion(values)
        items = "".join(f"<li>{_esc(line)}</li>" for line in render.describe_run(cfg))
        self.summary_box.value = f"<ul>{items}</ul>"

    def _update_gee(self, values):
        triggers = S.earth_engine_triggers(values)
        project = self._value("GEE_PROJECT") or os.environ.get("GEE_PROJECT")
        for key, (box, note, _field) in self.gee_boxes.items():
            here = [(w, r) for w, r, name in triggers if step_of(name) is STEP_BY_KEY[key]]
            if key == "run":
                here = here or [("nothing yet", False)]
            _display(box, bool(here))
            if not here:
                continue
            needed = [w for w, r in here if r]
            if needed:
                text = (f"<b>Google Earth Engine</b> is needed in this step for "
                        f"{_esc(', '.join(needed))}. Enter your project and press "
                        "<i>Connect</i> to check that it works.")
                if not project:
                    text += " <b>Problem:</b> enter your Earth Engine project below."
            elif key == "run":
                text = ("<b>Google Earth Engine project</b> (optional): only needed for "
                        "options that download data.")
            else:
                text = (f"<b>Google Earth Engine</b> (optional) improves "
                        f"{_esc(', '.join(w for w, _r in here))}.")
            note.value = f'<div class="mrrpy-help">{text}</div>'

    def _apply_help(self):
        show = self.help_toggle.value
        for f in list(self.fields.values()) + [x.field for x in self.proxies]:
            _display(f.help, show)

    def _say(self, text, problem=False):
        role = ' role="alert"' if problem else ' role="status"'
        self.status.value = f'<div class="mrrpy-msg"{role}>{_esc(text)}</div>'

    def _say_list(self, title, items, problem=True):
        role = ' role="alert"' if problem else ' role="status"'
        lis = "".join(f"<li>{_esc(i)}</li>" for i in items)
        self.status.value = (f'<div class="mrrpy-msg"{role}><b>{_esc(title)}</b>'
                             f"<ol>{lis}</ol></div>")

    def _apply_start(self, _btn=None):
        sp = S.STARTING_POINT_BY_KEY[self.start.value]
        self.set_values(**sp.values)
        for name in sp.focus:
            if name in self._accordion_of:
                self._accordion_of[name].selected_index = 0
        changes = ", ".join(f"{n} = {S.format_value(S.param(n), v)}"
                            for n, v in sp.values.items())
        self._say(f"Starting point applied: {sp.label}." + (f" Set {changes}." if changes else ""))

    def _load_clicked(self, _btn=None):
        path = os.path.expanduser(self.load_path.value.strip())
        try:
            self.load(path)
        except (OSError, ValueError, AttributeError, ImportError) as exc:
            self._say(f"Could not load {path!r}: {exc}", problem=True)
            return
        self.save_path.value = path
        self._say(f"Loaded {path}.")

    def _report_check(self):
        probs = self.problems()
        if probs:
            self._say_list(f"Found {len(probs)} problem{'s' if len(probs) > 1 else ''}:", probs)
        else:
            self._say("Checked: no problems found. You can save or run it.")
        return probs

    def _save_clicked(self):
        try:
            path = self.save()
        except (OSError, ValueError) as exc:
            self._say(f"Not saved: {exc}", problem=True)
            return None
        probs = S.problems(self.config)
        note = (f" It still has {len(probs)} problem(s); press Check settings to see them."
                if probs else "")
        self._say(f"Saved {path}. Run it with:  MRRpy run -c {path}.{note}")
        return path

    def _show_text(self, make, what):
        try:
            text = make()
        except ValueError as exc:
            self._say(str(exc), problem=True)
            return
        self.view_box.value = f"<b>{_esc(what)}</b>" + _pre(text)

    def _run_clicked(self):
        probs = self._report_check()
        if probs:
            return None
        stages = _STAGES[self.stage.value][1]
        self._say("Running… progress, the model's log and the results are in step 6.")
        try:
            results = self.run(stages)
        except Exception as exc:   # noqa: BLE001 — report any failure in the form
            self._say(f"The run stopped: {exc}  The full log is in step 6"
                      + (f" and in {self.log_path}." if self.log_path else "."), problem=True)
            return None
        self._say(f"Finished at {time.strftime('%H:%M:%S')}. Results are in "
                  f"{os.path.abspath(self.config.OUTPUT_DIR)}; the log is in {self.log_path}. "
                  "In code: form.results")
        return results

    # ── Display ───────────────────────────────────────────────────────────────
    def _repr_mimebundle_(self, **kwargs):
        return self.widget._repr_mimebundle_(**kwargs)
