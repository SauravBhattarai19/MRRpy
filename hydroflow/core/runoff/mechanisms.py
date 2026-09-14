# -*- coding: utf-8 -*-
"""
mechanisms.py — composable, physics-based runoff-generation mechanisms.

Each mechanism is a self-contained runoff *process* that can run alone or be
combined with the others by ``PhysicalRunoffMode`` (physical.py). They share a
forward-Euler contract and are combined by a physically-consistent partitioning
that never double-counts (see ``PhysicalRunoffMode.get_effective_1d``).

Mechanisms
----------
impervious           urban/impervious fraction sheds 100 % of rain.
infiltration_excess  Hortonian overland flow; infiltration capacity from
                     Green-Ampt (ψ, K_v, Δθ₀, cumulative F).  ``GA_*`` config.
saturation_excess    Dunne overland flow via the Pradhan & Ogden (2010) VSA-OPM
                     sandbox ("Dr. Nawa's model").  ``VSA_*`` config.

Adding a mechanism
------------------
Subclass ``RunoffMechanism``, implement the small contract, and decorate with
``@register_mechanism('name')``.  A brand-new *whole* runoff generator (curve
number, coefficient, or a third-party method) plugs in one level up, at the
``RunoffMode`` registry in engine.py, and feeds routing through the same
``effective runoff [m/s]`` contract.
"""

import os

import numpy as np
import rasterio

from ..io_utils import raster_to_grid
from .soil import (
    OPM_Q_MIN,
    resolve_zone_divides,
    per_zone_sd_from_raster,
    usda_psi_m,
)


# ═════════════════════════════════════════════════════════════════════════════
# Mechanism registry
# ═════════════════════════════════════════════════════════════════════════════
MECHANISM_REGISTRY = {}


def register_mechanism(name):
    """Class decorator: register a RunoffMechanism under *name* (lower-cased)."""
    def _wrap(cls):
        cls.name = name.lower()
        MECHANISM_REGISTRY[name.lower()] = cls
        return cls
    return _wrap


class RunoffMechanism:
    """
    One composable runoff process (forward-Euler, stateful).

    Parameters
    ----------
    cfg       : config object
    grid_data : dict from ``initialise_grid``
    shared    : dict of resources resolved once by the composing mode and shared
                across mechanisms — ``xp`` (numpy/cupy), ``cell_size``,
                ``cell_area``, ``sd_params`` (from ``resolve_sd_params``), and
                ``imperv_frac`` (the impervious fraction per cell, zeros when the
                impervious mechanism is inactive).
    """

    name = None

    def __init__(self, cfg, grid_data, shared):
        self._cfg      = cfg
        self._grid     = grid_data
        self._shared   = shared
        self._xp       = shared['xp']
        self._n_cells  = grid_data['n_cells']

    def update_state(self, rain_1d, dt):
        """Advance internal state one step (after the combiner read current state)."""
        pass


# ═════════════════════════════════════════════════════════════════════════════
# Impervious — urban shedding
# ═════════════════════════════════════════════════════════════════════════════
@register_mechanism('impervious')
class ImperviousMechanism(RunoffMechanism):
    """Impervious fraction Imp ∈ [0,1]; sheds 100 % of rain regardless of soil."""

    def __init__(self, cfg, grid_data, shared):
        super().__init__(cfg, grid_data, shared)
        from ..routing import surface as _ru
        imperv_np = _ru.resolve_impervious_fraction(cfg, grid_data)   # (n_cells,)
        self.frac = self._xp.asarray(imperv_np)
    # static — no update_state


