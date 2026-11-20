# -*- coding: utf-8 -*-
"""
open_dem.py
===========
Download a DEM without any account: the Copernicus GLO-30 / GLO-90 global
elevation model, kept as open files on Amazon's open-data service.

The files are 1° × 1° tiles read straight over the internet (only the part
inside the requested box is fetched), joined, and reprojected to the model
grid.  Tiles over the open sea do not exist and are skipped.  A few countries'
30 m tiles are not public; the 90 m set has them.

It is a surface model: it includes the height of trees and buildings.
Credit: © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018,
provided under COPERNICUS by the European Union and ESA; all rights reserved.
"""

import math
import os

ATTRIBUTION = ("Copernicus DEM © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH "
               "2014-2018, provided under COPERNICUS by the European Union and ESA")

#: catalogue key → (bucket, arc-second code in the tile name, native resolution m)
_SETS = {
    "glo30_open": ("copernicus-dem-30m", "10", 30.0),
    "glo90_open": ("copernicus-dem-90m", "30", 90.0),
}


def tile_url(dataset, lat, lon):
    """HTTPS address of the 1° tile whose south-west corner is (*lat*, *lon*)."""
    bucket, code, _res = _SETS[dataset]
    ns = f"{'N' if lat >= 0 else 'S'}{abs(int(lat)):02d}_00"
    ew = f"{'E' if lon >= 0 else 'W'}{abs(int(lon)):03d}_00"
    name = f"Copernicus_DSM_COG_{code}_{ns}_{ew}_DEM"
    return f"https://{bucket}.s3.amazonaws.com/{name}/{name}.tif"


def download_open_dem(bbox_wgs84, target_crs_epsg, output_path, scale_m=None,
                      dataset="glo30_open", log=print):
    """
    Download the Copernicus DEM for *bbox_wgs84* (west, south, east, north) and
    write it in *target_crs_epsg* at *scale_m* metres (default: the native 30
    or 90 m).  Reuses *output_path* if it exists.  Returns the path.
    """
    import numpy as np
    import rasterio
    from rasterio.merge import merge
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject, transform_bounds
    from rasterio.windows import from_bounds

    if os.path.isfile(output_path):
        log(f"  DEM            |  reusing {output_path}")
        return output_path
    if dataset not in _SETS:
        raise ValueError(f"'{dataset}' is not an open DEM set; use one of {', '.join(_SETS)}.")
    native = _SETS[dataset][2]
    scale_m = float(scale_m or native)
    west, south, east, north = (float(v) for v in bbox_wgs84)
    if not (west < east and south < north):
        raise ValueError("DEM_BOUNDS_WGS84 must be (west, south, east, north) with "
                         "west < east and south < north.")
    n_tiles = (math.floor(east) - math.floor(west) + 1) * (math.floor(north) - math.floor(south) + 1)
    if n_tiles > 64:
        raise ValueError(f"The box covers {n_tiles} one-degree tiles; that is too large to "
                         "download this way. Use a smaller box, or the 90 m set.")

    # The model grid is a rectangle in the target projection, slightly wider
    # than the lon/lat box at its corners: read a margin so it is filled.
    box = (west, south, east, north)
    pad_x, pad_y = 0.05 * (east - west) + 0.01, 0.05 * (north - south) + 0.01
    west, east = max(west - pad_x, -180.0), min(east + pad_x, 180.0)
    south, north = max(south - pad_y, -90.0), min(north + pad_y, 90.0)

    pieces, missing = [], []
    env = rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                       CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                       GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2")
    with env:
        for lat in range(math.floor(south), math.floor(north) + 1):
            for lon in range(math.floor(west), math.floor(east) + 1):
                url = tile_url(dataset, lat, lon)
                try:
                    with rasterio.open(url) as src:
                        win = from_bounds(max(west, src.bounds.left), max(south, src.bounds.bottom),
                                          min(east, src.bounds.right), min(north, src.bounds.top),
                                          src.transform).round_offsets().round_lengths()
                        if win.width < 1 or win.height < 1:
                            continue
                        data = src.read(1, window=win).astype("float32")
                        if src.nodata is not None:
                            data[data == src.nodata] = np.nan
                        pieces.append((data, src.window_transform(win), src.crs))
                except rasterio.errors.RasterioIOError:
                    missing.append(f"{'N' if lat >= 0 else 'S'}{abs(lat):02d} "
                                   f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}")
    if not pieces:
        raise RuntimeError(
            f"No {dataset} tile could be read for this box ({', '.join(missing) or 'none tried'}). "
            "Either it is open sea, the internet connection is down, or (for the 30 m set) "
            "the country's tiles are not public: try DEM_SOURCE='glo90_open'.")
    if missing:
        log(f"  DEM            |  no tile for {', '.join(missing)} (open sea, or not public)")

    # Join the tiles on the geographic grid, then reproject to the model grid.
    from rasterio.io import MemoryFile
    mems, sets = [], []
    try:
        for data, tr, crs in pieces:
            mem = MemoryFile()
            ds = mem.open(driver="GTiff", height=data.shape[0], width=data.shape[1], count=1,
                          dtype="float32", crs=crs, transform=tr, nodata=float("nan"))
            ds.write(data, 1)
            mems.append(mem)
            sets.append(ds)
        mosaic, mtr = merge(sets, nodata=float("nan"))
        src_crs = sets[0].crs
    finally:
        for ds in sets:
            ds.close()
        for mem in mems:
            mem.close()
    mosaic = mosaic[0]

    left, bottom, right, top = transform_bounds("EPSG:4326", target_crs_epsg,
                                                *box, densify_pts=21)
    width = max(1, int(round((right - left) / scale_m)))
    height = max(1, int(round((top - bottom) / scale_m)))
    dst_tr = from_origin(left, top, scale_m, scale_m)
    out = np.full((height, width), np.nan, dtype="float32")
    reproject(mosaic, out, src_transform=mtr, src_crs=src_crs, src_nodata=float("nan"),
              dst_transform=dst_tr, dst_crs=target_crs_epsg, dst_nodata=float("nan"),
              resampling=Resampling.average if scale_m > 1.5 * native else Resampling.bilinear)
    nodata = -9999.0
    out = np.where(np.isfinite(out), out, nodata).astype("float32")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    with rasterio.open(output_path, "w", driver="GTiff", height=height, width=width, count=1,
                       dtype="float32", crs=target_crs_epsg, transform=dst_tr, nodata=nodata,
                       compress="deflate") as dst:
        dst.write(out, 1)
        dst.update_tags(SOURCE=dataset, ATTRIBUTION=ATTRIBUTION)
    log(f"  DEM            |  {dataset}: {width} × {height} cells at {scale_m:g} m → {output_path}")
    log(f"                 |  {ATTRIBUTION}")
    return output_path


def fetch_dem(bbox_wgs84, target_crs_epsg, output_path, scale_m=None, dataset="nasadem",
              project=None, log=print):
    """
    Download catalogue DEM *dataset*, from wherever it lives: the open sets
    need no account, the others come from Google Earth Engine.  Returns the
    path, or None when an Earth Engine download could not be made.
    """
    from ..gee.dem_catalog import needs_earth_engine
    if not needs_earth_engine(dataset):
        return download_open_dem(bbox_wgs84, target_crs_epsg, output_path, scale_m=scale_m,
                                 dataset=str(dataset).strip().lower(), log=log)
    from ..gee.dem_gee import download_dem
    return download_dem(bbox_wgs84=bbox_wgs84, target_crs_epsg=target_crs_epsg,
                        output_path=output_path, scale_m=scale_m, project=project,
                        dataset=dataset)
