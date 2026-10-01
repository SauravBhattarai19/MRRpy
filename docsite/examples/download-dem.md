# 2 Download a DEM

**Goal:** start with no DEM at all. MRRpy downloads one from Google Earth Engine
for a box you choose, then delineates the basin.

**You need:** an Earth Engine sign-in and project
([setup](../manual/earth-engine.md)) and `pip install "MRRpy[gee]"`.

**Settings used:** [[DEM_PATH]] (empty), [[DEM_BOUNDS_WGS84]], [[DEM_SOURCE]],
[[DEM_SCALE_M]], [[GEE_PROJECT]], [[OUTPUT_POINT]].

The box must contain everything that drains to the outlet; make it a little
larger than you think. Here it covers the Kathmandu valley.

## Set it up

=== "Notebook form"

    1. **Terrain**: *Download a DEM for an area (Google Earth Engine)*. Type the
       area `85.05, 27.55, 85.55, 27.90` (west, south, east, north), or press
       **Pick the outlet or download area on a map** and draw a rectangle.
       *DEM dataset* `nasadem`; under *More options*, *Download resolution* `90`.
       An *Earth Engine* box appears: type your project ID and press **Connect to
       Earth Engine**.
    2. Outlet `27.632222, 85.293333`, results folder `results/download/`.
    3. **Coordinate system**: **Use the outlet's UTM zone**.
    4. Step **6**: *What to run* → *Delineate the watershed only*, then **Run the
       model**.

=== "Config file + CLI"

    ```yaml
    DEM_PATH: ''
    DEM_BOUNDS_WGS84: [85.05, 27.55, 85.55, 27.90]
    DEM_SOURCE: nasadem
    DEM_SCALE_M: 90.0
    GEE_PROJECT: ee-yourname
    OUTPUT_POINT: [27.632222, 85.293333]
    TARGET_CRS_EPSG: EPSG:32645
    OUTPUT_DIR: results/download/
    ```

    ```bash
    MRRpy list-dems                                   # the datasets you can choose
    MRRpy run -c download.yaml --stages process_dem   # download and delineate only
    ```

=== "Python"

    ```python
    import MRRpy
    from MRRpy import Config, run_pipeline, plot_watershed

    print(MRRpy.describe_available_dems())     # the datasets (no sign-in needed)

    cfg = Config(
        DEM_BOUNDS_WGS84=(85.05, 27.55, 85.55, 27.90),   # west, south, east, north
        DEM_SOURCE="nasadem",
        DEM_SCALE_M=90.0,
        GEE_PROJECT="ee-yourname",
        OUTPUT_POINT=(27.632222, 85.293333),
        TARGET_CRS_EPSG="EPSG:32645",
        OUTPUT_DIR="results/download/",
    )
    out = run_pipeline(cfg, stages=("process_dem",))
    plot_watershed(out)
    ```

    In Jupyter, `MRRpy.utils.notebook_map.pick_bounds_map()` draws the box on a
    map (see `notebooks/pick_dem_bounds.ipynb`).

=== "QGIS plugin"

    The DEM tab takes a DEM file. Download it once with any of the other three
    ways, then choose `results/download/raw_dem_gee.tif` as the *DEM file* and
    carry on as in [Example 1](first-run.md). QGIS's own plugins (for example
    *OpenTopography DEM Downloader*) also work.

## Results

![Watershed from a downloaded NASADEM](../assets/img/dem_gee_watershed.png)

The download is saved as `results/download/raw_dem_gee.tif`, and a second run
with the same settings reuses it. Large boxes are split into tiles and joined
automatically. Earth Engine averages the data to the pixel size you ask for: it
can make a DEM coarser, but not more detailed than the dataset.

## Other options to try

| Change | Setting | See |
|---|---|---|
| a hydrologically cleaned 90 m DEM | `DEM_SOURCE: merit` | [1.1](../manual/terrain.md#11-elevation-data-dem) |
| bare earth for a city or floodplain | `DEM_SOURCE: fabdem`, `DEM_SCALE_M: 30` | [1.1](../manual/terrain.md#11-elevation-data-dem) |
| the native resolution | `DEM_SCALE_M: null` | [1.1](../manual/terrain.md#11-elevation-data-dem) |
| no outlet: the whole box | `MODEL_AREA: whole_dem` | [Example 10](whole-dem.md) |
| keep a reservoir flat | `DEM_LAKE_MASK: lakes.tif` | [1.4](../manual/terrain.md#14-terrain-processing-advanced) |
