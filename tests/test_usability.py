# -*- coding: utf-8 -*-
"""
tests/test_usability.py
=======================
The parts added to make MRRpy easier to use and harder to misuse:

* Config: typos are refused, numbers typed as text are read, paths with a
  value of their own are kept, a hand-edited file gets the wizard's checks,
  the map projection can be chosen for you.
* A run: log file, quiet mode, progress and cancel inside the routing, the
  run record, clock times in the outputs, the results object.
* Rain: gauge files in latitude/longitude and clock time, the 'interval'
  reading of rain tables, ensemble members.
* Many runs in one call, the ensemble runner, flow records and skill scores,
  the DEM download without an account, the demo, the doctor.

Nothing here uses the internet (downloads are replaced by local stand-ins).
Run:  pytest tests/test_usability.py -v
"""

import contextlib
import glob
import io
import json
import os
import re

import numpy as np
import pandas as pd
import pytest
import rasterio

import MRRpy
from MRRpy import Config, run_pipeline
from MRRpy import config_schema as S
from MRRpy.cli.main import main as cli


@pytest.fixture(scope="module")
def valley(tmp_path_factory):
    """The sample valley: (dem path, outlet (lat, lon), a base Config factory)."""
    d = tmp_path_factory.mktemp("valley")
    dem, outlet = MRRpy.sample.sample_dem(str(d / "dem.tif"), n=61)

    def make(out, **kw):
        base = dict(DEM_PATH=dem, OUTPUT_POINT=outlet, OUTPUT_DIR=str(out),
                    RAIN_INTENSITY_MM_HR=20.0, RAIN_DURATION_HOURS=1.0,
                    TOTAL_SIMULATION_TIME_HOURS=4.0, CHANNEL_MIN_AREA_KM2=2.0,
                    CHANNEL_QBF_M3S=50.0)
        base.update(kw)
        return Config(**base)
    return dem, outlet, make


