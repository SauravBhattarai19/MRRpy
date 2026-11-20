# -*- coding: utf-8 -*-
"""
pipeline.py
===========
Pure-Python orchestration of the VSA-OPM pipeline stages — no QGIS, no Qt.

Every interface (Python API, CLI, QGIS plugin worker) drives the model
through :func:`run_pipeline`.  Interface-specific concerns (threads, signals,
stdout capture) stay in the caller.

Stages (in order):
    'process_dem'  – DEM preprocessing (core.dem_processing.main)
    'routing'      – kinematic/diffusive-wave routing
                     (initialise_grid → run_time_loop → save_hydrograph)
    'vsa_opm'      – standalone OPM run (core.opm.run_opm)
    'inundation'   – flood depth / extent maps from a routed run's discharge
                     (HAND; core.inundation.make_flood_maps).  Runs at the end
                     of 'routing' when INUNDATION_MAP is on; on its own it
                     redraws the maps without routing again.
"""

import json
import os
import platform
import sys
import time
from datetime import datetime, timezone

from .utils.runlog import RunCancelled, capture, check_cancelled

DEFAULT_STAGES = ("process_dem", "routing")

#: (progress base, progress span) per stage, matching the historical plugin UI.
_STAGE_PROGRESS = {
    "process_dem": (0, 30),
    "routing": (30, 65),
    "vsa_opm": (30, 65),
    "inundation": (95, 5),
}

#: Raised inside a run when the caller's is_cancelled() returns True.
PipelineCancelled = RunCancelled


class RunResult(dict):
    """
    What :func:`run_pipeline` returns: the dict of output paths and tables it
    always was (``out["hydrograph_csv"]``, ``plot_hydrograph(out)`` still work),
    plus a few shortcuts::

        out = run_pipeline(cfg)
        out.hydrograph        # the outlet hydrograph as a DataFrame
        out.peak_m3s          # its peak, and out.peak_time_hr
        print(out.summary())  # peak, water balance, where the files are
        out.plot()            # the hydrograph figure
    """

    cancelled = False       #: the run was stopped early by is_cancelled()
    output_dir = None       #: the results folder (absolute)
    info = None             #: the run record also saved as run_info.json

    @property
    def hydrograph(self):
        """The outlet hydrograph (DataFrame), or None when routing did not run."""
        df = self.get("hydrograph_df")
        if df is None and self.get("hydrograph_csv") and os.path.exists(self["hydrograph_csv"]):
            import pandas as pd
            df = pd.read_csv(self["hydrograph_csv"])
        return df

    @property
    def peak_m3s(self):
        df = self.hydrograph
        return None if df is None or not len(df) else float(df["Q_m3s"].max())

    @property
    def peak_time_hr(self):
        df = self.hydrograph
        return None if df is None or not len(df) else float(df["time_hr"][df["Q_m3s"].idxmax()])

    def summary(self):
        """A few plain lines: what ran, the peak, the water balance, the files."""
        info = self.info or {}
        lines = []
        state = "stopped early (cancelled)" if self.cancelled else "finished"
        took = info.get("wall_seconds")
        lines.append(f"Run {state}" + (f" in {took:.0f} s" if took is not None else "")
                     + f": {', '.join(info.get('stages', [])) or 'no stages'}")
        if self.peak_m3s is not None:
            lines.append(f"Peak flow at the outlet: {self.peak_m3s:.2f} m³/s, "
                         f"{self.peak_time_hr:.2f} h after the start")
        err = info.get("mass_balance_rel_error")
        if err is not None:
            ok = "water balance closes" if abs(err) < 1e-6 else "CHECK the water balance"
            lines.append(f"Water balance error: {100 * err:.2e} % of the input ({ok})")
        if self.output_dir:
            lines.append(f"Results folder: {self.output_dir}")
        return "\n".join(lines)

    def plot(self, **kwargs):
        """The outlet hydrograph figure (``MRRpy.plot_hydrograph``) → (fig, ax)."""
        from .plotting import plot_hydrograph
        return plot_hydrograph(self, **kwargs)

    def __repr__(self):
        return "RunResult(" + self.summary().replace("\n", "; ") + ")"


