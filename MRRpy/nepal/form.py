# -*- coding: utf-8 -*-
"""
form.py
=======
``NepalForm`` — the MRRpy-Nepal interface for Jupyter (JupyterLab, Notebook
7, VS Code, Colab).  Needs ipywidgets (``pip install MRRpy[notebook]``).

    from MRRpy.nepal import NepalForm
    form = NepalForm()
    form                       # shows it

Three steps and a separate tab:

    1 Site      a results folder, a DEM file and an outlet, or typed numbers
                → "Measure the catchment"
    2 Methods   which manual (ticks its methods) and what you are designing
                (ticks its return periods); each ticked method opens only the
                inputs it needs
    3 Results   the table with validity flags, the official range, the physics
                model's floods, a chart; save the table, chart and report
    Monthly and low flows   MIP 1982, WECS/DHM and MHSP, and the e-flow

Everything the form does is ordinary Python: ``form.study`` is the
NepalStudy it describes, ``form.compute()`` runs it and ``form.result`` holds
the outcome.  Like the MRRpy configuration form: every input has a visible
label, explanations are text (not hover tooltips), problems are written
out, and it works from the keyboard.
"""

import contextlib
import html
import io
import os
import pprint
import re
import time
import traceback

try:
    import ipywidgets as W
except ImportError as exc:   # pragma: no cover - exercised without ipywidgets
    raise ImportError(
        "The Nepal form needs ipywidgets: pip install MRRpy[notebook] (or: pip install "
        "ipywidgets).  Without it, use the command line (MRRpy nepal estimate …) or "
        "MRRpy.nepal.NepalStudy in code."
    ) from exc

from ..interactive.form import _CSS
from . import design_storm as ds
from . import frequency as fq
from . import guidelines as gl
from .descriptors import CatchmentDescriptors
from .flows import MIP_1982, MONTHLY_METHODS, monthly_flows
from .methods import (FLOOD_METHODS, GROUPS, INPUTS, MHSP_REGIONS, OFFERED_RETURN_PERIODS,
                      parse_table)
from .study import PHYSICS_DEFAULTS, NepalStudy

_NONE = "__none__"
_FIELD = dict(width="100%", max_width="46em")
_LABEL = "17em"
_LOG_LINES = 300

_EXTRA_CSS = """
<style>
.mrrpy-form .mrrpy-periods .widget-checkbox { width: auto !important; margin-right: 0.8em; }
.mrrpy-form table.mrrpy-table { border-collapse: collapse; font-size: 0.9em; margin: 0.4em 0; }
.mrrpy-form table.mrrpy-table th, .mrrpy-form table.mrrpy-table td {
  padding: 0.2em 0.6em; border-bottom: 1px solid var(--jp-border-color2, #ddd); text-align: right; }
.mrrpy-form table.mrrpy-table th:first-child, .mrrpy-form table.mrrpy-table td:first-child,
.mrrpy-form table.mrrpy-table td.mrrpy-left { text-align: left; }
</style>
"""


def _esc(text):
    return html.escape(str(text))


def _html(value=""):
    return W.HTML(value)


def _help(text):
    return _html(f'<div class="mrrpy-help">{_esc(text)}</div>')


def _style():
    return {"description_width": _LABEL}


def _display(widget, visible):
    widget.layout.display = "" if visible else "none"


def _branch(children):
    box = W.VBox(children)
    box.add_class("mrrpy-branch")
    return box


def _pre(text):
    return f'<pre class="mrrpy-text">{_esc(text)}</pre>'


# ── parsing typed text ───────────────────────────────────────────────────────
def parse_series(text):
    """A CSV path (kept as text) or numbers separated by commas/spaces/lines → list; '' → None."""
    s = (text or "").strip()
    if not s:
        return None
    if s.lower().endswith((".csv", ".txt")) or os.path.sep in s or os.path.exists(s):
        return os.path.expanduser(s.strip("'\""))
    try:
        return [float(x) for x in re.split(r"[,;\s]+", s) if x]
    except ValueError:
        raise ValueError("Give a CSV file path, or the yearly values separated by commas.") from None


def _optional_float(text, label):
    s = (text or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"{label}: {s!r} is not a number.") from None


