"""
openmeteo.py
============
Open-Meteo weather-model precipitation for the router — forecasts and past weather.

Open-Meteo (https://open-meteo.com) serves precipitation from national weather
models and reanalyses through a free HTTP API that needs no account.  Like the
IMERG source, every model grid cell over the watershed becomes a *pseudo-gauge*
at its centre, written in the standard OPM gauge format so the existing
Thiessen/IDW + per-polygon VSA machinery runs unchanged:

    <PRECIP_OPENMETEO_DIR>/gauges.csv           gauge_id,name,easting_m,northing_m
    <PRECIP_OPENMETEO_DIR>/timeseries.csv       time_s, <gauge cols...>   (mm depth / interval)
    <PRECIP_OPENMETEO_DIR>/openmeteo_meta.json  provenance for the cache check

Which API
---------
OPENMETEO_SOURCE picks one of four Open-Meteo APIs (all return the same JSON):

    forecast             api.open-meteo.com/v1/forecast — the past ~3 months and
                         up to 16 days ahead (the only one with future rain)
    historical           archive-api.open-meteo.com/v1/archive — reanalysis
                         (ERA5 …) and archived analyses from 1940 to a few days ago
    historical_forecast  historical-forecast-api.open-meteo.com/v1/forecast —
                         archived high-resolution model runs, from about 2021
                         (the first hours of each run, joined end to end)
    single_run           single-runs-api.open-meteo.com/v1/forecast — one model
                         run as it was issued at OPENMETEO_RUN (default: the
                         event start), with its full lead time: a real
                         hindcast with no look-ahead.  Needs a specific model.
    auto (default)       forecast when the window starts within the forecast
                         API's past range, otherwise historical (or
                         historical_forecast when 15-minute data is asked for)

The window is EVENT_START_UTC … + TOTAL_SIMULATION_TIME_HOURS, in UTC.

Sampling the model grid
-----------------------
Open-Meteo answers *points*: each point is served from the model cell that
contains it, and the response carries that cell's centre coordinates.  A regular
lattice of query points (OPENMETEO_POINT_SPACING_M apart) is laid over the
buffered watershed box, all points are sent in a few multi-location requests,
and points that land in the same model cell are merged — so the pseudo-gauges
sit on the model's own grid, whatever its resolution or projection.

Time convention
---------------
Open-Meteo's ``precipitation`` at time T is the sum over the *preceding* hour (or
15 minutes), which is exactly the gauge format's "mm in the interval ending at
time_s" — no shifting is needed.  The row at (or just before) the event start is
kept, so the rain rate at t = 0 is defined.

Data by Open-Meteo.com, licensed CC BY 4.0 — credit it when you publish results.
Set the OPENMETEO_API_KEY environment variable to use a commercial subscription.
"""

import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd


API_URLS = {
    "forecast":            "https://api.open-meteo.com/v1/forecast",
    "historical":          "https://archive-api.open-meteo.com/v1/archive",
    "historical_forecast": "https://historical-forecast-api.open-meteo.com/v1/forecast",
    "single_run":          "https://single-runs-api.open-meteo.com/v1/forecast",
}
# The forecast API also serves the recent past (its `past_days` reaches 92).
# One day of margin keeps 'auto' clear of the boundary.
FORECAST_PAST_DAYS = 91
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"

_M_PER_DEG = 111320.0        # metres per degree of latitude
_MAX_POINTS = 400            # lattice size cap; each point counts as one API call
_POINTS_PER_REQUEST = 100    # locations per HTTP request (keeps URLs ~1–2 kB)
_RETRIES = 3
_TIMEOUT_S = 60


# ── Config helpers ────────────────────────────────────────────────────────────

def _resolve_paths(cfg):
    """Return (openmeteo_dir, gauges_path, timeseries_path, meta_path)."""
    om_dir = getattr(cfg, 'PRECIP_OPENMETEO_DIR', None) \
        or os.path.join(getattr(cfg, 'OUTPUT_DIR', 'output/'), 'openmeteo/')
    return (
        om_dir,
        os.path.join(om_dir, 'gauges.csv'),
        os.path.join(om_dir, 'timeseries.csv'),
        os.path.join(om_dir, 'openmeteo_meta.json'),
    )


