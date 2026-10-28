# -*- coding: utf-8 -*-
"""
Restart files (RESTART_FROM / SAVE_STATE_AT_HOURS): a run split in two with a
saved state must give the same flow and the same end state as one continuous
run, for every routing scheme and runoff model; a state that does not fit the
model is refused with a plain message.  ('dynamic' is under development and is
not tested.)
"""

import contextlib
import io
import shutil

import numpy as np
import pandas as pd
import pytest
import rasterio

from MRRpy import Config, run_pipeline
from MRRpy.core.routing.restart import RestartError, read_meta

SPLIT_H, TOTAL_H = 12.0, 24.0

RUNOFF = {
    "none": dict(RUNOFF_SOURCE="none"),
    "scs_cn": dict(RUNOFF_SOURCE="scs_cn"),
    "all3": dict(RUNOFF_SOURCE="physical", GA_RECOVERY=True,
                 RUNOFF_MECHANISMS=["impervious", "infiltration_excess", "saturation_excess"]),
    "ga_norec": dict(RUNOFF_SOURCE="physical", GA_RECOVERY=False,
                     RUNOFF_MECHANISMS=["infiltration_excess"]),
}
# Static steps: every step is identical in both runs, so the result is exact.
STATIC = {"kinematic": 5.0, "diffusive_implicit": 60.0, "muskingum": 30.0}


@pytest.fixture(autouse=True)
def _no_land_cover_download(monkeypatch):
    """Root-zone depth without Earth Engine (the basin sits near Kathmandu)."""
    from MRRpy.core.routing import surface
    monkeypatch.setattr(surface, "resolve_lulc_field",
                        lambda cfg, grid, column, default, source:
                            np.full(len(grid["s_rows"]), 0.5))


