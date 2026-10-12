# -*- coding: utf-8 -*-
"""
descriptors.py
==============
The catchment numbers the Nepali methods need, measured from the DEM so
nobody has to do it by hand in a GIS:

    A      total area (km²)
    A3000  area below 3,000 m (km²) — WECS/DHM, DHM 2004
    A5000  area below 5,000 m (km²) — WECS/DHM monthly flows
    snow   permanent-snow area, taken as the area at or above 5,000 m
           (km²) — Modified Dickens
    L, S   longest flow path (km) and its average slope H/L (m/m) —
           Kirpich time of concentration (Rational method)
    S10-85 slope between 10 % and 85 % of L from the outlet (m/m)
    Lc     distance along L from the outlet to the point nearest the
           catchment centroid (km)

``measure_catchment(folder)`` reads the rasters the ``process_dem`` stage
writes (clipped_dem.tif, flow_direction.tif, clipped_flow_accumulation.tif,
watershed.tif); ``CatchmentDescriptors(area_km2=65)`` types them in instead
(A3000 and A5000 then default to the whole area, as for a Terai/Chure
catchment, and the assumption is reported).
"""

import contextlib
import io
import math
import os
from dataclasses import asdict, dataclass, fields
from typing import Optional

import numpy as np
import pandas as pd

# Elevation limits the official methods use.
RAIN_FED_LIMIT_M = 3000.0      # WECS/DHM and DHM 2004: area below 3,000 m
SNOW_LIMIT_M = 5000.0          # permanent snow / WECS-DHM low flows: 5,000 m
CHURE_MAX_M = 1500.0           # highest point of a Chure/Siwalik catchment (approximate)

_D8 = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1),
       4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}
_D8_DIAGONAL = (128, 2, 8, 32)


