# -*- coding: utf-8 -*-
"""
reporting.py — run outputs: hydrograph CSV, VSA partition time series and
the per-run mass-balance ledger row.
"""

import os

import numpy as np
import pandas as pd




def utc_times(cfg, times_s):
    """
    Clock times (UTC, 'YYYY-MM-DD HH:MM:SS') of simulation *times_s* when the
    run has a start date (EVENT_START_UTC), else None.  Simulation time 0 is
    EVENT_START_UTC.
    """
    start = getattr(cfg, 'EVENT_START_UTC', None)
    if not start:
        return None
    try:
        t0 = pd.Timestamp(str(start).strip().rstrip("Z"))
    except (ValueError, TypeError):
        return None
    if t0.tzinfo is not None:
        t0 = t0.tz_convert("UTC").tz_localize(None)
    stamps = t0 + pd.to_timedelta(np.asarray(times_s, dtype=np.float64), unit="s")
    return pd.DatetimeIndex(stamps).round("s").strftime("%Y-%m-%d %H:%M:%S")


def write_partition_series(cfg, series):
    """Write the cumulative Dunne/Horton/Impervious time series to
    {OUTPUT_DIR}/partition_{RUN_TAG}.csv (one file per event)."""
    if not series:
        return
    import csv
    tag = getattr(cfg, 'RUN_TAG', None)
    out_dir = getattr(cfg, 'OUTPUT_DIR', 'output/')
    fname = f"partition_{tag}.csv" if tag else "partition.csv"
    path = os.path.join(out_dir, fname)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time_hr', 'dunne_m3', 'horton_m3', 'imperv_m3'])
        for t_hr, d, h, i in series:
            w.writerow([f"{t_hr:.4f}", f"{d:.3f}", f"{h:.3f}", f"{i:.3f}"])
    print(f"  Partition time series  → {path}")


def append_mass_balance_csv(cfg, scheme, theta, rain_m3, input_m3, outflow_m3,
                             storage_m3, error_m3, rel_error, runoff_ratio,
                             partition=None, bc_m3=0.0):
    """Append one row of the mass-balance budget to MASS_BALANCE_CSV (header on create).
    Appends so successive runs at different configs accumulate for side-by-side review.
    The row also carries the run tag, the key runoff knobs, and (when available) the
    Dunne/Horton/Impervious mechanism partition so a sweep is self-describing."""
    import csv
    from datetime import datetime

    path = getattr(cfg, 'MASS_BALANCE_CSV', None) or os.path.join(
        getattr(cfg, 'OUTPUT_DIR', 'output/'), 'mass_balance.csv')
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    p = partition or {}
    header = ['timestamp', 'run_tag', 'scheme', 'theta', 'runoff_source',
              'sd_source', 'sd_max', 'ksat_scale', 'infiltration', 'impervious',
              'rain_m3', 'input_m3', 'bc_inflow_m3', 'outflow_m3', 'storage_m3',
              'error_m3', 'rel_error', 'runoff_ratio',
              'dunne_m3', 'horton_m3', 'imperv_m3',
              'dunne_frac', 'horton_frac', 'imperv_frac']
    def _f(key, fmt="{}"):
        v = p.get(key)
        return "" if v is None else fmt.format(v)
    row = [datetime.now().isoformat(timespec='seconds'),
           getattr(cfg, 'RUN_TAG', ''),
           scheme, theta, getattr(cfg, 'RUNOFF_SOURCE', 'none'),
           getattr(cfg, 'VSA_SD_SOURCE', ''),
           getattr(cfg, 'VSA_SD_MAX_INITIAL', ''),
           getattr(cfg, 'GA_KSAT_SCALE', ''),
           ('green_ampt' if 'infiltration_excess'
            in getattr(cfg, 'RUNOFF_MECHANISMS', []) else 'none'),
           getattr(cfg, 'IMPERVIOUS_SOURCE', ''),
           f"{rain_m3:.3f}", f"{input_m3:.3f}", f"{bc_m3:.3f}", f"{outflow_m3:.3f}",
           f"{storage_m3:.3f}", f"{error_m3:.6e}", f"{rel_error:.6e}",
           f"{runoff_ratio:.4f}",
           _f('dunne_m3', "{:.3f}"), _f('horton_m3', "{:.3f}"), _f('imperv_m3', "{:.3f}"),
           _f('dunne_frac', "{:.4f}"), _f('horton_frac', "{:.4f}"), _f('imperv_frac', "{:.4f}")]
    write_header = not os.path.exists(path)
    with open(path, 'a', newline='') as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(header)
        w.writerow(row)
    print(f"  Mass-balance row appended → {path}")


