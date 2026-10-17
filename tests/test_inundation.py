# -*- coding: utf-8 -*-
"""
tests/test_inundation.py
========================
Flood depth and extent maps (MRRpy/core/inundation):

* the network helpers on hand-built networks (exact answers);
* the rating curve equals the model's own compound channel section when the
  floodplain is only the river cells, and matches the analytic V-valley;
* full runs: the recorded peak equals the hydrograph peak for every tested
  scheme, routing is unchanged by the recorder, the 'inundation' stage
  redraws the same maps, a finer DEM and a map area work, 'auto' falls back;
  the maps lie on the DEM as it is (no channel below it);
* the 2D flood simulation (INUNDATION_METHOD: 2d): its maps, water balance,
  rivers entering a smaller area with their routed flow, the local inflow
  equal to the routed water, and the switch between methods.

Run:  pytest tests/test_inundation.py -v
"""

import json
import os

import numpy as np
import pandas as pd
import pytest
import rasterio

from MRRpy import Config, run_pipeline
from MRRpy.core.inundation import network as N
from MRRpy.core.inundation import rating as RT
from MRRpy.core.routing.hydraulics import compound_conveyance


# ── Network helpers ──────────────────────────────────────────────────────────
#    river: 0 → 1 → 2 → 3 (exit);  hillslope 4 → 1, 5 → 4, 6 → 3, 7 exits on its own
_DS = np.array([1, 2, 3, -1, 1, 4, 3, -1])
_RIVER = np.array([1, 1, 1, 1, 0, 0, 0, 0], bool)
_Z = np.array([3.0, 2.0, 1.0, 0.0, 5.0, 9.0, 4.0, 7.0])


def test_nearest_drain_and_hand_any_order():
    for order in (N.downstream_first_order(_DS), np.array([3, 7, 2, 6, 1, 0, 4, 5])):
        drain = N.nearest_drain(order, _DS, _RIVER)
        assert drain.tolist() == [0, 1, 2, 3, 1, 1, 3, -1]
        hand = N.height_above_drain(_Z, drain)
        assert hand[:7].tolist() == [0, 0, 0, 0, 3.0, 7.0, 4.0]
        assert np.isnan(hand[7])


def test_river_bed_profile_lowers_only():
    """A bridge (bump) on the river is cut down; nothing is raised; hillslopes keep z."""
    z = np.array([5.0, 4.0, 6.5, 3.0, 9.0, 9.0, 9.0, 9.0])     # cell 2 = a bridge
    bed = N.river_bed_profile(N.downstream_first_order(_DS), _DS, _RIVER, z)
    assert bed[:4].tolist() == [5.0, 4.0, 4.0, 3.0]
    assert bed[4:].tolist() == z[4:].tolist()
    assert np.all(bed <= z)


def test_downstream_first_order_puts_outlets_first():
    order = N.downstream_first_order(_DS)
    pos = np.empty(len(order), int)
    pos[order] = np.arange(len(order))
    ok = _DS >= 0
    assert np.all(pos[ok] > pos[_DS[ok]])


def _y_network():
    """Two 5-cell tributaries (0–4, 5–9) join a 12-cell main stem (10–21)."""
    ds = np.r_[np.arange(1, 5), 10, np.arange(6, 10), 10, np.arange(11, 22), -1]
    return ds, np.ones(22, bool), np.full(22, 100.0)


def test_reaches_break_at_confluences_into_equal_pieces():
    ds, river, dist = _y_network()
    order = N.downstream_first_order(ds)
    reach, length, outlet = N.segment_reaches(order, ds, river, dist, 500.0)
    assert (reach >= 0).all()
    assert len(length) == 2 + 3                       # 2 tributaries + main stem in 3
    assert sorted(length.tolist()) == [400.0, 400.0, 400.0, 500.0, 500.0]
    assert len(set(reach[:5])) == 1 and len(set(reach[5:10])) == 1
    assert reach[4] != reach[10]                      # the confluence starts a new reach
    for r in range(len(length)):                      # contiguous: the outlet is the last cell
        cells = np.flatnonzero(reach == r)
        assert outlet[r] == cells.max()


