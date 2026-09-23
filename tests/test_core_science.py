# -*- coding: utf-8 -*-
"""
tests/test_core_science.py
==========================
Pytest suite that exercises the scientific core of ``MRRpy`` without any
external data, Earth Engine access, or a GPU. It is fast (a few seconds),
deterministic, and safe to run in CI.

Coverage
--------
* Config round-trip (save -> load) and cross-field ``validate()``.
* Runoff generation:
    - the composable ``physical`` mechanisms partition exactly
      (impervious + Dunne + Horton == effective runoff, every step);
    - the SCS Curve Number generator never sheds more than it rains;
    - the built-in mechanism registry is populated.
* End-to-end pipeline on a small, self-generated synthetic DEM:
  ``process_dem`` (delineation) + ``routing`` for all three routing schemes,
  asserting valid, non-negative hydrographs and near-machine-precision
  mass-balance closure.

Run with::

    pytest tests/test_core_science.py -v
"""

import os

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer

from MRRpy import Config, run_pipeline
from MRRpy.core.runoff import RunoffEngine, MECHANISM_REGISTRY


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic fixtures
# ─────────────────────────────────────────────────────────────────────────────
_CHAIN_N = 8          # cells in the 1-D runoff-mechanism test grid
_CHAIN_CELL = 30.0    # m


@pytest.fixture(scope="module")
def chain_rasters(tmp_path_factory):
    """Two tiny (N×1) rasters on a common grid: a sloping DEM and an
    impervious-fraction map. Used only to satisfy ``Config`` path checks;
    the mechanism maths runs on the in-memory ``_chain_grid`` below."""
    d = tmp_path_factory.mktemp("chain")
    dem_p = str(d / "dem.tif")
    imp_p = str(d / "imperv.tif")
    transform = from_origin(0.0, _CHAIN_N * _CHAIN_CELL, _CHAIN_CELL, _CHAIN_CELL)
    prof = dict(driver="GTiff", height=_CHAIN_N, width=1, count=1, dtype="float32",
                crs="EPSG:32645", transform=transform, nodata=-9999.0)
    dem = np.linspace(100.0, 10.0, _CHAIN_N, dtype="float32").reshape(_CHAIN_N, 1)
    imp = np.full((_CHAIN_N, 1), 0.3, dtype="float32")
    for path, arr in ((dem_p, dem), (imp_p, imp)):
        with rasterio.open(path, "w", **prof) as ds:
            ds.write(arr, 1)
    return dem_p, imp_p


def _chain_grid():
    """Synthetic single-sandbox ``grid_data`` (8-cell downhill chain)."""
    return {
        "n_cells": _CHAIN_N, "nrows": _CHAIN_N, "ncols": 1,
        "s_rows": np.arange(_CHAIN_N), "s_cols": np.zeros(_CHAIN_N, dtype=int),
        "cell_area": _CHAIN_CELL * _CHAIN_CELL, "cell_size": _CHAIN_CELL,
        "slope_1d": np.full(_CHAIN_N, 0.01),
        "faccum_1d": np.arange(1, _CHAIN_N + 1, dtype=np.float64),   # outlet = last
        "dem": np.linspace(100.0, 10.0, _CHAIN_N, dtype=np.float64).reshape(_CHAIN_N, 1),
        "xp": np,
    }


@pytest.fixture(scope="module")
def valley_dem(tmp_path_factory):
    """A 40×40 convergent-valley DEM (drains south into a central channel) plus
    an (lat, lon) outlet near the south edge. Deterministic, so downstream
    delineation and routing are reproducible."""
    d = tmp_path_factory.mktemp("valley")
    dem_p = str(d / "dem.tif")
    n, cell = 40, 30.0
    rows, cols = np.mgrid[0:n, 0:n]
    center = (n - 1) / 2.0
    dem = ((n - 1 - rows) * 1.0 + np.abs(cols - center) * 2.0 + 10.0).astype("float32")
    epsg = 32615
    ox, oy = 500000.0, 4000000.0 + n * cell
    transform = from_origin(ox, oy, cell, cell)
    prof = dict(driver="GTiff", height=n, width=n, count=1, dtype="float32",
                crs=f"EPSG:{epsg}", transform=transform, nodata=-9999.0)
    with rasterio.open(dem_p, "w", **prof) as ds:
        ds.write(dem, 1)
    orow, ocol = n - 2, int(round(center))
    ex, ey = transform * (ocol + 0.5, orow + 0.5)
    lon, lat = Transformer.from_crs(epsg, 4326, always_xy=True).transform(ex, ey)
    return dem_p, (lat, lon)


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
def test_config_roundtrip_and_validate(tmp_path, valley_dem):
    dem_p, pt = valley_dem
    cfg = Config(DEM_PATH=dem_p, OUTPUT_POINT=pt, OUTPUT_DIR=str(tmp_path / "out"))
    cfg.update_output_paths()
    cfg.validate()   # must not raise

    yaml_p = str(tmp_path / "cfg.yaml")
    cfg.save(yaml_p)
    cfg2 = Config.from_file(yaml_p)
    assert cfg2.DEM_PATH == cfg.DEM_PATH
    assert tuple(cfg2.OUTPUT_POINT) == tuple(cfg.OUTPUT_POINT)


