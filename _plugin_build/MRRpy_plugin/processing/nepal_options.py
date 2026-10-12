# -*- coding: utf-8 -*-
"""
nepal_options.py
================
Plain-Python glue for the MRRpy-Nepal Processing algorithms (alg_nepal.py):
the option lists the dialogs show, and ``build_study`` — the mapping from
the dialog's values to an ``MRRpy.nepal.NepalStudy``.  No QGIS imports, so
it is tested without QGIS (MRRpy_plugin/tests/test_nepal_options.py).
"""

from ..bridge import ensure_core

ensure_core()

from MRRpy.nepal import frequency as _fq                     # noqa: E402
from MRRpy.nepal import guidelines as _gl                    # noqa: E402
from MRRpy.nepal.design_storm import PATTERNS as _PATTERNS   # noqa: E402
from MRRpy.nepal.methods import (FLOOD_METHODS as _METHODS,  # noqa: E402
                                 MHSP_REGIONS as _REGIONS,
                                 OFFERED_RETURN_PERIODS as _PERIODS,
                                 parse_table as _parse_table)
from MRRpy.nepal.study import NepalStudy                     # noqa: E402

# Dropdown entries: (label, key), in display order.
METHODS = [(f"{m.name} — {m.gives}", k) for k, m in _METHODS.items()]
AGENCIES = [(a.label, a.key) for a in _gl.AGENCIES.values()]
STRUCTURES = [(s.label, s.key) for s in _gl.STRUCTURES.values()]
PERIODS = [(f"{t} years", t) for t in _PERIODS]
REGIONS = [("(not set)", None)] + [(r.capitalize(), r) for r in _REGIONS]
DISTRIBUTIONS = [(_fq.DISTRIBUTION_LABELS[d], d) for d in _fq.DISTRIBUTIONS]
PATTERNS = [(label, key) for key, label in _PATTERNS.items()]


def labels(options):
    return [label for label, _key in options]


def keys(options, indices):
    """Keys of the chosen entries (indices from a multi-select enum)."""
    return [options[int(i)][1] for i in (indices or [])]


def key(options, index):
    return options[int(index)][1]


def parse_pairs(text):
    """'2=120, 100=250' (or '2: 120 …') → {2.0: 120.0, 100.0: 250.0}; '' → None."""
    return _parse_table(text)


def parse_periods(text):
    """'50, 100' → [50.0, 100.0]; '' → None."""
    text = (text or "").strip()
    if not text:
        return None
    return [float(x) for x in text.replace(";", ",").replace(",", " ").split()]


def build_study(v):
    """
    The NepalStudy for a dict of dialog values:

    results_dir  folder of a DEM pre-processing run ('' → typed numbers)
    area, area_below_3000, area_below_5000, snow_area, length_km, slope
                 typed catchment numbers (None = not given)
    agency, methods (list of keys, [] = the agency's), structure,
    return_periods (list, [] = the structure's), site_name,
    mhsp_region, runoff_coefficient, rain_24h (text), rain_series (path),
    rain_distribution, flood_series (path), flood_distribution,
    donor_area, donor_floods (text), donor_series (path), area_exponent,
    curve_number, physics_T (text), storm_duration, climate_factor, output_dir
    """
    folder = (v.get("results_dir") or "").strip()
    if folder:
        site = {"results": folder}
    else:
        if not v.get("area"):
            raise ValueError("Give the results folder of a DEM pre-processing run, or type the "
                             "catchment area.")
        numbers = {"area_km2": float(v["area"])}
        for name, field in (("area_below_3000", "area_below_3000_km2"),
                            ("area_below_5000", "area_below_5000_km2"),
                            ("snow_area", "snow_area_km2"), ("length_km", "flow_length_km"),
                            ("slope", "flow_path_slope")):
            if v.get(name) not in (None, ""):
                numbers[field] = float(v[name])
        site = {"numbers": numbers}
    inputs = {}
    if v.get("mhsp_region"):
        inputs["mhsp_region"] = v["mhsp_region"]
    if v.get("runoff_coefficient") not in (None, ""):
        inputs["runoff_coefficient"] = float(v["runoff_coefficient"])
    rain = parse_pairs(v.get("rain_24h"))
    if rain:
        inputs["rain_24h"] = rain
    elif (v.get("rain_series") or "").strip():
        inputs["rain_annual_max"] = v["rain_series"].strip()
    if v.get("rain_distribution"):
        inputs["rain_distribution"] = v["rain_distribution"]
    if (v.get("flood_series") or "").strip():
        inputs["flood_annual_max"] = v["flood_series"].strip()
    if v.get("flood_distribution"):
        inputs["flood_distribution"] = v["flood_distribution"]
    if v.get("donor_area") not in (None, ""):
        inputs["donor_area_km2"] = float(v["donor_area"])
    donor = parse_pairs(v.get("donor_floods"))
    if donor:
        inputs["donor_floods"] = donor
    elif (v.get("donor_series") or "").strip():
        inputs["donor_annual_max"] = v["donor_series"].strip()
    if v.get("area_exponent") not in (None, ""):
        inputs["area_ratio_exponent"] = float(v["area_exponent"])
    physics = {}
    if v.get("curve_number") not in (None, ""):
        physics["curve_number"] = float(v["curve_number"])
    periods = parse_periods(v.get("physics_T"))
    if periods:
        physics["return_periods"] = periods
    if v.get("storm_duration") not in (None, ""):
        physics["duration_h"] = float(v["storm_duration"])
    if v.get("climate_factor") not in (None, ""):
        physics["climate_factor"] = float(v["climate_factor"])
    methods = list(v.get("methods") or []) or None
    periods = [float(t) for t in v.get("return_periods") or []] or None
    return NepalStudy(site, name=(v.get("site_name") or "").strip(),
                      agency=v.get("agency") or "recommended",
                      structure=v.get("structure") or None, methods=methods,
                      return_periods=periods, inputs=inputs, physics=physics,
                      output_dir=v.get("output_dir") or None)
