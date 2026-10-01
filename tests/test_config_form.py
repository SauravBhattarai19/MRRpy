# -*- coding: utf-8 -*-
"""
tests/test_config_form.py
=========================
The Jupyter form (``MRRpy.ConfigForm``), driven headlessly through its
widgets (ipywidgets works without a browser).  Skipped when ipywidgets is not
installed (``pip install MRRpy[notebook]``).

Covers: the step-by-step layout (Terrain → Coordinate system → Precipitation
→ Runoff → Routing → Run, with Next/Back); every setting has a labelled,
explained field in the right step, hanging in the branch of the choice that
opens it and shown only while that choice is selected; two-level choices
(IMERG first, then Thiessen/IDW); every setting can be set and read back; bad
input is reported in words; loading, saving, YAML/Python views, starting
points, the UTM suggestion, the map picker, and running the model.

Run:  pytest tests/test_config_form.py -v
"""

import html
import os

import pytest

W = pytest.importorskip("ipywidgets")

from MRRpy import Config                                  # noqa: E402
from MRRpy import config_schema as S                      # noqa: E402
from MRRpy.interactive import form as F                   # noqa: E402
from MRRpy.interactive.form import ConfigForm             # noqa: E402
from MRRpy.interactive.render import save_yaml            # noqa: E402

from _interactive_helpers import example_for, normalised, same, visible_config  # noqa: E402


@pytest.fixture(scope="module")
def form():
    return ConfigForm(map=False)


def _descendants(widget):
    yield widget
    for child in getattr(widget, "children", ()) or ():
        yield from _descendants(child)


def _shown(field):
    return field.box.layout.display != "none"


def _status(f):
    return f.status.value


def _ids(widget):
    return set(map(id, _descendants(widget)))


def _accordions(widget):
    return [w for w in _descendants(widget) if isinstance(w, W.Accordion)]


# ── Steps and the tree of choices ────────────────────────────────────────────
def test_steps_in_order(form):
    assert [s.key for s in F.STEPS] == ["terrain", "crs", "rain", "runoff", "routing", "run"]
    assert form.tabs.titles == ("1 Terrain", "2 Coordinate system", "3 Precipitation",
                                "4 Runoff", "5 Routing", "6 Outputs and run")


@pytest.mark.parametrize("name", [p.name for p in S.PARAMS if p.name != "GEE_PROJECT"])
def test_every_setting_is_in_exactly_its_step(form, name):
    box = id(form.fields[name].box)
    homes = [i for i, page in enumerate(form.tabs.children) if box in _ids(page)]
    assert homes == [F.STEPS.index(F.step_of(name))], (name, homes)


def test_earth_engine_project_is_offered_in_every_step(form):
    for i, step in enumerate(F.STEPS):
        box, _note, field = form.gee_boxes[step.key]
        assert id(box) in _ids(form.tabs.children[i])
        field.text.value = f"proj-{i}"
        assert form.config.GEE_PROJECT == f"proj-{i}"         # all copies are linked
    form.fields["GEE_PROJECT"].set(None)


@pytest.mark.parametrize("name", [p.name for p in S.PARAMS if S.parent_of(p)])
def test_settings_hang_under_the_choice_that_opens_them(form, name):
    """Each conditional setting sits in the branch of its controlling choice —
    under the very tick box for multi-choice items (e.g. Green-Ampt settings
    under 'infiltration_excess')."""
    parent, item = S.parent_of(name)
    if F.step_of(parent) is not F.step_of(name):
        pytest.skip("controller in another step")
    box = id(form.fields[name].box)
    if parent == "DEM_PATH":
        assert box in _ids(form.dem_download_branch)
        return
    pf = form.fields[parent]
    home = pf.slots[item] if item else form._nodes[parent]
    assert box in _ids(home), (name, parent, item)


def test_every_setting_reachable_from_its_choice_is_never_hidden_in_a_fold(form):
    """'All the features come up': a basic setting is never inside a collapsed
    'More options' section, so choosing its branch shows it straight away."""
    folded = set().union(*(_ids(a) for a in _accordions(form.widget)))
    for p in S.PARAMS:
        if p.level == "basic" and p.name != "GEE_PROJECT":
            assert id(form.fields[p.name].box) not in folded, p.name


