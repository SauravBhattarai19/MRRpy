# -*- coding: utf-8 -*-
"""
io_utils.py — shared raster I/O helpers.

Sampling and grid-alignment utilities used by the routing surface fields and
the runoff soil-parameter resolution.
"""

import os

import numpy as np
import rasterio




# ---------------------------------------------------------------------------
# 7.  Raster alignment
# ---------------------------------------------------------------------------

def align_raster_to_dem(src_path, dem_path, resampling='nearest', fill=0.0):
    """
    Reproject/resample *src_path* onto the routing DEM grid — matching its CRS,
    transform, height and width — so any GDAL-readable raster in any projection,
    resolution or extent can be used as model input.

    Cells that fall outside the source footprint, or that carry the source
    nodata value, are set to *fill* (default 0) rather than left uninitialised.
    If the source declares no CRS it is assumed to already be in the DEM's CRS.

    Returns a 2-D numpy array with the same (height, width) as the DEM.
    """
    from rasterio.warp import reproject, Resampling

    METHODS = {
        'nearest':  Resampling.nearest,
        'bilinear': Resampling.bilinear,
    }

    with rasterio.open(dem_path) as dem:
        dst_crs       = dem.crs
        dst_transform = dem.transform
        dst_shape     = (dem.height, dem.width)

    with rasterio.open(src_path) as src:
        # A NaN fill needs a float destination even if the source is integer.
        out_dtype = src.dtypes[0]
        try:
            if np.isnan(fill):
                out_dtype = 'float64'
        except TypeError:
            pass
        dst_array = np.full(dst_shape, fill, dtype=out_dtype)
        reproject(
            source=rasterio.band(src, 1),
            destination=dst_array,
            src_transform=src.transform,
            src_crs=src.crs or dst_crs,
            src_nodata=src.nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=fill,
            resampling=METHODS.get(resampling, Resampling.nearest),
        )
    return dst_array


def raster_band_1d(raster_path, s_rows, s_cols):
    """
    Read band 1 of a routing-grid-aligned raster into a per-cell (n_cells,)
    array (used for the SERVES deficit and the HiHydroSoil Ksat rasters).

    Returns float64 with nodata/out-of-grid cells set to NaN, or None if the
    raster grid does not match the routing grid.
    """
    with rasterio.open(raster_path) as src:
        arr2d  = src.read(1).astype(np.float64)
        nodata = src.nodata
    if nodata is not None:
        arr2d[arr2d == nodata] = np.nan

    _to_np = lambda a: a.get() if hasattr(a, 'get') else np.asarray(a)
    sr = _to_np(s_rows); sc = _to_np(s_cols)
    if sr.max() >= arr2d.shape[0] or sc.max() >= arr2d.shape[1]:
        return None
    return arr2d[sr, sc]


def raster_to_grid(src_path, dem_path, s_rows, s_cols, resampling='bilinear'):
    """
    Reproject/resample a single-band raster onto the routing DEM grid and sample
    the active cells, returning a (n_cells,) float64 array. Cells outside the
    source footprint or flagged as source nodata come back as NaN, so callers
    can substitute a per-cell fallback. Unlike ``raster_band_1d`` this accepts
    inputs in any CRS/resolution/extent (it aligns first).
    """
    arr2d = align_raster_to_dem(src_path, dem_path, resampling=resampling,
                                fill=np.nan)
    _to_np = lambda a: a.get() if hasattr(a, 'get') else np.asarray(a)
    sr = _to_np(s_rows); sc = _to_np(s_cols)
    return np.asarray(arr2d, dtype=np.float64)[sr, sc]


def routing_grid_crs(cfg):
    """
    CRS of the routing grid, read from the actual DEM file (``ROUTING_DEM_PATH``,
    else ``DEM_PATH``) so coordinate transforms match the grid the model runs on.
    Falls back to ``cfg.TARGET_CRS_EPSG`` when no DEM file is available yet.
    """
    for attr in ('ROUTING_DEM_PATH', 'DEM_PATH'):
        path = getattr(cfg, attr, '') or ''
        if path and os.path.exists(path):
            with rasterio.open(path) as src:
                if src.crs is not None:
                    return src.crs.to_string()
    return getattr(cfg, 'TARGET_CRS_EPSG', 'EPSG:4326')
