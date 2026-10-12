# -*- coding: utf-8 -*-
"""
design_storm.py
===============
Design rainfall for the physics model, built the way Nepali practice builds
it (compendium §3.8): the T-year 24-hour rainfall R24 from DHM data, spread
in time with the Mononobe curve — the same intensity–duration rule the
official Rational method uses:

    I(t) = (R24/24)·(24/t)^(2/3)      so the depth in t hours is
    D(t) = R24·(t/24)^(1/3)

``design_hyetograph`` turns the curve into a storm with the alternating
block method: the largest block in the middle, the next largest on
alternate sides.  Every duration inside the storm then carries its Mononobe
depth, so one storm serves catchments of any response time.
``write_storm_files`` saves it as the one-gauge CSV pair MRRpy already reads
with PRECIP_METHOD='thiessen' — the physics model needs no new rain option.

Factors applied to R24 before the time pattern (``design_depth``):

areal_reduction  point → catchment-average rainfall (1 = none)
climate_factor   e.g. 1.10 for +10 % (the ToR's climate delta factors)
"""

import os

import numpy as np
import pandas as pd

#: Time patterns offered by the interfaces.
PATTERNS = {
    "center": "Centre-peaked — alternating blocks from the Mononobe curve",
    "uniform": "Uniform — the same intensity for the whole storm",
}


def mononobe_depth(r24_mm, duration_h):
    """Rain depth [mm] in the most intense *duration_h* hours: R24·(t/24)^(1/3)."""
    return float(r24_mm) * (np.asarray(duration_h, dtype=float) / 24.0) ** (1.0 / 3.0)


def design_depth(r24_mm, areal_reduction=1.0, climate_factor=1.0):
    """The 24-hour depth the storm is built from: R24 × areal reduction × climate factor."""
    r24, arf, cf = float(r24_mm), float(areal_reduction), float(climate_factor)
    if not r24 > 0:
        raise ValueError(f"The 24-hour design rainfall must be above 0 mm (got {r24_mm!r}).")
    if not 0 < arf <= 1:
        raise ValueError(f"The areal reduction factor must be in (0, 1] (got {areal_reduction!r}).")
    if not cf > 0:
        raise ValueError(f"The climate factor must be above 0 (got {climate_factor!r}).")
    return r24 * arf * cf


def design_hyetograph(r24_mm, duration_h=24.0, step_min=15.0, pattern="center",
                      peak_fraction=0.5):
    """
    A design storm as a table of blocks: start_h, end_h, rain_mm, intensity_mm_h.

    r24_mm         the (factored) 24-hour design rainfall.
    duration_h     storm length; the total depth is the Mononobe depth for it
                   (R24 itself for 24 h).
    step_min       block length in minutes; must divide the duration.
    pattern        'center' (alternating blocks) or 'uniform'.
    peak_fraction  where the peak block sits, 0 (start) … 1 (end); 0.5 = middle.
    """
    if pattern not in PATTERNS:
        raise ValueError(f"Storm pattern must be one of {', '.join(PATTERNS)} (got {pattern!r}).")
    duration_h, step_min = float(duration_h), float(step_min)
    if not duration_h > 0 or not step_min > 0:
        raise ValueError("The storm duration and the time step must be above 0.")
    n = int(round(duration_h * 60.0 / step_min))
    if n < 1 or abs(n * step_min - duration_h * 60.0) > 1e-6:
        raise ValueError(f"The time step ({step_min:g} min) must divide the storm duration "
                         f"({duration_h:g} h).")
    if not 0.0 <= float(peak_fraction) <= 1.0:
        raise ValueError("peak_fraction must be between 0 and 1.")
    dt_h = step_min / 60.0
    if pattern == "uniform":
        depths = np.full(n, float(mononobe_depth(r24_mm, duration_h)) / n)
    else:
        cum = mononobe_depth(r24_mm, np.arange(1, n + 1) * dt_h)
        blocks = np.diff(np.concatenate([[0.0], cum]))     # largest first (concave curve)
        depths = np.zeros(n)
        depths[_alternating_positions(n, float(peak_fraction))] = blocks
    start = np.arange(n) * dt_h
    df = pd.DataFrame({"start_h": start, "end_h": start + dt_h, "rain_mm": depths,
                       "intensity_mm_h": depths / dt_h})
    df.attrs.update(r24_mm=float(r24_mm), duration_h=duration_h, step_min=step_min,
                    pattern=pattern, total_mm=float(depths.sum()))
    return df


def _alternating_positions(n, peak_fraction):
    """Block indices from the peak outwards: peak, right, left, right, … ."""
    peak = min(int(peak_fraction * n), n - 1)
    order, right, left, go_right = [peak], peak + 1, peak - 1, True
    while len(order) < n:
        if (go_right and right < n) or left < 0:
            order.append(right)
            right += 1
        else:
            order.append(left)
            left -= 1
        go_right = not go_right
    return np.asarray(order)


def write_storm_files(hyetograph, folder, x, y, sim_hours=None, prefix="design_storm",
                      name="design storm"):
    """
    Save the storm as MRRpy rain-gauge CSVs (one gauge at x, y in the model's
    map projection) and return (gauge_csv, rain_csv).

    MRRpy interpolates linearly between the rows of a rain file, so each
    block is written as the depth at the block's end time with a zero row
    before and after the storm: the total depth is kept exactly and the
    storm is shifted by half a block.  A last zero row at *sim_hours* keeps
    the rain file as long as the run.
    """
    os.makedirs(folder, exist_ok=True)
    gauge_csv = os.path.join(folder, f"{prefix}_gauge.csv")
    rain_csv = os.path.join(folder, f"{prefix}_rain.csv")
    pd.DataFrame({"gauge_id": ["G01"], "name": [name], "easting_m": [float(x)],
                  "northing_m": [float(y)]}).to_csv(gauge_csv, index=False)
    dt_s = float(hyetograph["end_h"].iloc[0] - hyetograph["start_h"].iloc[0]) * 3600.0
    n = len(hyetograph)
    times = np.arange(n + 2) * dt_s
    depths = np.concatenate([[0.0], hyetograph["rain_mm"].to_numpy(dtype=float), [0.0]])
    if sim_hours is not None and float(sim_hours) * 3600.0 > times[-1] + 1.0:
        times = np.append(times, float(sim_hours) * 3600.0)
        depths = np.append(depths, 0.0)
    pd.DataFrame({"time_s": times, "G01": depths}).to_csv(rain_csv, index=False)
    return gauge_csv, rain_csv


def apply_storm(cfg, gauge_csv, rain_csv, sim_hours):
    """Point *cfg* at the storm files (PRECIP_METHOD='thiessen') for *sim_hours*."""
    cfg.PRECIP_METHOD = "thiessen"
    cfg.PRECIP_GAUGE_FILE = gauge_csv
    cfg.PRECIP_TIMESERIES_FILE = rain_csv
    cfg.PRECIP_EXCLUDE_OUTSIDE_STATIONS = False
    cfg.TOTAL_SIMULATION_TIME_HOURS = float(sim_hours)
    return cfg
