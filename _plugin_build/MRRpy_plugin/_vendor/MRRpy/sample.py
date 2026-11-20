# -*- coding: utf-8 -*-
"""
sample.py
=========
A basin to try MRRpy on before you have data of your own.

``sample_basin(folder)`` writes a small made-up valley (a DEM file) and returns
a ready ``Config`` for it; ``demo(folder)`` runs it and saves the hydrograph.
Nothing is downloaded.  ``demo(folder, real=True)`` instead downloads a real
90 m DEM of a small basin in the hills east of Kathmandu (open data, no
account) and runs that.

    MRRpy demo                 # on the command line
    import MRRpy; out = MRRpy.demo()
"""

import os

#: The real-basin demo: a box and an outlet on the Roshi Khola side, Nepal.
REAL_BOX = (85.48, 27.52, 85.66, 27.68)          # west, south, east, north
REAL_OUTLET = (27.575, 85.555)                   # latitude, longitude


def sample_dem(path, n=101, cell=90.0):
    """
    Write the made-up valley as a GeoTIFF and return (path, (lat, lon) of its
    outlet).  A main valley running south with side valleys on both flanks,
    *n* × *n* cells of *cell* metres, placed in UTM zone 45N.
    """
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    rows, cols = np.mgrid[0:n, 0:n].astype("float64")
    mid = (n - 1) / 2.0
    across = np.abs(cols - mid)
    down_valley = (n - 1 - rows) * 2.0                       # falls 2 m per cell southwards
    flanks = across * 3.5                                     # valley sides
    side_valleys = 12.0 * (1.0 - np.cos(rows * 2.0 * np.pi / 25.0)) * np.minimum(across / 10.0, 1.0)
    rng = np.random.default_rng(2024)
    dem = (500.0 + down_valley + flanks + side_valleys + rng.random((n, n)) * 0.3)
    transform = from_origin(330000.0, 3060000.0 + n * cell, cell, cell)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs="EPSG:32645", transform=transform,
                       nodata=-9999.0) as ds:
        ds.write(dem.astype("float32"), 1)
    x, y = transform * (int(mid) + 0.5, n - 3 + 0.5)
    lon, lat = Transformer.from_crs(32645, 4326, always_xy=True).transform(x, y)
    return path, (round(lat, 6), round(lon, 6))


def sample_basin(folder="mrrpy_demo", real=False):
    """
    A ready ``Config`` for the sample basin, with its files under *folder*.

    real=False : the made-up valley (written to ``<folder>/dem.tif``); works offline.
    real=True  : a real basin near Kathmandu; the DEM (Copernicus GLO-90, open
                 data, no account) is downloaded when the run starts.

    The storm is 25 mm/h for 2 hours, all of it running off, routed for 10 hours.
    """
    from .config import Config

    folder = os.path.abspath(folder)
    common = dict(OUTPUT_DIR=os.path.join(folder, "results"),
                  RAIN_INTENSITY_MM_HR=25.0, RAIN_DURATION_HOURS=2.0,
                  TOTAL_SIMULATION_TIME_HOURS=10.0, CHANNEL_MIN_AREA_KM2=2.0)
    if real:
        return Config(DEM_BOUNDS_WGS84=REAL_BOX, DEM_SOURCE="glo90_open",
                      OUTPUT_POINT=REAL_OUTLET, **common)
    dem, outlet = sample_dem(os.path.join(folder, "dem.tif"))
    return Config(DEM_PATH=dem, OUTPUT_POINT=outlet, **common)


def demo(folder="mrrpy_demo", real=False, quiet=True, log=print):
    """
    Run the sample basin from start to finish and return the ``RunResult``.

    Writes, under *folder*: ``run.yaml`` (the settings, to edit and re-run),
    ``results/`` (hydrograph.csv, the basin, the terrain, run.log) and
    ``results/hydrograph.png``.
    """
    from .interactive.render import save_yaml
    from .pipeline import run_pipeline

    cfg = sample_basin(folder, real=real)
    yaml_path = save_yaml(cfg, os.path.join(os.path.abspath(folder), "run.yaml"),
                          title="MRRpy demo — the sample basin", source="MRRpy demo")
    log("MRRpy demo: " + ("a real basin near Kathmandu (downloading a 90 m DEM, no account)"
                          if real else "a made-up valley of about 70 km² (nothing is downloaded)"))
    log("Storm: 25 mm/h for 2 hours, all of it running off. Running …")
    cfg.validate()
    out = run_pipeline(cfg, quiet=quiet)
    png = None
    try:
        import matplotlib
        matplotlib.use("Agg", force=False)
        from .plotting import plot_hydrograph
        fig, _ax = plot_hydrograph(out)
        png = os.path.join(cfg.OUTPUT_DIR, "hydrograph.png")
        fig.savefig(png, dpi=120, bbox_inches="tight")
        out["hydrograph_png"] = png
    except Exception as exc:                 # noqa: BLE001 — the run itself succeeded
        log(f"(The figure could not be drawn: {exc})")
    log("")
    log(out.summary())
    if png:
        log(f"Figure: {png}")
    log("")
    log("Next:")
    log(f"  look at the settings      {yaml_path}")
    log(f"  change them and run again MRRpy run -c {yaml_path}")
    log("  set up your own basin     MRRpy wizard")
    return out
