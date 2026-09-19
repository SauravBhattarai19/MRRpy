# -*- coding: utf-8 -*-
"""
engine.py
=========
Modular, **pluggable** runoff generation engine for the grid router.

Sits between PrecipEngine (rainfall in [m/s]) and the time loop (volume update),
transforming raw rainfall into effective surface runoff based on the selected
mode.  Each mode is a small self-contained ``RunoffMode`` subclass that
registers itself under a name via the ``@register`` decorator, so a method can
be *plugged in / plugged out* from one place — including from a third-party
package (``from MRRpy.core.runoff import register``) without editing this
file.

Built-in modes (set via ``config.RUNOFF_SOURCE``):
  'none'        – all rainfall is direct runoff (default, backward compatible)
  'coefficient' – multiply rainfall by static spatial Cf raster [0–1]
  'raster'      – read pre-computed runoff raster time series [m/s]
  'scs_cn'      – SCS Curve Number method (scalar / GEE GCN250 / raster CN)
  'physical'    – process-based, composable mechanisms (impervious /
                  infiltration_excess / saturation_excess); see physical.py

Usage in the time loop (forward Euler):
    source_1d = runoff_engine.get_effective_1d(t_s, rain_1d)   # current state
    runoff_engine.update_state(rain_1d, dt)                     # advance state
    rain_vol = source_1d * cell_area * dt

CPU/GPU: each mode reads ``grid_data['xp']`` (numpy or cupy) and builds its
state on that array module, so the same classes run on both backends — the GPU
variant (``RunoffEngineGPU``) is a thin marker subclass, no per-mode overrides.

Reference:
    Pradhan, N.R. and Ogden, F.L. (2010). Development of a one-parameter variable
    source area runoff model for ungauged basins. Advances in Water Resources,
    33(5), pp.572–584.
"""

import os

import numpy as np
import pandas as pd
import rasterio

from ...utils import gpu_utils
from ..io_utils import align_raster_to_dem


# ═════════════════════════════════════════════════════════════════════════════
# Registry
# ═════════════════════════════════════════════════════════════════════════════
# Maps a RUNOFF_SOURCE name → RunoffMode subclass.  Built-ins register below;
# external packages can add their own with the same decorator.
RUNOFF_MODES = {}


def register(name):
    """Class decorator: register a RunoffMode under *name* (case-insensitive)."""
    def _wrap(cls):
        RUNOFF_MODES[name.lower()] = cls
        return cls
    return _wrap


# ═════════════════════════════════════════════════════════════════════════════
# Mode contract
# ═════════════════════════════════════════════════════════════════════════════
class RunoffMode:
    """
    Base contract every runoff mode satisfies.

    Subclasses implement ``get_effective_1d`` and, if stateful, ``update_state``
    and ``is_active``.  ``__init__`` receives the config object and the
    ``grid_data`` dict from ``initialise_grid`` and stores the common grid
    handles (including ``xp``, the numpy/cupy array module).
    """

    #: registered mode name; set by @register-decorated subclasses.
    name = None

    def __init__(self, cfg, grid_data):
        self._cfg     = cfg
        self._n_cells = grid_data['n_cells']
        self._s_rows  = grid_data['s_rows']
        self._s_cols  = grid_data['s_cols']
        self._nrows   = grid_data['nrows']
        self._ncols   = grid_data['ncols']
        self._xp      = grid_data.get('xp', np)
        self._mode    = self.name

    # ── Interface (forward Euler) ─────────────────────────────────────────────
    def get_effective_1d(self, t_seconds, rain_1d):
        """Effective runoff rate [m/s] per active cell, shape (n_cells,)."""
        raise NotImplementedError

    def update_state(self, rain_1d, dt):
        """Advance internal state by one timestep (stateless modes: no-op)."""
        pass

    def is_active(self, t_seconds):
        """True if any cell is generating non-zero runoff this step."""
        return False

    def get_effective_2d(self, t_seconds, rain_1d):
        """2-D runoff map (nrows × ncols), NaN outside watershed."""
        eff_1d = gpu_utils.to_cpu(self.get_effective_1d(t_seconds, rain_1d))
        out = np.full((self._nrows, self._ncols), np.nan, dtype=np.float64)
        out[self._s_rows, self._s_cols] = eff_1d
        return out


# ═════════════════════════════════════════════════════════════════════════════
# Built-in modes
# ═════════════════════════════════════════════════════════════════════════════
@register('none')
class NoneMode(RunoffMode):
    """All rainfall is direct runoff (backward-compatible default)."""
    name = 'none'

    def get_effective_1d(self, t_seconds, rain_1d):
        return rain_1d