def prepare_output_dir(cfg, log=print):
    """
    Resolve cfg.OUTPUT_DIR to an ABSOLUTE path and pre-create it, so relative
    defaults are never created under a read-only working directory (e.g. QGIS
    launched from C:\\Program Files).  The paths that follow OUTPUT_DIR move
    with it; a path given a value of its own (e.g. a PRECIP_IMERG_DIR shared by
    many runs) is kept.
    """
    try:
        cfg.OUTPUT_DIR = os.path.abspath(cfg.OUTPUT_DIR or "output")
        if hasattr(cfg, "update_output_paths"):
            cfg.update_output_paths()
        os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
        log(f"[INFO] Output directory: {cfg.OUTPUT_DIR}")
    except OSError as exc:
        raise RuntimeError(
            f"Cannot create the output directory '{cfg.OUTPUT_DIR}'. "
            "Pick a writable folder (e.g. under your user/Documents folder)."
        ) from exc


# ── Run record ─────────────────────────────────────────────────────────────────

def _write_run_config(cfg, log=print):
    """Save the settings of this run as {OUTPUT_DIR}/run_config.yaml (re-runnable)."""
    from .config import Config
    if not isinstance(cfg, Config):
        return None                       # a legacy settings module: nothing to render
    try:
        from . import __version__
        from .interactive.render import save_yaml
        return save_yaml(cfg, os.path.join(cfg.OUTPUT_DIR, "run_config.yaml"), full=False,
                         title=f"MRRpy {__version__} — the settings of the run in this folder",
                         source="MRRpy run")
    except Exception as exc:              # noqa: BLE001 — a record must never stop a run
        log(f"  [NOTE] Could not save run_config.yaml ({exc}).")
        return None


