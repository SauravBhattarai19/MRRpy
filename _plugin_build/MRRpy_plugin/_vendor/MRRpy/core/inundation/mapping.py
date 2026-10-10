# -*- coding: utf-8 -*-
"""
mapping.py — flood depth and extent from the routed discharge (HAND method).

For every river reach the routed discharge is turned into a water level with
the reach's synthetic rating curve (rating.py), and that level is spread over
every cell that drains to the reach and lies below it:

    depth = stage − HAND          where HAND < stage

Main stems are mapped again on their own (drainage area ×10, ×100, …) and the
deepest water wins, so a big river's flood backs up into the mouths of side
streams.  The grid is the run's original DEM or a finer one, with least-cost
flow paths and discharge taken from the matching routed river cells
(finegrid.py), or — when that DEM is missing — the routing network itself.
"""

import json
import os

import numpy as np

from . import network as N
from .rating import floodplain_area, rating_curves_fitting, stage_from_discharge

try:
    from numba import njit as _njit
except Exception:                                 # pragma: no cover
    def _njit(*a, **k):
        return (lambda f: f) if not (a and callable(a[0])) else a[0]

WET_M = 0.01          # [m] shallower water is not drawn
DURATION_M = 0.1      # [m] depth counted for first-wet time and duration
_CHUNK = 2048         # time records processed at once