def test_enum_accepts_string_or_code():
    """Fixed-choice options normalise to their canonical string whether set by
    name (case-insensitive) or by integer code, and reject unknown values."""
    by_name = Config(DEM_PATH="x.tif", ROUTING_SCHEME="DIFFUSIVE")
    assert by_name.ROUTING_SCHEME == "diffusive"

    by_code = Config(DEM_PATH="x.tif", ROUTING_SCHEME=0)
    assert isinstance(by_code.ROUTING_SCHEME, str)
    assert by_code.ROUTING_SCHEME == Config(DEM_PATH="x.tif").ROUTING_SCHEME

    with pytest.raises((ValueError, AttributeError)):
        Config(DEM_PATH="x.tif", ROUTING_SCHEME="not_a_scheme")


# ─────────────────────────────────────────────────────────────────────────────
# Runoff generation
# ─────────────────────────────────────────────────────────────────────────────
def test_runoff_partition_invariant(chain_rasters):
    """imperv + Dunne + Horton rates sum EXACTLY to the effective runoff the
    engine returns, every step, for the full three-mechanism mix."""
    dem_p, imp_p = chain_rasters
    cfg = Config(DEM_PATH=dem_p, RUNOFF_SOURCE="physical",
                 RUNOFF_MECHANISMS=["impervious", "infiltration_excess", "saturation_excess"],
                 VSA_SD_SOURCE="manual", GA_SUCTION_SOURCE="scalar", GA_KSAT_SOURCE="scalar",
                 IMPERVIOUS_SOURCE="raster", IMPERVIOUS_RASTER_PATH=imp_p)
    cfg.ROUTING_DEM_PATH = dem_p
    eng = RunoffEngine(cfg, _chain_grid())

    rain = np.full(_CHAIN_N, 20.0 / 1000.0 / 3600.0)   # 20 mm/hr -> m/s
    dt = 300.0
    worst = 0.0
    for step in range(12):
        eff = np.asarray(eng.get_effective_1d(step * dt, rain), dtype=np.float64)
        imp = np.asarray(eng._impl._last_imperv_rate, dtype=np.float64)
        dun = np.asarray(eng._impl._last_dunne_rate, dtype=np.float64)
        hor = np.asarray(eng._impl._last_horton_rate, dtype=np.float64)
        worst = max(worst, float(np.max(np.abs((imp + dun + hor) - eff))))
        eng.update_state(rain, dt)
    assert worst < 1e-15


def test_scs_cn_never_exceeds_rainfall(chain_rasters):
    """Cumulative SCS-CN effective runoff is positive but never exceeds
    cumulative rainfall."""
    dem_p, _ = chain_rasters
    cfg = Config(DEM_PATH=dem_p, RUNOFF_SOURCE="scs_cn",
                 RUNOFF_CN_SOURCE="scalar", RUNOFF_CN=75)
    cfg.ROUTING_DEM_PATH = dem_p
    eng = RunoffEngine(cfg, _chain_grid())

    rain = np.full(_CHAIN_N, 30.0 / 1000.0 / 3600.0)   # 30 mm/hr -> m/s
    dt = 600.0
    cum_rain = cum_eff = 0.0
    for step in range(24):
        eff = np.asarray(eng.get_effective_1d(step * dt, rain), dtype=np.float64)
        cum_eff += float(eff[0]) * dt
        cum_rain += float(rain[0]) * dt
        eng.update_state(rain, dt)
    assert cum_eff > 0.0
    assert cum_eff <= cum_rain + 1e-12