@register('coefficient')
class CoefficientMode(RunoffMode):
    """Multiply rainfall by a static spatial runoff coefficient [0–1]."""
    name = 'coefficient'

    def __init__(self, cfg, grid_data):
        super().__init__(cfg, grid_data)
        path = cfg.RUNOFF_COEFFICIENT_PATH
        if not path or not os.path.exists(path):
            raise FileNotFoundError(
                f"RUNOFF_COEFFICIENT_PATH '{path}' not found. Point it at a "
                "runoff-coefficient GeoTIFF [0–1]."
            )
        # Reproject/resample onto the routing grid (any CRS/resolution/extent).
        dem_path = getattr(cfg, 'ROUTING_DEM_PATH', '') or cfg.DEM_PATH
        arr = align_raster_to_dem(path, dem_path, resampling='bilinear')
        _to_np = lambda a: a.get() if hasattr(a, 'get') else np.asarray(a)
        sr, sc = _to_np(self._s_rows), _to_np(self._s_cols)
        Cf = np.clip(np.asarray(arr, dtype=np.float64)[sr, sc], 0.0, 1.0)
        self._Cf_1d = self._xp.asarray(Cf)

    def get_effective_1d(self, t_seconds, rain_1d):
        return rain_1d * self._Cf_1d

    def is_active(self, t_seconds):
        return bool((self._Cf_1d > 0).any())


@register('raster')
class RasterMode(RunoffMode):
    """Read a pre-computed effective-runoff raster time series [m/s]."""
    name = 'raster'

    def __init__(self, cfg, grid_data):
        super().__init__(cfg, grid_data)
        manifest_path = cfg.RUNOFF_RASTER_MANIFEST
        if not manifest_path or not os.path.exists(manifest_path):
            raise FileNotFoundError(
                f"RUNOFF_RASTER_MANIFEST '{manifest_path}' not found."
            )
        mf = pd.read_csv(manifest_path)
        for col in ('time_s', 'filepath'):
            if col not in mf.columns:
                raise ValueError(
                    "RUNOFF_RASTER_MANIFEST must have columns 'time_s' and "
                    f"'filepath'; missing '{col}'."
                )
        # Frames may be listed at irregular times and in any order.
        mf = mf.sort_values('time_s').reset_index(drop=True)
        dem_path = getattr(cfg, 'ROUTING_DEM_PATH', '') or cfg.DEM_PATH
        _to_np = lambda a: a.get() if hasattr(a, 'get') else np.asarray(a)
        s_rows, s_cols = _to_np(self._s_rows), _to_np(self._s_cols)

        self._raster_times = mf['time_s'].values.astype(np.float64)
        self._raster_cache = {}
        for _, row in mf.iterrows():
            t_s   = float(row['time_s'])
            fpath = row['filepath']
            if not os.path.exists(fpath):
                raise FileNotFoundError(
                    f"RUNOFF_RASTER_MANIFEST references missing raster '{fpath}'."
                )
            # Reproject/resample each frame onto the routing grid, so runoff
            # rasters can be in any CRS/resolution/extent (uncovered → 0).
            arr = align_raster_to_dem(fpath, dem_path, resampling='bilinear')
            vals = np.asarray(arr, dtype=np.float64)[s_rows, s_cols]
            vals = np.where(np.isfinite(vals), vals, 0.0)
            vals = np.maximum(vals, 0.0)                     # runoff rate ≥ 0 [m/s]
            self._raster_cache[t_s] = self._xp.asarray(vals)

    def _interp_raster(self, t_seconds):
        times = self._raster_times
        if len(times) == 1:                                 # single frame → constant
            return self._raster_cache[times[0]]
        idx   = np.searchsorted(times, t_seconds, side='right') - 1
        idx   = int(np.clip(idx, 0, len(times) - 2))
        t0, t1 = times[idx], times[idx + 1]
        r0 = self._raster_cache[t0]
        r1 = self._raster_cache[t1]
        w  = (t_seconds - t0) / (t1 - t0) if t1 > t0 else 0.0
        return r0 + w * (r1 - r0)

    def get_effective_1d(self, t_seconds, rain_1d):
        return self._interp_raster(t_seconds)

    def is_active(self, t_seconds):
        return bool((self._interp_raster(t_seconds) > 0).any())


