# -*- coding: utf-8 -*-
"""
tests/test_config_render.py
===========================
Readable views of a Config and the CLI commands built on them:
the commented YAML template (``MRRpy init-config``), the Python export, the
plain-language run summary, and ``MRRpy explain``.

The key property: whatever is written can be read back to the *same*
configuration — for the defaults and for a config where every setting has
been changed.

Run:  pytest tests/test_config_render.py -v
"""

import os

import pytest
import yaml

from MRRpy import Config
from MRRpy import config_schema as S
from MRRpy.cli.main import main as cli
from MRRpy.interactive import render

from _interactive_helpers import example_for, same


def _everything_changed():
    """A Config where every catalogued setting holds its non-default example."""
    cfg = Config()
    for p in S.PARAMS:
        setattr(cfg, p.name, example_for(p))
    return cfg


def _assert_same_config(a, b):
    diff = [p.name for p in S.PARAMS
            if not same(getattr(a, p.name), getattr(b, p.name))]
    assert not diff, f"settings that changed on the way: {diff}"


# ── YAML ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("full", [True, False])
@pytest.mark.parametrize("make", [Config, _everything_changed], ids=["defaults", "all-changed"])
def test_yaml_round_trip(tmp_path, make, full):
    cfg = make()
    path = render.save_yaml(cfg, tmp_path / "run.yaml", full=full)
    _assert_same_config(Config.from_file(path), cfg)


def test_full_yaml_lists_every_setting_with_an_explanation(tmp_path):
    text = render.render_yaml(Config(), full=True)
    for p in S.PARAMS:
        assert f"\n{p.name}:" in text or f"\n# {p.name}:" in text, p.name
        assert p.label in text, p.name
    for sec in S.SECTIONS:
        assert sec.title in text
    for name in S.NOT_ASKED:                     # derived paths are not written
        assert f"\n{name}:" not in text
    data = yaml.safe_load(text)
    assert set(data) <= set(S.PARAM_BY_NAME)


def test_yaml_layout_is_block_style():
    text = render.render_yaml(_everything_changed(), full=True)
    assert not any(line.startswith("{") for line in text.splitlines())
    assert "\nOUTPUT_POINT: [28.0, 84.5]\n" in text
    assert "\nROUTING_GAUGES:\n  - {name: bridge, lat: 27.7, lon: 85.3}\n" in text


def test_short_yaml_keeps_what_matters():
    cfg = Config(PRECIP_METHOD="thiessen", PRECIP_GAUGE_FILE="g.csv", IMPLICIT_THETA=0.6)
    text = render.render_yaml(cfg, full=False)
    data = yaml.safe_load(text)
    assert data["PRECIP_GAUGE_FILE"] == "g.csv"          # visible basic
    assert "RAIN_INTENSITY_MM_HR" not in data            # hidden for gauges, unchanged
    assert "TIME_STEP_SECONDS" not in data               # advanced, unchanged
    assert data["IMPLICIT_THETA"] == 0.6                 # changed, though hidden
    assert "Not used with your current choices" in text  # …and flagged as such
    assert "keep their defaults" in text


def test_builtin_lookup_tables_are_not_written_as_machine_paths(tmp_path):
    text = render.render_yaml(Config(), full=True)
    assert "# LULC_LOOKUP_CSV: <the table shipped with MRRpy>" in text
    assert os.path.dirname(S.param("LULC_LOOKUP_CSV").default) not in text
    path = render.save_yaml(Config(), tmp_path / "a.yaml", full=True)
    assert Config.from_file(path).LULC_LOOKUP_CSV == Config().LULC_LOOKUP_CSV


def test_python_only_values_are_commented_not_lost(tmp_path):
    cfg = Config(MANNINGS_N_CHANNEL=lambda z: 0.05, RAIN_INTENSITY_MM_HR=42.0)
    path = render.save_yaml(cfg, tmp_path / "f.yaml", full=False)
    text = open(path).read()
    assert "cannot hold" in text and "# MANNINGS_N_CHANNEL: <python value>" in text
    back = Config.from_file(path)
    assert back.RAIN_INTENSITY_MM_HR == 42.0
    assert back.MANNINGS_N_CHANNEL == Config().MANNINGS_N_CHANNEL


def test_save_yaml_creates_folders(tmp_path):
    path = render.save_yaml(Config(), tmp_path / "new" / "dir" / "r.yaml")
    assert os.path.isfile(path)


# ── Python ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("make", [Config, _everything_changed], ids=["defaults", "all-changed"])
def test_python_export_rebuilds_the_config(make):
    cfg = make()
    code = render.to_python(cfg, run=False)
    scope = {}
    exec(compile(code, "<to_python>", "exec"), scope)
    _assert_same_config(scope["cfg"], cfg)
    assert scope["cfg"].HYDROGRAPH_CSV.startswith(scope["cfg"].OUTPUT_DIR)


def test_python_export_lists_only_changes():
    code = render.to_python(Config(ROUTING_SCHEME="muskingum"))
    assert "ROUTING_SCHEME='muskingum'" in code
    assert "MANNINGS_N=" not in code
    assert "run_pipeline(cfg)" in code


# ── Plain-language summary ───────────────────────────────────────────────────
def _summary(**kw):
    return "\n".join(render.describe_run(Config(**kw)))


