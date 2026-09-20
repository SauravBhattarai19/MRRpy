# -*- coding: utf-8 -*-
"""
tests/_surge_case.py
====================
A small synthetic *surge* case shared by ``tests/test_surge_benchmark.py`` and
``paper/make_figures.py``, so the numbers quoted in the paper are produced by
code that lives in (and is tested with) the repository.

Setup: a 120 x 21-cell (30 m) valley with a 0.2 % down-valley slope draining
into a central channel.  A GLOF-style inflow hydrograph — a 1-minute rise to a
plateau of ``q_peak`` m3/s held for 30 minutes — is injected at the head through
``ROUTING_INFLOW_BC`` (pure routing, no rainfall) and virtual gauges record
discharge 1.2, 2.1 and 3.0 km downstream.  Every scheme sees identical terrain,
forcing, roughness and channel width.

This is a *numerical behaviour* check (mass closure, boundedness, front
arrival), not a validation against observations or an analytical dam-break.
"""

import os

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from MRRpy import Config, run_pipeline

SCHEMES = ("kinematic", "diffusive", "muskingum", "dynamic")

N_ROWS, N_COLS, CELL_M = 120, 21, 30.0
BED_SLOPE = 0.002
CHANNEL_WIDTH_M = 20.0
MANNINGS_N = 0.035
GAUGE_ROWS = (40, 70, 100)            # 1.2 / 2.1 / 3.0 km below the inflow point
_EPSG = 32615


def build_valley(directory):
    """Write the synthetic DEM; return (dem_path, affine transform)."""
    dem_p = os.path.join(directory, "surge_dem.tif")
    rows, cols = np.mgrid[0:N_ROWS, 0:N_COLS]
    centre = (N_COLS - 1) / 2.0
    dem = ((N_ROWS - 1 - rows) * CELL_M * BED_SLOPE
           + np.abs(cols - centre) * CELL_M * 0.05 + 10.0).astype("float32")
    transform = from_origin(500000.0, 4000000.0 + N_ROWS * CELL_M, CELL_M, CELL_M)
    with rasterio.open(dem_p, "w", driver="GTiff", height=N_ROWS, width=N_COLS,
                       count=1, dtype="float32", crs=f"EPSG:{_EPSG}",
                       transform=transform, nodata=-9999.0) as ds:
        ds.write(dem, 1)
    return dem_p, transform


def _latlon(transform, row, col):
    x, y = transform * (col + 0.5, row + 0.5)
    lon, lat = Transformer.from_crs(_EPSG, 4326, always_xy=True).transform(x, y)
    return lat, lon


def run_surge(directory, scheme, q_peak=50.0, plateau_hr=0.5, sim_hours=3.0):
    """Run one scheme on the surge case.

    Returns ``{"gauges": DataFrame, "rel_error": float, "q_peak": float}`` where
    ``gauges`` has ``time_s`` and one ``g<row>_Q_m3s`` column per gauge.
    """
    os.makedirs(directory, exist_ok=True)
    dem_p, transform = build_valley(directory)
    centre = (N_COLS - 1) // 2

    qcsv = os.path.join(directory, "inflow.csv")
    pd.DataFrame({
        "time_hr": [0.0, 1 / 60, plateau_hr, plateau_hr + 1 / 60, sim_hours + 1.0],
        "Q_m3s":   [0.0, q_peak, q_peak, 0.0, 0.0],
    }).to_csv(qcsv, index=False)

    bc_lat, bc_lon = _latlon(transform, 3, centre)
    gauges = []
    for r in GAUGE_ROWS:
        lat, lon = _latlon(transform, r, centre)
        gauges.append({"name": f"g{r}", "lat": lat, "lon": lon,
                       "snap_to_channel": True, "snap_radius_cells": 2})

    cfg = Config(
        DEM_PATH=dem_p, OUTPUT_DIR=os.path.join(directory, f"out_{scheme}"),
        OUTPUT_POINT=_latlon(transform, N_ROWS - 2, centre),
        PRECIP_METHOD="uniform", RAIN_INTENSITY_MM_HR=0.0, RAIN_DURATION_HOURS=1.0,
        RUNOFF_SOURCE="none", TOTAL_SIMULATION_TIME_HOURS=sim_hours,
        ADAPTIVE_TIMESTEP=True, ROUTING_SCHEME=scheme,
        MANNINGS_N=MANNINGS_N,
        CHANNEL_WIDTH_BY_ORDER={i: CHANNEL_WIDTH_M for i in range(1, 9)},
        OUTPUT_INTERVAL_SECONDS=30,
        ROUTING_INFLOW_BC=[{"lat": bc_lat, "lon": bc_lon, "csv": qcsv,
                            "snap_to_channel": True}],
        ROUTING_GAUGES=gauges,
    )
    cfg.update_output_paths()
    res = run_pipeline(cfg, stages=("process_dem", "routing"),
                       on_log=lambda m: None, on_progress=lambda p: None)

    mb = pd.read_csv(res["mass_balance_csv"]).tail(1).iloc[0]
    g = pd.read_csv(os.path.join(cfg.OUTPUT_DIR, "gauges.csv"))
    return {"gauges": g, "rel_error": float(mb["rel_error"]), "q_peak": q_peak}


def front_arrival_s(time_s, q, level):
    """First time the discharge reaches ``level`` [m3/s] (NaN if it never does)."""
    idx = np.flatnonzero(np.asarray(q) >= level)
    return float(np.asarray(time_s)[idx[0]]) if idx.size else float("nan")


def gauge_metrics(result):
    """Per-gauge peak ratio (Qmax / Q_in) and 50 % front-arrival time [s]."""
    g, q_in = result["gauges"], result["q_peak"]
    out = {}
    for r in GAUGE_ROWS:
        q = g[f"g{r}_Q_m3s"].to_numpy()
        out[r] = {
            "peak_ratio": float(q.max() / q_in),
            "t50_s": front_arrival_s(g["time_s"], q, 0.5 * q_in),
        }
    return out
