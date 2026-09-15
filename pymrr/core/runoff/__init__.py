# -*- coding: utf-8 -*-
"""
pymrr.core.runoff — rainfall → effective-runoff generation.

Modules
-------
engine     : RunoffEngine — dispatches by cfg.RUNOFF_SOURCE
             ('none' | 'coefficient' | 'raster' | 'scs_cn' | 'physical').
             Whole runoff generators are pluggable: subclass RunoffMode and
             decorate it with @register('my_mode') to add one (even from another
             package) without editing the engine, then feed routing unchanged.
physical   : PhysicalRunoffMode — the 'physical' generator, composing the
             mechanisms below.
mechanisms : impervious / infiltration_excess / saturation_excess as
             self-contained, combinable physics components (pluggable via
             @register_mechanism).
soil       : soil-parameter resolution (SD_max, phi, Rawls suction table).
gpu        : RunoffEngineGPU — CuPy device-array variant (import explicitly;
             kept out of this namespace so CPU-only installs never touch CuPy).
"""

from .engine import RunoffEngine, RunoffMode, register, RUNOFF_MODES
from .mechanisms import (
    RunoffMechanism,
    register_mechanism,
    MECHANISM_REGISTRY,
)
from .soil import (
    OPM_SD_MIN,
    OPM_Q_MIN,
    resolve_sd_params,
    resolve_zone_divides,
    per_zone_sd_from_raster,
    usda_psi_m,
)

__all__ = [
    "RunoffEngine", "RunoffMode", "register", "RUNOFF_MODES",
    "RunoffMechanism", "register_mechanism", "MECHANISM_REGISTRY",
    "OPM_SD_MIN", "OPM_Q_MIN",
    "resolve_sd_params", "resolve_zone_divides", "per_zone_sd_from_raster",
    "usda_psi_m",
]
