# -*- coding: utf-8 -*-
"""
tests/test_config_schema.py
===========================
The parameter catalogue (MRRpy/config_schema.py) that drives the wizard, the
Jupyter form and the YAML template.  These tests are the safety net that
keeps every interactive front-end complete:

* every Config attribute is catalogued (or deliberately listed in NOT_ASKED);
* every choice has a readable label, every condition names real settings and
  real values, and every setting can be made to matter;
* typed text ⇄ value round-trips for defaults and for a non-default example
  of every setting, with plain-language errors for bad input.

Run:  pytest tests/test_config_schema.py -v
"""

import pytest

from MRRpy import Config
from MRRpy import config_schema as S
from MRRpy.config import _ENUM_CHOICES, _ENUM_LIST
from MRRpy.core.routing.surface import BIEGER_2015
from MRRpy.utils.crs import describe_utm, utm_epsg

from _interactive_helpers import example_for, normalised, same, visible_config

PARAM_IDS = [p.name for p in S.PARAMS]


# ── Completeness ─────────────────────────────────────────────────────────────
def test_every_config_attribute_is_catalogued():
    attrs = set(Config().to_dict())
    catalogued = set(S.PARAM_BY_NAME)
    missing = attrs - catalogued - set(S.NOT_ASKED)
    assert not missing, (
        f"Config attributes missing from MRRpy/config_schema.py: {sorted(missing)}. "
        "Add a P(...) entry (or list them in NOT_ASKED with a reason) so the wizard, "
        "the notebook form and the YAML template offer them.")
    assert not (catalogued - attrs), f"catalogued but not on Config: {catalogued - attrs}"
    assert not (set(S.NOT_ASKED) - attrs), "NOT_ASKED names something Config lacks"
    assert not (catalogued & set(S.NOT_ASKED)), "a parameter is both asked and NOT_ASKED"
    assert len(S.PARAMS) == len(catalogued), "duplicate parameter in PARAMS"


def test_not_asked_have_reasons():
    for name, why in S.NOT_ASKED.items():
        assert why and len(why) > 10, name


@pytest.mark.parametrize("name", PARAM_IDS)
def test_param_metadata_is_complete(name):
    p = S.param(name)
    assert p.kind in S.KINDS
    assert p.section in S.SECTION_BY_KEY
    assert p.level in ("basic", "advanced")
    assert p.label and p.label[0].isupper() or p.label.startswith(("…", "Manning")), p.label
    assert len(p.label) <= 45, "keep labels short; put detail in help"
    assert p.help and p.help.rstrip().endswith((".", ")")), "help should be full sentences"
    assert "TODO" not in p.help
    if p.optional and p.kind not in ("text",):
        assert p.none_label, f"{name}: say what 'empty' means (none_label)"


def test_every_section_has_basic_questions():
    for sec in S.SECTIONS:
        assert any(p.section == sec.key and p.level == "basic" for p in S.PARAMS), sec.key


# ── Choices ──────────────────────────────────────────────────────────────────
def test_enum_registry_params_are_choices():
    for name in _ENUM_CHOICES:
        assert S.param(name).kind == "choice", name
    for name in _ENUM_LIST:
        assert S.param(name).kind == "multichoice", name


@pytest.mark.parametrize("name", [p.name for p in S.PARAMS
                                  if p.kind in ("choice", "multichoice")])
def test_every_choice_has_a_label(name):
    p = S.param(name)
    values = [v for v, _ in S.choices_for(p)]
    assert values, name
    for value, label in S.choices_for(p):
        assert label != value, f"{name}: choice {value!r} has no friendly label"
        assert label.startswith(value), f"{name}: label should start with its value"
    stale = set(p.choice_labels) - set(values)
    assert not stale, f"{name}: labels for choices that no longer exist: {stale}"


def test_hydraulic_geometry_presets_have_labels():
    hg = S.param("CHANNEL_HG")
    preset_mode = next(m for m in S.modes_for(hg) if m.key == "preset")
    assert set(preset_mode.sub.choices) == set(BIEGER_2015)
    for value, label in S.choices_for(preset_mode.sub):
        assert label.startswith(value) and label != value


def test_starting_points():
    keys = [sp.key for sp in S.STARTING_POINTS]
    assert len(keys) == len(set(keys))
    for sp in S.STARTING_POINTS:
        cfg = Config()
        S.apply_starting_point(cfg, sp.key)         # values must be valid Config values
        for name in sp.focus:
            assert S.is_visible(S.param(name), S.values_of(cfg)), (sp.key, name)