def test_next_and_back():
    f = ConfigForm(map=False)
    assert f.tabs.selected_index == 0 and f.back_btns[0].disabled
    for i in range(len(F.STEPS) - 1):
        assert F.STEPS[i + 1].title in f.next_btns[i].description
        f.next_btns[i].click()
        assert f.tabs.selected_index == i + 1
    assert f.next_btns[-1].disabled
    f.back_btns[3].click()
    assert f.tabs.selected_index == 2
    f.go("routing")
    assert f.tabs.selected_index == 4


def test_dem_file_or_download():
    f = ConfigForm(map=False)
    assert f.dem_mode.value == "file"
    assert _shown(f.fields["DEM_PATH"]) and not _shown(f.fields["DEM_BOUNDS_WGS84"])
    f.fields["DEM_PATH"].text.value = "my_dem.tif"
    f.dem_mode.value = "download"
    assert not _shown(f.fields["DEM_PATH"])
    assert _shown(f.fields["DEM_BOUNDS_WGS84"]) and _shown(f.fields["DEM_SOURCE"])
    assert f.dem_download_branch.layout.display != "none"
    assert f.config.DEM_PATH == ""                            # download wins
    f.dem_mode.value = "file"
    assert f.config.DEM_PATH == "my_dem.tif"                  # the path was kept
    g = ConfigForm(Config(DEM_BOUNDS_WGS84=(85.1, 27.5, 85.6, 27.9)), map=False)
    assert g.dem_mode.value == "download"


def test_rain_is_chosen_in_two_levels():
    f = ConfigForm(map=False)
    rain = f.fields["PRECIP_METHOD"]
    assert rain.group.value == "storm" and rain.sub_box.layout.display == "none"
    assert _shown(f.fields["RAIN_INTENSITY_MM_HR"])
    rain.group.value = "imerg"
    assert rain.sub_box.layout.display != "none"
    assert [v for _l, v in rain.sub.options] == ["imerg_thiessen", "imerg_idw"]
    assert f.config.PRECIP_METHOD == "imerg_thiessen"
    assert _shown(f.fields["EVENT_START_UTC"]) and not _shown(f.fields["RAIN_INTENSITY_MM_HR"])
    assert not _shown(f.fields["PRECIP_IDW_POWER"])
    rain.sub.value = "imerg_idw"
    assert _shown(f.fields["PRECIP_IDW_POWER"])
    rain.group.value = "gauges"                               # keeps 'IDW'
    assert f.config.PRECIP_METHOD == "idw"
    assert _shown(f.fields["PRECIP_GAUGE_FILE"]) and not _shown(f.fields["EVENT_START_UTC"])
    rain.group.value = "storm"
    assert f.config.PRECIP_METHOD == "uniform" and rain.sub_box.layout.display == "none"


def test_branches_open_only_for_the_selection():
    f = ConfigForm(map=False)
    implicit = f._nodes["IMPLICIT_THETA"]
    branch_of_scheme = f._nodes["ROUTING_SCHEME"].children[1]
    assert not _shown(f.fields["IMPLICIT_THETA"])
    f.fields["ROUTING_SCHEME"].drop.value = "diffusive_implicit"
    assert implicit.layout.display != "none" and branch_of_scheme.layout.display != "none"
    acc = f._accordion_of["IMPLICIT_THETA"]
    assert acc.titles[0].startswith("More options: Routing method (")
    f.fields["ROUTING_SCHEME"].drop.value = "muskingum"
    assert implicit.layout.display == "none"
    # runoff: nothing below 'none'; physical opens the tick boxes, each with its branch
    assert not _shown(f.fields["RUNOFF_MECHANISMS"])
    f.fields["RUNOFF_SOURCE"].drop.value = "physical"
    mech = f.fields["RUNOFF_MECHANISMS"]
    assert _shown(mech) and _shown(f.fields["GA_KSAT_MMHR"])
    mech.checks["infiltration_excess"].value = False
    assert not _shown(f.fields["GA_KSAT_MMHR"])
    assert mech.slots["infiltration_excess"].children[0].layout.display == "none"


