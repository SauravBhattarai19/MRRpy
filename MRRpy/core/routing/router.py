# -*- coding: utf-8 -*-
"""
router.py
=========
Explicit, grid-based kinematic / diffusive wave routing model.

Algorithm (per time step)
-------------------------
1. Build a rainfall 2-D array for the current time.
2. Iterate over ALL active cells in topological (upstream-first) order.
3. For each cell i:
      a. Compute rainfall volume added this step.
      b. Add Q_in arriving from upstream cells (accumulated in inflow buffer).
      c. Compute depth from stored volume.
      d. Compute slope-driven Manning velocity → Q_out.
      e. Solve continuity: new_volume = old_volume + rain_vol + Q_in*dt - Q_out*dt
      f. Pass Q_out to the downstream neighbour's inflow buffer.
4. Record Q at the outlet cell → hydrograph.
5. Write hydrograph to CSV.

All physical parameters and paths come from the cfg object passed in
(vsa_opm.config.OpmConfig or any object exposing the same attributes).
"""

import time

import numpy as np

from ...utils import gpu_utils
from . import terrain, surface, hydraulics
from .schemes import get_scheme
from .reporting import (
    save_hydrograph,
    write_partition_series,
    append_mass_balance_csv,
)




# ─────────────────────────────────────────────────────────────────────────────
# Grid initialisation
# ─────────────────────────────────────────────────────────────────────────────

def initialise_grid(cfg):
    """
    Load rasters, compute slopes, build topological order and downstream map.

    Returns a dict ('grid_data') with every array the time loop needs.
    """
    print("=" * 60)
    print("KINEMATIC WAVE ROUTER  –  Grid Initialisation")
    print("=" * 60)

    # ── Backend selection ─────────────────────────────────────────────────────
    # Select routing/precip/runoff modules before any computation so the
    # vectorized GPU variants of compute_slope_grid and build_downstream_map
    # are used when BACKEND='gpu'.
    _backend = getattr(cfg, 'BACKEND', 'cpu').lower()
    _use_gpu  = (_backend == 'gpu') and gpu_utils.cupy_available()

    # The semi-implicit diffusion wave solves a tree linear system on the CPU
    # (core/linear-algebra bound, no GPU kernel); force CPU so all state arrays
    # stay on the host for the solver.
    if getattr(cfg, 'ROUTING_SCHEME', 'kinematic').lower() == 'diffusive_implicit' and _use_gpu:
        print("  [WARNING] ROUTING_SCHEME='diffusive_implicit' runs on the CPU "
              "(implicit tree solve) — ignoring BACKEND='gpu'.")
        _use_gpu = False

    if _use_gpu:
        import cupy as cp
        from . import gpu as _ru
        from ..precip.gpu import PrecipEngineGPU  as _PrecipEngine
        from ..runoff.gpu  import RunoffEngineGPU  as _RunoffEngine
        xp = cp
        print("  Backend: GPU (CuPy)")
    else:
        _ru = terrain   # CPU terrain kernels
        from ..precip import PrecipEngine as _PrecipEngine
        from ..runoff  import RunoffEngine as _RunoffEngine
        xp = np
        if _backend == 'gpu':
            print("  [WARNING] BACKEND='gpu' requested but CuPy is unavailable "
                  "or no CUDA device found — falling back to CPU.")
        else:
            print("  Backend: CPU (NumPy)")

    # --- Load rasters ---
    dem, fdir, faccum, ws_mask, transform, nodata_dem, cell_size = _ru.load_rasters(cfg)
    nrows, ncols = dem.shape

    # --- Slope grid ---
    print("  Computing slope grid...")
    slope_2d = _ru.compute_slope_grid(
        dem, fdir, ws_mask, cell_size, cfg.MIN_SLOPE, nodata_dem
    )

    # --- Topological order ---
    print("  Building topological order...")
    s_rows, s_cols, outlet_rc = _ru.topological_order(faccum, fdir, ws_mask)
    n_cells = len(s_rows)
    print(f"  Total active cells: {n_cells:,}")

    # --- Downstream neighbour map ---
    print("  Building downstream neighbour map...")
    ds_idx = _ru.build_downstream_map(
        s_rows, s_cols, fdir, ws_mask, nrows, ncols
    )

    # --- Extract 1-D arrays in topological order (fast indexing) ---
    slope_1d  = slope_2d[s_rows, s_cols]       # slope at each active cell [m/m]
    _slope_cap = getattr(cfg, 'MANNING_SLOPE_CAP', None)
    if _slope_cap is not None:                  # bound unphysical steep-cell celerity
        _n_capped = int((slope_1d > float(_slope_cap)).sum())
        slope_1d = np.minimum(slope_1d, float(_slope_cap))
        print(f"  Slope cap      |  S <= {float(_slope_cap):.3f} m/m  "
              f"({_n_capped:,}/{len(slope_1d):,} cells capped)")
    faccum_1d = faccum[s_rows, s_cols]         # flow accumulation [cell count] for VSA/OPM
    cell_area = cell_size ** 2                  # [m²]  (same for every cell)

    # Static arrays for the diffusive-wave scheme (water-surface slope needs bed
    # elevation and the true flow-path length; harmless to build even when kinematic).
    dem_1d  = dem[s_rows, s_cols].astype(np.float64)        # bed elevation [m]
    fdir_1d = fdir[s_rows, s_cols]
    dist_1d = cell_size * np.where(                          # flow-path length to downstream [m]
        np.isin(fdir_1d, list(terrain.D8_DIAGONAL)), np.sqrt(2.0), 1.0
    ).astype(np.float64)

    # --- Index of outlet in the sorted list ---
    outlet_pos = n_cells - 1  # last element (highest accumulation = downstream-most)

    print("  Initialisation complete.\n")

    grid_data = {
        "dem"        : dem,
        "fdir"       : fdir,
        "ws_mask"    : ws_mask,
        "s_rows"     : s_rows,        # 1-D topologically sorted row indices
        "s_cols"     : s_cols,        # 1-D topologically sorted col indices
        "slope_1d"   : slope_1d,      # [m/m]
        "dem_1d"     : dem_1d,        # [m] bed elevation in topo order (diffusive wave)
        "dist_1d"    : dist_1d,       # [m] flow-path length to downstream (diffusive wave)
        "faccum_1d"  : faccum_1d,     # [cell count] flow accumulation in topo order
        "ds_idx"     : ds_idx,        # downstream position index (-1 = outlet/off-mask)
        "n_cells"    : n_cells,
        "nrows"      : nrows,
        "ncols"      : ncols,
        "cell_size"  : cell_size,
        "cell_area"  : cell_area,
        "outlet_pos" : outlet_pos,
        "outlet_rc"  : outlet_rc,
        "transform"  : transform,
    }

    # ── Resolve spatially variable Manning's n ──────────────────────────────
    print("  Resolving Manning's n...")
    n_1d = surface.resolve_mannings_n(cfg, grid_data)
    grid_data["n_1d"] = n_1d

    # ── Channel (river) cross-section geometry ──────────────────────────────
    # Wide-sheet defaults (cell_size / cell_area) unless CHANNEL_ROUTING is on, in
    # which case high-faccum channel cells get a confined rectangular section.
    chan_mask_1d, width_1d, store_area_1d = surface.build_channel_geometry(cfg, grid_data)
    grid_data["chan_mask_1d"]  = chan_mask_1d
    grid_data["width_1d"]      = width_1d
    grid_data["store_area_1d"] = store_area_1d

    # ── Transfer hot arrays to GPU (must happen BEFORE engine construction) ───
    # Engines read grid_data['faccum_1d'] and grid_data['slope_1d'] during
    # __init__; they must already be CuPy arrays so engine state is on GPU.
    if _use_gpu:
        _dtype    = gpu_utils.get_dtype(cfg)
        slope_1d  = gpu_utils.to_device(slope_1d.astype(_dtype),  xp)
        ds_idx    = gpu_utils.to_device(ds_idx,                    xp)
        faccum_1d = gpu_utils.to_device(faccum_1d.astype(_dtype),  xp)
        n_1d      = gpu_utils.to_device(n_1d.astype(_dtype),       xp)
        dem_1d    = gpu_utils.to_device(dem_1d.astype(_dtype),     xp)
        dist_1d   = gpu_utils.to_device(dist_1d.astype(_dtype),    xp)
        width_1d      = gpu_utils.to_device(width_1d.astype(_dtype),      xp)
        store_area_1d = gpu_utils.to_device(store_area_1d.astype(_dtype), xp)
        chan_mask_1d  = gpu_utils.to_device(chan_mask_1d,                 xp)
        grid_data["slope_1d"]  = slope_1d
        grid_data["ds_idx"]    = ds_idx
        grid_data["faccum_1d"] = faccum_1d
        grid_data["n_1d"]      = n_1d
        grid_data["dem_1d"]    = dem_1d
        grid_data["dist_1d"]   = dist_1d
        grid_data["width_1d"]      = width_1d
        grid_data["store_area_1d"] = store_area_1d
        grid_data["chan_mask_1d"]  = chan_mask_1d

    grid_data["xp"] = xp   # carried into run_time_loop

    # Build precipitation engine (uses grid_data for spatial weight construction)
    print("  Building precipitation engine...")
    grid_data["precip_engine"] = _PrecipEngine(cfg, grid_data)

    # Expose per-cell zone assignment for per-polygon VSA sandbox
    grid_data["cell_polygon"] = grid_data["precip_engine"].cell_polygon

    # Build runoff generation engine (optional; None when RUNOFF_SOURCE='none')
    _rsrc = getattr(cfg, 'RUNOFF_SOURCE', 'none').lower()
    if _rsrc != 'none':
        print("  Building runoff generation engine...")
        grid_data["runoff_engine"] = _RunoffEngine(cfg, grid_data)
    else:
        grid_data["runoff_engine"] = None

    # Build upstream inflow boundary condition(s) (optional; None when disabled)
    if getattr(cfg, 'ROUTING_INFLOW_BC', None):
        from .boundary import InflowBoundary
        _bc = InflowBoundary(cfg, grid_data)
        grid_data["inflow_bc"] = _bc if _bc.active else None
    else:
        grid_data["inflow_bc"] = None

    return grid_data