class FloodGrid:
    """
    A D8 grid ready for HAND mapping.  Per cell (n,): raster position
    (rows, cols), downstream index ``ds`` and a downstream-first ``order``,
    elevation never rising downstream ``z`` (slopes) and original elevation
    ``z_raw`` (heights), flow length ``dist``, drainage area ``area_km2``, reach
    slope, floodplain n, river flag, and on river cells the channel (W, D,
    n_ch) and where the discharge comes from: routed river ``src`` (index into
    the run's river cells) times ``scale`` (drainage-area ratio).
    ``inside`` marks the cells the maps are written for.
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.n = len(self.z)

    @property
    def cell_area(self):
        return self.cell_size ** 2


def routing_flood_grid(arrays, meta):
    """The routing grid itself (discharge taken cell by cell, no transfer)."""
    n = len(arrays["z"])
    river = arrays["river"].astype(bool)
    src = np.full(n, -1, dtype=np.int64)
    src[arrays["river_idx"]] = np.arange(arrays["river_idx"].size)
    from affine import Affine
    return FloodGrid(
        label=f"model grid, {meta['cell_size']:g} m", fine=False,
        nrows=meta["nrows"], ncols=meta["ncols"], transform=Affine(*meta["transform"]),
        crs=meta["crs"], cell_size=float(meta["cell_size"]),
        rows=arrays["s_rows"].astype(np.int64), cols=arrays["s_cols"].astype(np.int64),
        ds=arrays["ds"].astype(np.int64), order=np.arange(n, dtype=np.int64)[::-1],
        z=arrays["z"].astype(np.float64),
        z_raw=arrays.get("z_raw", arrays["z"]).astype(np.float64),
        dist=arrays["dist"].astype(np.float64),
        area_km2=arrays["area_km2"].astype(np.float64),
        slope_reach=arrays["slope_reach"].astype(np.float64),
        n_fp=arrays["n_fp"].astype(np.float64), river=river,
        W=arrays["W"].astype(np.float64), D=arrays["D"].astype(np.float64),
        n_ch=arrays["n_ch"].astype(np.float64), src=src, scale=np.ones(n),
        inside=np.ones(n, dtype=bool), match=None)


# ── One HAND level ───────────────────────────────────────────────────────────
class Level:
    """HAND, reaches, rating curves and stages for one drainage level."""

    def __init__(self, grid, drains, threshold_km2, reach_len_m, q_river_peak, t_river_peak):
        g = grid
        self.threshold_km2 = float(threshold_km2)
        # Heights are measured on the original DEM above the river bed made
        # non-increasing by lowering only (NOAA OWP HAND practice): filling a
        # DEM raises whole valley floors with their rivers to one flat, which
        # would put HAND ≈ 0 across it.
        self.drain_of = N.nearest_drain(g.order, g.ds, drains)
        bed = N.river_bed_profile(g.order, g.ds, drains, g.z_raw)
        ok = self.drain_of >= 0
        self.hand = np.where(ok, np.maximum(g.z_raw - bed[np.where(ok, self.drain_of, 0)], 0.0),
                             np.nan)
        reach_of, L, _out = N.segment_reaches(g.order, g.ds, drains, g.dist, reach_len_m)
        R = self.n_reach = len(L)
        self.cell_reach = np.where(ok, reach_of[np.where(ok, self.drain_of, 0)], -1)

        di = np.flatnonzero(drains)
        rc = reach_of[di]
        cnt = np.maximum(np.bincount(rc, minlength=R), 1)
        mean = lambda v: np.bincount(rc, weights=v[di], minlength=R) / cnt
        self.L = L
        self.S = mean(g.slope_reach)
        self.W, self.D, self.n_ch = mean(g.W), mean(g.D), mean(g.n_ch)
        self.area_km2 = np.zeros(R)
        np.maximum.at(self.area_km2, rc, g.area_km2[di])

        # Discharge of each reach = the largest at any of its river cells.
        self._di_sorted = di[np.argsort(rc, kind="stable")]
        self._rc_sorted = reach_of[self._di_sorted]
        self._starts = np.r_[0, np.flatnonzero(np.diff(self._rc_sorted)) + 1]
        q_cell = _cell_flow(g, self._di_sorted, q_river_peak)
        self.q_peak = np.maximum.reduceat(q_cell, self._starts) if di.size else np.zeros(0)
        best = np.lexsort((q_cell, self._rc_sorted))           # last of each reach = max
        last = np.r_[np.flatnonzero(np.diff(self._rc_sorted[best])), best.size - 1]
        t_cell = _cell_flow(g, self._di_sorted, t_river_peak, scaled=False)
        self.t_peak_s = t_cell[best[last]] if di.size else np.zeros(0)

        a_fp = floodplain_area(self.cell_reach, self.hand, drains, g.W, g.dist,
                               g.cell_area, g.cell_size, R)
        self.y, self.Q, self.A = rating_curves_fitting(
            self.q_peak, self.cell_reach, self.hand, a_fp, g.n_fp, g.cell_area,
            L, self.S, self.W, self.D, self.n_ch)
        self.stage_peak, self.clipped = stage_from_discharge(self.Q, self.y, self.q_peak)
        self.stage_series = None

    def reach_series(self, grid, q_series):
        """(T, R) discharge of every reach from the run's river-cell series."""
        T = q_series.shape[0]
        out = np.zeros((T, self.n_reach), dtype=np.float32)
        for t0 in range(0, T, _CHUNK):
            q = _cell_flow(grid, self._di_sorted, q_series[t0:t0 + _CHUNK])
            out[t0:t0 + _CHUNK] = np.maximum.reduceat(q, self._starts, axis=1)
        return out

    def depth(self, stage):
        """Depth [m] at every cell for reach stages (R,)."""
        s = np.where(self.cell_reach >= 0, stage[np.maximum(self.cell_reach, 0)], 0.0)
        return np.where(self.cell_reach >= 0, np.maximum(s - self.hand, 0.0), 0.0)

    def flooded_km2(self, stage):
        """Flooded land [km²] per reach at stages (R,) or (T, R), from the curves."""
        stage = np.atleast_2d(stage)
        out = np.empty(stage.shape)
        for r in range(self.n_reach):
            out[:, r] = np.interp(stage[:, r], self.y, self.A[r]) / 1e6
        return out


def _cell_flow(grid, cells, river_values, scaled=True):
    """Routed river values at grid cells: values[..., src] (× scale)."""
    src = grid.src[cells]
    v = np.asarray(river_values)[..., np.maximum(src, 0)]
    if scaled:
        v = v * grid.scale[cells]
    return np.where(src >= 0, v, 0.0)