# ── SCS Curve Number ─────────────────────────────────────────────────────────
def _apply_amc(cn, amc):
    """Convert an AMC-II curve number to AMC I (dry) or III (wet).

    Standard SCS conversion (Chow, Maidment & Mays 1988); AMC II returned as-is.
    """
    amc = str(amc).strip().lower()
    if amc == 'i':
        return cn / (2.281 - 0.01281 * cn)
    if amc == 'iii':
        return cn / (0.427 + 0.00573 * cn)
    return cn  # 'ii' (normal)


@register('scs_cn')
class ScsCnMode(RunoffMode):
    """
    SCS Curve Number method (event-cumulative, forward-Euler).

    Per-cell CN comes from ``RUNOFF_CN_SOURCE``:
      'scalar' – uniform ``RUNOFF_CN``
      'gee'    – GCN250 global curve numbers (AMC picks Dry/Average/Wet image)
      'raster' – a user CN GeoTIFF (``RUNOFF_CN_PATH``), aligned to the DEM

    Math (applied to *cumulative* rainfall P, giving cumulative effective
    rainfall Pe, differenced per step): S = 25400/CN − 254 [mm],
    Ia = Ia_factor·S, Pe = (P−Ia)²/(P−Ia+S) for P > Ia else 0.
    """
    name = 'scs_cn'

    def __init__(self, cfg, grid_data):
        super().__init__(cfg, grid_data)
        xp = self._xp

        CN_1d = self._resolve_cn(cfg)                     # numpy, clipped [1,100]
        Ia_factor = getattr(cfg, 'RUNOFF_SCS_Ia_FACTOR', 0.2)
        S_1d = 25400.0 / CN_1d - 254.0                    # [mm] max retention
        self._S_1d  = xp.asarray(S_1d)
        self._Ia_1d = xp.asarray(Ia_factor * S_1d)        # [mm] initial abstraction

        self._cumrain_mm  = xp.zeros(self._n_cells, dtype=np.float64)
        self._Pe_mm_old   = xp.zeros(self._n_cells, dtype=np.float64)
        self._delta_Pe_m  = xp.zeros(self._n_cells, dtype=np.float64)  # [m] this step
        self._scs_rate_ms = xp.zeros(self._n_cells, dtype=np.float64)  # [m/s]

    # ── CN resolution ─────────────────────────────────────────────────────────
    def _resolve_cn(self, cfg):
        """Return per-cell CN as a numpy array, clipped to [1, 100]."""
        source = getattr(cfg, 'RUNOFF_CN_SOURCE', 'gee').lower()
        amc    = getattr(cfg, 'RUNOFF_CN_AMC', 'ii').lower()
        cn_fallback = float(getattr(cfg, 'RUNOFF_CN', 75.0))
        n_cells = self._n_cells

        if source == 'scalar':
            cn = np.full(n_cells, cn_fallback, dtype=np.float64)
            cn = _apply_amc(cn, amc)
        elif source == 'gee':
            cn = self._resolve_cn_gee(cfg, amc, cn_fallback)   # AMC baked in
        elif source == 'raster':
            cn = self._resolve_cn_raster(cfg, cn_fallback)
            cn = _apply_amc(cn, amc)
        else:
            raise ValueError(
                f"RUNOFF_CN_SOURCE='{source}' is not recognised; use "
                "'scalar', 'gee', or 'raster'."
            )
        return np.clip(cn, 1.0, 100.0)

    def _resolve_cn_gee(self, cfg, amc, cn_fallback):
        n_cells = self._n_cells
        try:
            from ...gee.cn_gee import download_cn_raster
        except ImportError:
            print(f"  [WARN] earthengine-api not installed; using scalar CN={cn_fallback}")
            return np.full(n_cells, cn_fallback, dtype=np.float64)

        output_dir = getattr(cfg, 'OUTPUT_DIR', 'output/')
        cached   = os.path.join(output_dir, f"cn_gcn250_amc{amc}.tif")
        dem_path = cfg.ROUTING_DEM_PATH
        result = download_cn_raster(
            dem_path=dem_path,
            watershed_geojson_path=getattr(
                cfg, 'WATERSHED_GEOJSON', 'output/watershed.geojson'),
            output_path=cached,
            amc=amc,
            project=getattr(cfg, 'GEE_PROJECT', None),
        )
        if result is None:
            print(f"  [WARN] GEE CN (GCN250) download failed; using scalar CN={cn_fallback}")
            return np.full(n_cells, cn_fallback, dtype=np.float64)

        cn_2d = align_raster_to_dem(cached, dem_path, resampling='bilinear')
        cn = cn_2d[self._s_rows, self._s_cols].astype(np.float64)
        bad = (cn <= 0) | ~np.isfinite(cn)
        cn[bad] = cn_fallback
        return cn

    def _resolve_cn_raster(self, cfg, cn_fallback):
        path = getattr(cfg, 'RUNOFF_CN_PATH', '')
        if not path or not os.path.exists(path):
            raise FileNotFoundError(
                f"RUNOFF_CN_SOURCE='raster' but RUNOFF_CN_PATH '{path}' not "
                "found. Point it at a curve-number GeoTIFF, or use "
                "RUNOFF_CN_SOURCE='scalar'/'gee'."
            )
        dem_path = cfg.ROUTING_DEM_PATH
        cn_2d = align_raster_to_dem(path, dem_path, resampling='bilinear')
        cn = cn_2d[self._s_rows, self._s_cols].astype(np.float64)
        bad = (cn <= 0) | ~np.isfinite(cn)
        cn[bad] = cn_fallback
        return cn

    # ── State (forward Euler) ─────────────────────────────────────────────────
    def _scs_formula(self, P_mm):
        """SCS-CN accumulated effective rainfall [mm] from cumulative P [mm]."""
        xp = self._xp
        excess = P_mm - self._Ia_1d
        return xp.where(excess > 0, (excess ** 2) / (excess + self._S_1d), 0.0)

    def update_state(self, rain_1d, dt):
        xp = self._xp
        self._cumrain_mm = self._cumrain_mm + rain_1d * dt * 1000.0   # m/s → mm
        Pe_new = self._scs_formula(self._cumrain_mm)
        delta  = xp.maximum(Pe_new - self._Pe_mm_old, 0.0)           # [mm] this step
        self._delta_Pe_m  = delta / 1000.0                           # [m]  this step
        self._scs_rate_ms = (self._delta_Pe_m / dt) if dt > 0 \
            else xp.zeros(self._n_cells)                             # [m/s]
        self._Pe_mm_old = Pe_new

    def get_effective_1d(self, t_seconds, rain_1d):
        return self._scs_rate_ms

    def is_active(self, t_seconds):
        return bool((self._delta_Pe_m > 0).any())


