# -*- coding: utf-8 -*-
"""
snapshot.py — the routing network a run hands to the flood-mapping step.

At the end of a run with ``INUNDATION_MAP`` on, the router saves
``{OUTPUT_DIR}/inundation/network.npz``: the static D8 network on the routing
grid (order, elevation, river cells and their channel), plus the peak and the
time series of the discharge at every river cell.  Flood maps are made from
this file alone, so they can be redrawn (another area, a finer DEM) without
routing again: ``MRRpy run -c run.yaml --stages inundation``.
"""

import json
import os

import numpy as np

from ...utils import gpu_utils

SNAPSHOT_VERSION = 1


def snapshot_path(cfg):
    return os.path.join(getattr(cfg, "OUTPUT_DIR", "output/"), "inundation", "network.npz")


def river_mask(cfg, grid_data):
    """The river cells HAND drains to: the model's channel cells, or (with
    CHANNEL_ROUTING off) the same drainage-area rule."""
    chan = gpu_utils.to_cpu(grid_data["chan_mask_1d"]).astype(bool)
    if chan.any():
        return chan
    from ..routing.surface import channel_mask_1d
    return np.asarray(channel_mask_1d(cfg, grid_data), dtype=bool)


def build_snapshot(cfg, grid_data):
    """CPU copies of everything the mapping step needs (dict of arrays + meta)."""
    from ..io_utils import routing_grid_crs
    from ..routing.surface import channel_threshold_cells, reach_slope

    cpu = lambda k: gpu_utils.to_cpu(grid_data[k])
    n = int(grid_data["n_cells"])
    cell_size = float(grid_data["cell_size"])
    cell_area = float(grid_data["cell_area"])
    ds = cpu("ds_idx").astype(np.int64)
    z = gpu_utils.to_cpu(grid_data.get("dem_surface_1d", grid_data["dem_1d"])).astype(np.float64)
    dist = cpu("dist_1d").astype(np.float64)
    fa = cpu("faccum_1d").astype(np.float64)
    slope = cpu("slope_1d").astype(np.float64)
    river = river_mask(cfg, grid_data)
    chan = cpu("chan_mask_1d").astype(bool)

    s_floor = max(float(getattr(cfg, "MIN_SLOPE", 1e-4)), 1e-5)
    s_reach = reach_slope(dict(ds_idx=ds, dem_1d=z, dist_1d=dist, cell_size=cell_size,
                               faccum_1d=fa, slope_1d=slope),
                          getattr(cfg, "CHANNEL_SLOPE_REACH_M", 1000.0), s_floor)

    n_1d = gpu_utils.to_cpu(grid_data.get("n_1d", np.full(n, float(cfg.MANNINGS_N)))).astype(np.float64)
    n_fp_cfg = getattr(cfg, "MANNINGS_N_FLOODPLAIN", None)
    if n_fp_cfg is not None:
        n_fp = np.full(n, float(n_fp_cfg))
    else:
        n_fp = gpu_utils.to_cpu(grid_data.get("n_overland_1d", n_1d)).astype(np.float64)

    width = cpu("width_1d").astype(np.float64)
    W = np.where(chan, width, 0.0)                     # channel narrower than the cell
    bank = grid_data.get("bank_1d")
    D = gpu_utils.to_cpu(bank).astype(np.float64) if bank is not None else np.zeros(n)
    D = np.where(chan, D, 0.0)

    z_raw = _original_dem(cfg, grid_data, z)

    t = grid_data["transform"]
    meta = dict(
        version=SNAPSHOT_VERSION,
        nrows=int(grid_data["nrows"]), ncols=int(grid_data["ncols"]),
        transform=[t.a, t.b, t.c, t.d, t.e, t.f],
        crs=routing_grid_crs(cfg), cell_size=cell_size, cell_area=cell_area,
        a_channel_km2=float(channel_threshold_cells(cfg, grid_data)) * cell_area / 1e6,
        has_slot=bank is not None,
        model_area=str(getattr(cfg, "MODEL_AREA", "watershed")),
        output_interval_s=float(getattr(cfg, "OUTPUT_INTERVAL_SECONDS", None)
                                or cfg.TIME_STEP_SECONDS),
        hydrograph_csv=os.path.abspath(getattr(cfg, "HYDROGRAPH_CSV", "") or "") or None,
    )
    arrays = dict(
        s_rows=cpu("s_rows").astype(np.int32), s_cols=cpu("s_cols").astype(np.int32),
        ds=ds, z=z, z_raw=z_raw, dist=dist.astype(np.float32), area_km2=fa * cell_area / 1e6,
        slope_reach=s_reach.astype(np.float32), n_fp=n_fp.astype(np.float32),
        n_ch=n_1d.astype(np.float32), river=river, W=W.astype(np.float32),
        D=D.astype(np.float32),
    )
    return arrays, meta


def original_dem(output_dir, nrows, ncols, transform, s_rows, s_cols, z):
    """The DEM before hydrological conditioning (reprojected_dem.tif written by
    process_dem) at the routing cells; *z* where it is missing or off-grid."""
    from ..routing.terrain import _read_on_grid
    path = os.path.join(output_dir, "reprojected_dem.tif")
    if not os.path.isfile(path):
        return z
    try:
        raw, nodata = _read_on_grid(path, (int(nrows), int(ncols)), transform)
    except ValueError:                      # not on the routing grid's lattice
        return z
    v = raw[np.asarray(s_rows), np.asarray(s_cols)].astype(np.float64)
    bad = ~np.isfinite(v) | ((v == nodata) if nodata is not None else False)
    return np.where(bad, z, v)


def _original_dem(cfg, grid_data, z):
    return original_dem(getattr(cfg, "OUTPUT_DIR", "output/"), grid_data["nrows"],
                        grid_data["ncols"], grid_data["transform"],
                        gpu_utils.to_cpu(grid_data["s_rows"]),
                        gpu_utils.to_cpu(grid_data["s_cols"]), z)


def save_snapshot(path, arrays, meta):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    np.savez_compressed(path, meta_json=np.array(json.dumps(meta)), **arrays)
    return path


def load_snapshot(path):
    """(arrays dict, meta dict) from a network.npz written by a run."""
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"No flood-map data found at {path}. Run the routing stage with "
            "INUNDATION_MAP: true first; it saves the river network and its flows there.")
    with np.load(path, allow_pickle=False) as d:
        arrays = {k: d[k] for k in d.files if k != "meta_json"}
        meta = json.loads(str(d["meta_json"]))
    if meta.get("version") != SNAPSHOT_VERSION:
        raise ValueError(f"{path} was written by another MRRpy version; route the run again.")
    return arrays, meta
