"""
Open-Meteo weather-model rain (MRRpy/core/precip/openmeteo.py).

Everything runs against a fake Open-Meteo server (no network): which API the
storm date picks, the query lattice, merging points into model cells, the
"mm in the interval ending at time_s" convention, trimming past the forecast
horizon, the cache, error messages, and a full run through the router.

Set MRRPY_LIVE_OPENMETEO=1 to also run one request against the real API.
"""

import io
import json
import math
import os
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from MRRpy import Config, run_pipeline
from MRRpy import config_schema as S
from MRRpy.core.precip import openmeteo as om
from MRRpy.interactive import render

START = datetime(2024, 9, 27, 0, 0)
T0 = int(START.replace(tzinfo=timezone.utc).timestamp())


def _epoch(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


class FakeOpenMeteo:
    """
    Answers like Open-Meteo: each point is served from the cell_deg-wide cell
    it falls in, with that cell's centre as its coordinates, whole UTC days
    from start_date to end_date.  rain(lat, lon, t) gives the mm in the
    interval ending at t (None = no data).
    """

    def __init__(self, rain, cell_deg=0.1, max_end=None):
        self.rain, self.cell, self.max_end = rain, cell_deg, max_end
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        block = "minutely_15" if "minutely_15" in q else "hourly"
        step = 900 if block == "minutely_15" else 3600
        if "run" in q:                          # single-runs API: run + forecast_days
            assert "start_date" not in q and "end_date" not in q
            t_run = int(datetime.fromisoformat(q["run"]).replace(tzinfo=timezone.utc).timestamp())
            times = list(range(t_run, t_run + int(q["forecast_days"]) * 86400, step))
        else:
            end = date.fromisoformat(q["end_date"])
            if self.max_end and end > self.max_end:
                raise om.OpenMeteoError(
                    f"Parameter 'end_date' is out of allowed range from 2024-01-01 to "
                    f"{self.max_end.isoformat()}")
            times = list(range(_epoch(date.fromisoformat(q["start_date"])),
                               _epoch(end + timedelta(days=1)), step))
        out = []
        for la, lo in zip(map(float, q["latitude"].split(",")),
                          map(float, q["longitude"].split(","))):
            c = self.cell
            cla = round(math.floor(la / c) * c + c / 2, 5)
            clo = round(math.floor(lo / c) * c + c / 2, 5)
            out.append({"latitude": cla, "longitude": clo, "elevation": 100.0,
                        block: {"time": times,
                                "precipitation": [self.rain(cla, clo, t) for t in times]}})
        return out if len(out) > 1 else out[0]


def _points(series_by_cell, times):
    """build_series input: {(lat, lon): [values]} → list of point dicts."""
    return [{"latitude": la, "longitude": lo, "time": list(times), "precipitation": list(v)}
            for (la, lo), v in series_by_cell.items()]


@pytest.fixture
def basin(tmp_path):
    """A watershed polygon near Kathmandu and a config pointing at it."""
    import geopandas as gpd
    from shapely.geometry import box
    gj = str(tmp_path / "watershed.geojson")
    gpd.GeoDataFrame(geometry=[box(85.25, 27.65, 85.35, 27.75)], crs="EPSG:4326").to_file(gj)
    cfg = Config(OUTPUT_DIR=str(tmp_path / "out"), TARGET_CRS_EPSG="EPSG:32645",
                 PRECIP_METHOD="openmeteo_thiessen", EVENT_START_UTC="2024-09-27 00:00",
                 TOTAL_SIMULATION_TIME_HOURS=6.0)
    cfg.update_output_paths()
    cfg.WATERSHED_GEOJSON = gj
    cfg.DEM_PATH = ""
    return cfg


# ── Which API ────────────────────────────────────────────────────────────────
def test_auto_source_follows_the_storm_date():
    today = date(2026, 10, 27)
    recent = datetime(2026, 10, 1)
    future = datetime(2026, 11, 2)
    old = datetime(2024, 9, 27)
    assert om.resolve_source("auto", recent, today=today) == "forecast"
    assert om.resolve_source("auto", future, today=today) == "forecast"
    assert om.resolve_source("auto", old, today=today) == "historical"
    assert om.resolve_source("auto", old, minutely_15=True, today=today) == "historical_forecast"
    assert om.resolve_source("historical_forecast", recent, today=today) == "historical_forecast"
    with pytest.raises(ValueError, match="OPENMETEO_SOURCE"):
        om.resolve_source("ecmwf", old)


def test_event_window_is_utc_and_simulation_length():
    cfg = Config(EVENT_START_UTC="2024-09-27 06:00", TOTAL_SIMULATION_TIME_HOURS=36)
    assert om.event_window(cfg) == (datetime(2024, 9, 27, 6), datetime(2024, 9, 28, 18))
    with pytest.raises(ValueError, match="EVENT_START_UTC"):
        om.event_window(Config())


# ── Query lattice ────────────────────────────────────────────────────────────
def test_query_points_cover_the_buffered_box():
    bounds = (85.25, 27.65, 85.35, 27.75)
    lats, lons, spacing = om.query_points(bounds, 5000.0, 10000.0)
    assert spacing == 5000.0 and len(lats) == len(lons)
    buf_lat = 10000.0 / om._M_PER_DEG
    assert lats.min() < 27.65 - 0.5 * buf_lat and lats.max() > 27.75 + 0.5 * buf_lat
    assert lons.min() < 85.25 and lons.max() > 85.35
    assert np.allclose(np.diff(np.unique(lats.round(6))), 5000.0 / om._M_PER_DEG, atol=1e-5)
    # centred on the box
    assert np.isclose(0.5 * (lats.min() + lats.max()), 27.70)
    assert np.isclose(0.5 * (lons.min() + lons.max()), 85.30)


def test_tiny_basin_gets_its_centre_and_big_basin_is_capped():
    lats, lons, _ = om.query_points((85.3, 27.7, 85.3001, 27.7001), 5000.0, 0.0)
    assert len(lats) == 1 and np.isclose(lats[0], 27.70005) and np.isclose(lons[0], 85.30005)
    lats, _lons, spacing = om.query_points((80.0, 26.0, 88.0, 30.5), 5000.0, 10000.0,
                                           max_points=100)
    assert len(lats) <= 100 and spacing > 5000.0


# ── Merging cells and the time axis ──────────────────────────────────────────
def test_points_in_one_cell_merge_and_empty_cells_drop():
    times = [T0 + 3600 * i for i in range(7)]
    pts = _points({(27.75, 85.25): [1.0] * 7, (27.65, 85.35): [2.0] * 7,
                   (27.65, 85.25): [None] * 7}, times)
    pts.append(dict(pts[0]))                                    # same cell again
    stations, depth, notes = om.build_series(pts, START, START + timedelta(hours=6), 3600)
    assert list(stations["gauge_id"]) == ["OM001", "OM002"]    # north first
    assert list(stations["lat"]) == [27.75, 27.65]
    assert any("no precipitation" in n for n in notes)
    assert list(depth.columns) == ["OM001", "OM002"]
    assert (depth["OM001"] == 1.0).all() and (depth["OM002"] == 2.0).all()


def test_rows_are_depth_in_the_interval_ending_at_time_s():
    # A whole day of data; the window is 03:00–06:00.  The value at 04:00 is the
    # 03:00–04:00 rain, so it lands on time_s = 3600 unchanged.
    times = [T0 + 3600 * i for i in range(24)]
    vals = [float(i) for i in range(24)]
    start = START + timedelta(hours=3)
    _s, depth, notes = om.build_series(_points({(27.7, 85.3): vals}, times),
                                       start, start + timedelta(hours=3), 3600)
    assert list(depth.index) == [0, 3600, 7200, 10800]         # the row at the start is kept
    assert list(depth.iloc[:, 0]) == [3.0, 4.0, 5.0, 6.0]
    assert depth.index.name == "time_s" and not notes


def test_off_hour_start_keeps_the_row_before_it():
    times = [T0 + 3600 * i for i in range(24)]
    start = START + timedelta(minutes=30)
    _s, depth, _n = om.build_series(_points({(27.7, 85.3): [1.0] * 24}, times),
                                    start, start + timedelta(hours=2), 3600)
    assert list(depth.index) == [-1800, 1800, 5400, 9000]      # rate at t=0 is defined


def test_missing_tail_is_trimmed_and_inner_gaps_are_zero():
    times = [T0 + 3600 * i for i in range(8)]
    vals = [1.0, 1.0, None, 1.0, 1.0, None, None, None]        # horizon after 04:00
    _s, depth, notes = om.build_series(_points({(27.7, 85.3): vals}, times),
                                       START, START + timedelta(hours=7), 3600)
    assert list(depth.index) == [0, 3600, 7200, 10800, 14400]
    assert list(depth.iloc[:, 0]) == [1.0, 1.0, 0.0, 1.0, 1.0]
    assert any("Data ends at 2024-09-27 04:00" in n for n in notes)
    assert any("1 missing value" in n for n in notes)


def test_no_data_at_all_is_an_error():
    times = [T0 + 3600 * i for i in range(4)]
    with pytest.raises(om.OpenMeteoError, match="no precipitation"):
        om.build_series(_points({(27.7, 85.3): [None] * 4}, times),
                        START, START + timedelta(hours=3), 3600)
    later = START + timedelta(days=3)                           # outside the data
    with pytest.raises(om.OpenMeteoError, match="beyond the forecast horizon"):
        om.build_series(_points({(27.7, 85.3): [1.0] * 4}, times),
                        later, later + timedelta(hours=3), 3600)


# ── Download, files and cache ────────────────────────────────────────────────
def test_download_writes_the_gauge_format(basin, monkeypatch):
    fake = FakeOpenMeteo(lambda la, lo, t: 2.0 if la > 27.7 else 1.0)
    monkeypatch.setattr(om, "_http_get_json", fake)
    g_path, ts_path = om.ensure_openmeteo_data(basin)

    gauges = pd.read_csv(g_path)
    ts = pd.read_csv(ts_path)
    assert list(gauges.columns) == ["gauge_id", "name", "easting_m", "northing_m"]
    assert list(ts.columns) == ["time_s"] + list(gauges["gauge_id"])
    assert len(gauges) == 16              # 0.1° box + 10 km each side spans 4 × 4 cells of 0.1°
    assert gauges["name"].str.startswith("Open-Meteo ").all()
    assert gauges["easting_m"].between(300000, 400000).all()    # UTM 45N metres
    assert list(ts["time_s"]) == list(range(0, 6 * 3600 + 1, 3600))
    meta = json.load(open(os.path.join(basin.PRECIP_OPENMETEO_DIR, "openmeteo_meta.json")))
    assert meta["api"] == "historical" and meta["model"] == "best_match"
    assert meta["includes_forecast"] is False and "CC BY 4.0" in meta["attribution"]

    url = urllib.parse.urlparse(fake.urls[0])
    assert url.netloc == "archive-api.open-meteo.com"
    q = urllib.parse.parse_qs(url.query)
    assert q["hourly"] == ["precipitation"] and q["cell_selection"] == ["nearest"]
    assert q["timeformat"] == ["unixtime"] and q["models"] == ["best_match"]
    assert q["start_date"] == ["2024-09-26"] and q["end_date"] == ["2024-09-27"]


def test_cache_is_reused_until_the_request_changes(basin, monkeypatch, capsys):
    fake = FakeOpenMeteo(lambda la, lo, t: 1.0)
    monkeypatch.setattr(om, "_http_get_json", fake)
    om.ensure_openmeteo_data(basin)
    n = len(fake.urls)
    om.ensure_openmeteo_data(basin)
    assert len(fake.urls) == n and "reusing it" in capsys.readouterr().out

    basin.OPENMETEO_MODEL = "era5"
    om.ensure_openmeteo_data(basin)
    assert len(fake.urls) > n and "model: cached='best_match' now='era5'" in capsys.readouterr().out

    n = len(fake.urls)
    basin.PRECIP_OPENMETEO_FORCE_DOWNLOAD = True
    om.ensure_openmeteo_data(basin)
    assert len(fake.urls) > n

    # Hand-made CSVs (no metadata) are used as they are.
    os.remove(os.path.join(basin.PRECIP_OPENMETEO_DIR, "openmeteo_meta.json"))
    basin.PRECIP_OPENMETEO_FORCE_DOWNLOAD = False
    n = len(fake.urls)
    om.ensure_openmeteo_data(basin)
    assert len(fake.urls) == n and "no metadata" in capsys.readouterr().out


def test_forecast_window_and_15_minute_data(basin, monkeypatch):
    fake = FakeOpenMeteo(lambda la, lo, t: 0.25)
    monkeypatch.setattr(om, "_http_get_json", fake)
    basin.EVENT_START_UTC = (datetime.now(timezone.utc) + timedelta(days=1)).strftime(
        "%Y-%m-%d 00:00")
    basin.OPENMETEO_MINUTELY_15 = True
    om.ensure_openmeteo_data(basin)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(fake.urls[0]).query)
    assert urllib.parse.urlparse(fake.urls[0]).netloc == "api.open-meteo.com"
    assert q["minutely_15"] == ["precipitation"] and "hourly" not in q
    ts = pd.read_csv(basin.PRECIP_OPENMETEO_DIR + "timeseries.csv")
    assert list(ts["time_s"][:3]) == [0, 900, 1800]
    meta = json.load(open(basin.PRECIP_OPENMETEO_DIR + "openmeteo_meta.json"))
    assert meta["includes_forecast"] is True and meta["interval"] == "15min"


