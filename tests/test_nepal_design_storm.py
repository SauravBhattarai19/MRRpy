# -*- coding: utf-8 -*-
"""
tests/test_nepal_design_storm.py
================================
Design storms (MRRpy.nepal.design_storm): the Mononobe curve, the
alternating-block property (every window around the peak holds its
Mononobe depth), and the rain-gauge files — whose total depth, read back
through MRRpy's own PrecipEngine, equals the storm's.

Run:  pytest tests/test_nepal_design_storm.py -v
"""

import numpy as np
import pandas as pd
import pytest
from affine import Affine

from MRRpy import Config
from MRRpy.nepal import design_storm as ds


def test_mononobe_depth():
    assert ds.mononobe_depth(250, 24) == pytest.approx(250)
    assert ds.mononobe_depth(250, 1) == pytest.approx(250 * (1 / 24) ** (1 / 3))


def test_design_depth_factors_and_checks():
    assert ds.design_depth(200, 0.9, 1.1) == pytest.approx(198.0)
    for bad in (dict(r24_mm=0), dict(r24_mm=100, areal_reduction=1.2),
                dict(r24_mm=100, climate_factor=0)):
        with pytest.raises(ValueError):
            ds.design_depth(**bad)


def test_centre_peaked_alternating_blocks():
    h = ds.design_hyetograph(250.0, duration_h=24, step_min=60, pattern="center")
    d = h["rain_mm"].to_numpy()
    assert len(h) == 24 and d.sum() == pytest.approx(250.0)
    peak = int(np.argmax(d))
    assert peak == 12
    order = np.argsort(d)[::-1]
    for k in range(1, 25):                       # the k largest blocks: contiguous, Mononobe depth
        idx = np.sort(order[:k])
        assert idx[-1] - idx[0] == k - 1
        assert d[idx].sum() == pytest.approx(ds.mononobe_depth(250.0, k), rel=1e-9)
    assert h.attrs["total_mm"] == pytest.approx(250.0)


def test_shorter_storm_total_and_uniform_pattern():
    h = ds.design_hyetograph(250.0, duration_h=6, step_min=15)
    assert h["rain_mm"].sum() == pytest.approx(ds.mononobe_depth(250.0, 6))
    u = ds.design_hyetograph(240.0, duration_h=24, step_min=60, pattern="uniform")
    assert np.allclose(u["rain_mm"], 10.0) and np.allclose(u["intensity_mm_h"], 10.0)


def test_peak_position():
    early = ds.design_hyetograph(100.0, 6, 60, peak_fraction=0.0)["rain_mm"].to_numpy()
    assert np.argmax(early) == 0 and np.all(np.diff(early) < 0)


@pytest.mark.parametrize("kwargs", [dict(step_min=7), dict(pattern="scs"), dict(duration_h=0),
                                    dict(peak_fraction=2)])
def test_hyetograph_input_checks(kwargs):
    args = dict(r24_mm=100.0, duration_h=24, step_min=15)
    args.update(kwargs)
    with pytest.raises(ValueError):
        ds.design_hyetograph(**args)


def _integrate_through_engine(gauge_csv, rain_csv, hours):
    from MRRpy.core.precip import PrecipEngine
    cfg = Config(PRECIP_METHOD="thiessen", PRECIP_GAUGE_FILE=gauge_csv,
                 PRECIP_TIMESERIES_FILE=rain_csv, TOTAL_SIMULATION_TIME_HOURS=hours)
    grid = {"s_rows": np.array([0, 0, 1]), "s_cols": np.array([0, 1, 1]), "nrows": 2,
            "ncols": 2, "n_cells": 3, "transform": Affine(30, 0, 1000, 0, -30, 2000)}
    eng = PrecipEngine(cfg, grid)
    dt = 5.0
    t = np.arange(0.0, hours * 3600.0, dt) + dt / 2
    rates = np.array([eng.get_field_1d(x)[0] for x in t])
    return rates.sum() * dt * 1000.0                 # mm


def test_storm_files_keep_the_depth(tmp_path):
    h = ds.design_hyetograph(180.0, duration_h=3, step_min=15)
    gauge, rain = ds.write_storm_files(h, tmp_path, 1015.0, 1985.0, sim_hours=6.0)
    g = pd.read_csv(gauge)
    assert list(g.columns) == ["gauge_id", "name", "easting_m", "northing_m"]
    r = pd.read_csv(rain)
    assert r["time_s"].iloc[0] == 0 and r["time_s"].iloc[-1] == 6 * 3600
    assert r["G01"].sum() == pytest.approx(h["rain_mm"].sum())
    total = _integrate_through_engine(gauge, rain, 6.0)
    assert total == pytest.approx(h["rain_mm"].sum(), rel=2e-3)


def test_apply_storm(tmp_path):
    h = ds.design_hyetograph(100.0, 2, 30)
    gauge, rain = ds.write_storm_files(h, tmp_path, 0, 0)
    cfg = ds.apply_storm(Config(), gauge, rain, 9.0)
    assert cfg.PRECIP_METHOD == "thiessen" and cfg.TOTAL_SIMULATION_TIME_HOURS == 9.0
    assert cfg.PRECIP_GAUGE_FILE == gauge and cfg.PRECIP_TIMESERIES_FILE == rain
