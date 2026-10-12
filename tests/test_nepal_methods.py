# -*- coding: utf-8 -*-
"""
tests/test_nepal_methods.py
===========================
The official Nepali flood methods (MRRpy.nepal.methods) reproduce every
worked example of the compendium *Nepal Flood Estimation Methods* — the
65 km² snow-free Chure catchment of §3 — and the comparison table, validity
flags, official range and presets behave as documented.

Run:  pytest tests/test_nepal_methods.py -v
"""

import math

import numpy as np
import pytest

from MRRpy.nepal import (AGENCIES, FLOOD_METHODS, STRUCTURES, CatchmentDescriptors,
                         estimate_floods, recommend_methods, slope_area_discharge)
from MRRpy.nepal import methods as M
from MRRpy.nepal.guidelines import methods_for, return_periods_for

A = 65.0                                   # the compendium's illustration catchment


def close(a, b, rel=1.5e-3):
    """Equal to the compendium's printed value (it rounds to 0.1 m³/s)."""
    return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=0.051)


# ── §3.1 WECS/DHM 1990 ──────────────────────────────────────────────────────
def test_wecs_dhm_worked_example():
    q2, q50, q100 = M.wecs_dhm_1990(A, [2, 50, 100])
    assert close(q2, 74.4) and close(q100, 317.1)
    assert close(q50, 267.6)                       # printed with S rounded to 2.054/2.326


def test_wecs_dhm_daily_and_plus_one():
    q2, q100 = M.wecs_dhm_1990(0.0, [2, 100], daily=True)
    assert close(q2, 0.8154) and close(q100, 4.144)     # (A3000 + 1) = 1 for a snow-only basin


def test_standard_normal_variates():
    S = M.normal_variate([2, 5, 10, 20, 50, 100, 200, 500])
    printed = [0, 0.842, 1.282, 1.645, 2.054, 2.326, 2.576, 2.878]
    assert np.allclose(S, printed, atol=6e-4)


# ── §3.2 DHM 2004 ───────────────────────────────────────────────────────────
def test_dhm_2004_worked_example():
    q2, q50, q100 = M.dhm_2004(A, [2, 50, 100])
    assert close(q2, 83.0) and close(q100, 418.1) and close(q50, 346.0)
    # "About 32 % higher than WECS/DHM for the 100-year flood"
    assert round(q100 / M.wecs_dhm_1990(A, [100])[0], 2) == 1.32


# ── §3.3 MHSP 1997 ──────────────────────────────────────────────────────────
def test_mhsp_worked_example_and_tabulation():
    Q, flags = M.mhsp_1997(A, [2, 5, 10, 100, 200], "western")
    assert close(Q[3], 170.6)
    assert np.isnan(Q[0]) and np.isnan(Q[4])            # only 5, 20, 50, 100 are tabulated
    assert flags == ["not tabulated", "", "interpolated", "", "not tabulated"]
    q5, q20 = M.mhsp_1997(A, [5, 20], "western")[0]
    assert q5 < Q[2] < q20                               # 10 years sits between 5 and 20
    with pytest.raises(ValueError, match="MHSP region"):
        M.mhsp_1997(A, [100], "northern")


def test_mhsp_eastern_pair_matches_the_reviews():
    # Reviews quote "k ≈ 21.52, b ≈ 0.728" for T = 100: the Eastern pair.
    assert M.MHSP_1997["eastern"][100] == (21.5181, 0.7281)


# ── §3.4 and §3.14 Indian formulas (comparison only) ───────────────────────
def test_dickens_ryves_inglis_worked_examples():
    assert close(M.dickens(A, 11.4), 261.0) and close(M.dickens(A, 14), 320.5)
    assert close(M.ryves(A, 10.2), 164.9)
    assert close(M.inglis(A), 928.2)


# ── §3.5 Modified Dickens ───────────────────────────────────────────────────
def test_modified_dickens_worked_example():
    Q, C, p = M.modified_dickens(A, [2, 50, 100], snow_km2=0.0)
    assert round(p, 2) == 9.23
    assert round(C[2], 2) == 12.78
    assert close(Q[2], 292.6) and close(Q[0], 100.5) and close(Q[1], 258.5)


def test_modified_dickens_snow_area_enters_p():
    Q0 = M.modified_dickens(500.0, [100], 0.0)[0][0]
    Qs = M.modified_dickens(500.0, [100], 100.0)[0][0]
    assert Qs != Q0                                     # snow area enters through p
    q_variant = M.modified_dickens(500.0, [100], 100.0, denominator="A")[0][0]
    assert q_variant != Qs                              # the "/A" variant differs a little


# ── §3.8 Rational method ────────────────────────────────────────────────────
def test_rational_worked_example():
    tc = M.kirpich_tc_minutes(15000.0, 0.015)
    assert round(tc) == 161
    intensity = M.mononobe_intensity(250.0, tc / 60.0)
    assert round(float(intensity), 1) == 44.8
    assert close(M.rational_peak(0.45, intensity, A), 364.1)