def test_window_past_the_horizon_is_cut(basin, monkeypatch, capsys):
    basin.TOTAL_SIMULATION_TIME_HOURS = 72.0                    # to 2024-09-30
    fake = FakeOpenMeteo(lambda la, lo, t: 1.0, max_end=date(2024, 9, 28))
    monkeypatch.setattr(om, "_http_get_json", fake)
    om.ensure_openmeteo_data(basin)
    out = capsys.readouterr().out
    assert "data only up to 2024-09-28" in out and "no rain is assumed after it" in out
    ts = pd.read_csv(basin.PRECIP_OPENMETEO_DIR + "timeseries.csv")
    assert ts["time_s"].iloc[-1] == 47 * 3600


def test_refusals_explain_themselves(basin, monkeypatch):
    def refuse(url):
        raise om.OpenMeteoError("Parameter 'start_date' is out of allowed range "
                                "from 2026-07-27 to 2026-11-12")
    monkeypatch.setattr(om, "_http_get_json", refuse)
    basin.OPENMETEO_SOURCE = "forecast"
    with pytest.raises(om.OpenMeteoError, match="OPENMETEO_SOURCE='historical'"):
        om.ensure_openmeteo_data(basin)


def test_single_run_replays_one_model_run(basin, monkeypatch, capsys):
    """A run issued 2 days before the storm: the request names the run, not dates,
    and only the storm window is kept (the lead-time hours are cut)."""
    fake = FakeOpenMeteo(lambda la, lo, t: 1.0)
    monkeypatch.setattr(om, "_http_get_json", fake)
    basin.OPENMETEO_SOURCE, basin.OPENMETEO_MODEL = "single_run", "ecmwf_ifs"
    basin.OPENMETEO_RUN = "2024-09-25 00:00"
    om.ensure_openmeteo_data(basin)
    url = urllib.parse.urlparse(fake.urls[0])
    q = urllib.parse.parse_qs(url.query)
    assert url.netloc == "single-runs-api.open-meteo.com"
    assert q["run"] == ["2024-09-25T00:00"] and q["models"] == ["ecmwf_ifs"]
    assert q["forecast_days"] == ["3"]                       # 25th → end of the 27th
    assert "lead 48 h" in capsys.readouterr().out
    ts = pd.read_csv(basin.PRECIP_OPENMETEO_DIR + "timeseries.csv")
    assert list(ts["time_s"]) == list(range(0, 6 * 3600 + 1, 3600))
    meta = json.load(open(basin.PRECIP_OPENMETEO_DIR + "openmeteo_meta.json"))
    assert meta["api"] == "single_run" and meta["run_utc"] == "2024-09-25 00:00"

    n = len(fake.urls)                                       # another run → new download
    basin.OPENMETEO_RUN = "2024-09-26 00:00"
    om.ensure_openmeteo_data(basin)
    assert len(fake.urls) > n

    basin.OPENMETEO_RUN = None                               # default: the storm start
    assert om.model_run(basin) == START


