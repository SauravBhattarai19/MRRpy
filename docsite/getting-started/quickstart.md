# Quickstart

## See it work first

Before you look for data, run the sample basin. It needs nothing but the
install, and takes a few seconds:

```bash
pip install MRRpy
MRRpy demo
```

It routes a two-hour storm over a made-up valley and writes
`mrrpy_demo/results/hydrograph.csv`, a figure of it, and `mrrpy_demo/run.yaml`,
the settings, which you can edit and run again. `MRRpy demo --real` does the
same on a real basin near Kathmandu, downloading a 90 m DEM with no account.
If anything goes wrong, `MRRpy doctor` checks the install.

Nothing installed yet? The same first run, in your browser: [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/SauravBhattarai19/MRRpy/blob/main/notebooks/quickstart_demo.ipynb)

## Your own basin

From a DEM to a flood hydrograph in a few minutes. You need two things: a
**DEM** (a GeoTIFF of ground elevation covering your basin) and the **latitude
and longitude of the outlet**, the river point your basin drains to. No DEM?
Give the area instead and MRRpy [downloads one](../examples/download-dem.md),
with no account needed.

Pick the way you like to work; all of them make the same run.

=== "Notebook form"

    ```bash
    pip install "MRRpy[all]"
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
    MRRpy init-config --short -o run.yaml   # then set DEM_PATH and OUTPUT_POINT
    MRRpy validate -c run.yaml              # checks it and says what the run will do
    MRRpy run -c run.yaml
    ```

=== "Python"

    ```python
    from MRRpy import Config, run_pipeline, plot_hydrograph

    cfg = Config(
        DEM_PATH="dem.tif",
        OUTPUT_POINT=(27.632, 85.293),   # (latitude, longitude) of the outlet
        OUTPUT_DIR="results/",
        RAIN_INTENSITY_MM_HR=20.0,       # a design storm: 20 mm/h …
        RAIN_DURATION_HOURS=3.0,         # … for 3 hours
        TOTAL_SIMULATION_TIME_HOURS=12.0,
    )
    out = run_pipeline(cfg)              # terrain, then routing
    print(out.summary())                 # peak flow, water balance, results folder
    plot_hydrograph(out)
    ```

    The map projection is chosen for you (the UTM zone of the outlet). With no
    DEM file, give the area instead:
    `Config(DEM_BOUNDS_WGS84=(85.1, 27.5, 85.6, 27.9), DEM_SOURCE="glo90_open", …)`.

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
| `run.log`, `run_config.yaml`, `run_info.json` | what the run reported, its settings (ready to run again) and its record |
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
