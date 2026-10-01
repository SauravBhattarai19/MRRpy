# -*- coding: utf-8 -*-
"""
tests/test_config_wizard.py
===========================
The terminal wizard (``MRRpy wizard`` / ``MRRpy.run_wizard``), driven by a
scripted user that answers by matching the question text (so the tests don't
depend on question order), and fails loudly if the wizard loops.

Covers: every setting can be asked and answered; Enter keeps values; the
starting points; only relevant questions are asked; advanced gates; the
catch-up of earlier questions; ? / back / done / quit / end-of-input; bad
input; missing files; the review-and-fix loop; editing an existing file;
YAML and JSON output; the CLI entry points; and a configuration built by the
wizard actually running the model.

Run:  pytest tests/test_config_wizard.py -v
"""

import builtins
import os

import pandas as pd
import pytest

from MRRpy import Config, run_pipeline
from MRRpy import config_schema as S
from MRRpy.cli.main import main as cli
from MRRpy.interactive.wizard import Wizard, run_wizard

from _interactive_helpers import Script, example_for, normalised, same, visible_config

SAVE = "Save the configuration as"


def wizard(answers, **kw):
    """Run the wizard with scripted answers; returns (Config or None, Script)."""
    script = Script(answers)
    cfg = run_wizard(input_fn=script, print_fn=script.out, **kw)
    return cfg, script


@pytest.fixture
def basin(tiny_basin, tmp_path):
    dem, (lat, lon) = tiny_basin
    return dict(dem=dem, point=f"{lat}, {lon}", out=str(tmp_path / "out"),
                yaml=str(tmp_path / "run.yaml"), tmp=tmp_path)


# ── Every setting can be asked ───────────────────────────────────────────────
def _typed_answers(p, value):
    """The keystrokes that enter *value* for *p* in the wizard."""
    if p.kind in ("qbf", "channel_n", "hg"):
        mode, sub = S.split_composite(p, value)
        answers = [mode]
        if sub is not None:
            m = next(x for x in S.modes_for(p, value) if x.key == mode)
            answers.append(S.format_value(m.sub, sub))
        return answers
    if p.kind == "points":
        return S.format_value(p, value).splitlines() + [""]
    return [S.format_value(p, value)]


@pytest.mark.parametrize("name", [p.name for p in S.PARAMS])
def test_every_setting_can_be_answered(name):
    p = S.param(name)
    example = normalised(p, example_for(p))
    queue = _typed_answers(p, example)

    def answer(prompt):
        if "anyway?" in prompt:                    # example files don't exist
            return "yes"
        return queue.pop(0)

    wiz = Wizard(visible_config(p), input_fn=answer, print_fn=lambda *a: None)
    wiz.ask_param(p)
    assert same(normalised(p, getattr(wiz.cfg, name)), example)
    assert not queue, f"unused answers {queue}"


@pytest.mark.parametrize("name", [p.name for p in S.PARAMS])
def test_enter_keeps_every_setting(name):
    p = S.param(name)
    cfg = visible_config(p)
    before = getattr(cfg, name)
    wiz = Wizard(cfg, input_fn=lambda prompt: "yes" if "anyway?" in prompt else "",
                 print_fn=lambda *a: None)
    wiz.ask_param(p)
    assert same(getattr(wiz.cfg, name), before)


@pytest.mark.parametrize("start", [sp.key for sp in S.STARTING_POINTS])
def test_ask_all_reaches_every_relevant_setting(start):
    """With --advanced, every setting that matters for the final answers is asked."""
    script = Script({"Use them anyway?": "yes"})
    wiz = Wizard(ask_all=True, starting_point=start, input_fn=script,
                 print_fn=script.out)
    assert wiz.run() is not None
    relevant = {p.name for p in S.visible_params(S.values_of(wiz.cfg))}
    assert relevant <= wiz.asked, relevant - wiz.asked
    assert "advanced setting" not in script.text          # no gates with --advanced


