# -*- coding: utf-8 -*-
"""
tests/test_nepal_descriptors.py
===============================
Catchment descriptors (MRRpy.nepal.descriptors): typed values and their
documented defaults, and the values measured from a delineated DEM — the
area bands below 3,000 m and 5,000 m are checked cell by cell on a synthetic
mountain valley that crosses both limits.

Run:  pytest tests/test_nepal_descriptors.py -v
"""

import os

import numpy as np
import pytest

from MRRpy import Config, run_pipeline
from MRRpy.nepal import CatchmentDescriptors, measure_catchment
from MRRpy.nepal.descriptors import delineated


# ── typed values ─────────────────────────────────────────────────────────────
def test_typed_defaults_and_assumptions():
    d = CatchmentDescriptors(area_km2=65)
    assert (d.a3000, d.a5000, d.snow) == (65.0, 65.0, 0.0)
    assert len(d.assumptions()) == 2
    d2 = CatchmentDescriptors(area_km2=500, area_below_3000_km2=300, area_below_5000_km2=450)
    assert d2.snow == 50.0 and d2.assumptions() == []
    d3 = CatchmentDescriptors(area_km2=500, snow_area_km2=20)
    assert d3.a5000 == 480.0


@pytest.mark.parametrize("kwargs, match", [
    (dict(area_km2=0), "more than 0"),
    (dict(area_km2=10, area_below_3000_km2=12), "cannot be larger"),
    (dict(area_km2=10, flow_length_km=-1), "negative"),
    (dict(area_km2=10, area_below_3000_km2=8, area_below_5000_km2=6), "cannot exceed"),
])
def test_typed_validation(kwargs, match):
    with pytest.raises(ValueError, match=match):
        CatchmentDescriptors(**kwargs)


def test_river_class():
    assert CatchmentDescriptors(area_km2=40, max_elevation_m=900).river_class()[0] == "III"
    assert CatchmentDescriptors(area_km2=400, max_elevation_m=2600).river_class()[0] == "II"
    assert CatchmentDescriptors(area_km2=4000, snow_area_km2=300).river_class()[0] == "I"
    assert CatchmentDescriptors(area_km2=40).river_class()[0] is None
    assert CatchmentDescriptors(area_km2=40, area_below_3000_km2=30).river_class()[0] == "II"


def test_dict_roundtrip_and_table():
    d = CatchmentDescriptors(area_km2=65, flow_length_km=15, flow_path_slope=0.015,
                             outlet_xy=(1.0, 2.0), name="X")
    again = CatchmentDescriptors.from_dict(d.to_dict())
    assert again == d
    with pytest.raises(ValueError, match="Unknown catchment value"):
        CatchmentDescriptors.from_dict({"area_km2": 3, "areaa": 1})
    t = d.table()
    assert "Longest flow path L" in list(t["quantity"]) and "X:" in d.summary()


# ── measured from a DEM ──────────────────────────────────────────────────────
def _delineate(dem_path, outlet, folder):
    cfg = Config(DEM_PATH=dem_path, OUTPUT_POINT=outlet, OUTPUT_DIR=str(folder),
                 TARGET_CRS_EPSG="EPSG:32645")
    cfg.update_output_paths()
    run_pipeline(cfg, stages=("process_dem",), on_log=lambda _s: None)
    return cfg


@pytest.fixture(scope="module")
def tiny_results(tiny_basin, tmp_path_factory):
    dem, outlet = tiny_basin
    return _delineate(dem, outlet, tmp_path_factory.mktemp("nepal_tiny"))


def test_measure_tiny_basin(tiny_results, tiny_basin):
    import rasterio
    cfg = tiny_results
    assert delineated(cfg.OUTPUT_DIR) and not delineated(os.path.dirname(cfg.OUTPUT_DIR))
    d = measure_catchment(cfg.OUTPUT_DIR, name="tiny")
    with rasterio.open(cfg.ROUTING_WATERSHED_MASK_PATH) as src:
        n_cells = int((src.read(1) > 0).sum())
    assert d.area_km2 == pytest.approx(n_cells * 900 / 1e6)
    assert d.a3000 == d.area_km2 and d.snow == 0.0            # all below 60 m
    assert d.flow_length_km > 0 and d.flow_path_slope > 0
    assert 0 < d.centroid_distance_km < d.flow_length_km
    assert d.river_class()[0] == "III" and d.source == "dem" and d.crs.endswith("32645")
    lat, lon = tiny_basin[1]
    assert d.outlet_lat == pytest.approx(lat, abs=5e-4) and d.outlet_lon == pytest.approx(lon, abs=5e-4)
    # a config file / Config works as the source too
    assert measure_catchment(cfg).area_km2 == d.area_km2


def test_measure_needs_a_delineated_catchment(tmp_path):
    with pytest.raises(FileNotFoundError, match="process_dem"):
        measure_catchment(tmp_path)


@pytest.fixture(scope="module")
def mountain(tmp_path_factory):
    """A steep valley rising from 2,800 m at the outlet to about 7,000 m (the side
    slopes are steeper than the valley floor, so flow converges on the outlet)."""
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin
    d = tmp_path_factory.mktemp("nepal_mountain")
    n, cell = 30, 30.0
    rows, cols = np.mgrid[0:n, 0:n]
    centre = (n - 1) / 2.0
    dem = (2800.0 + (n - 1 - rows) * 70.0 + np.abs(cols - centre) * 150.0).astype("float32")
    transform = from_origin(330000.0, 3060000.0 + n * cell, cell, cell)
    path = str(d / "dem.tif")
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32",
                       crs="EPSG:32645", transform=transform, nodata=-9999.0) as ds:
        ds.write(dem, 1)
    ex, ey = transform * (int(round(centre)) + 0.5, n - 2 + 0.5)
    lon, lat = Transformer.from_crs(32645, 4326, always_xy=True).transform(ex, ey)
    return _delineate(path, (lat, lon), d / "results")


def test_elevation_bands_cell_by_cell(mountain):
    import rasterio
    d = measure_catchment(mountain)
    with rasterio.open(mountain.ROUTING_DEM_PATH) as src:
        z = src.read(1).astype(float)
        shape, transform = src.shape, src.transform
    from MRRpy.core.routing.terrain import _read_on_grid
    ws, _nd = _read_on_grid(mountain.ROUTING_WATERSHED_MASK_PATH, shape, transform)
    zb = z[ws > 0]
    km2 = 900 / 1e6
    assert d.area_below_3000_km2 == pytest.approx((zb < 3000).sum() * km2)
    assert d.area_below_5000_km2 == pytest.approx((zb < 5000).sum() * km2)
    assert d.snow_area_km2 == pytest.approx((zb >= 5000).sum() * km2)
    assert 0 < d.a3000 < d.a5000 < d.area_km2                 # the valley crosses both limits
    assert d.max_elevation_m == pytest.approx(zb.max()) and d.river_class()[0] == "I"