def test_mechanism_registry_populated():
    for m in ("impervious", "infiltration_excess", "saturation_excess"):
        assert m in MECHANISM_REGISTRY


def test_raster_to_grid_aligns_foreign_crs_and_nodata(chain_rasters, tmp_path):
    """raster_to_grid (used for the deficit and Green-Ampt Ksat rasters)
    reprojects a foreign-CRS raster onto the model grid, and maps nodata to
    NaN so callers can fall back per cell."""
    import rasterio.warp
    from MRRpy.core.io_utils import raster_to_grid

    dem_p, _ = chain_rasters
    with rasterio.open(dem_p) as d:
        left, bottom, right, top = rasterio.warp.transform_bounds(
            d.crs, "EPSG:4326", *d.bounds)
    tr = from_origin(left, top, (right - left) / 3, (top - bottom) / 3)
    prof = dict(driver="GTiff", height=3, width=3, count=1, dtype="float32",
                crs="EPSG:4326", transform=tr, nodata=-9999.0)
    sr = np.arange(_CHAIN_N)
    sc = np.zeros(_CHAIN_N, dtype=int)

    # (a) constant foreign-CRS raster covering the DEM -> aligned constant.
    covered = str(tmp_path / "k_cov.tif")
    with rasterio.open(covered, "w", **prof) as ds:
        ds.write(np.full((3, 3), 7.0, dtype="float32"), 1)
    vals = raster_to_grid(covered, dem_p, sr, sc)
    assert np.all(np.isfinite(vals))
    assert np.allclose(vals, 7.0, atol=1e-4)

    # (b) all-nodata raster -> all NaN.
    nod = str(tmp_path / "k_nodata.tif")
    with rasterio.open(nod, "w", **prof) as ds:
        ds.write(np.full((3, 3), -9999.0, dtype="float32"), 1)
    vals2 = raster_to_grid(nod, dem_p, sr, sc)
    assert np.all(~np.isfinite(vals2))


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end pipeline (DEM -> watershed -> routed hydrograph)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("scheme", ["kinematic", "diffusive", "muskingum",
                                    "diffusive_implicit"])
def test_pipeline_conserves_mass(valley_dem, tmp_path, scheme):
    dem_p, pt = valley_dem
    cfg = Config(DEM_PATH=dem_p, OUTPUT_DIR=str(tmp_path / f"out_{scheme}"),
                 OUTPUT_POINT=pt, PRECIP_METHOD="uniform",
                 RAIN_INTENSITY_MM_HR=20.0, RAIN_DURATION_HOURS=1.0,
                 RUNOFF_SOURCE="none", TOTAL_SIMULATION_TIME_HOURS=3.0,
                 ADAPTIVE_TIMESTEP=True, ROUTING_SCHEME=scheme)
    cfg.update_output_paths()
    res = run_pipeline(cfg, stages=("process_dem", "routing"),
                       on_log=lambda m: None, on_progress=lambda p: None)

    for key in ("watershed_tif", "hydrograph_csv", "mass_balance_csv"):
        assert os.path.exists(res[key]), f"missing output: {key}"

    hg = res["hydrograph_df"]
    assert "Q_m3s" in hg.columns and len(hg) > 0
    assert (hg["Q_m3s"] >= 0).all()             # no negative discharge
    assert float(hg["Q_m3s"].max()) > 0.0        # the storm actually routed

    mb = pd.read_csv(res["mass_balance_csv"]).tail(1)
    assert abs(float(mb["rel_error"].iloc[0])) < 1e-6   # closes to ~machine precision


