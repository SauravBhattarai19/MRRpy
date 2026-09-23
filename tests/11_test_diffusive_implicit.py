"""
tests/11_test_diffusive_implicit.py
===================================
Verification tests for the semi-implicit (HEC-RAS-style) diffusion-wave routing
scheme (ROUTING_SCHEME='diffusive_implicit') in MRRpy/core/routing/implicit.py.

The explicit 'diffusive' scheme is stable only under a CFL time step, so it
collapses dt on steep cells (celerity ∝ √S) and leans on the volume flux limiter
(artificial diffusion) elsewhere.  The implicit scheme solves the same physics on
the D8 tree with an exact O(n) two-sweep solve — unconditionally stable, big
steps, mass-conservative.  These checks confirm it is correct, conservative,
scientific and fast.

Tests
-----
1. Tree linear solver     — the O(n) sweep + SciPy splu match a dense solve on
   random tree matrices (the linear-algebra core).
2. Mass balance           — a convergent-valley DEM closes to < 1e-6 (machine
   precision), Q ≥ 0, the storm actually routes.
3. Steep-terrain speed    — on a steep valley the explicit scheme's CFL dt
   collapses (many steps); the implicit scheme uses far fewer steps and still
   closes mass — the headline "HEC-RAS quick" win.
4. Kinematic-limit depth  — steady inflow on a uniform channel converges to
   Manning normal depth (hydraulics.normal_depth) — physical correctness.
5. Diffusion attenuation  — the implicit diffusive peak is attenuated relative to
   the non-diffusive kinematic peak (the diffusion wave flattens the peak).
6. Hayami benchmark       — outflow of a routed inflow pulse on a straight channel
   matches the analytical linear diffusion-wave (Hayami) solution in peak
   attenuation and time-to-peak (approximate; nonlinear Manning vs linear theory).

Run from the project root:
    python tests/11_test_diffusive_implicit.py

Each test prints PASS or FAIL with a short reason.
"""

import io
import os
import re
import sys
import contextlib
import tempfile

