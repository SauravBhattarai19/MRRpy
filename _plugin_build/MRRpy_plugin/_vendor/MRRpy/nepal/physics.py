# -*- coding: utf-8 -*-
"""
physics.py
==========
Design floods from the MRRpy physics model.  For each return period the
design storm (``design_storm``) is run through the configured runoff and
routing on the delineated DEM, and the peak, its timing, the flood volume
and the runoff ratio are read back:

    from MRRpy.nepal.physics import nepal_design_config, run_design_floods
    cfg = nepal_design_config("results/")        # SCS-CN 75, kinematic, Nepal channels
    floods = run_design_floods(cfg, {100: 250.0})
    floods[100].peak_m3s

Any MRRpy Config works (e.g. Green-Ampt with soils from Earth Engine); only
its rainfall is replaced by the design storm.  ``nepal_design_config`` is
the offline default:

* runoff: SCS curve number (one value, normal wetness — AMC II);
* channels sized by the official 2-year flood (``CHANNEL_QBF_M3S =
  'wecs_nepal'``);
* rain share ramping from 1 at 3,000 m to 0 at 5,000 m — the idea behind the
  official A3000 rule (``RAIN_SNOW_ELEV_LOW/HIGH``).

Each return period writes to ``<OUTPUT_DIR>/nepal/design_T<T>/`` (the
hyetograph, the storm CSVs, hydrograph.csv, gauges.csv when virtual gauges
are set, and maps when SAVE_FIELDS is on).  The results folder's own
hydrograph.csv and gauges.csv are left as they were.
"""

import contextlib
import copy
import os
import shutil
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from . import design_storm as ds
from .descriptors import delineated, measure_catchment
from .methods import kirpich_tc_minutes

#: Default rain/snow ramp for Nepal design storms [m]: full rain below
#: 3,000 m (the official A3000 limit), none above 5,000 m (permanent snow).
NEPAL_SNOW_RAMP = (3000.0, 5000.0)


@dataclass
class DesignFlood:
    """The physics model's flood for one return period."""

    T: float
    r24_mm: float                 # the 24-hour design rainfall given
    storm_mm: float               # total depth of the storm applied (after factors and
                                  # the Mononobe depth for the storm's duration)
    duration_h: float
    peak_m3s: float
    time_to_peak_h: float
    volume_m3: float
    runoff_ratio: Optional[float]
    folder: str
    hydrograph_csv: str
    files: dict = field(default_factory=dict)

    def summary(self):
        ratio = f", runoff ratio {self.runoff_ratio:.2f}" if self.runoff_ratio is not None else ""
        return (f"T = {_tkey(self.T)} years: {self.storm_mm:.0f} mm in {self.duration_h:g} h "
                f"(R24 {self.r24_mm:.0f} mm) → peak {self.peak_m3s:.4g} m³/s at "
                f"{self.time_to_peak_h:.1f} h, volume {self.volume_m3 / 1e6:.3g} Mm³{ratio}")


def _tkey(t):
    t = float(t)
    return int(t) if t.is_integer() else t


def nepal_design_config(results, curve_number=75.0, snow_ramp=NEPAL_SNOW_RAMP, crs=None):
    """
    An offline physics setup for design floods on a delineated catchment.

    results       the results folder of a process_dem run (or a Config).
    curve_number  SCS curve number (about 30 very permeable … 98 paved).
    snow_ramp     (low, high) elevations [m] of the rain/snow ramp, or None.
    crs           the model grid's CRS; read from clipped_dem.tif when None.
    """
    from ..config import Config
    if hasattr(results, "ROUTING_DEM_PATH"):
        cfg = copy.deepcopy(results)
    else:
        cfg = Config(OUTPUT_DIR=os.fspath(results))
        cfg.update_output_paths()
    if crs is None and os.path.isfile(cfg.ROUTING_DEM_PATH):
        import rasterio
        with rasterio.open(cfg.ROUTING_DEM_PATH) as src:
            if src.crs is not None:
                crs = src.crs.to_string()
    if crs:
        cfg.TARGET_CRS_EPSG = crs
    cfg.RUNOFF_SOURCE = "scs_cn"
    cfg.RUNOFF_CN_SOURCE = "scalar"
    cfg.RUNOFF_CN = float(curve_number)
    cfg.RUNOFF_CN_AMC = "ii"
    cfg.ROUTING_SCHEME = "kinematic"
    cfg.CHANNEL_QBF_M3S = "wecs_nepal"
    if snow_ramp:
        cfg.RAIN_SNOW_ELEV_LOW, cfg.RAIN_SNOW_ELEV_HIGH = (float(v) for v in snow_ramp)
    return cfg


def default_simulation_hours(descriptors, duration_h):
    """
    Storm length plus time for the flood to pass: four Kirpich times of
    concentration (at least 6 h, at most 120 h), or 24 h when the flow
    length is unknown.
    """
    L, S = descriptors.flow_length_km, descriptors.flow_path_slope
    if L and S and S > 0:
        tc_h = kirpich_tc_minutes(L * 1000.0, S) / 60.0
        recession = min(max(6.0, 4.0 * tc_h), 120.0)
    else:
        recession = 24.0
    return float(duration_h) + recession


