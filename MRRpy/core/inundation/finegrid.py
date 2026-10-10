# -*- coding: utf-8 -*-
"""
finegrid.py — flood maps on a finer DEM than the routing grid.

The routing (and its discharge) stays on the model grid; only the flood maps
are drawn on a finer DEM, e.g. FABDEM at 30 m when the model ran at 90 m, or
a local LiDAR file.  Steps:

1. Decide which DEM to use (``resolve_inundation_dem``): ``auto`` takes the
   run's own Earth Engine dataset at its native resolution when the model grid
   is coarser, else keeps the model grid.
2. Get that DEM over the map area (or the modelled area) plus a 3 km margin
   (cached in ``inundation/fine/``) and trace flow on it by least-cost search
   (``network.least_cost_d8``), which keeps rivers in their real channels.
3. Rivers that enter the area from outside get their upstream area added where
   they enter, so every fine river cell knows its true drainage area.
4. Each fine river cell takes the discharge of the routed river cell that is
   close by and drains about the same area (within 1.5×), scaled by the area
   ratio; cells without such a match take the specific discharge of the
   nearest matched river cell downstream (else they get no flow).
"""

import json
import os

import numpy as np

from . import network as N
from .mapping import FloodGrid

BUFFER_M = 3000.0
MAX_CELLS = 30_000_000
_MAX_RATIO = 1.5

try:
    from numba import njit as _njit
except Exception:                                 # pragma: no cover
    def _njit(*a, **k):
        return (lambda f: f) if not (a and callable(a[0])) else a[0]


def _from_gee(cfg):
    """Was the run's DEM downloaded from Earth Engine (DEM_BOUNDS_WGS84)?"""
    path = getattr(cfg, "DEM_PATH", "") or ""
    return bool(getattr(cfg, "DEM_BOUNDS_WGS84", None)) and (
        not path or os.path.basename(path) == "raw_dem_gee.tif")


def resolve_inundation_dem(cfg, meta):
    """
    Which DEM the flood maps use → (kind, dataset_or_path, scale_m, reason) with
    kind 'model' (the routing grid), 'download' (an Earth Engine dataset) or
    'file' (a local GeoTIFF).
    """
    from ...gee.dem_catalog import DEM_CATALOG
    choice = str(getattr(cfg, "INUNDATION_DEM", "auto") or "auto")
    scale = getattr(cfg, "INUNDATION_DEM_SCALE_M", None)
    cell = float(meta["cell_size"])
    if choice == "model_grid":
        return "model", None, cell, "INUNDATION_DEM is model_grid"
    if choice == "file":
        return "file", getattr(cfg, "INUNDATION_DEM_PATH", None), None, "INUNDATION_DEM_PATH"
    if choice in DEM_CATALOG:
        s = float(scale or DEM_CATALOG[choice]["resolution_m"])
        return "download", choice, s, f"INUNDATION_DEM is {choice}"
    # auto
    if _from_gee(cfg):
        src = str(getattr(cfg, "DEM_SOURCE", "nasadem"))
        native = float(scale or DEM_CATALOG.get(src, {}).get("resolution_m", cell))
        if cell > 1.5 * native:
            return ("download", src, native,
                    f"the run used {src} at {cell:g} m; it exists at {native:g} m")
        return "model", None, cell, f"the run already uses {src} at its finest resolution"
    return "model", None, cell, "the run's DEM is a local file (set INUNDATION_DEM_PATH for a finer one)"


def _extent(cfg, arrays, meta):
    """(xmin, ymin, xmax, ymax) in the grid CRS: map area or modelled area, + margin."""
    from affine import Affine
    area = getattr(cfg, "INUNDATION_AREA", None)
    if area:
        from rasterio.warp import transform_bounds
        x0, y0, x1, y1 = transform_bounds("EPSG:4326", meta["crs"], *[float(v) for v in area],
                                          densify_pts=21)
    else:
        tr = Affine(*meta["transform"])
        r, c = arrays["s_rows"], arrays["s_cols"]
        x0, y1 = tr * (int(c.min()), int(r.min()))
        x1, y0 = tr * (int(c.max()) + 1, int(r.max()) + 1)
    return (x0 - BUFFER_M, y0 - BUFFER_M, x1 + BUFFER_M, y1 + BUFFER_M)


