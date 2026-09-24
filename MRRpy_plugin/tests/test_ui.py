# -*- coding: utf-8 -*-
"""
tests/test_ui.py
================
Headless tests of the plugin dialog ↔ Config mapping.

They need QGIS's Python (``qgis.core`` / ``qgis.gui``) and are skipped
elsewhere.  On Linux:

    QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest MRRpy_plugin/tests/test_ui.py -v

The point is to catch drift between the core ``Config`` and the plugin: every
routing scheme the core registers must be selectable, and every knob the UI
exposes must survive a Config → widgets → Config round trip.
"""

import os
import sys
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("qgis.core")
pytest.importorskip("qgis.gui")

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from qgis.core import QgsApplication  # noqa: E402

from MRRpy.config import Config, _ENUM_CHOICES  # noqa: E402

_ALL_SCHEMES = _ENUM_CHOICES["ROUTING_SCHEME"]


@pytest.fixture(scope="module")
def qgis_app():
    app = QgsApplication.instance()
    if app is None:
        app = QgsApplication([], True)
        app.initQgis()
    return app


@pytest.fixture
def dialog(qgis_app):
    from MRRpy_plugin.ui.main_dialog import MainDialog
    dlg = MainDialog(mock.MagicMock())
    yield dlg
    dlg.deleteLater()


def _roundtrip(tab, cfg):
    tab.apply_config(cfg)
    out = Config()
    tab.write_to_config(out)
    return out


# ── Routing ───────────────────────────────────────────────────────────────────

def test_every_core_scheme_is_selectable(dialog):
    assert dialog.tab_routing._SCHEMES == list(_ALL_SCHEMES)


def test_processing_alg_offers_every_core_scheme(qgis_app):
    from MRRpy_plugin.processing.alg_router import RoutingAlgorithm
    assert RoutingAlgorithm._SCHEME_OPTIONS == list(_ALL_SCHEMES)


@pytest.mark.parametrize("scheme", _ALL_SCHEMES)
def test_scheme_roundtrip(dialog, scheme):
    assert _roundtrip(dialog.tab_routing, Config(ROUTING_SCHEME=scheme)).ROUTING_SCHEME == scheme


def test_scheme_specific_knobs_roundtrip(dialog):
    cfg = Config(
        ROUTING_SCHEME="diffusive_implicit",
        DIFFUSION_THETA=0.4, DYNAMIC_FLUX_THETA=0.75,
        IMPLICIT_MAX_ITERS=12, IMPLICIT_TOL=5e-5, IMPLICIT_SLOPE_FLOOR=1e-7,
        IMPLICIT_THETA=0.6, IMPLICIT_RELAX=0.9, IMPLICIT_CFL_TARGET=3.5,
        IMPLICIT_SOLVER="splu", IMPLICIT_NUM_THREADS=16,
        MANNING_SLOPE_CAP=0.08, FLUX_LIMITER=False, ADAPTIVE_TIMESTEP=True,
    )
    out = _roundtrip(dialog.tab_routing, cfg)
    for key in ("ROUTING_SCHEME", "IMPLICIT_MAX_ITERS", "IMPLICIT_SOLVER",
                "IMPLICIT_NUM_THREADS", "FLUX_LIMITER", "ADAPTIVE_TIMESTEP"):
        assert getattr(out, key) == getattr(cfg, key), key
    for key in ("DIFFUSION_THETA", "DYNAMIC_FLUX_THETA", "IMPLICIT_TOL",
                "IMPLICIT_SLOPE_FLOOR", "IMPLICIT_THETA", "IMPLICIT_RELAX",
                "IMPLICIT_CFL_TARGET", "MANNING_SLOPE_CAP"):
        assert getattr(out, key) == pytest.approx(getattr(cfg, key)), key


def test_off_values_map_back_to_none(dialog):
    out = _roundtrip(dialog.tab_routing,
                     Config(MANNING_SLOPE_CAP=None, IMPLICIT_NUM_THREADS=None))
    assert out.MANNING_SLOPE_CAP is None
    assert out.IMPLICIT_NUM_THREADS is None


def test_implicit_disclosure(dialog):
    tab = dialog.tab_routing
    shown = lambda w: w.isVisibleTo(tab)  # noqa: E731 — tab page need not be current
    tab.apply_config(Config(ROUTING_SCHEME="diffusive_implicit", ADAPTIVE_TIMESTEP=True))
    assert shown(tab.implicit_cfl_target)
    assert not shown(tab.cfl_target)               # explicit C ≤ 1 doesn't apply
    assert shown(tab._grp_implicit)                # solver settings (collapsed group)
    assert tab._grp_implicit.isCollapsed()
    assert not shown(tab.diffusion_theta)
    tab.apply_config(Config(ROUTING_SCHEME="dynamic", ADAPTIVE_TIMESTEP=True))
    assert shown(tab.dynamic_flux_theta)
    assert shown(tab.cfl_target)
    assert not shown(tab._grp_implicit)


