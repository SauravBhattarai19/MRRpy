# -*- coding: utf-8 -*-
"""
Flood depth and extent maps from the routed discharge (HAND method).

A run with ``INUNDATION_MAP`` on records the discharge of every river cell
(recorder.py) and saves the river network (snapshot.py); ``make_flood_maps``
then turns each reach's flow into a water level with a synthetic rating curve
(rating.py) and spreads it over the land below it (network.py, mapping.py),
on the run's original DEM or a finer one with least-cost flow paths
(finegrid.py).
"""

import os

from .snapshot import load_snapshot, snapshot_path


def make_flood_maps(cfg, log=print):
    """Flood maps for a routed run → {name: path} (the 'inundation' stage)."""
    from .finegrid import fine_flood_grid, model_dem_grid
    from .mapping import FloodModel, routing_flood_grid, write_outputs

    arrays, meta = load_snapshot(snapshot_path(cfg))
    if "z_raw" not in arrays:                    # snapshots saved before z_raw existed
        from affine import Affine
        from .snapshot import original_dem
        arrays["z_raw"] = original_dem(getattr(cfg, "OUTPUT_DIR", "output/"), meta["nrows"],
                                       meta["ncols"], Affine(*meta["transform"]),
                                       arrays["s_rows"], arrays["s_cols"], arrays["z"])
    choice = str(getattr(cfg, "INUNDATION_DEM", "auto") or "auto")
    grid, reason = fine_flood_grid(cfg, arrays, meta, log=log)
    if grid is None:
        if choice not in ("auto", "model_grid"):
            raise RuntimeError(f"Flood maps: INUNDATION_DEM '{choice}' could not be used — "
                               f"{reason}.")
        log(f"  Flood maps     |  model grid, {meta['cell_size']:g} m ({reason})")
        # The run's own original DEM with least-cost flow paths; the routing
        # network itself only when that DEM is not in the results folder.
        grid, why = model_dem_grid(cfg, arrays, meta, log=log)
        if grid is None:
            log(f"  Flood maps     |  using the routing network ({why})")
            grid = routing_flood_grid(arrays, meta)
    model = FloodModel(grid, arrays, meta,
                       reach_len_m=float(getattr(cfg, "INUNDATION_REACH_LENGTH_M", 1000.0)),
                       backwater=bool(getattr(cfg, "INUNDATION_BACKWATER", True)))
    out_dir = os.path.join(getattr(cfg, "OUTPUT_DIR", "output/"), "inundation")
    paths = write_outputs(model, out_dir, getattr(cfg, "INUNDATION_AREA", None), log=log)
    if getattr(cfg, "INUNDATION_ANIMATION", True):
        from ...plotting import animate_inundation
        gif = animate_inundation(paths["flood_model"], area=getattr(cfg, "INUNDATION_AREA", None),
                                 log=log)
        if gif:
            paths["flood_animation"] = gif
    paths["inundation_dir"] = out_dir
    return paths