def _quietly(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


# ── Config: typos, numbers as text ───────────────────────────────────────────

def test_typo_in_assignment_is_refused_with_a_suggestion():
    cfg = Config()
    with pytest.raises(AttributeError, match="ROUTING_SCHEME"):
        cfg.ROUTNG_SCHEME = "muskingum"
    with pytest.raises(AttributeError, match="did you mean DEM_PATH"):
        Config(DEM_PAHT="x")
    with pytest.raises(AttributeError, match="did you mean DEM_PATH"):
        Config.from_dict({"dem_path": "x"})
    cfg.note = "lower-case attributes of your own are still allowed"


def test_numbers_typed_as_text_are_read(tmp_path):
    cfg = Config(TIME_STEP_SECONDS="2", MIN_SLOPE="1e-4", OUTPUT_INTERVAL_SECONDS="600")
    assert cfg.TIME_STEP_SECONDS == 2.0 and cfg.MIN_SLOPE == 1e-4
    assert cfg.OUTPUT_INTERVAL_SECONDS == 600 and isinstance(cfg.OUTPUT_INTERVAL_SECONDS, int)
    with pytest.raises(ValueError, match="not a number"):
        Config(TIME_STEP_SECONDS="fast")
    # PyYAML reads 1e-5 (no dot) as text: the file must still load as a number.
    f = tmp_path / "c.yaml"
    f.write_text("MIN_SLOPE: 1e-5\nCFL_DT_MAX: null\n")
    cfg = Config.from_file(f)
    assert cfg.MIN_SLOPE == 1e-5 and cfg.CFL_DT_MAX is None


def test_legacy_py_config_reads_mixed_case_names(tmp_path):
    f = tmp_path / "legacy.py"
    f.write_text("RUNOFF_SCS_Ia_FACTOR = 0.05\nOUTPUT_DIR = 'runs/x/'\n"
                 "ROUTING_DEM_PATH = OUTPUT_DIR + 'clipped_dem.tif'\nhelper = 3\n")
    cfg = Config.from_file(f)
    assert cfg.RUNOFF_SCS_Ia_FACTOR == 0.05
    assert not cfg.explicit_paths()                    # the path follows OUTPUT_DIR


# ── Config: output paths ─────────────────────────────────────────────────────

def test_output_dir_moves_the_paths_that_follow_it():
    cfg = Config(OUTPUT_DIR="results/")
    assert cfg.HYDROGRAPH_CSV == os.path.join("results/", "hydrograph.csv")
    cfg.OUTPUT_DIR = "other"
    assert cfg.ROUTING_DEM_PATH == os.path.join("other", "clipped_dem.tif")
    assert cfg.explicit_paths() == {}


def test_a_path_with_its_own_value_is_kept(tmp_path):
    shared = str(tmp_path / "shared_imerg")
    cfg = Config.from_dict({"OUTPUT_DIR": str(tmp_path / "a"), "PRECIP_IMERG_DIR": shared})
    cfg.OUTPUT_DIR = str(tmp_path / "b")
    from MRRpy.pipeline import prepare_output_dir
    prepare_output_dir(cfg, log=lambda s: None)
    assert cfg.PRECIP_IMERG_DIR == shared
    assert cfg.HYDROGRAPH_CSV == str(tmp_path / "b" / "hydrograph.csv")
    assert list(cfg.explicit_paths()) == ["PRECIP_IMERG_DIR"]
    # … and it survives save → load, while the following paths are not written.
    f = str(tmp_path / "c.yaml")
    cfg.save(f)
    text = open(f).read()
    assert "PRECIP_IMERG_DIR" in text and "HYDROGRAPH_CSV" not in text
    assert Config.from_file(f).PRECIP_IMERG_DIR == shared


def test_a_full_dump_with_an_edited_output_dir_writes_to_the_new_one(tmp_path, capsys):
    old = Config(OUTPUT_DIR=str(tmp_path / "old"))
    data = old.to_dict()                                # every path, under old/
    data["OUTPUT_DIR"] = str(tmp_path / "new")
    cfg = Config.from_dict(data)
    assert cfg.HYDROGRAPH_CSV == str(tmp_path / "new" / "hydrograph.csv")
    assert "writing to OUTPUT_DIR" in capsys.readouterr().out


def test_copy_equality_and_short_repr():
    a = Config(ROUTING_GAUGES=[{"name": "g", "lat": 1.0, "lon": 2.0}], MANNINGS_N=0.05)
    b = a.copy(ROUTING_SCHEME="muskingum")
    b.ROUTING_GAUGES[0]["name"] = "changed"
    assert a.ROUTING_GAUGES[0]["name"] == "g"           # an independent copy
    assert a == a.copy() and a != b
    assert repr(Config()) == "Config()" and "MANNINGS_N=0.05" in repr(a)
    assert set(a.changes()) == {"ROUTING_GAUGES", "MANNINGS_N"}


# ── Config: a hand-edited file gets the wizard's checks ──────────────────────

@pytest.mark.parametrize("bad, word", [
    (dict(TARGET_CRS_EPSG="EPSG:4326"), "degrees"),
    (dict(TARGET_CRS_EPSG="utm45"), "not a coordinate system"),
    (dict(RAIN_INTENSITY_MM_HR=-5), "at least 0"),
    (dict(PRECIP_METHOD="openmeteo_idw", EVENT_START_UTC="27/09/2024"), "not a date"),
    (dict(OUTPUT_POINT=(127.6, 85.29)), "Latitude"),
    (dict(OUTPUT_INTERVAL_SECONDS=0), "at least 1"),
])
def test_validate_applies_the_catalogue_checks(valley, tmp_path, bad, word):
    cfg = valley[2](tmp_path, **bad)
    with pytest.raises(ValueError, match=word):
        cfg.validate()


def test_validate_passes_the_sample_and_ignores_settings_that_do_not_matter(valley, tmp_path):
    cfg = valley[2](tmp_path, RAIN_SNOW_ELEV_LOW=None)
    cfg.PRECIP_IDW_POWER = -3                # not used by a uniform storm: not judged
    cfg.validate()


def test_validate_catches_an_outlet_outside_the_dem(valley, tmp_path):
    _dem, (lat, lon), make = valley
    with pytest.raises(ValueError, match="outside your DEM.*longitude first"):
        make(tmp_path, OUTPUT_POINT=(lon, lat)).validate()
    with pytest.raises(ValueError, match="outside your DEM"):
        make(tmp_path, OUTPUT_POINT=(40.0, -75.0)).validate()


def test_validate_catches_a_projection_from_another_part_of_the_world(valley, tmp_path):
    with pytest.raises(ValueError, match="made for longitudes"):
        valley[2](tmp_path, TARGET_CRS_EPSG="EPSG:32618").validate()      # UTM 18N: Vermont
    valley[2](tmp_path, TARGET_CRS_EPSG="EPSG:32644").validate()          # the next zone: fine


def test_earth_engine_options_need_a_project_whatever_the_runoff_method(valley, tmp_path,
                                                                        monkeypatch):
    monkeypatch.delenv("GEE_PROJECT", raising=False)
    cfg = valley[2](tmp_path, MANNINGS_N_SOURCE="lulc", RUNOFF_SOURCE="scs_cn",
                    RUNOFF_CN_SOURCE="scalar")
    with pytest.raises(ValueError, match="GEE_PROJECT.*MANNINGS_N_SOURCE"):
        cfg.validate()


# ── Map projection chosen for you ────────────────────────────────────────────

def test_auto_projection_is_the_outlets_utm_zone(valley, tmp_path):
    cfg = valley[2](tmp_path / "o")
    assert cfg.TARGET_CRS_EPSG == "auto"
    out = _quietly(run_pipeline, cfg, stages=("process_dem",))
    assert cfg.TARGET_CRS_EPSG == "EPSG:32645"
    with rasterio.open(out["clipped_dem"]) as ds:
        assert ds.crs.to_epsg() == 32645
    assert "TARGET_CRS_EPSG: EPSG:32645" in open(tmp_path / "o" / "run_config.yaml").read()


def test_auto_projection_without_a_place_says_what_to_give():
    from MRRpy.utils.crs import resolve_target_crs
    cfg = Config(MODEL_AREA="whole_dem")
    with pytest.raises(ValueError, match="OUTPUT_POINT"):
        resolve_target_crs(cfg, log=lambda s: None)


# ── A run: log, quiet, progress, cancel, record, results object ──────────────

@pytest.fixture(scope="module")
def a_run(valley, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("run")
    cfg = valley[2](out_dir, EVENT_START_UTC="2024-09-27 06:00",
                    ROUTING_GAUGES=[{"name": "mid", "lat": valley[1][0] + 0.01,
                                     "lon": valley[1][1]}])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = run_pipeline(cfg, quiet=True)
    return cfg, out, buf.getvalue(), str(out_dir)


def test_quiet_run_prints_no_report_but_logs_it(a_run):
    _cfg, out, printed, folder = a_run
    assert "ROUTING GRID INITIALISATION" not in printed
    log = open(os.path.join(folder, "run.log")).read()
    assert "ROUTING GRID INITIALISATION" in log and "MASS BALANCE" in log
    assert not out.cancelled


def test_run_record_is_saved_and_runs_again(a_run):
    cfg, out, _printed, folder = a_run
    info = json.load(open(os.path.join(folder, "run_info.json")))
    assert info["status"] == "finished" and info["mrrpy_version"] == MRRpy.__version__
    assert info["stages"] == ["process_dem", "routing"]
    assert abs(info["mass_balance_rel_error"]) < 1e-6 and info["peak_m3s"] == out.peak_m3s
    again = Config.from_file(os.path.join(folder, "run_config.yaml"))
    assert again.DEM_PATH == cfg.DEM_PATH and again.EVENT_START_UTC == cfg.EVENT_START_UTC
    again.validate()


def test_outputs_carry_clock_times_when_the_start_is_known(a_run):
    _cfg, out, _printed, folder = a_run
    hyd = pd.read_csv(out["hydrograph_csv"])
    assert list(hyd.columns) == ["time_s", "time_hr", "Q_m3s", "time_utc"]
    assert hyd.time_utc.iloc[0] == "2024-09-27 06:10:00"
    gauges = pd.read_csv(os.path.join(folder, "gauges.csv"))
    assert gauges.columns[-1] == "time_utc" and gauges.time_utc.iloc[-1] == hyd.time_utc.iloc[-1]


def test_no_clock_column_without_a_start_date(valley, tmp_path):
    out = _quietly(run_pipeline, valley[2](tmp_path), quiet=True)
    assert "time_utc" not in out.hydrograph.columns


def test_results_object_is_still_a_dict_with_shortcuts(a_run):
    _cfg, out, _printed, folder = a_run
    assert isinstance(out, dict) and os.path.exists(out["hydrograph_csv"])
    assert out.hydrograph is out["hydrograph_df"]
    assert out.peak_m3s == pytest.approx(out.hydrograph.Q_m3s.max())
    text = out.summary()
    assert "Peak flow" in text and "water balance closes" in text and folder in text
    assert out.output_dir == folder
    import matplotlib
    matplotlib.use("Agg")
    fig, _ax = out.plot()
    assert fig is not None


def test_on_log_gets_every_line_and_nothing_is_printed(valley, tmp_path):
    lines, progress = [], []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_pipeline(valley[2](tmp_path), on_log=lines.append, on_progress=progress.append)
    assert buf.getvalue() == ""
    assert any("MASS BALANCE" in ln for ln in lines) and all("\n" not in ln for ln in lines)
    assert progress == sorted(progress) and progress[-1] == 100
    assert len([p for p in progress if 46 < p < 90]) > 5      # it moves during the routing


def test_cancel_stops_the_routing_within_a_step(valley, tmp_path):
    state = {"stop": False}

    def on_progress(pct):
        if pct >= 60:
            state["stop"] = True

    out = _quietly(run_pipeline, valley[2](tmp_path), on_progress=on_progress,
                   is_cancelled=lambda: state["stop"], on_log=lambda s: None)
    assert out.cancelled and "hydrograph_csv" not in out
    assert json.load(open(tmp_path / "run_info.json"))["status"] == "cancelled"


def test_a_failed_run_is_recorded(valley, tmp_path):
    cfg = valley[2](tmp_path, RUNOFF_SOURCE="raster")            # no manifest → fails
    with pytest.raises(Exception):
        _quietly(run_pipeline, cfg)
    info = json.load(open(tmp_path / "run_info.json"))
    assert info["status"] == "failed" and "error" in info


def test_capture_is_per_thread():
    import threading
    from MRRpy.utils.runlog import capture
    seen, other = [], io.StringIO()

    def elsewhere():
        print("from another thread")

    with contextlib.redirect_stdout(other):
        with capture(on_line=seen.append):
            print("from the run")
            t = threading.Thread(target=elsewhere)
            t.start()
            t.join()
    assert seen == ["from the run"] and "from another thread" in other.getvalue()


# ── Rain files as people keep them ───────────────────────────────────────────

@pytest.fixture(scope="module")
def rain_files(valley, tmp_path_factory):
    d = tmp_path_factory.mktemp("rain")
    lat, lon = valley[1]
    g, r = str(d / "gauges.csv"), str(d / "rain.csv")
    pd.DataFrame({"gauge_id": ["G1"], "name": ["a"], "Latitude": [lat + 0.02],
                  "Longitude": [lon]}).to_csv(g, index=False)
    pd.DataFrame({"time": pd.date_range("2024-09-27 05:00", periods=8, freq="h"),
                  "G1": [0, 0, 0, 20, 0, 0, 0, 0]}).to_csv(r, index=False)   # 07–08 h UTC
    return g, r


def _gauge_run(valley, rain_files, out, **kw):
    cfg = valley[2](out, PRECIP_METHOD="thiessen", PRECIP_GAUGE_FILE=rain_files[0],
                    PRECIP_TIMESERIES_FILE=rain_files[1],
                    EVENT_START_UTC="2024-09-27 06:00", TOTAL_SIMULATION_TIME_HOURS=6.0, **kw)
    cfg.validate()
    out = _quietly(run_pipeline, cfg, quiet=True)
    mb = pd.read_csv(out["mass_balance_csv"]).iloc[-1]
    with rasterio.open(out["watershed_tif"]) as ws:
        area = float((ws.read(1) > 0).sum()) * abs(ws.transform.a * ws.transform.e)
    return out, 1000.0 * mb.rain_m3 / area


def test_gauges_in_latlon_and_clock_time(valley, rain_files, tmp_path):
    out, rain_mm = _gauge_run(valley, rain_files, tmp_path)
    assert rain_mm == pytest.approx(20.0, rel=1e-6)
    assert out.peak_m3s > 0


def test_interval_reading_keeps_the_burst_in_its_hour(valley, rain_files, tmp_path):
    lin, mm_lin = _gauge_run(valley, rain_files, tmp_path / "lin")
    itv, mm_itv = _gauge_run(valley, rain_files, tmp_path / "itv",
                             PRECIP_INTERPOLATION="interval")
    assert mm_lin == pytest.approx(20.0, rel=1e-6) and mm_itv == pytest.approx(20.0, rel=1e-6)
    # The burst fell between 1 and 2 h of the run.  Read by interval it ends at
    # 2 h; joined by straight lines it lasts until 3 h, so its peak comes later.
    assert itv.peak_time_hr < lin.peak_time_hr
    assert itv.peak_m3s > lin.peak_m3s


def test_interval_rates_for_both_stamp_conventions():
    from MRRpy.core.precip.engine import PrecipEngine
    eng = PrecipEngine.__new__(PrecipEngine)
    eng._by_interval, eng._n_gauges = True, 1
    eng._time_s = np.array([0.0, 3600.0, 7200.0, 10800.0])
    eng._intervals = np.full(4, 3600.0)
    eng._rates_ms = np.array([[0.0], [1.0], [2.0], [0.0]])
    eng._stamp = "end"                      # row 1 covers (0, 3600], row 2 (3600, 7200]
    assert [float(eng._interp_gauges(t)[0]) for t in (1.0, 3600.0, 3601.0, 7200.0, 7201.0)] \
        == [1.0, 1.0, 2.0, 2.0, 0.0]
    eng._stamp = "start"                    # row 1 covers [3600, 7200), row 2 [7200, 10800)
    assert [float(eng._interp_gauges(t)[0]) for t in (1.0, 3600.0, 7199.0, 7200.0, 10799.0)] \
        == [0.0, 1.0, 1.0, 2.0, 2.0]


def test_unreadable_gauge_files_say_what_is_wanted(valley, tmp_path):
    g, r = str(tmp_path / "g.csv"), str(tmp_path / "r.csv")
    pd.DataFrame({"gauge_id": ["G1"], "x": [1], "y": [2]}).to_csv(g, index=False)
    pd.DataFrame({"hour": [0, 1], "G1": [0, 1]}).to_csv(r, index=False)
    cfg = valley[2](tmp_path / "o", PRECIP_METHOD="thiessen", PRECIP_GAUGE_FILE=g,
                    PRECIP_TIMESERIES_FILE=r)
    with pytest.raises(ValueError, match="'lat' and 'lon'"):
        _quietly(run_pipeline, cfg, quiet=True)


# ── Many runs in one call ────────────────────────────────────────────────────

def test_run_many_shares_the_terrain_and_reports_failures(valley, tmp_path):
    base = valley[2](tmp_path / "unused")
    table = _quietly(MRRpy.run_many, base, {
        "smooth": {"MANNINGS_N": 0.05},
        "rough": {"MANNINGS_N": 0.15},
        "broken": {"RUNOFF_SOURCE": "raster"},
    }, output_dir=str(tmp_path / "batch"))
    assert list(table["name"]) == ["smooth", "rough", "broken"]
    assert list(table["status"]) == ["finished", "finished", "failed"]
    ok = table.set_index("name")
    assert ok.loc["smooth", "peak_m3s"] > ok.loc["rough", "peak_m3s"]
    assert "RUNOFF_RASTER_MANIFEST" in ok.loc["broken", "error"]
    assert os.path.exists(tmp_path / "batch" / "summary.csv")
    assert os.path.isdir(tmp_path / "batch" / "_terrain")
    # each run folder is complete on its own (terrain files are there)
    assert os.path.exists(tmp_path / "batch" / "rough" / "watershed.tif")
    # … and equals a run made the ordinary way
    alone = _quietly(run_pipeline, base.copy(MANNINGS_N=0.15, OUTPUT_DIR=str(tmp_path / "alone")),
                     quiet=True)
    batch = pd.read_csv(tmp_path / "batch" / "rough" / "hydrograph.csv")
    assert np.array_equal(batch.Q_m3s.values, pd.read_csv(alone["hydrograph_csv"]).Q_m3s.values)


def test_run_many_side_by_side_gives_the_same_table(valley, tmp_path):
    base = valley[2](tmp_path / "unused")
    runs = [{"MANNINGS_N": 0.05}, {"name": "musk", "ROUTING_SCHEME": "muskingum"}]
    one = _quietly(MRRpy.run_many, base, runs, output_dir=str(tmp_path / "one"))
    two = _quietly(MRRpy.run_many, base, runs, output_dir=str(tmp_path / "two"), workers=2)
    assert list(two["name"]) == ["run_01", "musk"] and list(two["status"]) == ["finished"] * 2
    assert np.allclose(one["peak_m3s"], two["peak_m3s"], rtol=0, atol=0)
    assert not glob.glob(str(tmp_path / "two" / "*" / "batch_*.json"))


def test_run_many_refuses_names_that_are_not_folder_names(valley, tmp_path):
    with pytest.raises(ValueError, match="plain name"):
        MRRpy.run_many(valley[2](tmp_path), {"a/b": {}}, output_dir=str(tmp_path / "x"))


# ── Ensemble forecast (the download replaced by a stand-in) ──────────────────

@pytest.fixture
def fake_ensemble(monkeypatch):
    from MRRpy.core.precip import openmeteo as om

    def fetch(api, lats, lons, start_date, end_date, model="best_match", minutely_15=False,
              run=None):
        assert api == "ensemble" and model == "gfs_seamless"
        t0 = int(pd.Timestamp(start_date, tz="UTC").timestamp())
        times = [t0 + 3600 * i for i in range(72)]
        out = []
        for la, lo in zip(lats, lons):
            base = [5.0 if 26 <= i < 28 else 0.0 for i in range(72)]
            out.append({"latitude": round(float(la), 2), "longitude": round(float(lo), 2),
                        "time": times, "precipitation": base,
                        "members": {m: [v * (1 + 0.5 * m) for v in base] for m in (1, 2, 3)}})
        return out
    monkeypatch.setattr(om, "fetch_points", fetch)


def test_ensemble_member_setting_and_runner(valley, tmp_path, fake_ensemble):
    cfg = valley[2](tmp_path / "e", PRECIP_METHOD="openmeteo_thiessen",
                    OPENMETEO_MODEL="gfs_seamless", EVENT_START_UTC="2024-09-27 00:00",
                    TOTAL_SIMULATION_TIME_HOURS=8.0)
    res = _quietly(MRRpy.run_ensemble, cfg)
    frame = res["hydrographs"]
    members = [c for c in frame.columns if c.startswith("member_")]
    assert members == ["member_00", "member_01", "member_02", "member_03"]
    peaks = frame[members].max()
    assert peaks["member_03"] > peaks["member_02"] > peaks["member_01"] > peaks["member_00"] > 0
    assert (frame["p10"] <= frame["median"]).all() and (frame["median"] <= frame["p90"]).all()
    assert os.path.exists(res["csv"]) and "time_utc" in frame.columns
    # one download serves every member
    assert len(glob.glob(os.path.join(res["output_dir"], "_rain", "timeseries_member*.csv"))) == 4
    import matplotlib
    matplotlib.use("Agg")
    fig, _ax = MRRpy.plot_ensemble(res, members=True)
    assert fig is not None


def test_ensemble_needs_an_ensemble_model(valley, tmp_path):
    cfg = valley[2](tmp_path, PRECIP_METHOD="openmeteo_idw", OPENMETEO_SOURCE="ensemble",
                    EVENT_START_UTC="2024-09-27 00:00")
    with pytest.raises(ValueError, match="gfs_seamless"):
        cfg.validate()
    with pytest.raises(ValueError, match="Open-Meteo rain"):
        MRRpy.run_ensemble(valley[2](tmp_path))


# ── Flow records and skill ───────────────────────────────────────────────────

def test_read_flow_csv_and_skill(a_run, tmp_path):
    _cfg, out, _printed, _folder = a_run
    hyd = out.hydrograph
    f = tmp_path / "obs.csv"
    local = pd.to_datetime(hyd.time_utc) + pd.Timedelta(hours=5.75)       # Nepal time
    pd.DataFrame({"DateTime": local, "Discharge": hyd.Q_m3s * 1.1 / 0.028316846592}) \
        .to_csv(f, index=False)
    obs = MRRpy.observed.read_flow_csv(f, unit="ft3/s", utc_offset_hours=5.75)
    assert list(obs.columns) == ["time_utc", "Q_m3s"]
    sk = MRRpy.observed.skill(out, obs)
    assert sk["peak_timing_hours"] == 0.0
    assert sk["peak_error_percent"] == pytest.approx(-100 / 11, rel=1e-4)
    assert sk["bias_percent"] == pytest.approx(-100 / 11, rel=1e-4) and 0.9 < sk["nse"] < 1.0
    same = MRRpy.observed.skill(out, obs.assign(Q_m3s=obs.Q_m3s / 1.1))
    assert same["nse"] == pytest.approx(1.0) and same["kge"] == pytest.approx(1.0)
    import matplotlib
    matplotlib.use("Agg")
    fig, ax = MRRpy.plot_hydrograph(out, observed=obs)
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["MRRpy", "observed"]


def test_skill_needs_clock_times(valley, tmp_path):
    out = _quietly(run_pipeline, valley[2](tmp_path), quiet=True)
    obs = pd.DataFrame({"time_utc": pd.date_range("2024-01-01", periods=5, freq="h"),
                        "Q_m3s": [1.0, 2, 3, 2, 1]})
    with pytest.raises(ValueError, match="EVENT_START_UTC"):
        MRRpy.observed.skill(out, obs)
    assert MRRpy.observed.skill(out, obs, start_utc="2024-01-01")["n"] >= 3


def test_glofas_reader_and_two_year_flood(monkeypatch):
    from MRRpy import observed

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        days = pd.date_range("2000-01-01", "2003-12-31", freq="D")
        q = [100.0 + (300.0 if (d.month, d.day) == (7, 1) else 0.0) * (d.year - 1999)
             for d in days]
        return Reply(json.dumps({"latitude": 1.0, "longitude": 2.0, "daily": {
            "time": [d.strftime("%Y-%m-%d") for d in days], "river_discharge": q}}).encode())
    monkeypatch.setattr(observed.urllib.request, "urlopen", urlopen)
    df = observed.glofas_flow(1, 2, "2000-01-01", "2003-12-31")
    assert len(df) == 1461 and df.attrs["cell"] == (1.0, 2.0)
    q2 = observed.glofas_two_year_flood(1, 2, first_year=2000, last_year=2003)
    assert q2["years"] == 4 and q2["q2_m3s"] == pytest.approx(850.0)     # median of 400…1300


# ── DEM without an account (tiles replaced by local files) ───────────────────

def test_open_dem_download_feeds_a_run(tmp_path, monkeypatch):
    from MRRpy.utils import open_dem
    from rasterio.transform import from_origin

    tiles = tmp_path / "tiles"
    tiles.mkdir()

    def tile(dataset, lat, lon):
        path = tiles / f"{lat}_{lon}.tif"
        if not path.exists() and (lat, lon) == (27, 85):
            n = 360
            rows, cols = np.mgrid[0:n, 0:n]
            z = 1500.0 - rows * 2.0 + np.abs(cols - n / 2) * 1.5
            with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1,
                               dtype="float32", crs="EPSG:4326",
                               transform=from_origin(85.0, 28.0, 1 / n, 1 / n)) as ds:
                ds.write(z.astype("float32"), 1)
        return str(path)
    monkeypatch.setattr(open_dem, "tile_url", tile)

    cfg = Config(DEM_BOUNDS_WGS84=(85.3, 27.3, 85.7, 27.7), DEM_SOURCE="glo90_open",
                 OUTPUT_POINT=(27.35, 85.5), OUTPUT_DIR=str(tmp_path / "o"),
                 RAIN_DURATION_HOURS=1.0, TOTAL_SIMULATION_TIME_HOURS=2.0)
    cfg.validate()                                    # no Earth Engine project needed
    out = _quietly(run_pipeline, cfg, quiet=True)
    assert os.path.basename(cfg.DEM_PATH) == "raw_dem_open.tif" and out.peak_m3s > 0
    with rasterio.open(cfg.DEM_PATH) as ds:
        assert ds.crs.to_epsg() == 32645 and abs(ds.transform.a) == 90.0
        assert (ds.read(1) != ds.nodata).all()         # no empty edge
    assert not S.earth_engine_uses(S.values_of(cfg)) or all(
        "DEM" not in what for what, _req in S.earth_engine_uses(S.values_of(cfg)))


def test_open_dem_over_the_sea_says_so(tmp_path, monkeypatch):
    from MRRpy.utils import open_dem
    monkeypatch.setattr(open_dem, "tile_url", lambda *a: str(tmp_path / "missing.tif"))
    with pytest.raises(RuntimeError, match="open sea"):
        open_dem.download_open_dem((0.1, 0.1, 0.2, 0.2), "EPSG:32631", str(tmp_path / "d.tif"),
                                   log=lambda s: None)


def test_gee_dem_still_needs_a_project(tmp_path, monkeypatch):
    monkeypatch.delenv("GEE_PROJECT", raising=False)
    cfg = Config(DEM_BOUNDS_WGS84=(85.3, 27.3, 85.7, 27.7), OUTPUT_POINT=(27.35, 85.5))
    with pytest.raises(ValueError, match="glo30_open"):
        cfg.validate()


# ── Demo, doctor, command line ───────────────────────────────────────────────

def test_demo_runs_from_nothing(tmp_path):
    lines = []
    out = MRRpy.demo(str(tmp_path / "demo"), log=lines.append)
    assert out.peak_m3s > 100 and os.path.exists(out["hydrograph_png"])
    cfg = Config.from_file(tmp_path / "demo" / "run.yaml")
    cfg.validate()
    assert any("MRRpy run -c" in ln for ln in lines)


def test_doctor_offline_reports_in_words():
    from MRRpy import doctor
    lines = []
    ok = doctor.report(online=False, out=lines.append)
    text = "\n".join(lines)
    assert ok and "Everything a run needs is here." in text
    assert "OK:      numpy" in text and "Internet checks skipped" in text
    assert {s for s, _w, _d in doctor.check(online=False)} <= {"OK", "MISSING"}


def test_cli_version_quiet_and_plain_errors(valley, tmp_path, capsys):
    with pytest.raises(SystemExit):
        cli(["--version"])
    assert capsys.readouterr().out.strip() == f"MRRpy {MRRpy.__version__}"
    f = str(tmp_path / "run.yaml")
    valley[2](tmp_path / "o").save(f)
    assert cli(["run", "-c", f, "--quiet"]) == 0
    printed = capsys.readouterr().out
    assert "Peak flow at the outlet" in printed and "ROUTING GRID" not in printed
    bad = tmp_path / "bad.yaml"
    bad.write_text("ROUTNG_SCHEME: muskingum\n")
    assert cli(["validate", "-c", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "did you mean ROUTING_SCHEME" in err and "Traceback" not in err
    with pytest.raises(AttributeError):
        cli(["--debug", "validate", "-c", str(bad)])


# ── Flood maps on a basin too small for the map grid's rivers ────────────────

def test_flood_maps_fall_back_to_the_routing_network(tmp_path):
    from pyproj import Transformer
    from rasterio.transform import from_origin
    n, cell = 49, 90.0
    rows, cols = np.mgrid[0:n, 0:n]
    dem = ((n - 1 - rows) * 2.0 + np.abs(cols - (n - 1) / 2.0) * 3.0 + 600.0
           + np.random.default_rng(7).random((n, n)) * 0.4).astype("float32")
    tr = from_origin(330000.0, 3060000.0 + n * cell, cell, cell)
    with rasterio.open(tmp_path / "dem.tif", "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs="EPSG:32645", transform=tr, nodata=-9999.0) as ds:
        ds.write(dem, 1)
    lon, lat = Transformer.from_crs(32645, 4326, always_xy=True).transform(
        *(tr * (24.5, n - 2 + 0.5)))
    cfg = Config(DEM_PATH=str(tmp_path / "dem.tif"), OUTPUT_POINT=(lat, lon),
                 OUTPUT_DIR=str(tmp_path / "o"), TOTAL_SIMULATION_TIME_HOURS=6.0,
                 RAIN_INTENSITY_MM_HR=30.0, RAIN_DURATION_HOURS=1.5, CHANNEL_MIN_AREA_KM2=1.0,
                 CHANNEL_QBF_M3S=8.0, INUNDATION_MAP=True, INUNDATION_ANIMATION=False)
    lines = []
    out = run_pipeline(cfg, on_log=lines.append)
    assert os.path.exists(out["flood_depth_max"]) if "flood_depth_max" in out else True
    assert any("using the routing network" in ln for ln in lines)


# ── One source for fallback values ───────────────────────────────────────────

#: getattr(cfg, NAME, <value>) fallbacks that are deliberately not the Config
#: default: "absent" markers (None, "", 0, []) and four with a meaning of their own.
_OWN_MEANING = {"VSA_SD_MAX_INITIAL", "VSA_Q_MAX", "IMERG_UTC_OFFSET_HOURS",
                "TARGET_CRS_EPSG"}


def test_getattr_fallbacks_agree_with_config_defaults():
    root = os.path.dirname(MRRpy.__file__)
    base = Config()
    pattern = re.compile(r"getattr\(\s*(?:cfg|config|self\.cfg|self\._cfg)\s*,\s*"
                         r"['\"]([A-Z][A-Za-z0-9_]+)['\"]\s*,\s*([^)\n]+?)\)")
    wrong = []
    for path in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        for name, text in pattern.findall(open(path, encoding="utf-8").read()):
            if not hasattr(Config, name) or name in _OWN_MEANING:
                continue
            try:
                value = eval(text, {"_Defaults": Config})          # noqa: S307 — our own source
            except Exception:                                      # an expression: not a literal
                continue
            default = getattr(base, name)
            if value in (None, "", 0, 0.0, [], False) or value == default:
                continue
            if isinstance(value, str) and isinstance(default, str) \
                    and value.lower() == default.lower():
                continue
            if name.endswith(("_CSV", "_PATH", "_DIR")):           # file names, not numbers
                continue
            wrong.append(f"{os.path.relpath(path, root)}: {name} falls back to {text}, "
                         f"Config says {default!r}")
    assert not wrong, "\n".join(wrong)
