# -*- coding: utf-8 -*-
"""
vsa_opm.core.precip — precipitation forcing engines.

Modules
-------
engine    : PrecipEngine — uniform / Thiessen / IDW / IMERG / Open-Meteo
            (thiessen or IDW) rainfall fields on the routing grid.
openmeteo : Open-Meteo weather-model rain (forecast or past weather) as
            pseudo-gauges; HTTP only, no account needed.
gpu       : PrecipEngineGPU — CuPy device-array variant (import explicitly;
            kept out of this namespace so CPU-only installs never touch CuPy).
"""

from .engine import PrecipEngine

__all__ = ["PrecipEngine"]
