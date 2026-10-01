# Quickstart

From a DEM to a flood hydrograph in a few minutes. You need two things: a
**DEM** (a GeoTIFF of ground elevation covering your basin) and the **latitude
and longitude of the outlet**, the river point your basin drains to. No DEM?
MRRpy can [download one](../examples/download-dem.md).

Pick the way you like to work; all of them make the same run.

=== "Notebook form"

    ```bash
    pip install "MRRpy[notebook]"
    ```

    In Jupyter:

    ```python
    from MRRpy import ConfigForm
    form = ConfigForm()
    form
    ```

    Go through the six steps with **Next**: your DEM file and outlet, the map
    projection (one click), a design storm, the runoff and routing methods
    (the defaults are fine to start). In step 6 press **Check settings**, then
    **Run the model**. The form shows the peak flow, the water-balance check and
    the hydrograph.

=== "Terminal"

    ```bash
    pip install MRRpy
    MRRpy wizard              # answers a few questions, saves run.yaml
    MRRpy run -c run.yaml
    ```

    Or write the file yourself, starting from a commented template:

    ```bash
    MRRpy init-config --short -o run.yaml   # then set DEM_PATH, OUTPUT_POINT, TARGET_CRS_EPSG
    MRRpy validate -c run.yaml              # checks it and says what the run will do
    MRRpy run -c run.yaml
    ```

=== "Python"

    ```python
    from MRRpy import Config, run_pipeline, plot_hydrograph

    cfg = Config(
        DEM_PATH="dem.tif",
        OUTPUT_POINT=(27.632, 85.293),   # (latitude, longitude) of the outlet
        TARGET_CRS_EPSG="EPSG:32645",    # a projection in metres: your UTM zone
        OUTPUT_DIR="results/",
        RAIN_INTENSITY_MM_HR=20.0,       # a design storm: 20 mm/h …
        RAIN_DURATION_HOURS=3.0,         # … for 3 hours
        TOTAL_SIMULATION_TIME_HOURS=12.0,
    )
    out = run_pipeline(cfg)              # terrain, then routing
    plot_hydrograph(out)
    ```

=== "QGIS plugin"

    Install **MRRpy_plugin** ([how](interfaces.md#qgis-plugin)), open it from the
    Plugins menu, and:

    1. Tab **1 · DEM & Watershed**: DEM file, target CRS, **Analyze terrain**,
       pick the outlet, **Delineate watershed**.
    2. Tab **2 · Precipitation**: *Uniform (constant rate)*, 20 mm/h for 3 h.
    3. **Run**. Tab **5 · Results** shows the hydrograph.

## What you get

In the results folder:

| File | Contents |
|---|---|
| `hydrograph.csv` | the flow at the outlet over time (`time_hr`, `Q_m3s`) |
| `mass_balance.csv` | the water-balance check: rain, outflow, storage, error |
| `watershed.tif`, `watershed.geojson` | the basin |
| `clipped_dem.tif`, `flow_direction.tif`, `clipped_flow_accumulation.tif` | the terrain the model ran on |

With the defaults, all rain runs off and is routed with the kinematic wave.
That is the largest flood the storm can make.

## Next

- [Example 1 – Your first run](../examples/first-run.md): the same run, explained,
  with results.
- [Examples 3–5](../examples/routing-schemes.md): add losses to the rain and
  compare routing methods.
- The [user manual](../manual/index.md) explains every setting, step by step.