def test_accumulate_within_counts_a_meander_once():
    """A routed river outside a cut-out DEM (cells 0, 1), inside (2), outside
    again round a meander (3, 4), inside (5): the two entering cells (1 and 4)
    bring only the land outside since the river was last inside — 2 + 2, not
    2 + 5."""
    ds = np.array([1, 2, 3, 4, 5, -1])
    outside = np.array([1, 1, 0, 1, 1, 0], bool)
    acc = N.accumulate_within(N.downstream_first_order(ds), ds, np.ones(6), outside)
    assert acc[1] == 2.0 and acc[4] == 2.0
    assert N.upstream_area(N.downstream_first_order(ds), ds, 1.0)[4] == 5.0


def test_level_thresholds():
    assert N.level_thresholds(10.0, 606.0) == [10.0, 100.0]
    assert N.level_thresholds(10.0, 15.0) == [10.0]


def test_upstream_area_with_extra_inflow():
    order = N.downstream_first_order(_DS)
    extra = np.zeros(8)
    extra[0] = 5.0
    a = N.upstream_area(order, _DS, 1.0, extra)
    assert a[3] == 1 + 1 + 1 + 1 + 1 + 1 + 1 + 5      # cells 0–6 plus the extra 5 km²
    assert a[7] == 1.0


# ── Rating curves ────────────────────────────────────────────────────────────
def test_rating_equals_model_section_when_only_river_cells():
    """Catalogue = the river cells only → exactly the model's compound section."""
    ncell, dx, W, D, n_ch, n_fp, S = 10, 90.0, 35.0, 2.5, 0.035, 0.08, 0.002
    cell_reach = np.zeros(ncell, int)
    hand = np.zeros(ncell)
    a_fp = RT.floodplain_area(cell_reach, hand, np.ones(ncell, bool), np.full(ncell, W),
                              np.full(ncell, dx), dx * dx, dx, 1)
    y = RT.stage_grid(6.0)
    Q, _A = RT.rating_curves(cell_reach, hand, a_fp, np.full(ncell, n_fp), dx * dx,
                             [ncell * dx], [S], [W], [D], [n_ch], y)
    C, _ = compound_conveyance(D + y, n_ch, np.full(y.shape, W), np.ones(y.shape, bool),
                               D, dx, np, n_fp)
    np.testing.assert_allclose(Q[0], np.sqrt(S) * C, rtol=1e-9)


def test_v_valley_matches_analytic():
    """Valley with side slope m (HAND = m·|x|), no channel below the DEM:
    Q(y) = (√S/n)·(3/4)·y^(8/3)/m."""
    dx, m, n, S, half = 1.0, 0.05, 0.05, 0.001, 200
    k = np.arange(-half, half + 1)
    hand = m * np.abs(k) * dx
    cell_reach = np.zeros(k.size, int)
    a_fp = np.full(k.size, dx * dx)
    y = RT.stage_grid(3.0)
    Q, A = RT.rating_curves(cell_reach, hand, a_fp, np.full(k.size, n), dx * dx,
                            [dx], [S], [0.0], [0.0], [n], y)
    sel = y >= 0.5
    exact = np.sqrt(S) / n * 0.75 * y[sel] ** (8 / 3) / m
    np.testing.assert_allclose(Q[0][sel], exact, rtol=0.05)
    np.testing.assert_allclose(A[0][sel], 2 * y[sel] / m * dx, rtol=0.05, atol=dx)


def test_stage_from_discharge_inbank_monotone_and_clipped():
    y = RT.stage_grid(5.0)
    Q = np.vstack([10.0 + 5.0 * y ** 1.6, 1.0 + y ** 2])
    stage, clipped = RT.stage_from_discharge(Q, y, [9.0, 0.5])
    assert stage.tolist() == [0.0, 0.0] and not clipped.any()          # in-bank
    qs = np.linspace(11.0, 40.0, 30)
    st = RT.stage_from_discharge(Q, y, np.column_stack([qs, qs]))[0][:, 0]
    assert np.all(np.diff(st) > 0)
    np.testing.assert_allclose(10.0 + 5.0 * st ** 1.6, qs, rtol=2e-3)
    stage, clipped = RT.stage_from_discharge(Q, y, [1e6, 2.0])
    assert stage[0] == y[-1] and clipped.tolist() == [True, False]