# ── The flood model (all levels + series) ────────────────────────────────────
class FloodModel:
    """HAND flood mapping of one run on one grid (see module docstring)."""

    def __init__(self, grid, arrays, meta, reach_len_m=1000.0, backwater=True):
        self.grid = grid
        self.meta = meta
        river_idx = arrays["river_idx"]
        q_peak = arrays["q_peak"][river_idx].astype(np.float64)
        t_peak = arrays["t_peak_s"][river_idx].astype(np.float64)
        a_max = float(grid.area_km2[grid.river].max()) if grid.river.any() else 0.0
        thr = N.level_thresholds(meta["a_channel_km2"], a_max) if backwater \
            else [meta["a_channel_km2"]]
        self.levels = []
        for k, a in enumerate(thr):
            drains = grid.river if k == 0 else grid.river & (grid.area_km2 >= a)
            if not drains.any():
                break
            self.levels.append(Level(grid, drains, a, reach_len_m, q_peak, t_peak))
        self.times_s = arrays["times_s"]
        q_series = arrays["q_series"]
        for lev in self.levels:
            lev.stage_series = stage_from_discharge(
                lev.Q, lev.y, lev.reach_series(grid, q_series))[0].astype(np.float32)
        self.dt_series_s = float(meta["output_interval_s"]) * int(meta.get("series_stride", 1))
        self._peak = None

    # -- maps ---------------------------------------------------------------
    def depth_peak(self):
        """(max depth (n,), time of max [s] (n,)) over the run."""
        if self._peak is None:
            depth = np.zeros(self.grid.n)
            tmax = np.full(self.grid.n, np.nan)
            for lev in self.levels:
                d = lev.depth(lev.stage_peak)
                t = np.where(lev.cell_reach >= 0, lev.t_peak_s[np.maximum(lev.cell_reach, 0)], np.nan)
                deeper = d > depth
                tmax = np.where(deeper, t, tmax)
                depth = np.maximum(depth, d)
            tmax = np.where(depth >= WET_M, tmax, np.nan)
            self._peak = (depth, tmax)
        return self._peak

    def first_wet_and_duration(self):
        """(first time deeper than 0.1 m [s], hours deeper than 0.1 m) per cell."""
        n = self.grid.n
        first = np.full(n, np.inf)
        dur = np.zeros(n)
        if not len(self.times_s):
            return np.full(n, np.nan), dur
        for lev in self.levels:
            f, d = _time_products(lev.cell_reach, lev.hand + DURATION_M,
                                  lev.stage_series.astype(np.float64), self.times_s)
            first = np.minimum(first, f)
            dur = np.maximum(dur, d)
        dur = dur * self.dt_series_s / 3600.0
        return np.where(np.isfinite(first), first, np.nan), dur

    # -- persistence for plots / animations ---------------------------------
    def save(self, path):
        g = self.grid
        d = dict(rows=g.rows.astype(np.int32), cols=g.cols.astype(np.int32),
                 z=g.z_raw.astype(np.float32), inside=g.inside, river=g.river,
                 times_s=self.times_s)
        depth, tmax = self.depth_peak()
        d["depth_max"] = depth.astype(np.float32)
        d["time_of_max_s"] = tmax.astype(np.float32)
        for k, lev in enumerate(self.levels):
            d[f"l{k}_cell_reach"] = lev.cell_reach.astype(np.int32)
            d[f"l{k}_hand"] = lev.hand.astype(np.float32)
            d[f"l{k}_stage_series"] = lev.stage_series
            d[f"l{k}_y"] = lev.y
            d[f"l{k}_A"] = lev.A.astype(np.float32)
        meta = dict(label=g.label, nrows=g.nrows, ncols=g.ncols,
                    transform=list(g.transform)[:6], crs=g.crs, cell_size=g.cell_size,
                    n_levels=len(self.levels), dt_series_s=self.dt_series_s,
                    hydrograph_csv=self.meta.get("hydrograph_csv"))
        np.savez_compressed(path, meta_json=np.array(json.dumps(meta)), **d)
        return path