# ─────────────────────────────────────────────────────────────────────────────
# Time loop
# ─────────────────────────────────────────────────────────────────────────────

def run_time_loop(grid_data, cfg):
    """
    Core explicit kinematic-wave routing loop.

    Continuity per cell per step:
        V_new = V_old + (rain [m/s] * cell_area * dt)   <- rain input
                      + Q_in  * dt                       <- upstream inflow
                      - Q_out * dt                       <- Manning outflow
        V_new = max(V_new, 0)                            <- no negative storage
        depth = V_new / cell_area

    Returns
    -------
    hydrograph : list of (time_s, Q_out_m3s) tuples
    """
    n         = grid_data.get("n_1d", cfg.MANNINGS_N)
    cell_area = grid_data["cell_area"]
    dx        = grid_data["cell_size"]
    T         = cfg.TOTAL_SIMULATION_TIME_HOURS * 3600.0

    # Adaptive CFL parameters
    adaptive      = getattr(cfg, 'ADAPTIVE_TIMESTEP', True)
    cfl_target    = float(getattr(cfg, 'CFL_TARGET', 0.8))
    _cfl_dt_max   = getattr(cfg, 'CFL_DT_MAX', None)
    _out_interval = float(getattr(cfg, 'OUTPUT_INTERVAL_SECONDS', None)
                          or cfg.TIME_STEP_SECONDS)
    cfl_dt_max    = float(_cfl_dt_max) if _cfl_dt_max is not None else _out_interval
    cfl_dt_min    = float(getattr(cfg, 'CFL_DT_MIN', 0.01))
    cfl_dt_grow   = float(getattr(cfg, 'CFL_DT_GROW', 1.5))
    dt            = cfg.TIME_STEP_SECONDS   # legacy dt / adaptive seed
    n_steps       = int(T / dt)             # reference value for legacy-mode header

    s_rows         = grid_data["s_rows"]
    s_cols         = grid_data["s_cols"]
    slope_1d       = grid_data["slope_1d"]
    dem_1d         = grid_data["dem_1d"]
    dist_1d        = grid_data["dist_1d"]
    width_1d       = grid_data["width_1d"]        # flow width [m] (channel cross-section)
    store_area_1d  = grid_data["store_area_1d"]   # depth-from-volume footprint [m²]
    chan_mask_1d   = grid_data["chan_mask_1d"]    # True on confined channel cells
    ds_idx         = grid_data["ds_idx"]
    n_cells        = grid_data["n_cells"]
    outlet_pos     = grid_data["outlet_pos"]
    ws_mask        = grid_data["ws_mask"]
    precip_engine  = grid_data["precip_engine"]
    runoff_engine  = grid_data.get("runoff_engine")   # None when RUNOFF_SOURCE='none'
    inflow_bc      = grid_data.get("inflow_bc")       # None when no upstream BC
    _flux_limiter  = bool(getattr(cfg, "FLUX_LIMITER", True))  # kinematic/diffusive Q<=V/dt clip

    # ── Optional rain/snow elevation partition ───────────────────────────────
    # Scale precip per cell by a rain fraction ramping 1.0 (<= LOW) → 0.0
    # (>= HIGH); snow-zone precip is excluded from event runoff.  None → off.
    rain_frac_1d = None
    _sn_lo = getattr(cfg, 'RAIN_SNOW_ELEV_LOW', None)
    _sn_hi = getattr(cfg, 'RAIN_SNOW_ELEV_HIGH', None)
    if _sn_lo is not None or _sn_hi is not None:
        _xp = grid_data["xp"]
        lo = float(_sn_lo) if _sn_lo is not None else float(_sn_hi)
        hi = float(_sn_hi) if _sn_hi is not None else float(_sn_lo)
        if hi <= lo:
            rain_frac_1d = _xp.where(dem_1d >= hi, 0.0, 1.0)
        else:
            rain_frac_1d = _xp.clip((hi - dem_1d) / (hi - lo), 0.0, 1.0)
        rain_frac_1d = rain_frac_1d.astype(dem_1d.dtype)
        _full = int((rain_frac_1d <= 0.0).sum())
        _part = int((rain_frac_1d < 1.0).sum())
        print(f"  Rain/snow      |  rain<={lo:.0f}m  snow>={hi:.0f}m  |  "
              f"{_full:,} snow-only, {_part:,} reduced / {n_cells:,} cells")

    # Optional spatiotemporal field recorder (depth/velocity/discharge over time)
    recorder = None
    if getattr(cfg, 'SAVE_FIELDS', False):
        from .fields import FieldRecorder
        recorder = FieldRecorder(cfg, grid_data)
        if not recorder.active:
            recorder = None

    # Optional virtual gauges (depth/discharge time series at fixed points)
    gauge_rec = None
    if getattr(cfg, 'ROUTING_GAUGES', None):
        from .gauges import GaugeRecorder
        gauge_rec = GaugeRecorder(cfg, grid_data)
        if not gauge_rec.active:
            gauge_rec = None

    # ── Routing scheme ────────────────────────────────────────────────────────
    # Scheme behaviour is described by a registry descriptor (schemes.py); the
    # time loop branches on its trait flags rather than raw name comparisons.
    scheme = getattr(cfg, 'ROUTING_SCHEME', 'kinematic').lower()
    scheme_desc = get_scheme(scheme)
    theta  = float(getattr(cfg, 'DIFFUSION_THETA', 1.0))
    print(f"  Routing scheme: {scheme_desc.describe(theta)}")

    # ── Array module (numpy or cupy) ─────────────────────────────────────────
    xp     = grid_data.get("xp", np)
    _dtype = gpu_utils.get_dtype(cfg)

    # State arrays on the correct device (CPU or GPU)
    volume_1d     = xp.zeros(n_cells, dtype=_dtype)   # [m³]   water stored per cell
    Q_out_1d      = xp.zeros(n_cells, dtype=_dtype)   # [m³/s] outflow rate (for hydrograph)
    Q_out_vol_1d  = xp.zeros(n_cells, dtype=_dtype)   # [m³]   outflow VOLUME last step
    inflow_vol_1d = xp.zeros(n_cells, dtype=_dtype)   # [m³]   upstream inflow volume this step

    # Muskingum–Cunge extra state: I₁ (previous-step inflow rate) and the previous
    # dt (used to recover the inflow RATE I₂ = inflow_vol/dt_prev from the volume
    # scatter without a second reduction).  O₁ is the persistent Q_out_1d above.
    _mc          = scheme_desc.rate_based
    I_prev_1d    = xp.zeros(n_cells, dtype=_dtype)    # [m³/s] inflow rate previous step
    _dt_prev_mc  = cfg.TIME_STEP_SECONDS              # [s] seeds I₂ recovery on step 0
    _mc_neg_max  = xp.zeros((), dtype=_dtype)         # peak negative-outflow fraction

    # Local-inertial (dynamic wave) extra state: the per-face discharge carried
    # across steps so the ∂Q/∂t term has memory.  Unused by other schemes.
    _dyn         = scheme_desc.momentum_state
    Q_face_1d    = xp.zeros(n_cells, dtype=_dtype)    # [m³/s] downstream-face discharge
    _dt_prev_dyn = cfg.TIME_STEP_SECONDS             # [s] for upstream-inflow-rate centering
    _dyn_theta   = float(getattr(cfg, 'DYNAMIC_FLUX_THETA', 0.8))  # de Almeida centering weight
    _GRAV        = 9.81

    # Semi-implicit (HEC-RAS-style) diffusion wave: unconditionally stable global
    # tree solve each step (implicit.py).  dt is an ACCURACY knob, not a stability
    # one — flat/ponded/steep cells never force a tiny dt.  Runs on the CPU (xp is
    # forced to NumPy for this scheme in initialise_grid).
    _implicit         = scheme_desc.implicit
    implicit_solver   = None
    _impl_cfl         = float(getattr(cfg, 'IMPLICIT_CFL_TARGET', 8.0))
    _impl_tol         = float(getattr(cfg, 'IMPLICIT_TOL', 1e-4))
    _c_max_prev       = 0.0     # previous-step max celerity [m/s] (0 → seed dt at dt_max)
    _impl_iters_sum   = 0       # Σ Picard iterations (mean reported at the end)
    _impl_res_max     = 0.0     # peak final Picard residual [m]
    if _implicit:
        from .implicit import ImplicitDiffusiveSolver
        implicit_solver = ImplicitDiffusiveSolver(cfg, grid_data)
        print(f"  Implicit solver: {implicit_solver.solver_name}  "
              f"(max_iters={implicit_solver.max_iters}, tol={_impl_tol:g} m, "
              f"θ={implicit_solver.theta:g})")

    hydrograph = []  # list of (time_seconds, Q_m3s) — Python floats

    # Baseflow offset: add the steady pre-storm discharge (VSA_Q_MAX) so the
    # reported outlet hydrograph starts at baseflow instead of zero, making it
    # directly comparable to observed (gauged) discharge.  Pure additive offset
    # on the routed stormflow — does not affect routing/runoff generation.
    q_base = (float(getattr(cfg, 'VSA_Q_MAX', 0.0))
              if getattr(cfg, 'VSA_BASEFLOW', False) else 0.0)
    if q_base:
        print(f"  Baseflow offset added to outlet: {q_base:.3f} m³/s")

    print("=" * 60)
    if adaptive:
        print(f"TIME LOOP  |  adaptive CFL  |  C_target={cfl_target}  "
              f"dt_max={cfl_dt_max:.0f}s  dt_min={cfl_dt_min}s  "
              f"dt_grow={cfl_dt_grow:.1f}×  sim={cfg.TOTAL_SIMULATION_TIME_HOURS}h")
    else:
        print(f"TIME LOOP  |  static dt  |  steps={n_steps:,}  dt={dt}s  "
              f"sim={cfg.TOTAL_SIMULATION_TIME_HOURS}h")
    print("=" * 60)

    # ── One-time CFL diagnostic (celerity = 5/3·V for Manning wide channel) ──
    # The kinematic wave speed is c = (5/3)·V, not V — using V alone under-counts
    # the Courant number by 5/3.  This corrected check is informational only;
    # the adaptive loop tracks actual instantaneous celerity at each step.
    max_slope  = float(slope_1d.max().item())
    n_min      = float(n.min().item()) if hasattr(n, 'min') else float(n)
    V_at_1m    = (1.0 / n_min) * (1.0 ** (2.0 / 3.0)) * (max_slope ** 0.5)
    c_at_1m    = (5.0 / 3.0) * V_at_1m          # wave celerity at 1 m depth [m/s]
    c_safe_dt  = dx / c_at_1m
    if adaptive:
        print(f"  [CFL] Steepest-slope celerity (1 m depth): c={c_at_1m:.2f} m/s  "
              f"→ CFL-safe dt={c_safe_dt:.2f}s  (adaptive loop will track this)")
    else:
        c_fixed = c_at_1m * dt / dx
        if c_fixed > 1.0:
            print(f"  [CFL WARNING] Celerity-based Courant C={c_fixed:.2f} > 1.  "
                  f"Flux limiter is ACTIVE.  Set TIME_STEP_SECONDS ≤ {c_safe_dt:.2f}s")
        else:
            print(f"  [CFL OK] Celerity-based Courant C={c_fixed:.2f} ≤ 1.")
    print()

    # ── Adaptive-loop state (also used for step-tracking in legacy mode) ──────
    _eps         = 1e-9    # time-axis guard: stop before T + _eps
    _eps_div     = 1e-12   # division guard for celerity (depth · dx)
    t_seconds    = 0.0
    step_count   = 0
    cfl_min_bind = 0
    _dt_sum      = 0.0
    _dt_min_seen = float('inf')
    _dt_max_seen  = 0.0
    _dt_cfl_prev  = cfl_dt_max   # unclamped CFL dt from previous step (growth-limiter seed)
    next_output_t   = _out_interval
    next_progress_t = T / 10.0

    # ── Pre-compute static scatter-add masks (ds_idx never changes) ──────────
    valid_ds      = ds_idx >= 0         # mask: cell has a valid downstream neighbour
    ds_positions  = ds_idx[valid_ds]    # downstream position indices
    ds_safe       = xp.where(valid_ds, ds_idx, 0)   # gather-safe index (diffusive scheme)
    boundary_mask = ~valid_ds           # cells whose Q_out leaves the domain (outlet + off-mask)
    boundary_f    = boundary_mask.astype(_dtype)    # float mask for hot-loop reduction

    # ── Mass-balance accumulators (always on; routing is exactly conservative,
    #    so |error/input| should be ~machine precision — any departure flags a bug) ──
    mb_in   = xp.zeros((), dtype=_dtype)   # Σ effective-runoff volume entering routing [m³]
    mb_out  = xp.zeros((), dtype=_dtype)   # Σ volume leaving the domain at boundary cells [m³]
    mb_rain = xp.zeros((), dtype=_dtype)   # Σ gross rainfall volume [m³] (for runoff ratio)
    mb_bc   = xp.zeros((), dtype=_dtype)   # Σ upstream inflow-BC volume entering routing [m³]

    # Flux-limiter engagement diagnostic: max per-step fraction of wet cells clipped,
    # WHEN that peak occurred, and how many steps were "notably" clipped (>10%) —
    # a bare peak-% conflates a single transient spike (e.g. a flood wavefront
    # arriving in previously-dry cells one step before adaptive dt catches up)
    # with sustained under-resolution.  Device 0-d scalars, synced once at the end.
    _frac_clip_max_dev  = xp.zeros((), dtype=_dtype)
    _frac_clip_peak_t   = xp.zeros((), dtype=_dtype)
    _frac_clip_high_ct  = xp.zeros((), dtype=_dtype)   # steps with >10% wet cells clipped
    _FRAC_CLIP_HIGH     = 0.10

    # ── Runoff-mechanism partition (physical mode only) ──────────────────────
    # Σ effective-runoff volume by generating mechanism [m³].  The three sum
    # EXACTLY to mb_in (effective runoff IN) by construction in the engine.
    _partition = (runoff_engine is not None
                  and getattr(runoff_engine, '_mode', None) == 'physical')
    mb_dunne  = xp.zeros((), dtype=_dtype)   # Σ Dunne / saturation-excess [m³]
    mb_horton = xp.zeros((), dtype=_dtype)   # Σ Horton / infiltration-excess [m³]
    mb_imperv = xp.zeros((), dtype=_dtype)   # Σ impervious (urban) shedding [m³]
    partition_series = []   # (time_hr, cum_dunne_m3, cum_horton_m3, cum_imperv_m3)

    Q_outlet     = 0.0                  # initialise for progress reporting
    # Interval-averaged outlet hydrograph: accumulate the volume that leaves the
    # outlet each step (device scalar, no per-step host sync) and report
    # accumulated-volume / interval at each output time.  This is the physically
    # correct hydrograph quantity (mean flux = ΔV/Δt, mass-consistent) and removes
    # the aliasing of sub-step dispersive ripples / adaptive-dt jitter that makes a
    # point-sampled instantaneous Q_out look like a saw-tooth at the output cadence.
    _out_vol_dev = xp.zeros((), dtype=_dtype)   # Σ outlet outflow volume this interval [m³]
    _last_out_t  = 0.0                          # interval start time [s]
    t_wall_start = time.time()

    while t_seconds < T - _eps:

        # Non-adaptive: reset dt to the configured value each iteration so that
        # output-boundary clamping (below) only shortens THIS step, not all future
        # ones.  Without this, dt would "stick" at the clamped value permanently
        # (e.g. 0.9 → 0.6 after the first 600s boundary → 50% more steps).
        if not adaptive:
            dt = cfg.TIME_STEP_SECONDS

        # ── 1. Rainfall array for this step ──────────────────────────────────
        rain_1d = precip_engine.get_field_1d(t_seconds)   # [m/s], (n_cells,)
        if rain_frac_1d is not None:
            rain_1d = rain_1d * rain_frac_1d              # exclude snow-zone precip

        # ── 1b. Upstream inflow boundary condition (point discharge) ─────────
        # Per-cell external inflow RATE [m³/s] (zero except at BC cells).  dt-
        # independent, so it is sampled here; the volume schemes multiply by the
        # final dt and Muskingum–Cunge adds it to the lateral inflow Q_L below.
        bc_rate_1d = inflow_bc.rate_1d(t_seconds) if inflow_bc is not None else None

        # ── 2. Inflow buffer: accumulates VOLUME (not rate) from upstream cells ─
        # We scatter-add Q_out_vol_1d [m³] — the volume that left each upstream
        # cell in the previous step — not the rate Q_out [m³/s].  This is the
        # critical invariant for variable-dt correctness: inflow volume is fixed
        # at what the upstream step actually computed, independent of dt_current.
        # (If we scattered rates and multiplied by dt_current, a dt jump from
        # 0.01s to 7s would inject 700× a cell's water into its downstream
        # neighbour, causing the observed blow-up to ~500K m³/s.)
        inflow_vol_1d.fill(0)
        gpu_utils.scatter_add(inflow_vol_1d, ds_positions, Q_out_vol_1d[valid_ds])

        # ── 3. Update each cell (vectorised) ─────────────────────────────────
        #
        # Volume balance:
        #   V_new = V_old + rain*cell_area*dt + Q_in*dt - Q_out*dt
        #
        # Because Q_out depends on depth which depends on V_new, we use
        # the EXPLICIT (forward-Euler) scheme:
        #   - Q_out is computed from the CURRENT depth (V_old / cell_area)
        #   - Then V is advanced with that Q_out
        # This is the standard explicit kinematic-wave approach.

        # Depth from stored volume over the cell's storage footprint.  Overland:
        # store_area = cell_area → depth = V/cell_area (unchanged).  Channel cells:
        # store_area = B·L → depth = V/(B·L) = channel-reach depth (confined, deeper).
        depth_1d = xp.maximum(volume_1d / store_area_1d, cfg.MIN_DEPTH_M)   # [m]
        # Floor only — no ceiling. A depth cap freezes Manning Q at the cap
        # value while volume keeps growing, creating a permanent flat plateau.
        # The flux limiter already prevents numerical runaway; deeper cells
        # simply get larger Q_out and drain faster (physically correct).

        if _implicit:
            # Semi-implicit diffusion wave: the global tree solve needs the final
            # dt (set in the dt block below), so here we only resolve the lateral
            # source.  The runoff sandbox is advanced AFTER the solve (forward
            # Euler: query current state, then update).
            if runoff_engine is not None:
                source_1d = runoff_engine.get_effective_1d(t_seconds, rain_1d)   # [m/s]
            else:
                source_1d = rain_1d
            A_xs_1d  = None          # geometry is internal to the implicit solver
            S_eff_1d = slope_1d
        elif _mc:
            # Muskingum–Cunge: the state is per-cell OUTFLOW (not volume).  Recover the
            # inflow RATES from the volume scatter (I₂ = inflow_vol/dt_prev is exact —
            # inflow_vol = Σ upstream O·dt_prev), form the 3-point reference discharge
            # Q_ref = (I₁+I₂+O₁)/3, and get the reference flow area A_xs from a Manning
            # normal-depth rating.  Q_out_1d is set to Q_ref here purely as the celerity
            # proxy for the shared adaptive-dt block below (c = 5/3·Q_ref/A_xs); the real
            # outflow O₂ is computed once dt is final (after the boundary clamp).
            I2_1d    = inflow_vol_1d / max(_dt_prev_mc, _eps)          # [m³/s] inflow this step
            I1_1d    = I_prev_1d                                       # [m³/s] inflow last step
            O1_1d    = Q_out_1d                                        # [m³/s] outflow last step
            # Lateral inflow (effective-runoff rate) generated in the cell.  Needed
            # here — not just for the O₂ formula — so it can FLOOR the reference
            # discharge: a dry hillslope cell fed only by rainfall would otherwise
            # have Q_ref=0 → c=0 → C3=0 and could never shed its lateral inflow (MC
            # cold-start).  Flooring by Q_L gives it the celerity of a reach carrying
            # at least its own generated runoff.  get_effective_1d needs no dt;
            # update_state (which advances the sandbox) is deferred to volume-advance.
            if runoff_engine is not None:
                source_1d = runoff_engine.get_effective_1d(t_seconds, rain_1d)   # [m/s]
            else:
                source_1d = rain_1d
            Q_L_1d   = source_1d * cell_area                          # [m³/s] lateral inflow
            if bc_rate_1d is not None:
                Q_L_1d = Q_L_1d + bc_rate_1d      # upstream BC enters as point inflow
            Q_ref    = xp.maximum((I1_1d + I2_1d + O1_1d) / 3.0, Q_L_1d)
            _h_nd, A_xs_1d = hydraulics.normal_depth(
                Q_ref, slope_1d, n, width_1d, chan_mask_1d, xp)
            c_mc_1d  = (5.0 / 3.0) * Q_ref / xp.maximum(A_xs_1d, _eps_div)
            Q_out_1d = Q_ref
            S_eff_1d = slope_1d
        elif _dyn:
            # Local-inertial (dynamic) wave.  Build the water-surface slope and the
            # flow depth over the higher bed (as in the diffusion wave); the actual
            # momentum discharge is computed AFTER dt is final (like Muskingum's O₂),
            # because it needs dt.  Here we only stage geometry + a celerity proxy.
            _depth_ds = depth_1d[ds_safe]
            _dem_ds   = dem_1d[ds_safe]
            _wse      = dem_1d + depth_1d
            _wse_ds   = _wse[ds_safe]
            S_dyn      = xp.where(valid_ds, (_wse - _wse_ds) / dist_1d, slope_1d)
            h_flow_dyn = xp.where(valid_ds,
                                  xp.maximum(_wse, _wse_ds) - xp.maximum(dem_1d, _dem_ds),
                                  depth_1d)
            h_flow_dyn = xp.maximum(h_flow_dyn, cfg.MIN_DEPTH_M)
            _A_chan   = h_flow_dyn * width_1d
            A_xs_1d   = xp.where(chan_mask_1d, _A_chan, h_flow_dyn * dx)
            R_dyn     = xp.where(chan_mask_1d,
                                 _A_chan / (width_1d + 2.0 * h_flow_dyn), h_flow_dyn)
            S_eff_1d  = xp.maximum(S_dyn, 0.0)
            Q_out_1d  = Q_face_1d      # previous face discharge → celerity proxy for dt
            # de Almeida (2013) flux centering: blend the own face flux with the
            # upstream inflow rate (I₂) and the downstream face flux to suppress the
            # local-inertial checkerboard oscillation (θ=1 → original Bates).
            _I2_dyn    = inflow_vol_1d / max(_dt_prev_dyn, _eps)
            _q_down    = xp.where(valid_ds, Q_face_1d[ds_safe], Q_face_1d)
            Q_cent_dyn = (_dyn_theta * Q_face_1d
                          + (1.0 - _dyn_theta) * 0.5 * (_I2_dyn + _q_down))
        elif scheme_desc.needs_water_surface_slope:
            # Diffusion wave: Manning on the water-surface slope along the flow path,
            # with conveyance on the flow-depth-over-the-higher-bed (CASC2D/GSSHA-style).
            # Returns (Q, A_xs, S_eff); channel cells use a confined rectangular section.
            Q_out_1d, A_xs_1d, S_eff_1d = hydraulics.diffusive_wave_discharge(
                depth_1d, dem_1d, dist_1d, slope_1d, n, ds_safe, valid_ds,
                theta, dx, xp, cfg.MIN_DEPTH_M, width_1d, chan_mask_1d,
            )                                                          # [m³/s], [m²], [m/m]
        else:
            # Kinematic wave: Manning on the bed slope.  Channel cells use the
            # confined rectangular section (R=A/P); overland cells reproduce the
            # original mannings_velocity·cell_discharge bit-for-bit.
            Q_out_1d, A_xs_1d = hydraulics.mannings_discharge(
                depth_1d, slope_1d, n, width_1d, chan_mask_1d, dx, xp)  # [m³/s], [m²]
            S_eff_1d    = slope_1d   # bed slope; makes the combined limit reduce to pure CFL
        # ── Adaptive CFL dt (state^n → dt^n, computed before volume advance) ──
        if _implicit:
            # Unconditionally stable → dt is an ACCURACY knob.  Adaptive: target a
            # Courant number IMPLICIT_CFL_TARGET (≫1 allowed) on the PREVIOUS step's
            # max celerity; flat/steep cells give small/zero celerity and so never
            # force a tiny dt (the explicit scheme's failure mode).  Non-adaptive:
            # honour TIME_STEP_SECONDS directly.
            if adaptive:
                # Ceiling is the output cadence (dt is clamped there anyway), NOT
                # the explicit CFL_DT_MAX — the implicit scheme has no CFL limit.
                dt_new = (_impl_cfl * dx / _c_max_prev
                          if _c_max_prev > _eps_div else _out_interval)
                dt_new = min(dt_new, _out_interval, _dt_cfl_prev * cfl_dt_grow)
                dt_new = max(dt_new, cfl_dt_min)
                _dt_cfl_prev = dt_new
                dt = dt_new
            else:
                dt = cfg.TIME_STEP_SECONDS
        elif adaptive:
            # Wave celerity c = (5/3)·Q/A_xs, using the flow cross-section area A_xs
            # returned by the discharge function (overland: h_flow·cell_size; channel:
            # h_flow·B).  Using A_xs — not depth_1d·dx — keeps the celerity consistent
            # with the conveyance section: for the diffusive scheme A_xs is built from
            # h_flow = h_higher (depth over the higher bed), and for channel cells from
            # the confined width B, so dt tracks the true wave speed in both.
            if _dyn:
                # Dynamic wave: gravity-wave celerity |u| + √(g·h) (Q_out_1d is the
                # previous face discharge here; h from the staged flow depth).
                _u_dyn = xp.abs(Q_out_1d) / xp.maximum(A_xs_1d, _eps_div)
                c_1d   = _u_dyn + xp.sqrt(_GRAV * h_flow_dyn)
            else:
                c_1d   = (5.0 / 3.0) * Q_out_1d / xp.maximum(A_xs_1d, _eps_div)
            # Advective CFL only.  A von Neumann diffusion-number limit
            # (dt ≤ ½dx²/D, D = Q/(2·dx·S_eff) = h_flow^(5/3)/(2n·√S_eff)) was tried
            # and REMOVED: D ∝ S_eff^(-1/2) blows up on the always-present flat-water
            # cells (ponding / backwater / saturated VSA), pinning dt at CFL_DT_MIN
            # for the whole run with NO accuracy benefit.  Stability of this scheme
            # comes from the nonlinear volume flux limiter (Q ≤ V/dt) + the
            # S_eff=max(·,0) clamp, NOT from a linear-stability dt: static dt=0.9s
            # violates the diffusion-number bound yet is stable and accurate because
            # the limiter bounds the solution.  For the diffusive scheme dt is an
            # ACCURACY knob — prefer ADAPTIVE_TIMESTEP=False with a modest TIME_STEP.
            inv_dt     = c_1d / dx
            inv_dt_max = float(inv_dt.max().item())
            dt_new     = cfl_target / max(inv_dt_max, _eps_div)
            dt_new     = min(dt_new, cfl_dt_max)
            # Growth limiter (GSSHA-style): dt may shrink instantly but can grow by at
            # most cfl_dt_grow per step.  Without this, a sudden c_max drop (e.g. after
            # a CFL_DT_MIN-bound peak) causes dt to jump 700× in one step, dumping a
            # huge volume pulse downstream and creating oscillatory instability.
            # From dt=0.01s to dt=7s with grow=1.5 takes ~17 steps — smooth ramp-up.
            dt_new = min(dt_new, _dt_cfl_prev * cfl_dt_grow)
            if dt_new < cfl_dt_min:
                cfl_min_bind += 1
                if cfl_min_bind == 1:
                    print(f"  [CFL_DT_MIN] First bind at t={t_seconds/3600:.3f}h "
                          f"(dt_adaptive={dt_new:.4f}s < {cfl_dt_min}s) — "
                          f"flux limiter engaged for fast cells")
                dt_new = cfl_dt_min
            _dt_cfl_prev = dt_new   # save post-floor, pre-clamp CFL dt for next growth limit
            dt = dt_new

        # Clamp to land exactly on output-record boundaries and simulation end.
        # This keeps the hydrograph on a clean regular time axis and ensures the
        # final step reaches T without overshoot.
        dt = min(dt, next_output_t - t_seconds, T - t_seconds)
        dt = max(dt, _eps)

        if _implicit:
            # dt final → one implicit diffusion-wave solve (Picard-iterated) on the
            # D8 tree.  Produces the new storage directly (mass-consistent) and the
            # per-cell downstream outflow used for the hydrograph / boundary budget.
            # No volume flux limiter: the scheme is unconditionally stable and a
            # limiter would re-introduce the numerical diffusion it avoids.
            volume_1d, Q_out_1d, _n_it, _res = implicit_solver.solve_step(
                volume_1d, source_1d, bc_rate_1d, dt)
            Q_out_vol_1d = Q_out_1d * dt
            rain_vol     = source_1d * cell_area * dt       # [m³] effective runoff added
            _impl_iters_sum += _n_it
            _impl_res_max    = max(_impl_res_max, _res)
            # Celerity proxy for the NEXT step's dt: c = 5/3·V, V = Q/(h·width).
            depth_1d = np.maximum(volume_1d / store_area_1d, cfg.MIN_DEPTH_M)
            A_xs_1d  = depth_1d * width_1d
            _V_impl  = Q_out_1d / np.maximum(depth_1d * width_1d, _eps_div)
            _c_max_prev = float((5.0 / 3.0 * _V_impl).max()) if n_cells else 0.0
            # Picard non-convergence → halve the next step (still stable, more accurate).
            if adaptive and _res > _impl_tol:
                _dt_cfl_prev = max(dt * 0.5, cfl_dt_min)
            # Advance the runoff sandbox once with the final dt (+ partition).
            if runoff_engine is not None:
                if _partition:
                    mb_dunne  += runoff_engine._last_dunne_rate.sum()  * (cell_area * dt)
                    mb_horton += runoff_engine._last_horton_rate.sum() * (cell_area * dt)
                    mb_imperv += runoff_engine._last_imperv_rate.sum() * (cell_area * dt)
                runoff_engine.update_state(rain_1d, dt)
        elif _mc:
            # dt is now final → compute the real Muskingum–Cunge outflow O₂ and
            # overwrite the Q_ref proxy in Q_out_1d (source_1d / Q_L_1d were computed
            # in the discharge branch above).  The volume flux-limiter is intentionally
            # skipped: MC has no per-cell volume state, and clamping would reintroduce
            # the grid-dependent numerical diffusion MC is designed to remove.
            Q_out_1d, _mc_neg = hydraulics.muskingum_cunge_step(
                I2_1d, I1_1d, O1_1d, Q_L_1d, c_mc_1d, A_xs_1d,
                width_1d, slope_1d, dist_1d, dt, xp)
            _mc_neg_max = xp.maximum(_mc_neg_max, _mc_neg)
        elif _dyn:
            # dt final → local-inertial momentum update from the staged geometry,
            # then the same volume-conservative limiter as the other volume schemes.
            Q_out_1d = hydraulics.local_inertial_update(
                Q_cent_dyn, Q_face_1d, A_xs_1d, R_dyn, S_dyn, n, dt, xp, g=_GRAV)
            Q_out_1d = xp.where(h_flow_dyn > cfg.MIN_DEPTH_M, Q_out_1d, 0.0)
            Q_out_1d = xp.maximum(Q_out_1d, 0.0)   # D8 network: downstream-only (no backflow)
            if _flux_limiter:
                _q_cap = xp.maximum(volume_1d, 0.0) / dt
                _wet   = volume_1d > 0.0
                _frac_clip = ((Q_out_1d > _q_cap) & _wet).sum() / xp.maximum(_wet.sum(), 1)
                _is_new_peak = _frac_clip > _frac_clip_max_dev
                _frac_clip_peak_t  = xp.where(_is_new_peak, t_seconds, _frac_clip_peak_t)
                _frac_clip_max_dev = xp.maximum(_frac_clip_max_dev, _frac_clip)
                _frac_clip_high_ct = _frac_clip_high_ct + (_frac_clip > _FRAC_CLIP_HIGH)
                Q_out_1d = xp.minimum(Q_out_1d, _q_cap)
        else:
            # Apply volume-conservative CFL limiter: a cell cannot eject more
            # water than it stores in one time step (prevents Courant runaway).
            # Inlined with xp.minimum/xp.maximum so it works on both CPU and GPU.
            # Diagnostic: the limiter is meant to be a RARE safety net.  When the dt
            # controller keeps the scheme inside its stability envelope only a handful
            # of pathological cells should ever clip; a large clipped fraction signals
            # dt is too aggressive (artificial diffusion / outlet ringing).  A high
            # PEAK that occurs at a single early timestamp with few HIGH-clip steps
            # overall is a transient (e.g. a flood wavefront reaching previously-dry
            # cells one step before adaptive dt catches up, self-healing next step) —
            # different from many high-clip steps, which means dt is systemically
            # too aggressive for this scheme/grid.  On-device scalars (transferred to
            # host once at the end, like the mass-balance accumulators) so the hot
            # loop stays sync-free on GPU.
            if _flux_limiter:
                _q_cap     = xp.maximum(volume_1d, 0.0) / dt
                _wet       = volume_1d > 0.0
                _n_wet     = _wet.sum()
                _n_clipped = ((Q_out_1d > _q_cap) & _wet).sum()
                _frac_clip = _n_clipped / xp.maximum(_n_wet, 1)
                _is_new_peak = _frac_clip > _frac_clip_max_dev
                _frac_clip_peak_t  = xp.where(_is_new_peak, t_seconds, _frac_clip_peak_t)
                _frac_clip_max_dev = xp.maximum(_frac_clip_max_dev, _frac_clip)
                _frac_clip_high_ct = _frac_clip_high_ct + (_frac_clip > _FRAC_CLIP_HIGH)
                Q_out_1d = xp.minimum(Q_out_1d, _q_cap)

        # Convert outflow rate → volume for this step.  This is the value that
        # the NEXT step's scatter-add will use — decoupled from dt_next.
        Q_out_vol_1d = Q_out_1d * dt                 # [m³] outflow volume this step

        if _implicit:
            # Storage, outflow and the runoff sandbox were all advanced in the
            # implicit finalize block above — nothing to do here.
            pass
        elif _mc:
            # MC: source_1d / Q_L were computed above.  Advance the runoff sandbox
            # once with the final dt and accumulate the mechanism partition, then
            # update the volume ledger.  The ledger is SIGNED (no max(·,0) clamp): a
            # cell may briefly over-release, but that deficit is conserved globally
            # (the water was scattered to a downstream cell), so the mass budget still
            # closes to machine precision.  A clamp here would silently discard water.
            if runoff_engine is not None:
                if _partition:
                    mb_dunne  += runoff_engine._last_dunne_rate.sum()  * (cell_area * dt)
                    mb_horton += runoff_engine._last_horton_rate.sum() * (cell_area * dt)
                    mb_imperv += runoff_engine._last_imperv_rate.sum() * (cell_area * dt)
                runoff_engine.update_state(rain_1d, dt)
            rain_vol   = source_1d * cell_area * dt      # [m³] effective runoff added
            volume_1d  = volume_1d + rain_vol + inflow_vol_1d - Q_out_vol_1d
            # Persist MC state for the next step: this step's inflow becomes I₁, and
            # dt is the divisor that recovers I₂ from next step's volume scatter.
            I_prev_1d   = I2_1d
            _dt_prev_mc = dt
        else:
            # Volume advance
            # If a RunoffEngine is active, convert rainfall to effective runoff first
            # (forward Euler: query current VSA/mask, then advance sandbox state).
            # With RUNOFF_SOURCE='none', source_1d == rain_1d (bit-identical to old code).
            if runoff_engine is not None:
                source_1d = runoff_engine.get_effective_1d(t_seconds, rain_1d)  # [m/s]
                if _partition:
                    # Component rates [m/s] stashed by _opm_effective_runoff this step.
                    mb_dunne  += runoff_engine._last_dunne_rate.sum()  * (cell_area * dt)
                    mb_horton += runoff_engine._last_horton_rate.sum() * (cell_area * dt)
                    mb_imperv += runoff_engine._last_imperv_rate.sum() * (cell_area * dt)
                runoff_engine.update_state(rain_1d, dt)
            else:
                source_1d = rain_1d

            rain_vol   = source_1d * cell_area * dt      # [m³] effective runoff added
            volume_1d  = (volume_1d
                          + rain_vol
                          + inflow_vol_1d               # [m³] pre-computed upstream volume
                          - Q_out_vol_1d)               # [m³] pre-computed outflow volume
            if bc_rate_1d is not None:
                volume_1d = volume_1d + bc_rate_1d * dt  # [m³] upstream BC inflow
            volume_1d  = xp.maximum(volume_1d, 0.0)     # no negative storage
            if _dyn:
                Q_face_1d = Q_out_1d      # persist face discharge for next step's ∂Q/∂t
                _dt_prev_dyn = dt         # for next step's upstream-inflow-rate centering

        # ── Mass-balance accumulation (device reductions; transferred once at end) ──
        mb_in   += rain_vol.sum()                              # effective runoff entering routing
        mb_out  += (Q_out_vol_1d * boundary_f).sum()          # volume leaving the domain [m³]
        mb_rain += rain_1d.sum() * (cell_area * dt)           # gross rainfall (for runoff ratio)
        if bc_rate_1d is not None:
            mb_bc += bc_rate_1d.sum() * dt                    # upstream BC inflow [m³]
        _out_vol_dev += Q_out_vol_1d[outlet_pos]              # outlet outflow volume this step [m³]

        # ── Advance simulation time and accumulate step statistics ───────────
        t_seconds    += dt
        step_count   += 1
        _dt_sum      += dt
        _dt_min_seen  = min(_dt_min_seen, dt)
        _dt_max_seen  = max(_dt_max_seen, dt)

        # ── 4. Record outlet hydrograph (at output interval, not every step) ───
        # Both triggers share the single D→H transfer when both fire on one step.
        _at_output   = t_seconds >= next_output_t - _eps or t_seconds >= T - _eps
        _at_progress = t_seconds >= next_progress_t - _eps
        if _at_output:
            # Interval-mean discharge = Σ outlet volume this interval / interval length.
            # .item() converts CuPy 0-d → Python float (8-byte D→H); no-op on NumPy.
            _interval = t_seconds - _last_out_t
            Q_outlet  = float(_out_vol_dev.item()) / max(_interval, _eps) + q_base
            _out_vol_dev.fill(0)            # reset accumulator for the next interval
            _last_out_t = t_seconds
        elif _at_progress:
            # Console-only: instantaneous rate is fine for the progress line.
            Q_outlet = float(Q_out_1d[outlet_pos].item()) + q_base

        if _at_output:
            hydrograph.append((t_seconds, Q_outlet))
            if recorder is not None:
                # depth_1d / Q_out_1d / A_xs_1d are this step's (start-of-step
                # depth → resulting discharge); volume_1d is end-of-step.
                recorder.record(t_seconds, depth_1d, Q_out_1d, A_xs_1d,
                                volume_1d, xp)
            if gauge_rec is not None:
                gauge_rec.record(t_seconds, depth_1d, Q_out_1d, A_xs_1d, xp)
            if _partition:
                # Cumulative mechanism volumes [m³] at the hydrograph cadence —
                # one D→H transfer per recorded row (cheap, same rate as Q).
                partition_series.append((
                    t_seconds / 3600.0,
                    float(mb_dunne.item()),
                    float(mb_horton.item()),
                    float(mb_imperv.item()),
                ))
            next_output_t += _out_interval

        # Progress reporting every 10 % of simulation
        if _at_progress:
            elapsed = time.time() - t_wall_start
            pct     = 100.0 * t_seconds / T
            print(f"  {pct:5.1f}%  |  t={t_seconds/3600:.3f}h  "
                  f"|  Q_outlet={Q_outlet:.4f} m³/s  "
                  f"|  wall={elapsed:.1f}s")
            next_progress_t += T / 10.0

    _wall_total = time.time() - t_wall_start
    _dt_mean    = _dt_sum / step_count if step_count > 0 else 0.0
    print(f"\n  Simulation finished in {_wall_total:.1f}s  |  "
          f"{step_count:,} steps  |  "
          f"dt mean={_dt_mean:.2f}s  min={_dt_min_seen:.3f}s  max={_dt_max_seen:.1f}s")
    if adaptive and cfl_min_bind > 0:
        print(f"  [CFL_DT_MIN] Bound {cfl_min_bind} times — "
              f"flux limiter engaged for pathological fast cells")
    # Flux-limiter engagement: a stable dt keeps this near zero; a large peak
    # fraction means the limiter (not the wave equation) is doing the routing,
    # i.e. dt is too aggressive for the chosen scheme.
    if _implicit:
        _mean_it = _impl_iters_sum / step_count if step_count > 0 else 0.0
        print(f"  Implicit solve |  mean {_mean_it:.2f} Picard iters/step  "
              f"(max_iters={implicit_solver.max_iters})  |  peak residual "
              f"{_impl_res_max:.2e} m")
        if _impl_res_max > _impl_tol:
            print(f"  [NOTE] Peak Picard residual {_impl_res_max:.2e} m > tol "
                  f"{_impl_tol:g} m on at least one step — raise IMPLICIT_MAX_ITERS "
                  f"or lower the time step for a tighter solve.")
    elif _mc:
        # MC has no volume flux-limiter; its resolution diagnostic is how often the
        # raw O₂ went negative (Cr+Dg<1) and was floored at 0.  A small fraction is
        # the harmless classic MC dip; a large one means dt/dx under-resolves the wave.
        _neg_pct = 100.0 * float(_mc_neg_max.item())
        print(f"  Muskingum–Cunge |  peak {_neg_pct:.2f}% of cells had raw O₂<0 (floored to 0)")
        if _neg_pct > 5.0:
            print("  [NOTE] >5% of cells hit the O₂≥0 floor (Cr+Dg<1, under-resolved) — "
                  "raise CFL_TARGET toward 1.0 for a sharper, less-clipped wave.")
    else:
        _frac_clip_max  = float(_frac_clip_max_dev.item())
        _frac_clip_t_h  = float(_frac_clip_peak_t.item()) / 3600.0
        _frac_clip_high = int(_frac_clip_high_ct.item())
        _high_pct = 100.0 * _frac_clip_high / max(step_count, 1)
        print(f"  Flux limiter   |  peak {100.0*_frac_clip_max:.2f}% of wet cells clipped "
              f"in a step, at t={_frac_clip_t_h:.2f}h  |  {_frac_clip_high:,}/{step_count:,} "
              f"steps ({_high_pct:.2f}%) had >{100*_FRAC_CLIP_HIGH:.0f}% of wet cells clipped")
        if _frac_clip_max > 0.02:
            _nature = ("an isolated spike" if _high_pct < 1.0 else
                      "recurring, not just a one-off spike")
            print(f"  [WARNING] Flux limiter clipped >2% of wet cells at its peak "
                  f"({_nature}) — if {_high_pct:.1f}% of steps are affected, dt is "
                  f"marginal; lower CFL_TARGET or (static mode) TIME_STEP_SECONDS. "
                  f"MANNING_SLOPE_CAP can also help if a few unphysically steep DEM "
                  f"cells are forcing a small global dt.")

    # ── Mass balance ─────────────────────────────────────────────────────────
    # Budget on the routed water:  INPUT − OUTFLOW − STORAGE = ERROR.
    # STORAGE includes water still in cells PLUS the final step's interior outflow,
    # which is "in transit" (subtracted from upstream cells but, due to the one-step
    # routing lag, not yet scattered downstream).  Accounting for it makes the budget
    # close to machine precision when the scheme is conservative — so any non-trivial
    # error is a genuine red flag rather than a loop-boundary artefact.
    # In-transit water: the explicit schemes scatter each step's interior outflow
    # to the downstream cell on the NEXT step (one-step lag), so it is subtracted
    # from upstream volume but not yet added downstream — count it as storage.  The
    # implicit scheme has no lag (the global solve updates all cells at once), so
    # its interior outflow is already reflected in volume_1d → no in-flight term.
    inflight   = 0.0 if _implicit else float((Q_out_vol_1d[valid_ds].sum()).item())
    storage    = float(volume_1d.sum().item()) + inflight
    input_m3   = float(mb_in.item())
    bc_m3      = float(mb_bc.item())          # upstream inflow-BC volume [m³]
    outflow_m3 = float(mb_out.item())
    rain_m3    = float(mb_rain.item())
    total_in   = input_m3 + bc_m3             # everything entering the routed domain
    error_m3   = total_in - outflow_m3 - storage
    rel_error  = error_m3 / total_in if total_in > 0 else 0.0
    runoff_ratio = input_m3 / rain_m3 if rain_m3 > 0 else 0.0
    status     = "PASS" if abs(rel_error) < 1e-6 else "WARN"

    print("\n" + "=" * 60)
    print("MASS BALANCE  (routed water budget)")
    print("=" * 60)
    print(f"  Gross rainfall     : {rain_m3:16.3f} m³")
    print(f"  Effective runoff IN: {input_m3:16.3f} m³   (runoff ratio {runoff_ratio:.3f})")
    if bc_m3:
        print(f"  Upstream inflow IN : {bc_m3:16.3f} m³")
    print(f"  Outflow at boundary: {outflow_m3:16.3f} m³")
    print(f"  Storage (end+transit): {storage:14.3f} m³")
    print(f"  Closure error      : {error_m3:16.3f} m³   ({100.0*rel_error:+.2e} % of input)  [{status}]")
    if status == "WARN":
        print("  [WARNING] Mass balance error exceeds 1e-6 — investigate routing/runoff.")

    # ── Runoff-mechanism partition (physical mode only) ──────────────────────
    partition = None
    if _partition:
        dunne_m3  = float(mb_dunne.item())
        horton_m3 = float(mb_horton.item())
        imperv_m3 = float(mb_imperv.item())
        comp_sum  = dunne_m3 + horton_m3 + imperv_m3
        f_dunne   = dunne_m3  / input_m3 if input_m3 > 0 else 0.0
        f_horton  = horton_m3 / input_m3 if input_m3 > 0 else 0.0
        f_imperv  = imperv_m3 / input_m3 if input_m3 > 0 else 0.0
        # Closure check: the three components must sum to the effective runoff IN.
        part_err  = (comp_sum - input_m3) / input_m3 if input_m3 > 0 else 0.0
        partition = dict(dunne_m3=dunne_m3, horton_m3=horton_m3, imperv_m3=imperv_m3,
                         dunne_frac=f_dunne, horton_frac=f_horton, imperv_frac=f_imperv)
        print("-" * 60)
        print("RUNOFF PARTITION  (by generating mechanism)")
        print(f"  Dunne  (saturation-excess): {dunne_m3:16.3f} m³   ({100*f_dunne:5.1f} %)")
        print(f"  Horton (infiltration-exc.): {horton_m3:16.3f} m³   ({100*f_horton:5.1f} %)")
        print(f"  Impervious (urban shed)   : {imperv_m3:16.3f} m³   ({100*f_imperv:5.1f} %)")
        print(f"  Σ components vs runoff IN  : {part_err:+.2e}  rel  "
              f"[{'PASS' if abs(part_err) < 1e-6 else 'WARN'}]")
        write_partition_series(cfg, partition_series)

    if getattr(cfg, 'MASS_BALANCE_REPORT', True):
        append_mass_balance_csv(cfg, scheme, theta, rain_m3, input_m3,
                                 outflow_m3, storage, error_m3, rel_error,
                                 runoff_ratio, partition, bc_m3=bc_m3)

    # ── Persist spatiotemporal fields (depth/velocity/discharge over time) ────
    if recorder is not None:
        recorder.save()
    if gauge_rec is not None:
        gauge_rec.save()

    return hydrograph


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main(cfg):
    """Run the full routing stage (initialise → time loop → save) with *cfg*."""
    # --- Initialise ---
    grid_data  = initialise_grid(cfg)

    # --- Run ---
    hydrograph = run_time_loop(grid_data, cfg)

    # --- Save ---
    df = save_hydrograph(hydrograph, cfg)

    # --- Quick console summary ---
    print("\n" + "=" * 60)
    print("DONE")
    print(f"  CSV rows       : {len(df):,}")
    print(f"  Output file    : {cfg.HYDROGRAPH_CSV}")
    print("=" * 60)
    return df