@pytest.mark.parametrize("rule", [
    {1: 0.05, 2: 0.04, 3: 0.03},            # per Strahler order
    [(1000.0, 0.05), (3000.0, 0.035)],      # elevation breakpoints
])
def test_non_scalar_channel_n_is_preserved(dialog, rule):
    out = _roundtrip(dialog.tab_routing, Config(MANNINGS_N_CHANNEL=rule))
    assert out.MANNINGS_N_CHANNEL == rule


def test_channel_n_scalar_and_off(dialog):
    assert _roundtrip(dialog.tab_routing, Config(MANNINGS_N_CHANNEL=0.042)).MANNINGS_N_CHANNEL \
        == pytest.approx(0.042)
    tab = dialog.tab_routing
    tab.apply_config(Config(MANNINGS_N_CHANNEL={1: 0.05}))
    tab.channel_n_override.setChecked(False)   # user drops the custom rule
    out = Config()
    tab.write_to_config(out)
    assert out.MANNINGS_N_CHANNEL is None


# ── Runoff: SCS-CN source ─────────────────────────────────────────────────────

@pytest.mark.parametrize("src", ["scalar", "gee", "raster"])
def test_scs_cn_source_roundtrip(dialog, src):
    cfg = Config(RUNOFF_SOURCE="scs_cn", RUNOFF_CN_SOURCE=src,
                 RUNOFF_CN_AMC="iii", RUNOFF_CN=82.0)
    out = _roundtrip(dialog.tab_runoff, cfg)
    assert (out.RUNOFF_SOURCE, out.RUNOFF_CN_SOURCE, out.RUNOFF_CN_AMC) == ("scs_cn", src, "iii")
    assert out.RUNOFF_CN == pytest.approx(82.0)


def test_scs_cn_ui_default_runs_offline(dialog):
    """Picking SCS-CN in a fresh dialog must not silently require Earth Engine."""
    tab = dialog.tab_runoff
    tab.mode_combo.setCurrentIndex(tab._MODES.index("scs_cn"))
    out = Config()
    tab.write_to_config(out)
    assert out.RUNOFF_CN_SOURCE == "scalar"


# ── Precipitation: rain/snow partition ────────────────────────────────────────

def test_rain_snow_partition_roundtrip(dialog):
    out = _roundtrip(dialog.tab_precip,
                     Config(RAIN_SNOW_ELEV_LOW=3200.0, RAIN_SNOW_ELEV_HIGH=4100.0))
    assert (out.RAIN_SNOW_ELEV_LOW, out.RAIN_SNOW_ELEV_HIGH) == (3200.0, 4100.0)
    out = _roundtrip(dialog.tab_precip, Config())
    assert out.RAIN_SNOW_ELEV_LOW is None and out.RAIN_SNOW_ELEV_HIGH is None


def test_rain_snow_single_threshold(dialog):
    out = _roundtrip(dialog.tab_precip, Config(RAIN_SNOW_ELEV_HIGH=3500.0))
    assert (out.RAIN_SNOW_ELEV_LOW, out.RAIN_SNOW_ELEV_HIGH) == (3500.0, 3500.0)


# ── Whole dialog: load / build / save ─────────────────────────────────────────

def test_load_config_keeps_settings_without_widgets(dialog, tmp_path):
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"")
    src = Config(
        DEM_PATH=str(dem), OUTPUT_DIR=str(tmp_path / "out"),
        ROUTING_SCHEME="dynamic", DYNAMIC_FLUX_THETA=0.7,
        ROUTING_GAUGES=[{"name": "g1", "lat": 27.9, "lon": 85.2}],
        SAVE_FIELDS=True, FIELD_STRIDE=3,
    )
    path = tmp_path / "run.json"
    src.save(str(path))

    dialog.load_config(str(path))
    cfg = dialog._build_config()
    assert cfg.ROUTING_SCHEME == "dynamic"
    assert cfg.DYNAMIC_FLUX_THETA == pytest.approx(0.7)
    assert cfg.ROUTING_GAUGES == src.ROUTING_GAUGES
    assert cfg.SAVE_FIELDS is True and cfg.FIELD_STRIDE == 3
    assert cfg.DEM_PATH == str(dem)
    cfg.validate()


def test_saved_config_reloads(dialog, tmp_path):
    dialog.tab_routing.scheme_combo.setCurrentIndex(
        dialog.tab_routing._SCHEMES.index("diffusive_implicit"))
    dialog.tab_routing.implicit_cfl_target.setValue(4.0)
    cfg = dialog._build_config()
    for ext in (".json", ".py"):
        path = str(tmp_path / f"saved{ext}")
        if ext == ".py":
            from MRRpy_plugin.ui.main_dialog import _write_config_py
            _write_config_py(cfg, path)
        else:
            cfg.save(path)
        back = Config.from_file(path)
        assert back.ROUTING_SCHEME == "diffusive_implicit"
        assert back.IMPLICIT_CFL_TARGET == pytest.approx(4.0)