def test_radio_buttons_for_choices_with_branches(form):
    assert isinstance(form.fields["RUNOFF_SOURCE"].drop, W.RadioButtons)
    assert isinstance(form.fields["ROUTING_SCHEME"].drop, W.RadioButtons)
    assert isinstance(form.fields["DEM_SOURCE"].drop, W.Dropdown)        # 8 options, no branch
    assert isinstance(form.fields["CHANNEL_QBF_M3S"].drop, W.RadioButtons)


def test_storm_date_is_shared_with_the_soil_step():
    """Satellite soil moisture (runoff step) needs the storm date (rain step):
    a linked copy of that question appears in the soil branch."""
    f = ConfigForm(map=False)
    f.set_values(RUNOFF_SOURCE="physical", VSA_SD_SOURCE="gee")
    proxy = next(x for x in f.proxies if x.p.name == "EVENT_START_UTC")
    assert id(proxy.field.box) in _ids(f._nodes["VSA_SD_SOURCE"])
    assert _shown(proxy.field) and not _shown(f.fields["EVENT_START_UTC"])  # uniform rain
    proxy.field.text.value = "2024-07-01 06:00"
    assert f.config.EVENT_START_UTC == "2024-07-01 06:00"
    assert f.fields["EVENT_START_UTC"].text.value == "2024-07-01 06:00"


def test_earth_engine_box_appears_where_needed(monkeypatch):
    monkeypatch.delenv("GEE_PROJECT", raising=False)
    f = ConfigForm(Config(CHANNEL_QBF_M3S=300.0), map=False)
    shown = {k for k, (box, _n, _f) in f.gee_boxes.items() if box.layout.display != "none"}
    assert shown == {"run"}                                       # optional box only
    f.fields["PRECIP_METHOD"].group.value = "imerg"
    box, note, _field = f.gee_boxes["rain"]
    assert box.layout.display != "none" and "IMERG" in note.value and "Problem:" in note.value
    f.dem_mode.value = "download"
    f.fields["DEM_BOUNDS_WGS84"].text.value = "85.1, 27.5, 85.6, 27.9"
    assert f.gee_boxes["terrain"][0].layout.display != "none"
    f.gee_boxes["terrain"][2].text.value = "abc"
    assert "Problem:" not in f.gee_boxes["rain"][1].value


@pytest.mark.parametrize("name", [p.name for p in S.PARAMS])
def test_every_field_is_labelled_and_explained(form, name):
    p = S.param(name)
    f = form.fields[name]
    assert html.escape(p.help) in f.help.value               # visible explanation
    inputs = [w for w in _descendants(f.row) if hasattr(w, "description")
              and isinstance(w, (W.Text, W.Textarea, W.Dropdown, W.RadioButtons,
                                 W.FloatText, W.IntText, W.Checkbox))]
    labelled = [w for w in inputs if w.description]
    assert labelled, f"{name}: no labelled input"
    if p.kind == "multichoice":
        assert p.title in f.row.children[0].value
    else:
        assert labelled[0].description == p.title


def test_help_toggle(form):
    form.help_toggle.value = False
    assert all(f.help.layout.display == "none" for f in form.fields.values())
    form.help_toggle.value = True
    assert all(f.help.layout.display != "none" for f in form.fields.values())


# ── Values ───────────────────────────────────────────────────────────────────
def test_default_form_is_the_default_config():
    f = ConfigForm(map=False)
    cfg = f.config
    for p in S.PARAMS:
        assert same(getattr(cfg, p.name), getattr(Config(), p.name)), p.name


@pytest.mark.parametrize("name", [p.name for p in S.PARAMS])
def test_every_setting_can_be_set_and_read(form, name):
    p = S.param(name)
    form.load(visible_config(p))
    if S.parent_of(p) and S.parent_of(p)[0] == "DEM_PATH":
        form.dem_mode.value = "download"
    assert _shown(form.fields[name]), f"{name} hidden although it matters"
    example = normalised(p, example_for(p))
    form.set(name, example)
    assert same(normalised(p, getattr(form.config, name)), example)
    form.load(Config())