# ── Full runs on a small valley ──────────────────────────────────────────────
_NR, _NC, _CELL = 60, 41, 30.0


def _valley_dem(path, factor=1):
    """A straight valley: 0.2 % down-valley, a gentle 1 % floodplain 300 m
    either side of the river, steep sides beyond.  *factor* refines the grid."""
    from rasterio.transform import from_origin
    cell = _CELL / factor
    r, c = np.mgrid[0:_NR * factor, 0:_NC * factor]
    yrow = (r + 0.5) / factor - 0.5
    xcol = (c + 0.5) / factor - 0.5
    lat = np.abs(xcol - (_NC - 1) / 2) * _CELL
    dem = (_NR - 1 - yrow) * _CELL * 0.002 + np.where(lat < 300, lat * 0.01,
                                                      3 + (lat - 300) * 0.15) + 100
    prof = dict(driver="GTiff", height=dem.shape[0], width=dem.shape[1], count=1,
                dtype="float32", crs="EPSG:32645", nodata=-9999.0,
                transform=from_origin(330000, 3060000 + _NR * _CELL, cell, cell))
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(dem.astype("float32"), 1)
    return path


def _outlet_latlon():
    from pyproj import Transformer
    x = 330000 + ((_NC - 1) / 2 + 0.5) * _CELL
    y = 3060000 + _NR * _CELL - (_NR - 2 + 0.5) * _CELL
    lon, lat = Transformer.from_crs(32645, 4326, always_xy=True).transform(x, y)
    return lat, lon


def _cfg(tmp, dem, name, **kw):
    base = dict(DEM_PATH=dem, OUTPUT_POINT=_outlet_latlon(), TARGET_CRS_EPSG="EPSG:32645",
                OUTPUT_DIR=str(tmp / name), RAIN_INTENSITY_MM_HR=60.0, RAIN_DURATION_HOURS=1.0,
                TOTAL_SIMULATION_TIME_HOURS=2.5, OUTPUT_INTERVAL_SECONDS=300,
                CHANNEL_MIN_AREA_KM2=0.3, CHANNEL_QBF_M3S=0.5, INUNDATION_MAP=True,
                INUNDATION_DEM="model_grid", INUNDATION_ANIMATION=False)
    base.update(kw)
    cfg = Config(**base)
    cfg.validate()
    return cfg


def _quiet(_msg):
    pass