@dataclass
class CatchmentDescriptors:
    """
    The catchment numbers used by the Nepali methods (units in the names).

    Only ``area_km2`` is required.  Left empty, the area below 3,000 m and
    below 5,000 m default to the whole area and the snow area to the area
    above 5,000 m (0 when that is unknown) — ``assumptions()`` lists every
    value that was assumed rather than measured or typed.
    """

    area_km2: float
    area_below_3000_km2: Optional[float] = None
    area_below_5000_km2: Optional[float] = None
    snow_area_km2: Optional[float] = None
    flow_length_km: Optional[float] = None
    flow_path_slope: Optional[float] = None
    slope_10_85: Optional[float] = None
    centroid_distance_km: Optional[float] = None
    mean_elevation_m: Optional[float] = None
    min_elevation_m: Optional[float] = None
    max_elevation_m: Optional[float] = None
    outlet_lat: Optional[float] = None
    outlet_lon: Optional[float] = None
    outlet_xy: Optional[tuple] = None
    crs: Optional[str] = None
    name: str = ""
    source: str = "typed"

    def __post_init__(self):
        if self.area_km2 is None or not float(self.area_km2) > 0:
            raise ValueError(f"The catchment area must be more than 0 km² (got {self.area_km2!r}).")
        self.area_km2 = float(self.area_km2)
        for f in ("area_below_3000_km2", "area_below_5000_km2", "snow_area_km2",
                  "flow_length_km", "centroid_distance_km"):
            v = getattr(self, f)
            if v is not None:
                v = float(v)
                if v < 0:
                    raise ValueError(f"{f} cannot be negative (got {v}).")
                setattr(self, f, v)
        tol = 1e-6 * self.area_km2
        for f in ("area_below_3000_km2", "area_below_5000_km2", "snow_area_km2"):
            v = getattr(self, f)
            if v is not None and v > self.area_km2 + tol:
                raise ValueError(f"{f} ({v:g} km²) cannot be larger than the whole "
                                 f"area ({self.area_km2:g} km²).")
        a3, a5 = self.area_below_3000_km2, self.area_below_5000_km2
        if a3 is not None and a5 is not None and a3 > a5 + tol:
            raise ValueError(f"The area below 3,000 m ({a3:g} km²) cannot exceed the area "
                             f"below 5,000 m ({a5:g} km²).")
        if self.outlet_xy is not None:
            self.outlet_xy = tuple(float(v) for v in self.outlet_xy)

    # ── The values the methods use (with the documented defaults) ────────────
    @property
    def a3000(self):
        """Area below 3,000 m [km²] (the whole area when not given)."""
        return self.area_km2 if self.area_below_3000_km2 is None else self.area_below_3000_km2

    @property
    def a5000(self):
        """Area below 5,000 m [km²] (the whole area when not given)."""
        if self.area_below_5000_km2 is not None:
            return self.area_below_5000_km2
        if self.snow_area_km2 is not None:
            return max(self.area_km2 - self.snow_area_km2, 0.0)
        return self.area_km2

    @property
    def snow(self):
        """Permanent-snow area [km²]: given, else the area above 5,000 m, else 0."""
        if self.snow_area_km2 is not None:
            return self.snow_area_km2
        if self.area_below_5000_km2 is not None:
            return max(self.area_km2 - self.area_below_5000_km2, 0.0)
        return 0.0

    def assumptions(self):
        """Plain sentences for every value that was assumed, not measured or typed."""
        notes = []
        if self.area_below_3000_km2 is None:
            notes.append("the area below 3,000 m is taken as the whole area (true for "
                         "Terai and Chure catchments; give it if part lies higher)")
        if self.area_below_5000_km2 is None and self.snow_area_km2 is None:
            notes.append("no permanent snow is assumed (no area above 5,000 m)")
        return notes

    def river_class(self):
        """
        (class, description) after the compendium's river classes, judged
        from the elevations — approximate, for warnings only:
        I snow-fed (area above 5,000 m), III Chure/Siwalik or Terai stream
        (highest point below about 1,500 m), II other rain-fed rivers.
        The class is None when the elevations are unknown.
        """
        if self.snow > 0 or (self.max_elevation_m is not None
                             and self.max_elevation_m >= SNOW_LIMIT_M):
            return "I", "snow-fed river (part of the catchment lies above 5,000 m)"
        if self.max_elevation_m is not None:
            if self.max_elevation_m < CHURE_MAX_M:
                return "III", ("Chure/Siwalik or Terai stream (highest point below about "
                               f"{CHURE_MAX_M:,.0f} m)")
            return "II", "rain-fed river from the hills or the Mahabharat range"
        if self.a3000 < self.area_km2:
            return "II", "rain-fed river with high ground above 3,000 m"
        return None, ("rain-fed catchment wholly below 3,000 m (give the highest elevation "
                      "to tell a Chure stream from a hill river)")

    @property
    def is_chure_or_terai(self):
        """True when the catchment looks like a Class III Chure/Terai stream."""
        return self.river_class()[0] == "III"

    # ── Conversions ──────────────────────────────────────────────────────────
    def to_dict(self):
        """All fields as plain values (outlet_xy as a list), for YAML/JSON."""
        d = asdict(self)
        if d.get("outlet_xy") is not None:
            d["outlet_xy"] = list(d["outlet_xy"])
        return d

    @classmethod
    def from_dict(cls, data):
        """Build from a dict; unknown keys raise a clear error."""
        names = {f.name for f in fields(cls)}
        data = dict(data or {})
        unknown = sorted(set(data) - names)
        if unknown:
            raise ValueError(f"Unknown catchment value(s): {', '.join(unknown)}. "
                             f"Known: {', '.join(sorted(names))}.")
        return cls(**data)

    def table(self):
        """A two-column table (quantity, value) for display and reports."""
        rows = [("Total area A", _num(self.area_km2), "km²"),
                ("Area below 3,000 m (A3000)", _num(self.a3000), "km²"),
                ("Area below 5,000 m (A5000)", _num(self.a5000), "km²"),
                ("Permanent snow (≥ 5,000 m)", _num(self.snow), "km²")]
        optional = [("Longest flow path L", self.flow_length_km, "km"),
                    ("Slope of L (H/L)", self.flow_path_slope, "m/m"),
                    ("Slope 10–85 %", self.slope_10_85, "m/m"),
                    ("Length to centroid Lc", self.centroid_distance_km, "km"),
                    ("Mean elevation", self.mean_elevation_m, "m"),
                    ("Lowest elevation", self.min_elevation_m, "m"),
                    ("Highest elevation", self.max_elevation_m, "m"),
                    ("Outlet latitude", self.outlet_lat, "°"),
                    ("Outlet longitude", self.outlet_lon, "°")]
        rows += [(q, _num(v), u) for q, v, u in optional if v is not None]
        cls, why = self.river_class()
        rows.append(("River class (approximate)", f"{cls or '?'} — {why}", ""))
        return pd.DataFrame(rows, columns=["quantity", "value", "unit"])

    def summary(self):
        """One line: 'A = 65 km² (A3000 65, snow 0) · L 15 km · S 0.015'."""
        parts = [f"A = {_num(self.area_km2)} km² (below 3,000 m: {_num(self.a3000)}, "
                 f"snow: {_num(self.snow)})"]
        if self.flow_length_km is not None:
            parts.append(f"L = {_num(self.flow_length_km)} km")
        if self.flow_path_slope is not None:
            parts.append(f"S = {_num(self.flow_path_slope)} m/m")
        if self.max_elevation_m is not None:
            parts.append(f"highest point {self.max_elevation_m:,.0f} m")
        return (self.name + ": " if self.name else "") + " · ".join(parts)


