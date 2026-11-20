# -*- coding: utf-8 -*-
"""
Baseflow from soaked-in water (BASEFLOW_METHOD='store', core/runoff/slowflow.py):
the recession curve, the water budget in every scheme, restart, the settings
checks and the evaporation download (offline: the request is monkeypatched).
"""
import contextlib
import io
import shutil

import numpy as np
import pandas as pd
import pytest
import rasterio

from MRRpy import Config, run_pipeline
from MRRpy.core.runoff import slowflow

HOURS = 24.0
SCHEMES = {"kinematic": 5.0, "diffusive_implicit": 60.0, "muskingum": 30.0}


@pytest.fixture(autouse=True)
def _no_land_cover_download(monkeypatch):
    from MRRpy.core.routing import surface
    monkeypatch.setattr(surface, "resolve_lulc_field",
                        lambda cfg, grid, column, default, source:
                            np.full(len(grid["s_rows"]), 0.5))


@pytest.fixture(scope="module")
def prepared(tiny_basin, tmp_path_factory):
    dem_p, outlet = tiny_basin
    d = tmp_path_factory.mktemp("baseflow")
    with rasterio.open(dem_p) as ds:
        cx, cy = ds.xy(ds.height // 2, ds.width // 2)
    g = str(d / "gauges.csv")
    pd.DataFrame({"gauge_id": ["G1"], "name": ["G1"], "easting_m": [cx],
                  "northing_m": [cy]}).to_csv(g, index=False)
    t = np.arange(0, HOURS * 3600 + 1, 900)
    storm = ((t >= 3600) & (t < 3 * 3600)) | ((t >= 11 * 3600) & (t < 14 * 3600))
    wet, dry, tail = str(d / "wet.csv"), str(d / "dry.csv"), str(d / "tail.csv")
    rain = pd.DataFrame({"time_s": t, "G1": np.where(storm, 12.0, 0.0)})
    rain.to_csv(wet, index=False)
    rain.assign(G1=0.0).to_csv(dry, index=False)
    rain.assign(time_s=rain["time_s"] - 12 * 3600).to_csv(tail, index=False)
    base = str(d / "base")
    with contextlib.redirect_stdout(io.StringIO()):
        run_pipeline(_cfg(dem_p, outlet, base, g, wet), stages=("process_dem",),
                     on_log=lambda *_: None)
    return dict(dem=dem_p, outlet=outlet, base=base, gauges=g, wet=wet, dry=dry, tail=tail)


def _cfg(dem_p, outlet, out, g, r, **extra):
    kw = dict(DEM_PATH=dem_p, OUTPUT_POINT=outlet, OUTPUT_DIR=out,
              TARGET_CRS_EPSG="EPSG:32645", DELINEATION_ENGINE="pysheds",
              PRECIP_METHOD="thiessen", PRECIP_GAUGE_FILE=g, PRECIP_TIMESERIES_FILE=r,
              CFL_DT_MAX=30.0, OUTPUT_INTERVAL_SECONDS=600, CHANNEL_QBF_M3S=1.0,
              RUNOFF_SOURCE="physical", RUNOFF_MECHANISMS=["infiltration_excess"],
              GA_KSAT_MMHR=4.0, TOTAL_SIMULATION_TIME_HOURS=HOURS,
              BASEFLOW_METHOD="store", BASEFLOW_ET0_MM_DAY=3.0)
    kw.update(extra)
    return Config(**kw)


def _route(p, out, rain, **extra):
    shutil.copytree(p["base"], out, dirs_exist_ok=True)
    cfg = _cfg(p["dem"], p["outlet"], str(out), p["gauges"], rain, **extra)
    cfg.validate()
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        run_pipeline(cfg, stages=("routing",), on_log=lambda *_: None)
    return cfg, log.getvalue()


def _budget(cfg):
    b = pd.read_csv(f"{cfg.OUTPUT_DIR}/baseflow.csv")
    mb = pd.read_csv(cfg.MASS_BALANCE_CSV).iloc[-1]
    return b, mb


def test_store_alone_follows_the_recession_curve(prepared, tmp_path):
    """No rain: baseflow starts at BASEFLOW_SPECIFIC_Q and fades as exp(-t/K)."""
    k_days, q0 = 2.0, 0.5
    cfg, _ = _route(prepared, tmp_path / "r", prepared["dry"], ROUTING_SCHEME="kinematic",
                    BASEFLOW_SPECIFIC_Q=q0, BASEFLOW_RESPONSE_DAYS=k_days,
                    BASEFLOW_ET0_MM_DAY=0.0)
    b, mb = _budget(cfg)
    rate = b["baseflow_m3s"].to_numpy()[1:]                  # mean over each closed interval
    t_mid = b["time_s"].to_numpy()[1:] - 300.0
    np.testing.assert_allclose(rate / rate[0], np.exp(-(t_mid - t_mid[0]) / (k_days * 86400)),
                               rtol=1e-6)
    q = pd.read_csv(cfg.HYDROGRAPH_CSV)["Q_m3s"].to_numpy()
    assert q[0] == pytest.approx(rate[0], rel=0.02)          # rivers start in balance with it
    assert q[-1] == pytest.approx(rate[-1], rel=0.02) and q[-1] < 0.65 * q[0]
    assert abs(float(mb["rel_error"])) < 1e-6


@pytest.mark.parametrize("scheme", list(SCHEMES) + ["diffusive"])
def test_water_is_conserved_in_every_scheme(prepared, tmp_path, scheme):
    cfg, log = _route(prepared, tmp_path / "w", prepared["wet"], ROUTING_SCHEME=scheme,
                      BASEFLOW_SOIL_STORAGE_MM=20.0, BASEFLOW_START_WETNESS=0.9,
                      BASEFLOW_RESPONSE_DAYS=1.0)
    b, mb = _budget(cfg)
    assert abs(float(mb["rel_error"])) < 1e-6                # routed water
    last = b.iloc[-1]
    assert last["soaked_in_mm"] > 20 and last["recharge_mm"] > 0 and last["evaporation_mm"] > 0
    assert b["baseflow_m3s"].max() > 0
    assert "SOIL AND GROUNDWATER BUDGET" in log
    line = [ln for ln in log.splitlines() if "Closure error" in ln][-1]
    assert "PASS" in line                                    # soil and groundwater


def test_without_evaporation_all_soaked_in_water_is_kept_or_returned(prepared, tmp_path):
    cfg, _ = _route(prepared, tmp_path / "z", prepared["wet"], ROUTING_SCHEME="kinematic",
                    BASEFLOW_ET0_MM_DAY=0.0, BASEFLOW_START_WETNESS=1.0,
                    BASEFLOW_RESPONSE_DAYS=0.5)
    b, _ = _budget(cfg)
    last = b.iloc[-1]
    assert last["evaporation_mm"] == 0.0
    assert last["recharge_mm"] == pytest.approx(last["soaked_in_mm"], rel=1e-9)
    off, _ = _route(prepared, tmp_path / "off", prepared["wet"], ROUTING_SCHEME="kinematic",
                    BASEFLOW_METHOD="constant")
    more = (pd.read_csv(cfg.HYDROGRAPH_CSV)["Q_m3s"].sum()
            - pd.read_csv(off.HYDROGRAPH_CSV)["Q_m3s"].sum()) * 600.0
    assert more > 0                                           # the returned water reaches the outlet


@pytest.mark.parametrize("scheme", list(SCHEMES))
def test_split_run_equals_continuous_run(prepared, tmp_path, scheme):
    kw = dict(ROUTING_SCHEME=scheme, ADAPTIVE_TIMESTEP=False, TIME_STEP_SECONDS=SCHEMES[scheme],
              BASEFLOW_SOIL_STORAGE_MM=20.0, BASEFLOW_RESPONSE_DAYS=1.0, BASEFLOW_SPECIFIC_Q=0.2)
    whole, _ = _route(prepared, tmp_path / "whole", prepared["wet"],
                      SAVE_STATE_AT_HOURS=[12, 24], **kw)
    second, _ = _route(prepared, tmp_path / "second", prepared["tail"],
                       TOTAL_SIMULATION_TIME_HOURS=12.0, SAVE_STATE_AT_HOURS=[12],
                       RESTART_FROM=f"{whole.OUTPUT_DIR}/state/state_{12.0:08.2f}h.npz", **kw)
    hw = pd.read_csv(whole.HYDROGRAPH_CSV)
    hw = hw[hw["time_s"] > 12 * 3600 + 1]["Q_m3s"].to_numpy()
    hs = pd.read_csv(second.HYDROGRAPH_CSV)["Q_m3s"].to_numpy()
    np.testing.assert_array_equal(hs, hw)
    ew = np.load(f"{whole.OUTPUT_DIR}/state/state_{24.0:08.2f}h.npz")
    es = np.load(f"{second.OUTPUT_DIR}/state/state_{12.0:08.2f}h.npz")
    for k in ("baseflow._S", "baseflow._G"):
        np.testing.assert_array_equal(es[k], ew[k], err_msg=k)


def test_settings_are_checked(prepared):
    def errors(**kw):
        return " ".join(_cfg(prepared["dem"], prepared["outlet"], "x", prepared["gauges"],
                             prepared["wet"], **kw).validate(raise_on_error=False))
    assert "evaporation demand" in errors(BASEFLOW_ET0_MM_DAY=None)
    assert "BASEFLOW_RESPONSE_DAYS" in errors(BASEFLOW_RESPONSE_DAYS=0)
    assert "BASEFLOW_START_WETNESS" in errors(BASEFLOW_START_WETNESS=1.5)
    assert "BASEFLOW" not in errors()
    assert "BASEFLOW" not in errors(BASEFLOW_METHOD="constant", BASEFLOW_ET0_MM_DAY=None)


def test_evaporation_is_downloaded_once_and_cached(prepared, tmp_path, monkeypatch):
    from MRRpy.core.precip import openmeteo
    calls = []

    def fake(url):
        calls.append(url)
        return {"daily": {"et0_fao_evapotranspiration": [2.0, 4.0, None]}}
    monkeypatch.setattr(openmeteo, "_http_get_json", fake)
    kw = dict(ROUTING_SCHEME="kinematic", BASEFLOW_ET0_MM_DAY=None,
              EVENT_START_UTC="2021-07-01 12:00", BASEFLOW_START_WETNESS=1.0)
    cfg, log = _route(prepared, tmp_path / "e", prepared["wet"], **kw)
    assert len(calls) == 1 and "et0_fao_evapotranspiration" in calls[0]
    assert "start_date=2021-07-01" in calls[0] and "end_date=2021-07-02" in calls[0]
    b, _ = _budget(cfg)
    # 12 h of the first day (2 mm/day) + 12 h of the second (4 mm/day), soil wet → 3 mm
    assert b.iloc[-1]["evaporation_mm"] == pytest.approx(3.0, rel=0.02)

    def offline(url):
        raise OSError("no network")
    monkeypatch.setattr(openmeteo, "_http_get_json", offline)
    _route(prepared, tmp_path / "e", prepared["wet"], **kw)      # same folder: uses the cache
    with pytest.raises(slowflow.SlowFlowError, match="BASEFLOW_ET0_MM_DAY"):
        _route(prepared, tmp_path / "f", prepared["wet"], **kw)
