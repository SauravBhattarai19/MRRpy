# -*- coding: utf-8 -*-
"""
tests/test_nepal_cli.py
=======================
``MRRpy nepal …``: methods, estimate (typed numbers, a study file), frequency,
monthly and design-storm.

Run:  pytest tests/test_nepal_cli.py -v
"""

import os

import pandas as pd
import pytest

from MRRpy.cli.main import main


def run(capsys, *argv):
    code = main(["nepal", *argv])
    out = capsys.readouterr()
    return code, out.out + out.err


def test_methods_lists_everything(capsys):
    code, out = run(capsys, "methods")
    assert code == 0
    for word in ("wecs_dhm", "modified_dickens", "dowri_2019", "bridge", "--rain24"):
        assert word in out


def test_estimate_typed_numbers(capsys):
    code, out = run(capsys, "estimate", "--area", "65", "--methods", "wecs_dhm", "dhm_2004",
                    "--T", "2", "100", "--name", "Chure")
    assert code == 0
    assert "317.1" in out and "418.1" in out and "Official range" in out
    assert "nothing saved" in out


def test_estimate_with_inputs_and_output(capsys, tmp_path):
    code, out = run(capsys, "estimate", "--area", "8", "--length-km", "4", "--slope", "0.04",
                    "--agency", "dolidar_2015", "--structure", "intake", "--C", "0.35",
                    "--rain24", "2=110", "10=170", "25=205", "-o", str(tmp_path),
                    "--save-study", str(tmp_path / "s.yaml"))
    assert code == 0
    assert "Rational method" in out and "DHM 2004" in out and "Q25" in out
    assert (tmp_path / "nepal_flood_estimates.csv").is_file()
    assert (tmp_path / "s.yaml").is_file()
    # the saved study runs again, with a flag on top
    code, out2 = run(capsys, "estimate", "--study", str(tmp_path / "s.yaml"), "--T", "2", "10")
    assert code == 0 and "Q25" not in out2 and "Q10" in out2


def test_estimate_without_site_is_an_error(capsys):
    code, out = run(capsys, "estimate", "--methods", "wecs_dhm")
    assert code == 1 and "Say where the catchment is" in out


def test_frequency_command(capsys, tmp_path):
    p = tmp_path / "peaks.csv"
    pd.DataFrame({"year": range(2000, 2020),
                  "q": [410, 380, 655, 520, 300, 720, 450, 390, 610, 505, 470, 820, 360, 540,
                        430, 600, 495, 380, 700, 455]}).to_csv(p, index=False)
    code, out = run(capsys, "frequency", str(p), "--T", "2", "100", "--boot", "100")
    assert code == 0
    for label in ("Gumbel", "Log-Pearson III", "GEV"):
        assert label in out
    assert "90 % band" in out


def test_monthly_command(capsys, tmp_path):
    code, out = run(capsys, "monthly", "--area", "65", "--mip-region", "4",
                    "--measured", "2024-02-15=1.5", "--mmp", "1500", "-o",
                    str(tmp_path / "m.csv"))
    assert code == 0
    assert "Lower of WECS/DHM and MIP" in out and "E-flow" in out
    assert (tmp_path / "m.csv").is_file()


def test_design_storm_command(capsys, tmp_path):
    code, out = run(capsys, "design-storm", "--rain24", "250", "--duration", "6", "--step", "30",
                    "-o", str(tmp_path))
    assert code == 0 and "PRECIP_METHOD: thiessen" in out
    rain = pd.read_csv(tmp_path / "design_storm_rain.csv")
    assert rain["G01"].sum() == pytest.approx(250 * (6 / 24) ** (1 / 3))
    assert os.path.isfile(tmp_path / "hyetograph.csv")


def test_physics_choice_is_kept_in_a_saved_study(capsys, tmp_path):
    study = tmp_path / "s.yaml"
    code, out = run(capsys, "estimate", "--area", "20", "--methods", "wecs_dhm", "--T", "100",
                    "--rain24", "100=200", "--physics", "--save-study", str(study))
    assert code == 0 and "needs a DEM" in out          # typed numbers: no physics run possible
    assert "enabled: true" in study.read_text()
    code, out = run(capsys, "estimate", "--study", str(study))
    assert code == 0 and "MRRpy physics model" in out and "needs a DEM" in out