# ── Naming, labels and first-run behaviour ────────────────────────────────────

def test_plugin_names(qgis_app):
    import configparser
    meta = configparser.ConfigParser()
    meta.read(os.path.join(_REPO, "MRRpy_plugin", "metadata.txt"))
    assert meta["general"]["name"] == "MRRpy_plugin"
    from MRRpy_plugin.processing.provider import ProcessingProvider
    prov = ProcessingProvider()
    assert (prov.id(), prov.name()) == ("mrrpy_plugin", "MRRpy_plugin")
    from MRRpy_plugin.processing.alg_router import RoutingAlgorithm
    from MRRpy_plugin.processing.alg_process_dem import ProcessDemAlgorithm
    assert (RoutingAlgorithm().name(), ProcessDemAlgorithm().name()) == ("routing", "process_dem")


def test_labels_render_literally(dialog):
    """No single '&' (Qt would eat it as a shortcut) and no emoji on buttons."""
    import re
    from qgis.PyQt.QtWidgets import QAbstractButton, QGroupBox
    texts = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    texts += [w.title() for w in dialog.findChildren(QGroupBox)]
    texts += [w.text() for w in dialog.findChildren(QAbstractButton)]
    for t in texts:
        assert not re.search(r"(?<!&)&(?!&)", t), t
        assert not re.search("[\U0001F300-\U0001FAFF\u2600-\u27BF]", t), t


def test_fresh_dialog_runs_offline(dialog, tmp_path):
    """Pick a DEM, press Run: the defaults must not need Earth Engine."""
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"")
    dialog.tab_dem.dem_widget.setFilePath(str(dem))
    cfg = dialog._build_config()
    cfg.validate()
    assert not dialog.tab_precip._grp_ee.isVisibleTo(dialog.tab_precip)
    assert not dialog.tab_runoff._grp_ee.isVisibleTo(dialog.tab_runoff)


def test_earth_engine_fields_follow_the_options(dialog):
    precip, runoff = dialog.tab_precip, dialog.tab_runoff
    shown = lambda w, tab: w.isVisibleTo(tab)  # noqa: E731
    # SERVES soil moisture → project on both tabs + the event date on Precipitation
    runoff.mode_combo.setCurrentIndex(runoff._MODES.index("physical"))
    runoff._chk_sat.setChecked(True)
    runoff._sd_source.setCurrentIndex(1)
    assert shown(runoff._grp_ee, runoff) and shown(precip._grp_ee, precip)
    assert shown(precip.event_dt, precip) and not shown(precip.utc_offset, precip)
    runoff._sd_source.setCurrentIndex(0)
    assert not shown(precip._grp_ee, precip)
    # LULC Manning's n → project only
    dialog.tab_routing.mannings_source.setCurrentIndex(1)
    assert shown(precip._grp_ee, precip) and not shown(precip.event_dt, precip)
    dialog.tab_routing.mannings_source.setCurrentIndex(0)
    # IMERG → project, event date and UTC offset
    precip.method_combo.setCurrentIndex(precip._METHODS.index("imerg_idw"))
    assert all(shown(w, precip) for w in (precip._grp_ee, precip.event_dt, precip.utc_offset))
    cfg = Config()
    precip.write_to_config(cfg)
    assert cfg.EVENT_START_UTC                      # required date is always written


def test_delineation_links_to_dem_stage(dialog):
    assert dialog.chk_dem.isChecked()
    dialog._on_dem_step_finished({"task": "delineate"})
    assert not dialog.chk_dem.isChecked()           # Run reuses the watershed
    dialog.tab_dem.lat_spin.setValue(dialog.tab_dem.lat_spin.value() + 0.01)
    assert dialog.chk_dem.isChecked()               # new outlet → recompute


def test_routing_without_watershed_is_blocked(dialog, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[1]))
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"")
    dialog.tab_dem.dem_widget.setFilePath(str(dem))
    dialog.tab_dem.output_dir_widget.setFilePath(str(tmp_path / "empty_out"))
    dialog.chk_dem.setChecked(False)
    dialog._on_run()
    assert shown == ["No watershed yet"] and dialog._worker is None


def test_cancel_reenables_run(dialog, tmp_path):
    from MRRpy_plugin.bridge.runner import PipelineWorker
    w = PipelineWorker(Config(OUTPUT_DIR=str(tmp_path)), ["routing"])
    got = []
    w.cancelled.connect(lambda: got.append("cancelled"))
    w.finished.connect(lambda r: got.append("finished"))
    w.cancel()
    w.run()                                          # synchronous: stops before stage 1
    assert got == ["cancelled"]
    dialog.run_btn.setEnabled(False)
    dialog._on_cancelled()
    assert dialog.run_btn.isEnabled()