# The process-based 'physical' mode (composable mechanisms) is registered in
# physical.py, imported at the bottom of this module.


# ═════════════════════════════════════════════════════════════════════════════
# Engine façade
# ═════════════════════════════════════════════════════════════════════════════
class RunoffEngine:
    """
    Thin dispatcher that instantiates the ``RunoffMode`` named by
    ``cfg.RUNOFF_SOURCE`` and delegates the forward-Euler interface to it.
    Any attribute not defined here is forwarded to the active mode instance
    (so mode-specific state such as the VSA masks stays reachable).

    Parameters
    ----------
    cfg       : config object
    grid_data : dict returned by router.initialise_grid()
    """

    def __init__(self, cfg, grid_data):
        mode = getattr(cfg, 'RUNOFF_SOURCE', 'none').lower()
        cls = RUNOFF_MODES.get(mode)
        if cls is None:
            valid = ", ".join(f"'{k}'" for k in RUNOFF_MODES)
            raise ValueError(
                f"RUNOFF_SOURCE='{mode}' is not recognised. "
                f"Valid options: {valid}."
            )
        self._mode = mode
        self._impl = cls(cfg, grid_data)
        print(f"  RunoffEngine    |  mode='{mode}'")

    # ── Public interface (delegates to the mode) ──────────────────────────────
    def get_effective_1d(self, t_seconds, rain_1d):
        return self._impl.get_effective_1d(t_seconds, rain_1d)

    def update_state(self, rain_1d, dt):
        self._impl.update_state(rain_1d, dt)

    def get_effective_2d(self, t_seconds, rain_1d):
        return self._impl.get_effective_2d(t_seconds, rain_1d)

    def is_active(self, t_seconds):
        return self._impl.is_active(t_seconds)

    def __getattr__(self, name):
        # Only reached for attributes not found normally → forward to the mode
        # instance, preserving deep access to mode-specific state.
        try:
            impl = object.__getattribute__(self, '_impl')
        except AttributeError:
            raise AttributeError(name)
        return getattr(impl, name)


# Import at the bottom (after RunoffMode/register/RunoffEngine are defined) so the
# process-based mechanisms register themselves without a circular import.
from . import physical  # noqa: E402,F401  (registers the 'physical' RunoffMode)
