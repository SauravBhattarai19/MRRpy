# -*- coding: utf-8 -*-
"""
study.py
========
``NepalStudy`` — one Nepal design-flood study from start to finish:

    site      where the catchment comes from — typed numbers, the results
              folder of an earlier MRRpy run, an MRRpy config file, or a DEM
              file and an outlet (delineated on the spot);
    design    an agency preset (which methods that manual names) and a
              structure (its design return periods) — or explicit lists;
    inputs    what the ticked methods need (MHSP region, C, R24, gauge data);
    physics   how to run the MRRpy model with a design storm.

``run()`` measures the catchment, runs every method, runs the physics model
for the design return period(s), and returns a ``NepalResult`` with the
comparison table, the official range, a chart and a Markdown report — saved
to ``<results folder>/nepal/`` when there is a folder.

    from MRRpy.nepal import NepalStudy
    study = NepalStudy.from_results("results/", agency="dowri_2019",
                                    structure="weir",
                                    inputs={"rain_24h": {2: 120, 50: 230, 100: 250}})
    result = study.run()
    result.table, result.envelope, result.plot()

A study can be saved to and loaded from YAML (``save`` / ``load``) — the
same file drives ``MRRpy nepal estimate --study study.yaml``.
"""

import copy
import os

import numpy as np

from . import frequency as fq
from . import guidelines as gl
from .descriptors import CatchmentDescriptors, delineated, measure_catchment
from .methods import (FLOOD_METHODS, INPUTS, TOR_RETURN_PERIODS, _given, design_rainfall,
                      estimate_floods, resolve_methods)

#: The physics options and their defaults (plus 'enabled': True adds the physics
#: model to the methods, False skips it — e.g. from ``MRRpy nepal estimate --physics``).
PHYSICS_DEFAULTS = {
    "return_periods": None,     # None → the structure's design T (else 100, else the largest)
    "curve_number": 75.0,       # the offline default model: SCS-CN, normal wetness
    "pattern": "center",        # storm time pattern (design_storm.PATTERNS)
    "duration_h": 24.0,
    "step_min": 15.0,
    "areal_reduction": 1.0,
    "climate_factor": 1.0,
    "snow_ramp": True,          # rain share 1 → 0 between 3,000 m and 5,000 m
    "model_config": None,       # a run.yaml / Config to use instead of the default model
    "sim_hours": None,          # None → storm + four Kirpich t_c
}

PHYSICS_LABELS = {
    "return_periods": "Return periods to simulate",
    "curve_number": "SCS curve number",
    "pattern": "Storm time pattern",
    "duration_h": "Storm duration (h)",
    "step_min": "Storm time step (min)",
    "areal_reduction": "Areal reduction factor",
    "climate_factor": "Climate factor on rainfall",
    "snow_ramp": "Less rain above 3,000 m (none above 5,000 m)",
    "model_config": "Model settings file (optional)",
    "sim_hours": "Simulation length (h)",
}

SITE_KINDS = ("numbers", "results", "config", "dem")