# ── Conditions ───────────────────────────────────────────────────────────────
def _clauses(p):
    yield from p.when
    for group in p.when_any:
        yield from group


@pytest.mark.parametrize("name", PARAM_IDS)
def test_conditions_name_real_settings_and_values(name):
    p = S.param(name)
    for ctrl_name, pred in _clauses(p):
        ctrl = S.param(ctrl_name)
        assert ctrl_name != name, "a setting can't depend on itself"
        if isinstance(pred, S.In) and ctrl.kind == "choice":
            valid = [v for v, _ in S.choices_for(ctrl)]
            assert set(pred.values) <= set(valid), (name, ctrl_name, pred.values)
        if isinstance(pred, S.Has):
            assert pred.item in [v for v, _ in S.choices_for(ctrl)], (name, pred.item)
        if isinstance(pred, S.On):
            assert ctrl.kind == "bool", (name, ctrl_name)
        assert pred.describe(ctrl_name)


@pytest.mark.parametrize("name", PARAM_IDS)
def test_every_setting_can_be_made_to_matter(name):
    """Each setting is visible for *some* choices, and its controllers are then
    visible too (no condition chain points at a hidden setting)."""
    p = S.param(name)
    values = S.values_of(visible_config(p))
    assert S.is_visible(p, values), (name, S.condition_text(p))
    for ctrl_name, _pred in _clauses(p):
        if ctrl_name in dict(p.when) or (p.when_any and ctrl_name in dict(p.when_any[0])):
            assert S.is_visible(S.param(ctrl_name), values), (name, ctrl_name)


def test_default_visibility_matches_expectations():
    v = S.values_of(Config())
    shown = {p.name for p in S.visible_params(v)}
    assert {"DEM_PATH", "OUTPUT_POINT", "PRECIP_METHOD", "RAIN_INTENSITY_MM_HR",
            "RUNOFF_SOURCE", "ROUTING_SCHEME", "CHANNEL_QBF_M3S"} <= shown
    assert not shown & {"PRECIP_GAUGE_FILE", "RUNOFF_MECHANISMS", "VSA_PHI",
                        "IMPLICIT_THETA", "GPU_PRECISION", "CHANNEL_HG",
                        "CHANNEL_QBF_AREA_KM2", "FIELD_VARS", "EVENT_START_UTC"}


def test_saturation_soil_date_needs_event_start():
    cfg = Config(RUNOFF_SOURCE="physical", RUNOFF_MECHANISMS=["saturation_excess"],
                 VSA_SD_SOURCE="gee")
    assert S.is_visible(S.param("EVENT_START_UTC"), S.values_of(cfg))
    assert S.is_visible(S.param("SERVES_SATELLITE"), S.values_of(cfg))
    cfg.VSA_SD_SOURCE = "manual"
    assert not S.is_visible(S.param("EVENT_START_UTC"), S.values_of(cfg))


def test_condition_text_is_readable():
    assert S.condition_text(S.param("ROUTING_SCHEME")) == "always"
    t = S.condition_text(S.param("RAIN_INTENSITY_MM_HR"))
    assert t == "PRECIP_METHOD is 'uniform'"
    assert " or " in S.condition_text(S.param("EVENT_START_UTC"))


# ── Text ⇄ value ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", PARAM_IDS)
def test_default_is_valid_and_round_trips(name):
    p = S.param(name)
    default = S.check_value(p, p.default)
    assert same(S.parse_value(p, S.format_value(p, default)), default)


@pytest.mark.parametrize("name", PARAM_IDS)
def test_example_is_valid_non_default_and_round_trips(name):
    p = S.param(name)
    example = normalised(p, example_for(p))
    assert not same(example, S.check_value(p, p.default)), f"{name}: example equals default"
    assert same(S.parse_value(p, S.format_value(p, example)), example)
    cfg = Config()
    setattr(cfg, name, example)                       # Config accepts it
    assert same(normalised(p, getattr(cfg, name)), example)


@pytest.mark.parametrize("name", [p.name for p in S.PARAMS if p.optional])
def test_optional_settings_accept_none_words(name):
    p = S.param(name)
    for word in ("", "none", "auto", "off", "  None  "):
        assert S.parse_value(p, word) is None


@pytest.mark.parametrize("name", [p.name for p in S.PARAMS
                                  if not p.optional and p.kind in
                                  ("float", "int", "latlon", "crs", "folder")])
