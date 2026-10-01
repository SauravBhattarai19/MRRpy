# -*- coding: utf-8 -*-
"""MODEL_AREA='whole_dem' (route every DEM cell, no outlet) and the flow-
propagation outputs built from the saved fields (plot_field, animate_fields,
export_peak_maps)."""

import os

import numpy as np
import pandas as pd
import pytest
import rasterio

import matplotlib
matplotlib.use("Agg")

from MRRpy import Config, run_pipeline
from MRRpy import config_schema as S
from MRRpy.core.routing import qbf


def _cfg(dem, out, **kw):
    base = dict(DEM_PATH=dem, TARGET_CRS_EPSG="EPSG:32645", OUTPUT_DIR=str(out),
                TOTAL_SIMULATION_TIME_HOURS=1.0, RAIN_INTENSITY_MM_HR=20.0,
                RAIN_DURATION_HOURS=0.5, OUTPUT_INTERVAL_SECONDS=300)
    base.update(kw)
    return Config(**base)


@pytest.fixture(scope="module")
def whole_run(tiny_basin, tmp_path_factory):
    """One whole-DEM run with saved fields (Earth Engine lookups stubbed out)."""
    dem, _pt = tiny_basin
    out = tmp_path_factory.mktemp("whole")
    looked_up = []
    mp = pytest.MonkeyPatch()
    mp.setattr(qbf, "_outlet_attrs", lambda cfg, point=None: looked_up.append(point))
    try:
        cfg = _cfg(dem, out, MODEL_AREA="whole_dem", OUTPUT_POINT=(0.0, 0.0),
                   SAVE_FIELDS=True)
        result = run_pipeline(cfg, on_log=lambda m: None)
    finally:
        mp.undo()
    return cfg, result, looked_up


def _mask_cells(out):
    with rasterio.open(os.path.join(out, "watershed.tif")) as src:
        return int((src.read(1) > 0).sum())


def test_whole_dem_models_every_valid_cell(whole_run, tiny_basin, tmp_path, monkeypatch):
    cfg, result, _ = whole_run
    for key in ("watershed_tif", "watershed_geojson", "clipped_dem", "flow_accumulation"):
        assert os.path.isfile(result[key]), key
    with rasterio.open(tiny_basin[0]) as src:
        n_valid = int((src.read(1) != src.nodata).sum())
    assert _mask_cells(cfg.OUTPUT_DIR) == n_valid

    # A delineated watershed of the same DEM covers fewer cells.
    monkeypatch.setattr(qbf, "_outlet_attrs", lambda cfg, point=None: None)
    ws = _cfg(tiny_basin[0], tmp_path, OUTPUT_POINT=tiny_basin[1])
    run_pipeline(ws, stages=["process_dem"], on_log=lambda m: None)
    assert _mask_cells(ws.OUTPUT_DIR) < n_valid


def test_whole_dem_mass_balance_and_total_outflow(whole_run):
    cfg, result, _ = whole_run
    mb = pd.read_csv(cfg.MASS_BALANCE_CSV).iloc[-1]
    assert abs(float(mb["rel_error"])) < 1e-9
    df = pd.read_csv(cfg.HYDROGRAPH_CSV)
    assert "Q_total_outflow_m3s" in df
    assert (df["Q_total_outflow_m3s"] >= df["Q_m3s"] - 1e-12).all()
    assert df["Q_m3s"].max() > 0


def test_watershed_hydrograph_has_no_total_column(tiny_basin, tmp_path, monkeypatch):
    monkeypatch.setattr(qbf, "_outlet_attrs", lambda cfg, point=None: None)
    cfg = _cfg(tiny_basin[0], tmp_path, OUTPUT_POINT=tiny_basin[1])
    run_pipeline(cfg, on_log=lambda m: None)
    assert list(pd.read_csv(cfg.HYDROGRAPH_CSV).columns) == ["time_s", "time_hr", "Q_m3s"]


def test_channel_size_lookup_uses_the_main_exit(whole_run, tiny_basin):
    _, _, looked_up = whole_run
    assert looked_up, "the automatic channel size should be looked up"
    lat, lon = looked_up[0]
    assert (lat, lon) != (0.0, 0.0)                       # not OUTPUT_POINT
    assert lat == pytest.approx(tiny_basin[1][0], abs=0.002)
    assert lon == pytest.approx(tiny_basin[1][1], abs=0.002)


def test_outlet_not_asked_for_whole_dem(tiny_basin):
    p = S.param("OUTPUT_POINT")
    assert S.is_visible(p, S.values_of(Config()))
    assert not S.is_visible(p, S.values_of(Config(MODEL_AREA="whole_dem")))
    assert Config(MODEL_AREA=1).MODEL_AREA == "whole_dem"
    v = S.values_of(Config(MODEL_AREA="whole_dem", DEM_PATH=tiny_basin[0]))
    epsg, why = S.suggest_crs(v)
    assert epsg == "EPSG:32645" and "centre of your DEM" in why


def test_plot_field_and_peak_maps(whole_run):
    from MRRpy import plot_field, export_peak_maps
    cfg, result, _ = whole_run
    fig, ax = plot_field(result, "depth")
    assert "peak" in ax.get_title()
    fig, ax = plot_field(cfg, "discharge", time=0.5)
    assert "0.50 h" in ax.get_title()
    # discharge is drawn as river lines, wider where more water flows
    from matplotlib.collections import LineCollection
    lc = [c for c in ax.collections if isinstance(c, LineCollection)][0]
    q, w = np.ma.getdata(lc.get_array()), np.asarray(lc.get_linewidths())
    wet = w > 0
    assert wet.sum() > 1 and w[wet][np.argmax(q[wet])] == w.max()
    fig, ax = plot_field(cfg, "discharge", lines=False)       # plain cells on request
    assert not [c for c in ax.collections if isinstance(c, LineCollection)]
    with pytest.raises(KeyError, match="volume"):
        plot_field(cfg, "volume")

    written = export_peak_maps(cfg.OUTPUT_DIR)
    assert {"max_depth", "time_of_max_depth_hours", "max_discharge"} <= set(written)
    with rasterio.open(written["max_depth"]) as m, rasterio.open(cfg.ROUTING_DEM_PATH) as d:
        assert m.crs == d.crs and m.transform == d.transform and m.shape == d.shape
        peak = m.read(1, masked=True)
    assert peak.count() == _mask_cells(cfg.OUTPUT_DIR) and float(peak.max()) > 0
    with rasterio.open(written["time_of_max_depth_hours"]) as t:
        tp = t.read(1, masked=True)
    assert 0 < float(tp.min()) and float(tp.max()) <= cfg.TOTAL_SIMULATION_TIME_HOURS + 1e-6


def test_animate_fields_writes_a_gif(whole_run, tmp_path):
    from PIL import Image
    from MRRpy import animate_fields
    cfg, result, _ = whole_run
    path = animate_fields(result, "depth", str(tmp_path / "flow.gif"), every=2, dpi=40)
    with Image.open(path) as im:
        assert im.n_frames == 6                           # 12 saved maps, every 2nd
    both = animate_fields(result, ["depth", "discharge"], every=4, dpi=40)
    assert os.path.basename(both) == "depth_discharge_animation.gif"
    with Image.open(both) as im:
        assert im.n_frames == 3


def test_missing_fields_say_how_to_get_them(tmp_path):
    from MRRpy import plot_field
    with pytest.raises(FileNotFoundError, match="SAVE_FIELDS"):
        plot_field(str(tmp_path))