def _num(v):
    """Compact display: 4 significant figures, no trailing noise."""
    if v is None:
        return ""
    v = float(v)
    if v == 0:
        return "0"
    return f"{v:.4g}" if abs(v) < 1e5 else f"{v:,.0f}"


# ═════════════════════════════════════════════════════════════════════════════
# Measuring from the DEM results
# ═════════════════════════════════════════════════════════════════════════════
def _config_for(source):
    """A Config whose ROUTING_* paths point at the delineated catchment."""
    from ..config import Config
    if hasattr(source, "ROUTING_DEM_PATH"):
        return source
    path = os.fspath(source)
    if os.path.isdir(path):
        cfg = Config(OUTPUT_DIR=path)
        cfg.update_output_paths()
        return cfg
    if os.path.isfile(path):
        return Config.from_file(path)
    raise FileNotFoundError(f"No results folder or config file at {path!r}.")


def delineated(source):
    """True when *source* (a Config, results folder or config file) holds a
    delineated catchment (the four rasters the process_dem stage writes)."""
    try:
        cfg = _config_for(source)
    except (FileNotFoundError, OSError, ValueError):
        return False
    return all(os.path.isfile(p) for p in _raster_paths(cfg))


def _raster_paths(cfg):
    return (cfg.ROUTING_DEM_PATH, cfg.ROUTING_FLOW_DIR_PATH,
            cfg.ROUTING_FLOW_ACCUM_PATH, cfg.ROUTING_WATERSHED_MASK_PATH)


