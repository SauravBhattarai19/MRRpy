# -*- coding: utf-8 -*-
"""
tests/test_routing_verification.py
==================================
Fast analytic / textbook regression tests for the routing core (no data, no
network, no GPU).  Every case runs MRRpy's real routing stage on a prescribed
N×1 strip (flow network written directly, so delineation is not under test).

  * kinematic plane (Wooding 1965; Chow, Maidment & Mays 1988 §9.6):
    rising limb, equilibrium i·A and recession — also catches the former
    one-step transit lag (+24 % travel time at any resolution);
  * dry channel + step inflow: wetting front arrives at L / V_normal;
  * steady flood above bankfull through the sub-grid incised channel: stage =
    compound-section Manning normal depth, Q_out = Q_in;
  * steady inflow + rain: Q_out = Q_in + i·A;
  * steady spatially-varied flow on a mild channel: diffusive_implicit matches
    the exact steady diffusion-wave profile (backwater from the outlet);
  * mass closure ≤ 1e-6 % in every run.

Run with:  pytest tests/test_routing_verification.py -v
"""
import contextlib
import io
import os
import re

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from MRRpy import Config, run_pipeline
from MRRpy.core.routing import hydraulics

EPSG = "EPSG:32614"


def _strip(out, N, dx, S0):
    os.makedirs(out, exist_ok=True)
    dem = ((N - 1 - np.arange(N)) * S0 * dx + 10.0).reshape(N, 1)
    arrs = (("clipped_dem.tif", dem, "float32", -9999.0),
            ("flow_direction.tif", np.full((N, 1), 4), "int16", None),       # ESRI D8 south
            ("clipped_flow_accumulation.tif", np.arange(1, N + 1).reshape(N, 1), "float32", -1.0),
            ("watershed.tif", np.ones((N, 1)), "uint8", None))
    tr = from_origin(500000.0, 4000000.0 + N * dx, dx, dx)
    for name, a, dt, nd in arrs:
        with rasterio.open(os.path.join(out, name), "w", driver="GTiff", height=N, width=1,
                           count=1, crs=EPSG, transform=tr, dtype=dt, nodata=nd) as d:
            d.write(np.asarray(a).astype(dt), 1)
    return os.path.join(out, "clipped_dem.tif")


def _run(tmp, scheme, N, dx, S0, hours, rain_mmhr=0.0, rain_hours=0.0, inflow=None,
         channel=None, n=0.05, fields=False, **kw):
    out = str(tmp / f"{scheme}")
    dem = _strip(out, N, dx, S0)
    cfg = Config(DEM_PATH=dem, OUTPUT_DIR=out, TARGET_CRS_EPSG=EPSG, OUTPUT_POINT=(36.0, -99.0),
                 ROUTING_SCHEME=scheme, PRECIP_METHOD="uniform", RAIN_INTENSITY_MM_HR=rain_mmhr,
                 RAIN_DURATION_HOURS=max(rain_hours, 1e-6), RUNOFF_SOURCE="none",
                 TOTAL_SIMULATION_TIME_HOURS=hours, MANNINGS_N_SOURCE="scalar", MIN_SLOPE=1e-6,
                 OUTPUT_INTERVAL_SECONDS=60, SAVE_FIELDS=fields, FIELD_VARS=["depth"])
    if channel is None:
        cfg.CHANNEL_ROUTING = False
        cfg.MANNINGS_N = n
        cfg.MANNINGS_N_CHANNEL = None
    else:
        cfg.CHANNEL_ROUTING = True
        cfg.CHANNEL_MIN_AREA_KM2 = 1e-9
        cfg.CHANNEL_GEOMETRY = "area"
        cfg.CHANNEL_HG = dict(w_a=channel["B"], w_b=0.0, d_a=channel["D"], d_b=0.0)
        cfg.MANNINGS_N = channel.get("n_fp", 0.05)
        cfg.MANNINGS_N_CHANNEL = channel["n"]
        cfg.MANNINGS_N_FLOODPLAIN = channel.get("n_fp", None)
    if inflow is not None:
        bc = os.path.join(out, "inflow.csv")
        pd.DataFrame({"time_s": inflow[0], "Q_m3s": inflow[1]}).to_csv(bc, index=False)
        cfg.ROUTING_INFLOW_BC = [dict(name="in", row=0, col=0, csv=bc, snap_to_channel=False)]
    for k, v in kw.items():
        setattr(cfg, k, v)
    cfg.update_output_paths()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_pipeline(cfg, stages=("routing",))
    hg = pd.read_csv(cfg.HYDROGRAPH_CSV)
    mb = float(re.search(r"Closure error\s*:.*?\(([-+\d.e]+) %", buf.getvalue()).group(1))
    return hg.time_s.values, hg.Q_m3s.values, mb, out