def test_required_settings_reject_blank(name):
    with pytest.raises(ValueError, match="needs a value"):
        S.parse_value(name, "")


@pytest.mark.parametrize("text, expected", [
    ("0", "kinematic"), ("4", "diffusive_implicit"), ("MUSKINGUM", "muskingum"),
    ("dy", "dynamic"), ("diffusive", "diffusive"), ("  diffusive_i ", "diffusive_implicit"),
])
def test_choice_by_code_name_or_prefix(text, expected):
    assert S.parse_value("ROUTING_SCHEME", text) == expected


@pytest.mark.parametrize("text, message", [
    ("di", "could mean"), ("9", "0–4"), ("zzz", "Choose one of: 0=kinematic"),
])
def test_choice_errors_are_helpful(text, message):
    with pytest.raises(ValueError, match=message):
        S.parse_value("ROUTING_SCHEME", text)


def test_nullable_enum_choice():
    assert S.parse_value("DEM_CONDITIONING", "auto") is None
    assert S.parse_value("DEM_CONDITIONING", "2") == "carve_spread"


def test_multichoice():
    p = "RUNOFF_MECHANISMS"
    assert S.parse_value(p, "0, 2") == ["impervious", "saturation_excess"]
    assert S.parse_value(p, "saturation_excess infiltration_excess") == [
        "infiltration_excess", "saturation_excess"]           # canonical order
    assert S.parse_value(p, "0,0,0") == ["impervious"]
    with pytest.raises(ValueError, match="at least 1"):
        S.parse_value(p, "none")


@pytest.mark.parametrize("text, expected", [
    ("27.6322, 85.2933", (27.6322, 85.2933)), ("27.6 85.3", (27.6, 85.3)),
    ("(27.6, 85.3)", (27.6, 85.3)), ("-33.9;18.4", (-33.9, 18.4)),
])
def test_latlon(text, expected):
    assert S.parse_value("OUTPUT_POINT", text) == expected


def test_latlon_errors():
    with pytest.raises(ValueError, match="Latitude comes first"):
        S.parse_value("OUTPUT_POINT", "120.5, 27.6")
    with pytest.raises(ValueError, match="Expected 2"):
        S.parse_value("OUTPUT_POINT", "27.6")
    with pytest.raises(ValueError, match="not a number"):
        S.parse_value("OUTPUT_POINT", "north, east")


def test_bbox():
    assert S.parse_value("DEM_BOUNDS_WGS84", "85.1, 27.5, 85.6, 27.9") == (85.1, 27.5, 85.6, 27.9)
    with pytest.raises(ValueError, match="west, south, east, north"):
        S.parse_value("DEM_BOUNDS_WGS84", "85.6, 27.5, 85.1, 27.9")
    with pytest.raises(ValueError, match="Expected 4"):
        S.parse_value("DEM_BOUNDS_WGS84", "85.1, 27.5")


@pytest.mark.parametrize("text", ["2024-09-27 06:00", "2024-09-27T06:00", "2024-09-27 06:00:00",
                                  "2024-09-27T06:00Z"])
def test_datetime_formats(text):
    assert S.parse_value("EVENT_START_UTC", text) == "2024-09-27 06:00"


def test_datetime_date_only_and_errors():
    assert S.parse_value("EVENT_START_UTC", "2024-09-27") == "2024-09-27 00:00"
    with pytest.raises(ValueError, match="YYYY-MM-DD HH:MM"):
        S.parse_value("EVENT_START_UTC", "27/09/2024")


def test_crs():
    assert S.parse_value("TARGET_CRS_EPSG", "32645") == "EPSG:32645"
    assert S.parse_value("TARGET_CRS_EPSG", "epsg:32644") == "EPSG:32644"
    with pytest.raises(ValueError, match="degrees"):
        S.parse_value("TARGET_CRS_EPSG", "EPSG:4326")
    with pytest.raises(ValueError, match="recognises"):
        S.parse_value("TARGET_CRS_EPSG", "not-a-crs")


def test_numbers_and_ranges():
    assert S.parse_value("RAIN_INTENSITY_MM_HR", "1e1") == 10.0
    assert S.parse_value("OUTPUT_INTERVAL_SECONDS", "900") == 900
    with pytest.raises(ValueError, match="whole number"):
        S.parse_value("OUTPUT_INTERVAL_SECONDS", "90.5")
    with pytest.raises(ValueError, match="at least 0"):
        S.parse_value("RAIN_INTENSITY_MM_HR", "-1")
    with pytest.raises(ValueError, match="more than 0"):
        S.parse_value("MANNINGS_N", "0")
    with pytest.raises(ValueError, match="at most 100"):
        S.parse_value("RUNOFF_CN", "120")
    with pytest.raises(ValueError, match="not a number"):
        S.parse_value("MANNINGS_N", "rough")


