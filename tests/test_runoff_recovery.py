# -*- coding: utf-8 -*-
"""
tests/test_runoff_recovery.py
=============================
Green-Ampt soil recovery between storms (``GA_RECOVERY``, the EPA SWMM 5
method).  Without recovery the cumulative infiltration F only grows, so over a
long run the infiltration capacity collapses to K_v for good.  These tests pin:

* ``GA_RECOVERY=False`` reproduces the legacy update exactly;
* inside one continuous heavy storm recovery changes nothing;
* a long dry spell restores the starting soil exactly, a shorter one partly;
* light rain keeps the dry-spell clock running, heavy rain restarts it;
* stored water stays within its physical bounds;
* under a repeating storm pattern the response settles instead of drifting;
* the physical-mode partition stays exact, and routing still conserves mass;
* the CuPy path matches NumPy (skipped without a GPU).

No Earth Engine, no data files; runs in a few seconds.
"""

import numpy as np
import pytest

from MRRpy import Config, run_pipeline
from MRRpy.core.runoff import RunoffEngine, MECHANISM_REGISTRY

MMHR = 1.0 / 1000.0 / 3600.0          # mm/h → m/s
KSAT = 12.0                           # mm/h
PSI = 0.15                            # m
SD_MAX, ZR = 0.10, 0.5                # → Δθ₀ = 0.2
DT = 300.0                            # s


@pytest.fixture(autouse=True)
def _no_land_cover_download(monkeypatch):
    """Root-zone depth without Earth Engine: every cell gets ZR."""
    from MRRpy.core.routing import surface
    monkeypatch.setattr(
        surface, "resolve_lulc_field",
        lambda cfg, grid, column, default, source:
            np.full(len(grid["s_rows"]), ZR, dtype=np.float64))


def _grid(n=1, xp=np):
    return {
        "n_cells": n, "nrows": n, "ncols": 1,
        "s_rows": np.arange(n), "s_cols": np.zeros(n, dtype=int),
        "cell_area": 900.0, "cell_size": 30.0,
        "slope_1d": np.full(n, 0.01),
        "faccum_1d": np.arange(1, n + 1, dtype=np.float64),
        "dem": np.linspace(100.0, 10.0, n).reshape(n, 1),
        "xp": xp,
    }


def _mech(recovery, ksat=KSAT, n=1, xp=np):
    cfg = Config(GA_RECOVERY=recovery, GA_KSAT_MMHR=ksat, GA_SUCTION_M=PSI,
                 VSA_SD_MAX_INITIAL=SD_MAX)
    shared = {"xp": xp, "cell_size": 30.0, "cell_area": 900.0,
              "sd_params": {"sd_max": SD_MAX, "deficit_raster": None},
              "imperv_frac": xp.zeros(n)}
    return MECHANISM_REGISTRY["infiltration_excess"](cfg, _grid(n, xp), shared)


def _run(mech, rain_mmhr, dt=DT):
    """Drive one mechanism through a rain series [mm/h]; return the
    infiltration-excess runoff depth [mm] of every step (forward Euler)."""
    out = []
    for r in rain_mmhr:
        rain = np.full(mech._n_cells, r * MMHR)
        exc = mech.excess_fraction(rain)
        out.append(float(np.asarray(rain * exc).mean()) * dt * 1000.0)
        mech.update_state(rain, dt)
    return np.array(out)


def _hours(h, dt=DT):
    return int(round(h * 3600.0 / dt))


STORM = [40.0] * _hours(2) + [25.0] * _hours(1)       # 3 h, always > K_v


# ─────────────────────────────────────────────────────────────────────────────
def test_off_reproduces_legacy_update_exactly():
    rng = np.random.default_rng(7)
    rain = rng.choice([0.0, 0.0, 5.0, 20.0, 60.0], size=600)
    mech = _mech(False)
    K = KSAT * MMHR
    dth = SD_MAX / ZR
    F = 0.0
    for r in rain:
        r_ms = np.array([r * MMHR])
        cap = K * (1.0 + PSI * dth / np.maximum(F, 1e-9))
        ref_exc = np.where(r_ms > 0.0, np.maximum(r_ms - cap, 0.0)
                           / np.maximum(r_ms, 1e-30), 0.0)
        assert np.array_equal(mech.excess_fraction(r_ms), ref_exc)
        mech.update_state(r_ms, DT)
        F = F + np.minimum(r_ms, cap) * DT
        assert np.array_equal(mech._F, F)


def test_continuous_heavy_storm_is_unchanged():
    assert np.array_equal(_run(_mech(True), STORM), _run(_mech(False), STORM))