class NepalStudy:
    """
    Settings of one study; ``run()`` does the work.  Prefer the
    constructors: ``from_numbers``, ``from_results``, ``from_config``,
    ``from_dem``.
    """

    def __init__(self, site, *, name="", agency=None, structure=None, methods=None,
                 return_periods=None, inputs=None, physics=None, output_dir=None,
                 observed_floods=None):
        self.site = _check_site(site)
        self.name = name or ""
        if agency is not None and agency not in gl.AGENCIES:
            raise ValueError(f"Unknown agency preset {agency!r}; use one of {', '.join(gl.AGENCIES)}.")
        if structure is not None and structure not in gl.STRUCTURES:
            raise ValueError(f"Unknown structure {structure!r}; use one of {', '.join(gl.STRUCTURES)}.")
        self.agency = agency
        self.structure = structure
        self.methods = resolve_methods(methods) if methods is not None else None
        self.return_periods = (list(fq.as_return_periods(return_periods))
                               if return_periods is not None else None)
        inputs = dict(inputs or {})
        unknown = sorted(set(inputs) - set(INPUTS))
        if unknown:
            raise ValueError(f"Unknown input(s) {', '.join(unknown)}; known: {', '.join(INPUTS)}.")
        self.inputs = inputs
        physics = dict(physics or {})
        unknown = sorted(set(physics) - set(PHYSICS_DEFAULTS) - {"enabled"})
        if unknown:
            raise ValueError(f"Unknown physics option(s) {', '.join(unknown)}; known: "
                             f"{', '.join(PHYSICS_DEFAULTS)}.")
        self.physics = {**PHYSICS_DEFAULTS, **physics}
        self.output_dir = output_dir
        self.observed_floods = [(str(a), float(b)) for a, b in (observed_floods or [])]
        self._descriptors = None

    # ── Constructors ─────────────────────────────────────────────────────────
    @classmethod
    def from_numbers(cls, area_km2, *, name="", **kwargs):
        """A study on typed catchment numbers (no DEM; no physics run)."""
        names = set(CatchmentDescriptors.__dataclass_fields__)
        values = {k: kwargs.pop(k) for k in list(kwargs) if k in names}
        values["area_km2"] = area_km2
        return cls({"numbers": values}, name=name, **kwargs)

    @classmethod
    def from_results(cls, folder, **kwargs):
        """A study on the results folder of an earlier MRRpy run (process_dem done)."""
        return cls({"results": os.fspath(folder)}, **kwargs)

    @classmethod
    def from_config(cls, config, **kwargs):
        """A study on an MRRpy config (file or Config); the physics run uses its settings."""
        return cls({"config": config if hasattr(config, "OUTPUT_DIR") else os.fspath(config)},
                   **kwargs)

    @classmethod
    def from_dem(cls, dem, outlet, folder="results", **kwargs):
        """A study on a DEM file and an outlet (lat, lon), delineated into *folder*."""
        lat, lon = (float(v) for v in outlet)
        return cls({"dem": os.fspath(dem), "outlet": [lat, lon], "folder": os.fspath(folder)},
                   **kwargs)

    # ── Site ─────────────────────────────────────────────────────────────────
    @property
    def site_kind(self):
        return next(k for k in SITE_KINDS if k in self.site)

    def model_config(self):
        """The MRRpy Config of the site (None for typed numbers)."""
        from ..config import Config
        from ..utils.crs import utm_epsg
        kind = self.site_kind
        if kind == "numbers":
            return None
        if kind == "results":
            cfg = Config(OUTPUT_DIR=self.site["results"])
        elif kind == "config":
            src = self.site["config"]
            cfg = copy.deepcopy(src) if hasattr(src, "OUTPUT_DIR") else Config.from_file(src)
        else:
            lat, lon = self.site["outlet"]
            cfg = Config(DEM_PATH=self.site["dem"], OUTPUT_POINT=(lat, lon),
                         OUTPUT_DIR=self.site.get("folder") or "results",
                         TARGET_CRS_EPSG=utm_epsg(lat, lon) or "EPSG:32645")
        cfg.OUTPUT_DIR = os.path.abspath(cfg.OUTPUT_DIR or "output")
        cfg.update_output_paths()
        return cfg

    @property
    def folder(self):
        """Where the study writes (``<results>/nepal``), or None for typed numbers
        without an output_dir."""
        if self.output_dir:
            return os.path.abspath(self.output_dir)
        cfg = self.model_config()
        return os.path.join(cfg.OUTPUT_DIR, "nepal") if cfg is not None else None

    def descriptors(self, log=print):
        """The catchment numbers — measured (delineating first for a DEM site)."""
        if self._descriptors is not None:
            return self._descriptors
        if self.site_kind == "numbers":
            values = dict(self.site["numbers"])
            values.setdefault("name", self.name)
            desc = CatchmentDescriptors.from_dict(values)
        else:
            cfg = self.model_config()
            if not delineated(cfg):
                if self.site_kind == "results":
                    raise FileNotFoundError(
                        f"No delineated catchment in {cfg.OUTPUT_DIR}: run the process_dem "
                        "stage there first, or choose a DEM file and an outlet as the site.")
                from ..pipeline import run_pipeline
                log("Delineating the catchment (process_dem) …")
                run_pipeline(cfg, stages=("process_dem",), on_log=log)
            desc = measure_catchment(cfg, name=self.name)
        self._descriptors = desc
        return desc

    # ── Choices ──────────────────────────────────────────────────────────────
    def data_flags(self):
        """What data the inputs hold: has_rainfall / has_gauge / has_donor."""
        i = self.inputs
        return {"has_rainfall": _given(i.get("rain_24h")) or _given(i.get("rain_annual_max")),
                "has_gauge": _given(i.get("flood_annual_max")),
                "has_donor": _given(i.get("donor_area_km2")) and (
                    _given(i.get("donor_floods")) or _given(i.get("donor_annual_max")))}

    def chosen_methods(self, descriptors=None):
        """Explicit methods, else the agency preset, else the recommendation."""
        if self.methods is not None:
            return list(self.methods)
        desc = descriptors or self.descriptors()
        return gl.methods_for(self.agency or "recommended", desc, **self.data_flags())

    def chosen_return_periods(self):
        """Explicit return periods, else the structure's, else the ToR set."""
        if self.return_periods is not None:
            return list(self.return_periods)
        if self.structure:
            return gl.return_periods_for(self.structure)
        return list(TOR_RETURN_PERIODS)

    def physics_return_periods(self, T):
        """Return periods for the physics runs (a subset of the table's)."""
        chosen = self.physics.get("return_periods")
        if chosen:
            return [float(t) for t in np.atleast_1d(chosen)]
        if self.structure:
            design = [float(t) for t in gl.STRUCTURES[self.structure].design]
            return [t for t in design if any(np.isclose(t, T))] or design
        return [100.0] if any(np.isclose(100.0, T)) else [float(max(T))]

    # ── Running ──────────────────────────────────────────────────────────────
    def run(self, physics=None, save=True, log=print):
        """
        Measure, estimate, simulate and report.

        physics  True/False to force the physics run on or off; None (default)
                 follows ``self.physics['enabled']`` when set, else runs it when
                 'physics' is among the methods.
        save     write the CSV, chart and report to ``self.folder`` (if any).
        log      receives progress lines (default print).
        """
        log = log or (lambda _s: None)
        desc = self.descriptors(log)
        methods = self.chosen_methods(desc)
        want = physics if physics is not None else self.physics.get("enabled")
        if want is True and "physics" not in methods:
            methods = resolve_methods(methods + ["physics"])
        T = self.chosen_return_periods()
        est = estimate_floods(desc, methods, T, **{k: v for k, v in self.inputs.items()
                                                   if v is not None})
        floods = {}
        if "physics" in methods and want is not False:
            floods = self._run_physics(desc, est, log)
        recommendation = gl.recommend_methods(desc, **self.data_flags())[1]
        result = NepalResult(
            descriptors=desc, estimates=est, physics=floods, methods=methods,
            agency=gl.AGENCIES.get(self.agency) if self.agency else None,
            structure=gl.STRUCTURES.get(self.structure) if self.structure else None,
            recommendation=recommendation, observed=self.observed_floods)
        if save and self.folder:
            result.save(self.folder)
        return result

    def _run_physics(self, desc, est, log):
        from .physics import nepal_design_config, run_design_floods
        name = FLOOD_METHODS["physics"].name
        if self.site_kind == "numbers":
            est.add_result("physics", name, {}, status="needs input",
                           notes=["needs a DEM — choose a DEM file, a results folder or a "
                                  "config file as the site"])
            return {}
        Tp = self.physics_return_periods(est.T)
        try:
            r24, _flags, rain_notes, _fit = design_rainfall(self.inputs, Tp)
        except ValueError as exc:
            est.add_result("physics", name, {}, status="needs input", notes=[str(exc)])
            return {}
        rain = {t: float(r) for t, r in zip(Tp, r24) if np.isfinite(r)}
        skipped = [fq._tkey(t) for t, r in zip(Tp, r24) if not np.isfinite(r)]
        if not rain:
            est.add_result("physics", name, {}, status="needs input",
                           notes=[f"no 24-hour design rainfall for T = {skipped} years"])
            return {}
        p = self.physics
        site_cfg = self.model_config()
        if self.site_kind == "config":
            cfg = site_cfg
        elif p.get("model_config"):
            from ..config import Config
            src = p["model_config"]
            cfg = copy.deepcopy(src) if hasattr(src, "OUTPUT_DIR") else Config.from_file(src)
            cfg.OUTPUT_DIR = site_cfg.OUTPUT_DIR
            cfg.update_output_paths()
        else:
            cfg = nepal_design_config(site_cfg, curve_number=p["curve_number"], snow_ramp=None)
        ramp = (3000.0, 5000.0) if p.get("snow_ramp") else None
        try:
            floods = run_design_floods(
                cfg, rain, duration_h=p["duration_h"], step_min=p["step_min"],
                pattern=p["pattern"], areal_reduction=p["areal_reduction"],
                climate_factor=p["climate_factor"], snow_ramp=ramp,
                sim_hours=p.get("sim_hours"), descriptors=desc, log=log)
        except (ValueError, FileNotFoundError) as exc:
            est.add_result("physics", name, {}, status="needs input", notes=[str(exc)])
            return {}
        shape = {"center": "centre-peaked"}.get(p["pattern"], p["pattern"])
        notes = [f"{_model_text(cfg)}; {shape} {p['duration_h']:g}-h storm"] + rain_notes
        if p["areal_reduction"] != 1.0 or p["climate_factor"] != 1.0:
            notes.append(f"R24 × {p['areal_reduction']:g} (areal) × {p['climate_factor']:g} "
                         "(climate)")
        if ramp and cfg.RAIN_SNOW_ELEV_LOW is None:
            notes.append("rain share ramps 1 → 0 between 3,000 m and 5,000 m")
        if skipped:
            notes.append(f"not run for T = {skipped} years (no design rainfall)")
        est.add_result("physics", name, {t: f.peak_m3s for t, f in floods.items()},
                       status="ok", notes=notes)
        return floods

    # ── Saving ───────────────────────────────────────────────────────────────
    def to_dict(self):
        """The study as plain values (for YAML)."""
        site = dict(self.site)
        if "config" in site and hasattr(site["config"], "OUTPUT_DIR"):
            raise ValueError("A study built on a Config object cannot be saved; build it on "
                             "the config file instead.")
        physics = {k: v for k, v in self.physics.items()
                   if k == "enabled" or v != PHYSICS_DEFAULTS.get(k)}
        out = {"site": site, "name": self.name, "agency": self.agency, "structure": self.structure,
               "methods": self.methods, "return_periods": [fq._tkey(t) for t in self.return_periods]
               if self.return_periods else None, "inputs": _plain(self.inputs),
               "physics": _plain(physics), "output_dir": self.output_dir,
               "observed_floods": [list(x) for x in self.observed_floods] or None}
        return {k: v for k, v in out.items() if v not in (None, "", {}, [])}

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        unknown = sorted(set(data) - {"site", "name", "agency", "structure", "methods",
                                      "return_periods", "inputs", "physics", "output_dir",
                                      "observed_floods"})
        if unknown:
            raise ValueError(f"Unknown study key(s): {', '.join(unknown)}.")
        if "site" not in data:
            raise ValueError("A study needs a 'site' (numbers, results, config or dem).")
        site = data.pop("site")
        return cls(site, **data)

    def save(self, path):
        """Write the study to a YAML file."""
        import yaml
        path = os.fspath(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# MRRpy-Nepal study — run it with:  MRRpy nepal estimate --study "
                    f"{os.path.basename(path)}\n")
            yaml.safe_dump(self.to_dict(), f, sort_keys=False, allow_unicode=True)
        return path

    @classmethod
    def load(cls, path):
        """Read a study from a YAML file."""
        import yaml
        with open(os.fspath(path), encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f) or {})

    def __repr__(self):
        return f"NepalStudy({self.site_kind}, agency={self.agency!r}, structure={self.structure!r})"