@_njit(cache=True)
def _time_products(cell_reach, level, stage, times):
    """Per cell: first time the reach stage exceeds *level*, and the number of
    records it does (stage (T, R))."""
    T, R = stage.shape
    runmax = np.empty((T, R))
    srt = np.empty((T, R))
    for r in range(R):
        m = -np.inf
        for t in range(T):
            if stage[t, r] > m:
                m = stage[t, r]
            runmax[t, r] = m
        srt[:, r] = np.sort(stage[:, r])
    n = cell_reach.shape[0]
    first = np.full(n, np.inf)
    count = np.zeros(n)
    for i in range(n):
        r = cell_reach[i]
        h = level[i]
        if r < 0 or not (h == h):
            continue
        lo, hi = 0, T                             # first t with runmax > h
        while lo < hi:
            mid = (lo + hi) // 2
            if runmax[mid, r] > h:
                hi = mid
            else:
                lo = mid + 1
        if lo < T:
            first[i] = times[lo]
        lo, hi = 0, T                             # records with stage > h
        while lo < hi:
            mid = (lo + hi) // 2
            if srt[mid, r] > h:
                hi = mid
            else:
                lo = mid + 1
        count[i] = T - lo
    return first, count


# ── Writing the results ──────────────────────────────────────────────────────
def _area_window(grid, area_bbox):
    """(row0, row1, col0, col1) of the map area on the grid, and an (n,) mask."""
    rows, cols = grid.rows, grid.cols
    if not area_bbox:
        sel = grid.inside
    else:
        from pyproj import Transformer
        w, s, e, n = (float(v) for v in area_bbox)
        tr = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
        xs, ys = tr.transform([w, e, e, w], [s, s, n, n])
        inv = ~grid.transform
        cc, rr = inv * (np.array(xs), np.array(ys))
        # cells that overlap the box
        sel = (grid.inside & (rows >= np.floor(rr.min())) & (rows < np.ceil(rr.max()))
               & (cols >= np.floor(cc.min())) & (cols < np.ceil(cc.max())))
    if not sel.any():
        raise ValueError("The flood-map area (INUNDATION_AREA) does not overlap the modelled "
                         "area. Check it is west, south, east, north in degrees.")
    return (int(rows[sel].min()), int(rows[sel].max()) + 1,
            int(cols[sel].min()), int(cols[sel].max()) + 1), sel


def _to_grid(values, grid, sel, win, fill=np.nan):
    r0, r1, c0, c1 = win
    out = np.full((r1 - r0, c1 - c0), fill, dtype=np.float64)
    out[grid.rows[sel] - r0, grid.cols[sel] - c0] = values[sel]
    return out


def _write_tif(path, arr, grid, win, dtype="float32", nodata=-9999.0):
    import rasterio
    from rasterio.windows import Window, transform as win_transform
    r0, r1, c0, c1 = win
    prof = dict(driver="GTiff", height=r1 - r0, width=c1 - c0, count=1, dtype=dtype,
                nodata=nodata, crs=grid.crs, compress="deflate",
                transform=win_transform(Window(c0, r0, c1 - c0, r1 - r0), grid.transform))
    data = np.where(np.isfinite(arr), arr, nodata).astype(dtype)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(data, 1)
    return path