# ── Typical sessions ─────────────────────────────────────────────────────────
def test_design_storm_session(basin):
    cfg, s = wizard({"Starting point": "0",
                     "Elevation model (DEM) file": basin["dem"],
                     "Basin outlet": basin["point"],
                     "Results folder": basin["out"],
                     "Rain intensity": "50", "Storm duration": "2",
                     SAVE: basin["yaml"]})
    assert cfg is not None and not s.unused()
    saved = Config.from_file(basin["yaml"])
    assert saved.DEM_PATH == basin["dem"] and saved.RAIN_INTENSITY_MM_HR == 50.0
    assert saved.HYDROGRAPH_CSV == os.path.join(basin["out"], "hydrograph.csv")
    assert S.problems(saved) == []
    assert "Checked: no problems found." in s.text
    assert f"MRRpy run -c {basin['yaml']}" in s.text
    # only relevant questions: no gauge files, IMERG or physical-runoff questions
    for fragment in ("Gauge locations", "Storm start", "Processes to include",
                     "IMERG", "Download resolution"):
        assert not s.asked(fragment), fragment
    # the DEM was given, so the download questions are skipped
    assert not s.asked("Area to download")


def test_wizard_built_config_runs_the_model(basin):
    """The whole point: answer questions → a file `MRRpy run` can use."""
    cfg, _s = wizard({"Starting point": "0",
                      "Elevation model (DEM) file": basin["dem"],
                      "Basin outlet": basin["point"],
                      "Results folder": basin["out"],
                      "Simulation length": "0.5",
                      "Save results every": "300",
                      SAVE: basin["yaml"]})
    assert cli(["run", "-c", basin["yaml"]]) == 0
    hydro = pd.read_csv(os.path.join(basin["out"], "hydrograph.csv"))
    assert len(hydro) > 1 and (hydro.iloc[:, -1] >= 0).all()


def test_satellite_event_asks_for_project_and_date(basin, monkeypatch):
    monkeypatch.delenv("GEE_PROJECT", raising=False)
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Google Earth Engine project": "my-ee",
                     "Storm start (UTC)": "2024-09-27 00:00",
                     SAVE: basin["yaml"]}, starting_point="satellite_event")
    assert cfg.PRECIP_METHOD == "imerg_thiessen"
    assert cfg.EVENT_START_UTC == "2024-09-27 00:00" and cfg.GEE_PROJECT == "my-ee"
    assert "This sets PRECIP_METHOD = imerg_thiessen" in s.text
    assert not s.asked("Rain intensity")
    assert S.problems(cfg) == []


def test_scs_curve_number_session(basin):
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Runoff method": "scs_cn", "Curve numbers from": "scalar",
                     "Soil wetness": "wet", "Curve number": "85", SAVE: basin["yaml"]},
                    starting_point="design_storm")
    assert (cfg.RUNOFF_SOURCE, cfg.RUNOFF_CN_SOURCE, cfg.RUNOFF_CN_AMC, cfg.RUNOFF_CN) == \
           ("scs_cn", "scalar", "iii", 85.0)
    assert not s.unused()


def test_gauge_rain_session(basin):
    g, r = basin["tmp"] / "gauges.csv", basin["tmp"] / "rain.csv"
    g.write_text("gauge_id,name,easting_m,northing_m\nG1,a,330450,3060450\n")
    r.write_text("time_s,G1\n0,0\n600,5\n")
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Gauge locations": str(g), "Gauge rainfall": str(r),
                     SAVE: basin["yaml"]}, starting_point="gauge_event")
    assert cfg.PRECIP_GAUGE_FILE == str(g) and cfg.PRECIP_TIMESERIES_FILE == str(r)
    assert not s.asked("Rain intensity")