def measure_catchment(source, name=""):
    """
    Measure the catchment descriptors from the rasters of a ``process_dem``
    run.

    source   a results folder, a config file (its OUTPUT_DIR is used) or a
             Config.  For a whole-DEM run the catchment of the main exit
             (the largest drainage area) is measured.
    name     an optional site name carried into tables and reports.
    """
    import rasterio
    from ..core.routing import terrain

    cfg = _config_for(source)
    missing = [p for p in _raster_paths(cfg) if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError(
            "No delineated catchment found (missing " + ", ".join(os.path.basename(p)
                                                            for p in missing)
            + f" in {os.path.dirname(missing[0]) or '.'}). Run the process_dem stage "
            "first, e.g. MRRpy run -c run.yaml --stages process_dem, or type the "
            "catchment numbers instead.")
    with contextlib.redirect_stdout(io.StringIO()):          # keep the model's prints out
        dem, fdir, faccum, ws_mask, transform, _nodata, cell_size = terrain.load_rasters(cfg)
        s_rows, s_cols, outlet_rc = terrain.topological_order(faccum, fdir, ws_mask)
    with rasterio.open(cfg.ROUTING_DEM_PATH) as src:
        crs = src.crs.to_string() if src.crs else None

    nrows, ncols = dem.shape
    fd = fdir[s_rows, s_cols].astype(np.int64)
    ds = _downstream_map(s_rows, s_cols, fd, ws_mask, nrows, ncols)
    step = float(cell_size) * np.where(np.isin(fd, _D8_DIAGONAL), math.sqrt(2.0), 1.0)
    outlet = len(s_rows) - 1                                  # highest accumulation
    dist, inside = _downstream_pass(ds, step, outlet)

    z = dem[s_rows, s_cols].astype(np.float64)
    zb = z[inside]
    cell_km2 = float(cell_size) ** 2 / 1e6
    area = inside.sum() * cell_km2

    # Longest flow path: the basin cell farthest (along the flow) from the outlet.
    far = np.where(inside, dist, -1.0)
    start = int(np.argmax(far))
    path = [start]
    while path[-1] != outlet and len(path) <= len(ds):
        path.append(int(ds[path[-1]]))
    path = np.asarray(path)
    length_m = float(dist[start])
    zp, dp = z[path], dist[path]
    slope = s1085 = lc_km = None
    if length_m > 0:
        slope = float((zp[0] - zp[-1]) / length_m)
        order = np.argsort(dp)
        z10 = float(np.interp(0.10 * length_m, dp[order], zp[order]))
        z85 = float(np.interp(0.85 * length_m, dp[order], zp[order]))
        s1085 = (z85 - z10) / (0.75 * length_m)
        xs = transform.c + (s_cols + 0.5) * transform.a
        ys = transform.f + (s_rows + 0.5) * transform.e
        cx, cy = xs[inside].mean(), ys[inside].mean()
        near = int(np.argmin((xs[path] - cx) ** 2 + (ys[path] - cy) ** 2))
        lc_km = float(dp[near]) / 1000.0
    ox = transform.c + (s_cols[outlet] + 0.5) * transform.a
    oy = transform.f + (s_rows[outlet] + 0.5) * transform.e
    lat, lon = terrain.cell_latlon(outlet_rc, transform, crs) if crs else (None, None)

    return CatchmentDescriptors(
        area_km2=float(area),
        area_below_3000_km2=float((zb < RAIN_FED_LIMIT_M).sum() * cell_km2),
        area_below_5000_km2=float((zb < SNOW_LIMIT_M).sum() * cell_km2),
        snow_area_km2=float((zb >= SNOW_LIMIT_M).sum() * cell_km2),
        flow_length_km=length_m / 1000.0 if length_m > 0 else None,
        flow_path_slope=slope,
        slope_10_85=s1085,
        centroid_distance_km=lc_km,
        mean_elevation_m=float(zb.mean()),
        min_elevation_m=float(zb.min()),
        max_elevation_m=float(zb.max()),
        outlet_lat=lat,
        outlet_lon=lon,
        outlet_xy=(float(ox), float(oy)),
        crs=crs,
        name=name,
        source="dem",
    )


def _downstream_map(s_rows, s_cols, fd, ws_mask, nrows, ncols):
    """Position of each cell's D8 downstream neighbour in the sorted list (−1 = none)."""
    n = len(s_rows)
    lut_r = np.zeros(256, dtype=np.int64)
    lut_c = np.zeros(256, dtype=np.int64)
    lut_ok = np.zeros(256, dtype=bool)
    for code, (dr, dc) in _D8.items():
        lut_r[code], lut_c[code], lut_ok[code] = dr, dc, True
    code = np.clip(fd, 0, 255)
    ok = (fd >= 0) & (fd <= 255) & lut_ok[code]
    rn = s_rows + lut_r[code]
    cn = s_cols + lut_c[code]
    ok &= (rn >= 0) & (rn < nrows) & (cn >= 0) & (cn < ncols)
    ok[ok] = ws_mask[rn[ok], cn[ok]]
    flat_to_pos = np.full(nrows * ncols, -1, dtype=np.int64)
    flat_to_pos[s_rows * ncols + s_cols] = np.arange(n, dtype=np.int64)
    ds = np.full(n, -1, dtype=np.int64)
    ds[ok] = flat_to_pos[rn[ok] * ncols + cn[ok]]
    return ds


def _downstream_pass(ds, step, outlet):
    """
    Distance along the flow to the outlet [m] and whether each cell drains
    to it, in one pass from the outlet upstream (cells are sorted upstream
    first, so a cell's downstream neighbour is always visited before it).
    """
    n = ds.shape[0]
    dist = np.zeros(n)
    inside = np.zeros(n, dtype=np.bool_)
    inside[outlet] = True
    for i in range(n - 1, -1, -1):
        j = ds[i]
        if i != outlet and j >= 0 and inside[j]:
            inside[i] = True
            dist[i] = dist[j] + step[i]
    return dist, inside


try:                                                   # numba is optional
    from numba import njit as _njit
    _downstream_pass = _njit(cache=True)(_downstream_pass)
except Exception:                                      # pragma: no cover
    pass