@pytest.mark.parametrize("text, expected", [
    ("yes", True), ("Y", True), ("on", True), ("no", False), ("false", False), ("0", False)])
def test_bool_words(text, expected):
    assert S.parse_value("SAVE_FIELDS", text) is expected


def test_file_paths_strip_quotes_and_expand_home(tmp_path):
    import os
    assert S.parse_value("DEM_PATH", '"/data/my dem.tif"') == "/data/my dem.tif"
    assert S.parse_value("DEM_PATH", "~/dem.tif") == os.path.expanduser("~/dem.tif")
    assert S.parse_value("DEM_PATH", "") == ""                  # = download one
    assert S.parse_value("GA_KSAT_RASTER", "") is None


def test_text_required():
    with pytest.raises(ValueError, match="needs a value"):
        S.parse_value("IMERG_BAND", "")
    assert S.parse_value("GEE_PROJECT", "") is None


def test_order_table_both_syntaxes():
    p = "CHANNEL_WIDTH_BY_ORDER"
    assert S.parse_value(p, "3, 5, 8") == {1: 3.0, 2: 5.0, 3: 8.0}
    assert S.parse_value(p, "1: 3, 4: 12") == {1: 3.0, 4: 12.0}
    assert S.format_value(p, {1: 3.0, 4: 12.0}) == "1: 3, 4: 12"
    with pytest.raises(ValueError, match="positive"):
        S.parse_value(p, "3, -5")


def test_points_parse_and_round_trip():
    p = S.param("ROUTING_GAUGES")
    pts = S.parse_value(p, "Betrawati, 27.974, 85.185\n27.7, 85.3\n"
                           "dam, row=10, col=20, snap_radius_cells=4, snap_to_channel=no\n"
                           "# a comment line\n")
    assert pts == [
        {"name": "Betrawati", "lat": 27.974, "lon": 85.185},
        {"lat": 27.7, "lon": 85.3},
        {"name": "dam", "row": 10, "col": 20, "snap_radius_cells": 4, "snap_to_channel": False},
    ]
    assert S.parse_value(p, S.format_value(p, pts)) == pts
    assert S.parse_value(p, "") is None


def test_inflow_points_need_a_csv():
    p = S.param("ROUTING_INFLOW_BC")
    assert S.parse_value(p, "us1, 27.7, 85.3, q.csv")[0]["csv"] == "q.csv"
    with pytest.raises(ValueError, match="hydrograph CSV"):
        S.parse_value(p, "us1, 27.7, 85.3")


@pytest.mark.parametrize("text, message", [
    ("gauge, 27.7", "location"), ("g, 27.7, 85.3, extra, more", "too many"),
    ("g, 127.7, 85.3", "Latitude"), ("g, height=3", "unknown field"),
])
def test_point_errors(text, message):
    with pytest.raises(ValueError, match=message):
        S.parse_value("ROUTING_GAUGES", text)


def test_bankfull_flow_forms():
    p = S.param("CHANNEL_QBF_M3S")
    assert S.parse_value(p, "auto") is None
    assert S.parse_value(p, "400") == 400.0
    assert S.parse_value(p, "wecs_nepal") == "wecs_nepal"
    assert S.parse_value(p, "1.73 * A ^ 0.606") == "1.73 * A ^ 0.606"
    with pytest.raises(ValueError):
        S.parse_value(p, "-3")
    with pytest.raises(ValueError):
        S.parse_value(p, "import os")


def test_channel_n_forms(tmp_path):
    p = S.param("MANNINGS_N_CHANNEL")
    assert S.parse_value(p, "off") is None
    assert S.parse_value(p, "0.04") == 0.04
    assert S.parse_value(p, "{1: 0.05, 3: 0.035}") == {1: 0.05, 3: 0.035}
    assert S.parse_value(p, "[[1500, 0.06], [9000, 0.04]]") == [[1500.0, 0.06], [9000.0, 0.04]]
    assert S.parse_value(p, "n_channel.tif") == "n_channel.tif"
    with pytest.raises(ValueError, match="low to high"):
        S.parse_value(p, "[[9000, 0.04], [1500, 0.06]]")