# ─────────────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────────────

def save_hydrograph(hydrograph, cfg):
    """
    Save the hydrograph as a CSV with columns:
        time_s   – simulation time in seconds
        time_hr  – simulation time in hours
        Q_m3s    – discharge at the outlet [m³/s]
        time_utc – clock time (UTC), only when EVENT_START_UTC is set
    plus, for a whole-DEM run (rows carry a third value):
        Q_total_outflow_m3s – all water leaving the DEM, every exit cell [m³/s]
    Also prints peak flow and time-to-peak.
    """
    times_s  = np.array([h[0] for h in hydrograph])
    Q_values = np.array([h[1] for h in hydrograph])

    df = pd.DataFrame({
        "time_s"  : times_s,
        "time_hr" : times_s / 3600.0,
        "Q_m3s"   : Q_values,
    })
    if hydrograph and len(hydrograph[0]) > 2:
        df["Q_total_outflow_m3s"] = np.array([h[2] for h in hydrograph])
    stamps = utc_times(cfg, times_s)
    if stamps is not None:              # last column: older readers are unaffected
        df["time_utc"] = stamps

    df.to_csv(cfg.HYDROGRAPH_CSV, index=False)
    print(f"\n  Hydrograph saved → {cfg.HYDROGRAPH_CSV}")

    peak_Q  = Q_values.max()
    peak_t  = times_s[Q_values.argmax()] / 3600.0
    print(f"  Peak discharge : {peak_Q:.4f} m³/s  at t={peak_t:.2f} h")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Closing reports of the time loop
# ─────────────────────────────────────────────────────────────────────────────

