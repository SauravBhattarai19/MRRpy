# -*- coding: utf-8 -*-
"""
tests/test_nepal_form.py
========================
The Jupyter interface of MRRpy-Nepal (NepalForm), driven from code: presets
tick methods and return periods, each method shows only its inputs, the
estimates and monthly flows are computed, and a study round-trips through
the form.  Skipped without ipywidgets.

Run:  pytest tests/test_nepal_form.py -v
"""

import pytest

pytest.importorskip("ipywidgets")

from MRRpy.nepal import NepalForm, NepalStudy   # noqa: E402


def _shown(w):
    return w.layout.display != "none"


@pytest.fixture
def form():
    f = NepalForm()
    f.site_mode.value = "numbers"
    f.area.value = 65.0
    f.num["flow_length_km"].value = "15"
    f.num["flow_path_slope"].value = "0.015"
    return f


def test_presets_tick_methods_and_return_periods(form):
    assert form.methods[:2] == ["wecs_dhm", "dhm_2004"]          # recommended, not yet measured
    assert form.return_periods == [2, 5, 10, 20, 50, 100, 200, 500]
    form.agency.value = "dolidar_2015"
    assert form.methods == ["dhm_2004", "rational", "frequency"]
    form.structure.value = "culvert"
    assert form.return_periods == [2, 25]
    assert "Not yet" not in form.design_note.value
    form.agency.value = "dowri_2019"
    assert "B.D. Richards" in form.design_note.value


def test_branches_follow_the_ticks(form):
    form.agency.value = "nea_1997"
    assert _shown(form.method_branches["mhsp_1997"]) and not _shown(form.rain_box)
    form.method_checks["rational"].value = True
    assert _shown(form.rain_box) and _shown(form.inp["rain_24h"])
    form.rain_mode.value = "series"
    assert _shown(form.inp["rain_annual_max"]) and not _shown(form.inp["rain_24h"])
    form.site_mode.value = "results"
    assert _shown(form.branch_results) and not _shown(form.branch_numbers)


def test_measure_then_recommended(form):
    d = form.measure()
    assert d.area_km2 == 65.0
    assert "physics" in form.methods                             # recommendation for 12–500 km²
    form.method_checks["physics"].value = False                  # a hand change survives …
    form.measure()
    assert "physics" not in form.methods                         # … a second measurement


def test_compute_shows_table_and_chart(form):
    form.agency.value = "wecs_2019"
    form.structure.value = "bridge"
    form.inp["runoff_coefficient"].value = "0.45"
    form.inp["rain_24h"].value = "2: 120, 100: 250"
    res = form.compute()
    assert [r["key"] for r in res.estimates.rows] == ["wecs_dhm", "dhm_2004",
                                                      "specific_discharge", "rational"]
    html = form.results_box.children[0].value
    assert "317.1" in html and "Official range" in html and "outside its range" in html
    assert type(form.results_box.children[-1]).__name__ == "Image"
    code = form.to_python()
    assert "NepalStudy.from_dict(" in code and "'rain_24h': {2: 120.0, 100: 250.0}" in code


def test_problems_are_reported(form):
    form.inp["rain_24h"].value = "2 120"
    form.agency.value = "dolidar_2015"
    with pytest.raises(ValueError, match="return period: value"):
        form.study
    form.site_mode.value = "dem"
    with pytest.raises(ValueError, match="DEM file"):
        form.site()


def test_monthly_tab(form):
    form.mip_region.value = 4
    form.mip_measured.value = "2024-02-15 = 1.5"
    form.mmp.value = "1500"
    form.mon_checks["mhsp_1997"].value = True
    mf = form.compute_monthly()
    assert "Lower of WECS/DHM and MIP" in mf.table.index
    assert "E-flow" in form.mon_box.value


def test_study_roundtrip_through_the_form(tmp_path):
    study = NepalStudy.from_numbers(30.0, name="Mohana", agency="doed_2018", structure="weir",
                                    methods=["wecs_dhm", "mhsp_1997", "area_ratio"],
                                    return_periods=[2, 50, 100],
                                    inputs={"mhsp_region": "western", "donor_area_km2": 120.0,
                                            "donor_floods": {50: 400.0, 100: 480.0}},
                                    physics={"curve_number": 82.0})
    f = NepalForm(study)
    assert f.methods == ["wecs_dhm", "mhsp_1997", "area_ratio"]   # not the agency's preset
    assert f.return_periods == [2, 50, 100]
    assert f.inp["mhsp_region"].value == "western" and f.phys["curve_number"].value == 82.0
    again = f.study
    assert again.inputs["donor_floods"] == {50.0: 400.0, 100.0: 480.0}
    assert again.methods == study.methods and again.name == "Mohana"