def test_single_run_checks(basin, monkeypatch):
    monkeypatch.setattr(om, "_http_get_json", FakeOpenMeteo(lambda la, lo, t: 1.0))
    basin.OPENMETEO_SOURCE = "single_run"
    with pytest.raises(ValueError, match="specific OPENMETEO_MODEL"):
        om.ensure_openmeteo_data(basin)                      # best_match has no runs
    assert any("specific OPENMETEO_MODEL" in p for p in S.problems(basin))
    basin.OPENMETEO_MODEL, basin.OPENMETEO_RUN = "ecmwf_ifs", "2024-09-27 06:00"
    with pytest.raises(ValueError, match="after the event start"):
        om.ensure_openmeteo_data(basin)
    assert any("OPENMETEO_RUN must not be after" in p for p in S.problems(basin))

    def unavailable(url):
        raise om.OpenMeteoError("The requested model run is not available. "
                                "Model: ecmwf_ifs, run: 2024-02-10T00:00Z")
    monkeypatch.setattr(om, "_http_get_json", unavailable)
    basin.OPENMETEO_RUN = "2024-09-26 03:00"
    with pytest.raises(om.OpenMeteoError, match="pick another OPENMETEO_RUN"):
        om.ensure_openmeteo_data(basin)


# ── HTTP layer ───────────────────────────────────────────────────────────────
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_reason_retry_and_api_key(monkeypatch):
    calls = []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:                     # a server hiccup, retried
            raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, io.BytesIO(b""))
        if "bad" in req.full_url:
            body = json.dumps({"error": True, "reason": "Cannot initialize x from invalid String value"})
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                         io.BytesIO(body.encode()))
        return _Resp(b'{"ok": 1}')

    monkeypatch.setattr(om.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(om.time, "sleep", lambda s: None)
    assert om._http_get_json("https://x/good") == {"ok": 1} and len(calls) == 2
    with pytest.raises(om.OpenMeteoError, match="invalid String value"):
        om._http_get_json("https://x/bad")
    assert len(calls) == 3                      # a 400 is not retried

    monkeypatch.setenv("OPENMETEO_API_KEY", "k123")
    assert om._base_url("historical") == "https://customer-archive-api.open-meteo.com/v1/archive"


# ── Config, catalogue and summary ────────────────────────────────────────────
def test_config_checks(tiny_basin, monkeypatch):
    monkeypatch.delenv("GEE_PROJECT", raising=False)
    dem, pt = tiny_basin
    cfg = Config(DEM_PATH=dem, OUTPUT_POINT=pt, PRECIP_METHOD=6)      # code 6
    assert cfg.PRECIP_METHOD == "openmeteo_idw"
    assert any("EVENT_START_UTC" in p for p in S.problems(cfg))
    cfg.EVENT_START_UTC = "2024-09-27 00:00"
    assert S.problems(cfg) == []                                       # no Earth Engine needed
    assert S.earth_engine_uses(S.values_of(cfg)) == [("automatic bankfull flow (falls back "
                                                      "to drainage area offline)", False)]
    cfg.OPENMETEO_SOURCE, cfg.OPENMETEO_MINUTELY_15 = "historical", True
    assert any("OPENMETEO_MINUTELY_15" in p for p in S.problems(cfg))


def test_catalogue_shows_open_meteo_settings_only_when_chosen():
    shown = {p.name for p in S.visible_params(S.values_of(Config()))}
    assert not {n for n in shown if "OPENMETEO" in n}
    v = S.values_of(Config(PRECIP_METHOD="openmeteo_idw"))
    shown = {p.name for p in S.visible_params(v)}
    assert {"EVENT_START_UTC", "OPENMETEO_SOURCE", "OPENMETEO_MODEL", "PRECIP_IDW_POWER",
            "PRECIP_OPENMETEO_FORCE_DOWNLOAD"} <= shown
    assert "OPENMETEO_RUN" not in shown                      # only for single_run
    v["OPENMETEO_SOURCE"] = "single_run"
    assert S.is_visible(S.param("OPENMETEO_RUN"), v)
    assert not shown & {"IMERG_UTC_OFFSET_HOURS", "IMERG_DATASET"}


def test_summary_says_open_meteo_and_internet(monkeypatch):
    monkeypatch.delenv("GEE_PROJECT", raising=False)
    cfg = Config(PRECIP_METHOD="openmeteo_thiessen", EVENT_START_UTC="2024-09-27 00:00",
                 CHANNEL_QBF_M3S=300.0, MANNINGS_N_SOURCE="scalar")
    text = "\n".join(render.describe_run(cfg))
    assert "Open-Meteo best_match weather-model rain" in text and "nearest grid point" in text
    assert "Internet" in text and "Runs fully offline" not in text


# ── Through the router ───────────────────────────────────────────────────────
@pytest.mark.parametrize("method", ["openmeteo_thiessen", "openmeteo_idw"])
def test_pipeline_routes_open_meteo_rain(tiny_basin, tmp_path, monkeypatch, method):
    """10 mm in each of the first two hours, then dry: the storm reaches the outlet
    and the water balance closes."""
    def rain(la, lo, t):
        return 10.0 if T0 < t <= T0 + 7200 else 0.0
    monkeypatch.setattr(om, "_http_get_json", FakeOpenMeteo(rain, cell_deg=0.01))
    dem, pt = tiny_basin
    cfg = Config(DEM_PATH=dem, OUTPUT_DIR=str(tmp_path / "out"), OUTPUT_POINT=pt,
                 TARGET_CRS_EPSG="EPSG:32645", PRECIP_METHOD=method,
                 EVENT_START_UTC="2024-09-27 00:00", TOTAL_SIMULATION_TIME_HOURS=4.0,
                 OPENMETEO_POINT_SPACING_M=1000.0, OPENMETEO_BBOX_BUFFER_M=2000.0,
                 RUNOFF_SOURCE="none", ADAPTIVE_TIMESTEP=True)
    cfg.update_output_paths()
    res = run_pipeline(cfg, stages=("process_dem", "routing"),
                       on_log=lambda m: None, on_progress=lambda p: None)
    assert float(res["hydrograph_df"]["Q_m3s"].max()) > 0.0
    mb = pd.read_csv(res["mass_balance_csv"]).tail(1)
    assert abs(float(mb["rel_error"].iloc[0])) < 1e-6
    assert os.path.exists(os.path.join(cfg.PRECIP_OPENMETEO_DIR, "gauges.csv"))


# ── The real API (opt-in) ────────────────────────────────────────────────────
@pytest.mark.skipif(os.environ.get("MRRPY_LIVE_OPENMETEO") != "1",
                    reason="set MRRPY_LIVE_OPENMETEO=1 to call the real Open-Meteo API")
def test_live_open_meteo(basin):
    basin.TOTAL_SIMULATION_TIME_HOURS = 24.0
    g_path, ts_path = om.ensure_openmeteo_data(basin)            # 26–27 Sep 2024, Kathmandu
    gauges, ts = pd.read_csv(g_path), pd.read_csv(ts_path)
    assert len(gauges) >= 2 and len(ts) == 25
    assert float(ts.drop(columns="time_s").sum().mean()) > 50.0   # the record 2024 storm
