# -*- coding: utf-8 -*-
"""
tests/test_nepal_study.py
=========================
NepalStudy end to end: typed numbers; a DEM delineated on the spot, measured,
estimated and simulated with a design storm through the physics model; the
saved table, chart and report; study files; and the two Nepal bankfull-flow
presets added to the core.

Run:  pytest tests/test_nepal_study.py -v
"""

import os

import numpy as np
import pandas as pd
import pytest

from MRRpy import Config
from MRRpy.nepal import NepalStudy, nepal_design_config, run_design_floods
from MRRpy.nepal.study import PHYSICS_DEFAULTS


def test_numbers_study_without_saving():
    study = NepalStudy.from_numbers(65.0, flow_length_km=15, flow_path_slope=0.015,
                                    name="Chure", agency="wecs_2019", structure="bridge",
                                    inputs={"runoff_coefficient": 0.45, "rain_24h": {100: 250}})
    assert study.folder is None
    res = study.run(log=None)
    assert res.files == {}
    keys = [r["key"] for r in res.estimates.rows]
    assert keys == ["wecs_dhm", "dhm_2004", "specific_discharge", "rational"]
    assert list(res.table.columns[3:5]) == ["Q2", "Q100"]       # bridge: 2 and 100 years
    assert res.structure.key == "bridge" and "WECS" in res.agency.label
    assert any("Under 12" in w or "12–500" in w for w in res.recommendation)
    assert "Chure" in res.report() and "## Official range" in res.report()


def test_numbers_study_physics_needs_a_dem(tmp_path):
    study = NepalStudy.from_numbers(20.0, methods=["wecs_dhm", "physics"], return_periods=[100],
                                    inputs={"rain_24h": {100: 200}}, output_dir=tmp_path)
    res = study.run(log=None)
    r = res.estimates.row("physics")
    assert r["status"] == "needs input" and "needs a DEM" in r["notes"][0]
    assert os.path.isfile(res.files["table"]) and os.path.isfile(res.files["report"])
    assert os.path.isfile(res.files["chart"])


def test_recommended_methods_follow_the_data():
    study = NepalStudy.from_numbers(65.0, inputs={"flood_annual_max": list(range(100, 125))})
    assert "frequency" in study.chosen_methods()
    assert study.chosen_return_periods() == [2, 5, 10, 20, 50, 100, 200, 500]


@pytest.mark.parametrize("site, err", [
    ({"results": "a", "dem": "b"}, "exactly one"),
    ({"dem": "x.tif"}, "outlet"),
    ({"numbers": {"area_below_3000_km2": 3}}, "area_km2"),
    ("results/", "must be a dict"),
])
def test_site_checks(site, err):
    with pytest.raises(ValueError, match=err):
        NepalStudy(site)


def test_option_checks():
    with pytest.raises(ValueError, match="Unknown agency"):
        NepalStudy.from_numbers(10, agency="dor")
    with pytest.raises(ValueError, match="Unknown input"):
        NepalStudy.from_numbers(10, inputs={"R24": 3})
    with pytest.raises(ValueError, match="Unknown physics"):
        NepalStudy.from_numbers(10, physics={"cn": 70})


def test_study_yaml_roundtrip(tmp_path):
    study = NepalStudy.from_dem("dem.tif", (28.7, 80.9), "res", name="Khutiya",
                                agency="dowri_2019", structure="weir",
                                inputs={"rain_24h": {2: 120.0, 100: 250.0}, "mhsp_region": "western"},
                                physics={"curve_number": 80.0, "return_periods": [100]},
                                observed_floods=[("2021 flood marks", 410)])
    path = study.save(tmp_path / "study.yaml")
    text = open(path).read()
    assert text.startswith("# MRRpy-Nepal study") and "2: 120.0" in text
    again = NepalStudy.load(path)
    assert again.to_dict() == study.to_dict()
    assert again.physics["curve_number"] == 80.0 and again.physics["duration_h"] == 24.0


def test_results_folder_must_be_delineated(tmp_path):
    with pytest.raises(FileNotFoundError, match="process_dem"):
        NepalStudy.from_results(tmp_path).run(log=None)


# ═════════════════════════════════════════════════════════════════════════════
# A DEM site with the physics model
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dem_result(tiny_basin, tmp_path_factory):
    dem, outlet = tiny_basin
    folder = tmp_path_factory.mktemp("nepal_study") / "results"
    os.makedirs(folder)
    # a gauges.csv of the user's own run must survive the design runs untouched
    (folder / "gauges.csv").write_text("mine\n")
    study = NepalStudy.from_dem(dem, outlet, folder, name="Tiny khola", agency="dor_bridge",
                                structure="bridge",
                                inputs={"rain_24h": {2: 120.0, 100: 250.0}, "runoff_coefficient": 0.4},
                                physics={"duration_h": 3.0, "step_min": 15.0, "curve_number": 80.0})
    result = study.run(log=lambda _s: None)
    return study, result, folder