def _interval_mean(fun, t):
    tt = np.concatenate([[0.0], t])
    return np.array([fun(np.linspace(a, b, 30)).mean() for a, b in zip(tt[:-1], tt[1:])])


# ── kinematic plane: rise, equilibrium, recession ───────────────────────────
@pytest.mark.parametrize("scheme,min_nse", [("kinematic", 0.99), ("muskingum", 0.97),
                                            ("diffusive_implicit", 0.97)])
def test_kinematic_plane(tmp_path, scheme, min_nse):
    N, dx, S, n = 50, 20.0, 0.01, 0.05
    i = 50 / 1000 / 3600; L = N * dx; m = 5 / 3; a = np.sqrt(S) / n
    te = (L / (a * i ** (m - 1))) ** (1 / m); tr = 1.5 * te

    def q(t):
        t = np.asarray(t, float); out = np.where(t <= te, a * (i * t) ** m, i * L)
        rec = t > tr
        if rec.any():
            qq = np.logspace(np.log10(i * L) - 8, np.log10(i * L), 3000)
            trel = (L - qq / i) / (m * a ** (1 / m) * qq ** ((m - 1) / m))
            out[rec] = np.interp(t[rec] - tr, trel[::-1], qq[::-1])
        return out
    t, Q, mb, _ = _run(tmp_path, scheme, N, dx, S, 3 * te / 3600, 50.0, tr / 3600, n=n)
    qa = _interval_mean(q, t) * dx
    nse = 1 - np.sum((Q - qa) ** 2) / np.sum((qa - qa.mean()) ** 2)
    assert nse >= min_nse, f"NSE {nse:.4f}"
    assert abs(Q[(t > 1.2 * te) & (t <= tr)].mean() / (i * L * dx) - 1) < 0.01
    assert abs(mb) < 1e-6


# ── dry channel, step inflow: front at L / V_normal ─────────────────────────
@pytest.mark.parametrize("scheme,tol", [("kinematic", 0.05), ("muskingum", 0.12),
                                        ("diffusive_implicit", 0.08)])
def test_dry_channel_front(tmp_path, scheme, tol):
    N, dx, S0, B, D, n, Q = 100, 50.0, 0.001, 20.0, 2.0, 0.035, 30.0
    _h, A = hydraulics.normal_depth(np.array([Q]), np.array([S0]), np.array([n]), np.array([B]),
                                    np.array([True]), np, iters=40, bank=np.array([D]),
                                    cell_size=dx, n_fp=np.array([0.05]))
    t_arr = N * dx / (Q / float(A[0]))
    t, Qo, mb, _ = _run(tmp_path, scheme, N, dx, S0, 3 * t_arr / 3600, inflow=([0, 1e9], [Q, Q]),
                        channel=dict(B=B, D=D, n=n))
    t50 = float(np.interp(0.5 * Q, np.maximum.accumulate(Qo), t))
    assert abs(t50 / t_arr - 1) < tol, f"front {t50/60:.1f} min vs {t_arr/60:.1f} min"
    assert abs(Qo[-1] / Q - 1) < 0.01
    assert abs(mb) < 1e-6


