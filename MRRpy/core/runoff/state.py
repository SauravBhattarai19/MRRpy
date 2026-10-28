# -*- coding: utf-8 -*-
"""
state.py — the runoff state that a restart file carries (RESTART_FROM).

Runoff modes and mechanisms list two kinds of attributes:

* ``state_attrs()`` — what changes from step to step and must be carried over
  (e.g. Green-Ampt infiltrated depth F, the saturation-excess sandbox z);
* ``param_attrs()`` — per-cell parameters fixed at start-up (e.g. Ksat, the
  initial moisture deficit).  They are not restored, only compared: a restart
  into a model whose soil came out different (a missing raster, another date)
  is refused rather than run quietly with the wrong soil.

Values move to the host as NumPy arrays (plain floats as 0-d arrays) and back to
the backend (NumPy or CuPy) with the dtype and shape of the live attribute.
"""

import numpy as np

from ...utils import gpu_utils


def to_host(value):
    """A NumPy copy of an attribute (scalars become 0-d float arrays)."""
    if isinstance(value, (bool, int, float, np.number)):
        return np.asarray(float(value))
    return np.array(gpu_utils.to_cpu(value), copy=True)


def to_backend(saved, current, xp, name):
    """*saved* in the form of the live attribute *current* (float or array)."""
    if isinstance(current, (bool, int, float, np.number)):
        return float(np.asarray(saved))
    saved = np.asarray(saved)
    if tuple(saved.shape) != tuple(current.shape):
        raise ValueError(f"saved runoff state '{name}' has shape {saved.shape}, "
                         f"the model has {tuple(current.shape)}")
    return xp.array(saved, dtype=current.dtype, copy=True)


class StateMixin:
    """get_state / set_state / get_params from ``state_attrs`` / ``param_attrs``."""

    def state_attrs(self):
        """Attributes carried from one step to the next (none by default)."""
        return ()

    def param_attrs(self):
        """Per-cell parameters fixed at start-up (none by default)."""
        return ()

    def get_state(self):
        return {k: to_host(getattr(self, k)) for k in self.state_attrs()}

    def set_state(self, state):
        missing = [k for k in self.state_attrs() if k not in state]
        if missing:
            raise ValueError(f"saved runoff state has no {missing}")
        for k in self.state_attrs():
            setattr(self, k, to_backend(state[k], getattr(self, k), self._xp, k))

    def get_params(self):
        return {k: to_host(getattr(self, k)) for k in self.param_attrs()}