# ── §3.12 catchment area ratio ──────────────────────────────────────────────
def test_area_ratio_worked_example():
    ratio = 430.0 / 1148.0
    assert round(ratio, 3) == 0.375
    assert round(float(M.area_ratio(1.0, 430.0, 1148.0, 0.8)), 3) == 0.456


# ── §3.13 slope-area method ─────────────────────────────────────────────────
def test_slope_area_manning():
    # 1 m deep, 10 m wide rectangular section: A = 10, P = 12
    q = slope_area_discharge(10.0, 12.0, 0.01, 0.035)
    assert math.isclose(q, (1 / 0.035) * 10 * (10 / 12) ** (2 / 3) * 0.1)


# ── §3.15 specific discharge ────────────────────────────────────────────────
def test_specific_discharge_worked_example():
    Q, flags = M.specific_discharge(A, [2, 25, 100, 200])
    assert close(Q[2], 516.0, rel=2e-3) and close(Q[0], 78.0, rel=2e-3)
    assert round(Q[2] / A, 2) == 7.94                    # q100 = 7.94 m³/s per km²
    assert flags[3] == "not tabulated" and np.isnan(Q[3])


# ═════════════════════════════════════════════════════════════════════════════
# The comparison table
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def chure():
    return CatchmentDescriptors(area_km2=A, flow_length_km=15.0, flow_path_slope=0.015,
                                max_elevation_m=1200.0, name="Chure example")


def test_table_rows_columns_and_status(chure):
    est = estimate_floods(chure, list(FLOOD_METHODS), [2, 10, 50, 100],
                          mhsp_region="western", runoff_coefficient=0.45,
                          rain_24h={2: 120, 100: 250})
    t = est.table
    assert list(t.columns[3:7]) == ["Q2", "Q10", "Q50", "Q100"]
    assert est.columns == ["Q2", "Q10", "Q50", "Q100"]
    status = dict(zip(t["key"], t["status"]))
    assert status["rational"] == "outside its range"          # 65 km² > 50 km² (WECS 2019)
    assert status["physics"] == "not run"                     # needs a model run
    assert status["frequency"] == "needs input"
    assert status["dickens"] == "comparison only"
    assert status["wecs_dhm"] == "use with caution"           # < 100 km² and a Chure stream
    assert est.values("wecs_dhm")[100] == pytest.approx(317.1, abs=0.06)
    assert "interpolated" in est.flags.loc["MHSP 1997 (NEA)", "Q10"]
    assert "Q10 rain interpolated" in t.loc["Rational method", "flags"]   # R24 between 2 and 100


def test_official_range_excludes_daily_and_comparison(chure):
    est = estimate_floods(chure, ["wecs_dhm", "dhm_2004", "modified_dickens", "wecs_dhm_daily",
                                  "inglis"], [2, 100])
    env = est.envelope
    assert env.loc[100, "n_methods"] == 3
    assert env.loc[100, "min"] == pytest.approx(292.6, abs=0.06)    # Modified Dickens
    assert env.loc[100, "max"] == pytest.approx(418.1, abs=0.06)    # DHM 2004
    assert "Inglis" not in env.loc[100, "methods"]
    assert "daily" not in env.loc[100, "methods"]


def test_compare_places_a_result_against_the_range(chure):
    est = estimate_floods(chure, ["wecs_dhm", "dhm_2004"], [2, 100])
    est.add_result("physics", "MRRpy physics model (design storm)", {100: 500.0})
    c = est.compare("physics")
    assert c.loc[100, "position"] == "above"
    assert c.loc[2, "position"] == ""                          # not run at 2 years
    est.add_result("physics", "MRRpy physics model (design storm)", {100: 350.0})
    assert est.compare("physics").loc[100, "position"] == "inside"


def test_missing_input_is_reported_not_raised():
    site = CatchmentDescriptors(area_km2=8.0)                  # no L, S
    est = estimate_floods(site, ["rational", "mhsp_1997", "area_ratio"], [10],
                          runoff_coefficient=0.3, rain_24h={10: 150})
    notes = {r["key"]: r["notes"][0] for r in est.rows}
    assert {r["status"] for r in est.rows} == {"needs input"}
    assert "longest flow path" in notes["rational"]
    assert "MHSP region" in notes["mhsp_1997"]
    assert "Donor" in notes["area_ratio"]


def test_bad_input_value_is_reported():
    site = CatchmentDescriptors(area_km2=8.0, flow_length_km=3, flow_path_slope=0.05)
    est = estimate_floods(site, ["rational"], [10], runoff_coefficient=1.7, rain_24h={10: 150})
    assert est.rows[0]["status"] == "needs input" and "(0, 1]" in est.rows[0]["notes"][0]


def test_validity_flags():
    small = CatchmentDescriptors(area_km2=5.0, flow_length_km=3, flow_path_slope=0.05)
    est = estimate_floods(small, ["specific_discharge", "rational"], [2],
                          runoff_coefficient=0.4, rain_24h={2: 100})
    st = {r["key"]: r["status"] for r in est.rows}
    assert st == {"specific_discharge": "outside", "rational": "ok"}
    tiny = CatchmentDescriptors(area_km2=0.3)                  # p = 2000 > 1185
    assert estimate_floods(tiny, ["modified_dickens"], [2]).rows[0]["status"] == "outside"
    high = CatchmentDescriptors(area_km2=40.0, area_below_3000_km2=0.0, area_below_5000_km2=10)
    r = estimate_floods(high, ["dhm_2004"], [2]).rows[0]
    assert r["status"] == "outside" and np.isnan(r["Q"][0])