def test_dem_site_is_delineated_and_measured(dem_result):
    study, result, folder = dem_result
    d = result.descriptors
    assert d.source == "dem" and d.area_km2 > 0 and d.name == "Tiny khola"
    assert os.path.isfile(folder / "watershed.tif")
    assert study.folder == os.path.join(os.path.abspath(folder), "nepal")


def test_physics_design_flood(dem_result):
    _study, result, folder = dem_result
    assert list(result.physics) == [100.0]                    # the bridge's design return period
    f = result.physics[100.0]
    assert f.peak_m3s > 0 and 0 < f.time_to_peak_h < 9 and 0 < f.runoff_ratio < 1
    assert f.storm_mm == pytest.approx(250.0 * (3 / 24) ** (1 / 3))   # Mononobe depth for 3 h
    # the routed volume is the effective runoff (all of it leaves in the recession time)
    runoff_m3 = f.runoff_ratio * f.storm_mm / 1000.0 * result.descriptors.area_km2 * 1e6
    assert f.volume_m3 == pytest.approx(runoff_m3, rel=0.05)
    row = result.estimates.row("physics")
    assert row["status"] == "ok" and row["Q"][list(result.estimates.T).index(100.0)] == f.peak_m3s
    assert any("SCS curve number 80" in n for n in row["notes"])
    assert os.path.isfile(f.hydrograph_csv) and os.path.isfile(f.files["hyetograph"])
    hyd = pd.read_csv(f.hydrograph_csv)
    assert hyd["Q_m3s"].max() == pytest.approx(f.peak_m3s)
    mb = pd.read_csv(folder / "nepal" / "mass_balance_design.csv")
    assert abs(float(mb["rel_error"].iloc[-1])) < 1e-6
    comp = result.estimates.compare("physics")
    assert comp.loc[100, "position"] in ("inside", "above", "below")


def test_users_files_are_left_alone(dem_result):
    _study, _result, folder = dem_result
    assert (folder / "gauges.csv").read_text() == "mine\n"
    assert not (folder / "hydrograph.csv").exists()            # design runs write elsewhere


def test_saved_outputs(dem_result):
    _study, result, folder = dem_result
    out = folder / "nepal"
    for name in ("nepal_flood_estimates.csv", "nepal_flood_estimates.png", "nepal_report.md",
                 "catchment.csv"):
        assert (out / name).is_file(), name
    table = pd.read_csv(out / "nepal_flood_estimates.csv")
    assert "MRRpy physics model (design storm)" in set(table["method"])
    report = (out / "nepal_report.md").read_text()
    assert "## Physics model" in report and "official range" in report


def test_run_design_floods_directly(dem_result, tmp_path):
    _study, result, folder = dem_result
    cfg = nepal_design_config(folder, curve_number=70.0)
    assert cfg.RUNOFF_SOURCE == "scs_cn" and cfg.CHANNEL_QBF_M3S == "wecs_nepal"
    assert cfg.RAIN_SNOW_ELEV_LOW == 3000.0 and cfg.TARGET_CRS_EPSG.endswith("32645")
    floods = run_design_floods(cfg, {10: 150.0, 50: 210.0}, duration_h=2, step_min=30,
                               sim_hours=6, descriptors=result.descriptors, log=lambda _s: None)
    assert floods[10.0].peak_m3s < floods[50.0].peak_m3s
    with pytest.raises(ValueError, match="No 24-hour"):
        run_design_floods(cfg, {10: 150.0}, return_periods=[100], log=lambda _s: None)
    with pytest.raises(FileNotFoundError):
        run_design_floods(Config(OUTPUT_DIR=str(tmp_path)), {10: 100.0}, log=lambda _s: None)


def test_physics_defaults_are_documented():
    assert set(PHYSICS_DEFAULTS) >= {"curve_number", "pattern", "duration_h", "snow_ramp"}


# ═════════════════════════════════════════════════════════════════════════════
# Nepal bankfull-flow presets in the core
# ═════════════════════════════════════════════════════════════════════════════
def test_nepal_bankfull_presets():
    from MRRpy.core.routing.qbf import QBF_PRESETS, QbfFormula, classify_qbf
    for name in ("wecs_nepal", "dhm2004_nepal", "specific_q_nepal"):
        assert name in QBF_PRESETS and classify_qbf(name)[0] == "formula"
    f = QbfFormula("dhm2004_nepal")
    q = f.evaluate({("A_below", 3000.0): np.array([65.0])})
    assert q[0] == pytest.approx(2.29 * 65 ** 0.86)
    g = QbfFormula("specific_q_nepal")
    assert g.evaluate({"A": np.array([65.0])})[0] == pytest.approx(4.2 * 65 ** 0.7)
    assert Config(CHANNEL_QBF_M3S="dhm2004_nepal").CHANNEL_QBF_M3S == "dhm2004_nepal"
