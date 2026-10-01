# -*- coding: utf-8 -*-
"""
surface.py — spatial parameter fields on the routing grid.

Manning's n (scalar / LULC / LCZ / raster overland source, with an
independently specified channel override — uniform, per-Strahler-order,
elevation-rule, callable, or a channel-only raster), land-cover lookups,
impervious fraction, and the confined-channel geometry (mask, width, storage
area).
"""

import numpy as np

from .terrain import compute_strahler_order
from ..io_utils import align_raster_to_dem
from ...utils.terrain_rules import apply_elevation_rule, _SANE_N_RANGE




# ---------------------------------------------------------------------------
# 8.  Spatially variable Manning's n
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Channel network definition shared by Manning's-n override and geometry
# ---------------------------------------------------------------------------

def channel_threshold_cells(cfg, grid_data):
    """
    Flow-accumulation threshold [cells] above which a cell is a channel.

    An explicit ``CHANNEL_FACCUM_THRESHOLD`` [cells] wins.  Otherwise
    ``CHANNEL_MIN_AREA_KM2`` (default 10 km²) → resolution- and basin-size-
    independent drainage-area threshold, capped at 10 % of the basin area so
    small catchments still get a channel.  ``None`` (or a grid without a cell
    area) → the legacy rule, the top 1 % of cells.
    """
    fa = grid_data['faccum_1d']
    fa = fa.get() if hasattr(fa, 'get') else np.asarray(fa)
    thr = getattr(cfg, 'CHANNEL_FACCUM_THRESHOLD', None)
    if thr is not None:
        return float(thr)
    n_cells = int(grid_data.get('n_cells', fa.size))
    min_area = getattr(cfg, 'CHANNEL_MIN_AREA_KM2', 10.0)
    cell_area = grid_data.get('cell_area')
    if min_area is None or cell_area is None:
        return float(max(1, n_cells // 100))
    cell_area = float(cell_area)
    basin_km2 = float(fa.max()) * cell_area / 1e6
    area = min(float(min_area), 0.1 * basin_km2)
    return area * 1e6 / cell_area


def channel_mask_1d(cfg, grid_data):
    fa = grid_data['faccum_1d']
    fa = fa.get() if hasattr(fa, 'get') else np.asarray(fa)
    return fa > channel_threshold_cells(cfg, grid_data)


# Bieger, Rathjens, Allen & Arnold (2015, JAWRA 51(4)) Table 3 — bankfull width
# W [m] and depth D [m] vs drainage area A [km²]: US national model (1,279 /
# 1,254 sites) and the eight physiographic divisions  (W = w_a·A^w_b, D = d_a·A^d_b).
BIEGER_2015 = {
    "bieger_usa": dict(w_a=2.70,  w_b=0.352, d_a=0.30, d_b=0.213),
    "bieger_lup": dict(w_a=4.15,  w_b=0.308, d_a=0.31, d_b=0.202),   # Laurentian Upland
    "bieger_apl": dict(w_a=2.22,  w_b=0.363, d_a=0.24, d_b=0.323),   # Atlantic Plain
    "bieger_ahi": dict(w_a=3.12,  w_b=0.415, d_a=0.26, d_b=0.287),   # Appalachian Highlands
    "bieger_ipl": dict(w_a=2.56,  w_b=0.351, d_a=0.38, d_b=0.191),   # Interior Plains
    "bieger_ihi": dict(w_a=23.23, w_b=0.121, d_a=0.27, d_b=0.267),   # Interior Highlands
    "bieger_rms": dict(w_a=1.24,  w_b=0.435, d_a=0.23, d_b=0.225),   # Rocky Mountain System
    "bieger_imp": dict(w_a=1.11,  w_b=0.415, d_a=0.07, d_b=0.329),   # Intermontane Plateaus
    "bieger_pms": dict(w_a=2.76,  w_b=0.399, d_a=0.23, d_b=0.294),   # Pacific Mountain System
}


def hydraulic_geometry_coeffs(cfg):
    """Resolve CHANNEL_HG (preset name or dict with w_a, w_b, d_a, d_b)."""
    hg = getattr(cfg, 'CHANNEL_HG', 'bieger_usa')
    if isinstance(hg, str):
        key = hg.lower()
        if key not in BIEGER_2015:
            raise ValueError(f"CHANNEL_HG preset {hg!r} unknown; use one of "
                             f"{sorted(BIEGER_2015)} or a dict with w_a, w_b, d_a, d_b")
        return dict(BIEGER_2015[key])
    c = dict(hg)
    missing = {'w_a', 'w_b', 'd_a', 'd_b'} - set(c)
    if missing:
        raise ValueError(f"CHANNEL_HG dict missing {sorted(missing)}")
    return {k: float(c[k]) for k in ('w_a', 'w_b', 'd_a', 'd_b')}


def hydraulic_geometry(cfg, area_km2):
    """Bankfull width and depth [m] from drainage area [km²]."""
    c = hydraulic_geometry_coeffs(cfg)
    A = np.maximum(np.asarray(area_km2, dtype=np.float64), 1e-6)
    return c['w_a'] * A ** c['w_b'], c['d_a'] * A ** c['d_b']


# Andreadis, Schumann & Pavelsky (2013, WRR 49, doi:10.1002/wrcr.20440) global
# bankfull hydraulic geometry vs bankfull (≈2-year) discharge Q [m³/s]:
#     W = 7.2·Q^0.50 ,   D = 0.27·Q^0.30        (W, D in m)
ANDREADIS_2013 = dict(w_a=7.2, w_b=0.50, d_a=0.27, d_b=0.30)

# Used when a (legacy, duck-typed) cfg has no CHANNEL_GEOMETRY — same as Config.
DEFAULT_CHANNEL_GEOMETRY = 'discharge'


def reach_slope(grid_data, reach_m, min_slope):
    """
    Bed slope averaged over ~``reach_m`` metres downstream of every cell
    (following the D8 path), floored at ``min_slope``.  Smooths the cell-to-cell
    noise of a DEM profile so channel depths do not jump with local slope.
    """
    ds = grid_data['ds_idx']
    ds = ds.get() if hasattr(ds, 'get') else np.asarray(ds)
    z = np.asarray(grid_data['dem_1d'], dtype=np.float64)
    dist = np.asarray(grid_data['dist_1d'], dtype=np.float64)
    k = max(1, int(np.ceil(float(reach_m) / float(grid_data['cell_size']))))
    idx = np.arange(len(z))
    L = np.zeros(len(z))
    for _ in range(k):
        nxt = ds[idx]
        ok = nxt >= 0
        L = L + np.where(ok, dist[idx], 0.0)
        idx = np.where(ok, nxt, idx)
    S = np.where(L > 0, (z - z[idx]) / np.maximum(L, 1e-9), 0.0)
    # Outlet / edge cells have no downstream reach of their own: use the reach
    # slope of their main (largest-drainage) upstream donor.  That donor's reach
    # also ends at the outlet, so near the outlet this is the slope over the
    # last few cells rather than a full reach_m.
    fa = grid_data['faccum_1d']
    fa = fa.get() if hasattr(fa, 'get') else np.asarray(fa, dtype=np.float64)
    src = np.where(ds >= 0)[0]
    order = src[np.lexsort((fa[src], ds[src]))]           # grouped by parent, faccum rising
    main_donor = np.full(len(z), -1)
    if order.size:
        par = ds[order]
        last = np.r_[par[1:] != par[:-1], True]           # last of each parent group = largest
        main_donor[par[last]] = order[last]
    no_reach = (L <= 0) & (main_donor >= 0)
    S[no_reach] = S[main_donor[no_reach]]
    still = L <= 0
    still &= ~no_reach
    S = np.where(still, np.asarray(grid_data['slope_1d'], dtype=np.float64), S)
    return np.maximum(S, float(min_slope))


def bankfull_depth_continuity(Q, width, slope, n):
    """
    Depth [m] at which a rectangular channel of width ``width`` carries ``Q``
    exactly full (Manning, R = A/P) — hydraulic continuity: the bank sits at the
    bankfull stage by construction.
    """
    from .hydraulics import normal_depth
    Q = np.asarray(Q, dtype=np.float64)
    h, _A = normal_depth(Q, np.asarray(slope, dtype=np.float64), n, np.asarray(width, dtype=np.float64),
                         np.ones(Q.shape, dtype=bool), np, iters=30)
    return np.asarray(h, dtype=np.float64)


def discharge_geometry(cfg, grid_data, chan_mask_1d):
    """
    Bankfull width/depth from bankfull discharge (``CHANNEL_GEOMETRY='discharge'``).

      Q_bf(cell) = from CHANNEL_QBF_M3S — automatic global estimate, your
                   number spread as (A/A_ref)^CHANNEL_QBF_AREA_EXP, or a
                   formula evaluated per cell (see ``qbf.py``)
      W          = 7.2·Q_bf^0.5  (Andreadis et al. 2013), capped at the cell size
      D          = the depth that carries Q_bf exactly bankfull with the cell's
                   channel n and a ~1 km reach slope (continuity), so channel
                   capacity is Q_bf by construction at every cell — a steep
                   gorge gets a shallower channel, a flat reach a deeper one.

    Returns (W, D, Q_bf, source label).
    """
    from .qbf import resolve_qbf
    cell_size = float(grid_data['cell_size'])
    cell_area = float(grid_data['cell_area'])
    fa = grid_data['faccum_1d']
    fa = fa.get() if hasattr(fa, 'get') else np.asarray(fa, dtype=np.float64)
    A = np.maximum(fa * cell_area / 1e6, 1e-6)
    Qbf, label = resolve_qbf(cfg, grid_data, A)

    c = ANDREADIS_2013
    W = np.minimum(c['w_a'] * Qbf ** c['w_b'], cell_size)

    # Floor the slope: a zero/near-zero MIN_SLOPE would make the continuity
    # depth blow up on flat reaches (D ∝ S^-0.3; S = 0 → D → ∞).
    s_floor = max(float(cfg.MIN_SLOPE), 1e-5)
    S = reach_slope(grid_data, getattr(cfg, 'CHANNEL_SLOPE_REACH_M', 1000.0), s_floor)
    n = grid_data.get('n_1d', getattr(cfg, 'MANNINGS_N_CHANNEL', None) or 0.035)
    n = n.get() if hasattr(n, 'get') else n
    D = np.zeros_like(W)
    m = np.asarray(chan_mask_1d)
    if m.any():
        n_m = np.asarray(n)[m] if np.ndim(n) else n
        D[m] = bankfull_depth_continuity(Qbf[m], W[m], S[m], n_m)
    D = np.maximum(D, float(getattr(cfg, 'CHANNEL_MIN_DEPTH_M', 0.1)))
    return W, D, Qbf, label


def monotone_bed_depth(D, grid_data, chan_mask_1d, min_slope):
    """
    Deepen channel cells so the sub-grid bed (DEM − D) never steps uphill along
    the network (the automated equivalent of GSSHA/WMS thalweg smoothing).
    Depths that vary with reach slope — continuity depth — can otherwise put a
    shallow channel just below a deep one and create a digital dam.  One pass in
    topological (upstream-first) order; only increases D.
    """
    ds = grid_data['ds_idx']
    ds = ds.get() if hasattr(ds, 'get') else np.asarray(ds)
    z = np.asarray(grid_data['dem_1d'], dtype=np.float64)
    dist = np.asarray(grid_data['dist_1d'], dtype=np.float64)
    m = np.asarray(chan_mask_1d)
    D = np.array(D, dtype=np.float64)
    bed = z - D
    added = 0.0
    for i in np.where(m & (ds >= 0))[0]:           # ascending index = upstream first
        j = ds[i]
        if not m[j]:
            continue
        allowed = bed[i] - float(min_slope) * dist[i]
        if bed[j] > allowed:
            added = max(added, bed[j] - allowed)
            D[j] += bed[j] - allowed
            bed[j] = allowed
    return D, added


def channel_dimensions(cfg, grid_data, chan_mask_1d):
    """Bankfull (W, D) per cell for 'area' or 'discharge' geometry (cached)."""
    cache = grid_data.get('_channel_WD')
    if cache is not None:
        return cache
    mode = str(getattr(cfg, 'CHANNEL_GEOMETRY', DEFAULT_CHANNEL_GEOMETRY)).lower()
    if mode == 'discharge':
        W, D, Qbf, label = discharge_geometry(cfg, grid_data, chan_mask_1d)
        m = np.asarray(chan_mask_1d)
        D, added = monotone_bed_depth(D, grid_data, chan_mask_1d, cfg.MIN_SLOPE)
        if added > 0:
            print(f"  Channel geometry| bed made monotone downstream (max deepening {added:.2f} m)")
        if m.any():
            print(f"  Channel geometry| Q_bf from {label}: "
                  f"[{Qbf[m].min():.1f}, {Qbf[m].max():.1f}] m³/s  "
                  f"outlet W={W[m][-1]:.1f} m D={D[m][-1]:.2f} m")
    else:
        fa = grid_data['faccum_1d']
        fa = fa.get() if hasattr(fa, 'get') else np.asarray(fa)
        W, D = hydraulic_geometry(cfg, fa * float(grid_data['cell_area']) / 1e6)
        W = np.minimum(W, float(grid_data['cell_size']))
    grid_data['_channel_WD'] = (W, D)
    return W, D


def qbf_from_annual_peaks(peaks_m3s):
    """Bankfull discharge estimate = the 2-year flood = median of annual maxima."""
    p = np.asarray([x for x in peaks_m3s if np.isfinite(x) and x > 0], dtype=np.float64)
    if p.size < 3:
        raise ValueError("need at least 3 annual maxima to estimate the 2-year flood")
    return float(np.median(p))


def fit_channel_to_rating(stage_m, q_m3s, slope, n, zero_flow_stage=None):
    """
    Fit a rectangular channel (width W, datum h0) to a stage–discharge rating
    with Manning's equation (known n, slope):  Q = (1/n)·W·h·R^(2/3)·√S,
    h = stage − h0, R = W·h/(W + 2h).  Returns dict(width_m, zero_flow_stage,
    rmse_m3s).  The bankfull depth then follows from the bankfull discharge
    (``bankfull_depth_continuity``) or from where the rating bends.
    """
    st = np.asarray(stage_m, dtype=np.float64)
    Q = np.asarray(q_m3s, dtype=np.float64)
    h0s = [float(zero_flow_stage)] if zero_flow_stage is not None else np.linspace(st.min() - 1.0, st.min(), 21)
    best = None
    for h0 in h0s:
        h = np.maximum(st - h0, 1e-6)
        for W in np.geomspace(2.0, 2000.0, 400):
            R = W * h / (W + 2 * h)
            Qm = W * h * R ** (2 / 3) * np.sqrt(slope) / n
            e = float(np.sqrt(np.mean((Qm - Q) ** 2)))
            if best is None or e < best[0]:
                best = (e, W, h0)
    return dict(width_m=best[1], zero_flow_stage=best[2], rmse_m3s=best[0])


def resolve_mannings_n(cfg, grid_data):
    """
    Build a per-cell Manning's n array from config.

    Supports four overland sources (``MANNINGS_N_SOURCE``):
      scalar  – uniform value from ``MANNINGS_N``
      lulc    – LULC class codes remapped via ``LULC_LOOKUP_CSV``
      lcz     – WUDAPT LCZ class codes remapped via ``LCZ_LOOKUP_CSV``
      raster  – pre-computed Manning's n GeoTIFF

    In all modes, cells whose flow accumulation exceeds a threshold are
    independently overridden via ``MANNINGS_N_CHANNEL`` (if not None), which
    accepts:
      None                          – off, channel cells keep the overland value
      float                         – uniform channel n
      dict{int order: n}            – per Strahler order (``compute_strahler_order``)
      dict{(min_elev, max_elev): n} – per elevation bin, ``[min, max)``, channel cells only
      list[(upper_elev, n), ...]    – ascending elevation breakpoints, first match wins
      callable(elev_array) -> n_array – custom rule over channel-cell elevations
      str (file path)               – channel-only Manning's-n raster (resampled)

    The elevation-bin/breakpoint/callable forms reuse
    ``MRRpy.utils.terrain_rules.apply_elevation_rule`` and are evaluated
    directly against ``grid_data['dem_1d']`` — no intermediate raster file is
    needed (contrast with ``mannings_n_from_dem``, which writes a whole-grid
    raster for use via ``MANNINGS_N_SOURCE='raster'``).

    Returns 1-D float64 array of shape ``(n_cells,)``.
    """
    import os
    import pandas as pd

    source     = getattr(cfg, 'MANNINGS_N_SOURCE', 'scalar').lower()
    n_fallback = float(cfg.MANNINGS_N)
    s_rows     = grid_data['s_rows']
    s_cols     = grid_data['s_cols']
    n_cells    = len(s_rows)

    # ── Source: scalar ────────────────────────────────────────────────────
    if source == 'scalar':
        n_1d = np.full(n_cells, n_fallback, dtype=np.float64)

    # ── Source: pre-computed raster ───────────────────────────────────────
    elif source == 'raster':
        path = getattr(cfg, 'MANNINGS_N_RASTER_PATH', None)
        if path is None or not os.path.isfile(path):
            raise FileNotFoundError(
                f"MANNINGS_N_SOURCE='raster' but MANNINGS_N_RASTER_PATH "
                f"not found: {path}"
            )
        dem_path = cfg.ROUTING_DEM_PATH
        n_2d = align_raster_to_dem(path, dem_path, resampling='bilinear')
        n_1d = n_2d[s_rows, s_cols].astype(np.float64)
        bad = (n_1d <= 0) | ~np.isfinite(n_1d)
        if bad.any():
            n_1d[bad] = n_fallback

    # ── Source: LULC class codes → lookup CSV ────────────────────────────
    elif source == 'lulc':
        lulc_path = getattr(cfg, 'MANNINGS_N_LULC_PATH', 'gee')
        dem_path  = cfg.ROUTING_DEM_PATH

        if str(lulc_path).lower() == 'gee':
            try:
                from ...gee.serves_gee import download_lulc_raster
            except ImportError:
                print("  [WARN] earthengine-api not installed; "
                      f"using scalar n={n_fallback}")
                return np.full(n_cells, n_fallback, dtype=np.float64)

            output_dir = getattr(cfg, 'OUTPUT_DIR', 'output/')
            cached = os.path.join(output_dir, 'lulc_mannings.tif')
            result = download_lulc_raster(
                dem_path=dem_path,
                watershed_geojson_path=getattr(
                    cfg, 'WATERSHED_GEOJSON', 'output/watershed.geojson'),
                output_path=cached,
                project=getattr(cfg, 'GEE_PROJECT', None),
            )
            if result is None:
                print("  [WARN] GEE LULC download failed; "
                      f"using scalar n={n_fallback}")
                return np.full(n_cells, n_fallback, dtype=np.float64)
            lulc_2d = align_raster_to_dem(cached, dem_path,
                                          resampling='nearest')
        else:
            if not os.path.isfile(lulc_path):
                raise FileNotFoundError(
                    f"MANNINGS_N_LULC_PATH not found: {lulc_path}"
                )
            lulc_2d = align_raster_to_dem(lulc_path, dem_path,
                                          resampling='nearest')

        csv_path = getattr(cfg, 'LULC_LOOKUP_CSV', 'lulc_lookup.csv')
        lut = pd.read_csv(csv_path)
        code_to_n = dict(zip(lut['class_code'].astype(int),
                             lut['mannings_n'].astype(float)))
        lulc_1d = lulc_2d[s_rows, s_cols]
        n_1d = np.full(n_cells, n_fallback, dtype=np.float64)
        for code, nval in code_to_n.items():
            n_1d[lulc_1d == code] = nval

    # ── Source: WUDAPT Local Climate Zones ───────────────────────────────
    elif source == 'lcz':
        try:
            from ...gee.serves_gee import download_lcz_raster
        except ImportError:
            print("  [WARN] earthengine-api not installed; "
                  f"using scalar n={n_fallback}")
            return np.full(n_cells, n_fallback, dtype=np.float64)

        output_dir = getattr(cfg, 'OUTPUT_DIR', 'output/')
        cached = os.path.join(output_dir, 'lulc_mannings_lcz.tif')
        dem_path = cfg.ROUTING_DEM_PATH
        result = download_lcz_raster(
            dem_path=dem_path,
            watershed_geojson_path=getattr(
                cfg, 'WATERSHED_GEOJSON', 'output/watershed.geojson'),
            output_path=cached,
            project=getattr(cfg, 'GEE_PROJECT', None),
        )
        if result is None:
            print("  [WARN] GEE LCZ download failed; "
                  f"using scalar n={n_fallback}")
            return np.full(n_cells, n_fallback, dtype=np.float64)

        lcz_2d = align_raster_to_dem(cached, dem_path, resampling='nearest')
        csv_path = getattr(cfg, 'LCZ_LOOKUP_CSV', 'lcz_lookup.csv')
        lut = pd.read_csv(csv_path)
        code_to_n = dict(zip(lut['class_code'].astype(int),
                             lut['mannings_n'].astype(float)))
        lulc_1d = lcz_2d[s_rows, s_cols]
        n_1d = np.full(n_cells, n_fallback, dtype=np.float64)
        for code, nval in code_to_n.items():
            n_1d[lulc_1d == code] = nval

    else:
        raise ValueError(f"Unknown MANNINGS_N_SOURCE: '{source}'")

    # ── Channel override (all modes) ─────────────────────────────────────
    # Independent of the overland source above: None|float|dict{order:n}
    # (unchanged, backward compatible) plus dict{(lo,hi):n} / list of
    # (upper_elev, n) / callable(elev)->n / str raster path (new — let
    # channel cells use a different rule than overland, e.g. LULC overland +
    # elevation-based channel roughness).
    # Land-cover (pre-override) n: used for above-bank floodplain flow on
    # channel cells by the sub-grid channel section.
    grid_data['n_overland_1d'] = n_1d.copy()
    n_channel_cfg = getattr(cfg, 'MANNINGS_N_CHANNEL', None)
    if n_channel_cfg is not None:
        threshold = channel_threshold_cells(cfg, grid_data)
        channel_mask = channel_mask_1d(cfg, grid_data)

        def _fill_and_assign(n_channel_1d, mode_label):
            bad = ~np.isfinite(n_channel_1d)
            if bad.any():
                ok = ~bad
                fallback = float(n_channel_1d[ok].mean()) if ok.any() else n_fallback
                n_channel_1d[bad] = fallback
            lo_ok, hi_ok = _SANE_N_RANGE
            out_of_range = (n_channel_1d < lo_ok) | (n_channel_1d > hi_ok)
            if out_of_range.any():
                print(f"  [WARN] Manning's n   |  {int(out_of_range.sum())} "
                      f"channel cell(s) have n outside the typical "
                      f"[{lo_ok}, {hi_ok}] range — check MANNINGS_N_CHANNEL.")
            n_1d[channel_mask] = n_channel_1d
            print(f"  Manning's n   |  channel cells: "
                  f"{int(channel_mask.sum()):,} / {n_cells:,}  "
                  f"(threshold={threshold}, mode={mode_label})")

        if isinstance(n_channel_cfg, dict):
            keys = list(n_channel_cfg.keys())
            is_strahler = bool(keys) and all(
                isinstance(k, int) and not isinstance(k, bool) for k in keys)
            is_elev_bins = bool(keys) and all(
                isinstance(k, tuple) and len(k) == 2 for k in keys)

            if is_strahler:
                ds_idx = grid_data['ds_idx']
                ds_np = ds_idx.get() if hasattr(ds_idx, 'get') else np.asarray(
                    ds_idx)
                strahler = compute_strahler_order(ds_np, n_cells)
                max_order = max(n_channel_cfg.keys())
                for ci in np.where(channel_mask)[0]:
                    so = min(int(strahler[ci]), max_order)
                    n_1d[ci] = n_channel_cfg.get(so, n_channel_cfg[max_order])
                order_dist = {o: int((strahler[channel_mask] == o).sum())
                              for o in sorted(set(strahler[channel_mask]))}
                print(f"  Manning's n   |  channel cells: "
                      f"{int(channel_mask.sum()):,} / {n_cells:,}  "
                      f"(threshold={threshold}, mode=strahler-order)")
                print(f"  Manning's n   |  Strahler order distribution: "
                      f"{order_dist}")
            elif is_elev_bins:
                dem_1d = grid_data['dem_1d']
                elev = dem_1d.get() if hasattr(dem_1d, 'get') else np.asarray(dem_1d)
                n_channel_1d = apply_elevation_rule(elev[channel_mask], n_channel_cfg)
                _fill_and_assign(n_channel_1d, 'elevation-bins')
            else:
                raise ValueError(
                    "MANNINGS_N_CHANNEL dict keys must be all int (Strahler "
                    "order, e.g. {1: 0.10, 2: 0.06}) or all 2-tuples "
                    "(elevation bins, e.g. {(0, 1500): 0.03, (1500, 3000): "
                    f"0.08}}) — got mixed/unsupported key types: "
                    f"{sorted({type(k).__name__ for k in keys})}"
                )

        elif isinstance(n_channel_cfg, (list, tuple)):
            dem_1d = grid_data['dem_1d']
            elev = dem_1d.get() if hasattr(dem_1d, 'get') else np.asarray(dem_1d)
            n_channel_1d = apply_elevation_rule(elev[channel_mask], n_channel_cfg)
            _fill_and_assign(n_channel_1d, 'elevation-breakpoints')

        elif isinstance(n_channel_cfg, str):
            dem_path = cfg.ROUTING_DEM_PATH
            n_2d = align_raster_to_dem(n_channel_cfg, dem_path, resampling='bilinear')
            n_channel_1d = n_2d[s_rows[channel_mask], s_cols[channel_mask]].astype(np.float64)
            bad = (n_channel_1d <= 0) | ~np.isfinite(n_channel_1d)
            if bad.any():
                n_channel_1d[bad] = n_fallback
            n_1d[channel_mask] = n_channel_1d
            print(f"  Manning's n   |  channel raster: {n_channel_cfg}")
            print(f"  Manning's n   |  channel cells: "
                  f"{int(channel_mask.sum()):,} / {n_cells:,}  "
                  f"(threshold={threshold}, mode=channel-raster)")

        elif callable(n_channel_cfg):
            dem_1d = grid_data['dem_1d']
            elev = dem_1d.get() if hasattr(dem_1d, 'get') else np.asarray(dem_1d)
            n_channel_1d = np.asarray(
                n_channel_cfg(elev[channel_mask]), dtype=np.float64)
            _fill_and_assign(n_channel_1d, 'callable')

        else:
            n_1d[channel_mask] = float(n_channel_cfg)
            print(f"  Manning's n   |  channel cells: "
                  f"{int(channel_mask.sum()):,} / {n_cells:,}  "
                  f"(threshold={threshold}, mode=uniform)")

    print(f"  Manning's n   |  source={source}"
          f"  range=[{n_1d.min():.4f}, {n_1d.max():.4f}]"
          f"  mean={n_1d.mean():.4f}")
    return n_1d


# ---------------------------------------------------------------------------
# 8b. Per-cell land-cover field lookup (impervious fraction, root depth, …)
# ---------------------------------------------------------------------------

def _lulc_class_1d(cfg, grid_data, source):
    """
    Per-cell land-cover class codes from the cached LCZ/LULC raster.

    Reuses the SAME cache file as ``resolve_mannings_n``
    (``lulc_mannings_lcz.tif`` / ``lulc_mannings.tif``) so no extra GEE download
    happens when Manning's n already pulled the layer.

    Returns
    -------
    (class_1d, lookup_csv_path) : (n_cells,) int-ish array + CSV path,
        or (None, None) when the raster is unavailable.
    """
    import os

    s_rows = grid_data['s_rows']
    s_cols = grid_data['s_cols']
    dem_path   = cfg.ROUTING_DEM_PATH
    output_dir = getattr(cfg, 'OUTPUT_DIR', 'output/')
    geojson    = getattr(cfg, 'WATERSHED_GEOJSON', 'output/watershed.geojson')
    project    = getattr(cfg, 'GEE_PROJECT', None)

    if source == 'lcz':
        try:
            from ...gee.serves_gee import download_lcz_raster
        except ImportError:
            return None, None
        cached = os.path.join(output_dir, 'lulc_mannings_lcz.tif')
        result = download_lcz_raster(dem_path=dem_path,
                                     watershed_geojson_path=geojson,
                                     output_path=cached, project=project)
        csv_path = getattr(cfg, 'LCZ_LOOKUP_CSV', 'lcz_lookup.csv')
    else:
        try:
            from ...gee.serves_gee import download_lulc_raster
        except ImportError:
            return None, None
        cached = os.path.join(output_dir, 'lulc_mannings.tif')
        result = download_lulc_raster(dem_path=dem_path,
                                      watershed_geojson_path=geojson,
                                      output_path=cached, project=project)
        csv_path = getattr(cfg, 'LULC_LOOKUP_CSV', 'lulc_lookup.csv')

    if result is None:
        return None, None

    arr2d = align_raster_to_dem(cached, dem_path, resampling='nearest')
    _to_np = lambda a: a.get() if hasattr(a, 'get') else np.asarray(a)
    return arr2d[_to_np(s_rows), _to_np(s_cols)], csv_path


def resolve_lulc_field(cfg, grid_data, column, default, source):
    """
    Build a per-cell field by remapping land-cover class codes through *column*
    of the LCZ/LULC lookup CSV.  Used for impervious fraction and root-zone
    depth.  Cells with an unmapped class (or when the raster/column is missing)
    get *default*.  Returns (n_cells,) float64.
    """
    import pandas as pd

    n_cells = len(grid_data['s_rows'])
    class_1d, csv_path = _lulc_class_1d(cfg, grid_data, source)
    if class_1d is None:
        print(f"  [WARN] {source} raster unavailable; "
              f"'{column}' → {default} everywhere")
        return np.full(n_cells, float(default), dtype=np.float64)

    lut = pd.read_csv(csv_path)
    if column not in lut.columns:
        print(f"  [WARN] column '{column}' missing from {csv_path}; "
              f"using {default} everywhere")
        return np.full(n_cells, float(default), dtype=np.float64)

    code_to_v = dict(zip(lut['class_code'].astype(int),
                         lut[column].astype(float)))
    out = np.full(n_cells, float(default), dtype=np.float64)
    for code, v in code_to_v.items():
        out[class_1d == code] = v
    return out


def resolve_impervious_fraction(cfg, grid_data):
    """
    Per-cell impervious fraction Imp ∈ [0,1] from ``IMPERVIOUS_SOURCE``.

      'lcz' / 'lulc' → impervious_fraction column of the matching lookup CSV
      'raster'       → continuous GeoTIFF at IMPERVIOUS_RASTER_PATH (bilinear)
      'none'         → zeros

    Returns (n_cells,) float64, clipped to [0,1].
    """
    import os

    source  = getattr(cfg, 'IMPERVIOUS_SOURCE', 'none').lower()
    n_cells = len(grid_data['s_rows'])
    s_rows  = grid_data['s_rows']
    s_cols  = grid_data['s_cols']

    if source == 'none':
        return np.zeros(n_cells, dtype=np.float64)

    if source == 'raster':
        path = getattr(cfg, 'IMPERVIOUS_RASTER_PATH', None)
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(
                f"IMPERVIOUS_SOURCE='raster' but IMPERVIOUS_RASTER_PATH "
                f"not found: {path}"
            )
        arr2d = align_raster_to_dem(path, cfg.ROUTING_DEM_PATH,
                                    resampling='bilinear')
        _to_np = lambda a: a.get() if hasattr(a, 'get') else np.asarray(a)
        imp = arr2d[_to_np(s_rows), _to_np(s_cols)].astype(np.float64)
        imp[~np.isfinite(imp)] = 0.0
    elif source in ('lcz', 'lulc'):
        imp = resolve_lulc_field(cfg, grid_data, 'impervious_fraction',
                                 0.0, source)
    else:
        raise ValueError(f"Unknown IMPERVIOUS_SOURCE: '{source}'")

    imp = np.clip(imp, 0.0, 1.0)
    print(f"  Impervious    |  source={source}"
          f"  range=[{imp.min():.2f}, {imp.max():.2f}]"
          f"  mean={imp.mean():.2f}  (>0: {int((imp > 0).sum()):,}/{n_cells:,} cells)")
    return imp


# ---------------------------------------------------------------------------
# 10.  Channel (river) cross-section geometry
# ---------------------------------------------------------------------------

def build_channel_geometry(cfg, grid_data):
    """
    Per-cell channel geometry for ``CHANNEL_ROUTING`` (Workstream 1).

    Returns three NumPy arrays of shape ``(n_cells,)`` in topological order:

      chan_mask_1d  : bool   – True on channel cells (faccum > threshold), the SAME
                               cells the Manning's-n channel override uses.
      width_1d      : float  – flow width [m]: ``cell_size`` on overland cells,
                               a Strahler-order width (``CHANNEL_WIDTH_BY_ORDER``)
                               on channel cells.
      store_area_1d : float  – depth-from-volume denominator [m²]: ``cell_area`` on
                               overland cells (depth = V/cell_area, unchanged), and
                               ``width · flow-length`` on channel cells so depth is
                               the channel-reach depth V/(B·L).

    With ``CHANNEL_ROUTING`` False (or no channel cells / empty width table) every
    value reduces to the wide-sheet defaults (width = cell_size, store_area =
    cell_area), so routing is bit-for-bit unchanged.

    Reuses the channel threshold convention from ``resolve_mannings_n`` and
    ``compute_strahler_order`` for the network order — no new network analysis.
    """
    n_cells   = int(grid_data['n_cells'])
    cell_size = float(grid_data['cell_size'])
    cell_area = float(grid_data['cell_area'])
    dist_1d   = np.asarray(grid_data['dist_1d'], dtype=np.float64)

    width_1d      = np.full(n_cells, cell_size, dtype=np.float64)
    store_area_1d = np.full(n_cells, cell_area, dtype=np.float64)
    chan_mask_1d  = np.zeros(n_cells, dtype=bool)

    if not getattr(cfg, 'CHANNEL_ROUTING', True):
        return chan_mask_1d, width_1d, store_area_1d

    # Channel mask: shared with the Manning's-n channel override.
    fa = grid_data['faccum_1d']
    fa = fa.get() if hasattr(fa, 'get') else np.asarray(fa)
    threshold = channel_threshold_cells(cfg, grid_data)
    chan_mask_1d = fa > threshold

    width_by_order = getattr(cfg, 'CHANNEL_WIDTH_BY_ORDER', None)
    if str(getattr(cfg, 'CHANNEL_GEOMETRY', DEFAULT_CHANNEL_GEOMETRY)).lower() in ('area', 'discharge'):
        # Bankfull hydraulic geometry vs drainage area or bankfull discharge.
        W, _D = channel_dimensions(cfg, grid_data, chan_mask_1d)
        width_1d = np.where(chan_mask_1d, np.minimum(W, cell_size), width_1d)
    elif not width_by_order:
        print("  [WARN] CHANNEL_ROUTING on but CHANNEL_WIDTH_BY_ORDER empty; "
              "channel width defaults to cell_size (no confinement).")
    else:
        ds_idx = grid_data['ds_idx']
        ds_np  = ds_idx.get() if hasattr(ds_idx, 'get') else np.asarray(ds_idx)
        order  = compute_strahler_order(ds_np, n_cells)
        max_o  = max(int(o) for o in width_by_order.keys())
        # Strahler-order → width LUT (orders above max reuse max; unspecified
        # intermediate orders keep cell_size = no confinement).
        width_lut = np.full(max_o + 1, cell_size, dtype=np.float64)
        for o, w in width_by_order.items():
            if 0 <= int(o) <= max_o:
                width_lut[int(o)] = float(w)
        order_clip = np.minimum(order, max_o).astype(np.intp)
        width_1d   = np.where(chan_mask_1d, width_lut[order_clip], width_1d)

    # Channel storage footprint = width × channel length through the cell, never
    # more than the cell itself (a diagonal cell with W at the cell-size cap would
    # otherwise store √2× the cell area in-bank and LOSE storage going overbank).
    store_area_1d = np.where(chan_mask_1d, np.minimum(width_1d * dist_1d, cell_area), store_area_1d)

    n_chan = int(chan_mask_1d.sum())
    if n_chan:
        wch = width_1d[chan_mask_1d]
        print(f"  Channel routing|  {n_chan:,}/{n_cells:,} cells "
              f"(> {threshold * cell_area / 1e6:.2f} km²)  "
              f"width=[{wch.min():.1f}, {wch.max():.1f}] m  "
              f"({getattr(cfg, 'CHANNEL_GEOMETRY', DEFAULT_CHANNEL_GEOMETRY)})")
    else:
        print(f"  Channel routing|  no cells exceed faccum threshold "
              f"{threshold:g}; routing as wide sheet everywhere.")
    return chan_mask_1d, width_1d, store_area_1d


def build_channel_bank(cfg, grid_data, chan_mask_1d):
    """
    Bankfull depth D [m] per cell for the sub-grid incised channel (0 on
    overland cells).  ``CHANNEL_GEOMETRY='area'`` → hydraulic geometry
    (``CHANNEL_HG``); ``'order'`` → ``CHANNEL_DEPTH_BY_ORDER`` by Strahler order.
    """
    n_cells = int(grid_data['n_cells'])
    bank = np.zeros(n_cells, dtype=np.float64)
    if not np.any(chan_mask_1d):
        return bank
    fa = grid_data['faccum_1d']
    fa = fa.get() if hasattr(fa, 'get') else np.asarray(fa)
    mode = str(getattr(cfg, 'CHANNEL_GEOMETRY', DEFAULT_CHANNEL_GEOMETRY)).lower()
    if mode in ('area', 'discharge'):
        _W, D = channel_dimensions(cfg, grid_data, chan_mask_1d)
        bank = np.where(chan_mask_1d, D, 0.0)
        label = ("discharge-based geometry" if mode == 'discharge'
                 else f"hydraulic geometry ({getattr(cfg, 'CHANNEL_HG', 'bieger_usa')})")
    else:
        table = getattr(cfg, 'CHANNEL_DEPTH_BY_ORDER', None) or {}
        if not table:
            return bank
        ds_idx = grid_data['ds_idx']
        ds_np = ds_idx.get() if hasattr(ds_idx, 'get') else np.asarray(ds_idx)
        order = compute_strahler_order(ds_np, n_cells)
        keys = {int(k): float(v) for k, v in table.items()}
        max_o = max(keys)
        lut = np.zeros(max_o + 1, dtype=np.float64)
        last = 0.0
        for o in range(max_o + 1):             # gaps reuse the previous order's depth
            last = keys.get(o, last)
            lut[o] = last
        bank = np.where(chan_mask_1d, lut[np.minimum(order, max_o).astype(np.intp)], 0.0)
        label = "Strahler-order table"
    b = bank[chan_mask_1d]
    print(f"  Sub-grid channel| bankfull depth D=[{b.min():.2f}, {b.max():.2f}] m, "
          f"bed = DEM − D on {int(np.count_nonzero(chan_mask_1d)):,} cells ({label})")
    return bank