@pytest.mark.parametrize("name", ["RAIN_INTENSITY_MM_HR", "OUTPUT_POINT", "ROUTING_SCHEME",
                                  "PRECIP_METHOD", "RUNOFF_SOURCE",
                                  "RUNOFF_MECHANISMS", "SAVE_FIELDS", "ROUTING_GAUGES",
                                  "CHANNEL_QBF_M3S", "MANNINGS_N_CHANNEL", "CHANNEL_HG",
                                  "DEM_CONDITIONING", "CELL_SIZE"])
def test_typing_into_widgets(name):
    """Change values through the widgets themselves, as a user would."""
    f = ConfigForm(map=False)
    p = S.param(name)
    f.load(visible_config(p))
    field = f.fields[name]
    example = normalised(p, example_for(p))
    if isinstance(field, F.CompositeField):
        mode, sub = S.split_composite(p, example)
        field.drop.value = mode
        if sub is not None:
            sf = field.subs[mode]
            if isinstance(sf, F.ChoiceField):
                sf.drop.value = sub
            else:
                sf.text.value = S.format_value(sf.p, sub)
    elif isinstance(field, F.GroupedChoiceField):
        field.group.value = next(k for k, (_l, m) in field.groups.items() if example in m)
        field.sub.value = example
    elif isinstance(field, F.MultiField):
        for value, box in field.checks.items():
            box.value = value in example
    elif isinstance(field, F.ChoiceField):
        field.drop.value = example
    elif isinstance(field, F.BoolField):
        field.check.value = example
    elif isinstance(field, F.NumberField):
        field.num.value = example
    else:
        field.text.value = S.format_value(p, example)
    assert same(normalised(p, getattr(f.config, name)), example)


def test_fields_appear_only_when_they_matter():
    f = ConfigForm(map=False)
    hidden = ["PRECIP_GAUGE_FILE", "RUNOFF_MECHANISMS", "VSA_PHI", "GPU_PRECISION",
              "IMPLICIT_THETA", "CHANNEL_HG", "FIELD_VARS"]
    assert not any(_shown(f.fields[n]) for n in hidden)
    f.fields["PRECIP_METHOD"].set("thiessen")
    assert _shown(f.fields["PRECIP_GAUGE_FILE"])
    assert not _shown(f.fields["RAIN_INTENSITY_MM_HR"])
    f.fields["RUNOFF_SOURCE"].drop.value = "physical"
    assert _shown(f.fields["VSA_PHI"])
    f.fields["RUNOFF_MECHANISMS"].checks["saturation_excess"].value = False
    assert not _shown(f.fields["VSA_PHI"])
    f.fields["BACKEND"].drop.value = "gpu"
    assert _shown(f.fields["GPU_PRECISION"])
    f.fields["ROUTING_SCHEME"].drop.value = "diffusive_implicit"
    assert _shown(f.fields["IMPLICIT_THETA"]) and not _shown(f.fields["CFL_TARGET"])


def test_folded_options_count_and_hide():
    f = ConfigForm(map=False)
    fold = f._accordion_of["RUNOFF_SCS_Ia_FACTOR"]
    assert fold.layout.display == "none"                     # runoff 'none': nothing to fold
    f.set("RUNOFF_SOURCE", "scs_cn")
    assert fold.layout.display != "none"
    assert fold.titles[0] == "More options: Runoff method (1)"
    assert f._accordion_of["CELL_SIZE"].titles[0] == "Terrain processing (4)"


def test_summary_updates_live():
    f = ConfigForm(map=False)
    assert "kinematic" in f.summary_box.value
    f.fields["ROUTING_SCHEME"].drop.value = "muskingum"
    assert "muskingum" in f.summary_box.value
    f.fields["RAIN_INTENSITY_MM_HR"].num.value = 0.0
    assert "nothing will flow" in f.summary_box.value


