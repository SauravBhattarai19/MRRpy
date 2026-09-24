"""
tests/09_test_scs_cn.py
=======================
Verification tests for the SCS Curve Number runoff mode
(ScsCnMode in MRRpy/core/runoff/engine.py).

Uses a small synthetic grid_data built in-memory — no real DEM/watershed and
no Earth Engine needed — so these checks isolate the CN math, the AMC
conversion, and the pluggable-registry plumbing.

Tests
-----
1. Initial abstraction threshold — no runoff until cumulative rainfall exceeds
   Ia = 0.2·S, and the SCS parameters S, Ia match 25400/CN − 254.
2. Mass balance + monotonicity — cumulative effective rainfall Pe never exceeds
   cumulative gross rainfall P, and per-step increments are non-negative.
3. AMC ordering — total runoff for the same storm satisfies dry ≤ normal ≤ wet
   (AMC I ≤ II ≤ III), and the CN conversion hits the textbook values.
4. Registry / pluggability — a custom mode registered with @register is picked
   up by RunoffEngine, and the latent is_active() path works for scs_cn.

Run from the project root:
    python tests/09_test_scs_cn.py

Each test prints PASS or FAIL with a short reason.
"""

import os
import sys
import warnings

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from MRRpy.core.runoff import RunoffEngine, RunoffMode, register, RUNOFF_MODES
from MRRpy.core.runoff.engine import _apply_amc

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


class _Cfg:
    """Minimal stand-in for MRRpy.Config exposing only what ScsCnMode reads."""
    RUNOFF_SOURCE = "scs_cn"
    RUNOFF_CN_SOURCE = "scalar"
    RUNOFF_CN = 75.0
    RUNOFF_CN_AMC = "ii"
    RUNOFF_SCS_Ia_FACTOR = 0.2


def _grid(n=4):
    return dict(n_cells=n, s_rows=np.arange(n), s_cols=np.zeros(n, dtype=int),
                nrows=n, ncols=1, xp=np)


def _engine(cn=75.0, amc="ii", ia=0.2, source="scalar"):
    cfg = _Cfg()
    cfg.RUNOFF_CN = cn
    cfg.RUNOFF_CN_AMC = amc
    cfg.RUNOFF_SCS_Ia_FACTOR = ia
    cfg.RUNOFF_CN_SOURCE = source
    return RunoffEngine(cfg, _grid())


def _run_storm(eng, rate_mm_hr=30.0, hours=10, dt=3600.0):
    """Drive the forward-Euler contract; return (cumP_mm, cumPe_mm, rates_mm_hr)."""
    n = eng._n_cells
    rain = np.full(n, rate_mm_hr / 1000.0 / 3600.0)  # mm/hr → m/s
    cumP = 0.0
    cumPe = 0.0
    rates = []
    for step in range(hours):
        src = eng.get_effective_1d(step * dt, rain)   # uses previous state
        rates.append(float(np.asarray(src)[0]) * 1000.0 * 3600.0)  # m/s → mm/hr
        eng.update_state(rain, dt)
        cumP += rate_mm_hr
        cumPe += float(np.asarray(eng._delta_Pe_m)[0]) * 1000.0
    return cumP, cumPe, rates


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — initial abstraction threshold + SCS parameters
# ─────────────────────────────────────────────────────────────────────────────
def test_initial_abstraction():
    name = "1 · initial-abstraction threshold + S/Ia values"
    try:
        cn = 80.0
        eng = _engine(cn=cn)
        S = np.asarray(eng._S_1d)[0]
        Ia = np.asarray(eng._Ia_1d)[0]
        S_expected = 25400.0 / cn - 254.0
        ok_params = np.isclose(S, S_expected) and np.isclose(Ia, 0.2 * S_expected)

        # Feed rainfall just under Ia (in mm): Ia ≈ 12.7 mm. One 10 mm step → no runoff.
        n = eng._n_cells
        dt = 3600.0
        rain = np.full(n, 10.0 / 1000.0 / 3600.0)  # 10 mm in one hour
        eng.get_effective_1d(0.0, rain)
        eng.update_state(rain, dt)
        no_runoff_below_Ia = float(np.asarray(eng._delta_Pe_m)[0]) == 0.0

        # Another 10 mm step (cum 20 mm > Ia) → runoff now appears.
        eng.get_effective_1d(dt, rain)
        eng.update_state(rain, dt)
        runoff_above_Ia = float(np.asarray(eng._delta_Pe_m)[0]) > 0.0

        if ok_params and no_runoff_below_Ia and runoff_above_Ia:
            print(f"  {PASS}  {name}")
            return True
        print(f"  {FAIL}  {name} (params={ok_params}, "
              f"below_Ia={no_runoff_below_Ia}, above_Ia={runoff_above_Ia})")
        return False
    except Exception as exc:
        print(f"  {FAIL}  {name} (exception: {exc})")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — mass balance + monotonic non-negative increments