def _fine_dem(cfg, meta, kind, what, scale, ext, fine_dir, log):
    """Path of the fine DEM over the extent (downloaded, or reprojected and
    cropped from a file), cached in *fine_dir*."""
    import rasterio
    from rasterio.windows import from_bounds
    from ..dem_processing import reproject_dem

    key = dict(kind=kind, what=str(what), scale=scale, extent=[round(v, 1) for v in ext],
               mtime=os.path.getmtime(what) if kind == "file" else None)
    key_path = os.path.join(fine_dir, "source.json")
    crop = os.path.join(fine_dir, "dem_area.tif")
    if os.path.isfile(crop) and os.path.isfile(key_path):
        with open(key_path) as f:
            if json.load(f) == key:
                log(f"  Flood maps     |  reusing the fine DEM in {fine_dir}")
                return crop
    os.makedirs(fine_dir, exist_ok=True)
    if kind == "download":
        from rasterio.warp import transform_bounds
        from ...gee.dem_gee import download_dem
        bbox = transform_bounds(meta["crs"], "EPSG:4326", *ext, densify_pts=21)
        log(f"  Flood maps     |  downloading {what} at {scale:g} m from Earth Engine …")
        raw = download_dem(bbox_wgs84=bbox, target_crs_epsg=meta["crs"],
                           output_path=os.path.join(fine_dir, "raw_dem.tif"), scale_m=scale,
                           project=getattr(cfg, "GEE_PROJECT", None), dataset=what)
        if not raw:
            raise RuntimeError(f"the {what} download from Earth Engine failed")
    else:
        if not what or not os.path.isfile(what):
            raise FileNotFoundError(f"INUNDATION_DEM_PATH not found: {what}")
        raw = reproject_dem(what, os.path.join(fine_dir, "raw_dem.tif"), meta["crs"])
    with rasterio.open(raw) as src:
        win = from_bounds(*ext, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        if win.width * win.height > MAX_CELLS:
            raise RuntimeError(f"the fine DEM would have {win.width * win.height:,} cells "
                               f"(limit {MAX_CELLS:,}); set a smaller INUNDATION_AREA or a "
                               "coarser INUNDATION_DEM_SCALE_M")
        data = src.read(1, window=win, masked=True).astype("float32").filled(-9999.0)
        prof = src.profile.copy()
        prof.update(height=data.shape[0], width=data.shape[1], dtype="float32",
                    nodata=-9999.0, transform=src.window_transform(win))
    with rasterio.open(crop, "w", **prof) as dst:
        dst.write(data, 1)
    with open(key_path, "w") as f:
        json.dump(key, f)
    return crop


@_njit(cache=True)
def _inherit(order, ds, drains, src):
    """Unmatched river cells take the match of the matched river cell
    downstream of them.  (Never from upstream: cells along a cropped DEM's
    edge collect flow along the edge and must not get a river's discharge.)"""
    for k in range(order.shape[0]):                          # outlets first
        i = order[k]
        if drains[i] and src[i] < 0:
            d = ds[i]
            if d >= 0 and drains[d] and src[d] >= 0:
                src[i] = src[d]
    return src


def fine_flood_grid(cfg, arrays, meta, log=print):
    """FloodGrid on the finer DEM, or (None, reason) to keep the model grid."""
    kind, what, scale, reason = resolve_inundation_dem(cfg, meta)
    if kind == "model":
        return None, reason
    fine_dir = os.path.join(getattr(cfg, "OUTPUT_DIR", "output/"), "inundation", "fine")
    ext = _extent(cfg, arrays, meta)
    try:
        dem_path = _fine_dem(cfg, meta, kind, what, scale, ext, fine_dir, log)
    except Exception as exc:                                 # offline, bad file, too big
        return None, f"could not prepare the finer DEM ({exc})"
    label = (f"{what}" if kind == "download" else os.path.basename(str(what)))
    return dem_flood_grid(cfg, arrays, meta, dem_path, label, reason, log, finer=True)


def model_dem_grid(cfg, arrays, meta, log=print):
    """FloodGrid on the run's own original DEM (reprojected_dem.tif, the
    model's cells) with least-cost flow paths, or (None, reason)."""
    import rasterio
    from rasterio.windows import from_bounds
    src_path = os.path.join(getattr(cfg, "OUTPUT_DIR", "output/"), "reprojected_dem.tif")
    if not os.path.isfile(src_path):
        return None, "no reprojected_dem.tif in the results folder"
    ext = _extent(cfg, arrays, meta)
    out_dir = os.path.join(getattr(cfg, "OUTPUT_DIR", "output/"), "inundation", "model_dem")
    os.makedirs(out_dir, exist_ok=True)
    crop = os.path.join(out_dir, "dem_area.tif")
    with rasterio.open(src_path) as src:
        if not np.isclose(abs(src.transform.a), float(meta["cell_size"]), rtol=1e-3):
            return None, "reprojected_dem.tif is not on the model grid"
        win = from_bounds(*ext, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        data = src.read(1, window=win, masked=True).astype("float32").filled(-9999.0)
        prof = src.profile.copy()
        prof.update(height=data.shape[0], width=data.shape[1], dtype="float32",
                    nodata=-9999.0, transform=src.window_transform(win))
    with rasterio.open(crop, "w", **prof) as dst:
        dst.write(data, 1)
    return dem_flood_grid(cfg, arrays, meta, crop, "model grid", "", log, finer=False)


def dem_flood_grid(cfg, arrays, meta, dem_path, label, reason, log=print, finer=True):
    """FloodGrid from a DEM file: least-cost flow paths, river cells by drainage
    area, discharge passed from the routed rivers (module docstring)."""
    import rasterio
    from affine import Affine
    from scipy.spatial import cKDTree
    from ..routing.hydraulics import compound_conveyance
    from ..routing.surface import bankfull_depth_continuity, reach_slope

    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float64)
        ftr = src.transform
        nd = src.nodata if src.nodata is not None else -9999.0
    cs = float(abs(ftr.a))
    if finer and cs >= 0.9 * float(meta["cell_size"]):
        return None, f"the finer DEM ({cs:g} m) is not finer than the model grid"
    # Flow paths by least-cost search on the original DEM: they follow the real
    # channels (filling would turn a valley floor behind a bridge or a DEM dam
    # into a flat that D8 crosses in straight lines, far from the river).
    valid = np.isfinite(dem) & (dem != nd)
    d8 = N.least_cost_d8(dem, valid)
    H, Wd = dem.shape
    ds_full, dist_full = N.downstream_from_d8(d8, valid, cs)
    idx = np.flatnonzero(valid.ravel())
    pos = np.full(H * Wd, -1, dtype=np.int64)
    pos[idx] = np.arange(idx.size)
    dsf = ds_full[idx]
    ds = np.where(dsf >= 0, pos[np.maximum(dsf, 0)], -1)
    dist = dist_full[idx]
    order = N.downstream_first_order(ds)
    rows, cols = np.divmod(idx, Wd)
    z_raw = dem.ravel()[idx]
    # Elevation lowered along every flow path until it never rises downstream
    # (carving only), for the reach slopes.
    z = N.river_bed_profile(order, ds, np.ones(idx.size, dtype=bool), z_raw)
    km2 = cs * cs / 1e6
    a_loc = N.upstream_area(order, ds, km2)

    # Routed river cells (coarse)
    ctr = Affine(*meta["transform"])
    ccs = float(meta["cell_size"])
    ri = arrays["river_idx"].astype(np.int64)
    c_rows, c_cols = arrays["s_rows"].astype(np.int64), arrays["s_cols"].astype(np.int64)
    cx, cy = ctr * (c_cols[ri] + 0.5, c_rows[ri] + 0.5)
    c_area = arrays["area_km2"][ri].astype(np.float64)

    def fine_pos(x, y):
        col = np.floor((np.asarray(x) - ftr.c) / ftr.a).astype(np.int64)
        row = np.floor((np.asarray(y) - ftr.f) / ftr.e).astype(np.int64)
        ok = (row >= 0) & (row < H) & (col >= 0) & (col < Wd)
        p = np.full(np.shape(x), -1, dtype=np.int64)
        p[ok] = pos[row[ok] * Wd + col[ok]]
        return p

    # Water entering from outside the fine DEM: every routed cell beyond its
    # edge that drains into it adds its drainage area where it enters (rivers
    # onto the fine river nearby, hillslopes at the entry point).
    extra = np.zeros(idx.size)
    x_lo, y_hi = ftr * (0, 0)
    x_hi, y_lo = ftr * (Wd, H)
    ax_, ay_ = ctr * (c_cols + 0.5, c_rows + 0.5)
    out_c = (ax_ < x_lo) | (ax_ > x_hi) | (ay_ < y_lo) | (ay_ > y_hi)
    c_ds_all = arrays["ds"].astype(np.int64)
    ent = np.flatnonzero(out_c & (c_ds_all >= 0))
    ent = ent[~out_c[c_ds_all[ent]]]
    n_ent_river = 0
    if ent.size:
        is_river_c = np.zeros(c_rows.size, dtype=bool)
        is_river_c[ri] = True
        dx, dy = ax_[c_ds_all[ent]], ay_[c_ds_all[ent]]
        ftree = cKDTree(np.column_stack(ftr * (cols + 0.5, rows + 0.5)))
        a_all = arrays["area_km2"].astype(np.float64)
        for k, x, y in zip(ent, dx, dy):
            if is_river_c[k]:
                cand = ftree.query_ball_point((x, y), r=2.0 * ccs)
                if cand:
                    extra[cand[int(np.argmax(a_loc[cand]))]] += a_all[k]
                    n_ent_river += 1
            else:
                dist_k, j = ftree.query((x, y), distance_upper_bound=1.5 * ccs)
                if np.isfinite(dist_k):
                    extra[j] += a_all[k]
    a_tot = N.upstream_area(order, ds, km2, extra) if ent.size else a_loc
    drains = a_tot >= float(meta["a_channel_km2"])

    # Discharge transfer: nearest routed river cell draining about the same area.
    tree = cKDTree(np.column_stack([cx, cy]))
    fd = np.flatnonzero(drains)
    fx, fy = ftr * (cols[fd] + 0.5, rows[fd] + 0.5)
    pts = np.column_stack([fx, fy])
    src = np.full(idx.size, -1, dtype=np.int64)
    for radius in (2.0, 5.0):
        todo = np.flatnonzero(src[fd] < 0)
        if not todo.size:
            break
        for k, cand in zip(todo, tree.query_ball_point(pts[todo], r=radius * ccs)):
            if cand:
                lr = np.abs(np.log(a_tot[fd[k]] / c_area[cand]))
                j = int(np.argmin(lr))
                if lr[j] <= np.log(_MAX_RATIO):
                    src[fd[k]] = cand[j]
    n_direct = int((src[fd] >= 0).sum())
    src = _inherit(order, ds, drains, src)
    n_inherit = int((src[fd] >= 0).sum()) - n_direct
    keep = drains & (src >= 0)
    drains = keep
    scale_f = np.where(keep, a_tot / c_area[np.maximum(src, 0)], 0.0)

    # Channel on the fine grid: same width and n, depth re-solved so the slot
    # still carries the routed cell's bankfull flow (scaled by area).
    s_floor = max(float(getattr(cfg, "MIN_SLOPE", 1e-4)), 1e-5)
    slope_loc = np.where(ds >= 0, (z - z[np.maximum(ds, 0)]) / dist, s_floor)
    s_reach = reach_slope(dict(ds_idx=ds, dem_1d=z, dist_1d=dist, cell_size=cs,
                               faccum_1d=a_tot, slope_1d=np.maximum(slope_loc, s_floor)),
                          getattr(cfg, "CHANNEL_SLOPE_REACH_M", 1000.0), s_floor)
    Wc = arrays["W"][ri].astype(np.float64)
    Dc = arrays["D"][ri].astype(np.float64)
    nc = arrays["n_ch"][ri].astype(np.float64)
    Sc = arrays["slope_reach"][ri].astype(np.float64)
    Cb, _ = compound_conveyance(Dc, nc, Wc, np.ones(ri.size, dtype=bool), Dc, Wc, np)
    q_bank_c = np.sqrt(Sc) * Cb
    m = np.maximum(src, 0)
    W = np.where(keep, Wc[m], 0.0)
    n_ch = np.where(keep, nc[m], float(cfg.MANNINGS_N))
    D = np.zeros(idx.size)
    need = keep & (W > 0) & (q_bank_c[m] > 0)
    if need.any() and meta.get("has_slot", True):
        D[need] = bankfull_depth_continuity(q_bank_c[m][need] * scale_f[need], W[need],
                                            s_reach[need], n_ch[need])
        D[need] = np.maximum(D[need], float(getattr(cfg, "CHANNEL_MIN_DEPTH_M", 0.1)))

    # Floodplain roughness and the modelled footprint, from the routing grid.
    from rasterio.warp import Resampling, reproject
    from scipy.ndimage import binary_dilation
    cgrid = np.full((meta["nrows"], meta["ncols"]), np.nan, dtype=np.float32)
    cgrid[c_rows, c_cols] = arrays["n_fp"]
    nfp2 = np.full((H, Wd), np.nan, dtype=np.float32)
    reproject(cgrid, nfp2, src_transform=ctr, src_crs=meta["crs"], dst_transform=ftr,
              dst_crs=meta["crs"], resampling=Resampling.nearest, src_nodata=np.nan,
              dst_nodata=np.nan)
    n_fp = nfp2.ravel()[idx].astype(np.float64)
    n_fp = np.where(np.isfinite(n_fp) & (n_fp > 0), n_fp, float(cfg.MANNINGS_N))
    act = np.zeros((meta["nrows"], meta["ncols"]), dtype=bool)
    act[c_rows, c_cols] = True
    act = binary_dilation(act, iterations=1)
    inv = ~ctr
    ccol, crow = inv * (ftr * (cols + 0.5, rows + 0.5))
    crow, ccol = np.floor(crow).astype(np.int64), np.floor(ccol).astype(np.int64)
    okc = (crow >= 0) & (crow < act.shape[0]) & (ccol >= 0) & (ccol < act.shape[1])
    inside = np.zeros(idx.size, dtype=bool)
    inside[okc] = act[crow[okc], ccol[okc]]

    # Statistics over the river cells inside the modelled area (rivers of
    # neighbouring basins in the margin get no flow, by design).
    fin = fd[inside[fd]]
    n_in = int(fin.size)
    with_flow = int((src[fin] >= 0).sum())
    ratio = scale_f[fin][src[fin] >= 0]
    match = dict(river_cells_in_area=n_in, with_routed_flow=with_flow,
                 took_flow_from_downstream=n_inherit,
                 without_flow=n_in - with_flow,
                 area_ratio_median=float(np.median(ratio)) if ratio.size else None,
                 area_ratio_p5_p95=[float(v) for v in np.percentile(ratio, [5, 95])]
                 if ratio.size else None,
                 entering_rivers=n_ent_river, reason=reason)
    pct = 100.0 * with_flow / max(n_in, 1)
    label = f"{label}, {cs:g} m"
    what_ = f"finer DEM: {label} ({reason})" if finer else f"{label}, original DEM"
    log(f"  Flood maps     |  {what_}; {pct:.0f} % of its {n_in:,} river cells in the "
        f"modelled area get routed flow (median drainage-area ratio "
        f"{match['area_ratio_median'] or float('nan'):.2f}).")
    grid = FloodGrid(
        label=label, fine=finer, nrows=H, ncols=Wd, transform=ftr, crs=meta["crs"],
        cell_size=cs, rows=rows.astype(np.int64), cols=cols.astype(np.int64), ds=ds,
        order=order, z=z, z_raw=z_raw, dist=dist, area_km2=a_tot, slope_reach=s_reach, n_fp=n_fp,
        river=drains, W=W, D=D, n_ch=n_ch, src=np.where(keep, src, -1), scale=scale_f,
        inside=inside, match=match)
    return grid, reason