def _write_run_info(cfg, result, stages, started, t0, status, error=None):
    """Save {OUTPUT_DIR}/run_info.json: version, times, status, peak, balance."""
    from . import __version__
    info = {
        "mrrpy_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "wall_seconds": round(time.time() - t0, 2),
        "stages": list(stages),
        "status": status,
        "backend": str(getattr(cfg, "BACKEND", "cpu")),
        "routing_scheme": str(getattr(cfg, "ROUTING_SCHEME", "")),
    }
    if error:
        info["error"] = error
    try:
        if result.peak_m3s is not None:
            info["peak_m3s"] = result.peak_m3s
            info["peak_time_hr"] = result.peak_time_hr
        mb = result.get("mass_balance_csv")
        if "hydrograph_csv" in result and mb and os.path.exists(mb):
            import pandas as pd
            row = pd.read_csv(mb).iloc[-1]
            info["mass_balance_rel_error"] = float(row["rel_error"])
            info["runoff_ratio"] = float(row["runoff_ratio"])
        info["outputs"] = {k: v for k, v in result.items() if isinstance(v, str)}
        with open(os.path.join(cfg.OUTPUT_DIR, "run_info.json"), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
    except Exception:                     # noqa: BLE001 — a record must never stop a run
        pass
    return info


# ── Individual stages ──────────────────────────────────────────────────────────

def stage_process_dem(cfg, log=print):
    """Run DEM preprocessing.  Returns a dict of generated file paths.

    If cfg.DEM_PATH is empty and cfg.DEM_BOUNDS_WGS84 is set, first downloads
    a DEM from Google Earth Engine (dataset = cfg.DEM_SOURCE) covering those
    bounds and points cfg.DEM_PATH at it, so MRRpy/core/ stays GEE-free —
    all Earth Engine access happens here in the orchestration layer.
    """
    from .core import dem_processing
    from .utils.crs import resolve_target_crs

    resolve_target_crs(cfg, log=log)          # "auto" → the outlet's UTM zone

    if not cfg.DEM_PATH and getattr(cfg, "DEM_BOUNDS_WGS84", None):
        from .gee.dem_catalog import needs_earth_engine
        from .utils.open_dem import fetch_dem

        source = getattr(cfg, "DEM_SOURCE", "nasadem")
        open_data = not needs_earth_engine(source)
        log(f"  Downloading DEM ({source}) "
            + ("from open data, no account needed …" if open_data
               else "from Google Earth Engine …"))
        raw_dem_path = os.path.join(
            cfg.OUTPUT_DIR, "raw_dem_open.tif" if open_data else "raw_dem_gee.tif")
        downloaded = fetch_dem(
            bbox_wgs84=cfg.DEM_BOUNDS_WGS84,
            target_crs_epsg=cfg.TARGET_CRS_EPSG,
            output_path=raw_dem_path,
            scale_m=getattr(cfg, "DEM_SCALE_M", None),
            project=getattr(cfg, "GEE_PROJECT", None),
            dataset=source,
            log=log,
        )
        if not downloaded:
            raise RuntimeError(
                "DEM auto-download from Google Earth Engine failed. Check: "
                "'pip install MRRpy[gee]' is installed; GEE "
                "authentication (GOOGLE_APPLICATION_CREDENTIALS, or run "
                "`earthengine authenticate`); GEE_PROJECT is set; and that "
                "DEM_BOUNDS_WGS84 = (min_lon, min_lat, max_lon, max_lat) is "
                "valid EPSG:4326 coordinates."
            )
        cfg.DEM_PATH = downloaded

    dem_processing.main(cfg)

    d = cfg.OUTPUT_DIR
    return {
        "watershed_tif": os.path.join(d, "watershed.tif"),
        "watershed_geojson": os.path.join(d, "watershed.geojson"),
        "clipped_dem": os.path.join(d, "clipped_dem.tif"),
        "flow_direction": os.path.join(d, "flow_direction.tif"),
        "flow_accumulation": os.path.join(d, "clipped_flow_accumulation.tif"),
    }


def stage_routing(cfg, log=print, progress=None, is_cancelled=None):
    """Run routing: initialise_grid → run_time_loop → save_hydrograph."""
    from .core.routing import router as kwr

    base, span = _STAGE_PROGRESS["routing"]
    _emit = progress or (lambda p: None)

    log("  Initialising grid …")
    _emit(base + span // 4)
    grid_data = kwr.initialise_grid(cfg)

    if is_cancelled and is_cancelled():
        raise PipelineCancelled()

    log("  Running time loop …")
    first, last = base + span // 4, base + span - 5

    def _loop_progress(fraction, _seen=[first]):
        pct = int(first + fraction * (last - first))
        if pct > _seen[0]:                    # only when the whole percent moves
            _seen[0] = pct
            _emit(pct)

    hydrograph = kwr.run_time_loop(grid_data, cfg, on_progress=_loop_progress,
                                   is_cancelled=is_cancelled)

    log("  Saving hydrograph …")
    _emit(base + span - 5)
    df = kwr.save_hydrograph(hydrograph, cfg)

    out = {
        "hydrograph_csv": cfg.HYDROGRAPH_CSV,
        "hydrograph_df": df,
        "mass_balance_csv": cfg.MASS_BALANCE_CSV,
    }
    if getattr(cfg, "SAVE_FIELDS", False):
        out["fields_dir"] = (getattr(cfg, "FIELD_OUTPUT_DIR", None)
                             or os.path.join(cfg.OUTPUT_DIR, "fields"))
    if getattr(cfg, "INUNDATION_MAP", False):
        log("  Making flood maps …")
        out.update(stage_inundation(cfg, log=log))
    return out


def stage_inundation(cfg, log=print):
    """Flood depth / extent maps from the discharge saved by a routed run."""
    from .core.inundation import make_flood_maps

    return make_flood_maps(cfg, log=log)


def stage_vsa_opm(cfg):
    """Run the standalone VSA-OPM model."""
    from .core import opm

    df = opm.run_opm(cfg)
    return {
        "vsa_opm_csv": os.path.join(cfg.OUTPUT_DIR, "vsa_opm_results.csv"),
        "vsa_opm_df": df,
    }


# ── Orchestrator ───────────────────────────────────────────────────────────────

def run_pipeline(cfg, stages=DEFAULT_STAGES, on_log=None, on_progress=None,
                 is_cancelled=None, quiet=False, log_file=True):
    """
    Run the requested pipeline *stages* with configuration *cfg*.

    Parameters
    ----------
    cfg : Config (or any object with the same attributes)
    stages : sequence of str
        Subset of ('process_dem', 'routing', 'vsa_opm', 'inundation'), run in
        the given order.
    on_log : callable(str), optional
        Receives every line the run reports, one at a time (nothing is then
        printed).  Default: the lines are printed.
    on_progress : callable(int), optional
        Receives 0–100 progress percentages, moving all through the routing.
    is_cancelled : callable() -> bool, optional
        Polled between stages and at every routing time step; returning True
        stops the run (the result then has ``cancelled = True``).
    quiet : bool
        Print only warnings and the closing lines (ignored with *on_log*).
    log_file : bool or path
        True (default) appends everything the run reports to
        ``{OUTPUT_DIR}/run.log``; a path writes there; False writes no file.

    Returns
    -------
    RunResult — a dict of the accumulated stage results (file paths +
    DataFrames) with ``.hydrograph``, ``.summary()``, ``.plot()`` and
    ``.cancelled``; partial when the run was cancelled.  The settings used are
    saved as ``run_config.yaml`` and the run record as ``run_info.json`` in
    the results folder.
    """
    emit = on_progress or (lambda p: None)
    stages = list(stages)

    unknown = [s for s in stages if s not in _STAGE_PROGRESS]
    if unknown:
        raise ValueError(f"Unknown pipeline stage(s): {unknown}")

    prepare_output_dir(cfg, log=lambda line: None)
    log_path = (os.path.join(cfg.OUTPUT_DIR, "run.log") if log_file is True
                else (str(log_file) if log_file else None))
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.time()

    result = RunResult()
    result.output_dir = cfg.OUTPUT_DIR
    n = len(stages)
    status, error = "finished", None
    with capture(on_line=on_log, log_path=log_path, quiet=quiet):
        log = print                      # inside capture(): screen, log file, on_log
        if log_path:
            log(f"[INFO] MRRpy run started {started} UTC  (log: {log_path})")
        log(f"[INFO] Output directory: {cfg.OUTPUT_DIR}")
        _write_run_config(cfg, log=log)
        try:
            for idx, stage in enumerate(stages):
                check_cancelled(is_cancelled)

                log(f"\n{'=' * 60}")
                log(f"  STAGE {idx + 1}/{n}: {stage.upper()}")
                log(f"{'=' * 60}")

                base, span = _STAGE_PROGRESS[stage]
                if stage == "process_dem":
                    emit(base + span // 3)
                    result.update(stage_process_dem(cfg, log=log))
                    emit(base + span)
                elif stage == "routing":
                    result.update(stage_routing(cfg, log=log, progress=emit,
                                                is_cancelled=is_cancelled))
                    emit(base + span)
                elif stage == "inundation":
                    emit(base + span // 2)
                    result.update(stage_inundation(cfg, log=log))
                    emit(base + span)
                elif stage == "vsa_opm":
                    emit(base + span // 2)
                    result.update(stage_vsa_opm(cfg))
                    emit(base + span)
            emit(100)
            log("\n[INFO] All stages complete.")
        except RunCancelled:
            status = "cancelled"
            result.cancelled = True
            log("[INFO] Run cancelled by user.")
        except BaseException as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"
            log(f"[ERROR] {error}")
            raise
        finally:
            # Again at the end: with what the run filled in (the projection
            # chosen for "auto", the DEM it downloaded).
            _write_run_config(cfg, log=lambda line: None)
            result.info = _write_run_info(cfg, result, stages, started, t0, status, error)
    return result