def event_window(cfg):
    """(start, end) of the rain window as naive UTC datetimes.

    start is EVENT_START_UTC; end is start + TOTAL_SIMULATION_TIME_HOURS.
    """
    evt = getattr(cfg, 'EVENT_START_UTC', None)
    if not evt:
        raise ValueError(
            "Open-Meteo precipitation needs EVENT_START_UTC ('YYYY-MM-DD HH:MM', "
            "UTC): the download window starts there."
        )
    start = datetime.fromisoformat(str(evt).strip())
    if start.tzinfo is not None:
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
    hours = float(getattr(cfg, 'TOTAL_SIMULATION_TIME_HOURS', 0) or 0)
    if hours <= 0:
        raise ValueError("Open-Meteo precipitation needs TOTAL_SIMULATION_TIME_HOURS > 0.")
    return start, start + timedelta(hours=hours)


def model_run(cfg):
    """Issue time of the model run for OPENMETEO_SOURCE='single_run' (naive UTC).

    OPENMETEO_RUN if set, else the event start.  It may not be later than the
    event start: a run cannot forecast rain that falls before it was issued.
    """
    start, _end = event_window(cfg)
    run = getattr(cfg, 'OPENMETEO_RUN', None)
    run = datetime.fromisoformat(str(run).strip()) if run else start
    if run.tzinfo is not None:
        run = run.astimezone(timezone.utc).replace(tzinfo=None)
    if run > start:
        raise ValueError(f"OPENMETEO_RUN ({run:%Y-%m-%d %H:%M}) is after the event start "
                         f"({start:%Y-%m-%d %H:%M}); a model run only forecasts rain after "
                         "it was issued.")
    return run


def resolve_source(source, start_utc, minutely_15=False, today=None):
    """The Open-Meteo API to call: a key of API_URLS.

    An explicit *source* is returned unchanged.  'auto' uses the forecast API
    when the window starts within its past range (so recent storms and future
    forecasts both work), and the historical archive for older storms — or the
    historical-forecast archive when 15-minute data is wanted, since the
    reanalysis archive is hourly only.
    """
    source = str(source or 'auto').lower()
    if source != 'auto':
        if source not in API_URLS:
            raise ValueError(f"OPENMETEO_SOURCE {source!r} is not one of "
                             f"'auto', {', '.join(repr(k) for k in API_URLS)}.")
        return source
    today = today or datetime.now(timezone.utc).date()
    if start_utc.date() >= today - timedelta(days=FORECAST_PAST_DAYS):
        return 'forecast'
    return 'historical_forecast' if minutely_15 else 'historical'


def _watershed_bounds_4326(geojson_path):
    """Return (minx, miny, maxx, maxy) of the watershed in EPSG:4326."""
    import geopandas as gpd
    gdf = gpd.read_file(geojson_path).to_crs("EPSG:4326")
    minx, miny, maxx, maxy = gdf.total_bounds
    return float(minx), float(miny), float(maxx), float(maxy)


def query_points(bounds, spacing_m, buffer_m, max_points=_MAX_POINTS):
    """
    A regular lattice of (lat, lon) query points over the buffered *bounds*.

    The lattice is centred on the box, so a basin smaller than one spacing still
    gets its centre sampled.  If more than *max_points* would be needed the
    spacing is widened until it fits.

    Returns (lats, lons, spacing_m) — 1-D arrays of equal length, and the
    spacing actually used.
    """
    minx, miny, maxx, maxy = bounds
    lat_mid = 0.5 * (miny + maxy)
    m_per_deg_lon = _M_PER_DEG * max(math.cos(math.radians(lat_mid)), 0.01)
    minx -= buffer_m / m_per_deg_lon
    maxx += buffer_m / m_per_deg_lon
    miny -= buffer_m / _M_PER_DEG
    maxy += buffer_m / _M_PER_DEG
    width_m = (maxx - minx) * m_per_deg_lon
    height_m = (maxy - miny) * _M_PER_DEG

    spacing_m = float(spacing_m)
    while True:
        nx = int(math.floor(width_m / spacing_m)) + 1
        ny = int(math.floor(height_m / spacing_m)) + 1
        if nx * ny <= max_points:
            break
        spacing_m *= math.sqrt(nx * ny / max_points) * 1.01

    def axis(lo, hi, n, step_deg):
        mid = 0.5 * (lo + hi)
        return mid + (np.arange(n) - 0.5 * (n - 1)) * step_deg

    lons = axis(minx, maxx, nx, spacing_m / m_per_deg_lon)
    lats = axis(miny, maxy, ny, spacing_m / _M_PER_DEG)
    lat_grid, lon_grid = np.meshgrid(lats, lons, indexing='ij')
    return lat_grid.ravel(), lon_grid.ravel(), spacing_m


