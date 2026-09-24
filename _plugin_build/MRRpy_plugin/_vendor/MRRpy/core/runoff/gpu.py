"""
gpu.py
======
GPU variant of the RunoffEngine.

Device placement now flows from ``grid_data['xp']`` (CuPy in GPU mode, set by
``router.initialise_grid`` before the engine is built) into each ``RunoffMode``:
every mode builds its state with ``self._xp`` and transfers raster-derived
arrays via ``self._xp.asarray(...)``, and ``RunoffMode.get_effective_2d`` uses
``gpu_utils.to_cpu`` for the host write-back.  So the CPU classes already run
natively on CuPy — this subclass exists only for the explicit import in
``router.py`` and as an intentional marker of the GPU path.
"""

from .engine import RunoffEngine


class RunoffEngineGPU(RunoffEngine):
    """Drop-in GPU replacement for RunoffEngine (device selection via grid_data['xp'])."""
    pass
