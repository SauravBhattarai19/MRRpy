# -*- coding: utf-8 -*-
"""
MRRpy.nepal — MRRpy-Nepal: the official Nepali flood-estimation methods
next to the physics-based model.

The physics core of MRRpy (DEM → rain → runoff → routing) is unchanged.
This subpackage adds what a Nepali design study needs around it:

descriptors   catchment numbers measured from the DEM: A, A3000, A5000,
              snow area, flow length and slope (``measure_catchment``)
methods       the official methods — WECS/DHM 1990, DHM 2004, MHSP 1997,
              Modified Dickens, specific discharge (WECS 2019), Rational,
              frequency analysis, catchment area ratio, and the Indian
              formulas for comparison (``estimate_floods``)
frequency     Gumbel, Log-Pearson III and GEV (L-moments) fits with
              bootstrap confidence bands
guidelines    agency presets (which methods each manual names), design
              return periods by structure, and the compendium's quick guide
design_storm  design rainfall the Nepali way: R24 spread with the Mononobe
              curve into a centre-peaked hyetograph for the physics model
physics       design-flood runs of the MRRpy model, one per return period
flows         monthly and low flows: MIP 1982, WECS/DHM and MHSP monthly,
              catchment area ratio, 80 % dependable flow, e-flow, 7Q10
study         ``NepalStudy`` — site → methods → table, chart and report

Quick start
-----------
    from MRRpy.nepal import CatchmentDescriptors, estimate_floods
    est = estimate_floods(CatchmentDescriptors(area_km2=65), ["wecs_dhm", "dhm_2004"])
    print(est.table)

    from MRRpy.nepal import NepalStudy          # the whole workflow
    study = NepalStudy.from_results("results/", agency="dowri_2019", structure="weir",
                                    inputs={"rain_24h": {50: 230, 100: 250}})
    result = study.run()

Interfaces: ``NepalForm()`` in Jupyter (needs ipywidgets), ``MRRpy nepal …``
on the command line, and the QGIS Processing algorithms of MRRpy_plugin.
Every coefficient comes from the compendium *Nepal Flood Estimation
Methods*; see NEPAL_PLAN.md for what is included, deferred or left out.
"""

from .descriptors import CatchmentDescriptors, measure_catchment
from .methods import (FLOOD_METHODS, GROUPS, INPUTS, OFFERED_RETURN_PERIODS,
                      REGIONAL_METHODS, TOR_RETURN_PERIODS, FloodEstimates,
                      describe_methods, estimate_floods, slope_area_discharge)
from .guidelines import AGENCIES, STRUCTURES, recommend_methods
from .design_storm import design_hyetograph
from .physics import nepal_design_config, run_design_floods
from .flows import monthly_flows
from .study import NepalResult, NepalStudy

__all__ = [
    "CatchmentDescriptors", "measure_catchment",
    "FLOOD_METHODS", "GROUPS", "INPUTS", "OFFERED_RETURN_PERIODS", "REGIONAL_METHODS",
    "TOR_RETURN_PERIODS", "FloodEstimates", "describe_methods", "estimate_floods",
    "slope_area_discharge",
    "AGENCIES", "STRUCTURES", "recommend_methods",
    "design_hyetograph", "nepal_design_config", "run_design_floods",
    "monthly_flows",
    "NepalStudy", "NepalResult", "NepalForm",
]


def __getattr__(name):
    # The Jupyter form needs ipywidgets, so import it only when it is used.
    if name == "NepalForm":
        from .form import NepalForm
        return NepalForm
    raise AttributeError(f"module 'MRRpy.nepal' has no attribute {name!r}")