# ─────────────────────────────────────────────────────────────────────────────
def test_mass_balance():
    name = "2 · mass balance (Pe ≤ P) + non-negative increments"
    try:
        eng = _engine(cn=85.0)
        # capture per-step deltas
        n = eng._n_cells
        dt = 3600.0
        rain = np.full(n, 40.0 / 1000.0 / 3600.0)
        deltas = []
        cumP = 0.0
        cumPe = 0.0
        for step in range(12):
            eng.get_effective_1d(step * dt, rain)
            eng.update_state(rain, dt)
            d = float(np.asarray(eng._delta_Pe_m)[0]) * 1000.0
            deltas.append(d)
            cumP += 40.0
            cumPe += d
        non_negative = all(d >= -1e-12 for d in deltas)
        conserved = cumPe <= cumP + 1e-9
        if non_negative and conserved:
            print(f"  {PASS}  {name}")
            return True
        print(f"  {FAIL}  {name} (non_neg={non_negative}, "
              f"cumPe={cumPe:.2f} cumP={cumP:.2f})")
        return False
    except Exception as exc:
        print(f"  {FAIL}  {name} (exception: {exc})")
        return False


def test_cn100_dry_state():
    """CN=100 has zero retention and must not evaluate 0/0 when dry."""
    name = "CN=100 dry state and full runoff"
    try:
        eng = _engine(cn=100.0)
        rain = np.full(eng._n_cells, 10.0 / 1000.0 / 3600.0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            eng.update_state(np.zeros_like(rain), 3600.0)
            dry = np.asarray(eng._delta_Pe_m).copy()
            eng.update_state(rain, 3600.0)
            wet = np.asarray(eng._delta_Pe_m).copy()
        if np.all(dry == 0.0) and np.allclose(wet, 0.01):
            print(f"  {PASS}  {name}")
            return True
        print(f"  {FAIL}  {name} (dry={dry}, wet={wet})")
        return False
    except Exception as exc:
        print(f"  {FAIL}  {name} (exception: {exc})")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — AMC ordering (dry ≤ normal ≤ wet) + textbook conversion
# ─────────────────────────────────────────────────────────────────────────────
def test_amc_ordering():
    name = "3 · AMC ordering (I ≤ II ≤ III) + conversion values"
    try:
        # Textbook conversion for CN_II = 75 → CN_I ≈ 56.8, CN_III ≈ 87.5
        cn2 = np.array([75.0])
        cn_i = _apply_amc(cn2, "i")[0]
        cn_iii = _apply_amc(cn2, "iii")[0]
        conv_ok = (np.isclose(cn_i, 56.81, atol=0.2)
                   and np.isclose(cn_iii, 87.54, atol=0.2)
                   and cn_i < 75.0 < cn_iii)

        totals = {}
        for amc in ("i", "ii", "iii"):
            _, cumPe, _ = _run_storm(_engine(cn=75.0, amc=amc))
            totals[amc] = cumPe
        ordered = totals["i"] <= totals["ii"] <= totals["iii"]

        if conv_ok and ordered:
            print(f"  {PASS}  {name}  "
                  f"(Pe: I={totals['i']:.1f} II={totals['ii']:.1f} III={totals['iii']:.1f})")
            return True
        print(f"  {FAIL}  {name} (conv_ok={conv_ok}, ordered={ordered}, totals={totals})")
        return False
    except Exception as exc:
        print(f"  {FAIL}  {name} (exception: {exc})")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — registry / pluggability + is_active()
# ─────────────────────────────────────────────────────────────────────────────
def test_registry_pluggable():
    name = "4 · pluggable registry + is_active()"
    try:
        # scs_cn is registered and reachable; is_active() works (regression:
        # it used to read an undefined _delta_Pe_m).
        eng = _engine(cn=75.0)
        _run_storm(eng, rate_mm_hr=50.0, hours=3)
        active_ok = eng.is_active(0.0) is True and "scs_cn" in RUNOFF_MODES

        # A custom third-party-style mode plugs in with no engine edits.
        @register("half_rain")
        class _HalfRain(RunoffMode):
            name = "half_rain"

            def get_effective_1d(self, t_seconds, rain_1d):
                return rain_1d * 0.5

            def is_active(self, t_seconds):
                return True

        class _CustomCfg:
            RUNOFF_SOURCE = "half_rain"

        ce = RunoffEngine(_CustomCfg(), _grid())
        r = np.array([1.0, 2.0, 3.0, 4.0])
        plug_ok = np.allclose(ce.get_effective_1d(0.0, r), r * 0.5)

        # clean up the test registration so it doesn't leak into other suites
        RUNOFF_MODES.pop("half_rain", None)

        if active_ok and plug_ok:
            print(f"  {PASS}  {name}")
            return True
        print(f"  {FAIL}  {name} (active_ok={active_ok}, plug_ok={plug_ok})")
        return False
    except Exception as exc:
        print(f"  {FAIL}  {name} (exception: {exc})")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("SCS Curve Number Verification Tests")
    print("=" * 60)
    results = [
        test_initial_abstraction(),
        test_mass_balance(),
        test_cn100_dry_state(),
        test_amc_ordering(),
        test_registry_pluggable(),
    ]
    print("-" * 60)
    n_pass = sum(results)
    print(f"{n_pass}/{len(results)} tests passed")
    sys.exit(0 if n_pass == len(results) else 1)