# ── Problems are written out in words ────────────────────────────────────────
def test_bad_text_is_reported_in_words():
    f = ConfigForm(map=False)
    f.fields["OUTPUT_POINT"].text.value = "north-ish"
    msg = f.fields["OUTPUT_POINT"].message.value
    assert "Problem:" in msg and 'role="alert"' in msg
    with pytest.raises(ValueError, match="Basin outlet"):
        f.config
    assert any("Basin outlet" in p for p in f.problems())
    f.fields["OUTPUT_POINT"].text.value = "27.7, 85.3"
    assert f.fields["OUTPUT_POINT"].message.value == ""


def test_missing_file_note():
    f = ConfigForm(map=False)
    f.fields["DEM_PATH"].text.value = "no_such_dem.tif"
    assert "Not found" in f.fields["DEM_PATH"].message.value
    assert f.config.DEM_PATH == "no_such_dem.tif"            # a note, not a blocker


def test_check_button(tiny_basin):
    f = ConfigForm(map=False)
    f.check_btn.click()
    assert "Found 1 problem" in _status(f) and "DEM_PATH" in _status(f)
    dem, pt = tiny_basin
    f.set_values(DEM_PATH=dem, OUTPUT_POINT=pt)
    f.check_btn.click()
    assert "no problems found" in _status(f)


# ── Files, views, starting points ────────────────────────────────────────────
def test_load_and_save(tmp_path):
    src = Config(ROUTING_SCHEME="muskingum", RAIN_INTENSITY_MM_HR=44.0,
                 ROUTING_GAUGES=[{"name": "g", "lat": 27.7, "lon": 85.3}],
                 CHANNEL_HG={"w_a": 2.0, "w_b": 0.3, "d_a": 0.2, "d_b": 0.3})
    path = save_yaml(src, tmp_path / "in.yaml")
    f = ConfigForm(str(path), map=False)
    assert f.save_path.value == str(path)
    assert f.config.RAIN_INTENSITY_MM_HR == 44.0 and f.config.ROUTING_SCHEME == "muskingum"
    out = tmp_path / "out.yaml"
    f.save_path.value = str(out)
    f.save_btn.click()
    assert "Saved" in _status(f) and "MRRpy run -c" in _status(f)
    back = Config.from_file(str(out))
    for p in S.PARAMS:
        assert same(getattr(back, p.name), getattr(src, p.name)), p.name


def test_load_button(tmp_path):
    f = ConfigForm(map=False)
    f.load_path.value = str(tmp_path / "nope.yaml")
    f.load_btn.click()
    assert "Could not load" in _status(f)
    good = save_yaml(Config(RAIN_DURATION_HOURS=7.0), tmp_path / "ok.yaml")
    f.load_path.value = str(good)
    f.load_btn.click()
    assert "Loaded" in _status(f) and f.config.RAIN_DURATION_HOURS == 7.0


def test_save_every_setting_and_json(tmp_path):
    f = ConfigForm(map=False)
    f.save_all.value = True
    path = f.save(str(tmp_path / "all.yaml"))
    assert "IMPLICIT_SLOPE_FLOOR" in open(path).read()
    js = f.save(str(tmp_path / "c.json"))
    assert Config.from_file(js).ROUTING_SCHEME == "kinematic"


def test_yaml_and_python_views():
    f = ConfigForm(map=False)
    f.set("ROUTING_SCHEME", "muskingum")
    f.yaml_btn.click()
    assert "ROUTING_SCHEME: muskingum" in html.unescape(f.view_box.value)
    f.python_btn.click()
    text = html.unescape(f.view_box.value)
    assert "ROUTING_SCHEME='muskingum'" in text and "ROUTING_SCHEME: muskingum" not in text


def test_starting_points():
    f = ConfigForm(map=False)
    f.start.value = "inflow_only"
    f.start_btn.click()
    cfg = f.config
    assert cfg.RAIN_INTENSITY_MM_HR == 0.0 and cfg.RUNOFF_SOURCE == "none"
    assert f._accordion_of["ROUTING_INFLOW_BC"].selected_index == 0   # folded: opened
    assert "Starting point applied" in _status(f)
    f.start.value = "satellite_event"
    f.start_btn.click()
    assert f.config.PRECIP_METHOD == "imerg_thiessen"
    assert _shown(f.fields["EVENT_START_UTC"])