def write_outputs(model, out_dir, area_bbox=None, log=print):
    """Write the maps, tables and summary; returns {name: path}."""
    import geopandas as gpd
    import pandas as pd
    import rasterio.features
    from rasterio.windows import Window, transform as win_transform
    from shapely.geometry import LineString, shape

    g = model.grid
    os.makedirs(out_dir, exist_ok=True)
    win, sel = _area_window(g, area_bbox)
    out = {}
    depth, tmax = model.depth_peak()
    wet = depth >= WET_M
    first, dur = model.first_wet_and_duration()

    p = lambda name: os.path.join(out_dir, name)
    out["flood_depth_max"] = _write_tif(p("flood_depth_max.tif"),
                                        _to_grid(np.where(wet, depth, np.nan), g, sel, win), g, win)
    ext = _to_grid(wet.astype(float), g, sel, win, fill=0.0)
    out["flood_extent_max"] = _write_tif(p("flood_extent_max.tif"), ext, g, win,
                                         dtype="uint8", nodata=255)
    out["flood_time_of_max_hours"] = _write_tif(p("flood_time_of_max_hours.tif"),
                                                _to_grid(tmax / 3600.0, g, sel, win), g, win)
    out["flood_first_wet_hours"] = _write_tif(p("flood_first_wet_hours.tif"),
                                              _to_grid(first / 3600.0, g, sel, win), g, win)
    out["flood_duration_hours"] = _write_tif(p("flood_duration_hours.tif"),
                                             _to_grid(np.where(dur > 0, dur, np.nan), g, sel, win),
                                             g, win)
    out["hand"] = _write_tif(p("hand.tif"), _to_grid(model.levels[0].hand, g, sel, win), g, win)

    # Extent polygons
    r0, r1, c0, c1 = win
    tr = win_transform(Window(c0, r0, c1 - c0, r1 - r0), g.transform)
    mask = ext.astype("uint8")
    polys = [shape(geom) for geom, v in rasterio.features.shapes(mask, mask=mask > 0, transform=tr)
             if v == 1]
    gdf = gpd.GeoDataFrame({"area_km2": [q.area / 1e6 for q in polys]}, geometry=polys, crs=g.crs)
    out["flood_extent_geojson"] = p("flood_extent_max.geojson")
    if os.path.exists(out["flood_extent_geojson"]):
        os.remove(out["flood_extent_geojson"])
    if len(gdf):
        gdf.to_file(out["flood_extent_geojson"], driver="GeoJSON")
    else:
        with open(out["flood_extent_geojson"], "w") as f:
            json.dump({"type": "FeatureCollection", "features": []}, f)

    # Reach table, rating curves, reach lines
    rows, curves, lines, attrs = [], [], [], []
    xs, ys = g.transform * (g.cols + 0.5, g.rows + 0.5)
    for k, lev in enumerate(model.levels):
        fl = lev.flooded_km2(lev.stage_peak)[0]
        q_bank = lev.Q[:, 0]
        for r in range(lev.n_reach):
            rows.append(dict(level=k, reach=r, threshold_km2=lev.threshold_km2,
                             length_m=lev.L[r], slope=lev.S[r], channel_width_m=lev.W[r],
                             bankfull_depth_m=lev.D[r], n_channel=lev.n_ch[r],
                             drainage_km2=lev.area_km2[r], q_bankfull_m3s=q_bank[r],
                             q_peak_m3s=lev.q_peak[r], t_peak_hours=lev.t_peak_s[r] / 3600.0,
                             stage_above_bank_m=lev.stage_peak[r], flooded_km2=fl[r],
                             beyond_table=bool(lev.clipped[r])))
        step = max(1, int(round(0.25 / (lev.y[1] - lev.y[0]))))
        for r in range(lev.n_reach):
            for j in range(0, len(lev.y), step):
                curves.append((k, r, lev.y[j], lev.Q[r, j], lev.A[r, j] / 1e6))
        cells = lev._di_sorted
        for r in range(lev.n_reach):
            c = cells[lev._rc_sorted == r]
            c = c[np.argsort(g.area_km2[c])]
            if c.size >= 2:
                lines.append(LineString(np.column_stack([xs[c], ys[c]])))
                attrs.append(dict(level=k, reach=r, q_peak_m3s=float(lev.q_peak[r]),
                                  stage_above_bank_m=float(lev.stage_peak[r])))
    out["reaches_csv"] = p("reaches.csv")
    pd.DataFrame(rows).to_csv(out["reaches_csv"], index=False, float_format="%.4g")
    out["rating_curves_csv"] = p("rating_curves.csv")
    pd.DataFrame(curves, columns=["level", "reach", "stage_above_bank_m", "q_m3s",
                                  "flooded_km2"]).to_csv(out["rating_curves_csv"], index=False,
                                                         float_format="%.4g")
    out["reaches_geojson"] = p("reaches.geojson")
    if os.path.exists(out["reaches_geojson"]):
        os.remove(out["reaches_geojson"])
    if lines:
        gpd.GeoDataFrame(attrs, geometry=lines, crs=g.crs).to_file(out["reaches_geojson"],
                                                                   driver="GeoJSON")
    out["flood_model"] = model.save(p("flood_model.npz"))

    # Summary
    in_area = sel & wet
    lev0 = model.levels[0]
    summ = dict(
        grid=g.label, cell_size_m=g.cell_size,
        flooded_km2=float(in_area.sum() * g.cell_area / 1e6),
        max_depth_m=float(depth[in_area].max()) if in_area.any() else 0.0,
        reaches=int(lev0.n_reach),
        reaches_above_bank=int((lev0.stage_peak > 0).sum()),
        reaches_beyond_table=int(sum(int(l.clipped.sum()) for l in model.levels)),
        levels_km2=[l.threshold_km2 for l in model.levels],
        area_bbox=list(area_bbox) if area_bbox else None,
        discharge_transfer=getattr(g, "match", None),
    )
    out["summary_json"] = p("inundation_summary.json")
    with open(out["summary_json"], "w") as f:
        json.dump(summ, f, indent=2)
    log(f"  Flood maps     |  {summ['grid']}: {summ['flooded_km2']:.2f} km² flooded, deepest "
        f"{summ['max_depth_m']:.2f} m; {summ['reaches_above_bank']} of {summ['reaches']} river "
        f"reaches went above their banks.")
    if summ["reaches_beyond_table"]:
        log(f"  [WARN] {summ['reaches_beyond_table']} reach(es) carried more water than a "
            f"100 m-deep valley holds; their depth is capped (see reaches.csv, beyond_table).")
    return out