def test_rain_interpolation_and_series_fit():
    site = CatchmentDescriptors(area_km2=10.0, flow_length_km=5, flow_path_slope=0.03)
    r24, flags, _n, _f = M.design_rainfall({"rain_24h": {2: 100, 100: 300}}, [2, 10, 100, 500])
    assert r24[0] == 100 and r24[2] == 300 and 100 < r24[1] < 300 and np.isnan(r24[3])
    assert flags[1] == "rain interpolated" and flags[3] == "no rainfall for this T"
    years = [120, 95, 160, 140, 210, 130, 175, 99, 150, 188, 142, 115, 230, 165, 128]
    est = estimate_floods(site, ["rational"], [2, 100], runoff_coefficient=0.4,
                          rain_annual_max=years, rain_distribution="gev")
    assert est.rows[0]["status"] == "ok" and np.all(np.isfinite(est.rows[0]["Q"]))
    assert "GEV" in "; ".join(est.rows[0]["notes"])


def test_frequency_and_area_ratio_rows():
    site = CatchmentDescriptors(area_km2=430.0)
    peaks = [410, 380, 655, 520, 300, 720, 450, 390, 610, 505, 470, 820, 360, 540, 430,
             600, 495, 380, 700, 455]
    est = estimate_floods(site, ["frequency", "area_ratio"], [2, 100], flood_annual_max=peaks,
                          donor_area_km2=1148.0, donor_floods={2: 900.0, 100: 4200.0},
                          area_ratio_exponent=0.8)
    f = est.row("frequency")
    assert f["status"] == "ok" and f["band"][100][0] < f["Q"][1] < f["band"][100][1]
    ar = est.row("area_ratio")
    assert ar["Q"][1] == pytest.approx(4200 * (430 / 1148) ** 0.8)
    assert ar["status"] == "caution"          # the compendium's Ratuwa/Kankai pair: 0.37×
    near = estimate_floods(CatchmentDescriptors(area_km2=900.0), ["area_ratio"], [100],
                           donor_area_km2=1148.0, donor_floods={100: 4200.0})
    assert near.rows[0]["status"] == "ok"


def test_unknown_names_raise():
    with pytest.raises(ValueError, match="Unknown method"):
        estimate_floods({"area_km2": 10}, ["wecs"])
    with pytest.raises(ValueError, match="Unknown input"):
        estimate_floods({"area_km2": 10}, ["wecs_dhm"], rainfall=3)
    with pytest.raises(ValueError, match="above 1 year"):
        estimate_floods({"area_km2": 10}, ["wecs_dhm"], [1])


def test_markdown_marks_interpolated_and_extrapolated(chure):
    md = estimate_floods(chure, ["wecs_dhm", "mhsp_1997"], [10, 200],
                         mhsp_region="western").to_markdown()
    assert "*370.4" in md                 # WECS/DHM beyond 100 years
    assert "≈94.66" in md                 # MHSP 10 years, interpolated


# ═════════════════════════════════════════════════════════════════════════════
# Presets and the quick guide
# ═════════════════════════════════════════════════════════════════════════════
def test_agency_presets_only_name_implemented_methods():
    for a in AGENCIES.values():
        assert set(a.methods) <= set(FLOOD_METHODS), a.key
    assert methods_for("dolidar_2015") == ["dhm_2004", "rational", "frequency"]
    assert "B.D. Richards" in AGENCIES["dowri_2019"].not_yet
    assert "physics" in methods_for("dor_bridge")
    assert not any(FLOOD_METHODS[k].group == "comparison" for k in methods_for("all"))


def test_structures_set_the_design_return_periods():
    assert return_periods_for("bridge") == [2, 100]
    assert return_periods_for("culvert") == [2, 25]
    assert return_periods_for("study") == [2, 5, 10, 20, 50, 100, 200, 500]
    assert STRUCTURES["barrage"].design == (100, 500)
    assert "Cl. 3.2" in STRUCTURES["bridge"].describe()


def test_quick_guide_by_size():
    small, _ = recommend_methods(CatchmentDescriptors(area_km2=8))
    assert small == ["modified_dickens", "rational", "physics"]
    mid, why = recommend_methods(CatchmentDescriptors(area_km2=65, max_elevation_m=1200),
                                 has_gauge=True, has_donor=True)
    assert {"wecs_dhm", "dhm_2004", "mhsp_1997", "physics", "frequency", "area_ratio"} <= set(mid)
    assert any("Chure/Terai" in w for w in why)
    big, _ = recommend_methods(CatchmentDescriptors(area_km2=2000))
    assert "rational" not in big and "specific_discharge" in big


def test_describe_methods_lists_everything():
    text = M.describe_methods()
    for key in FLOOD_METHODS:
        assert key in text