def test_crs_suggestion_button():
    f = ConfigForm(map=False)
    crs = f.fields["TARGET_CRS_EPSG"]
    assert crs.suggest.disabled                                # default outlet → 32645 already
    f.fields["OUTPUT_POINT"].text.value = "-33.9, 18.4"
    assert not crs.suggest.disabled and "EPSG:32734" in crs.suggest.description
    crs.suggest.click()
    assert f.config.TARGET_CRS_EPSG == "EPSG:32734"


def test_python_rule_is_kept():
    rule = {(0, 1000): 0.05, (1000, 9000): 0.04}
    f = ConfigForm(Config(MANNINGS_N_CHANNEL=rule), map=False)
    assert f.fields["MANNINGS_N_CHANNEL"].drop.value == "custom"
    assert f.config.MANNINGS_N_CHANNEL == rule


def test_composite_shows_only_the_active_input():
    f = ConfigForm(map=False)
    q = f.fields["CHANNEL_QBF_M3S"]
    assert q.subs["value"].box.layout.display == "none"
    q.drop.value = "value"
    assert q.subs["value"].box.layout.display != "none"
    q.subs["value"].text.value = "-5"
    assert "Problem:" in q.subs["value"].message.value


# ── Map picker ───────────────────────────────────────────────────────────────
def test_map_picker():
    pytest.importorskip("ipyleaflet")
    f = ConfigForm()
    f.map_btn.click()
    assert f.map is not None and f.show_map() is f.map
    f._on_map_click(type="click", coordinates=[27.5, 85.6])
    assert f.config.OUTPUT_POINT == (27.5, 85.6)
    f.marker.location = (27.4, 85.4)
    assert f.config.OUTPUT_POINT == (27.4, 85.4)
    f._on_map_click(type="mousemove", coordinates=[1, 1])     # ignored
    assert f.config.OUTPUT_POINT == (27.4, 85.4)
    rect = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [
        [[85.0, 27.0], [85.0, 28.0], [86.0, 28.0], [86.0, 27.0], [85.0, 27.0]]]}}
    f._on_draw(None, "created", rect)
    assert f.config.DEM_BOUNDS_WGS84 == (85.0, 27.0, 86.0, 28.0)
    assert f.config.DEM_PATH == ""
    assert f.dem_mode.value == "download"
    f.set("DEM_PATH", "dem.tif")
    assert f.dem_mode.value == "file" and f.config.DEM_PATH == "dem.tif"
    f._on_draw(None, "created", rect)
    assert "switched to downloading" in _status(f)
    assert f.dem_mode.value == "download" and f.config.DEM_PATH == ""
    assert f.fields["DEM_PATH"].text.value == "dem.tif"


