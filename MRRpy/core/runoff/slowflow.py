# -*- coding: utf-8 -*-
"""
slowflow.py — baseflow from the water that soaks in (``BASEFLOW_METHOD='store'``).

Rain that does not run off used to leave the model.  Here it goes through two
stores per cell and comes back to the rivers slowly:

  1. Root-zone bucket (size S_max).  It takes the soaked-in water
     (rain − runoff, whatever ``RUNOFF_SOURCE`` made the runoff) and loses
     evaporation by the FAO-56 water-stress rule (Allen et al. 1998, eq. 84,
     depletion fraction 0.5): the full reference evaporation ET0 while the
     bucket is more than half full, less in proportion below that.
     Water above S_max overflows (recharge).
  2. Groundwater store, a linear reservoir: Q = G / K, K = BASEFLOW_RESPONSE_DAYS.
     Its outflow enters the nearest downstream river cell.

Without new water the store empties as Q0·e^(−t/K) — the classic recession curve
(HEC-HMS "Recession", k = e^(−1/K) per day) — so ``BASEFLOW_SPECIFIC_Q`` becomes
the *starting* baseflow: it fades, and soaked-in rain refills it.

The stores are advanced only at output times (the time step already stops
there), with the exact solution of the linear store, so they add one
accumulation per routing step and never limit the step.  Water is conserved:
soaked in = evaporated + returned to rivers + change in the two stores.

Evidence and the reasons for this method: TestCases/baseflow_methods/report.md.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np

from ...utils import gpu_utils
from .state import StateMixin

DEPLETION_FRACTION = 0.5      # FAO-56 p: no stress while the bucket is fuller than this
AVAILABLE_WATER = 0.10        # plant-available water [m³/m³] × root depth = bucket size
DEFAULT_STORAGE_MM = 150.0    # bucket size without land cover (tested value)
ET0_FILE = "baseflow_et0.json"
BASEFLOW_CSV = "baseflow.csv"


class SlowFlowError(ValueError):
    """Baseflow store could not be set up."""


# ─────────────────────────────────────────────────────────────────────────────
# Evaporation demand (ET0)
# ─────────────────────────────────────────────────────────────────────────────

def _basin_centre(cfg):
    path = getattr(cfg, "WATERSHED_GEOJSON", None)
    if path and os.path.isfile(path):
        try:
            from ..precip.openmeteo import _watershed_bounds_4326
            x0, y0, x1, y1 = _watershed_bounds_4326(path)
            return 0.5 * (y0 + y1), 0.5 * (x0 + x1)
        except Exception:
            pass
    pt = getattr(cfg, "OUTPUT_POINT", None)
    if pt:
        return float(pt[0]), float(pt[1])
    raise SlowFlowError("No basin outline or outlet point to place the evaporation request.")


def download_et0(cfg, start_utc, hours):
    """
    Daily FAO reference evaporation [mm/day] at the basin centre from Open-Meteo
    (no account) for the run window → (first day 00:00 UTC, list of mm/day).
    Cached in OUTPUT_DIR; the cache is used when the request fails.
    """
    from ..precip import openmeteo as om

    lat, lon = _basin_centre(cfg)
    d0 = start_utc.date()
    d1 = (start_utc + timedelta(hours=float(hours))).date()
    cache = os.path.join(getattr(cfg, "OUTPUT_DIR", "output/"), ET0_FILE)
    key = {"lat": round(lat, 3), "lon": round(lon, 3), "start": d0.isoformat(), "end": d1.isoformat()}
    cached = None
    if os.path.isfile(cache):
        try:
            with open(cache) as fh:
                cached = json.load(fh)
        except (OSError, ValueError):
            cached = None
        if cached and cached.get("key") == key:
            return d0, cached["et0_mm_day"]
    api = om.resolve_source("auto", start_utc)
    url = (om._base_url(api) + f"?latitude={lat:.4f}&longitude={lon:.4f}"
           f"&start_date={d0.isoformat()}&end_date={d1.isoformat()}"
           "&daily=et0_fao_evapotranspiration&timezone=GMT")
    if os.environ.get("OPENMETEO_API_KEY"):
        url += "&apikey=" + os.environ["OPENMETEO_API_KEY"]
    try:
        vals = (om._http_get_json(url).get("daily") or {}).get("et0_fao_evapotranspiration") or []
    except Exception as exc:
        if cached and cached.get("key", {}).get("start") == key["start"]:
            print(f"  [WARN] evaporation download failed ({str(exc)[:100]}); using the saved copy")
            return d0, cached["et0_mm_day"]
        raise SlowFlowError(
            "The evaporation demand could not be downloaded from Open-Meteo "
            f"({str(exc)[:120]}). Set BASEFLOW_ET0_MM_DAY to a number (for example 3) "
            "to run without the download.") from None
    good = [float(v) for v in vals if v is not None]
    if not good:
        raise SlowFlowError("Open-Meteo returned no evaporation values for this period. "
                            "Set BASEFLOW_ET0_MM_DAY to a number.")
    mean = sum(good) / len(good)
    vals = [mean if v is None else float(v) for v in vals]     # days not yet published
    try:
        os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
        with open(cache, "w") as fh:
            json.dump({"key": key, "source": f"open-meteo {api}", "et0_mm_day": vals}, fh)
    except OSError:
        pass
    return d0, vals


class Et0Series:
    """Evaporation demand over time: mean rate [m/s] between two simulation times."""

    def __init__(self, cfg, total_hours):
        number = getattr(cfg, "BASEFLOW_ET0_MM_DAY", None)
        if number is not None:
            self._const = float(number) / 1000.0 / 86400.0
            self.label = f"{float(number):g} mm/day (set by you)"
            return
        self._const = None
        start = getattr(cfg, "EVENT_START_UTC", None)
        if not start:
            raise SlowFlowError(
                "BASEFLOW_METHOD='store' needs the evaporation demand: set EVENT_START_UTC "
                "(it is then downloaded for those dates) or BASEFLOW_ET0_MM_DAY.")
        t0 = datetime.fromisoformat(str(start).strip().rstrip("Z"))
        if t0.tzinfo is not None:
            t0 = t0.astimezone(timezone.utc).replace(tzinfo=None)
        day0, vals = download_et0(cfg, t0, total_hours)
        offset = (datetime(day0.year, day0.month, day0.day) - t0).total_seconds()   # ≤ 0
        edges = offset + 86400.0 * np.arange(len(vals) + 1)
        self._edges = edges
        self._cum = np.concatenate([[0.0], np.cumsum(np.asarray(vals, float) / 1000.0)])  # [m]
        self._last = float(vals[-1]) / 1000.0 / 86400.0
        self.label = (f"Open-Meteo daily ET0 at the basin centre, "
                      f"mean {np.mean(vals):.2f} mm/day over {len(vals)} days")

    def depth(self, t0, t1):
        """Evaporation demand [m] between simulation times t0 < t1 [s]."""
        if t1 <= t0:
            return 0.0
        if self._const is not None:
            return self._const * (t1 - t0)
        c = np.interp([t0, t1], self._edges, self._cum)
        d = float(c[1] - c[0])
        end = self._edges[-1]
        if t1 > end:                                   # past the series: keep the last day
            d += self._last * (t1 - max(t0, end))
        return d


# ─────────────────────────────────────────────────────────────────────────────
# The store
# ─────────────────────────────────────────────────────────────────────────────

def river_targets(ds_idx, river):
    """For each cell, the nearest downstream river cell (or the exit cell of its
    path when it meets no river).  Pointer jumping on the D8 tree."""
    n = ds_idx.size
    idx = np.arange(n)
    tgt = np.where(river | (ds_idx < 0), idx, ds_idx)
    while True:
        nxt = tgt[tgt]
        if np.array_equal(nxt, tgt):
            return tgt
        tgt = nxt


class SlowFlowStore(StateMixin):
    """Root-zone bucket + linear groundwater store per cell (see module text)."""

    def __init__(self, cfg, grid_data, dtype=np.float64):
        xp = grid_data.get("xp", np)
        self._xp = xp
        self._cfg = cfg
        self._dtype = dtype
        n = int(grid_data["n_cells"])
        self._n = n
        self._cell_area = float(grid_data["cell_area"])
        to_np = gpu_utils.to_cpu

        self.K_days = float(getattr(cfg, "BASEFLOW_RESPONSE_DAYS", 45.0))
        self._K = self.K_days * 86400.0
        total_h = float(cfg.TOTAL_SIMULATION_TIME_HOURS)
        self._et0 = Et0Series(cfg, total_h)

        # Pervious share of each cell: only that part soaks, stores and evaporates.
        engine = grid_data.get("runoff_engine")
        imp = getattr(getattr(engine, "_imperv", None), "frac", None) if engine is not None else None
        perv = 1.0 - np.clip(np.asarray(to_np(imp), dtype=np.float64), 0.0, 1.0) if imp is not None \
            else np.ones(n)

        # Bucket size [m]: a number, or root depth (land cover) × available water.
        given = getattr(cfg, "BASEFLOW_SOIL_STORAGE_MM", None)
        if given is not None:
            smax = np.full(n, float(given) / 1000.0)
            how = f"{float(given):g} mm everywhere (set by you)"
        else:
            src = str(getattr(cfg, "MANNINGS_N_SOURCE", "scalar")).lower()
            smax = None
            if src in ("lulc", "lcz"):
                from ..routing import surface
                zr = surface.resolve_lulc_field(cfg, grid_data, "root_zone_depth_m", np.nan, src)
                if np.isfinite(zr).any():
                    zr = np.where(np.isfinite(zr), zr, np.nanmean(zr))
                    smax = np.maximum(zr, 0.05) * AVAILABLE_WATER
                    how = (f"land-cover root depth × {AVAILABLE_WATER:g}: "
                           f"{1000 * smax.min():.0f}–{1000 * smax.max():.0f} mm, mean {1000 * smax.mean():.0f} mm")
            if smax is None:
                smax = np.full(n, DEFAULT_STORAGE_MM / 1000.0)
                how = f"{DEFAULT_STORAGE_MM:g} mm everywhere (no land-cover map in this run)"
        smax = smax * perv

        wet = float(getattr(cfg, "BASEFLOW_START_WETNESS", 0.5))
        q0 = float(getattr(cfg, "BASEFLOW_SPECIFIC_Q", 0.0) or 0.0)          # m³/s per km²

        # Where each cell's baseflow enters the river network.
        ds = np.asarray(to_np(grid_data["ds_idx"])).astype(np.int64)
        river = np.asarray(to_np(grid_data["chan_mask_1d"])).astype(bool)
        if not river.any():
            from ..routing import surface
            river = np.asarray(surface.channel_mask_1d(cfg, grid_data)).astype(bool)
        self._target = xp.asarray(river_targets(ds, river))

        f64 = np.float64
        self._smax = xp.asarray(smax, dtype=f64)
        self._perv = xp.asarray(perv, dtype=f64)
        self._S = xp.asarray(wet * smax, dtype=f64)                 # bucket [m]
        self._G = xp.full(n, q0 * 1e-6 * self._K, dtype=f64)        # store, before the planned release [m]
        self._out = xp.zeros(n, dtype=f64)                          # release planned for this interval [m]
        self._soak = xp.zeros(n, dtype=f64)                         # soaked in since the last update [m]
        self.rate_1d = xp.zeros(n, dtype=dtype)                     # inflow to river cells [m³/s]
        self._rate_sum = 0.0
        self._t_last = 0.0
        # Totals [m³] for the budget.
        self._storage0 = None
        self.soaked_m3 = self.evap_m3 = self.recharge_m3 = self.released_m3 = self.delivered_m3 = 0.0
        self._rows = []
        print(f"  Baseflow store |  response time {self.K_days:g} days  |  root-zone storage: {how}")
        print(f"                 |  evaporation demand: {self._et0.label}")
        print(f"                 |  starts {100 * wet:.0f} % full"
              + (f", baseflow {q0:g} m³/s per km²" if q0 > 0 else ", no starting baseflow")
              + f"  |  {int(river.sum()):,} river cells receive it")

    # ── Restart ──────────────────────────────────────────────────────────────
    def state_attrs(self):
        return ("_S", "_G")

    def param_attrs(self):
        return ("_smax",)

    # ── Per routing step ─────────────────────────────────────────────────────
    def add_step(self, rain_1d, source_1d, dt):
        """Collect the water that soaked in this step [m] (rain − runoff, never negative)."""
        self._soak += self._xp.maximum(rain_1d - source_1d, 0.0) * dt
        self.delivered_m3 += self._rate_sum * dt

    # ── At output times ──────────────────────────────────────────────────────
    def _storage_m3(self):
        return float(((self._S + self._G - self._out).sum()).item()) * self._cell_area

    def update(self, t_seconds, next_dt):
        """
        Close the interval that ends at *t_seconds* (soak in, evaporate, recharge)
        and plan the release over the next *next_dt* seconds (0 at the end of the run).
        Called once at t = 0 (after a restart state is loaded) and at every output time.
        """
        xp = self._xp
        if self._storage0 is None:
            self._storage0 = float(((self._S + self._G).sum()).item()) * self._cell_area
        soak = self._soak
        S = self._S + soak
        demand = self._et0.depth(self._t_last, t_seconds)                     # [m]
        full = xp.maximum(DEPLETION_FRACTION * self._smax, 1e-12)
        et = xp.minimum(demand * self._perv * xp.minimum(S / full, 1.0), S)
        S = S - et
        rech = xp.maximum(S - self._smax, 0.0)
        self._S = S - rech
        G = self._G - self._out + rech
        a = self._cell_area
        self.soaked_m3 += float(soak.sum().item()) * a
        self.evap_m3 += float(et.sum().item()) * a
        self.recharge_m3 += float(rech.sum().item()) * a
        mean_rate = self._rate_sum                                            # over the closed interval
        if next_dt > 0.0:
            out = G * (-np.expm1(-next_dt / self._K))                         # exact linear-store release
            rate = xp.zeros(self._n, dtype=np.float64)
            gpu_utils.scatter_add(rate, self._target, out * (a / next_dt))
            self.rate_1d = rate.astype(self._dtype)
            self._rate_sum = float(self.rate_1d.sum().item())
            self.released_m3 += self._rate_sum * next_dt
        else:
            out = xp.zeros(self._n, dtype=np.float64)
            self.rate_1d = xp.zeros(self._n, dtype=self._dtype)
            self._rate_sum = 0.0
        self._G, self._out = G, out
        self._soak = xp.zeros(self._n, dtype=np.float64)
        self._t_last = t_seconds
        area = self._n * a
        self._rows.append((t_seconds, 1000 * self.soaked_m3 / area, 1000 * self.evap_m3 / area,
                           1000 * self.recharge_m3 / area,
                           1000 * float(self._S.sum().item()) * a / area,
                           1000 * float((G - out).sum().item()) * a / area, mean_rate))

    # ── End of run ───────────────────────────────────────────────────────────
    def finish(self):
        """Print the soil and groundwater budget and write baseflow.csv."""
        import pandas as pd
        from ..routing.reporting import utc_times

        stored = self._storage_m3()
        change = stored - (self._storage0 or 0.0)
        err = self.soaked_m3 - self.evap_m3 - self.delivered_m3 - change
        scale = max(self.soaked_m3 + (self._storage0 or 0.0), 1e-9)
        area = self._n * self._cell_area
        mm = lambda v: 1000.0 * v / area
        print("-" * 60)
        print("SOIL AND GROUNDWATER BUDGET  (baseflow store)")
        print(f"  Soaked in            : {self.soaked_m3:16.3f} m³   ({mm(self.soaked_m3):8.1f} mm)")
        print(f"  Evaporated           : {self.evap_m3:16.3f} m³   ({mm(self.evap_m3):8.1f} mm)")
        print(f"  Returned as baseflow : {self.delivered_m3:16.3f} m³   ({mm(self.delivered_m3):8.1f} mm)")
        print(f"  Change in the stores : {change:16.3f} m³   ({mm(change):8.1f} mm)")
        print(f"  Closure error        : {err:16.3f} m³   ({100.0 * err / scale:+.2e} %)  "
              f"[{'PASS' if abs(err / scale) < 1e-6 else 'WARN'}]")
        df = pd.DataFrame(self._rows, columns=["time_s", "soaked_in_mm", "evaporation_mm", "recharge_mm",
                                               "soil_water_mm", "groundwater_mm", "baseflow_m3s"])
        stamps = utc_times(self._cfg, df["time_s"].to_numpy())
        if stamps is not None:
            df["time_utc"] = stamps
        path = os.path.join(getattr(self._cfg, "OUTPUT_DIR", "output/"), BASEFLOW_CSV)
        df.to_csv(path, index=False)
        print(f"  Baseflow record → {path}")
        return {"soaked_m3": self.soaked_m3, "evap_m3": self.evap_m3, "baseflow_m3": self.delivered_m3,
                "store_change_m3": change, "error_m3": err}