# ── steady overbank flow: compound-section normal depth ─────────────────────
@pytest.mark.parametrize("scheme", ["kinematic", "diffusive_implicit"])
def test_overbank_compound_normal_depth(tmp_path, scheme):
    N, dx, S0, B, D, n, nfp = 60, 50.0, 0.001, 10.0, 1.0, 0.035, 0.06
    one = lambda v: np.array([v], float)
    Cb, _ = hydraulics.compound_conveyance(one(D), one(n), one(B), np.array([True]), one(D), dx, np, one(nfp))
    Q = 5 * float(Cb[0]) * np.sqrt(S0)
    h, _ = hydraulics.normal_depth(one(Q), one(S0), one(n), one(B), np.array([True]), np, iters=60,
                                   bank=one(D), cell_size=dx, n_fp=one(nfp))
    t, Qo, mb, out = _run(tmp_path, scheme, N, dx, S0, 8.0, inflow=([0, 1e9], [Q, Q]),
                          channel=dict(B=B, D=D, n=n, n_fp=nfp), fields=True)
    f = np.load(os.path.join(out, "fields", "fields.npz"))
    stage = f["depth"][-1][np.argsort(f["s_rows"])]
    assert abs(np.median(stage[N // 3: 2 * N // 3]) / float(h[0]) - 1) < 0.03
    assert abs(Qo[-1] / Q - 1) < 0.01
    assert abs(mb) < 1e-6


# ── inflow + rain superposition ─────────────────────────────────────────────
@pytest.mark.parametrize("scheme", ["kinematic", "muskingum", "diffusive_implicit"])
def test_inflow_plus_rain(tmp_path, scheme):
    N, dx, S0, Qin, imm = 60, 50.0, 0.002, 10.0, 20.0
    t, Qo, mb, _ = _run(tmp_path, scheme, N, dx, S0, 8.0, rain_mmhr=imm, rain_hours=8.0,
                        inflow=([0, 1e9], [Qin, Qin]), channel=dict(B=10.0, D=1.5, n=0.035))
    assert abs(Qo[-1] / (Qin + imm / 1000 / 3600 * N * dx * dx) - 1) < 0.01
    assert abs(mb) < 1e-6


# ── implicit = exact steady diffusion-wave profile (spatially varied flow) ──
def test_implicit_steady_diffusion_profile(tmp_path):
    """Lateral rain on a mild channel: Q grows downstream, so the steady
    diffusion-wave depth exceeds normal depth (flatter water surface).  The
    implicit solver must reproduce the exact discrete steady profile."""
    N, dx, S0, B, D, n, imm = 50, 20.0, 0.0005, 10.0, 2.0, 0.035, 200.0
    i = imm / 1000 / 3600
    t, Qo, mb, out = _run(tmp_path, "diffusive_implicit", N, dx, S0, 6.0, rain_mmhr=imm,
                          rain_hours=6.0, channel=dict(B=B, D=D, n=n), fields=True)
    f = np.load(os.path.join(out, "fields", "fields.npz"))
    h_model = f["depth"][-1][np.argsort(f["s_rows"])]
    one = lambda v: np.array([v], float)
    Qc = i * dx * dx * (np.arange(N) + 1)
    C = lambda h: float(hydraulics.compound_conveyance(one(h), one(n), one(B), np.array([True]),
                                                       one(D), dx, np, one(0.05))[0][0])
    h = np.zeros(N)
    h[-1] = float(hydraulics.normal_depth(one(Qc[-1]), one(S0), one(n), one(B), np.array([True]), np,
                                          iters=40, bank=one(D), cell_size=dx, n_fp=one(0.05))[0][0])
    for j in range(N - 2, -1, -1):
        g = lambda x: (x - h[j + 1]) + S0 * dx - dx * (Qc[j] / C(x)) ** 2
        lo, hi = 1e-7, 10.0
        for _ in range(80):
            mid = 0.5 * (lo + hi); lo, hi = (mid, hi) if g(mid) < 0 else (lo, mid)
        h[j] = 0.5 * (lo + hi)
    assert np.max(np.abs(h_model - h) / h) < 0.02, f"max rel. depth error {np.max(np.abs(h_model-h)/h):.3f}"
    assert abs(Qo[-1] / Qc[-1] - 1) < 0.01
    assert abs(mb) < 1e-6


# ── Muskingum–Cunge must pass an OVERBANK flood (no stalling in the ledger) ─
def test_muskingum_overbank_passes_volume(tmp_path):
    """Regression: with the sub-grid channel, MC used the channel width with the
    overbank flow area in its Cunge diffusion number, which drove the lateral /
    boundary-inflow coefficient to ~0 and left most of an overbank flood stuck
    in the ledger.  A 2-h flood at 5× bankfull must leave the reach."""
    N, dx, S0, B, D, n = 60, 90.0, 0.002, 12.0, 0.8, 0.035
    one = lambda v: np.array([v], float)
    Cb, _ = hydraulics.compound_conveyance(one(D), one(n), one(B), np.array([True]), one(D), dx, np, one(0.06))
    Q = 5 * float(Cb[0]) * np.sqrt(S0)
    t, Qo, mb, _ = _run(tmp_path, "muskingum", N, dx, S0, 12.0,
                        inflow=([0, 7199, 7200, 1e9], [Q, Q, 0.0, 0.0]),
                        channel=dict(B=B, D=D, n=n, n_fp=0.06))
    v_out = np.sum(Qo * np.diff(np.concatenate([[0.0], t])))
    # Variable-parameter MC is not exactly volume-conservative at the outlet: Tang,
    # Knight & Samuels (1999, J. Hydraul. Eng. 125(6)) report losses up to 8 %.  The
    # test guards against STALLING (the bug left ~35 % in the ledger), not against
    # that known method limitation.  Kinematic / implicit pass ≥ 99.8 % here.
    assert v_out / (Q * 7200.0) > 0.92, f"only {100*v_out/(Q*7200):.1f}% of the flood left the reach"
    assert abs(mb) < 1e-6


# ── discharge-based channel geometry: bankfull by construction ──────────────
@pytest.mark.parametrize("scheme", ["kinematic", "diffusive_implicit"])
def test_discharge_geometry_runs_bankfull_at_qbf(tmp_path, scheme):
    """CHANNEL_GEOMETRY='discharge' sizes the channel from the bankfull
    discharge (Andreadis et al. 2013 width + Manning-continuity depth), so a
    steady flow equal to Q_bf must fill the channel exactly to the bank."""
    N, dx, S0, Qbf = 60, 50.0, 0.001, 30.0
    t, Qo, mb, out = _run(tmp_path, scheme, N, dx, S0, 8.0, inflow=([0, 1e9], [Qbf, Qbf]),
                          channel=dict(B=1.0, D=1.0, n=0.035), fields=True,
                          CHANNEL_GEOMETRY="discharge", CHANNEL_QBF_M3S=Qbf, CHANNEL_QBF_AREA_EXP=0.0)
    W = 7.2 * Qbf ** 0.5
    one = lambda v: np.array([v], float)
    D = float(hydraulics.normal_depth(one(Qbf), one(S0), one(0.035), one(W), np.array([True]), np,
                                      iters=40)[0][0])
    f = np.load(os.path.join(out, "fields", "fields.npz"))
    stage = f["depth"][-1][np.argsort(f["s_rows"])]
    assert abs(np.median(stage[N // 3: 2 * N // 3]) / D - 1) < 0.03
    assert abs(Qo[-1] / Qbf - 1) < 0.01
    assert abs(mb) < 1e-6


def test_fit_channel_to_rating_recovers_width():
    from MRRpy.core.routing.surface import fit_channel_to_rating, qbf_from_annual_peaks
    W, n, S, h0 = 48.0, 0.035, 0.0017, 0.4
    stage = np.linspace(0.6, 6.0, 40)
    h = stage - h0
    Q = W * h * (W * h / (W + 2 * h)) ** (2 / 3) * np.sqrt(S) / n
    fit = fit_channel_to_rating(stage, Q, S, n, zero_flow_stage=h0)
    assert abs(fit["width_m"] / W - 1) < 0.03
    assert qbf_from_annual_peaks([100, 300, 200, np.nan]) == 200.0


def test_qbf_setting_kinds_and_safe_parsing():
    from MRRpy.core.routing.qbf import classify_qbf
    assert classify_qbf(None) == ("auto", None) and classify_qbf(" auto ") == ("auto", None)
    assert classify_qbf(400) == ("value", 400.0) and classify_qbf("400") == ("value", 400.0)
    kind, f = classify_qbf("wecs_nepal")
    assert kind == "formula" and f.uses == {("A_below", 3000.0)}
    kind, f = classify_qbf("Q2 = 1.8767*(A_below(3000)+1)^0.8783")      # pasted from a report
    assert kind == "formula" and f.uses == {("A_below", 3000.0)}
    assert classify_qbf("1.72e-4 * A^0.64 * P^1.313")[1].uses == {"A", "P"}
    for bad in ["__import__('os').system('ls')", "A.real", "foo(A)", "B*2", "A_below(H)",
                "lambda: 1", "[A]", "A if A else 1", 0, -5, "nan", True]:
        with pytest.raises(ValueError):
            classify_qbf(bad)


def test_qbf_formula_is_evaluated_per_cell():
    from MRRpy.core.routing.qbf import resolve_qbf
    g = _chain_grid()
    A = g["faccum_1d"] * g["cell_area"] / 1e6
    q, _ = resolve_qbf(Config(CHANNEL_QBF_M3S="2*A^0.5"), g, A)
    assert np.allclose(q, 2 * A ** 0.5)
    # A_below(z): the chain falls 0.18 m per cell from 107.2 m; cells below z drain
    # into the outlet, so the outlet's share below z = (cells below z) / N
    z = g["dem_1d"]
    q, _ = resolve_qbf(Config(CHANNEL_QBF_M3S="A_below(104)"), g, A)
    assert q[-1] == pytest.approx(A[-1] * np.mean(z < 104))
    q_w, label = resolve_qbf(Config(CHANNEL_QBF_M3S="wecs_nepal"), g, A)
    assert np.allclose(q_w, 1.8767 * (A + 1) ** 0.8783) and "wecs_nepal" in label   # all below 3,000 m


def test_qbf_number_and_auto_spread_from_outlet(monkeypatch):
    from MRRpy.core.routing import qbf
    g = _chain_grid()
    A = g["faccum_1d"] * g["cell_area"] / 1e6
    q, _ = qbf.resolve_qbf(Config(CHANNEL_QBF_M3S=300.0, CHANNEL_QBF_AREA_KM2=float(A[10])), g, A)
    assert q[10] == pytest.approx(300.0) and q[-1] == pytest.approx(300.0 * (A[-1] / A[10]) ** 0.75)
    monkeypatch.setattr(qbf, "_outlet_attrs", lambda cfg, point=None: None)            # offline
    q, label = qbf.resolve_qbf(Config(), g, A)
    assert q[-1] == pytest.approx(np.exp(0.5477) * A[-1] ** 0.6057) and "area only" in label
    monkeypatch.setattr(qbf, "_outlet_attrs",
                        lambda cfg, point=None: dict(UP_AREA=2 * A[-1], dis_m3_pmx=40.0, pre_mm_uyr=1500.0))
    q, label = qbf.resolve_qbf(Config(), g, A)
    assert q[-1] == pytest.approx(np.exp(2.7126) * 20.0 ** 0.6441) and "HydroATLAS" in label
    assert q[0] == pytest.approx(q[-1] * (A[0] / A[-1]) ** 0.75)
    q, _ = qbf.resolve_qbf(Config(CHANNEL_QBF_M3S="global_area_rain"), g, A)
    assert q[-1] == pytest.approx(1.72e-4 * A[-1] ** 0.640 * 1500.0 ** 1.313)


def test_qbf_validate_messages():
    def errs(**kw):
        try:
            Config(**kw).validate()
        except Exception as exc:                       # validate() also reports the missing DEM
            return str(exc)
        return ""
    assert "unknown function" in errs(CHANNEL_QBF_M3S="foo(A)")
    assert "only applies when CHANNEL_QBF_M3S is a number" in errs(CHANNEL_QBF_M3S="wecs_nepal",
                                                                    CHANNEL_QBF_AREA_KM2=100.0)
    assert "CHANNEL_QBF" not in errs(CHANNEL_QBF_M3S=None)                    # automatic is fine
    assert "CHANNEL_QBF" not in errs(CHANNEL_QBF_M3S=250.0, CHANNEL_QBF_AREA_KM2=100.0)


def test_channel_capacity_equals_qbf_at_every_cell():
    """Continuity depth: each channel cell carries exactly its own Q_bf full."""
    from MRRpy.core.routing.surface import discharge_geometry, reach_slope
    g = _chain_grid()
    W, D, Q, _ = discharge_geometry(Config(CHANNEL_QBF_M3S="5*A^0.7"), g, np.ones(g["n_cells"], bool))
    S = reach_slope(g, 1000.0, 1e-5)
    R = W * D / (W + 2 * D)
    assert np.allclose(W * D * R ** (2 / 3) * np.sqrt(S) / 0.035, Q, rtol=1e-3)


def test_monotone_bed_removes_digital_dams():
    """Reach-slope-dependent depths can put a shallow channel below a deep one
    (bed steps uphill = digital dam); monotone_bed_depth must remove every step
    and only ever deepen."""
    from MRRpy.core.routing.surface import monotone_bed_depth
    z = np.array([10.0, 9.9, 9.8, 9.7, 9.6])            # DEM surface, draining 0→4
    D = np.array([0.5, 3.0, 0.4, 0.4, 2.0])              # deep, then shallow → step up
    g = dict(ds_idx=np.array([1, 2, 3, 4, -1]), dem_1d=z, dist_1d=np.full(5, 90.0))
    D2, added = monotone_bed_depth(D, g, np.ones(5, bool), 1e-4)
    bed = z - D2
    assert np.all(np.diff(bed) < 0)
    assert np.all(D2 >= D) and added > 0


# ── audit follow-ups: discharge-geometry edge cases ─────────────────────────
def _chain_grid(N=40, dx=90.0, S=0.002, fa0=1000):
    """N-cell D8 chain draining to the last cell (topological order)."""
    fa = fa0 + np.arange(N, dtype=float) * 50.0
    return dict(n_cells=N, cell_size=dx, cell_area=dx * dx, faccum_1d=fa,
                ds_idx=np.r_[np.arange(1, N), -1], dem_1d=(N - np.arange(N)) * S * dx + 100.0,
                dist_1d=np.full(N, dx), slope_1d=np.full(N, S), n_1d=np.full(N, 0.035))


def test_channel_width_and_bank_share_one_geometry():
    from MRRpy.core.routing.surface import build_channel_geometry, build_channel_bank
    g = _chain_grid()
    cfg = Config(CHANNEL_GEOMETRY="discharge", CHANNEL_QBF_M3S=120.0, CHANNEL_MIN_AREA_KM2=1e-9)
    mask, width, store = build_channel_geometry(cfg, g)
    bank = build_channel_bank(cfg, g, mask)
    W, D = g["_channel_WD"]
    assert np.allclose(width[mask], np.minimum(W, g["cell_size"])[mask])
    assert np.allclose(bank[mask], D[mask])
    assert np.all(store <= g["cell_area"] + 1e-9)                  # slot never larger than the cell


def test_explicit_faccum_threshold_wins_over_min_area():
    from MRRpy.core.routing.surface import channel_threshold_cells
    g = _chain_grid()
    assert channel_threshold_cells(Config(CHANNEL_FACCUM_THRESHOLD=1500), g) == 1500.0
    thr = channel_threshold_cells(Config(), g)                  # 10 km², capped at 10 % of basin
    assert thr == pytest.approx(min(10.0, 0.1 * g["faccum_1d"].max() * g["cell_area"] / 1e6)
                                * 1e6 / g["cell_area"])
    bare = dict(faccum_1d=np.arange(1.0, 501.0))                 # no n_cells / cell_area
    assert channel_threshold_cells(Config(), bare) == 5.0        # legacy top 1 %


def test_reach_slope_outlet_uses_largest_donor():
    from MRRpy.core.routing.surface import reach_slope
    # cells 0 (small, steep) and 1 (large, flat) both drain to outlet 2
    g = dict(ds_idx=np.array([2, 2, -1]), dem_1d=np.array([20.0, 10.5, 10.0]),
             dist_1d=np.full(3, 100.0), cell_size=100.0, slope_1d=np.full(3, 0.5),
             faccum_1d=np.array([5.0, 500.0, 506.0]))
    S = reach_slope(g, 100.0, 1e-6)
    assert S[2] == pytest.approx(S[1]) and S[1] == pytest.approx(0.005)


def test_min_slope_zero_rejected_and_empty_mask_safe():
    from MRRpy.core.routing.surface import channel_dimensions
    with pytest.raises(Exception):
        Config(MIN_SLOPE=0.0).validate()
    g = _chain_grid()
    cfg = Config(CHANNEL_GEOMETRY="discharge", CHANNEL_QBF_M3S=50.0)
    W, D = channel_dimensions(cfg, g, np.zeros(g["n_cells"], bool))   # no channel cells
    assert np.all(np.isfinite(D))


def test_qbf_needs_three_annual_peaks():
    from MRRpy.core.routing.surface import qbf_from_annual_peaks
    with pytest.raises(ValueError):
        qbf_from_annual_peaks([100.0, 200.0])


# ── Muskingum–Cunge: baseflow start and mild-slope drainage ─────────────────
def test_muskingum_starts_at_baseflow(tmp_path):
    """With BASEFLOW_SPECIFIC_Q the MC rate state must start at the same steady
    flow the volume ledger is seeded with: outlet Q = q_b·A from the first step."""
    N, dx, S0, qb = 60, 50.0, 0.002, 10.0
    t, Q, mb, _ = _run(tmp_path, "muskingum", N, dx, S0, 2.0, channel=dict(B=5.0, D=1.0, n=0.035),
                       BASEFLOW_SPECIFIC_Q=qb)
    Q0 = qb * N * dx * dx / 1e6
    assert abs(Q[0] / Q0 - 1) < 0.02 and abs(Q[-1] / Q0 - 1) < 0.02
    assert abs(mb) < 1e-6


@pytest.mark.xfail(reason="audit finding 1: variable-parameter MC strands volume on mild slopes "
                          "at 90 m (x < 0); needs Todini (2007) MCT", strict=True)
def test_muskingum_pulse_drains_on_mild_slope(tmp_path):
    N, dx, S0 = 100, 90.0, 2e-4
    t, Q, mb, _ = _run(tmp_path, "muskingum", N, dx, S0, 48.0,
                       inflow=([0, 3 * 3600, 9 * 3600, 1e9], [0.0, 300.0, 0.0, 0.0]),
                       channel=dict(B=25.0, D=1.5, n=0.035))
    v_in = 0.5 * 300.0 * 9 * 3600
    v_out = np.sum(Q * np.diff(np.concatenate([[0.0], t])))
    assert v_out / v_in > 0.99


def test_implicit_storm_after_dry_spell_conserves_mass(tiny_basin, tmp_path):
    """Two 2-h storms 72 h apart.  During the dry spell the adaptive dt grows to
    the output interval, and the first wet step at that dt over-drained cells,
    which the solver floored at zero: +11.5 % water before step rejection."""
    dem_p, outlet = tiny_basin
    with rasterio.open(dem_p) as ds:
        cx, cy = ds.xy(ds.height // 2, ds.width // 2)
    g, r = str(tmp_path / "g.csv"), str(tmp_path / "r.csv")
    pd.DataFrame({"gauge_id": ["G1"], "name": ["G1"], "easting_m": [cx],
                  "northing_m": [cy]}).to_csv(g, index=False)
    t = np.arange(0, 80 * 3600 + 1, 1800)
    storm = (t < 2 * 3600) | ((t >= 74 * 3600) & (t < 76 * 3600))
    pd.DataFrame({"time_s": t, "G1": np.where(storm, 30.0, 0.0)}).to_csv(r, index=False)
    cfg = Config(DEM_PATH=dem_p, OUTPUT_POINT=outlet, OUTPUT_DIR=str(tmp_path / "out"),
                 TARGET_CRS_EPSG="EPSG:32645", DELINEATION_ENGINE="pysheds",
                 PRECIP_METHOD="thiessen", PRECIP_GAUGE_FILE=g, PRECIP_TIMESERIES_FILE=r,
                 RUNOFF_SOURCE="none", ROUTING_SCHEME="diffusive_implicit",
                 TOTAL_SIMULATION_TIME_HOURS=80.0, OUTPUT_INTERVAL_SECONDS=600,
                 CHANNEL_QBF_M3S=1.0)
    with contextlib.redirect_stdout(io.StringIO()):
        run_pipeline(cfg, on_log=lambda *_: None)
    mb = pd.read_csv(cfg.MASS_BALANCE_CSV).iloc[-1]
    assert abs(float(mb["rel_error"])) < 1e-6