def test_raster_runoff_mode_reprojects(valley_dem, tmp_path):
    """A prescribed-runoff raster supplied in a DIFFERENT CRS (EPSG:4326) and a
    different resolution than the UTM model grid is reprojected onto the grid via
    align_raster_to_dem, drives the router with no rainfall, and conserves mass."""
    import rasterio.warp

    dem_p, pt = valley_dem
    out = str(tmp_path / "out")

    # 1) Delineate to produce the routing grid (clipped_dem.tif etc.).
    cfg = Config(DEM_PATH=dem_p, OUTPUT_DIR=out, OUTPUT_POINT=pt)
    cfg.update_output_paths()
    run_pipeline(cfg, stages=("process_dem",),
                 on_log=lambda m: None, on_progress=lambda p: None)

    # 2) Build a coarse EPSG:4326 runoff raster covering the DEM (constant 10 mm/hr).
    with rasterio.open(cfg.ROUTING_DEM_PATH) as d:
        left, bottom, right, top = rasterio.warp.transform_bounds(
            d.crs, "EPSG:4326", *d.bounds)
    nr = nc = 6
    tr = from_origin(left, top, (right - left) / nc, (top - bottom) / nr)
    val = 10.0 / 1000.0 / 3600.0    # 10 mm/hr -> m/s
    prof = dict(driver="GTiff", height=nr, width=nc, count=1, dtype="float32",
                crs="EPSG:4326", transform=tr, nodata=-9999.0)
    rr = tmp_path / "rr"
    rr.mkdir()
    frames = [str(rr / "r0.tif"), str(rr / "r1.tif")]
    for f in frames:
        with rasterio.open(f, "w", **prof) as ds:
            ds.write(np.full((nr, nc), val, dtype="float32"), 1)
    manifest = str(tmp_path / "runoff_manifest.csv")
    pd.DataFrame({"time_s": [0.0, 7200.0], "filepath": frames}).to_csv(manifest, index=False)

    # 3) Route with RUNOFF_SOURCE='raster' and NO rainfall — runoff comes only
    #    from the reprojected raster, reusing the grid delineated in step 1.
    cfg2 = Config(DEM_PATH=dem_p, OUTPUT_DIR=out, OUTPUT_POINT=pt,
                  PRECIP_METHOD="uniform", RAIN_INTENSITY_MM_HR=0.0,
                  RAIN_DURATION_HOURS=1.0, RUNOFF_SOURCE="raster",
                  RUNOFF_RASTER_MANIFEST=manifest,
                  TOTAL_SIMULATION_TIME_HOURS=2.0, ADAPTIVE_TIMESTEP=True)
    cfg2.update_output_paths()
    res = run_pipeline(cfg2, stages=("routing",),
                       on_log=lambda m: None, on_progress=lambda p: None)

    hg = res["hydrograph_df"]
    assert (hg["Q_m3s"] >= 0).all()
    assert float(hg["Q_m3s"].max()) > 0.0     # reprojected runoff actually routed
    mb = pd.read_csv(res["mass_balance_csv"]).tail(1)
    assert abs(float(mb["rel_error"].iloc[0])) < 1e-6


def test_inflow_boundary_pure_routing(valley_dem, tmp_path):
    """Pure downstream routing driven ONLY by a lat/lon inflow hydrograph (no
    rainfall). Exercises the boundary-condition path and the lat/lon->grid CRS
    transform (which now reads the CRS from the DEM file)."""
    dem_p, pt = valley_dem
    out = str(tmp_path / "out")

    cfg0 = Config(DEM_PATH=dem_p, OUTPUT_DIR=out, OUTPUT_POINT=pt)
    cfg0.update_output_paths()
    run_pipeline(cfg0, stages=("process_dem",),
                 on_log=lambda m: None, on_progress=lambda p: None)

    qcsv = str(tmp_path / "bc_q.csv")
    pd.DataFrame({"time_hr": [0.0, 0.5, 1.0, 2.0],
                  "Q_m3s":   [0.0, 5.0, 5.0, 0.0]}).to_csv(qcsv, index=False)

    lat, lon = pt
    cfg = Config(DEM_PATH=dem_p, OUTPUT_DIR=out, OUTPUT_POINT=pt,
                 PRECIP_METHOD="uniform", RAIN_INTENSITY_MM_HR=0.0,
                 RAIN_DURATION_HOURS=1.0, RUNOFF_SOURCE="none",
                 TOTAL_SIMULATION_TIME_HOURS=3.0, ADAPTIVE_TIMESTEP=True,
                 ROUTING_INFLOW_BC=[{"lat": lat, "lon": lon, "csv": qcsv,
                                     "snap_to_channel": True}])
    cfg.update_output_paths()
    res = run_pipeline(cfg, stages=("routing",),
                       on_log=lambda m: None, on_progress=lambda p: None)

    hg = res["hydrograph_df"]
    assert float(hg["Q_m3s"].max()) > 0.0     # injected hydrograph routed to outlet
    mb = pd.read_csv(res["mass_balance_csv"]).tail(1)
    assert abs(float(mb["rel_error"].iloc[0])) < 1e-6