@pytest.fixture(scope="module")
def valley(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("flood")
    dem = _valley_dem(str(tmp / "dem.tif"))
    cfg = _cfg(tmp, dem, "kin", INUNDATION_ANIMATION=True)
    out = run_pipeline(cfg, on_log=_quiet)
    return tmp, dem, cfg, out


def _peak_check(out, cfg):
    h = pd.read_csv(out["hydrograph_csv"])
    with np.load(os.path.join(cfg.OUTPUT_DIR, "inundation", "network.npz")) as a:
        q_out = float(a["q_peak"][-1])                 # last cell = the outlet
        assert a["q_series"].shape[0] == len(h)
        np.testing.assert_allclose(a["q_series"][:, -1], h["Q_m3s"], rtol=1e-5)
    np.testing.assert_allclose(q_out, h["Q_m3s"].max(), rtol=1e-5)


def test_outputs_written_and_flooded(valley):
    _tmp, _dem, cfg, out = valley
    for key in ("flood_depth_max", "flood_extent_max", "flood_extent_geojson",
                "flood_time_of_max_hours", "flood_first_wet_hours", "flood_duration_hours",
                "hand", "reaches_csv", "rating_curves_csv", "reaches_geojson",
                "summary_json", "flood_animation"):
        assert os.path.isfile(out[key]), key
    summ = json.load(open(out["summary_json"]))
    assert summ["flooded_km2"] > 0.05 and summ["max_depth_m"] > 0.2
    with rasterio.open(out["flood_depth_max"]) as r:
        d = r.read(1, masked=True)
    assert abs(float(d.max()) - summ["max_depth_m"]) < 1e-4
    with rasterio.open(out["flood_extent_max"]) as r:
        e = r.read(1)
    assert int((e == 1).sum()) == int(d.count())
    from PIL import Image
    assert Image.open(out["flood_animation"]).n_frames > 5


def test_peak_matches_hydrograph_kinematic(valley):
    _tmp, _dem, cfg, out = valley
    _peak_check(out, cfg)


@pytest.mark.parametrize("scheme", ["muskingum", "diffusive_implicit"])
def test_peak_matches_hydrograph_other_schemes(valley, scheme):
    tmp, dem, _cfg0, _out = valley
    cfg = _cfg(tmp, dem, scheme, ROUTING_SCHEME=scheme)
    out = run_pipeline(cfg, on_log=_quiet)
    _peak_check(out, cfg)
    assert json.load(open(out["summary_json"]))["flooded_km2"] > 0


def test_routing_unchanged_by_flood_maps(valley):
    tmp, dem, cfg_on, out_on = valley
    cfg = _cfg(tmp, dem, "off", INUNDATION_MAP=False)
    out = run_pipeline(cfg, on_log=_quiet)
    with open(out["hydrograph_csv"], "rb") as a, open(out_on["hydrograph_csv"], "rb") as b:
        assert a.read() == b.read()
    assert not os.path.exists(os.path.join(cfg.OUTPUT_DIR, "inundation"))


def test_inundation_stage_redraws_same_maps(valley):
    _tmp, _dem, cfg, out = valley
    with rasterio.open(out["flood_depth_max"]) as r:
        before = r.read(1)
    again = run_pipeline(cfg, stages=["inundation"], on_log=_quiet)
    with rasterio.open(again["flood_depth_max"]) as r:
        np.testing.assert_array_equal(r.read(1), before)


def test_more_flow_floods_more(valley):
    """Nested extents: a bigger flood covers everything a smaller one does."""
    _tmp, _dem, cfg, _out = valley
    from MRRpy.core.inundation.mapping import FloodModel, routing_flood_grid
    from MRRpy.core.inundation.snapshot import load_snapshot, snapshot_path
    arrays, meta = load_snapshot(snapshot_path(cfg))
    model = FloodModel(routing_flood_grid(arrays, meta), arrays, meta)
    lev = model.levels[0]
    prev = None
    for f in (1.0, 1.5, 2.5):
        stage = RT.stage_from_discharge(lev.Q, lev.y, lev.q_peak * f)[0]
        wet = lev.depth(stage) > 0
        if prev is not None:
            assert np.all(wet[prev])
        prev = wet


def test_backwater_level_only_adds_water(valley):
    _tmp, _dem, cfg, _out = valley
    from MRRpy.core.inundation.mapping import FloodModel, routing_flood_grid
    from MRRpy.core.inundation.snapshot import load_snapshot, snapshot_path
    arrays, meta = load_snapshot(snapshot_path(cfg))
    meta = dict(meta, a_channel_km2=0.05)            # make room for a main-stem level
    grid = routing_flood_grid(arrays, meta)
    one = FloodModel(grid, arrays, meta, backwater=False).depth_peak()[0]
    two = FloodModel(grid, arrays, meta, backwater=True)
    assert len(two.levels) >= 2
    assert np.all(two.depth_peak()[0] >= one - 1e-12)


def test_map_area_crops_outputs(valley):
    tmp, dem, _cfg0, _out = valley
    from pyproj import Transformer
    tr = Transformer.from_crs(32645, 4326, always_xy=True)
    w, s = tr.transform(330300, 3060500)
    e, n = tr.transform(330900, 3061200)
    cfg = _cfg(tmp, dem, "kin", INUNDATION_AREA=(w, s, e, n))
    out = run_pipeline(cfg, stages=["inundation"], on_log=_quiet)
    with rasterio.open(out["flood_depth_max"]) as r:
        b = r.bounds
    assert b.left >= 330300 - _CELL and b.right <= 330900 + _CELL
    assert b.bottom >= 3060500 - _CELL and b.top <= 3061200 + _CELL


def test_finer_dem_file(valley):
    """Flood maps on a 10 m copy of the valley: every river cell finds its
    routed river, and the map agrees with the 30 m one."""
    tmp, dem, cfg30, out30 = valley
    dem10 = _valley_dem(str(tmp / "dem10.tif"), factor=3)
    cfg = _cfg(tmp, dem, "kin", INUNDATION_DEM="file", INUNDATION_DEM_PATH=dem10)
    out = run_pipeline(cfg, stages=["inundation"], on_log=_quiet)
    s10 = json.load(open(out["summary_json"]))
    tr = s10["discharge_transfer"]
    assert s10["cell_size_m"] == 10.0
    assert tr["with_routed_flow"] >= 0.95 * tr["river_cells_in_area"] > 0
    assert abs(tr["area_ratio_median"] - 1.0) < 0.05
    r10 = pd.read_csv(out["reaches_csv"])
    # back to the model grid for the comparison
    run_pipeline(_cfg(tmp, dem, "kin"), stages=["inundation"], on_log=_quiet)
    s30 = json.load(open(os.path.join(cfg30.OUTPUT_DIR, "inundation", "inundation_summary.json")))
    r30 = pd.read_csv(os.path.join(cfg30.OUTPUT_DIR, "inundation", "reaches.csv"))
    assert abs(s10["flooded_km2"] - s30["flooded_km2"]) <= 0.2 * s30["flooded_km2"]
    # each fine reach carries the routed flow of the river at its drainage area
    # (the routed outlet cell also collects edge-of-DEM flow, so stop below it)
    r30 = r30[r30.level == 0].sort_values("drainage_km2")
    r10 = r10[(r10.level == 0) & (r10.drainage_km2 < r30.drainage_km2.iloc[-2])]
    expect = np.interp(r10["drainage_km2"], r30["drainage_km2"], r30["q_peak_m3s"])
    np.testing.assert_allclose(r10["q_peak_m3s"], expect, rtol=0.15)


def test_auto_choice():
    from MRRpy.core.inundation.finegrid import resolve_inundation_dem
    meta = {"cell_size": 90.0}
    local = Config(DEM_PATH="dem.tif")
    assert resolve_inundation_dem(local, meta)[0] == "model"
    gee = Config(DEM_PATH="", DEM_BOUNDS_WGS84=(85.1, 27.5, 85.6, 27.9), DEM_SOURCE="fabdem")
    kind, what, scale, _why = resolve_inundation_dem(gee, meta)
    assert (kind, what, scale) == ("download", "fabdem", 30.0)
    assert resolve_inundation_dem(gee, {"cell_size": 30.0})[0] == "model"
    gee.INUNDATION_DEM = "model_grid"
    assert resolve_inundation_dem(gee, meta)[0] == "model"


def test_auto_falls_back_to_model_grid(valley, monkeypatch):
    tmp, dem, _cfg0, _out = valley
    import MRRpy.core.inundation.finegrid as FG

    def offline(*a, **k):
        raise RuntimeError("no Earth Engine here")
    monkeypatch.setattr(FG, "_fine_dem", offline)
    monkeypatch.setattr(FG, "resolve_inundation_dem",
                        lambda cfg, meta: ("download", "fabdem", 10.0, "test"))
    logs = []
    cfg = _cfg(tmp, dem, "kin", INUNDATION_DEM="auto")
    out = run_pipeline(cfg, stages=["inundation"], on_log=logs.append)
    assert json.load(open(out["summary_json"]))["grid"].startswith("model grid")
    assert any("no Earth Engine here" in m for m in logs)


def test_bad_settings_are_reported(tmp_path):
    cfg = Config(DEM_PATH=__file__, INUNDATION_MAP=True, INUNDATION_DEM="file",
                 INUNDATION_DEM_PATH=str(tmp_path / "missing.tif"),
                 INUNDATION_AREA=(85.3, 27.7, 85.2, 27.6))
    with pytest.raises(ValueError) as exc:
        cfg.validate()
    assert "INUNDATION_DEM_PATH" in str(exc.value) and "INUNDATION_AREA" in str(exc.value)


def test_missing_snapshot_message(tmp_path):
    cfg = Config(DEM_PATH=__file__, OUTPUT_DIR=str(tmp_path), INUNDATION_MAP=True)
    with pytest.raises(FileNotFoundError, match="INUNDATION_MAP"):
        run_pipeline(cfg, stages=["inundation"], on_log=_quiet)


def test_whole_dem_mode(tmp_path):
    dem = _valley_dem(str(tmp_path / "dem.tif"))
    cfg = _cfg(tmp_path, dem, "whole", MODEL_AREA="whole_dem", OUTPUT_POINT=None)
    out = run_pipeline(cfg, on_log=_quiet)
    summ = json.load(open(out["summary_json"]))
    assert summ["flooded_km2"] > 0
    with rasterio.open(out["hand"]) as r:
        hand = r.read(1, masked=True)
    assert hand.count() > 0 and float(hand.min()) >= 0.0


# ── On the DEM as it is ──────────────────────────────────────────────────────
def test_maps_lie_on_the_dem(valley):
    """No channel below the DEM: a stage of 0 carries no flow, so every river
    reach with flow is under water at its peak, and the routed water entering
    the rivers from their side is all the water the outlet passed."""
    _tmp, _dem, cfg, out = valley
    from MRRpy.core.inundation.mapping import FloodModel, routing_flood_grid
    from MRRpy.core.inundation.snapshot import load_snapshot, snapshot_path
    arrays, meta = load_snapshot(snapshot_path(cfg))
    model = FloodModel(routing_flood_grid(arrays, meta), arrays, meta)
    for lev in model.levels:
        assert np.all(lev.Q[:, 0] == 0.0)
    depth = model.depth_peak()[0]
    flowing = model.grid.river & (arrays["q_peak"] > 1e-6)
    assert flowing.any() and np.all(depth[flowing] > 0)
    # local inflow: everything the outlet passed entered a river cell from its side
    dt = float(meta["output_interval_s"])
    v_side = float(arrays["lat_series"].sum()) * dt
    v_out = float(pd.read_csv(out["hydrograph_csv"])["Q_m3s"].sum()) * dt
    assert v_out <= v_side <= 1.2 * v_out


# ── 2D flood simulation ──────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def valley2d(valley):
    """The valley run copied, HAND maps redrawn there, then the 2D maps."""
    import shutil
    tmp, dem, cfg, _out = valley
    shutil.copytree(cfg.OUTPUT_DIR, str(tmp / "kin2d"), dirs_exist_ok=True)
    hand = run_pipeline(_cfg(tmp, dem, "kin2d"), stages=["inundation"], on_log=_quiet)
    s_hand = json.load(open(hand["summary_json"]))
    cfg2 = _cfg(tmp, dem, "kin2d", INUNDATION_METHOD="2d")
    out = run_pipeline(cfg2, stages=["inundation"], on_log=_quiet)
    return tmp, dem, cfg2, out, s_hand


def test_2d_maps_written(valley2d):
    tmp, _dem, cfg, out, s_hand = valley2d
    for key in ("flood_depth_max", "flood_extent_max", "flood_extent_geojson",
                "flood_time_of_max_hours", "flood_first_wet_hours", "flood_duration_hours",
                "flood_velocity_max", "inflows_csv", "summary_json", "flood_model"):
        assert os.path.isfile(out[key]), key
    s = json.load(open(out["summary_json"]))
    assert s["method"] == "2d"
    assert abs(s["water_balance_error"]) < 1e-9
    assert s["water_in_hm3"] > 0 and s["water_out_hm3"] > 0
    assert not s["water_against_edge"]
    # the same flows spread over the same ground: about the area HAND draws
    assert s["max_depth_m"] > 0.2
    assert 0.4 * s_hand["flooded_km2"] < s["flooded_km2"] < 2.5 * s_hand["flooded_km2"]
    for stale in ("hand.tif", "reaches.csv", "rating_curves.csv"):       # from the HAND maps
        assert not os.path.exists(os.path.join(cfg.OUTPUT_DIR, "inundation", stale))
    with rasterio.open(out["flood_depth_max"]) as r:
        d = r.read(1, masked=True)
    assert abs(float(d.max()) - s["max_depth_m"]) < 1e-4
    with rasterio.open(out["flood_velocity_max"]) as r:
        v = r.read(1, masked=True)
    assert 0 < float(v.max()) < 10.0
    from MRRpy import animate_inundation, plot_inundation
    plot_inundation(out["flood_model"], time=1.5)
    gif = animate_inundation(out["flood_model"], out_path=str(tmp / "flood2d.gif"), log=_quiet)
    from PIL import Image
    assert Image.open(gif).n_frames > 5


def test_2d_redraw_is_identical(valley2d):
    _tmp, _dem, cfg, out, _s = valley2d
    with rasterio.open(out["flood_depth_max"]) as r:
        before = r.read(1)
    again = run_pipeline(cfg, stages=["inundation"], on_log=_quiet)
    with rasterio.open(again["flood_depth_max"]) as r:
        np.testing.assert_array_equal(r.read(1), before)


def _box_lonlat(row0, row1, col0, col1):
    """(west, south, east, north) of model-grid rows/cols [row0, row1) × [col0, col1)."""
    from pyproj import Transformer
    top = 3060000 + _NR * _CELL
    tr = Transformer.from_crs(32645, 4326, always_xy=True)
    w, s = tr.transform(330000 + col0 * _CELL + 1, top - row1 * _CELL + 1)
    e, n = tr.transform(330000 + col1 * _CELL - 1, top - row0 * _CELL - 1)
    return w, s, e, n


def test_2d_area_with_a_river_flowing_in(valley2d):
    """A box across the lower valley: the river (which starts at row 16) enters
    at its top edge with the routed flow of the river cell just above it
    (scaled by the ratio of the drainage areas on the two flow-path grids), and
    leaves at the bottom edge."""
    tmp, dem, _cfg2, _out, _s = valley2d
    from pyproj import Transformer
    from MRRpy.core.inundation.snapshot import load_snapshot, snapshot_path
    cfg = _cfg(tmp, dem, "kin2d", INUNDATION_METHOD="2d", INUNDATION_AREA=_box_lonlat(25, 50, 5, 36))
    logs = []
    out = run_pipeline(cfg, stages=["inundation"], on_log=logs.append)
    s = json.load(open(out["summary_json"]))
    assert s["rivers_entering"] == 1 and s["outflow_edge_cells"] > 0
    assert abs(s["water_balance_error"]) < 1e-9 and s["water_out_hm3"] > 0
    with rasterio.open(out["flood_depth_max"]) as r:
        assert r.width <= 33 and r.height <= 27            # the box, give or take a cell
    inflows = pd.read_csv(out["inflows_csv"])
    river = inflows[inflows["kind"].str.startswith("river")].iloc[0]
    x, y = Transformer.from_crs(4326, 32645, always_xy=True).transform(river["lon"], river["lat"])
    row = int((3060000 + _NR * _CELL - y) // _CELL) - 1       # the routed cell above the entry
    col = int((x - 330000) // _CELL)
    arrays, _meta = load_snapshot(snapshot_path(cfg))
    k = np.flatnonzero((arrays["s_rows"] == row) & (arrays["s_cols"] == col))
    assert k.size == 1
    ratio = river["drainage_km2"] / float(arrays["area_km2"][k[0]])
    assert abs(ratio - 1) < 0.15
    np.testing.assert_allclose(river["peak_m3s"], float(arrays["q_peak"][k[0]]) * ratio, rtol=0.01)
    assert any("2D simulation" in m for m in logs)


def test_2d_needs_the_local_inflow(valley2d):
    """Flood-map data saved without the local inflow → a clear message."""
    import shutil
    tmp, dem, _cfg2, _out, _s = valley2d
    shutil.copytree(str(tmp / "kin2d"), str(tmp / "old"), dirs_exist_ok=True)
    path = os.path.join(str(tmp / "old"), "inundation", "network.npz")
    with np.load(path) as d:
        kept = {k: d[k] for k in d.files if k != "lat_series"}
    np.savez_compressed(path, **kept)
    cfg = _cfg(tmp, dem, "old", INUNDATION_METHOD="2d")
    with pytest.raises(RuntimeError, match="Route the run again"):
        run_pipeline(cfg, stages=["inundation"], on_log=_quiet)
    # HAND maps still work from it, and clear the 2D-only files
    out = run_pipeline(_cfg(tmp, dem, "old"), stages=["inundation"], on_log=_quiet)
    assert json.load(open(out["summary_json"]))["method"] == "hand"
    for stale in ("flood_velocity_max.tif", "inflows.csv"):
        assert not os.path.exists(os.path.join(str(tmp / "old"), "inundation", stale))


# ── A finer DEM cut out of the basin ─────────────────────────────────────────
def _dam_valley_dem(path, cell, nr=150, nc=41, cell_model=90.0):
    """A 13.5 km valley falling 0.2 % with a 15 m DEM dam across its floor at
    row 135 (of the 90 m grid), at resolution *cell*."""
    from rasterio.transform import from_origin
    f = int(round(cell_model / cell))
    r, c = np.mgrid[0:nr * f, 0:nc * f]
    yrow = (r + 0.5) / f - 0.5
    lat = np.abs((c + 0.5) / f - 0.5 - (nc - 1) / 2) * cell_model
    dem = ((nr - 1 - yrow) * cell_model * 0.002
           + np.where(lat < 300, lat * 0.01, 3 + (lat - 300) * 0.15) + 100)
    dam = (yrow > 134.5) & (yrow < 135.5)
    dem = np.where(dam, np.maximum(dem, 100 + (nr - 1 - 135) * cell_model * 0.002 + 15.0), dem)
    prof = dict(driver="GTiff", height=dem.shape[0], width=dem.shape[1], count=1,
                dtype="float32", crs="EPSG:32645", nodata=-9999.0,
                transform=from_origin(330000, 3060000 + nr * cell_model, cell, cell))
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(dem.astype("float32"), 1)
    return path


def test_cut_out_dem_drains_through_the_dam(tmp_path):
    """The finer DEM covers only the area + 3 km, so the river enters it from
    upstream; a 15 m DEM dam lies across the valley inside the area.  Water
    must still run down the valley (over the dam), not back out of the upper
    edge where the river comes in, so the river in the area carries its
    routed flow."""
    from pyproj import Transformer
    nr, nc = 150, 41
    dem = _dam_valley_dem(str(tmp_path / "dem90.tif"), 90.0)
    dem30 = _dam_valley_dem(str(tmp_path / "dem30.tif"), 30.0)
    tr = Transformer.from_crs(32645, 4326, always_xy=True)
    top = 3060000 + nr * 90.0
    w, s = tr.transform(330000 + 5 * 90.0, top - 140 * 90.0)
    e, n = tr.transform(330000 + 36 * 90.0, top - 115 * 90.0)
    cfg = _cfg(tmp_path, dem, "dam", MODEL_AREA="whole_dem", OUTPUT_POINT=None,
               CHANNEL_MIN_AREA_KM2=1.0, INUNDATION_DEM="file", INUNDATION_DEM_PATH=dem30,
               INUNDATION_AREA=(w, s, e, n), TOTAL_SIMULATION_TIME_HOURS=4.0)
    out = run_pipeline(cfg, on_log=_quiet)
    t = json.load(open(out["summary_json"]))["discharge_transfer"]
    assert t["entering_rivers"] >= 1
    assert t["with_routed_flow"] == t["river_cells_in_area"] > 0
    assert abs(t["area_ratio_median"] - 1.0) < 0.1
    cfg.INUNDATION_METHOD = "2d"
    out = run_pipeline(cfg, stages=["inundation"], on_log=_quiet)
    s2 = json.load(open(out["summary_json"]))
    assert s2["rivers_entering"] == 1 and abs(s2["water_balance_error"]) < 1e-9
    river = pd.read_csv(out["inflows_csv"]).iloc[0]
    from MRRpy.core.inundation.snapshot import load_snapshot, snapshot_path
    arrays, _meta = load_snapshot(snapshot_path(cfg))
    a_routed = float(arrays["area_km2"][arrays["river_idx"]].max())
    assert 0.5 * a_routed < river["drainage_km2"] < a_routed      # the valley above the area