def _check_site(site):
    if isinstance(site, CatchmentDescriptors):
        return {"numbers": {k: v for k, v in site.to_dict().items() if v not in (None, "")}}
    if not isinstance(site, dict):
        raise ValueError("The site must be a dict: {'numbers': {...}}, {'results': folder}, "
                         "{'config': file}, or {'dem': file, 'outlet': [lat, lon]}.")
    kinds = [k for k in SITE_KINDS if k in site]
    if len(kinds) != 1:
        raise ValueError(f"The site needs exactly one of {', '.join(SITE_KINDS)} (got {sorted(site)}).")
    if kinds[0] == "dem" and "outlet" not in site:
        raise ValueError("A DEM site also needs its outlet: {'dem': file, 'outlet': [lat, lon]}.")
    if kinds[0] == "numbers" and "area_km2" not in dict(site["numbers"]):
        raise ValueError("Typed catchment numbers need at least area_km2.")
    extra = set(site) - {kinds[0], "outlet", "folder"}
    if extra:
        raise ValueError(f"Unknown site key(s): {', '.join(sorted(extra))}.")
    return dict(site)


def _plain(v):
    """*v* as YAML-safe builtins; whole-number keys (return periods) become ints."""
    if isinstance(v, dict):
        return {_plain_key(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_plain(x) for x in list(v)]
    if isinstance(v, (np.generic,)):
        return v.item()
    return v


def _plain_key(k):
    if isinstance(k, np.generic):
        k = k.item()
    if isinstance(k, float) and k.is_integer():
        return int(k)
    return k


def _model_text(cfg):
    src = str(getattr(cfg, "RUNOFF_SOURCE", "none"))
    if src == "scs_cn":
        how = (f"SCS curve number {getattr(cfg, 'RUNOFF_CN', 75):g}"
               if getattr(cfg, "RUNOFF_CN_SOURCE", "") == "scalar" else
               f"SCS curve numbers from {getattr(cfg, 'RUNOFF_CN_SOURCE', '')}")
    elif src == "physical":
        how = "physical runoff (" + ", ".join(getattr(cfg, "RUNOFF_MECHANISMS", [])) + ")"
    else:
        how = f"runoff '{src}'"
    return f"{how}, {getattr(cfg, 'ROUTING_SCHEME', 'kinematic')} routing"


class NepalResult:
    """
    The outcome of ``NepalStudy.run()``.

    table / envelope   the comparison table and the official range (DataFrames)
    estimates          the FloodEstimates object behind them
    physics            {T: DesignFlood} of the physics runs
    recommendation     the compendium's quick guide for this catchment
    files              what ``save`` wrote
    """

    def __init__(self, descriptors, estimates, physics, methods, agency, structure,
                 recommendation, observed=()):
        self.descriptors = descriptors
        self.estimates = estimates
        self.physics = dict(physics)
        self.methods = list(methods)
        self.agency = agency
        self.structure = structure
        self.recommendation = list(recommendation)
        self.observed = list(observed)
        self.files = {}

    @property
    def table(self):
        return self.estimates.table

    @property
    def envelope(self):
        return self.estimates.envelope

    def warnings(self):
        return self.estimates.warnings()

    def plot(self, ax=None, theme="light"):
        """Flood against return period for every method; returns (fig, ax)."""
        from .report import plot_estimates
        return plot_estimates(self.estimates, ax=ax, observed=self.observed, theme=theme)

    def report(self):
        """The whole result as Markdown."""
        from .report import report_markdown
        return report_markdown(self)

    def save(self, folder):
        """Write nepal_flood_estimates.csv / .md / .png and catchment.csv to *folder*."""
        os.makedirs(folder, exist_ok=True)
        files = {"table": os.path.join(folder, "nepal_flood_estimates.csv"),
                 "catchment": os.path.join(folder, "catchment.csv"),
                 "chart": os.path.join(folder, "nepal_flood_estimates.png"),
                 "report": os.path.join(folder, "nepal_report.md")}
        self.estimates.to_csv(files["table"])
        self.descriptors.table().to_csv(files["catchment"], index=False)
        try:
            from matplotlib.figure import Figure     # no pyplot: works headless and in QGIS
            fig = Figure(figsize=(8.0, 4.8), dpi=110)
            self.plot(ax=fig.subplots())
            fig.savefig(files["chart"], dpi=150, facecolor=fig.get_facecolor())
        except Exception as exc:          # noqa: BLE001 — a chart must never sink the table
            files.pop("chart")
            print(f"  [WARN] chart not saved: {exc}")
        self.files = files
        with open(files["report"], "w", encoding="utf-8") as f:
            f.write(self.report())
        return files

    def summary_lines(self):
        """A few lines for a terminal: the range and the physics result per T."""
        lines = [self.descriptors.summary()]
        env = self.envelope
        for t, e in env.iterrows():
            if e["n_methods"]:
                lines.append(f"  {t:>5} years: official {_g(e['min'])}–{_g(e['max'])} m³/s "
                             f"(median {_g(e['median'])}, {int(e['n_methods'])} methods)")
        for T, f in sorted(self.physics.items()):
            lines.append("  physics: " + f.summary())
        return lines

    def _repr_html_(self):
        return self.estimates._repr_html_()

    def __repr__(self):
        return f"NepalResult({len(self.estimates.rows)} methods, physics T={sorted(self.physics)})"


def _g(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    return "–" if not np.isfinite(v) else f"{v:.4g}"