import numpy as np
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from MRRpy import Config, run_pipeline
from MRRpy.core.routing import hydraulics
from MRRpy.core.routing.implicit import (
    ImplicitDiffusiveSolver, _sweep_solve, _splu_solve,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

_TMP = tempfile.mkdtemp(prefix="hf_impl_")
_results = []


def _record(name, ok, reason=""):
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {reason}" if reason else ""))
    _results.append(bool(ok))
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _valley_dem(name, n=40, cell=30.0, drop_per_row=1.0, cross=2.0):
    """A convergent-valley DEM draining south into a central channel.  Larger
    ``drop_per_row`` → steeper (bigger downstream slope)."""
    path = os.path.join(_TMP, f"{name}.tif")
    rows, cols = np.mgrid[0:n, 0:n]
    center = (n - 1) / 2.0
    dem = ((n - 1 - rows) * drop_per_row
           + np.abs(cols - center) * cross + 10.0).astype("float32")
    epsg = 32615
    tr = from_origin(500000.0, 4000000.0 + n * cell, cell, cell)
    prof = dict(driver="GTiff", height=n, width=n, count=1, dtype="float32",
                crs=f"EPSG:{epsg}", transform=tr, nodata=-9999.0)
    with rasterio.open(path, "w", **prof) as ds:
        ds.write(dem, 1)
    orow, ocol = n - 2, int(round(center))
    ex, ey = tr * (ocol + 0.5, orow + 0.5)
    lon, lat = Transformer.from_crs(epsg, 4326, always_xy=True).transform(ex, ey)
    return path, (lat, lon)


def _run(scheme, dem_path, outlet, **kw):
    """Run process_dem + routing, capturing stdout.  Returns
    (hydrograph_df, rel_error, {steps, dt_mean, residual})."""
    out = os.path.join(_TMP, f"out_{scheme}_{abs(hash((dem_path, tuple(sorted(kw.items())))))%9999}")
    cfg = Config(DEM_PATH=dem_path, OUTPUT_DIR=out, OUTPUT_POINT=outlet,
                 PRECIP_METHOD="uniform", RAIN_INTENSITY_MM_HR=20.0,
                 RAIN_DURATION_HOURS=1.0, RUNOFF_SOURCE="none",
                 TOTAL_SIMULATION_TIME_HOURS=3.0, ADAPTIVE_TIMESTEP=True,
                 ROUTING_SCHEME=scheme, **kw)
    cfg.update_output_paths()
    cfg.validate()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = run_pipeline(cfg, stages=("process_dem", "routing"),
                           on_log=lambda m: None, on_progress=lambda p: None)
    txt = buf.getvalue()
    import pandas as pd
    hg = res["hydrograph_df"]
    rel = float(pd.read_csv(res["mass_balance_csv"]).tail(1)["rel_error"].iloc[0])
    m_steps = re.search(r"([\d,]+) steps", txt)
    m_dt = re.search(r"dt mean=([\d.]+)s", txt)
    m_res = re.search(r"peak residual ([\d.eE+-]+) m", txt)
    diag = dict(
        steps=int(m_steps.group(1).replace(",", "")) if m_steps else -1,
        dt_mean=float(m_dt.group(1)) if m_dt else float("nan"),
        residual=float(m_res.group(1)) if m_res else float("nan"),
    )
    return hg, rel, diag


def _straight_channel_grid(N, L, S0, B, n):
    """Hand-built grid_data for a straight N-cell channel (cell i drains to i+1,
    outlet = last).  Bypasses delineation so the solver can be driven directly."""
    dem = (np.arange(N)[::-1] * S0 * L + 10.0).astype(np.float64)   # slopes down to outlet
    ds_idx = np.arange(1, N + 1, dtype=np.int64)
    ds_idx[-1] = -1                                                  # outlet
    return {
        "dem_1d": dem,
        "dist_1d": np.full(N, L),
        "slope_1d": np.full(N, S0),
        "n_1d": np.full(N, n),
        "width_1d": np.full(N, B),
        "store_area_1d": np.full(N, B * L),                          # channel footprint
        "chan_mask_1d": np.ones(N, dtype=bool),
        "cell_size": L,
        "cell_area": L * L,
        "ds_idx": ds_idx,
        "n_cells": N,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tree linear solver vs dense
# ─────────────────────────────────────────────────────────────────────────────
def test_tree_solver():
    rng = np.random.default_rng(0)
    worst = 0.0
    for _ in range(150):
        n = int(rng.integers(2, 40))
        parent = np.array([rng.integers(i + 1, n) if i < n - 1 else -1
                           for i in range(n)], dtype=np.int64)
        is_root = parent < 0
        K = rng.uniform(0.1, 5.0, n)
        K[is_root] = 0.0
        diag = rng.uniform(1.0, 3.0, n)          # A/dt term → diagonal dominance
        diag[~is_root] += K[~is_root]
        np.add.at(diag, parent[~is_root], K[~is_root])
        off = -K
        # Dense reference.
        M = np.diag(diag).astype(float)
        for i in range(n):
            if not is_root[i]:
                p = parent[i]
                M[i, p] += off[i]
                M[p, i] += off[i]
        b = rng.uniform(-2, 2, n)
        z_ref = np.linalg.solve(M, b)
        z_sw = _sweep_solve(diag.copy(), off, parent, is_root, b.copy())
        z_lu = _splu_solve(diag.copy(), off, parent, is_root, b.copy())
        worst = max(worst, np.max(np.abs(z_sw - z_ref)), np.max(np.abs(z_lu - z_ref)))
    _record("tree solver (sweep & splu) vs dense", worst < 1e-8,
            f"max abs error {worst:.2e} over 150 random trees")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Mass balance on a convergent valley
# ─────────────────────────────────────────────────────────────────────────────
def test_mass_balance():
    dem, pt = _valley_dem("valley")
    hg, rel, _ = _run("diffusive_implicit", dem, pt)
    ok = (abs(rel) < 1e-6 and (hg["Q_m3s"] >= 0).all()
          and float(hg["Q_m3s"].max()) > 0.0)
    _record("mass balance on valley DEM", ok,
            f"rel_error={rel:.2e}, Qpeak={float(hg['Q_m3s'].max()):.3f} m³/s")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Steep terrain — explicit CFL collapses, implicit stays cheap
# ─────────────────────────────────────────────────────────────────────────────
def test_steep_speed():
    dem, pt = _valley_dem("steep", n=30, drop_per_row=8.0, cross=3.0)  # ~0.27 bed slope
    hg_e, rel_e, d_e = _run("diffusive", dem, pt)
    hg_i, rel_i, d_i = _run("diffusive_implicit", dem, pt)
    ok = (d_i["steps"] > 0 and d_e["steps"] > 0
          and d_i["steps"] < d_e["steps"]           # fewer steps than explicit
          and abs(rel_i) < 1e-6                      # still conservative
          and np.isfinite(float(hg_i["Q_m3s"].max())))
    _record("steep terrain: implicit fewer steps + conservative", ok,
            f"steps explicit={d_e['steps']:,} vs implicit={d_i['steps']:,} "
            f"(dt̄ {d_e['dt_mean']:.2f}s→{d_i['dt_mean']:.2f}s), rel_err={rel_i:.1e}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Kinematic-limit → Manning normal depth (steady inflow)
# ─────────────────────────────────────────────────────────────────────────────
def test_normal_depth_limit():
    N, L, S0, B, n = 60, 100.0, 0.002, 10.0, 0.03
    grid = _straight_channel_grid(N, L, S0, B, n)
    cfg = Config(DEM_PATH="x.tif", ROUTING_SCHEME="diffusive_implicit",
                 IMPLICIT_SLOPE_FLOOR=1e-9, IMPLICIT_MAX_ITERS=12, MIN_SLOPE=S0)
    solver = ImplicitDiffusiveSolver(cfg, grid)

    Q_in = 5.0                                    # m³/s injected at the head cell
    bc = np.zeros(N); bc[0] = Q_in
    src = np.zeros(N)
    vol = np.zeros(N)
    # March to steady state.
    for _ in range(4000):
        vol, q, _, _ = solver.solve_step(vol, src, bc, dt=60.0)
    h = vol / grid["store_area_1d"]
    # Manning normal depth for Q_in in this rectangular channel (interior cells).
    h_ref, _ = hydraulics.normal_depth(
        np.array([Q_in]), np.array([S0]), np.array([n]),
        np.array([B]), np.array([True]), np, iters=8)
    h_ref = float(h_ref[0])
    h_mid = float(h[N // 2])                        # mid-reach, away from BC/outlet
    err = abs(h_mid - h_ref) / h_ref
    _record("kinematic-limit normal depth", err < 0.05,
            f"h_solved={h_mid:.3f} m vs Manning normal {h_ref:.3f} m ({100*err:.1f}%)")


def _route_pulse(N=80, L=100.0, S0=0.001, B=20.0, n=0.03,
                 Q_base=5.0, Q_peak=25.0, t_rise=3600.0, dt=60.0, T=6 * 3600.0):
    """Route a triangular inflow pulse (on top of a warmed-up base flow) down a
    straight N-cell channel with the implicit solver.  Returns (t, I, out)."""
    grid = _straight_channel_grid(N, L, S0, B, n)
    cfg = Config(DEM_PATH="x.tif", ROUTING_SCHEME="diffusive_implicit",
                 IMPLICIT_SLOPE_FLOOR=1e-9, IMPLICIT_MAX_ITERS=15, MIN_SLOPE=S0)
    solver = ImplicitDiffusiveSolver(cfg, grid)
    nt = int(T / dt)
    t = np.arange(nt) * dt
    I = Q_base + (Q_peak - Q_base) * np.clip(
        np.where(t <= t_rise, t / t_rise, 2 - t / t_rise), 0, 1)
    vol, src, bc = np.zeros(N), np.zeros(N), np.zeros(N)
    for _ in range(3000):                            # warm up to base-flow steady state
        vol, _, _, _ = solver.solve_step(vol, src, np.where(np.arange(N) == 0, Q_base, 0.0), dt)
    out = np.empty(nt)
    for k in range(nt):
        bc[:] = 0.0
        bc[0] = I[k]
        vol, q, _, _ = solver.solve_step(vol, src, bc, dt)
        out[k] = q[-1]
    return t, I, out, grid


# ─────────────────────────────────────────────────────────────────────────────
# 5. Diffusion attenuates and lags the peak (the diffusion-wave signature)
# ─────────────────────────────────────────────────────────────────────────────
def test_diffusion_attenuation():
    t, I, out, _ = _route_pulse()
    qp_in, qp_out = float(I.max()), float(out.max())
    tp_in, tp_out = t[int(np.argmax(I))], t[int(np.argmax(out))]
    # A diffusion wave both attenuates (peak drops) and lags (peak arrives later);
    # a pure kinematic wave would translate the peak with NO attenuation.
    ok = qp_out < 0.9 * qp_in and tp_out > tp_in
    _record("diffusion attenuates + lags peak", ok,
            f"peak {qp_in:.1f}→{qp_out:.1f} m³/s (−{100*(1-qp_out/qp_in):.0f}%), "
            f"t_peak {tp_in/3600:.2f}→{tp_out/3600:.2f} h")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Hayami analytical linear diffusion-wave benchmark
# ─────────────────────────────────────────────────────────────────────────────
def _hayami_outflow(I_t, t, X, c, D):
    """Convolve inflow I(t) with the Hayami kernel for distance X (linear
    diffusion-analogy channel: celerity c, diffusivity D)."""
    dt = t[1] - t[0]
    tau = t.copy()
    tau[0] = 1e-9
    K = (X / (2.0 * np.sqrt(np.pi * D))) * tau ** (-1.5) \
        * np.exp(-((X - c * tau) ** 2) / (4.0 * D * tau))
    return np.convolve(I_t, K)[:len(t)] * dt


def test_hayami_benchmark():
    N, L, S0, B, n = 80, 100.0, 0.001, 20.0, 0.03
    Q_base, Q_peak = 5.0, 25.0
    t, I, out, grid = _route_pulse(N=N, L=L, S0=S0, B=B, n=n,
                                   Q_base=Q_base, Q_peak=Q_peak)

    # Linear theory needs a single (c, D).  Reference at a representative discharge
    # between base and peak — the pulse travels near this, not at base flow.
    Q_ref = 0.5 * (Q_base + Q_peak)
    h_ref, A_ref = hydraulics.normal_depth(np.array([Q_ref]), np.array([S0]),
                                           np.array([n]), np.array([B]),
                                           np.array([True]), np, iters=8)
    c = 5.0 / 3.0 * (Q_ref / float(A_ref[0]))       # kinematic celerity
    D = Q_ref / (2.0 * B * S0)                       # hydraulic diffusivity
    X = N * L
    hay = _hayami_outflow(I, t, X, c, D)

    qp_model, qp_hay = out.max(), hay.max()
    tp_model = t[int(np.argmax(out))]
    tp_hay = t[int(np.argmax(hay))]
    peak_err = abs(qp_model - qp_hay) / qp_hay
    lag_err = abs(tp_model - tp_hay) / max(tp_hay, 60.0)
    ok = peak_err < 0.20 and lag_err < 0.20         # approximate: nonlinear Manning vs linear theory
    _record("Hayami linear diffusion-wave benchmark", ok,
            f"peak model/Hayami={qp_model:.2f}/{qp_hay:.2f} m³/s ({100*peak_err:.0f}%), "
            f"t_peak {tp_model/3600:.2f}/{tp_hay/3600:.2f} h ({100*lag_err:.0f}%)")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Semi-implicit diffusion-wave routing — verification")
    print("=" * 70)
    for fn in (test_tree_solver, test_mass_balance, test_steep_speed,
               test_normal_depth_limit, test_diffusion_attenuation,
               test_hayami_benchmark):
        try:
            fn()
        except Exception as e:            # keep going; report the failure
            import traceback
            _record(fn.__name__, False, f"raised {type(e).__name__}: {e}")
            traceback.print_exc()
    n_ok = sum(_results)
    print("=" * 70)
    print(f"  {n_ok}/{len(_results)} checks passed")
    print("=" * 70)
    sys.exit(0 if n_ok == len(_results) else 1)
