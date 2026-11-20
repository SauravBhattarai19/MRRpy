# -*- coding: utf-8 -*-
"""
observed.py
===========
Flow records to set next to a run, and the scores that compare them.

* ``read_flow_csv``  — your own gauge record (any CSV with a time and a flow column)
* ``usgs_flow``      — a USGS stream gauge (needs ``pip install MRRpy[usgs]``)
* ``glofas_flow``    — modelled daily river flow anywhere on Earth since 1984
                       (GloFAS, through Open-Meteo; no account).  A reference,
                       not an observation: its grid is about 5 km, so it only
                       means something on larger rivers.
* ``glofas_two_year_flood`` — the 2-year flood of that record (the median of
                       its yearly peaks), a starting value for CHANNEL_QBF_M3S
* ``skill``          — NSE, KGE, peak and timing errors of a run against a record

Every reader returns the same thing: a pandas DataFrame with ``time_utc``
(timestamps, UTC) and ``Q_m3s``.  ``MRRpy.plot_hydrograph(out, observed=df)``
draws it over the model's hydrograph.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

FT3_TO_M3 = 0.028316846592
GLOFAS_URL = "https://flood-api.open-meteo.com/v1/flood"
GLOFAS_ATTRIBUTION = ("River discharge: GloFAS (Copernicus Emergency Management Service) "
                      "via Open-Meteo.com (CC BY 4.0)")

_TIME_NAMES = ("time_utc", "time", "datetime", "date", "timestamp", "date_time")
_FLOW_NAMES = ("q_m3s", "q", "flow", "discharge", "flow_m3s", "discharge_m3s", "q_cms",
               "value", "river_discharge")


def _frame(times, flows):
    import pandas as pd
    stamps = pd.DatetimeIndex(pd.to_datetime(list(times), utc=True)).tz_localize(None)
    df = pd.DataFrame({"time_utc": stamps,
                       "Q_m3s": pd.to_numeric(pd.Series(list(flows)), errors="coerce").values})
    return df.dropna(subset=["Q_m3s"]).sort_values("time_utc").reset_index(drop=True)


def read_flow_csv(path, time_column=None, flow_column=None, unit="m3/s", utc_offset_hours=0.0):
    """
    Read a flow record from a CSV file → DataFrame(time_utc, Q_m3s).

    The time and flow columns are found by name (time / datetime / date and
    Q_m3s / flow / discharge / Q …) unless you name them.  *unit*: "m3/s"
    (default) or "ft3/s".  *utc_offset_hours*: the file's clock minus UTC
    (5.75 for Nepal time), used when its times carry no time zone.
    """
    import pandas as pd
    df = pd.read_csv(path)
    lower = {str(c).strip().lower(): c for c in df.columns}
    tcol = time_column or next((lower[n] for n in _TIME_NAMES if n in lower), None)
    qcol = flow_column or next((lower[n] for n in _FLOW_NAMES if n in lower), None)
    if tcol is None or qcol is None or tcol not in df.columns or qcol not in df.columns:
        raise ValueError(
            f"{path}: could not tell which columns hold the time and the flow "
            f"(found: {', '.join(map(str, df.columns))}). Name them with "
            "time_column= and flow_column=.")
    stamps = pd.to_datetime(df[tcol])
    if stamps.dt.tz is None:
        stamps = (stamps - pd.Timedelta(hours=float(utc_offset_hours))).dt.tz_localize("UTC")
    factor = {"m3/s": 1.0, "cms": 1.0, "ft3/s": FT3_TO_M3, "cfs": FT3_TO_M3}.get(
        str(unit).lower())
    if factor is None:
        raise ValueError(f"unit must be 'm3/s' or 'ft3/s' (got {unit!r}).")
    return _frame(stamps, pd.to_numeric(df[qcol], errors="coerce") * factor)


def usgs_flow(site, start, end):
    """
    Flow at a USGS stream gauge → DataFrame(time_utc, Q_m3s).

    *site*: the gauge number, e.g. "04286000" (Winooski River at Montpelier).
    *start*, *end*: dates or date-times, UTC.  Uses the USGS Water Data API
    through the ``dataretrieval`` package (``pip install MRRpy[usgs]``); the
    values are instantaneous readings, usually every 15 minutes.
    """
    import pandas as pd
    try:
        from dataretrieval import waterdata
    except ImportError as exc:
        raise ImportError(
            "usgs_flow needs the 'dataretrieval' package with the USGS Water Data API "
            "(version 1.3 or newer, which needs Python 3.10 or newer): "
            "pip install 'MRRpy[usgs]'") from exc
    site = str(site).strip()
    loc = site if site.upper().startswith("USGS-") else f"USGS-{site}"
    t0, t1 = (pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ") for t in (start, end))
    df, _meta = waterdata.get_continuous(monitoring_location_id=loc, parameter_code="00060",
                                         time=f"{t0}/{t1}")
    if df is None or not len(df):
        raise ValueError(f"USGS has no flow (parameter 00060) for {loc} between "
                         f"{t0} and {t1}. Check the gauge number and the dates.")
    units = set(str(u).lower() for u in df.get("unit_of_measure", ["ft^3/s"]))
    factor = 1.0 if units <= {"m^3/s", "m3/s"} else FT3_TO_M3
    return _frame(df["time"], pd.to_numeric(df["value"], errors="coerce") * factor)


def glofas_flow(lat, lon, start, end, ensemble=False):
    """
    Modelled daily river flow at (*lat*, *lon*) → DataFrame(time_utc, Q_m3s).

    From the Global Flood Awareness System (GloFAS v4) through Open-Meteo's
    Flood API: no account, 1984 to about seven months ahead.  With
    *ensemble* the frame also has ``Q_min_m3s`` and ``Q_max_m3s`` of the
    forecast ensemble.  ``df.attrs["cell"]`` is the (lat, lon) of the model
    cell that was served.

    This is another model's result, on a grid of about 5 km: use it as a
    reference line on larger rivers, not as a measurement.  If the cell served
    is not on your river, move the point by 0.05–0.1°.
    """
    import pandas as pd
    daily = "river_discharge" + (",river_discharge_min,river_discharge_max" if ensemble else "")
    params = {"latitude": f"{float(lat):.4f}", "longitude": f"{float(lon):.4f}",
              "daily": daily,
              "start_date": pd.Timestamp(start).strftime("%Y-%m-%d"),
              "end_date": pd.Timestamp(end).strftime("%Y-%m-%d")}
    url = GLOFAS_URL + "?" + urllib.parse.urlencode(params, safe=",")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MRRpy"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            reason = json.loads(body).get("reason") or body
        except ValueError:
            reason = body or exc.reason
        raise RuntimeError(f"The flood service refused the request: {reason}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not reach the flood service ({exc}).") from None
    d = data.get("daily") or {}
    df = _frame(d.get("time") or [], d.get("river_discharge") or [])
    if ensemble:
        full = pd.DataFrame({"time_utc": pd.to_datetime(d.get("time") or []),
                             "Q_min_m3s": d.get("river_discharge_min"),
                             "Q_max_m3s": d.get("river_discharge_max")})
        df = df.merge(full, on="time_utc", how="left")
    if not len(df):
        raise ValueError(f"GloFAS has no river flow at latitude {lat}, longitude {lon} for "
                         "these dates (the sea, or outside 1984 to seven months ahead).")
    df.attrs["cell"] = (data.get("latitude"), data.get("longitude"))
    df.attrs["attribution"] = GLOFAS_ATTRIBUTION
    return df


def glofas_two_year_flood(lat, lon, first_year=1984, last_year=None):
    """
    The 2-year flood at (*lat*, *lon*) from the GloFAS daily record: the median
    of its yearly peaks [m³/s].  Returns a dict: ``q2_m3s``, ``years``,
    ``yearly_peaks`` (DataFrame), ``cell``.

    A starting value for CHANNEL_QBF_M3S on larger rivers where no gauge
    exists.  Daily means sit below the momentary peak, more so on small, fast
    rivers; it has not been checked against MRRpy's own estimate basin by
    basin, so compare the two before relying on it.
    """
    import pandas as pd
    last_year = int(last_year or pd.Timestamp.utcnow().year - 1)
    df = glofas_flow(lat, lon, f"{int(first_year)}-01-01", f"{last_year}-12-31")
    peaks = df.groupby(df["time_utc"].dt.year)["Q_m3s"].max()
    return {"q2_m3s": float(peaks.median()), "years": int(len(peaks)),
            "yearly_peaks": peaks.rename("peak_m3s").rename_axis("year").reset_index(),
            "cell": df.attrs.get("cell")}


def _simulated(sim, start_utc=None):
    """DataFrame(time_utc, Q_m3s) of a run: a RunResult/dict, DataFrame, folder or CSV."""
    import os
    import pandas as pd
    if isinstance(sim, dict):
        df = sim.get("hydrograph_df")
        if df is None:
            df = pd.read_csv(sim["hydrograph_csv"])
    elif isinstance(sim, pd.DataFrame):
        df = sim
    else:
        path = str(sim)
        df = pd.read_csv(os.path.join(path, "hydrograph.csv") if os.path.isdir(path) else path)
    if "time_utc" in df.columns:
        times = pd.to_datetime(df["time_utc"])
    elif start_utc is not None:
        times = pd.Timestamp(start_utc) + pd.to_timedelta(df["time_s"], unit="s")
    else:
        raise ValueError(
            "The run has no clock times to match the record with: set EVENT_START_UTC "
            "before running (hydrograph.csv then has a time_utc column), or pass "
            "start_utc= here.")
    return pd.DataFrame({"time_utc": times.values, "Q_m3s": df["Q_m3s"].values})


def skill(sim, obs, start_utc=None):
    """
    How well a run matches a flow record → dict of scores.

    *sim*: the run (what ``run_pipeline`` returned, a results folder, a
    hydrograph.csv or its DataFrame).  *obs*: DataFrame(time_utc, Q_m3s) from
    one of the readers above.  The model's hydrograph is read at the record's
    times; only the hours both cover are compared.

    nse            Nash–Sutcliffe efficiency (1 perfect; 0 no better than the mean)
    kge            Kling–Gupta efficiency (1 perfect)
    bias_percent   total modelled volume against the record, in percent
    peak_obs_m3s, peak_sim_m3s, peak_error_percent
    peak_timing_hours   modelled peak minus recorded peak (positive: late)
    n              number of compared values
    """
    import numpy as np
    s, o = _simulated(sim, start_utc), obs
    t0 = max(s["time_utc"].min(), o["time_utc"].min())
    t1 = min(s["time_utc"].max(), o["time_utc"].max())
    o = o[(o["time_utc"] >= t0) & (o["time_utc"] <= t1)]
    if len(o) < 3:
        raise ValueError(
            f"The run ({s['time_utc'].min()} to {s['time_utc'].max()}) and the record "
            f"({obs['time_utc'].min()} to {obs['time_utc'].max()}) share fewer than 3 values.")
    x = s["time_utc"].values.astype("datetime64[s]").astype("int64").astype(float)
    xo = o["time_utc"].values.astype("datetime64[s]").astype("int64").astype(float)
    q_sim = np.interp(xo, x, s["Q_m3s"].values.astype(float))
    q_obs = o["Q_m3s"].values.astype(float)
    var = float(((q_obs - q_obs.mean()) ** 2).sum())
    nse = 1.0 - float(((q_sim - q_obs) ** 2).sum()) / var if var > 0 else float("nan")
    if q_obs.std() > 0 and q_sim.std() > 0 and q_obs.mean() != 0:
        r = float(np.corrcoef(q_sim, q_obs)[0, 1])
        kge = 1.0 - float(np.sqrt((r - 1) ** 2 + (q_sim.std() / q_obs.std() - 1) ** 2
                                  + (q_sim.mean() / q_obs.mean() - 1) ** 2))
    else:
        kge = float("nan")
    i_s, i_o = int(q_sim.argmax()), int(q_obs.argmax())
    return {
        "nse": nse, "kge": kge,
        "bias_percent": (float(100.0 * (q_sim.sum() - q_obs.sum()) / q_obs.sum())
                         if q_obs.sum() else float("nan")),
        "peak_obs_m3s": float(q_obs[i_o]), "peak_sim_m3s": float(q_sim[i_s]),
        "peak_error_percent": (float(100.0 * (q_sim[i_s] - q_obs[i_o]) / q_obs[i_o])
                               if q_obs[i_o] else float("nan")),
        "peak_timing_hours": float(xo[i_s] - xo[i_o]) / 3600.0,
        "n": int(len(q_obs)),
    }