class NepalForm:
    """The MRRpy-Nepal interface for Jupyter.  ``NepalForm(study)`` starts from a study."""

    def __init__(self, study=None, show_help=True):
        self.result = None
        self.monthly = None
        self.descriptors = None
        self._busy = False
        self._log = []
        self._build()
        if study is not None:
            self.load(study if isinstance(study, NepalStudy) else NepalStudy.load(study))
        else:
            self._apply_agency()
            self._apply_structure()
        self._refresh()
        self.help_toggle.value = bool(show_help)

    # ═════════════════════════════════════════════════════════════════════════
    # Layout
    # ═════════════════════════════════════════════════════════════════════════
    def _build(self):
        intro = _html(
            '<div class="mrrpy-intro"><b>MRRpy-Nepal.</b> Flood estimates by the official '
            "Nepali methods, next to MRRpy's physics model. Work through "
            "<i>1 Site → 2 Methods → 3 Results</i>; monthly and low flows are on the last "
            "tab. Formulas and coefficients come from the compendium <i>Nepal Flood "
            "Estimation Methods</i>.</div>")
        self.help_toggle = W.Checkbox(value=True, indent=False,
                                      description="Show an explanation under every setting")
        self.help_toggle.observe(lambda _c: self._apply_help(), names="value")
        self._helps = []
        pages = [self._site_page(), self._methods_page(), self._results_page(),
                 self._monthly_page()]
        self.tabs = W.Tab(children=pages, titles=["1 Site", "2 Methods", "3 Results",
                                                  "Monthly and low flows"])
        self.status = _html()
        self.widget = W.VBox([_html(_CSS + _EXTRA_CSS), intro, self.help_toggle, self.tabs,
                              self.status])
        self.widget.add_class("mrrpy-form")

    def _h(self, text):
        w = _help(text)
        self._helps.append(w)
        return w

    def _nav(self, back=None, nxt=None):
        items = []
        if back is not None:
            b = W.Button(description=f"‹ Back: {back[1]}")
            b.on_click(lambda _b: self.go(back[0]))
            items.append(b)
        if nxt is not None:
            n = W.Button(description=f"Next: {nxt[1]} ›", button_style="primary")
            n.on_click(lambda _b: self.go(nxt[0]))
            items.append(n)
        return W.HBox(items, layout=W.Layout(margin="1em 0 0 0"))

    def go(self, index):
        """Show tab *index* (0 Site, 1 Methods, 2 Results, 3 Monthly)."""
        self.tabs.selected_index = int(index)

    # ── 1 Site ───────────────────────────────────────────────────────────────
    def _site_page(self):
        self.site_mode = W.RadioButtons(
            options=[("A results folder from an MRRpy run (catchment already delineated)", "results"),
                     ("A DEM file and an outlet point (delineated here)", "dem"),
                     ("Type the catchment numbers (no DEM: no physics model)", "numbers")],
            description="The catchment from", style=_style(), layout=W.Layout(**_FIELD))
        self.results_dir = W.Text(description="Results folder", placeholder="e.g. results/",
                                  style=_style(), layout=W.Layout(**_FIELD))
        self.dem_path = W.Text(description="DEM file (GeoTIFF)", placeholder="path to a DEM",
                               style=_style(), layout=W.Layout(**_FIELD))
        self.outlet = W.Text(description="Outlet (latitude, longitude)",
                             placeholder="e.g. 28.71, 80.95", style=_style(),
                             layout=W.Layout(**_FIELD))
        self.dem_folder = W.Text(value="results", description="Results folder to create",
                                 style=_style(), layout=W.Layout(**_FIELD))
        self.area = W.FloatText(value=65.0, description="Area A (km²)", style=_style(),
                                layout=W.Layout(**_FIELD))
        self.num = {}
        for key, label in (("area_below_3000_km2", "Area below 3,000 m (km²)"),
                           ("area_below_5000_km2", "Area below 5,000 m (km²)"),
                           ("snow_area_km2", "Permanent snow (km²)"),
                           ("flow_length_km", "Longest flow path L (km)"),
                           ("flow_path_slope", "Slope of L (m/m)"),
                           ("max_elevation_m", "Highest point (m)")):
            self.num[key] = W.Text(description=label, placeholder="empty = not known",
                                   style=_style(), layout=W.Layout(**_FIELD))
        self.site_name = W.Text(description="Site name (optional)", placeholder="e.g. Khutiya Khola",
                                style=_style(), layout=W.Layout(**_FIELD))
        self.branch_results = _branch([self.results_dir, self._h(
            "The folder an earlier MRRpy run wrote (it holds clipped_dem.tif and watershed.tif). "
            "Run the MRRpy configuration form or 'MRRpy run --stages process_dem' first.")])
        self.branch_dem = _branch([self.dem_path, self.outlet, self.dem_folder, self._h(
            "The catchment upstream of the outlet is delineated on the DEM (the UTM zone of the "
            "outlet is used for the grid), then measured.")])
        self.branch_numbers = _branch([self.area] + list(self.num.values()) + [self._h(
            "Empty boxes are taken as: the whole area below 3,000 m and 5,000 m (as for a Terai "
            "or Chure catchment) and no permanent snow. L and S are needed by the Rational "
            "method only.")])
        self.measure_btn = W.Button(description="Measure the catchment", button_style="primary",
                                    icon="crosshairs")
        self.measure_btn.on_click(lambda _b: self._measure_clicked())
        self.site_box = _html('<div class="mrrpy-msg" role="status">Not measured yet.</div>')
        self.site_mode.observe(lambda _c: self._refresh(), names="value")
        head = _html("<h3>Step 1 of 3: Site</h3>")
        return W.VBox([head, self.site_mode, self.branch_results, self.branch_dem,
                       self.branch_numbers, self.site_name, W.HBox([self.measure_btn]),
                       self.site_box, self._nav(nxt=(1, "Methods"))])

    # ── 2 Methods ────────────────────────────────────────────────────────────
    def _methods_page(self):
        self.agency = W.Dropdown(options=[(a.label, a.key) for a in gl.AGENCIES.values()],
                                 value="recommended", description="Which manual or approach?",
                                 style=_style(), layout=W.Layout(**_FIELD))
        self.structure = W.Dropdown(options=[(s.label, s.key) for s in gl.STRUCTURES.values()],
                                    value="study", description="What are you designing?",
                                    style=_style(), layout=W.Layout(**_FIELD))
        self.design_note = _html()
        self.agency.observe(lambda _c: (self._apply_agency(), self._refresh()), names="value")
        self.structure.observe(lambda _c: (self._apply_structure(), self._refresh()), names="value")
        self.periods = {t: W.Checkbox(value=False, description=f"{t} y", indent=False,
                                      layout=W.Layout(width="auto"))
                        for t in OFFERED_RETURN_PERIODS}
        periods_box = W.HBox(list(self.periods.values()), layout=W.Layout(flex_flow="row wrap"))
        periods_box.add_class("mrrpy-periods")

        # Inputs (each widget is made once; a shared one may appear in two branches).
        self.inp = {}
        self.inp["mhsp_region"] = W.Dropdown(
            options=[("choose the region", _NONE)] + [(r.capitalize(), r) for r in MHSP_REGIONS],
            description=INPUTS["mhsp_region"].label, style=_style(), layout=W.Layout(**_FIELD))
        self.inp["runoff_coefficient"] = W.Text(description="Runoff coefficient C",
                                                placeholder="e.g. 0.45", style=_style(),
                                                layout=W.Layout(**_FIELD))
        self.rain_mode = W.RadioButtons(
            options=[("Typed 24-hour design rainfall R24 by return period", "table"),
                     ("A rain-gauge record: one annual maximum daily rainfall per year", "series")],
            description="Design rainfall from", style=_style(), layout=W.Layout(**_FIELD))
        self.inp["rain_24h"] = W.Text(description="R24 (mm)", placeholder="e.g. 2: 120, 100: 250",
                                      style=_style(), layout=W.Layout(**_FIELD))
        self.inp["rain_annual_max"] = W.Textarea(
            description="Annual maximum rainfall (mm)", rows=2,
            placeholder="a CSV path, or the yearly values: 112, 98, 140, …", style=_style(),
            layout=W.Layout(**_FIELD))
        self.inp["rain_distribution"] = W.Dropdown(
            options=[(fq.DISTRIBUTION_LABELS[d], d) for d in fq.DISTRIBUTIONS], value="gumbel",
            description="Fit with", style=_style(), layout=W.Layout(**_FIELD))
        self.inp["rain_fixed_day_factor"] = W.FloatText(
            value=1.0, description=INPUTS["rain_fixed_day_factor"].label, style=_style(),
            layout=W.Layout(**_FIELD))
        self.inp["flood_annual_max"] = W.Textarea(
            description="Annual maximum floods (m³/s)", rows=2,
            placeholder="a CSV path, or the yearly peaks: 410, 380, 655, …", style=_style(),
            layout=W.Layout(**_FIELD))
        self.inp["flood_distribution"] = W.Dropdown(
            options=[(fq.DISTRIBUTION_LABELS[d], d) for d in fq.DISTRIBUTIONS], value="gumbel",
            description="Fit with", style=_style(), layout=W.Layout(**_FIELD))
        self.inp["donor_area_km2"] = W.Text(description="Donor area (km²)", placeholder="e.g. 1148",
                                            style=_style(), layout=W.Layout(**_FIELD))
        self.donor_mode = W.RadioButtons(
            options=[("Its design floods, typed", "table"),
                     ("Its annual maximum floods (fitted)", "series")],
            description="Donor floods from", style=_style(), layout=W.Layout(**_FIELD))
        self.inp["donor_floods"] = W.Text(description="Donor floods (m³/s)",
                                          placeholder="e.g. 2: 900, 100: 4200", style=_style(),
                                          layout=W.Layout(**_FIELD))
        self.inp["donor_annual_max"] = W.Textarea(
            description="Donor annual maxima (m³/s)", rows=2, placeholder="a CSV path, or values",
            style=_style(), layout=W.Layout(**_FIELD))
        self.inp["area_ratio_exponent"] = W.FloatText(value=0.8, description="Area-ratio exponent n",
                                                      style=_style(), layout=W.Layout(**_FIELD))
        self.inp["dickens_constant"] = W.FloatText(value=11.4, description="Dickens constant C_D",
                                                   style=_style(), layout=W.Layout(**_FIELD))
        self.inp["ryves_constant"] = W.FloatText(value=10.2, description="Ryves constant C_R",
                                                 style=_style(), layout=W.Layout(**_FIELD))

        self.phys = {
            "return_periods": W.Text(description=PHYSICS_LABELS_FORM["return_periods"],
                                     placeholder="empty = the design return period",
                                     style=_style(), layout=W.Layout(**_FIELD)),
            "curve_number": W.FloatText(value=75.0, description="SCS curve number",
                                        style=_style(), layout=W.Layout(**_FIELD)),
            "pattern": W.Dropdown(options=[(v, k) for k, v in ds.PATTERNS.items()], value="center",
                                  description="Storm time pattern", style=_style(),
                                  layout=W.Layout(**_FIELD)),
            "duration_h": W.FloatText(value=24.0, description="Storm duration (h)", style=_style(),
                                      layout=W.Layout(**_FIELD)),
            "step_min": W.FloatText(value=15.0, description="Storm time step (min)",
                                    style=_style(), layout=W.Layout(**_FIELD)),
            "climate_factor": W.FloatText(value=1.0, description="Climate factor on R24",
                                          style=_style(), layout=W.Layout(**_FIELD)),
            "areal_reduction": W.FloatText(value=1.0, description="Areal reduction factor",
                                           style=_style(), layout=W.Layout(**_FIELD)),
            "snow_ramp": W.Checkbox(value=True, indent=False,
                                    description="Less rain above 3,000 m, none above 5,000 m"),
            "model_config": W.Text(description="Model settings file (optional)",
                                   placeholder="run.yaml — empty = SCS curve number model",
                                   style=_style(), layout=W.Layout(**_FIELD)),
        }

        self.method_checks, self.method_branches = {}, {}
        branches = self._method_branches()
        blocks = []
        for group, title in GROUPS.items():
            items = [_html(f"<b>{_esc(title)}</b>")]
            for key, m in FLOOD_METHODS.items():
                if m.group != group:
                    continue
                cb = W.Checkbox(value=False, indent=False, layout=W.Layout(width="auto"),
                                description=f"{m.name} — {m.gives}")
                cb.observe(lambda _c: self._refresh(), names="value")
                self.method_checks[key] = cb
                br = _branch(branches.get(key, []))
                self.method_branches[key] = br
                items += [cb, br]
            if group == "rainfall":
                items.append(self._rain_block())
            box = W.VBox(items, layout=W.Layout(margin="0 0 0.8em 0"))
            blocks.append(box)
        self.rain_mode.observe(lambda _c: self._refresh(), names="value")
        self.donor_mode.observe(lambda _c: self._refresh(), names="value")

        self.observed = W.Textarea(description="Observed floods", rows=2,
                                   placeholder="one per line: label = m³/s, e.g. 2021 flood "
                                               "marks = 410", style=_style(),
                                   layout=W.Layout(**_FIELD))
        observed_acc = W.Accordion(children=[W.VBox([self.observed, self._h(
            "Floods with no return period — from surveyed flood marks (slope-area method) or the "
            "largest gauged flood — drawn on the chart as reference lines.")])],
            titles=("Observed floods (optional)",))
        observed_acc.selected_index = None
        head = _html("<h3>Step 2 of 3: Methods</h3>")
        return W.VBox([head, self.agency, self.structure, self.design_note,
                       _html("<b>Return periods</b>"), periods_box,
                       self._h("The structure ticks its design return period(s); tick any others "
                               "you want in the table."),
                       _html("<h4>Methods</h4>")] + blocks +
                      [observed_acc, self._nav(back=(0, "Site"), nxt=(2, "Results"))])

    def _method_branches(self):
        i, p = self.inp, self.phys
        more = W.Accordion(children=[W.VBox([p["step_min"], p["areal_reduction"],
                                             p["model_config"], self._h(
            "Areal reduction turns point rainfall into a catchment average (1 = none). A model "
            "settings file (an MRRpy run.yaml) replaces the default SCS curve-number model with "
            "your own runoff and routing.")])], titles=("More options: physics model",))
        more.selected_index = None
        return {
            "mhsp_1997": [i["mhsp_region"], self._h(INPUTS["mhsp_region"].help)],
            "rational": [i["runoff_coefficient"], self._h(INPUTS["runoff_coefficient"].help)],
            "physics": [p["return_periods"], p["curve_number"], p["pattern"], p["duration_h"],
                        p["climate_factor"], p["snow_ramp"], self._h(
                "The design storm (Mononobe curve, alternating blocks) runs through the MRRpy "
                "model on the delineated DEM, once per return period. Default model: SCS curve "
                "number, kinematic routing, channels sized by the WECS/DHM 2-year flood."), more],
            "frequency": [i["flood_annual_max"], i["flood_distribution"],
                          self._h(INPUTS["flood_annual_max"].help)],
            "area_ratio": [i["donor_area_km2"], self.donor_mode, i["donor_floods"],
                           i["donor_annual_max"], i["area_ratio_exponent"],
                           self._h(INPUTS["area_ratio_exponent"].help)],
            "dickens": [i["dickens_constant"], self._h(INPUTS["dickens_constant"].help)],
            "ryves": [i["ryves_constant"], self._h(INPUTS["ryves_constant"].help)],
        }

    def _rain_block(self):
        i = self.inp
        more = W.Accordion(children=[W.VBox([i["rain_fixed_day_factor"],
                                             self._h(INPUTS["rain_fixed_day_factor"].help)])],
                           titles=("More options: rainfall",))
        more.selected_index = None
        self.rain_box = _branch([_html("<b>Design rainfall</b> (used by the Rational method and "
                                       "the physics model)"),
                                 self.rain_mode, i["rain_24h"], i["rain_annual_max"],
                                 i["rain_distribution"], self._h(INPUTS["rain_24h"].help), more])
        return self.rain_box

    # ── 3 Results ────────────────────────────────────────────────────────────
    def _results_page(self):
        self.compute_btn = W.Button(description="Compute the estimates", button_style="warning",
                                    icon="play")
        self.compute_btn.on_click(lambda _b: self._compute_clicked())
        self.run_state = _html('<div class="mrrpy-msg" role="status"><b>Status:</b> not computed '
                               "yet.</div>")
        self.results_box = W.VBox([])
        self.save_dir = W.Text(description="Save in folder", placeholder="empty = <results>/nepal",
                               style=_style(), layout=W.Layout(**_FIELD))
        self.save_btn = W.Button(description="Save table, chart and report", button_style="success")
        self.save_btn.on_click(lambda _b: self._save_clicked())
        self.study_path = W.Text(value="nepal_study.yaml", description="Study file",
                                 style=_style(), layout=W.Layout(**_FIELD))
        self.study_btn = W.Button(description="Save the study (YAML)")
        self.study_btn.on_click(lambda _b: self._save_study_clicked())
        self.python_btn = W.Button(description="Show Python code")
        self.python_btn.on_click(lambda _b: self._show_python())
        self.view_box = _html()
        self.log_box = _html(_pre("The model's log appears here when the physics model runs."))
        head = _html("<h3>Step 3 of 3: Results</h3>")
        return W.VBox([head, W.HBox([self.compute_btn]), self.run_state, self.results_box,
                       W.HBox([self.save_dir, self.save_btn]),
                       W.HBox([self.study_path, self.study_btn]), W.HBox([self.python_btn]),
                       self.view_box, _html("<h4>Log</h4>"), self.log_box,
                       self._nav(back=(1, "Methods"))])

    # ── Monthly ──────────────────────────────────────────────────────────────
    def _monthly_page(self):
        self.mon_checks = {k: W.Checkbox(value=(k != "mhsp_1997"), indent=False,
                                         description=v, layout=W.Layout(width="auto"))
                           for k, v in MONTHLY_METHODS.items()}
        self.mip_region = W.Dropdown(options=[("choose the region", _NONE)]
                                     + [(f"Region {r}", r) for r in MIP_1982],
                                     description="MIP 1982 region", style=_style(),
                                     layout=W.Layout(**_FIELD))
        self.mip_measured = W.Textarea(description="Dry-season measurements", rows=2,
                                       placeholder="one per line: date = m³/s, e.g. "
                                                   "2024-02-15 = 1.5", style=_style(),
                                       layout=W.Layout(**_FIELD))
        self.mmp = W.Text(description="Mean monsoon rain MMP (mm)", placeholder="June–September, "
                          "from the DHM isohyetal map", style=_style(), layout=W.Layout(**_FIELD))
        self.mip_branch = _branch([self.mip_region, self.mip_measured, self._h(
            "Measure the flow between November and April, away from rain; with several "
            "measurements the lowest implied April flow is used (Shrestha et al. 2010).")])
        self.mmp_branch = _branch([self.mmp, self._h(
            "WECS/DHM and MHSP use the catchment area (and the area below 5,000 m) from step 1 "
            "and the mean monsoon precipitation.")])
        for cb in self.mon_checks.values():
            cb.observe(lambda _c: self._refresh(), names="value")
        self.mon_btn = W.Button(description="Compute monthly flows", button_style="warning")
        self.mon_btn.on_click(lambda _b: self._monthly_clicked())
        self.mon_box = _html()
        return W.VBox([_html("<h3>Monthly and low flows</h3>"), self._h(
            "Calculators from the irrigation and hydropower manuals — they need no physics "
            "model. Also gives the 'lower of WECS/DHM and MIP' low-flow rule and the e-flow "
            "release."), self.mon_checks["mip_1982"], self.mip_branch,
                       self.mon_checks["wecs_dhm"], self.mon_checks["mhsp_1997"],
                       self.mmp_branch, W.HBox([self.mon_btn]), self.mon_box])

    # ═════════════════════════════════════════════════════════════════════════
    # Reactions
    # ═════════════════════════════════════════════════════════════════════════
    def _apply_help(self):
        for w in self._helps:
            _display(w, self.help_toggle.value)

    def _apply_agency(self):
        keys = gl.methods_for(self.agency.value, self.descriptors, **self._data_flags())
        for key, cb in self.method_checks.items():
            cb.value = key in keys
        self._preset_methods = list(self.methods)

    def _apply_structure(self):
        wanted = set(gl.return_periods_for(self.structure.value))
        for t, cb in self.periods.items():
            cb.value = t in wanted

    def _data_flags(self):
        try:
            inputs = self._inputs(strict=False)
        except ValueError:
            inputs = {}
        return NepalStudy({"numbers": {"area_km2": 1.0}}, inputs=inputs).data_flags()

    def _refresh(self):
        mode = self.site_mode.value
        _display(self.branch_results, mode == "results")
        _display(self.branch_dem, mode == "dem")
        _display(self.branch_numbers, mode == "numbers")
        for key, br in self.method_branches.items():
            _display(br, self.method_checks[key].value and bool(br.children))
        rain_used = any(self.method_checks[k].value for k in ("rational", "physics"))
        _display(self.rain_box, rain_used)
        table = self.rain_mode.value == "table"
        for k in ("rain_24h",):
            _display(self.inp[k], table)
        for k in ("rain_annual_max", "rain_distribution"):
            _display(self.inp[k], not table)
        donor_table = self.donor_mode.value == "table"
        _display(self.inp["donor_floods"], donor_table)
        _display(self.inp["donor_annual_max"], not donor_table)
        a, s = gl.AGENCIES[self.agency.value], gl.STRUCTURES[self.structure.value]
        note = f"{a.note} " if a.note else ""
        if a.not_yet:
            note += f"Not yet in MRRpy-Nepal: {', '.join(a.not_yet)}. "
        self.design_note.value = (f'<div class="mrrpy-help">{_esc(note)}<br>'
                                  f"{_esc(s.describe())}.</div>")
        _display(self.mip_branch, self.mon_checks["mip_1982"].value)
        _display(self.mmp_branch, self.mon_checks["wecs_dhm"].value
                 or self.mon_checks["mhsp_1997"].value)
        self._apply_help()

    def _say(self, text, problem=False):
        role = 'role="alert"' if problem else 'role="status"'
        prefix = "<b>Problem:</b> " if problem else ""
        self.status.value = f'<div class="mrrpy-msg" {role}>{prefix}{_esc(text)}</div>'

    # ═════════════════════════════════════════════════════════════════════════
    # Values in and out
    # ═════════════════════════════════════════════════════════════════════════
    def site(self):
        """The site dict the step-1 boxes describe (ValueError when incomplete)."""
        mode = self.site_mode.value
        if mode == "results":
            folder = self.results_dir.value.strip()
            if not folder:
                raise ValueError("Give the results folder of an MRRpy run.")
            return {"results": os.path.expanduser(folder)}
        if mode == "dem":
            dem = self.dem_path.value.strip()
            if not dem:
                raise ValueError("Give the DEM file.")
            try:
                lat, lon = (float(x) for x in re.split(r"[,;\s]+", self.outlet.value.strip()) if x)
            except ValueError:
                raise ValueError("Give the outlet as 'latitude, longitude', e.g. 28.71, 80.95.") from None
            return {"dem": os.path.expanduser(dem), "outlet": [lat, lon],
                    "folder": self.dem_folder.value.strip() or "results"}
        values = {"area_km2": float(self.area.value)}
        labels = {k: w.description for k, w in self.num.items()}
        for key, w in self.num.items():
            v = _optional_float(w.value, labels[key])
            if v is not None:
                values[key] = v
        CatchmentDescriptors.from_dict(values)            # checks the numbers now
        return {"numbers": values}

    def _inputs(self, strict=True):
        i, out = self.inp, {}
        on = {k for k, cb in self.method_checks.items() if cb.value}

        def take(key, fn):
            try:
                v = fn()
            except ValueError:
                if strict:
                    raise
                return
            if v is not None:
                out[key] = v
        if "mhsp_1997" in on and i["mhsp_region"].value != _NONE:
            out["mhsp_region"] = i["mhsp_region"].value
        if "rational" in on:
            take("runoff_coefficient", lambda: _optional_float(i["runoff_coefficient"].value,
                                                                "Runoff coefficient C"))
        if on & {"rational", "physics"}:
            if self.rain_mode.value == "table":
                take("rain_24h", lambda: parse_table(i["rain_24h"].value))
            else:
                take("rain_annual_max", lambda: parse_series(i["rain_annual_max"].value))
                out["rain_distribution"] = i["rain_distribution"].value
            if float(i["rain_fixed_day_factor"].value or 1.0) != 1.0:
                out["rain_fixed_day_factor"] = float(i["rain_fixed_day_factor"].value)
        if "frequency" in on:
            take("flood_annual_max", lambda: parse_series(i["flood_annual_max"].value))
            out["flood_distribution"] = i["flood_distribution"].value
        if "area_ratio" in on:
            take("donor_area_km2", lambda: _optional_float(i["donor_area_km2"].value, "Donor area"))
            if self.donor_mode.value == "table":
                take("donor_floods", lambda: parse_table(i["donor_floods"].value))
            else:
                take("donor_annual_max", lambda: parse_series(i["donor_annual_max"].value))
                out["flood_distribution"] = i["flood_distribution"].value
            out["area_ratio_exponent"] = float(i["area_ratio_exponent"].value)
        if "dickens" in on:
            out["dickens_constant"] = float(i["dickens_constant"].value)
        if "ryves" in on:
            out["ryves_constant"] = float(i["ryves_constant"].value)
        return out

    def _physics(self):
        p = self.phys
        out = {k: (float(p[k].value) if k not in ("pattern",) else p[k].value)
               for k in ("curve_number", "pattern", "duration_h", "step_min", "climate_factor",
                         "areal_reduction")}
        out["snow_ramp"] = bool(p["snow_ramp"].value)
        t = p["return_periods"].value.strip()
        if t:
            try:
                out["return_periods"] = [float(x) for x in re.split(r"[,;\s]+", t) if x]
            except ValueError:
                raise ValueError("Physics return periods: give numbers, e.g. 50, 100.") from None
        cfg = p["model_config"].value.strip()
        if cfg:
            out["model_config"] = os.path.expanduser(cfg)
        return {k: v for k, v in out.items() if v != PHYSICS_DEFAULTS.get(k)}

    def _observed(self):
        out = []
        for n, line in enumerate(self.observed.value.splitlines(), 1):
            if not line.strip():
                continue
            label, sep, q = line.rpartition("=")
            if not sep:
                raise ValueError(f"Observed floods, line {n}: write 'label = m³/s'.")
            out.append((label.strip(), float(q)))
        return out

    @property
    def methods(self):
        """The ticked method keys."""
        return [k for k, cb in self.method_checks.items() if cb.value]

    @property
    def return_periods(self):
        """The ticked return periods."""
        return [t for t, cb in self.periods.items() if cb.value]

    @property
    def study(self):
        """The NepalStudy the form describes (ValueError if something can't be read)."""
        if not self.methods:
            raise ValueError("Tick at least one method in step 2.")
        if not self.return_periods:
            raise ValueError("Tick at least one return period in step 2.")
        return NepalStudy(self.site(), name=self.site_name.value.strip(),
                          agency=self.agency.value, structure=self.structure.value,
                          methods=self.methods, return_periods=self.return_periods,
                          inputs=self._inputs(), physics=self._physics(),
                          output_dir=self.save_dir.value.strip() or None,
                          observed_floods=self._observed())

    def load(self, study):
        """Fill the form from a NepalStudy."""
        site = study.site
        if "results" in site:
            self.site_mode.value, self.results_dir.value = "results", site["results"]
        elif "dem" in site:
            self.site_mode.value, self.dem_path.value = "dem", site["dem"]
            self.outlet.value = ", ".join(str(v) for v in site["outlet"])
            self.dem_folder.value = site.get("folder") or "results"
        elif "numbers" in site:
            self.site_mode.value = "numbers"
            vals = dict(site["numbers"])
            self.area.value = float(vals.get("area_km2", 65.0))
            for k, w in self.num.items():
                w.value = "" if vals.get(k) is None else f"{vals[k]:g}"
        else:
            raise ValueError("The form cannot show a study built on a Config object.")
        self.site_name.value = study.name or ""
        inp = study.inputs
        if inp.get("mhsp_region"):
            self.inp["mhsp_region"].value = inp["mhsp_region"]
        for key in ("runoff_coefficient", "donor_area_km2"):
            if inp.get(key) is not None:
                self.inp[key].value = f"{inp[key]:g}"
        for key in ("rain_24h", "donor_floods"):
            if inp.get(key):
                self.inp[key].value = ", ".join(f"{fq._tkey(t)}: {v:g}" for t, v in inp[key].items())
        for key in ("rain_annual_max", "flood_annual_max", "donor_annual_max"):
            v = inp.get(key)
            if v is not None:
                self.inp[key].value = v if isinstance(v, str) else ", ".join(f"{x:g}" for x in v)
        if inp.get("rain_annual_max") is not None:
            self.rain_mode.value = "series"
        if inp.get("donor_annual_max") is not None:
            self.donor_mode.value = "series"
        for key in ("rain_distribution", "flood_distribution"):
            if inp.get(key):
                self.inp[key].value = inp[key]
        for key in ("rain_fixed_day_factor", "area_ratio_exponent", "dickens_constant",
                    "ryves_constant"):
            if inp.get(key) is not None:
                self.inp[key].value = float(inp[key])
        p = study.physics
        for key in ("curve_number", "duration_h", "step_min", "climate_factor", "areal_reduction"):
            self.phys[key].value = float(p[key])
        self.phys["pattern"].value = p["pattern"]
        self.phys["snow_ramp"].value = bool(p["snow_ramp"])
        if p.get("return_periods"):
            self.phys["return_periods"].value = ", ".join(f"{fq._tkey(t)}" for t in p["return_periods"])
        if p.get("model_config") and isinstance(p["model_config"], str):
            self.phys["model_config"].value = p["model_config"]
        self.observed.value = "\n".join(f"{a} = {b:g}" for a, b in study.observed_floods)
        self.save_dir.value = study.output_dir or ""
        self.agency.value = study.agency or "recommended"
        self.structure.value = study.structure or "study"
        self._apply_agency()                      # the presets first; explicit lists win
        self._apply_structure()
        if study.methods is not None:
            for k, cb in self.method_checks.items():
                cb.value = k in study.methods
        if study.return_periods is not None:
            for t, cb in self.periods.items():
                cb.value = any(abs(t - x) < 1e-9 for x in study.return_periods)
        self._refresh()

    # ═════════════════════════════════════════════════════════════════════════
    # Actions
    # ═════════════════════════════════════════════════════════════════════════
    def measure(self):
        """Measure (or read) the catchment of step 1; returns the descriptors."""
        study = NepalStudy(self.site(), name=self.site_name.value.strip())
        self.descriptors = self._captured(lambda: study.descriptors(log=self._log_line))
        self._measured_site = study.site
        # 'recommended' depends on the catchment: re-apply it now — unless the boxes were
        # changed by hand since the preset ticked them.
        if self.agency.value == "recommended" and self.methods == self._preset_methods:
            self._apply_agency()
            self._refresh()
        return self.descriptors

    def _measure_clicked(self):
        try:
            self.site_box.value = '<div class="mrrpy-msg" role="status">Measuring…</div>'
            d = self.measure()
        except Exception as exc:   # noqa: BLE001 — report any failure in the form
            self.site_box.value = (f'<div class="mrrpy-msg" role="alert"><b>Problem:</b> '
                                   f"{_esc(exc)}</div>")
            return None
        self.site_box.value = self._descriptor_html(d)
        self._say("Catchment measured. Step 2 ticks the methods for your manual.")
        return d

    def _descriptor_html(self, d):
        rows = "".join(f"<tr><td>{_esc(r['quantity'])}</td><td class='mrrpy-left'>"
                       f"{_esc(r['value'])} {_esc(r['unit'])}</td></tr>"
                       for _i, r in d.table().iterrows())
        notes = "".join(f"<li>Assumed: {_esc(a)}.</li>" for a in d.assumptions())
        return (f'<table class="mrrpy-table">{rows}</table>'
                + (f"<ul>{notes}</ul>" if notes else ""))

    def compute(self, physics=None):
        """Run the study (official methods, and the physics model if ticked); shows and
        returns the NepalResult."""
        study = self.study
        if self.descriptors is not None and study.site == self._measured_site:
            study._descriptors = self.descriptors
        self._log = []
        self.result = self._captured(lambda: study.run(physics=physics, log=self._log_line))
        self.descriptors = self.result.descriptors
        self._measured_site = study.site
        self._show(self.result)
        return self.result

    _measured_site = None
    _preset_methods = None

    def _compute_clicked(self):
        if self._busy:
            return None
        self._busy = True
        self.compute_btn.disabled = True
        self.run_state.value = '<div class="mrrpy-msg" role="status"><b>Status:</b> running…</div>'
        started = time.time()
        try:
            result = self.compute()
        except Exception as exc:   # noqa: BLE001
            self._log_line(traceback.format_exc())
            self.run_state.value = (f'<div class="mrrpy-msg" role="alert"><b>Status: stopped</b> '
                                    f"— {_esc(exc)}</div>")
            self._say(str(exc), problem=True)
            return None
        finally:
            self._busy = False
            self.compute_btn.disabled = False
        self.run_state.value = (f'<div class="mrrpy-msg" role="status"><b>Status: finished</b> in '
                                f"{time.time() - started:.0f} s"
                                + (f"; saved in {_esc(os.path.dirname(result.files['table']))}"
                                   if result.files else "") + ".</div>")
        self._say("Done — the table, the official range and the chart are in step 3.")
        return result

    def _captured(self, fn):
        writer = _Writer(self)
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            return fn()

    def _log_line(self, text):
        self._log.append(str(text).rstrip("\n"))
        lines = "\n".join(self._log).splitlines()[-_LOG_LINES:]
        self.log_box.value = _pre("\n".join(lines))

    def _show(self, result):
        est = result.estimates
        cols = est.columns
        head = "<tr><th>Method</th><th>Status</th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
        from .methods import STATUS_TEXT, _cell
        body = ""
        for r in est.rows:
            cells = "".join(f"<td>{_esc(_cell(q, f))}</td>" for q, f in zip(r["Q"], r["flags"]))
            body += (f"<tr><td>{_esc(r['name'])}</td><td class='mrrpy-left'>"
                     f"{_esc(STATUS_TEXT.get(r['status'], r['status']))}</td>{cells}</tr>")
        env = est.envelope
        env_rows = "".join(
            f"<tr><td>{t}</td><td>{int(e['n_methods'])}</td><td>{_esc(_fmt(e['min']))}</td>"
            f"<td>{_esc(_fmt(e['median']))}</td><td>{_esc(_fmt(e['max']))}</td>"
            f"<td>{_esc(_fmt(e['spread']))}</td></tr>" for t, e in env.iterrows())
        parts = [f"<p>{_esc(result.descriptors.summary())}</p>",
                 "<h4>Flood estimates (m³/s)</h4>",
                 f'<table class="mrrpy-table">{head}{body}</table>',
                 '<div class="mrrpy-help">≈ interpolated between tabulated return periods; * '
                 "extrapolated; – not available. The notes for every method are in the saved "
                 "report.</div>",
                 "<h4>Official range</h4>",
                 '<table class="mrrpy-table"><tr><th>T (years)</th><th>Methods</th><th>Min</th>'
                 f"<th>Median</th><th>Max</th><th>Max ÷ min</th></tr>{env_rows}</table>"]
        if result.physics:
            items = "".join(f"<li>{_esc(f.summary())}</li>" for _t, f in sorted(result.physics.items()))
            parts += ["<h4>Physics model</h4>", f"<ul>{items}</ul>"]
        attention = [(r["name"], r["notes"][0]) for r in est.rows
                     if r["status"] in ("needs input", "outside") and r["notes"]]
        if attention:
            items = "".join(f"<li><b>{_esc(n)}</b>: {_esc(t)}</li>" for n, t in attention)
            parts.append(f'<div class="mrrpy-msg" role="alert"><b>Needs attention</b><ul>{items}'
                         "</ul></div>")
        warnings = result.warnings()
        if warnings:
            items = "".join(f"<li>{_esc(w)}</li>" for w in warnings)
            parts.append(f"<h4>Warnings</h4><ul>{items}</ul>")
        if result.recommendation:
            items = "".join(f"<li>{_esc(w)}</li>" for w in result.recommendation)
            parts.append(f"<h4>The compendium's quick guide for this catchment</h4><ul>{items}</ul>")
        children = [_html("".join(parts))]
        try:
            from matplotlib.figure import Figure
            fig = Figure(figsize=(8.0, 4.8), dpi=100)
            result.plot(ax=fig.subplots())
            buf = io.BytesIO()
            fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
            children.append(W.Image(value=buf.getvalue(), format="png",
                                    layout=W.Layout(max_width="46em")))
        except Exception as exc:   # noqa: BLE001 — the chart is a convenience
            children.append(_html(f'<div class="mrrpy-help">(No chart: {_esc(exc)})</div>'))
        self.results_box.children = children

    def save(self, folder=None):
        """Save the last result's table, chart and report; returns the files."""
        if self.result is None:
            raise ValueError("Compute the estimates first.")
        folder = folder or self.save_dir.value.strip() or self.study.folder or "nepal_results"
        return self.result.save(os.path.expanduser(folder))

    def _save_clicked(self):
        try:
            files = self.save()
        except Exception as exc:   # noqa: BLE001
            self._say(f"Not saved: {exc}", problem=True)
            return None
        self._say("Saved: " + ", ".join(files.values()))
        return files

    def _save_study_clicked(self):
        try:
            path = self.study.save(os.path.expanduser(self.study_path.value.strip() or
                                                      "nepal_study.yaml"))
        except Exception as exc:   # noqa: BLE001
            self._say(f"Not saved: {exc}", problem=True)
            return None
        self._say(f"Study saved to {path}. Run it again with:  MRRpy nepal estimate --study {path}")
        return path

    def to_python(self):
        """Python code that runs the same study."""
        d = pprint.pformat(self.study.to_dict(), width=78, sort_dicts=False)
        return ("from MRRpy.nepal import NepalStudy\n\n"
                f"study = NepalStudy.from_dict({d})\n"
                "result = study.run()\nresult.table\n")

    def _show_python(self):
        try:
            text = self.to_python()
        except ValueError as exc:
            self._say(str(exc), problem=True)
            return
        self.view_box.value = "<b>Python</b>" + _pre(text)

    # ── monthly ──────────────────────────────────────────────────────────────
    def compute_monthly(self):
        """Monthly flows for the ticked methods; shows and returns MonthlyFlows."""
        methods = [k for k, cb in self.mon_checks.items() if cb.value]
        if not methods:
            raise ValueError("Tick at least one monthly method.")
        measurements = []
        for n, line in enumerate(self.mip_measured.value.splitlines(), 1):
            if not line.strip():
                continue
            d, sep, q = line.partition("=")
            if not sep:
                raise ValueError(f"Measurements, line {n}: write 'date = m³/s', e.g. 2024-02-15 = 1.5.")
            measurements.append((d.strip(), float(q)))
        region = None if self.mip_region.value == _NONE else int(self.mip_region.value)
        mmp = _optional_float(self.mmp.value, "Mean monsoon rain")
        desc = self.descriptors
        if desc is None and self.site_mode.value == "numbers":
            desc = CatchmentDescriptors.from_dict(self.site()["numbers"])
        self.monthly = monthly_flows(desc, methods, mip_region=region, measurements=measurements,
                                     mmp_mm=mmp)
        notes = "".join(f"<li>{_esc(n)}</li>" for n in self.monthly.notes)
        if desc is None and (self.mon_checks["wecs_dhm"].value or self.mon_checks["mhsp_1997"].value):
            notes += "<li>Measure the catchment in step 1 for WECS/DHM and MHSP.</li>"
        table = (self.monthly.table.round(3).to_html(classes="mrrpy-table", border=0)
                 if len(self.monthly.table) else "<p>No method could run.</p>")
        self.mon_box.value = f"<h4>Mean monthly flows (m³/s)</h4>{table}<ul>{notes}</ul>"
        return self.monthly

    def _monthly_clicked(self):
        try:
            return self.compute_monthly()
        except Exception as exc:   # noqa: BLE001
            self.mon_box.value = (f'<div class="mrrpy-msg" role="alert"><b>Problem:</b> '
                                  f"{_esc(exc)}</div>")
            return None

    def _repr_mimebundle_(self, **kwargs):
        return self.widget._repr_mimebundle_(**kwargs)


PHYSICS_LABELS_FORM = {"return_periods": "Return periods to simulate"}


class _Writer(io.TextIOBase):
    """Where print() goes while the form runs the model: into the form's log."""

    def __init__(self, form):
        self.form = form
        self._buf = ""

    def write(self, text):
        self._buf += str(text)
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.form._log_line(line)
        return len(text)

    def flush(self):
        if self._buf:
            self.form._log_line(self._buf)
            self._buf = ""


def _fmt(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    return "–" if v != v else f"{v:.4g}"