def test_inflow_only_session_asks_for_inflows(basin):
    q = basin["tmp"] / "q.csv"
    q.write_text("time_hr,Q_m3s\n0,1\n1,5\n")
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Inflow hydrographs, point 1": f"us1, {basin['point']}, {q}",
                     SAVE: basin["yaml"]}, starting_point="inflow_only")
    assert cfg.RAIN_INTENSITY_MM_HR == 0.0 and cfg.RUNOFF_SOURCE == "none"
    assert cfg.ROUTING_INFLOW_BC[0]["csv"] == str(q)
    assert "only the inflow hydrographs" in s.text


def test_physical_runoff_catches_up_on_the_storm_date(basin):
    """The storm-date question (rain part) only applies after the soil source
    (runoff part) is set to satellite — it is asked afterwards, with a note."""
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Runoff method": "physical", "Processes to include": "1, 2",
                     "Soil storage from": "gee", "Storm start (UTC)": "2024-07-01 06:00",
                     "Google Earth Engine project": "p", SAVE: basin["yaml"]},
                    starting_point="design_storm")
    assert cfg.RUNOFF_MECHANISMS == ["infiltration_excess", "saturation_excess"]
    assert cfg.EVENT_START_UTC == "2024-07-01 06:00"
    assert "a few earlier questions now apply" in s.text
    assert s.prompts.index(next(p for p in s.prompts if "Storm start" in p)) > \
        s.prompts.index(next(p for p in s.prompts if "Soil storage from" in p))
    assert s.asked("Drainable porosity") == 1 and s.asked("Soil infiltration rate") == 1


def test_advanced_gate_opens_only_when_asked(basin):
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Routing method": "diffusive_implicit",
                     "advanced settings for Routing": "yes",
                     "Implicit time weighting": "0.8", SAVE: basin["yaml"]},
                    starting_point="design_storm")
    assert cfg.IMPLICIT_THETA == 0.8
    assert s.asked("Implicit time weighting") == 1
    assert not s.asked("Download resolution")              # project gate said no
    assert "Routing and simulation time has" in s.text


def test_crs_is_suggested_from_the_outlet(basin):
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Basin outlet": "28.2, 83.9", SAVE: basin["yaml"]},
                    starting_point="design_storm")
    assert cfg.TARGET_CRS_EPSG == "EPSG:32644"
    assert "Suggested: EPSG:32644 (UTM zone 44N" in s.text


def test_composite_questions(basin):
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Manning's n in river channels": "elevation",
                     "Elevation limits and n": ["1500: 0.06, 900: 0.04", "1500: 0.06, 9000: 0.04"],
                     "Bankfull flow": "formula", "Formula or preset": ["import os", "wecs_nepal"],
                     SAVE: basin["yaml"]}, starting_point="design_storm")
    assert cfg.MANNINGS_N_CHANNEL == [[1500.0, 0.06], [9000.0, 0.04]]
    assert cfg.CHANNEL_QBF_M3S == "wecs_nepal"
    assert "low to high" in s.text
    assert "Presets you can type by name" in s.text


def test_back_from_a_sub_question_returns_to_its_mode(basin):
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Bankfull flow": ["value", "auto"], "2-year flood": "back",
                     SAVE: basin["yaml"]}, starting_point="design_storm")
    assert cfg.CHANNEL_QBF_M3S is None
    assert s.asked("Bankfull flow") == 2


def test_virtual_gauges(basin):
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Virtual gauges, point 1": "bridge, 27.70, 85.30",
                     "Virtual gauges, point 2": "dam, row=3, col=4",
                     SAVE: basin["yaml"]}, starting_point="design_storm")
    assert cfg.ROUTING_GAUGES == [{"name": "bridge", "lat": 27.7, "lon": 85.3},
                                  {"name": "dam", "row": 3, "col": 4}]
    assert Config.from_file(basin["yaml"]).ROUTING_GAUGES == cfg.ROUTING_GAUGES