def test_hydraulic_geometry_forms():
    p = S.param("CHANNEL_HG")
    assert S.parse_value(p, "BIEGER_APL") == "bieger_apl"
    assert S.parse_value(p, "2.7, 0.35, 0.3, 0.2") == {"w_a": 2.7, "w_b": 0.35,
                                                        "d_a": 0.3, "d_b": 0.2}
    with pytest.raises(ValueError, match="Unknown curve"):
        S.parse_value(p, "bieger_xxx")


@pytest.mark.parametrize("name, value, mode", [
    ("CHANNEL_QBF_M3S", None, "auto"), ("CHANNEL_QBF_M3S", 250.0, "value"),
    ("CHANNEL_QBF_M3S", "global_area", "formula"),
    ("MANNINGS_N_CHANNEL", None, "off"), ("MANNINGS_N_CHANNEL", 0.03, "value"),
    ("MANNINGS_N_CHANNEL", {1: 0.05}, "order"),
    ("MANNINGS_N_CHANNEL", [[1000.0, 0.06]], "elevation"),
    ("MANNINGS_N_CHANNEL", "n.tif", "raster"),
    ("CHANNEL_HG", "bieger_usa", "preset"),
    ("CHANNEL_HG", {"w_a": 1.0, "w_b": 0.4, "d_a": 0.2, "d_b": 0.3}, "custom"),
])
def test_composite_split_join(name, value, mode):
    p = S.param(name)
    got_mode, sub = S.split_composite(p, value)
    assert got_mode == mode
    assert same(S.join_composite(p, got_mode, sub), value)
    assert mode in [m.key for m in S.modes_for(p, value)]


def test_channel_n_custom_rule_is_kept():
    p = S.param("MANNINGS_N_CHANNEL")
    rule = {(0, 1000): 0.05}                          # elevation-bin dict (tuple keys)
    assert S.mode_of(p, rule) == "custom"
    assert "custom" in [m.key for m in S.modes_for(p, rule)]
    assert "custom" not in [m.key for m in S.modes_for(p, 0.035)]


def test_unknown_setting_suggests_names():
    with pytest.raises(KeyError, match="ROUTING_SCHEME"):
        S.param("ROUTING_SCHEM")


# ── Helpers ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("lat, lon, epsg", [
    (27.6322, 85.2933, "EPSG:32645"), (28.2, 83.9, "EPSG:32644"),
    (-33.9, 18.4, "EPSG:32734"), (40.7, -74.0, "EPSG:32618"),
    (0.0, 180.0, "EPSG:32660"), (0.0, -180.0, "EPSG:32601"),
    (85.0, 10.0, None), (-81.0, 10.0, None),
])
def test_utm_zone(lat, lon, epsg):
    assert utm_epsg(lat, lon) == epsg


def test_crs_suggestion_text():
    epsg, why = S.suggest_crs({"OUTPUT_POINT": (28.2, 83.9)})
    assert epsg == "EPSG:32644" and "UTM zone 44N" in why
    assert describe_utm("EPSG:32734") == "UTM zone 34S"
    assert S.suggest_crs({"OUTPUT_POINT": None}) == (None, "")


def test_config_changes():
    assert S.config_changes(Config()) == {}
    cfg = Config(ROUTING_SCHEME=2, OUTPUT_POINT=[27.632222, 85.293333])  # list == default tuple
    assert S.config_changes(cfg) == {"ROUTING_SCHEME": "muskingum"}


def test_problems_and_names_in_messages(tiny_basin):
    dem, pt = tiny_basin
    assert S.problems(Config(DEM_PATH=dem, OUTPUT_POINT=pt)) == []
    probs = S.problems(Config(DEM_PATH="nowhere.tif", PRECIP_METHOD="imerg_idw"))
    assert any("DEM_PATH" in p for p in probs)
    names = [n for m in probs for n in S.params_in_message(m)]
    assert "DEM_PATH" in names and "GEE_PROJECT" in names
    assert S.params_in_message("MANNINGS_N must be > 0 (got 0)") == ["MANNINGS_N"]