# ── Loading a saved flood model (plots, animations) ──────────────────────────
class SavedFlood:
    """A flood_model.npz read back: depth maps at the peak or any saved time."""

    def __init__(self, path):
        from affine import Affine
        with np.load(path, allow_pickle=False) as d:
            self.a = {k: d[k] for k in d.files if k != "meta_json"}
            self.meta = json.loads(str(d["meta_json"]))
        m = self.meta
        self.path = path
        self.transform = Affine(*m["transform"])
        self.nrows, self.ncols = int(m["nrows"]), int(m["ncols"])
        self.times_s = self.a["times_s"]

    def to_2d(self, values, fill=np.nan):
        out = np.full((self.nrows, self.ncols), fill, dtype=np.float64)
        sel = self.a["inside"]
        out[self.a["rows"][sel], self.a["cols"][sel]] = np.asarray(values)[sel]
        return out

    def depth(self, i=None):
        """Depth (n,) at the peak (i None) or at saved record i."""
        if i is None:
            return self.a["depth_max"].astype(np.float64)
        depth = np.zeros(self.a["z"].size)
        for k in range(int(self.meta["n_levels"])):
            cr = self.a[f"l{k}_cell_reach"]
            s = self.a[f"l{k}_stage_series"][i].astype(np.float64)
            st = np.where(cr >= 0, s[np.maximum(cr, 0)], 0.0)
            depth = np.maximum(depth, np.where(cr >= 0, st - self.a[f"l{k}_hand"], 0.0))
        return depth

    def flooded_area_series(self):
        if "l0_A" not in self.a or not len(self.times_s):
            return np.zeros(len(self.times_s))
        y, A, S = self.a["l0_y"], self.a["l0_A"], self.a["l0_stage_series"]
        tot = np.zeros(S.shape[0])
        for r in range(A.shape[0]):
            tot += np.interp(S[:, r], y, A[r])
        return tot / 1e6


def flood_model_path(source):
    """flood_model.npz from a run result dict, a Config, an OUTPUT_DIR, the
    inundation folder or the file itself."""
    if isinstance(source, dict):
        path = source.get("inundation_dir") or os.path.join(
            os.path.dirname(source["hydrograph_csv"]), "inundation")
    elif hasattr(source, "OUTPUT_DIR"):
        path = os.path.join(source.OUTPUT_DIR, "inundation")
    else:
        path = str(source)
    if os.path.isdir(path):
        sub = os.path.join(path, "inundation", "flood_model.npz")
        path = sub if os.path.isfile(sub) else os.path.join(path, "flood_model.npz")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No flood maps found at {path}. Run the model with "
                                "INUNDATION_MAP: true (or the 'inundation' stage).")
    return path