# ── Commands and mistakes ────────────────────────────────────────────────────
def test_help_back_and_retry(basin):
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Rain intensity": ["?", "70", "25"],
                     "Storm duration": ["back", "4"],
                     "Basin outlet": ["abc", basin["point"]],
                     SAVE: basin["yaml"]}, starting_point="design_storm")
    assert cfg.RAIN_INTENSITY_MM_HR == 25.0 and cfg.RAIN_DURATION_HOURS == 4.0
    assert "RAIN_INTENSITY_MM_HR — Rain intensity" in s.text       # the ? help card
    assert "Sorry — 'abc' is not a number" in s.text
    assert s.asked("Rain intensity") == 3


def test_back_at_the_first_question(basin):
    cfg, s = wizard({"Starting point": ["back", "0"],
                     "Elevation model (DEM) file": basin["dem"], SAVE: basin["yaml"]})
    assert cfg is not None and "This is the first question." in s.text


def test_back_across_a_gate(basin):
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Rainfall input": ["back", "0"],
                     "advanced settings for Basin": ["no", "yes"],
                     "Flow-direction engine": "pysheds", SAVE: basin["yaml"]},
                    starting_point="design_storm")
    # 'back' at the first rain question returns to the project part's gate,
    # which is asked again; this time it is opened.
    assert s.asked("advanced settings for Basin") == 2
    assert s.asked("Flow-direction engine") == 1
    assert cfg.DELINEATION_ENGINE == "pysheds" and cfg.DEM_PATH == basin["dem"]
    assert not s.unused()


def test_done_skips_to_the_review(basin):
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     "Rainfall input": "done", SAVE: basin["yaml"]},
                    starting_point="design_storm")
    assert cfg is not None and os.path.exists(basin["yaml"])
    assert not s.asked("Runoff method")
    assert "Review" in s.text


@pytest.mark.parametrize("how", ["quit", EOFError, KeyboardInterrupt])
def test_quit_saves_nothing(basin, how):
    cfg, s = wizard({"Rain intensity": how, "Elevation model (DEM) file": basin["dem"]},
                    starting_point="design_storm")
    assert cfg is None
    assert "Stopped — nothing was saved." in s.text
    assert not os.path.exists(basin["yaml"])


def test_missing_file_is_confirmed(basin):
    cfg, s = wizard({"Elevation model (DEM) file": ["missing.tif", basin["dem"]],
                     "Use it anyway?": "no", SAVE: basin["yaml"]},
                    starting_point="design_storm")
    assert cfg.DEM_PATH == basin["dem"]
    assert "I can't find 'missing.tif'" in s.text


def test_review_offers_to_fix_problems(basin):
    cfg, s = wizard({"Elevation model (DEM) file": ["", basin["dem"]],
                     "Fix them now?": "yes", SAVE: basin["yaml"]},
                    starting_point="design_storm")
    assert cfg.DEM_PATH == basin["dem"]
    assert "Found 1 problem:" in s.text and "Checked: no problems found." in s.text


def test_review_stops_when_nothing_changes(basin):
    cfg, s = wizard({"Fix them now?": "yes", "Save anyway?": "yes", SAVE: basin["yaml"]},
                    starting_point="design_storm")
    assert "Nothing was changed, so the problem is still there." in s.text
    assert os.path.exists(basin["yaml"])                      # saved anyway, as asked
    assert s.asked("Fix them now?") == 1


def test_declining_to_save(basin):
    cfg, s = wizard({"Fix them now?": "no", "Save anyway?": "no"},
                    starting_point="design_storm")
    assert cfg is not None and "Nothing was saved." in s.text
    assert not s.asked(SAVE)


def test_save_name_checks(basin):
    existing = basin["tmp"] / "taken.yaml"
    existing.write_text("RAIN_INTENSITY_MM_HR: 1\n")
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"],
                     SAVE: ["notes.txt", str(existing), basin["yaml"]],
                     "already exists": "no"}, starting_point="design_storm")
    assert "ending in .yaml" in s.text
    assert existing.read_text() == "RAIN_INTENSITY_MM_HR: 1\n"     # not overwritten
    assert os.path.exists(basin["yaml"])


