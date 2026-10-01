# -*- coding: utf-8 -*-
"""Shared pytest fixtures (pytest only — the NN_*.py demo scripts don't use these)."""

import numpy as np
import pytest


@pytest.fixture(scope="session")
def tiny_basin(tmp_path_factory):
    """
    A 30×30 convergent-valley DEM (EPSG:32645, 30 m cells) and an outlet
    (lat, lon) near its south edge — small enough to delineate and route in
    about a second.  Returns (dem_path, (lat, lon)).
    """
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    d = tmp_path_factory.mktemp("tiny_basin")
    dem_p = str(d / "dem.tif")
    n, cell = 30, 30.0
    rows, cols = np.mgrid[0:n, 0:n]
    centre = (n - 1) / 2.0
    dem = ((n - 1 - rows) * 1.0 + np.abs(cols - centre) * 2.0 + 10.0).astype("float32")
    ox, oy = 330000.0, 3060000.0 + n * cell
    transform = from_origin(ox, oy, cell, cell)
    prof = dict(driver="GTiff", height=n, width=n, count=1, dtype="float32",
                crs="EPSG:32645", transform=transform, nodata=-9999.0)
    with rasterio.open(dem_p, "w", **prof) as ds:
        ds.write(dem, 1)
    orow, ocol = n - 2, int(round(centre))
    ex, ey = transform * (ocol + 0.5, orow + 0.5)
    lon, lat = Transformer.from_crs(32645, 4326, always_xy=True).transform(ex, ey)
    return dem_p, (lat, lon)