def test_summary_mentions_the_essentials():
    text = _summary(DEM_PATH="dem.tif", RAIN_INTENSITY_MM_HR=10, RAIN_DURATION_HOURS=2)
    assert "dem.tif" in text and "10 mm/h for 2 h" in text and "20 mm in total" in text
    assert "kinematic for 96 h" in text and "every 10 min" in text


@pytest.mark.parametrize("kw, phrase", [
    (dict(DEM_BOUNDS_WGS84=(85.1, 27.5, 85.6, 27.9), DEM_SCALE_M=90.0), "download nasadem at 90 m"),
    (dict(PRECIP_METHOD="thiessen", PRECIP_TIMESERIES_FILE="r.csv"), "nearest gauge"),
    (dict(PRECIP_METHOD="imerg_idw", EVENT_START_UTC="2024-09-27 00:00"), "IMERG"),
    (dict(RAIN_INTENSITY_MM_HR=0, ROUTING_INFLOW_BC=[{"lat": 1, "lon": 2, "csv": "q.csv"}]),
     "only the inflow"),
    (dict(RAIN_INTENSITY_MM_HR=0), "nothing will flow"),
    (dict(RUNOFF_SOURCE="scs_cn", RUNOFF_CN_SOURCE="scalar", RUNOFF_CN=80, RUNOFF_CN_AMC="iii"),
     "CN 80 everywhere, wet soil"),
    (dict(RUNOFF_SOURCE="physical", RUNOFF_MECHANISMS=["impervious", "saturation_excess"]),
     "paved areas, saturation excess"),
    (dict(RUNOFF_SOURCE="coefficient", RUNOFF_COEFFICIENT_PATH="c.tif"), "c.tif"),
    (dict(CHANNEL_QBF_M3S=400.0), "bankfull flow of 400 m³/s"),
    (dict(CHANNEL_GEOMETRY="area", CHANNEL_HG="bieger_rms"), "bieger_rms"),
    (dict(CHANNEL_ROUTING=False), "no separate channel"),
    (dict(MANNINGS_N_CHANNEL=None), "the same in rivers"),
    (dict(SAVE_FIELDS=True, FIELD_VARS=["depth"]), "maps of depth"),
    (dict(RAIN_SNOW_ELEV_LOW=3000.0, RAIN_SNOW_ELEV_HIGH=4000.0), "above 4000 m"),
    (dict(CHANNEL_QBF_M3S=300.0), "Runs fully offline"),
    (dict(PRECIP_METHOD="imerg_thiessen"), "PROJECT NOT SET"),
    (dict(PRECIP_METHOD="imerg_thiessen", GEE_PROJECT="abc"), "project abc"),
    (dict(BACKEND="gpu"), "Computer: GPU"),
])
def test_summary_variants(kw, phrase, monkeypatch):
    monkeypatch.delenv("GEE_PROJECT", raising=False)
    assert phrase in _summary(**kw)


# ── explain ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", [p.name for p in S.PARAMS])
def test_explain_every_setting(name):
    text = render.explain(name.lower())
    assert text.startswith(name)
    assert "Applies when:" in text and "Default:" in text


def test_explain_choices_and_search():
    text = render.explain("ROUTING_SCHEME")
    assert "4  diffusive_implicit" in text
    hits = render.explain("manning")
    assert "MANNINGS_N_CHANNEL" in hits and "MANNINGS_N_SOURCE" in hits
    assert "RAIN_SNOW_ELEV_LOW" in render.explain("snow")
    assert "derived from OUTPUT_DIR" in render.explain("HYDROGRAPH_CSV")
    assert "Did you mean" in render.explain("ROUTNG_SCHEME")
    assert "wecs_nepal" in render.explain("CHANNEL_QBF_M3S")


def test_list_settings_has_every_setting():
    text = render.list_settings()
    for p in S.PARAMS:
        assert p.name in text


# ── CLI ──────────────────────────────────────────────────────────────────────
def test_cli_init_config_full_short_json(tmp_path, capsys):
    full, short, js = tmp_path / "f.yaml", tmp_path / "s.yaml", tmp_path / "j.json"
    assert cli(["init-config", "-o", str(full)]) == 0
    assert cli(["init-config", "--short", "-o", str(short)]) == 0
    assert cli(["init-config", "-o", str(js)]) == 0
    for path in (full, short, js):
        _assert_same_config(Config.from_file(str(path)), Config())
    assert len(full.read_text().splitlines()) > 3 * len(short.read_text().splitlines())
    assert "MRRpy wizard" in capsys.readouterr().out


def test_cli_explain(capsys):
    assert cli(["explain", "routing_scheme"]) == 0
    assert "diffusive_implicit" in capsys.readouterr().out
    assert cli(["explain", "rain", "intensity"]) == 0
    assert "RAIN_INTENSITY_MM_HR" in capsys.readouterr().out
    assert cli(["explain", "--all"]) == 0
    out = capsys.readouterr().out
    assert all(p.name in out for p in S.PARAMS)
    assert cli(["explain", "zzzz_not_a_setting"]) == 1


def test_cli_validate_prints_a_summary(tmp_path, tiny_basin, capsys):
    dem, pt = tiny_basin
    path = render.save_yaml(Config(DEM_PATH=dem, OUTPUT_POINT=pt), tmp_path / "ok.yaml")
    assert cli(["validate", "-c", path]) == 0
    out = capsys.readouterr().out
    assert "Config OK." in out and "Routing: kinematic" in out
