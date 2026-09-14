# -*- coding: utf-8 -*-
"""
physical.py — the process-based, composable runoff generator.

``PhysicalRunoffMode`` is the ``RUNOFF_SOURCE='physical'`` mode.  It instantiates
whichever of the three physics mechanisms (mechanisms.py) the user selected in
``RUNOFF_MECHANISMS`` and combines them per cell without double-counting:

    runoff = rain · [ Imp + (1 − Imp) · max(in_VSA, infil_excess_frac) ]

- Impervious fraction Imp always sheds rain (urban contributes regardless).
- On the pervious remainder a cell sheds all rain if it is in the saturated
  source area (Dunne / saturation-excess), otherwise the Green-Ampt
  infiltration-excess fraction (Horton).  ``max`` caps shedding at 100 % of rain
  and makes the two pervious mechanisms mutually exclusive per cell.

Any mechanism may be absent: a single mechanism runs alone (e.g.
``['infiltration_excess']`` is a standalone GSSHA/HEC-HMS-style infiltration
model; ``['impervious']`` is a pure land-use runoff study; ``['saturation_excess']``
is Dr. Nawa's VSA-OPM), and any subset composes.

Mechanics live in mechanisms.py; whole *alternative* runoff generators (curve
number, coefficient, raster, or a third-party method) register one level up, at
the RunoffMode registry in engine.py.
"""

import numpy as np

from ...utils import gpu_utils
from .engine import RunoffMode, register
from .mechanisms import MECHANISM_REGISTRY
from .soil import resolve_sd_params


@register('physical')
class PhysicalRunoffMode(RunoffMode):
    """Composable, process-based runoff generation."""

    name = 'physical'

    def __init__(self, cfg, grid_data):
        RunoffMode.__init__(self, cfg, grid_data)

        active = list(getattr(cfg, 'RUNOFF_MECHANISMS', []))
        cell_size = float(grid_data['cell_size'])
        xp = gpu_utils.get_xp(grid_data.get('faccum_1d'))

        # Soil params (SD_max / phi / K_sat / deficit) are needed by the
        # saturation-excess sandbox and the infiltration Δθ₀ — resolve once.
        need_soil = ('saturation_excess' in active) or ('infiltration_excess' in active)
        shared = {
            'xp': xp,
            'cell_size': cell_size,
            'cell_area': float(grid_data['cell_area']),
            'sd_params': resolve_sd_params(cfg, cell_size) if need_soil else None,
        }

        # Build in dependency order: impervious first (its fraction feeds the
        # saturation sandbox recharge), then infiltration, then saturation.
        self._imperv = self._make('impervious', active, cfg, grid_data, shared)
        shared['imperv_frac'] = (self._imperv.frac if self._imperv is not None
                                 else xp.zeros(self._n_cells, dtype=np.float64))
        self._infil = self._make('infiltration_excess', active, cfg, grid_data, shared)
        self._sat   = self._make('saturation_excess',   active, cfg, grid_data, shared)

        self._xp = xp
        print(f"  RunoffEngine    |  mechanisms: "
              f"{[m for m in ('impervious', 'infiltration_excess', 'saturation_excess') if m in active] or 'none'}")

    @staticmethod
    def _make(name, active, cfg, grid_data, shared):
        return MECHANISM_REGISTRY[name](cfg, grid_data, shared) if name in active else None

    # ── Interface (forward Euler) ─────────────────────────────────────────────
    def get_effective_1d(self, t_seconds, rain_1d):
        xp = self._xp
        imp = self._imperv.frac if self._imperv is not None else 0.0
        vsa = self._sat.mask    if self._sat    is not None else None
        exc = self._infil.excess_fraction(rain_1d) if self._infil is not None else 0.0

        if vsa is not None:
            pervious_frac = xp.where(vsa, 1.0, exc)
        else:
            pervious_frac = exc

        # ── Mechanism decomposition (per-cell rates [m/s]) ───────────────────
        # imperv + dunne + horton == effective runoff, exactly.
        one_imp = 1.0 - imp
        self._last_imperv_rate = rain_1d * imp
        if vsa is not None:
            self._last_dunne_rate  = rain_1d * one_imp * xp.where(vsa, 1.0, 0.0)
            self._last_horton_rate = rain_1d * one_imp * xp.where(vsa, 0.0, exc)
        else:
            self._last_dunne_rate  = rain_1d * 0.0
            self._last_horton_rate = rain_1d * one_imp * exc if self._infil is not None \
                else rain_1d * 0.0

        return rain_1d * (imp + one_imp * pervious_frac)

    def update_state(self, rain_1d, dt):
        # Saturation sandbox reads the current-step infiltration capacity, THEN
        # the infiltration mechanism advances its cumulative F (forward Euler,
        # matching get_effective_1d).
        if self._sat is not None:
            self._sat.update_state(rain_1d, dt, infiltration=self._infil)
        if self._infil is not None:
            self._infil.update_state(rain_1d, dt)

    def is_active(self, t_seconds):
        return (self._imperv is not None
                or self._infil is not None
                or (self._sat is not None and bool(self._sat.mask.any())))

    # ── Back-compat: VSA sandbox diagnostics (saturation-excess only) ─────────
    def get_opm_diagnostics(self):
        return self._sat.diagnostics() if self._sat is not None else {}