# ── HTTP ──────────────────────────────────────────────────────────────────────

class OpenMeteoError(RuntimeError):
    """Open-Meteo refused a request (bad date range, unknown model, …)."""


def _http_get_json(url):
    """GET *url* and decode its JSON, retrying on rate limits and server errors."""
    last = None
    for attempt in range(_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MRRpy"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                reason = json.loads(body).get("reason") or body
            except ValueError:
                reason = body or exc.reason
            if exc.code == 429 or exc.code >= 500:
                last = OpenMeteoError(f"HTTP {exc.code}: {reason}")
            else:
                raise OpenMeteoError(str(reason)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < _RETRIES:
            wait = 2 ** attempt * (20 if isinstance(last, OpenMeteoError)
                                   and "429" in str(last) else 2)
            print(f"  [Open-Meteo] request failed ({last}); retrying in {wait} s …")
            time.sleep(wait)
    raise OpenMeteoError(f"Could not reach Open-Meteo: {last}")


def _base_url(api):
    url = API_URLS[api]
    if os.environ.get("OPENMETEO_API_KEY"):
        url = url.replace("https://", "https://customer-", 1)
    return url


def fetch_points(api, lats, lons, start_date, end_date, model="best_match",
                 minutely_15=False, run=None):
    """
    Precipitation at each (lat, lon) from one Open-Meteo API, in chunks.

    For the single-runs API pass *run* (a datetime): it takes no dates, only
    the run and ``forecast_days`` counted from it, so *end_date* sets how
    many days are asked for and *start_date* is ignored.

    Returns a list (one per point, in order) of dicts with the served cell's
    ``latitude``/``longitude`` and ``time`` (unix seconds) / ``precipitation``
    (mm per interval, may contain None) lists.
    """
    block = "minutely_15" if minutely_15 else "hourly"
    out = []
    for i in range(0, len(lats), _POINTS_PER_REQUEST):
        la, lo = lats[i:i + _POINTS_PER_REQUEST], lons[i:i + _POINTS_PER_REQUEST]
        params = {
            "latitude": ",".join(f"{v:.4f}" for v in la),
            "longitude": ",".join(f"{v:.4f}" for v in lo),
            block: "precipitation",
            "models": model,
            "timezone": "GMT",
            "timeformat": "unixtime",
            "cell_selection": "nearest",
        }
        if run is None:
            params.update(start_date=start_date, end_date=end_date)
        else:
            days = (datetime.fromisoformat(end_date).date() - run.date()).days + 1
            params.update(run=run.strftime('%Y-%m-%dT%H:%M'), forecast_days=days)
        if os.environ.get("OPENMETEO_API_KEY"):
            params["apikey"] = os.environ["OPENMETEO_API_KEY"]
        url = _base_url(api) + "?" + urllib.parse.urlencode(params, safe=",")
        data = _http_get_json(url)
        rows = data if isinstance(data, list) else [data]
        if len(rows) != len(la):
            raise OpenMeteoError(
                f"Open-Meteo returned {len(rows)} locations for {len(la)} requested.")
        for r in rows:
            series = r.get(block) or {}
            out.append({
                "latitude": float(r["latitude"]),
                "longitude": float(r["longitude"]),
                "time": list(series.get("time") or []),
                "precipitation": list(series.get("precipitation") or []),
            })
    return out


# ── Core download ─────────────────────────────────────────────────────────────

def _request(cfg):
    """Everything that defines a download, as plain JSON-able values."""
    start, end = event_window(cfg)
    minutely_15 = bool(getattr(cfg, 'OPENMETEO_MINUTELY_15', False))
    source = str(getattr(cfg, 'OPENMETEO_SOURCE', 'auto'))
    run = model_run(cfg).strftime('%Y-%m-%d %H:%M') if source == 'single_run' else None
    return {
        'source':      source,
        'run_utc':     run,
        'model':       str(getattr(cfg, 'OPENMETEO_MODEL', 'best_match')),
        'interval':    '15min' if minutely_15 else 'hourly',
        'start_utc':   start.strftime('%Y-%m-%d %H:%M'),
        'end_utc':     end.strftime('%Y-%m-%d %H:%M'),
        'spacing_m':   float(getattr(cfg, 'OPENMETEO_POINT_SPACING_M', 5000.0)),
        'buffer_m':    float(getattr(cfg, 'OPENMETEO_BBOX_BUFFER_M', 10000.0)),
    }


def build_series(points, start_utc, end_utc, step_s):
    """
    Merge per-point responses into pseudo-gauges and a gap-free depth table.

    Points served from the same model cell collapse into one station; cells
    with no data at all (e.g. a land-only model over the sea) are dropped.
    Rows outside the window — except the one at or just before its start —
    are cut, and rows at either end where no station has data (past the
    forecast horizon, or not yet in the archive) are trimmed.

    Returns (stations, depth_mm, notes): a DataFrame of gauge_id/name/lat/lon,
    a DataFrame indexed by time_s with one column per gauge_id, and a list of
    warning strings.
    """
    notes = []
    cells = {}
    for p in points:
        key = (round(p["latitude"], 5), round(p["longitude"], 5))
        if key in cells:
            continue
        vals = pd.to_numeric(pd.Series(p["precipitation"], dtype=object),
                             errors='coerce')
        if not len(p["time"]) or vals.isna().all():
            cells[key] = None
            continue
        cells[key] = pd.Series(vals.values, index=np.asarray(p["time"], dtype=np.int64))
    n_empty = sum(s is None for s in cells.values())
    cells = {k: s for k, s in cells.items() if s is not None}
    if n_empty:
        notes.append(f"{n_empty} model cell(s) returned no precipitation and were skipped.")
    if not cells:
        raise OpenMeteoError(
            "Open-Meteo returned no precipitation for this area and window — the "
            "model may not cover this place or these dates "
            "(OPENMETEO_MODEL='best_match' covers the whole globe).")

    keys = sorted(cells, key=lambda k: (-k[0], k[1]))      # north→south, west→east
    stations = pd.DataFrame({
        'gauge_id': [f"OM{i + 1:03d}" for i in range(len(keys))],
        'lat': [k[0] for k in keys],
        'lon': [k[1] for k in keys],
    })
    stations['name'] = [f"Open-Meteo {la:.4f},{lo:.4f}"
                        for la, lo in zip(stations['lat'], stations['lon'])]
    table = pd.concat([cells[k] for k in keys], axis=1, keys=list(stations['gauge_id']))
    table = table[~table.index.duplicated()].sort_index()

    t0 = int(start_utc.replace(tzinfo=timezone.utc).timestamp())
    t1 = int(end_utc.replace(tzinfo=timezone.utc).timestamp())
    table = table[(table.index > t0 - step_s) & (table.index < t1 + step_s)]

    has = table.notna().any(axis=1).values
    if not has.any():
        raise OpenMeteoError(
            "Open-Meteo has no precipitation for "
            f"{start_utc:%Y-%m-%d %H:%M} → {end_utc:%Y-%m-%d %H:%M} UTC here "
            "(beyond the forecast horizon, or not yet in the archive).")
    first, last = int(np.argmax(has)), len(has) - 1 - int(np.argmax(has[::-1]))
    if last < len(has) - 1:
        end_at = datetime.fromtimestamp(int(table.index[last]), timezone.utc)
        notes.append(f"Data ends at {end_at:%Y-%m-%d %H:%M} UTC (forecast horizon or "
                     "archive delay) — no rain is assumed after it.")
    if first > 0:
        start_at = datetime.fromtimestamp(int(table.index[first]), timezone.utc)
        notes.append(f"Data starts at {start_at:%Y-%m-%d %H:%M} UTC — no rain is "
                     "assumed before it.")
    table = table.iloc[first:last + 1]

    full = np.arange(int(table.index[0]), int(table.index[-1]) + step_s, step_s)
    table = table.reindex(full)
    n_gap = int(table.isna().values.sum())
    if n_gap:
        notes.append(f"{n_gap} missing value(s) inside the window were set to 0 mm.")
    depth = table.fillna(0.0).clip(lower=0.0)
    depth.index = pd.Index(depth.index.values - t0, name='time_s')
    return stations, depth, notes


def download_openmeteo(cfg):
    """
    Download Open-Meteo precipitation over the watershed and write
    gauges.csv / timeseries.csv / openmeteo_meta.json into PRECIP_OPENMETEO_DIR.

    Returns (gauges_path, timeseries_path) on success; raises on failure.
    """
    from ..io_utils import routing_grid_crs

    om_dir, gauges_path, ts_path, meta_path = _resolve_paths(cfg)
    req = _request(cfg)
    start, end = event_window(cfg)
    minutely_15 = req['interval'] == '15min'
    step_s = 900 if minutely_15 else 3600
    api = resolve_source(req['source'], start, minutely_15)
    if minutely_15 and api == 'historical':
        raise ValueError("OPENMETEO_MINUTELY_15 is not available from the historical "
                         "archive (hourly only); use OPENMETEO_SOURCE='historical_forecast'.")
    run = model_run(cfg) if api == 'single_run' else None
    if run is not None and req['model'] == 'best_match':
        raise ValueError("OPENMETEO_SOURCE='single_run' needs a specific OPENMETEO_MODEL "
                         "(e.g. ecmwf_ifs), not 'best_match'.")

    target_crs = routing_grid_crs(cfg)
    geojson = getattr(cfg, 'WATERSHED_GEOJSON', 'output/watershed.geojson')
    bounds = _watershed_bounds_4326(geojson)
    lats, lons, spacing = query_points(bounds, req['spacing_m'], req['buffer_m'])

    # Whole UTC days that cover the window plus the rows at/before its start
    # and at/after its end.
    first_day = (start - timedelta(seconds=step_s)).date()
    last_day = (end + timedelta(seconds=step_s - 1)).date()
    print("=" * 60)
    print("OPEN-METEO DOWNLOAD")
    print("=" * 60)
    print(f"  API          : {api}  ({API_URLS[api]})"
          + ("  [auto]" if req['source'] == 'auto' else ""))
    print(f"  Model        : {req['model']}   interval={req['interval']}"
          + (f"   run={run:%Y-%m-%d %H:%M} UTC (lead {(start - run).total_seconds() / 3600:g} h)"
             if run is not None else ""))
    print(f"  Window UTC   : {req['start_utc']} → {req['end_utc']}")
    print(f"  BBox 4326    : [{bounds[0]:.3f}, {bounds[1]:.3f}, {bounds[2]:.3f}, "
          f"{bounds[3]:.3f}]  + {req['buffer_m']:.0f} m")
    note = "" if spacing == req['spacing_m'] else \
        f"  (widened from {req['spacing_m']:.0f} m to stay under {_MAX_POINTS} points)"
    print(f"  Query points : {len(lats)} at {spacing:.0f} m{note}")

    def fetch(last):
        return fetch_points(api, lats, lons, first_day.isoformat(), last.isoformat(),
                            req['model'], minutely_15, run)

    try:
        try:
            points = fetch(last_day)
        except OpenMeteoError as exc:
            # A window that runs past the forecast horizon (or the archive's
            # latest day) is cut there rather than refused.
            m = re.search(r"'end_date' is out of allowed range from \S+ to "
                          r"(\d{4}-\d{2}-\d{2})", str(exc))
            if not m or datetime.strptime(m.group(1), '%Y-%m-%d').date() < first_day:
                raise
            print(f"  [WARN] Open-Meteo has data only up to {m.group(1)} (forecast "
                  "horizon or archive end) — no rain is assumed after it.")
            points = fetch(datetime.strptime(m.group(1), '%Y-%m-%d').date())
    except OpenMeteoError as exc:
        hint = ""
        if "model run is not available" in str(exc):
            hint = (" Each model is issued at set hours (ECMWF IFS at 00/06/12/18 UTC) "
                    "and its run archive starts at a different date (ECMWF IFS in 2024, "
                    "most others later): pick another OPENMETEO_RUN or OPENMETEO_MODEL.")
        elif "out of allowed range" in str(exc) and api == 'forecast':
            future = start > datetime.now(timezone.utc).replace(tzinfo=None)
            hint = (" Forecasts reach about 16 days ahead." if future
                    else " The forecast API covers only about the last 3 months; use "
                         "OPENMETEO_SOURCE='historical' for older storms.")
        raise OpenMeteoError(f"Open-Meteo ({api}) refused the request: {exc}.{hint}") \
            from None

    stations, depth_mm, notes = build_series(points, start, end, step_s)

    from pyproj import Transformer
    tf = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    east, north = tf.transform(stations['lon'].values, stations['lat'].values)
    stations['easting_m'] = east
    stations['northing_m'] = north

    os.makedirs(om_dir, exist_ok=True)
    stations[['gauge_id', 'name', 'easting_m', 'northing_m']].to_csv(
        gauges_path, index=False)
    depth_mm.reset_index().to_csv(ts_path, index=False)

    now = datetime.now(timezone.utc)
    data_end = start + timedelta(seconds=int(depth_mm.index[-1]))
    meta = dict(req)
    meta.update({
        'api':               api,
        'url':               API_URLS[api],
        'query_spacing_m':   spacing,
        'bbox_4326':         [round(b, 5) for b in bounds],
        'n_query_points':    int(len(lats)),
        'n_stations':        int(len(stations)),
        'n_timesteps':       int(len(depth_mm)),
        'data_end_utc':      data_end.strftime('%Y-%m-%d %H:%M'),
        'includes_forecast': data_end > now.replace(tzinfo=None),
        'target_crs':        target_crs,
        'downloaded_at':     now.isoformat(),
        'attribution':       ATTRIBUTION,
    })
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)

    for n in notes:
        print(f"  [WARN] {n}")
    mean_total = float(depth_mm.sum(axis=0).mean())
    print(f"  Stations     : {len(stations)} model cells (from {len(lats)} points)")
    print(f"  Timesteps    : {len(depth_mm)} × {step_s}s")
    print(f"  Mean total   : {mean_total:.1f} mm per station over the window")
    if meta['includes_forecast']:
        print(f"  Forecast     : includes forecast values (issued {now:%Y-%m-%d %H:%M} UTC)")
    print(f"  Written      : {gauges_path}")
    print(f"               : {ts_path}")
    print(f"  {ATTRIBUTION}")
    print("=" * 60)
    return gauges_path, ts_path


# ── Cache-aware entry point used by PrecipEngine ──────────────────────────────

def ensure_openmeteo_data(cfg):
    """
    Return (gauges_path, timeseries_path) for the Open-Meteo folder.

    Cached CSVs are reused when their metadata matches the current request
    (window, source, model, interval, sampling).  A mismatch downloads again —
    unlike IMERG, a fetch is free and quick.  CSVs without metadata (placed
    there by hand) are reused as-is.  PRECIP_OPENMETEO_FORCE_DOWNLOAD=True
    always refetches, e.g. to get the latest forecast.
    """
    om_dir, gauges_path, ts_path, meta_path = _resolve_paths(cfg)
    force = bool(getattr(cfg, 'PRECIP_OPENMETEO_FORCE_DOWNLOAD', False))
    have_data = (os.path.isfile(gauges_path) and os.path.getsize(gauges_path) > 0
                 and os.path.isfile(ts_path) and os.path.getsize(ts_path) > 0)

    if have_data and not force:
        meta = None
        if os.path.isfile(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                meta = None
        if meta is None:
            print(f"  [Open-Meteo] Precip data found in '{om_dir}' (no metadata) — "
                  "using it as-is.")
            return gauges_path, ts_path
        req = _request(cfg)
        changed = [f"{k}: cached={meta.get(k)!r} now={v!r}" for k, v in req.items()
                   if meta.get(k) != v]
        if not changed:
            print(f"  [Open-Meteo] Precip data already downloaded in '{om_dir}' — "
                  "reusing it.")
            if meta.get('includes_forecast'):
                print(f"               It holds a forecast issued "
                      f"{meta.get('downloaded_at', '?')[:16].replace('T', ' ')} UTC; "
                      "set PRECIP_OPENMETEO_FORCE_DOWNLOAD=True for the latest one.")
            return gauges_path, ts_path
        print("  [Open-Meteo] Cached data was fetched for a different request — "
              "downloading again:")
        for c in changed:
            print(f"               {c}")
    elif force and have_data:
        print(f"  [Open-Meteo] PRECIP_OPENMETEO_FORCE_DOWNLOAD=True — refetching into "
              f"'{om_dir}'.")
    return download_openmeteo(cfg)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # python -m MRRpy.core.precip.openmeteo <config.yaml|json> [--force]
    import sys
    from ...config import Config

    args = [a for a in sys.argv[1:] if a != '--force']
    if not args:
        sys.exit("usage: python -m MRRpy.core.precip.openmeteo <config.yaml|json> [--force]")
    cfg = Config.from_file(args[0])
    if '--force' in sys.argv:
        cfg.PRECIP_OPENMETEO_FORCE_DOWNLOAD = True
    ensure_openmeteo_data(cfg)
