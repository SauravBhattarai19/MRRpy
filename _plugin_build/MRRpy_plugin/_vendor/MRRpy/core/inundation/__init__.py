# -*- coding: utf-8 -*-
"""
Flood depth and extent maps from the routed discharge.

A run with ``INUNDATION_MAP`` on records the discharge of every river cell and
the water entering each river cell from its side (recorder.py) and saves the
river network (snapshot.py).  ``make_flood_maps`` then draws the maps on the
run's original DEM or a finer one with least-cost flow paths (finegrid.py),
on the ground as it is (no channel cut below the DEM), by one of two methods
(``INUNDATION_METHOD``):

* ``hand`` — each reach's flow becomes a water level with a synthetic rating
  curve (rating.py) that is spread over the land below it (network.py,
  mapping.py).  Quick, for the whole river network.
* ``2d`` — the water is moved in two dimensions over one area, with the
  routed rivers flowing in (model2d.py, solver2d.py).  Slower, more exact:
  water spreads, ponds and backs up as it does on the ground.
"""

import os

from .snapshot import load_snapshot, snapshot_path


def make_flood_maps(cfg, log=print, out_dir=None, cache_dir=None):
    """
    Flood maps for a routed run → {name: path} (the 'inundation' stage).

    The maps go to *out_dir* (default ``{OUTPUT_DIR}/inundation``) and the DEM cut
    out for them is kept in *cache_dir* (default the same folder), so several
    areas can be drawn one after another from the same routed run, each with its
    own ``INUNDATION_AREA``, folder and cache.
    """
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
    grid, reason = fine_flood_grid(cfg, arrays, meta, log=log, cache_dir=cache_dir)
    if grid is None:
        if choice not in ("auto", "model_grid"):
            raise RuntimeError(f"Flood maps: INUNDATION_DEM '{choice}' could not be used — "
                               f"{reason}.")
        log(f"  Flood maps     |  model grid, {meta['cell_size']:g} m ({reason})")
        # The run's own original DEM with least-cost flow paths; the routing
        # network itself only when that DEM is not in the results folder.
        grid, why = model_dem_grid(cfg, arrays, meta, log=log, cache_dir=cache_dir)
        if grid is None:
            log(f"  Flood maps     |  using the routing network ({why})")
            grid = routing_flood_grid(arrays, meta)
    out_dir = out_dir or os.path.join(getattr(cfg, "OUTPUT_DIR", "output/"), "inundation")
    area = getattr(cfg, "INUNDATION_AREA", None)
    if str(getattr(cfg, "INUNDATION_METHOD", "hand") or "hand") == "2d":
        from .model2d import make_2d_flood_maps
        paths = make_2d_flood_maps(cfg, arrays, meta, grid, out_dir, log=log)
    else:
        paths = write_outputs(FloodModel(grid, arrays, meta), out_dir, area, log=log)
    if getattr(cfg, "INUNDATION_ANIMATION", True):
        from ...plotting import animate_inundation
        gif = animate_inundation(paths["flood_model"], area=area, log=log)
        if gif:
            paths["flood_animation"] = gif
    paths["inundation_dir"] = out_dir
    return paths