def test_long_dry_spell_restores_starting_soil():
    mech = _mech(True)
    first = _run(mech, STORM)
    assert first.sum() > 0
    _run(mech, [0.0] * _hours(1.05 / (3600 * float(mech._kr[0]))))   # > drain time
    assert mech._F[0] == 0.0 and mech._Fu[0] == 0.0
    assert mech._dtheta[0] == pytest.approx(SD_MAX / ZR)
    assert np.allclose(_run(mech, STORM), first, rtol=0, atol=1e-12)


def test_partial_recovery_sits_between_fresh_and_legacy():
    gap = [0.0] * _hours(24)          # > T_r (6.5 h), < drain time (109 h)
    legacy, recov = _mech(False), _mech(True)
    first = _run(legacy, STORM)
    _run(recov, STORM)
    second_legacy = _run(legacy, gap + STORM).sum()
    second_recov = _run(recov, gap + STORM).sum()
    assert first.sum() < second_recov < second_legacy


def test_short_gap_drains_but_keeps_the_storm():
    mech = _mech(True)
    _run(mech, STORM)
    F0, Fu0, dth0 = float(mech._F[0]), float(mech._Fu[0]), float(mech._dtheta[0])
    n = _hours(2)                     # < T_r = 6.5 h at 12 mm/h
    _run(mech, [0.0] * n)
    drained = float(mech._kr[0] * mech._Fumax[0]) * DT * n
    assert mech._F[0] == pytest.approx(F0 - drained)
    assert mech._Fu[0] == pytest.approx(Fu0 - drained)
    assert mech._dtheta[0] == dth0                 # still the same storm


def test_dry_spell_clock_light_vs_heavy_rain():
    tr_h = float(_mech(True)._Tr[0]) / 3600.0
    # light rain (≤ K_v) after a storm, for longer than T_r: a new storm opens
    light = _mech(True)
    _run(light, STORM + [5.0] * _hours(tr_h + 1))
    assert light._F[0] == 0.0
    assert light._dtheta[0] < SD_MAX / ZR
    # light rain on fresh soil soaks into the upper zone and lowers Δθ
    # (6 mm into a 14 mm zone: Δθ = 0.2 − 0.006/L_u)
    fresh = _mech(True)
    _run(fresh, [2.0] * _hours(3))
    Lu = float(fresh._Lu[0])
    assert fresh._dtheta[0] == pytest.approx(SD_MAX / ZR - 0.006 / Lu, rel=1e-9)
    # heavy rain every T_r/2 keeps the clock from running out
    heavy = _mech(True)
    burst = [40.0] + [0.0] * (_hours(tr_h / 2) - 1)
    _run(heavy, STORM + burst * 6)
    assert heavy._F[0] > 0.0 and heavy._dtheta[0] == SD_MAX / ZR


def test_state_stays_physical():
    rng = np.random.default_rng(3)
    mech = _mech(True, n=4)
    dth0 = SD_MAX / ZR
    for _ in range(5000):
        rain = rng.choice([0.0, 0.0, 0.0, 2.0, 15.0, 80.0], size=4) * MMHR
        mech.excess_fraction(rain)
        mech.update_state(rain, DT)
        assert np.all(mech._F >= 0.0)
        assert np.all((mech._Fu >= 0.0) & (mech._Fu <= mech._Fumax + 1e-15))
        assert np.all((mech._dtheta >= 0.0) & (mech._dtheta <= dth0))


def test_repeating_storms_settle_instead_of_drifting():
    """Two years of the same storm every 5 days: with recovery the response
    settles to a steady cycle; without it later storms shed ever more."""
    week = STORM + [0.0] * (_hours(5 * 24) - len(STORM))
    n_storms = 146
    per_storm = {}
    for rec in (False, True):
        r = _run(_mech(rec), week * n_storms)
        per_storm[rec] = r.reshape(n_storms, -1).sum(axis=1)
    legacy, recov = per_storm[False], per_storm[True]
    assert legacy[-1] > 1.5 * recov[-1]
    assert np.all(np.diff(legacy) >= -1e-12)                # only ever grows
    assert recov[-1] == pytest.approx(recov[-20], rel=1e-9)  # steady cycle


