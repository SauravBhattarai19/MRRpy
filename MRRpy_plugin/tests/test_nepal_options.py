# -*- coding: utf-8 -*-
"""
tests/test_nepal_options.py
===========================
The plain-Python glue of the MRRpy-Nepal Processing algorithms
(processing/nepal_options.py) — no QGIS needed:

    pytest MRRpy_plugin/tests/test_nepal_options.py -v
"""

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from MRRpy_plugin.processing import nepal_options as o  # noqa: E402


def test_option_lists_come_from_the_core():
    from MRRpy.nepal import AGENCIES, FLOOD_METHODS, STRUCTURES
    assert [k for _l, k in o.METHODS] == list(FLOOD_METHODS)
    assert [k for _l, k in o.AGENCIES] == list(AGENCIES)
    assert [k for _l, k in o.STRUCTURES] == list(STRUCTURES)
    assert o.AGENCIES[0][1] == "recommended" and o.STRUCTURES[0][1] == "study"
    assert o.REGIONS[0][1] is None and o.key(o.REGIONS, 1) == "western"
    assert o.keys(o.PERIODS, [0, 6]) == [2, 100]


def test_parse_pairs_and_periods():
    assert o.parse_pairs("2=120, 100=250") == {2.0: 120.0, 100.0: 250.0}
    assert o.parse_pairs("2: 120 100: 250") == {2.0: 120.0, 100.0: 250.0}
    assert o.parse_pairs("") is None and o.parse_periods(" 50, 100 ") == [50.0, 100.0]
    with pytest.raises(ValueError, match="pairs"):
        o.parse_pairs("2 120")


def test_build_study_from_typed_numbers():
    s = o.build_study({"area": 65, "length_km": 15, "slope": 0.015, "agency": "wecs_2019",
                       "methods": [], "structure": "bridge", "return_periods": [],
                       "runoff_coefficient": 0.45, "rain_24h": "100=250", "mhsp_region": None,
                       "curve_number": 75.0, "physics_T": "", "output_dir": ""})
    assert s.site == {"numbers": {"area_km2": 65.0, "flow_length_km": 15.0, "flow_path_slope": 0.015}}
    assert s.chosen_methods() == ["wecs_dhm", "dhm_2004", "specific_discharge", "rational"]
    assert s.chosen_return_periods() == [2, 100]
    assert s.inputs == {"runoff_coefficient": 0.45, "rain_24h": {100.0: 250.0}}
    res = s.run(physics=False, save=False, log=None)
    assert res.estimates.values("wecs_dhm")[100] == pytest.approx(317.1, abs=0.06)


def test_build_study_results_folder_and_explicit_lists():
    s = o.build_study({"results_dir": "/data/results", "methods": ["dhm_2004", "frequency"],
                       "return_periods": [2, 50], "flood_series": "peaks.csv",
                       "flood_distribution": "gev", "physics_T": "50, 100", "climate_factor": 1.1})
    assert s.site == {"results": "/data/results"}
    assert s.methods == ["dhm_2004", "frequency"] and s.return_periods == [2.0, 50.0]
    assert s.inputs["flood_annual_max"] == "peaks.csv"
    assert s.physics["return_periods"] == [50.0, 100.0] and s.physics["climate_factor"] == 1.1


def test_build_study_needs_a_site():
    with pytest.raises(ValueError, match="results folder"):
        o.build_study({"area": None})