def test_json_output(basin):
    path = str(basin["tmp"] / "run.json")
    cfg, _s = wizard({"Elevation model (DEM) file": basin["dem"],
                      "Manning's n in river channels": "order",
                      "Channel n for order": "0.06, 0.05, 0.04", SAVE: path},
                     starting_point="design_storm")
    back = Config.from_file(path)
    assert back.MANNINGS_N_CHANNEL == {1: 0.06, 2: 0.05, 3: 0.04}   # int keys survive JSON
    assert S.problems(back) == []


# ── Editing an existing file ─────────────────────────────────────────────────
def test_edit_existing_file_keeps_everything_else(basin):
    base = Config(DEM_PATH=basin["dem"], OUTPUT_POINT=(27.7, 85.3), ROUTING_SCHEME="muskingum",
                  IMPLICIT_THETA=0.6, CFL_TARGET=0.5, TARGET_CRS_EPSG="EPSG:32645")
    from MRRpy.interactive.render import save_yaml
    save_yaml(base, basin["yaml"], full=False)
    cfg, s = wizard({"Rain intensity": "33", SAVE: ""}, config=basin["yaml"])
    back = Config.from_file(basin["yaml"])
    assert back.RAIN_INTENSITY_MM_HR == 33.0
    assert (back.ROUTING_SCHEME, back.IMPLICIT_THETA, back.CFL_TARGET) == ("muskingum", 0.6, 0.5)
    assert not s.asked("Starting point") and not s.asked("already exists")
    assert "Editing an existing configuration" in s.text
    assert any("Routing method [2 muskingum]" in p for p in s.prompts)


# ── Command line ─────────────────────────────────────────────────────────────
def _feed_stdin(monkeypatch, answers):
    script = Script(answers)
    monkeypatch.setattr(builtins, "input", script)
    return script


def test_cli_wizard(monkeypatch, basin, capsys):
    script = _feed_stdin(monkeypatch, {"Elevation model (DEM) file": basin["dem"],
                                       "Run the model now?": "no"})
    assert cli(["wizard", "-o", basin["yaml"], "--start", "design_storm", "--brief"]) == 0
    assert os.path.exists(basin["yaml"])
    out = capsys.readouterr().out
    assert "A GeoTIFF of ground elevation" not in out           # --brief hides help lines
    assert script.asked("Run the model now?") == 1


def test_cli_wizard_edit_and_write_all(monkeypatch, basin):
    Config(DEM_PATH=basin["dem"]).save(basin["yaml"])
    _feed_stdin(monkeypatch, {"Run the model now?": "no"})
    assert cli(["wizard", "--edit", basin["yaml"], "--write-all"]) == 0
    text = open(basin["yaml"]).read()
    assert "IMPLICIT_SLOPE_FLOOR" in text                        # every setting written


def test_cli_init_config_interactive(monkeypatch, basin):
    _feed_stdin(monkeypatch, {"Elevation model (DEM) file": basin["dem"],
                              "Run the model now?": "no"})
    assert cli(["init-config", "-i", "-o", basin["yaml"]]) == 0
    assert Config.from_file(basin["yaml"]).DEM_PATH == basin["dem"]


def test_cli_wizard_quit_returns_error_code(monkeypatch):
    _feed_stdin(monkeypatch, {"Starting point": "quit"})
    assert cli(["wizard"]) == 1


def test_wizard_offers_to_run(monkeypatch, basin):
    calls = []
    monkeypatch.setattr("MRRpy.pipeline.run_pipeline", lambda cfg: calls.append(cfg))
    cfg, s = wizard({"Elevation model (DEM) file": basin["dem"], SAVE: basin["yaml"],
                     "Run the model now?": "yes"}, starting_point="design_storm",
                    offer_run=True)
    assert len(calls) == 1 and calls[0].DEM_PATH == basin["dem"]


def test_return_without_saving():
    cfg, s = wizard({"Fix them now?": "no"}, starting_point="defaults", save=False)
    assert isinstance(cfg, Config) and not s.asked(SAVE)