def print_step_summary(*, wall_s, step_count, dt_sum, dt_min, dt_max, adaptive, cfl_min_bind,
                       implicit_solver, impl_iters_sum, impl_res_max, impl_tol, impl_rejects,
                       mc_neg_max, clip):
    """
    Print how the time stepping went: steps and step sizes, then the one
    diagnostic that fits the scheme —

    implicit_solver : the semi-implicit solver (Picard iterations, retried steps), or None
    mc_neg_max      : Muskingum–Cunge, largest share of cells whose raw outflow went
                      negative in a step, or None
    clip            : kinematic / diffusive / dynamic flux limiter,
                      (largest share of wet cells clipped, its time [s], steps above
                      the "notable" share), or None
    """
    from .router import FRAC_CLIP_HIGH

    dt_mean = dt_sum / step_count if step_count > 0 else 0.0
    print(f"\n  Simulation finished in {wall_s:.1f}s  |  "
          f"{step_count:,} steps  |  "
          f"dt mean={dt_mean:.2f}s  min={dt_min:.3f}s  max={dt_max:.1f}s")
    if adaptive and cfl_min_bind > 0:
        print(f"  [CFL_DT_MIN] Bound {cfl_min_bind} times — "
              f"flux limiter engaged for pathological fast cells")
    if implicit_solver is not None:
        mean_it = impl_iters_sum / step_count if step_count > 0 else 0.0
        print(f"  Implicit solve |  mean {mean_it:.2f} Picard iters/step  "
              f"(max_iters={implicit_solver.max_iters})  |  peak residual "
              f"{impl_res_max:.2e} m  |  {impl_rejects:,} steps retried at half dt")
        if impl_res_max > impl_tol:
            print(f"  [NOTE] Peak Picard residual {impl_res_max:.2e} m > tol "
                  f"{impl_tol:g} m on at least one step — raise IMPLICIT_MAX_ITERS "
                  f"or lower the time step for a tighter solve.")
        neg = float(getattr(implicit_solver, "neg_volume_m3", 0.0))
        if neg > 0.0:
            print(f"  [WARN] Implicit step over-drained cells: {neg:.3f} m³ floored at zero "
                  f"(unconverged Picard) — shows in the closure error below.")
    elif mc_neg_max is not None:
        # MC has no volume flux-limiter; its resolution diagnostic is how often the
        # raw O₂ went negative (Cr+Dg<1) and was floored at 0.  A small fraction is
        # the harmless classic MC dip; a large one means dt/dx under-resolves the wave.
        neg_pct = 100.0 * mc_neg_max
        print(f"  Muskingum–Cunge |  peak {neg_pct:.2f}% of cells had raw O₂<0 (floored to 0)")
        if neg_pct > 5.0:
            print("  [NOTE] >5% of cells hit the O₂≥0 floor (Cr+Dg<1, under-resolved) — "
                  "raise CFL_TARGET toward 1.0 for a sharper, less-clipped wave.")
    elif clip is not None:
        # A stable dt keeps this near zero; a large peak share means the limiter
        # (not the wave equation) is doing the routing, i.e. dt is too aggressive.
        clip_max, clip_peak_t, clip_high = clip
        clip_t_h = clip_peak_t / 3600.0
        high_pct = 100.0 * clip_high / max(step_count, 1)
        print(f"  Flux limiter   |  peak {100.0*clip_max:.2f}% of wet cells clipped "
              f"in a step, at t={clip_t_h:.2f}h  |  {clip_high:,}/{step_count:,} "
              f"steps ({high_pct:.2f}%) had >{100*FRAC_CLIP_HIGH:.0f}% of wet cells clipped")
        if clip_max > 0.02:
            nature = ("an isolated spike" if high_pct < 1.0 else
                      "recurring, not just a one-off spike")
            print(f"  [WARNING] Flux limiter clipped >2% of wet cells at its peak "
                  f"({nature}) — if {high_pct:.1f}% of steps are affected, dt is "
                  f"marginal; lower CFL_TARGET or (static mode) TIME_STEP_SECONDS. "
                  f"MANNING_SLOPE_CAP can also help if a few unphysically steep DEM "
                  f"cells are forcing a small global dt.")


def close_mass_balance(cfg, scheme, theta, *, storage_m3, storage0_m3, input_m3, bc_m3,
                       outflow_m3, rain_m3, partition_m3=None, partition_series=None):
    """
    Close the budget of the routed water, print it and append it to
    MASS_BALANCE_CSV:  INPUT + STORAGE AT START − OUTFLOW − STORAGE AT END = ERROR.

    The routing is exactly conservative, so the error should be at machine
    precision; anything larger is a real fault, not a rounding artefact.
    *partition_m3*: (Dunne, Horton, impervious) runoff volumes for the physical
    runoff mode (they must sum to the runoff that entered), else None.
    Returns the dict of the runoff partition, or None.
    """
    storage = storage_m3
    total_in = input_m3 + bc_m3               # everything entering the routed domain
    error_m3 = total_in + storage0_m3 - outflow_m3 - storage
    rel_error = error_m3 / total_in if total_in > 0 else 0.0
    runoff_ratio = input_m3 / rain_m3 if rain_m3 > 0 else 0.0
    status = "PASS" if abs(rel_error) < 1e-6 else "WARN"

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

    partition = None
    if partition_m3 is not None:
        dunne_m3, horton_m3, imperv_m3 = partition_m3
        comp_sum = dunne_m3 + horton_m3 + imperv_m3
        f_dunne = dunne_m3 / input_m3 if input_m3 > 0 else 0.0
        f_horton = horton_m3 / input_m3 if input_m3 > 0 else 0.0
        f_imperv = imperv_m3 / input_m3 if input_m3 > 0 else 0.0
        # Closure check: the three components must sum to the effective runoff IN.
        part_err = (comp_sum - input_m3) / input_m3 if input_m3 > 0 else 0.0
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
    return partition