# ═════════════════════════════════════════════════════════════════════════════
# Infiltration-excess (Hortonian) — Green-Ampt
# ═════════════════════════════════════════════════════════════════════════════
@register_mechanism('infiltration_excess')
class InfiltrationExcessMechanism(RunoffMechanism):
    """
    Hortonian infiltration-excess overland flow.

    Infiltration capacity f_p [m/s] follows Green-Ampt:
        f_p = K_v · (1 + ψ·Δθ₀ / max(F, F_floor))
    with cumulative infiltration F advanced each step.  The pervious-soil runoff
    fraction is max(rain − f_p, 0)/rain.
    """

    def __init__(self, cfg, grid_data, shared):
        super().__init__(cfg, grid_data, shared)
        xp = self._xp
        params = shared['sd_params']
        SD_max_initial = params['sd_max']
        self._F_floor  = 1e-9   # m — floor on F so f_p is finite at F=0

        # Wetting-front suction ψ [m] per cell (scalar or SoilGrids texture).
        psi_m = self._resolve_psi_m(
            cfg, grid_data, float(getattr(cfg, 'GA_SUCTION_M', 0.15)))
        # Vertical surface infiltration capacity [mm/hr] (scalar / gridded).
        kv_scalar = float(getattr(cfg, 'GA_KSAT_MMHR', 12.0))
        s_rows = grid_data['s_rows']
        s_cols = grid_data['s_cols']
        kv_mmhr  = self._resolve_ksat_mmhr(cfg, grid_data, kv_scalar)
        kv_ms_1d = kv_mmhr / 1000.0 / 3600.0                          # → m/s

        # Root-zone depth Z_r per cell from the same land-cover source as the
        # SERVES deficit raster, so Δθ₀ = deficit / Z_r is consistent.
        from ..routing import surface as _ru
        _n_source = getattr(cfg, 'MANNINGS_N_SOURCE', 'lulc').lower()
        _lc_src   = 'lcz' if _n_source == 'lcz' else 'lulc'
        zr_default = float(getattr(cfg, 'VSA_SD_MAX_INITIAL', 0.5)) or 0.5
        zr_np = np.maximum(
            _ru.resolve_lulc_field(cfg, grid_data, 'root_zone_depth_m',
                                   zr_default, _lc_src), 1e-3)

        # Δθ₀ = initial moisture deficit per cell.
        #   deficit raster: Δθ₀ = deficit / Z_r ; fallback: SD_max / mean(Z_r).
        _fallback = float(SD_max_initial) / float(zr_np.mean())
        dtheta0_np = None
        deficit_raster = params.get('deficit_raster')
        if deficit_raster:
            dem_path = getattr(cfg, 'ROUTING_DEM_PATH', '') or cfg.DEM_PATH
            # Reproject onto the routing grid; uncovered/nodata → NaN → fallback.
            dfc = raster_to_grid(deficit_raster, dem_path, s_rows, s_cols)
            with np.errstate(invalid='ignore', divide='ignore'):
                dtheta0_np = dfc / zr_np
        if dtheta0_np is None:
            dtheta0_np = np.full(self._n_cells, _fallback, dtype=np.float64)
        _bad = ~np.isfinite(dtheta0_np)
        if _bad.any():
            dtheta0_np[_bad] = _fallback
        dtheta0_np = np.clip(dtheta0_np, 0.0, 1.0)

        self._psi     = xp.asarray(psi_m)
        self._ksat    = xp.asarray(kv_ms_1d)
        self._dtheta0 = xp.asarray(dtheta0_np)
        self._F       = xp.zeros(self._n_cells, dtype=np.float64)
        print(f"  Green-Ampt    |  K_v(mm/hr)=[{kv_mmhr.min():.2f}, "
              f"{kv_mmhr.max():.2f}] mean={kv_mmhr.mean():.2f}"
              f"  psi(m)=[{psi_m.min():.3f}, {psi_m.max():.3f}]"
              f"  dtheta0=[{dtheta0_np.min():.3f}, {dtheta0_np.max():.3f}]")

    # ── Contract ─────────────────────────────────────────────────────────────
    def capacity(self):
        """Green-Ampt infiltration capacity f_p [m/s] per cell (uses current F)."""
        xp = self._xp
        return self._ksat * (1.0 + self._psi * self._dtheta0
                             / xp.maximum(self._F, self._F_floor))

    def excess_fraction(self, rain_1d):
        """Infiltration-excess runoff fraction of the pervious soil [-]."""
        xp = self._xp
        excess = xp.maximum(rain_1d - self.capacity(), 0.0)
        return xp.where(rain_1d > 0.0,
                        excess / xp.maximum(rain_1d, 1e-30), 0.0)

    def update_state(self, rain_1d, dt):
        """Advance cumulative infiltration F by the infiltrated depth this step."""
        f = self._xp.minimum(rain_1d, self.capacity())    # infiltration rate
        self._F = self._F + f * dt

    # ── Green-Ampt parameter resolution (ported verbatim; GA_* config) ───────
    def _resolve_ksat_mmhr(self, cfg, grid_data, kv_scalar):
        """
        Per-cell Green-Ampt vertical Ksat [mm/hr].

          'scalar' → uniform kv_scalar.
          'gee'    → HiHydroSoil v2.0 Ksat aligned to the routing DEM (cached);
                     nodata/≤0 cells fall back to the valid-cell median.
          'raster' → pre-computed mm/hr GeoTIFF at GA_KSAT_RASTER.
        GA_KSAT_SCALE multiplies the gridded values (calibration knob).
        """
        n      = self._n_cells
        source = getattr(cfg, 'GA_KSAT_SOURCE', 'scalar').lower()
        scale  = float(getattr(cfg, 'GA_KSAT_SCALE', 1.0))
        if source == 'scalar':
            return np.full(n, kv_scalar, dtype=np.float64)

        path = getattr(cfg, 'GA_KSAT_RASTER', None) \
            or os.path.join(getattr(cfg, 'OUTPUT_DIR', 'output/'), 'ksat_hihydro.tif')

        if source == 'gee':
            try:
                from ...gee.serves_gee import download_ksat_raster
                got = download_ksat_raster(
                    dem_path=cfg.ROUTING_DEM_PATH,
                    watershed_geojson_path=getattr(
                        cfg, 'WATERSHED_GEOJSON', 'output/watershed.geojson'),
                    output_path=path,
                    project=getattr(cfg, 'GEE_PROJECT', None))
            except Exception as exc:
                print(f"  [WARN] Ksat download failed ({exc}); "
                      f"scalar K_v={kv_scalar} mm/hr")
                got = None
            if not got:
                return np.full(n, kv_scalar, dtype=np.float64)
        elif source == 'raster':
            if not (path and os.path.isfile(path)):
                print(f"  [WARN] GA_KSAT_RASTER not found: {path}; "
                      f"scalar K_v={kv_scalar} mm/hr")
                return np.full(n, kv_scalar, dtype=np.float64)
        else:
            raise ValueError(f"Unknown GA_KSAT_SOURCE: '{source}'")

        dem_path = getattr(cfg, 'ROUTING_DEM_PATH', '') or cfg.DEM_PATH
        # Reproject onto the routing grid (any CRS/resolution); nodata → NaN.
        kv = raster_to_grid(path, dem_path, grid_data['s_rows'],
                            grid_data['s_cols'])
        kv = kv * scale
        bad = ~np.isfinite(kv) | (kv <= 0.0)
        if bad.any():
            good = ~bad
            fill = float(np.median(kv[good])) if good.any() else kv_scalar
            kv[bad] = fill
            print(f"  Ksat gaps     |  {int(bad.sum()):,}/{n:,} nodata cells "
                  f"filled with median {fill:.2f} mm/hr")
        return kv

    def _resolve_psi_m(self, cfg, grid_data, psi_scalar):
        """
        Per-cell Green-Ampt suction ψ [m].

          'scalar'  → uniform psi_scalar.
          'texture' → SoilGrids sand/clay (DEM-aligned) → USDA class → Rawls
                      (1983) ψ.  nodata cells fall back to psi_scalar.
        """
        n      = self._n_cells
        source = getattr(cfg, 'GA_SUCTION_SOURCE', 'scalar').lower()
        if source != 'texture':
            return np.full(n, psi_scalar, dtype=np.float64)

        path = os.path.join(getattr(cfg, 'OUTPUT_DIR', 'output/'), 'texture_sandclay.tif')
        try:
            from ...gee.serves_gee import download_texture_raster
            got = download_texture_raster(
                dem_path=cfg.ROUTING_DEM_PATH,
                watershed_geojson_path=getattr(
                    cfg, 'WATERSHED_GEOJSON', 'output/watershed.geojson'),
                output_path=path,
                soil_depth_band=getattr(cfg, 'SOILGRIDS_DEPTH', 'b30'),
                project=getattr(cfg, 'GEE_PROJECT', None))
        except Exception as exc:
            print(f"  [WARN] texture download failed ({exc}); scalar psi={psi_scalar} m")
            got = None
        if not got:
            return np.full(n, psi_scalar, dtype=np.float64)

        with rasterio.open(got) as src:
            sand2d = src.read(1).astype(np.float64)
            clay2d = src.read(2).astype(np.float64)
            nodata = src.nodata
        _to_np = lambda a: a.get() if hasattr(a, 'get') else np.asarray(a)
        sr = _to_np(grid_data['s_rows']); sc = _to_np(grid_data['s_cols'])
        if sr.max() >= sand2d.shape[0] or sc.max() >= sand2d.shape[1]:
            print("  [WARN] texture raster grid ≠ routing grid; "
                  f"scalar psi={psi_scalar} m")
            return np.full(n, psi_scalar, dtype=np.float64)

        sand = sand2d[sr, sc]; clay = clay2d[sr, sc]
        bad = ~np.isfinite(sand) | ~np.isfinite(clay) | (sand + clay <= 0)
        if nodata is not None:
            bad |= (sand == nodata) | (clay == nodata)
        psi = usda_psi_m(np.clip(sand, 0, 100), np.clip(clay, 0, 100))
        if bad.any():
            psi[bad] = psi_scalar
        print(f"  GA suction    |  psi(m)=[{psi.min():.3f}, {psi.max():.3f}] "
              f"mean={psi.mean():.3f}  (texture/Rawls)")
        return psi