def test_no_map_without_ipyleaflet(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "ipyleaflet":
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    f = ConfigForm()
    assert f.map is None
    assert "pip install ipyleaflet" in "".join(
        getattr(w, "value", "") for w in _descendants(f.tabs.children[0])
        if isinstance(w, W.HTML))


# ── Running ──────────────────────────────────────────────────────────────────
def test_run_button_refuses_with_problems(monkeypatch):
    calls = []
    monkeypatch.setattr("MRRpy.pipeline.run_pipeline", lambda *a, **k: calls.append(a))
    f = ConfigForm(map=False)
    f.run_btn.click()
    assert not calls and "Found 1 problem" in _status(f)


def _log(f):
    return html.unescape(f.log_box.value)


def test_run_button_reports_failures(monkeypatch, tiny_basin, tmp_path):
    def boom(*a, **k):
        print("model says hello")
        raise RuntimeError("disk full")
    monkeypatch.setattr("MRRpy.pipeline.run_pipeline", boom)
    dem, pt = tiny_basin
    f = ConfigForm(Config(DEM_PATH=dem, OUTPUT_POINT=pt, OUTPUT_DIR=str(tmp_path)), map=False)
    f.run_btn.click()
    assert "The run stopped: disk full" in _status(f)
    assert f.run_state == "failed" and "Stopped with an error" in f.state_box.value
    assert "Traceback" in _log(f) and "model says hello" in _log(f)
    assert "disk full" in open(f.log_path).read()
    assert not f.run_btn.disabled and f.progress.bar_style == "danger"


def test_run_shows_running_while_it_runs(monkeypatch, tiny_basin, tmp_path):
    seen = {}

    def fake(cfg, stages, on_log, on_progress):
        seen["state"], seen["disabled"] = f.run_state, f.run_btn.disabled
        on_progress(40)
        seen["status"] = f.state_box.value
        print("routing step 1 of 9")                  # a model print() is captured
        on_log("STAGE 2/2: ROUTING")
        return {"hydrograph_csv": "", "hydrograph_df": None}

    monkeypatch.setattr("MRRpy.pipeline.run_pipeline", fake)
    dem, pt = tiny_basin
    f = ConfigForm(Config(DEM_PATH=dem, OUTPUT_POINT=pt, OUTPUT_DIR=str(tmp_path)), map=False)
    f.run_btn.click()
    assert seen["state"] == "running" and seen["disabled"] is True
    assert "Status: Running" in seen["status"] and "40 %" in seen["status"]
    assert f.run_state == "finished" and "Status: Finished" in f.state_box.value
    assert "routing step 1 of 9" in _log(f) and "STAGE 2/2" in _log(f)


def test_long_logs_show_the_end(monkeypatch, tiny_basin, tmp_path):
    def chatty(cfg, stages, on_log, on_progress):
        for i in range(F._LOG_LINES_SHOWN + 50):
            print(f"line {i}")
        return {}

    monkeypatch.setattr("MRRpy.pipeline.run_pipeline", chatty)
    dem, pt = tiny_basin
    f = ConfigForm(Config(DEM_PATH=dem, OUTPUT_POINT=pt, OUTPUT_DIR=str(tmp_path)), map=False)
    f.run_btn.click()
    shown = _log(f)
    assert f"line {F._LOG_LINES_SHOWN + 49}" in shown and "line 0\n" not in shown
    assert "50 earlier lines are in the full log" in shown
    assert "line 0\n" in open(f.log_path).read()


def test_run_the_model_from_the_form(tiny_basin, tmp_path):
    dem, pt = tiny_basin
    f = ConfigForm(map=False)
    f.set_values(DEM_PATH=dem, OUTPUT_POINT=pt, OUTPUT_DIR=str(tmp_path / "res"),
                 TOTAL_SIMULATION_TIME_HOURS=0.5, OUTPUT_INTERVAL_SECONDS=300)
    f.stage.value = 0
    f.run_btn.click()
    assert "Finished" in _status(f), _status(f)
    assert f.run_state == "finished" and "Status: Finished</b> at" in f.state_box.value
    assert os.path.isfile(f.results["hydrograph_csv"])
    assert f.progress.value == 100 and f.progress.bar_style == "success"
    log = _log(f)
    assert "STAGE 2/2: ROUTING" in log
    assert "Reprojecting DEM" in log                       # the model's own print()s
    assert os.path.isfile(f.log_path) and "STAGE 2/2" in open(f.log_path).read()
    facts, image = f.results_box.children
    assert "Peak flow at the outlet" in facts.value and "Water-balance error" in facts.value
    assert "hydrograph.csv" in facts.value and image.value[:4] == b"\x89PNG"


def test_delineation_only_run(tiny_basin, tmp_path):
    dem, pt = tiny_basin
    f = ConfigForm(Config(DEM_PATH=dem, OUTPUT_POINT=pt, OUTPUT_DIR=str(tmp_path)), map=False)
    f.stage.value = 1
    f.run_btn.click()
    assert f.run_state == "finished"
    assert "watershed.tif" in f.results_box.children[0].value
    assert "Peak flow" not in f.results_box.children[0].value


def test_display_bundle():
    f = ConfigForm(map=False)
    bundle = f._repr_mimebundle_()
    assert "application/vnd.jupyter.widget-view+json" in bundle


def test_no_output_widget_anywhere():
    """VS Code stops showing a form's updates after it fails to apply one to an
    ipywidgets.Output, so the form must not contain one."""
    f = ConfigForm(map=False)
    assert not [w for w in _descendants(f.widget) if isinstance(w, W.Output)]


def test_show_results_reads_the_folder(tiny_basin, tmp_path):
    """The button works for any finished run, e.g. one whose live updates were
    missed, or one started with `MRRpy run`."""
    from MRRpy import run_pipeline
    dem, pt = tiny_basin
    cfg = Config(DEM_PATH=dem, OUTPUT_POINT=pt, OUTPUT_DIR=str(tmp_path / "cli_run"),
                 TOTAL_SIMULATION_TIME_HOURS=0.5, OUTPUT_INTERVAL_SECONDS=300)
    run_pipeline(cfg)                                          # not through the form
    f = ConfigForm(map=False)
    f.set("OUTPUT_DIR", str(tmp_path / "cli_run"))
    f.results_btn.click()
    assert f.run_state == "finished" and "results written at" in f.state_box.value
    facts, image = f.results_box.children
    assert "Peak flow at the outlet" in facts.value and image.value[:4] == b"\x89PNG"
    # opening a form on that folder shows the results straight away
    g = ConfigForm(Config(OUTPUT_DIR=str(tmp_path / "cli_run")), map=False)
    assert g.run_state == "finished" and len(g.results_box.children) == 2


def test_show_results_explains_missing_or_unfinished(tmp_path):
    f = ConfigForm(Config(OUTPUT_DIR=str(tmp_path / "nothing")), map=False)
    f.results_btn.click()
    assert "No results yet" in f.results_box.children[0].value
    half = tmp_path / "half"
    half.mkdir()
    (half / "mrrpy_run.log").write_text("STAGE 1/2: PROCESS_DEM\n")
    f.set("OUTPUT_DIR", str(half))
    f.results_btn.click()
    assert "did not finish" in f.state_box.value
    assert "No hydrograph yet" in f.results_box.children[0].value
    assert "STAGE 1/2" in _log(f)
    (half / "mrrpy_run.log").write_text("Traceback (most recent call last):\n  boom\n")
    f.results_btn.click()
    assert f.run_state == "failed"


def test_form_stays_light():
    """Every widget is a model the browser must rebuild before the form shows
    (slow in VS Code).  Shared layouts/styles keep the count down; this guards
    against it creeping back up (it was 2,214 before sharing)."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        before = set(W.Widget.widgets)
        ConfigForm(map=False)
        created = len(set(W.Widget.widgets) - before)
    assert created < 1300, created


def test_results_list_warnings_from_the_log(tmp_path):
    """A run that silently fell back (e.g. a failed Earth Engine download) must
    say so in the Results panel."""
    folder = tmp_path / "warned"
    folder.mkdir()
    (folder / "hydrograph.csv").write_text("time_s,time_hr,Q_m3s\n600,0.1667,1.0\n1200,0.333,2.0\n")
    (folder / "mrrpy_run.log").write_text(
        "STAGE 2/2: ROUTING\n"
        "GEE deficit raster download failed: Image.clip: Unable to transform edge\n"
        "                |  deficit raster: unavailable → per-zone SD = watershed SD\n"
        "  [WARN] EVENT_START_UTC not set; using manual SD/phi values.\n"
        "[INFO] All stages complete.\n")
    f = ConfigForm(Config(OUTPUT_DIR=str(folder)), map=False)
    texts = [w.value for w in f.results_box.children if hasattr(w, "value")
             and isinstance(w.value, str)]
    warn = next(t for t in texts if "Warnings: 3." in t)
    assert "deficit raster download failed" in warn and 'role="alert"' in warn
    assert f.run_state == "finished"
    assert F.run_warnings("all good\nAll stages complete") == []