# Every configuration that Config.validate() rejects for lack of an Earth Engine
# project must be reported by earth_engine_uses() as needing one, and the
# offline configurations must not.
_GEE_CASES = [
    dict(DEM_PATH="", DEM_BOUNDS_WGS84=(85.1, 27.5, 85.6, 27.9)),
    dict(PRECIP_METHOD="imerg_thiessen", EVENT_START_UTC="2024-09-27 00:00"),
    dict(RUNOFF_SOURCE="scs_cn", RUNOFF_CN_SOURCE="gee"),
    dict(RUNOFF_SOURCE="physical", RUNOFF_MECHANISMS=["saturation_excess"], VSA_SD_SOURCE="gee"),
    dict(RUNOFF_SOURCE="physical", RUNOFF_MECHANISMS=["infiltration_excess"], GA_KSAT_SOURCE="gee"),
    dict(RUNOFF_SOURCE="physical", RUNOFF_MECHANISMS=["infiltration_excess"],
         GA_SUCTION_SOURCE="texture"),
    dict(RUNOFF_SOURCE="physical", MANNINGS_N_SOURCE="lcz"),
    dict(RUNOFF_SOURCE="physical", RUNOFF_MECHANISMS=["impervious"], IMPERVIOUS_SOURCE="lulc"),
    dict(CHANNEL_QBF_M3S="global_area_rain"),
]


@pytest.mark.parametrize("kw", _GEE_CASES)
def test_earth_engine_needs_agree_with_validate(kw, tiny_basin, monkeypatch):
    monkeypatch.delenv("GEE_PROJECT", raising=False)
    dem, pt = tiny_basin
    base = dict(DEM_PATH=dem, OUTPUT_POINT=pt)
    base.update(kw)
    cfg = Config(**base)
    assert any(required for _w, required in S.earth_engine_uses(S.values_of(cfg)))
    assert any("GEE_PROJECT" in p for p in S.problems(cfg))


def test_offline_config_needs_no_earth_engine():
    cfg = Config(CHANNEL_QBF_M3S=300.0, MANNINGS_N_SOURCE="scalar")
    assert S.earth_engine_uses(S.values_of(cfg)) == []
    auto = S.earth_engine_uses(S.values_of(Config()))
    assert auto and not any(req for _w, req in auto)      # automatic Q_bf: optional only


# ── Layout metadata for the step-by-step form ────────────────────────────────
@pytest.mark.parametrize("name", [p.name for p in S.PARAMS if p.choice_groups])
def test_choice_groups_cover_every_choice_once(name):
    p = S.param(name)
    members = [m for _k, _label, ms in p.choice_groups for m in ms]
    assert sorted(members) == sorted(v for v, _ in S.choices_for(p))
    assert len(members) == len(set(members))
    for _k, label, ms in p.choice_groups:
        assert label
        if len(ms) > 1:
            assert p.group_title and all(m in p.sub_labels for m in ms)


def test_rain_groups():
    groups = {k: ms for k, _l, ms in S.param("PRECIP_METHOD").choice_groups}
    assert groups == {"storm": ["uniform"], "gauges": ["thiessen", "idw"],
                      "imerg": ["imerg_thiessen", "imerg_idw"]}


@pytest.mark.parametrize("name", PARAM_IDS)
def test_tree_parents_are_real_and_acyclic(name):
    seen, cur = {name}, name
    while S.parent_of(cur):
        parent, item = S.parent_of(cur)
        assert parent in S.PARAM_BY_NAME
        if item is not None:
            assert S.param(parent).kind == "multichoice"
            assert item in [v for v, _ in S.choices_for(parent)]
        assert parent not in seen, f"cycle at {parent}"
        seen.add(parent)
        cur = parent


def test_tree_examples():
    assert S.parent_of("IMPLICIT_THETA") == ("ROUTING_SCHEME", None)
    assert S.parent_of("GA_KSAT_MMHR") == ("RUNOFF_MECHANISMS", "infiltration_excess")
    assert S.parent_of("VSA_SD_SOURCE") == ("RUNOFF_MECHANISMS", None)     # shared by two boxes
    assert S.parent_of("CHANNEL_QBF_AREA_KM2") == ("CHANNEL_QBF_M3S", None)
    assert S.parent_of("ROUTING_SCHEME") is None
    assert [n for n, _g in S.extra_parents("EVENT_START_UTC")] == ["VSA_SD_SOURCE"]


def test_earth_engine_triggers_name_their_setting():
    cfg = Config(PRECIP_METHOD="imerg_idw", DEM_PATH="", DEM_BOUNDS_WGS84=(85, 27, 86, 28))
    names = {n for _w, _r, n in S.earth_engine_triggers(S.values_of(cfg))}
    assert {"PRECIP_METHOD", "DEM_BOUNDS_WGS84", "CHANNEL_QBF_M3S"} <= names
    assert all(n in S.PARAM_BY_NAME for n in names)