# ═════════════════════════════════════════════════════════════════════════════
# Saturation-excess (Dunne) — Pradhan & Ogden (2010) VSA-OPM sandbox
# ═════════════════════════════════════════════════════════════════════════════
@register_mechanism('saturation_excess')
class SaturationExcessMechanism(RunoffMechanism):
    """
    Dunne saturation-excess via the Pradhan & Ogden (2010) One-Parameter Model.

    Holds the OPM sandbox — z (saturated-zone thickness), SD_max (deficit
    ceiling) and A_t (threshold contributing area), single or per precipitation
    zone — and the dynamic saturated-area mask ``self.mask`` (cells with
    upslope area > A_t).  When ``update_state`` is given an ``infiltration``
    mechanism, the sandbox recharge is capped by its infiltration capacity;
    otherwise the pervious fraction recharges with full rainfall.
    """

    def __init__(self, cfg, grid_data, shared):
        super().__init__(cfg, grid_data, shared)
        self._imperv_frac = shared['imperv_frac']   # (n_cells,) on the backend
        self._init_sandbox(cfg, grid_data, shared)

    # ── Sandbox initialisation (ported from VsaOpmMixin._init_vsa_opm) ───────
    def _init_sandbox(self, cfg, grid_data, shared):
        xp = self._xp
        params = shared['sd_params']

        Q_max = float(cfg.VSA_Q_MAX)
        if Q_max <= OPM_Q_MIN:
            raise ValueError(
                f"VSA_Q_MAX={Q_max} m³/s must be > {OPM_Q_MIN} m³/s (Q_min)."
            )

        cell_area = float(grid_data['cell_area'])
        cell_size = float(grid_data['cell_size'])
        slope_1d  = grid_data['slope_1d']
        faccum_1d = grid_data['faccum_1d']

        self._cell_area = cell_area
        self._cell_size = cell_size
        self._upslope_area = faccum_1d * cell_area     # (n_cells,) [m²]

        SD_max_initial = params['sd_max']
        sd_min         = params['sd_min']
        phi            = params['phi']
        ksat_ms        = params['ksat_ms']
        self._sd_min  = sd_min
        self._phi     = phi
        self._ksat_ms = ksat_ms

        A_1      = cell_area
        A_outlet = float(faccum_1d[-1]) * cell_area
        A_t_init = A_outlet / (1.0 - np.log(OPM_Q_MIN / Q_max))
        ratio    = A_t_init / (A_t_init - A_1)

        self._opm_A_1      = A_1
        self._opm_A_outlet = A_outlet
        self._opm_A_t_init = A_t_init

        # ── Per-polygon vs single-sandbox branching ──────────────────────────
        cell_polygon = grid_data.get('cell_polygon')
        use_per_polygon = getattr(cfg, 'VSA_PER_POLYGON', True)

        if cell_polygon is not None and use_per_polygon:
            cell_polygon = np.asarray(cell_polygon).ravel()
            precip_engine = grid_data.get('precip_engine')
            n_gauges      = getattr(precip_engine, '_n_gauges', None)
            n_polygons    = int(n_gauges) if n_gauges \
                else int(cell_polygon.max()) + 1

            _to_np = lambda a: a.get() if hasattr(a, 'get') else np.asarray(a)
            faccum_np = _to_np(faccum_1d)
            slope_np  = _to_np(slope_1d)
            dem = grid_data['dem']
            s_rows = grid_data['s_rows']
            s_cols = grid_data['s_cols']
            transform = grid_data['transform']

            divide_idx, divide_candidates, divide_xy = resolve_zone_divides(
                cell_polygon, n_polygons, faccum_np, dem, s_rows, s_cols, transform)
            slope_divide = slope_np[divide_idx]

            self._per_polygon          = True
            self._n_polygons           = n_polygons
            self._cell_polygon         = cell_polygon
            self._polygon_divide_idx   = divide_idx
            self._polygon_slope_divide = slope_divide

            deficit_raster = params.get('deficit_raster')
            reducer = getattr(cfg, 'VSA_SD_REDUCER', 'mean').lower()
            if deficit_raster:
                sd_init_arr = per_zone_sd_from_raster(
                    deficit_raster, cell_polygon, n_polygons,
                    s_rows, s_cols, reducer, sd_min, SD_max_initial,
                    divide_candidates=divide_candidates, divide_xy=divide_xy)
                n_real = int((np.abs(sd_init_arr - SD_max_initial) > 1e-9).sum())
                print(f"                |  Per-zone SD ({reducer}) over watershed "
                      f"cells: {n_real}/{n_polygons} zones populated, "
                      f"range=[{sd_init_arr.min():.3f}, {sd_init_arr.max():.3f}] m")
            else:
                sd_init_arr = np.full(n_polygons, SD_max_initial, dtype=np.float64)
            self._SD_max_initial = sd_init_arr
            self._ksat_ms = np.full(n_polygons, ksat_ms, dtype=np.float64)

            Rf_init_arr = sd_min / sd_init_arr
            H_a_arr = ratio * np.log(Rf_init_arr)
            self._opm_H_a = H_a_arr

            self._opm_z      = np.zeros(n_polygons, dtype=np.float64)
            self._opm_SD_max = sd_init_arr.copy()
            self._opm_A_t    = np.full(n_polygons, A_t_init, dtype=np.float64)

            A_t_per_cell = self._opm_A_t[cell_polygon]
            if hasattr(self._upslope_area, '__cuda_array_interface__'):
                import cupy as _cp
                A_t_per_cell = _cp.asarray(A_t_per_cell)
            self.mask = self._upslope_area > A_t_per_cell

            print(f"  OPM           |  A_outlet={A_outlet:.3e} m²"
                  f"  A_t_init={A_t_init:.3e} m²")
            print(f"                |  H_a={H_a_arr}  phi={phi}  Q_max={Q_max} m³/s")
            print(f"                |  SD_max_init={sd_init_arr}")
            print(f"                |  Per-polygon mode: {n_polygons} zones")
            print(f"                |  Initial VSA={self.mask.sum():,} cells"
                  f" ({100*self.mask.mean():.1f}% of watershed)")

            self._cell_polygon         = xp.asarray(cell_polygon)
            self._polygon_divide_idx   = xp.asarray(divide_idx)
            self._polygon_slope_divide = xp.asarray(slope_divide)
            self._SD_max_initial       = xp.asarray(sd_init_arr)
            self._ksat_ms              = xp.asarray(self._ksat_ms)
            self._opm_H_a              = xp.asarray(H_a_arr)
            self._opm_z                = xp.asarray(self._opm_z)
            self._opm_SD_max           = xp.asarray(self._opm_SD_max)
            self._opm_A_t              = xp.asarray(self._opm_A_t)
        else:
            self._per_polygon  = False
            _to_np = lambda a: a.get() if hasattr(a, 'get') else np.asarray(a)
            faccum_np = _to_np(faccum_1d)
            slope_np  = _to_np(slope_1d)
            dem = grid_data['dem']
            s_rows = grid_data['s_rows']
            s_cols = grid_data['s_cols']
            min_fa = faccum_np.min()
            candidates = np.where(faccum_np == min_fa)[0]
            elev = dem[s_rows[candidates], s_cols[candidates]]
            divide_cell = candidates[elev.argmax()]
            self._slope_divide = float(slope_np[divide_cell])
            self._divide_cell  = int(divide_cell)

            self._SD_max_initial = SD_max_initial
            Rf_init = sd_min / SD_max_initial
            H_a = ratio * np.log(Rf_init)
            self._opm_H_a = H_a

            self._opm_z      = 0.0
            self._opm_SD_max = SD_max_initial
            self._opm_A_t    = A_t_init

            self.mask = self._upslope_area > A_t_init

            print(f"  OPM           |  A_outlet={A_outlet:.3e} m²"
                  f"  A_t_init={A_t_init:.3e} m²")
            print(f"                |  H_a={H_a:.4f}  SD_max_init={SD_max_initial} m"
                  f"  phi={phi}  Q_max={Q_max} m³/s")
            print(f"                |  Initial VSA={self.mask.sum():,} cells"
                  f" ({100*self.mask.mean():.1f}% of watershed)")

    # ── Diagnostics ──────────────────────────────────────────────────────────
    def diagnostics(self):
        d = {
            "z_m":          self._opm_z.copy() if self._per_polygon else self._opm_z,
            "SD_max_t":     self._opm_SD_max.copy() if self._per_polygon else self._opm_SD_max,
            "A_t_m2":       self._opm_A_t.copy() if self._per_polygon else self._opm_A_t,
            "VSA_m2":       float(self.mask.sum()) * self._cell_area,
            "VSA_fraction": float(self.mask.sum()) / self._n_cells,
            "per_polygon":  self._per_polygon,
        }
        if self._per_polygon:
            d["n_polygons"] = self._n_polygons
        return d

    # ── Sandbox update (forward Euler) ───────────────────────────────────────
    def update_state(self, rain_1d, dt, infiltration=None):
        if self._per_polygon:
            self._update_per_polygon(rain_1d, dt, infiltration)
        else:
            self._update_single(rain_1d, dt, infiltration)

    def _divide_infiltration(self, rain_1d, infiltration):
        """Recharge rate [m/s] into each zone's sandbox at its divide cell.
        Capped by the infiltration mechanism's capacity when provided; impervious
        cells never recharge the water table."""
        xp    = self._xp
        idx   = self._polygon_divide_idx
        P_div = rain_1d[idx]
        if infiltration is None:
            return (1.0 - self._imperv_frac[idx]) * P_div
        f_p   = infiltration.capacity()[idx]
        f_div = xp.minimum(P_div, f_p)
        return (1.0 - self._imperv_frac[idx]) * f_div

    def _update_per_polygon(self, rain_1d, dt, infiltration):
        xp    = self._xp
        f_div = self._divide_infiltration(rain_1d, infiltration)   # (n_polygons,)

        q_b = (self._ksat_ms * self._polygon_slope_divide
               * self._opm_z * self._cell_size)
        dV  = (f_div * self._cell_area - q_b) * dt
        dz  = dV / (self._cell_area * self._phi)
        self._opm_z = xp.maximum(0.0, self._opm_z + dz)

        self._opm_SD_max = xp.maximum(self._sd_min,
                                      self._SD_max_initial - self._opm_z)

        Rf_t  = self._sd_min / self._opm_SD_max
        denom = self._opm_H_a - xp.log(Rf_t)
        denom_safe = xp.where(xp.abs(denom) < 1e-12, 1.0, denom)
        new_A_t    = xp.where(xp.abs(denom) < 1e-12, self._opm_A_t_init,
                              self._opm_H_a * self._opm_A_1 / denom_safe)
        self._opm_A_t = xp.clip(new_A_t, self._opm_A_1, self._opm_A_outlet)

        A_t_per_cell = self._opm_A_t[self._cell_polygon]
        self.mask    = self._upslope_area > A_t_per_cell

    def _update_single(self, rain_1d, dt, infiltration):
        di    = self._divide_cell
        P_div = float(rain_1d[di])
        if infiltration is not None:
            f_p   = float(infiltration.capacity()[di])
            f_div = (1.0 - float(self._imperv_frac[di])) * min(P_div, f_p)
        else:
            f_div = (1.0 - float(self._imperv_frac[di])) * P_div

        q_b = self._ksat_ms * self._slope_divide * self._opm_z * self._cell_size
        dV  = (f_div * self._cell_area - q_b) * dt
        dz  = dV / (self._cell_area * self._phi)
        self._opm_z = max(0.0, self._opm_z + dz)

        self._opm_SD_max = max(self._sd_min, self._SD_max_initial - self._opm_z)

        Rf_t  = self._sd_min / self._opm_SD_max
        denom = self._opm_H_a - np.log(Rf_t)
        if abs(denom) < 1e-12:
            new_A_t = self._opm_A_t_init
        else:
            new_A_t = self._opm_H_a * self._opm_A_1 / denom

        self._opm_A_t = float(np.clip(new_A_t, self._opm_A_1, self._opm_A_outlet))
        self.mask = self._upslope_area > self._opm_A_t
