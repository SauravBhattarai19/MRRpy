# 1 Terrain

The terrain step turns a digital elevation model (DEM) into the grid the model
runs on. It decides **which elevation data** to use, **which area** to model and
**where results go**. It is the `process_dem` stage of a run.

!!! info "Where to set it"
    Notebook form: step **1 Terrain** · Wizard: part **1 Basin, terrain and
    results folder** · QGIS: tab **1 · DEM & Watershed**.

What the stage does, in order:

1. **Get the DEM**: read your file, or download one from Google Earth Engine.
2. **Reproject** it to the projection of [2 Coordinate system](coordinate-system.md).
3. **Condition** it: remove pits and flats so water can always flow downhill.
4. **Flow directions (D8)**: each cell drains to the lowest of its 8 neighbours.
   The number of cells that drain through each cell is its **flow accumulation**.
5. **Choose the area**: delineate the watershed above the outlet, or keep the
   whole DEM.

## 1.1 Elevation data (DEM)

You either **give a DEM file** or **download one**.

**A DEM file** (`DEM_PATH`) is any GeoTIFF of ground elevation in metres, in any
projection. MRRpy reprojects it for you. The DEM's pixel size becomes the model's
cell size, so it sets both the detail and the run time: halving the cell size
gives four times as many cells and, for the explicit routing methods, also
smaller time steps. **90 m is a good size for basins of a few hundred to a few
thousand km²**; use 30 m or finer for small or urban areas.

**A download** happens when `DEM_PATH` is empty and `DEM_BOUNDS_WGS84` is set. MRRpy
fetches the area from Google Earth Engine, averages it to `DEM_SCALE_M` if you set
one, and saves it as `raw_dem_gee.tif` in the results folder. A second run with
the same settings reuses that file. Make the box a little larger than the basin:
anything that drains into your outlet must be inside it. Downloading needs an
Earth Engine sign-in (see [Google Earth Engine](earth-engine.md)).

The datasets you can download (`MRRpy list-dems` prints the same list):

| `DEM_SOURCE` | Dataset | Pixel | Coverage | Notes |
|---|---|---|---|---|
| `nasadem` (default) | NASADEM, void-filled SRTM | ~30 m | 56°S–60°N | good all-round choice |
| `srtm` | SRTM GL1 v3 | ~30 m | 56°S–60°N | not void-filled; for reproducing older studies |
| `merit` | MERIT DEM | ~92 m | 60°S–90°N | errors and tree bias removed; good for flow paths at 90 m |
| `alos` | ALOS World 3D (AW3D30) | ~30 m | 82°S–82°N | surface model: includes trees and buildings |
| `copernicus_glo30` | Copernicus DEM GLO-30 | ~30 m | global | surface model: includes trees and buildings |
| `fabdem` | FABDEM | ~30 m | 60°S–80°N | Copernicus with trees and buildings removed: bare earth, good for floodplains |
| `usgs_3dep_1m` | USGS 3DEP lidar | ~1 m | United States, patchy | for small US basins; the area must have been surveyed |
| `gmted2010` | GMTED2010 | ~232 m | near-global | coarse; last resort or very large areas |

!!! tip "Bare earth or surface?"
    Water flows on the ground, not on tree tops. A **surface model** (`alos`,
    `copernicus_glo30`) includes trees and buildings and can create false dams
    in forests and cities. Prefer a bare-earth DEM (`nasadem`, `fabdem`, `merit`)
    for routing.

<!-- settings: DEM_PATH DEM_BOUNDS_WGS84 DEM_SOURCE DEM_SCALE_M -->

## 1.2 Area to model

**The watershed** (default) is everything that drains to one outlet point,
`OUTPUT_POINT`. MRRpy moves the point to the nearest river cell (the 1 % of cells
with the largest flow accumulation) before tracing the basin upstream, so a point
a few cells off the river still works. The outlet hydrograph is reported at that
cell. Give the point as **latitude, longitude**, in that order.

**The whole DEM** routes every valid cell of the DEM, with no outlet. Use it to
see how water moves over a whole area, such as a city or a valley with several
rivers. Water leaves wherever it flows off the edge of the DEM or into a no-data
hole. Because nothing outside the DEM is modelled, make the DEM cover the uphill
land that drains into your area. In a whole-DEM run:

- `hydrograph.csv` reports `Q_m3s` at the **main exit** (where the largest river
  leaves the DEM; the log prints where it is) and adds `Q_total_outflow_m3s`, all
  water leaving the DEM.
- `watershed.tif` and `watershed.geojson` keep their names but hold the whole
  modelled area, so everything that reads them works as usual.

<!-- settings: MODEL_AREA OUTPUT_POINT -->

## 1.3 Results folder

Every file of a run is written to `OUTPUT_DIR`; it is created if it doesn't exist.
Downloads (DEM, satellite rain, soil maps) are cached there too, so re-running into
the same folder skips them. Use a new folder for each scenario you want to keep.
A relative path is relative to the folder you run MRRpy from.

Files written by the terrain step:

| File | What it is |
|---|---|
| `raw_dem_gee.tif` | the downloaded DEM (download only) |
| `reprojected_dem.tif` | the DEM in the model projection |
| `conditioned_dem.tif`, `filled_dem.tif`, `inflated_dem.tif` | the DEM after pit and flat removal |
| `flow_direction.tif`, `flow_accumulation.tif` | D8 flow directions and upstream cell counts |
| `clipped_dem.tif`, `clipped_flow_accumulation.tif` | the same, cut to the modelled area (what routing reads) |
| `watershed.tif`, `watershed.geojson` | the modelled area as a raster and an outline |
| `streams.geojson` | the river network, for picking an outlet on a map |

<!-- settings: OUTPUT_DIR -->

## 1.4 Terrain processing (advanced)

A raw DEM has **pits** (cells lower than all neighbours) and **flats** (areas of
equal height, such as lakes and valley floors). Water can't leave either, so they
are removed before flow directions are traced. `DEM_CONDITIONING` chooses how:

- **`fill`** raises every pit to the level where it spills over. It is the
  classic method, but in a deep gorge blocked by one bad pixel it fills a long
  "lake" behind it.
- **`carve`** lowers a path through the blocking cells instead (least-cost
  carving, Yamazaki et al. 2012). The landscape changes far less.
- **`carve_spread`** carves, then gives the remaining flats a gentle slope of at
  least `MIN_SLOPE` along the flow paths, keeping the relief of terraces. This is
  the default with `pyflwdir` and works best for routing.

`DELINEATION_ENGINE` picks the library that traces the flow. **`pyflwdir`** (the
default) uses priority-flood filling and handles large flat lakes and reservoirs.
**`pysheds`** was the original engine; with it, results stay identical to older
runs. A **lake mask** (`DEM_LAKE_MASK`) keeps real lakes and reservoirs flat
during conditioning, so their storage is kept.

<!-- settings: DELINEATION_ENGINE DEM_CONDITIONING DEM_LAKE_MASK CELL_SIZE -->

## Try it

- [Example 1 – Your first run](../examples/first-run.md): a DEM file and an outlet.
- [Example 2 – Download a DEM](../examples/download-dem.md): no DEM needed.
- [Example 10 – The whole DEM and flood maps](../examples/whole-dem.md).