def run_design_floods(cfg, rain_24h, return_periods=None, *, duration_h=24.0, step_min=15.0,
                      pattern="center", areal_reduction=1.0, climate_factor=1.0,
                      snow_ramp=NEPAL_SNOW_RAMP, sim_hours=None, descriptors=None, log=print):
    """
    Run the physics model once per return period with a design storm.

    cfg              an MRRpy Config whose OUTPUT_DIR holds a delineated
                     catchment (process_dem already run).
    rain_24h         {T: R24 in mm}.
    return_periods   which of them to run (default: all in rain_24h).
    duration_h, step_min, pattern   the storm (see design_storm.design_hyetograph).
    areal_reduction, climate_factor factors on R24 (see design_storm.design_depth).
    snow_ramp        (low, high) rain/snow ramp used when cfg has none; None = off.
    sim_hours        run length (default: storm + four Kirpich t_c, see
                     default_simulation_hours).
    descriptors      the measured catchment (measured here when None).
    log              receives one line per run.

    Returns {T: DesignFlood}.
    """
    from ..pipeline import stage_routing

    base = os.path.abspath(cfg.OUTPUT_DIR or "output")
    work = copy.deepcopy(cfg)
    work.OUTPUT_DIR = base
    work.update_output_paths()
    if not delineated(work):
        raise FileNotFoundError(f"No delineated catchment in {base}: run the process_dem stage "
                                "first (or use NepalStudy, which does it for a DEM site).")
    rain = {float(k): float(v) for k, v in dict(rain_24h).items()}
    wanted = sorted(rain) if return_periods is None else [float(t) for t in return_periods]
    missing = [_tkey(t) for t in wanted if t not in rain]
    if missing:
        raise ValueError(f"No 24-hour design rainfall for T = {missing} years.")
    desc = descriptors if descriptors is not None else measure_catchment(work)
    if desc.outlet_xy is None:
        desc = measure_catchment(work)
    x, y = desc.outlet_xy
    hours = float(sim_hours) if sim_hours else default_simulation_hours(desc, duration_h)
    nepal_dir = os.path.join(base, "nepal")
    os.makedirs(nepal_dir, exist_ok=True)

    out = {}
    for T in wanted:
        folder = os.path.join(nepal_dir, f"design_T{_tkey(T)}")
        depth = ds.design_depth(rain[T], areal_reduction, climate_factor)
        hyeto = ds.design_hyetograph(depth, duration_h, step_min, pattern)
        hyeto_csv = os.path.join(folder, "hyetograph.csv")
        gauge_csv, rain_csv = ds.write_storm_files(hyeto, folder, x, y, sim_hours=hours,
                                                   name=f"{_tkey(T)}-year design storm")
        hyeto.to_csv(hyeto_csv, index=False)

        run = copy.deepcopy(work)
        ds.apply_storm(run, gauge_csv, rain_csv, hours)
        if snow_ramp and run.RAIN_SNOW_ELEV_LOW is None and run.RAIN_SNOW_ELEV_HIGH is None:
            run.RAIN_SNOW_ELEV_LOW, run.RAIN_SNOW_ELEV_HIGH = (float(v) for v in snow_ramp)
        run.HYDROGRAPH_CSV = os.path.join(folder, "hydrograph.csv")
        run.MASS_BALANCE_CSV = os.path.join(nepal_dir, "mass_balance_design.csv")
        if getattr(run, "SAVE_FIELDS", False):
            run.FIELD_OUTPUT_DIR = os.path.join(folder, "fields")

        storm_mm = float(hyeto["rain_mm"].sum())
        log(f"  Design storm T = {_tkey(T)} years: {storm_mm:.1f} mm in {duration_h:g} h "
            f"({pattern}), running {hours:.1f} h …")
        files = {"hyetograph": hyeto_csv, "gauge_csv": gauge_csv, "rain_csv": rain_csv}
        with _set_aside(os.path.join(base, "gauges.csv"),
                        os.path.join(folder, "gauges.csv")) as gauges:
            stage_routing(run, log=log)
        if gauges.moved:
            files["gauges_csv"] = gauges.dest
        flood = _read_flood(T, rain[T], storm_mm, duration_h, folder, run)
        flood.files.update(files)
        log("  " + flood.summary())
        out[T] = flood
    return out


def _read_flood(T, r24, storm_mm, duration_h, folder, run):
    df = pd.read_csv(run.HYDROGRAPH_CSV)
    i = int(df["Q_m3s"].idxmax())
    trapezoid = getattr(np, "trapezoid", None) or np.trapz
    volume = float(trapezoid(df["Q_m3s"].to_numpy(), df["time_s"].to_numpy()))
    ratio = None
    try:
        mb = pd.read_csv(run.MASS_BALANCE_CSV)
        ratio = float(mb["runoff_ratio"].iloc[-1])
    except (OSError, KeyError, ValueError, IndexError):
        pass
    return DesignFlood(T=T, r24_mm=r24, storm_mm=storm_mm, duration_h=float(duration_h),
                       peak_m3s=float(df["Q_m3s"].iloc[i]),
                       time_to_peak_h=float(df["time_hr"].iloc[i]), volume_m3=volume,
                       runoff_ratio=ratio, folder=folder, hydrograph_csv=run.HYDROGRAPH_CSV)


class _Moved:
    def __init__(self, dest):
        self.dest, self.moved = dest, False


@contextlib.contextmanager
def _set_aside(path, dest):
    """
    Keep an existing *path* safe during a run: it is moved aside first and
    put back afterwards; a file the run writes at *path* is moved to *dest*.
    """
    backup = path + ".nepal-keep"
    had = os.path.isfile(path)
    if had:
        shutil.move(path, backup)
    state = _Moved(dest)
    try:
        yield state
    finally:
        if os.path.isfile(path):
            shutil.move(path, dest)
            state.moved = True
        if had:
            shutil.move(backup, path)