@pytest.fixture(scope="module")
def prepared(tiny_basin, tmp_path_factory):
    """Delineate once; rain for the whole run and the same rain from the split on."""
    dem_p, outlet = tiny_basin
    d = tmp_path_factory.mktemp("restart")
    with rasterio.open(dem_p) as ds:
        prof = ds.profile
        cx, cy = ds.xy(ds.height // 2, ds.width // 2)
        cols = np.mgrid[0:ds.height, 0:ds.width][1]
    g = str(d / "gauges.csv")
    pd.DataFrame({"gauge_id": ["G1"], "name": ["G1"], "easting_m": [cx],
                  "northing_m": [cy]}).to_csv(g, index=False)
    t = np.arange(0, TOTAL_H * 3600 + 1, 900)
    storm = ((t >= 3600) & (t < 3 * 3600)) | ((t >= 11 * 3600) & (t < 14 * 3600))
    rain = pd.DataFrame({"time_s": t, "G1": np.where(storm, 12.0, 0.0)})
    full, tail = str(d / "rain_full.csv"), str(d / "rain_tail.csv")
    rain.to_csv(full, index=False)
    rain.assign(time_s=rain["time_s"] - SPLIT_H * 3600).to_csv(tail, index=False)
    prof.update(dtype="float32", nodata=-9999.0)
    imp_p = str(d / "imperv.tif")
    with rasterio.open(imp_p, "w", **prof) as ds:
        ds.write(np.where(cols > cols.max() // 2, 0.6, 0.0).astype("float32"), 1)
    base = str(d / "base")
    with contextlib.redirect_stdout(io.StringIO()):
        run_pipeline(_cfg(dem_p, outlet, base, g, full, imp_p, "kinematic", "none"),
                     stages=("process_dem",), on_log=lambda *_: None)
    return dict(dem=dem_p, outlet=outlet, base=base, gauges=g, full=full, tail=tail,
                imperv=imp_p)


def _cfg(dem_p, outlet, out, g, r, imp_p, scheme, runoff, **extra):
    kw = dict(DEM_PATH=dem_p, OUTPUT_POINT=outlet, OUTPUT_DIR=out,
              TARGET_CRS_EPSG="EPSG:32645", DELINEATION_ENGINE="pysheds",
              PRECIP_METHOD="thiessen", PRECIP_GAUGE_FILE=g, PRECIP_TIMESERIES_FILE=r,
              ROUTING_SCHEME=scheme, CFL_DT_MAX=30.0, OUTPUT_INTERVAL_SECONDS=600,
              CHANNEL_QBF_M3S=1.0, RUNOFF_CN_SOURCE="scalar", RUNOFF_CN=80.0,
              VSA_SD_SOURCE="manual", VSA_Q_MAX=0.5, GA_KSAT_MMHR=4.0,
              IMPERVIOUS_SOURCE="raster", IMPERVIOUS_RASTER_PATH=imp_p)
    kw.update(RUNOFF[runoff])
    kw.update(extra)
    return Config(**kw)


def _route(p, out, scheme, runoff, rain, hours, **extra):
    shutil.copytree(p["base"], out, dirs_exist_ok=True)
    cfg = _cfg(p["dem"], p["outlet"], str(out), p["gauges"], rain, p["imperv"],
               scheme, runoff, TOTAL_SIMULATION_TIME_HOURS=hours, **extra)
    cfg.validate()
    with contextlib.redirect_stdout(io.StringIO()):
        run_pipeline(cfg, stages=("routing",), on_log=lambda *_: None)
    return cfg


def _split_vs_continuous(p, tmp_path, scheme, runoff, **extra):
    whole = _route(p, tmp_path / "whole", scheme, runoff, p["full"], TOTAL_H,
                   SAVE_STATE_AT_HOURS=[SPLIT_H, TOTAL_H], **extra)
    s_mid = f"{whole.OUTPUT_DIR}/state/state_{SPLIT_H:08.2f}h.npz"
    second = _route(p, tmp_path / "second", scheme, runoff, p["tail"], TOTAL_H - SPLIT_H,
                    RESTART_FROM=s_mid, SAVE_STATE_AT_HOURS=[TOTAL_H - SPLIT_H], **extra)
    h_whole = pd.read_csv(whole.HYDROGRAPH_CSV)
    h_whole = h_whole[h_whole["time_s"] > SPLIT_H * 3600 + 1].reset_index(drop=True)
    h_second = pd.read_csv(second.HYDROGRAPH_CSV)
    end_whole = np.load(f"{whole.OUTPUT_DIR}/state/state_{TOTAL_H:08.2f}h.npz")
    end_second = np.load(f"{second.OUTPUT_DIR}/state/state_{TOTAL_H - SPLIT_H:08.2f}h.npz")
    mb = pd.read_csv(second.MASS_BALANCE_CSV).iloc[-1]
    return h_whole, h_second, end_whole, end_second, mb


def _arrays(z):
    return {k: z[k] for k in z.files if k != "meta"}


@pytest.mark.parametrize("runoff", list(RUNOFF))
@pytest.mark.parametrize("scheme", list(STATIC))
def test_split_run_equals_continuous_run_exactly(prepared, tmp_path, scheme, runoff):
    hw, hs, ew, es, mb = _split_vs_continuous(
        prepared, tmp_path, scheme, runoff,
        ADAPTIVE_TIMESTEP=False, TIME_STEP_SECONDS=STATIC[scheme])
    assert len(hw) == len(hs) and hw["Q_m3s"].max() > 0
    np.testing.assert_array_equal(hs["Q_m3s"].to_numpy(), hw["Q_m3s"].to_numpy())
    aw, as_ = _arrays(ew), _arrays(es)
    assert sorted(aw) == sorted(as_)
    for k in aw:
        np.testing.assert_array_equal(as_[k], aw[k], err_msg=k)
    assert abs(float(mb["rel_error"])) < 1e-6           # mass balance from the saved water


@pytest.mark.parametrize("scheme", list(STATIC))
def test_split_run_matches_with_adaptive_steps(prepared, tmp_path, scheme):
    hw, hs, ew, es, mb = _split_vs_continuous(prepared, tmp_path, scheme, "all3")
    q_w, q_s = hw["Q_m3s"].to_numpy(), hs["Q_m3s"].to_numpy()
    # Time restarts at 0, so steps clamped to output times differ by ~1e-12 s; the
    # implicit scheme's Picard iteration (IMPLICIT_TOL) then stops at a slightly
    # different iterate (3e-6 measured), the explicit schemes stay at round-off.
    rtol = 1e-4 if scheme == "diffusive_implicit" else 1e-6
    np.testing.assert_allclose(q_s, q_w, rtol=rtol, atol=1e-9 * q_w.max())
    np.testing.assert_allclose(es["routing.volume_1d"], ew["routing.volume_1d"],
                               rtol=rtol, atol=1e-6 * ew["routing.volume_1d"].max())
    assert abs(float(mb["rel_error"])) < 1e-6


def test_saving_states_does_not_change_the_run(prepared, tmp_path):
    a = _route(prepared, tmp_path / "a", "kinematic", "all3", prepared["full"], TOTAL_H)
    b = _route(prepared, tmp_path / "b", "kinematic", "all3", prepared["full"], TOTAL_H,
               SAVE_STATE_AT_HOURS=[6, 12, 18])
    pd.testing.assert_frame_equal(pd.read_csv(a.HYDROGRAPH_CSV), pd.read_csv(b.HYDROGRAPH_CSV))
    index = pd.read_csv(f"{b.OUTPUT_DIR}/state/index.csv")
    assert list(index["hours"]) == [6, 12, 18]
    meta = read_meta(f"{b.OUTPUT_DIR}/state/{index['file'][1]}")
    assert meta["hours"] == 12 and meta["scheme"] == "kinematic"


def _saved(prepared, tmp_path, scheme="kinematic", runoff="all3"):
    cfg = _route(prepared, tmp_path / "src", scheme, runoff, prepared["full"], SPLIT_H,
                 SAVE_STATE_AT_HOURS=[SPLIT_H])
    return f"{cfg.OUTPUT_DIR}/state/state_{SPLIT_H:08.2f}h.npz"


@pytest.mark.parametrize("change, words", [
    (dict(GA_KSAT_MMHR=9.0), "infiltration rate"),          # soil came out different
    (dict(ROUTING_SCHEME="muskingum"), "Muskingum"),
    (dict(GA_RECOVERY=False), "runoff settings"),
    (dict(RUNOFF_MECHANISMS=["infiltration_excess"]), "runoff settings"),
    (dict(MANNINGS_N=0.08), "roughness changed"),
])
def test_a_state_that_does_not_fit_is_refused(prepared, tmp_path, change, words):
    state = _saved(prepared, tmp_path)
    scheme = change.pop("ROUTING_SCHEME", "kinematic")
    with pytest.raises(RestartError, match=words):
        _route(prepared, tmp_path / "dst", scheme, "all3", prepared["tail"], 1.0,
               RESTART_FROM=state, **change)


def test_volume_schemes_can_swap_on_restart(prepared, tmp_path):
    state = _saved(prepared, tmp_path, scheme="kinematic")
    cfg = _route(prepared, tmp_path / "dst", "diffusive_implicit", "all3", prepared["tail"],
                 2.0, RESTART_FROM=state)
    assert pd.read_csv(cfg.HYDROGRAPH_CSV)["Q_m3s"].iloc[0] > 0    # water already flowing


def test_a_different_grid_is_refused(prepared, tmp_path, tiny_basin):
    state = _saved(prepared, tmp_path)
    from MRRpy.core.routing import restart
    meta = restart.read_meta(state)
    meta["grid"] = "0" * 40
    with np.load(state) as z:
        arrays = {k: z[k] for k in z.files}
    arrays["meta"] = np.array(__import__("json").dumps(meta))
    bad = str(tmp_path / "other_grid.npz")
    np.savez(bad, **arrays)
    with pytest.raises(RestartError, match="different grid"):
        _route(prepared, tmp_path / "dst", "kinematic", "all3", prepared["tail"], 1.0,
               RESTART_FROM=bad)


def test_config_checks(prepared, tmp_path):
    p = prepared
    base = dict(TOTAL_SIMULATION_TIME_HOURS=24.0)
    cfg = _cfg(p["dem"], p["outlet"], str(tmp_path), p["gauges"], p["full"], p["imperv"],
               "kinematic", "none", SAVE_STATE_AT_HOURS=[1.05], **base)
    with pytest.raises(ValueError, match="not an output time"):
        cfg.validate()
    cfg.SAVE_STATE_AT_HOURS = [30]
    with pytest.raises(ValueError, match="outside the run"):
        cfg.validate()
    cfg.SAVE_STATE_AT_HOURS = [12]
    cfg.ROUTING_SCHEME = "dynamic"
    with pytest.raises(ValueError, match="dynamic"):
        cfg.validate()
    cfg.ROUTING_SCHEME = "kinematic"
    cfg.RESTART_FROM = str(tmp_path / "missing.npz")
    with pytest.raises(ValueError, match="RESTART_FROM file not found"):
        cfg.validate()


def test_serves_watershed_parameters_are_kept(tmp_path, monkeypatch):
    """The SERVES SD_max/phi call is saved next to the deficit raster, so a run
    without Earth Engine (a forecast update) gets the same soil."""
    import sys
    import types
    from MRRpy.core.runoff import soil
    calls = []

    def compute(**kw):
        calls.append(kw)
        return {"sd_max": 0.123456789012, "sd_min": 0.001, "phi": 0.21, "theta_min": 0.1,
                "theta_max": 0.4, "root_depth_mean": 0.8}

    fake = types.ModuleType("MRRpy.gee.serves_gee")
    fake.compute_opm_params = compute
    fake.download_deficit_raster = lambda **kw: None
    monkeypatch.setitem(sys.modules, "MRRpy.gee.serves_gee", fake)
    (tmp_path / "watershed.geojson").write_text("{}")
    cfg = Config(OUTPUT_DIR=str(tmp_path), VSA_SD_SOURCE="gee",
                 EVENT_START_UTC="2026-10-28 00:00")
    cfg.update_output_paths()
    a = soil.resolve_sd_params(cfg, 90.0)
    b = soil.resolve_sd_params(cfg, 90.0)
    assert len(calls) == 1 and a["sd_max"] == b["sd_max"] == 0.123456789012
    cfg.SERVES_SEARCH_WINDOW = 45                      # another request: asked again
    soil.resolve_sd_params(cfg, 90.0)
    assert len(calls) == 2