def test_partition_exact_with_dry_spells(tmp_path):
    from rasterio.transform import from_origin
    import rasterio
    n = 8
    dem_p = str(tmp_path / "dem.tif")
    prof = dict(driver="GTiff", height=n, width=1, count=1, dtype="float32",
                crs="EPSG:32645", transform=from_origin(0, n * 30.0, 30.0, 30.0),
                nodata=-9999.0)
    with rasterio.open(dem_p, "w", **prof) as ds:
        ds.write(np.linspace(100, 10, n, dtype="float32").reshape(n, 1), 1)
    cfg = Config(DEM_PATH=dem_p, RUNOFF_SOURCE="physical",
                 RUNOFF_MECHANISMS=["infiltration_excess", "saturation_excess"],
                 VSA_SD_SOURCE="manual", VSA_PER_POLYGON=False, GA_RECOVERY=True)
    cfg.ROUTING_DEM_PATH = dem_p
    eng = RunoffEngine(cfg, _grid(n))
    worst = 0.0
    for r in (STORM + [0.0] * _hours(12)) * 3:
        rain = np.full(n, r * MMHR)
        eff = eng.get_effective_1d(0.0, rain)
        parts = (eng._impl._last_imperv_rate + eng._impl._last_dunne_rate
                 + eng._impl._last_horton_rate)
        worst = max(worst, float(np.max(np.abs(parts - eff))))
        eng.update_state(rain, DT)
    assert worst < 1e-15


def _two_storm_inputs(tmp_path, dem_p):
    """One rain gauge at the basin centre: two 2-h storms 72 h apart."""
    import pandas as pd
    import rasterio
    with rasterio.open(dem_p) as ds:
        cx, cy = ds.xy(ds.height // 2, ds.width // 2)
    g = tmp_path / "gauges.csv"
    pd.DataFrame({"gauge_id": ["G1"], "name": ["G1"],
                  "easting_m": [cx], "northing_m": [cy]}).to_csv(g, index=False)
    t = np.arange(0, 80 * 3600 + 1, 1800)
    depth = np.where((t < 2 * 3600) | ((t >= 74 * 3600) & (t < 76 * 3600)), 30.0, 0.0)
    ts = tmp_path / "rain.csv"
    pd.DataFrame({"time_s": t, "G1": depth}).to_csv(ts, index=False)
    return str(g), str(ts)


@pytest.mark.parametrize("scheme", ["kinematic", "diffusive_implicit"])
def test_pipeline_two_storms_conserves_mass(tiny_basin, tmp_path, scheme):
    dem_p, outlet = tiny_basin
    g, ts = _two_storm_inputs(tmp_path, dem_p)
    vols = {}
    for rec in (False, True):
        out = tmp_path / f"{scheme}_{rec}"
        cfg = Config(DEM_PATH=dem_p, OUTPUT_POINT=outlet, OUTPUT_DIR=str(out),
                     TARGET_CRS_EPSG="EPSG:32645", DELINEATION_ENGINE="pysheds",
                     PRECIP_METHOD="thiessen", PRECIP_GAUGE_FILE=g,
                     PRECIP_TIMESERIES_FILE=ts, RUNOFF_SOURCE="physical",
                     RUNOFF_MECHANISMS=["infiltration_excess"],
                     GA_KSAT_MMHR=KSAT, GA_RECOVERY=rec, ROUTING_SCHEME=scheme,
                     TOTAL_SIMULATION_TIME_HOURS=80.0, OUTPUT_INTERVAL_SECONDS=600,
                     CHANNEL_QBF_M3S=1.0)
        run_pipeline(cfg, on_log=lambda *_: None)
        import pandas as pd
        mb = pd.read_csv(cfg.MASS_BALANCE_CSV).iloc[-1]
        assert abs(float(mb["rel_error"])) < 1e-6
        vols[rec] = float(mb["input_m3"])
    assert 0.0 < vols[True] < vols[False]       # the soil dried for 3 days


def test_gpu_matches_cpu():
    cp = pytest.importorskip("cupy")
    try:
        cp.zeros(1).sum().item()
    except Exception:
        pytest.skip("no usable GPU")
    rng = np.random.default_rng(11)
    rain = rng.choice([0.0, 0.0, 3.0, 20.0, 70.0], size=(800, 3)) * MMHR
    cpu, gpu = _mech(True, n=3), _mech(True, n=3, xp=cp)
    for r in rain:
        a = cpu.excess_fraction(r)
        b = gpu.excess_fraction(cp.asarray(r))
        assert np.allclose(a, cp.asnumpy(b), rtol=1e-12, atol=0)
        cpu.update_state(r, DT)
        gpu.update_state(cp.asarray(r), DT)
    assert np.allclose(cpu._F, cp.asnumpy(gpu._F), rtol=1e-12, atol=1e-18)
