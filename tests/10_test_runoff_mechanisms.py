"""
tests/10_test_runoff_mechanisms.py
==================================
Verification tests for the composable, process-based runoff generator
(RUNOFF_SOURCE='physical') and its three mechanisms
(impervious / infiltration_excess / saturation_excess) in
MRRpy/core/runoff/{physical,mechanisms}.py.

Uses a small synthetic grid built in-memory (an 8-cell chain) plus two tiny
on-disk rasters — no real watershed, no Earth Engine — so these checks isolate
the mechanism composition, the partition bookkeeping, and the pluggable
mechanism registry.

Tests
-----
1. Partition invariant       — imperv + dunne + horton rates sum EXACTLY to the
   effective runoff returned by the engine, every step, for every mechanism mix.
2. Single-mechanism isolation — each mechanism alone activates only its own
   partition component (impervious→imperv, infiltration_excess→horton,
   saturation_excess→dunne).
3. Combiner max()            — on a saturated pervious cell, saturation-excess
   sheds 100 % of rain regardless of infiltration capacity (no double count).
4. Forward-Euler infiltration — Green-Ampt capacity decays as cumulative F grows,
   so infiltration-excess runoff is non-decreasing under steady rain.
5. Registry / pluggability   — the three mechanisms are registered, and a custom
   mechanism registered with @register_mechanism is picked up.

Run from the project root:
    python tests/10_test_runoff_mechanisms.py

Each test prints PASS or FAIL with a short reason.
"""

import os
import sys
import tempfile

import numpy as np
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from MRRpy import Config
from MRRpy.core.runoff import RunoffEngine, MECHANISM_REGISTRY, register_mechanism

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

N = 8                      # cells in the synthetic chain
CELL = 30.0                # m
_TMP = tempfile.mkdtemp(prefix="hf_mech_")
_DEM = os.path.join(_TMP, "dem.tif")
_IMP = os.path.join(_TMP, "imperv.tif")


def _write_rasters():
    """Two tiny (N×1) rasters on the same grid: a DEM and a 0.3 impervious map."""
    transform = from_origin(0.0, N * CELL, CELL, CELL)
    prof = dict(driver="GTiff", height=N, width=1, count=1, dtype="float32",
                crs="EPSG:32645", transform=transform, nodata=-9999.0)
    dem = np.linspace(100.0, 10.0, N, dtype="float32").reshape(N, 1)  # slopes down
    imp = np.full((N, 1), 0.3, dtype="float32")
    for path, arr in ((_DEM, dem), (_IMP, imp)):
        with rasterio.open(path, "w", **prof) as d:
            d.write(arr, 1)


def _grid():
    """Synthetic single-sandbox grid_data (cell_polygon absent → single mode)."""
    faccum_1d = np.arange(1, N + 1, dtype=np.float64)   # outlet = last cell
    dem2d = np.linspace(100.0, 10.0, N, dtype=np.float64).reshape(N, 1)
    return {
        "n_cells": N, "nrows": N, "ncols": 1,
        "s_rows": np.arange(N), "s_cols": np.zeros(N, dtype=int),
        "cell_area": CELL * CELL, "cell_size": CELL,
        "slope_1d": np.full(N, 0.01), "faccum_1d": faccum_1d,
        "dem": dem2d, "xp": np,
    }


def _cfg(mechs, impervious=False):
    cfg = Config(DEM_PATH=_DEM, RUNOFF_SOURCE="physical", RUNOFF_MECHANISMS=mechs,
                 VSA_SD_SOURCE="manual", GA_SUCTION_SOURCE="scalar",
                 GA_KSAT_SOURCE="scalar",
                 IMPERVIOUS_SOURCE=("raster" if impervious else "none"),
                 IMPERVIOUS_RASTER_PATH=(_IMP if impervious else None))
    cfg.ROUTING_DEM_PATH = _DEM
    return cfg


def _engine(mechs, impervious=False):
    return RunoffEngine(_cfg(mechs, impervious), _grid())


def _rates(eng):
    """The three stashed per-cell mechanism rates from the last combiner call."""
    to = lambda a: np.asarray(a, dtype=np.float64)
    return (to(eng._impl._last_imperv_rate),
            to(eng._impl._last_dunne_rate),
            to(eng._impl._last_horton_rate))


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — partition invariant
# ─────────────────────────────────────────────────────────────────────────────
def test_partition_invariant():
    name = "1 · partition invariant (imperv + dunne + horton == effective)"
    try:
        rain = np.full(N, 20.0 / 1000.0 / 3600.0)   # 20 mm/hr → m/s
        dt = 300.0
        combos = [["impervious"], ["infiltration_excess"], ["saturation_excess"],
                  ["infiltration_excess", "saturation_excess"],
                  ["impervious", "infiltration_excess", "saturation_excess"]]
        worst = 0.0
        for mechs in combos:
            eng = _engine(mechs, impervious=("impervious" in mechs))
            for step in range(12):
                eff = np.asarray(eng.get_effective_1d(step * dt, rain), dtype=np.float64)
                imp, dun, hor = _rates(eng)
                worst = max(worst, float(np.max(np.abs((imp + dun + hor) - eff))))
                eng.update_state(rain, dt)
        ok = worst < 1e-18
        print(f"  {PASS if ok else FAIL}  {name}  (max residual={worst:.2e})")
    except Exception as e:
        print(f"  {FAIL}  {name}  Exception: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — single-mechanism isolation
# ─────────────────────────────────────────────────────────────────────────────
def test_isolation():
    name = "2 · single-mechanism isolation"
    try:
        rain = np.full(N, 60.0 / 1000.0 / 3600.0)   # high rain to force Horton
        dt = 600.0

        def totals(mechs, impervious=False):
            eng = _engine(mechs, impervious=impervious)
            tot = np.zeros(3)
            for step in range(20):
                eng.get_effective_1d(step * dt, rain)
                tot += [np.sum(r) for r in _rates(eng)]
                eng.update_state(rain, dt)
            return tot   # [imperv, dunne, horton]

        imp = totals(["impervious"], impervious=True)
        inf = totals(["infiltration_excess"])
        sat = totals(["saturation_excess"])
        ok = (imp[0] > 0 and imp[1] == 0 and imp[2] == 0 and       # impervious → imperv only
              inf[2] > 0 and inf[0] == 0 and inf[1] == 0 and       # infil → horton only
              sat[1] > 0 and sat[0] == 0 and sat[2] == 0)          # sat → dunne only
        print(f"  {PASS if ok else FAIL}  {name}  "
              f"(imp={imp.round(6)} inf={inf.round(6)} sat={sat.round(6)})")
    except Exception as e:
        print(f"  {FAIL}  {name}  Exception: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — combiner max() (saturation dominates on saturated pervious cells)
# ─────────────────────────────────────────────────────────────────────────────
def test_combiner_max():
    name = "3 · combiner max() — saturated cell sheds 100% (no double count)"
    try:
        rain = np.full(N, 40.0 / 1000.0 / 3600.0)
        dt = 600.0
        eng = _engine(["infiltration_excess", "saturation_excess"])
        sat = eng._impl._sat
        ok = True
        for step in range(15):
            eff = np.asarray(eng.get_effective_1d(step * dt, rain), dtype=np.float64)
            mask = np.asarray(sat.mask)
            # On saturated cells (no impervious here) effective runoff == rain.
            if mask.any() and not np.allclose(eff[mask], rain[mask], atol=1e-18):
                ok = False
            imp, dun, hor = _rates(eng)
            # A cell counts as EITHER dunne OR horton, never both.
            if np.any((dun > 0) & (hor > 0)):
                ok = False
            eng.update_state(rain, dt)
        print(f"  {PASS if ok else FAIL}  {name}")
    except Exception as e:
        print(f"  {FAIL}  {name}  Exception: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — forward-Euler Green-Ampt (capacity decays, runoff non-decreasing)
# ─────────────────────────────────────────────────────────────────────────────
def test_infiltration_forward_euler():
    name = "4 · Green-Ampt forward-Euler (F grows → runoff non-decreasing)"
    try:
        rain = np.full(N, 50.0 / 1000.0 / 3600.0)
        dt = 600.0
        eng = _engine(["infiltration_excess"])
        prev = -1.0
        monotone = True
        F0 = float(np.asarray(eng._impl._infil._F)[0])
        for step in range(20):
            eff = np.asarray(eng.get_effective_1d(step * dt, rain), dtype=np.float64)
            cur = float(eff[0])
            if cur < prev - 1e-18:
                monotone = False
            prev = cur
            eng.update_state(rain, dt)
        F1 = float(np.asarray(eng._impl._infil._F)[0])
        ok = monotone and (F1 > F0) and (prev > 0.0)
        print(f"  {PASS if ok else FAIL}  {name}  (F:{F0:.3g}→{F1:.3g})")
    except Exception as e:
        print(f"  {FAIL}  {name}  Exception: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — registry / pluggability
# ─────────────────────────────────────────────────────────────────────────────
def test_registry():
    name = "5 · mechanism registry + pluggability"
    try:
        builtins_ok = all(m in MECHANISM_REGISTRY for m in
                          ("impervious", "infiltration_excess", "saturation_excess"))

        @register_mechanism("half_rain")
        class _HalfRain:
            name = "half_rain"
            def __init__(self, cfg, grid_data, shared):
                pass

        plugged = MECHANISM_REGISTRY.get("half_rain") is _HalfRain
        ok = builtins_ok and plugged
        print(f"  {PASS if ok else FAIL}  {name}  "
              f"(registered: {sorted(MECHANISM_REGISTRY)})")
    except Exception as e:
        print(f"  {FAIL}  {name}  Exception: {e}")


if __name__ == "__main__":
    print("=" * 70)
    print("Runoff mechanisms — composable physical runoff generator")
    print("=" * 70)
    _write_rasters()
    test_partition_invariant()
    test_isolation()
    test_combiner_max()
    test_infiltration_forward_euler()
    test_registry()
    print("=" * 70)
