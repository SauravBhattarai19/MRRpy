# MRRpy

**Rainfall–runoff and flood routing for any basin on Earth, from a DEM and a storm.**

MRRpy, the **M**ulti-**M**echanism **R**unoff and **R**outing model, is a
distributed, physics-based flood model in Python. Give it an elevation model and
a storm. It traces the drainage network, works out how much of the rain runs off
the soil, routes the water through every grid cell and river channel, and returns
the flood hydrograph at the outlet, maps of depth and flow, and a check that no
water was lost.

It runs offline with your own data, or fetches what's missing (elevation,
satellite rain, soil, land cover) from Google Earth Engine, so even an ungauged
basin can be modelled in minutes.

[Get started](getting-started/quickstart.md){ .md-button .md-button--primary }
[User manual](manual/index.md){ .md-button }
[Examples](examples/index.md){ .md-button }

![Water depth and river flow spreading over the Kathmandu valley during a storm, with the hydrograph](assets/img/whole_dem_flow.gif)

*A 2-hour storm over the whole Kathmandu valley at 90 m. Left: water depth.
Middle: river flow, wider lines for more water. Right: flow leaving the valley.
([Example 10](examples/whole-dem.md))*

<div class="grid" markdown>

<figure markdown>
![IMERG satellite rain and the simulated flood of 26–30 September 2024](assets/img/ex7_satellite.png){ loading=lazy }
<figcaption>The September 2024 Kathmandu flood, from NASA satellite rain
(<a href="examples/satellite-storm/">Example 7</a>).</figcaption>
</figure>

<figure markdown>
![Storm rain spread from four gauges by Thiessen and by IDW, and the two hydrographs](assets/img/ex6_rain_gauges.png){ loading=lazy }
<figcaption>Your own rain gauges, spread two ways, and the floods they make
(<a href="examples/rain-gauges/">Example 6</a>).</figcaption>
</figure>

</div>

## Try it

```bash
pip install "MRRpy[notebook]"
```

=== "Notebook form"

    ```python
    from MRRpy import ConfigForm
    ConfigForm()        # six steps: terrain, projection, rain, runoff, routing, run
    ```

=== "Terminal"

    ```bash
    MRRpy wizard            # a few plain questions, saved as run.yaml
    MRRpy run -c run.yaml
    ```

=== "Python"

    ```python
    from MRRpy import Config, run_pipeline, plot_hydrograph

    cfg = Config(DEM_PATH="dem.tif", OUTPUT_POINT=(27.632, 85.293),   # outlet (lat, lon)
                 TARGET_CRS_EPSG="EPSG:32645", OUTPUT_DIR="results/",
                 RAIN_INTENSITY_MM_HR=20.0, RAIN_DURATION_HOURS=3.0)
    out = run_pipeline(cfg)              # → results/hydrograph.csv, mass_balance.csv, …
    plot_hydrograph(out)
    ```

=== "QGIS plugin"

    **MRRpy_plugin**: a five-tab dialog (DEM & Watershed, Precipitation, Runoff,
    Routing, Results) that runs the same model inside QGIS.
    [Install it](getting-started/interfaces.md#qgis-plugin).

## What it does

<div class="grid cards" markdown>

-   :material-terrain:{ .lg .middle } __Terrain__

    ---

    Your DEM, or one of eight DEM datasets downloaded for a box you draw.
    Pit removal that carves through barriers, D8 flow directions, and the
    watershed above an outlet, or the whole DEM.
    [Chapter 1](manual/terrain.md)

-   :material-weather-pouring:{ .lg .middle } __Rain__

    ---

    A design storm, your rain gauges (Thiessen or inverse-distance), or NASA
    IMERG satellite rain for any date since 2000. Optional snow line.
    [Chapter 3](manual/precipitation.md)

-   :material-water-percent:{ .lg .middle } __Runoff__

    ---

    SCS Curve Number (with the global GCN250 map), runoff coefficients, your own
    runoff maps, or soil physics: Green–Ampt infiltration, saturated source
    areas (VSA-OPM, Pradhan & Ogden 2010) and impervious cities, in any
    combination. [Chapter 4](manual/runoff.md)

-   :material-waves:{ .lg .middle } __Routing__

    ---

    Kinematic wave, Muskingum–Cunge, or a semi-implicit diffusion wave that
    handles backwater and flat valleys with large, stable time steps.
    [Chapter 5](manual/routing.md)

-   :material-waterfall:{ .lg .middle } __River channels__

    ---

    Sub-grid channels cut into each river cell, sized to carry the 2-year
    flood: from a global estimate, your gauge, or a regional formula.
    [Chapter 5.5](manual/channels.md)

-   :material-chart-areaspline:{ .lg .middle } __Results__

    ---

    Outlet hydrograph, virtual gauges anywhere, depth and flow maps over time,
    animations, peak-flood GeoTIFFs, and a water-balance check on every run.
    [Chapter 6](manual/outputs.md)

-   :material-earth:{ .lg .middle } __Global data, or none__

    ---

    Earth Engine supplies DEMs, IMERG rain, curve numbers, soil, land cover and
    river size. Every option also works offline with your own files.
    [Earth Engine](manual/earth-engine.md)

-   :material-gesture-tap-button:{ .lg .middle } __Four ways to work__

    ---

    A step-by-step Jupyter form, a terminal wizard and config files, Python,
    and a QGIS plugin, all building the same configuration. CPU or NVIDIA GPU.
    [Ways to set up a run](getting-started/interfaces.md)

</div>

## How it fits together

```text
 DEM ─▶ Terrain ─▶ drainage network + watershed                     (stage process_dem)
                          │
 Rain ─▶ Runoff ─▶ runoff in every cell                              (stage routing)
                          ▼
                  Routing through cells and channels ─▶ hydrograph.csv, gauges.csv,
                  ▲                                     flood maps, mass_balance.csv
     roughness · river channels · inflows from upstream
```

Runoff and routing are independent: any runoff method works with any routing
method, so comparing two choices means changing one setting.

## Where to go next

| I want to… | Go to |
|---|---|
| install MRRpy and make a first run | [Installation](getting-started/installation.md), [Quickstart](getting-started/quickstart.md) |
| understand a setting, or the physics behind it | the [user manual](manual/index.md), or the [A–Z list](manual/all-settings.md) |
| copy a working setup | the [examples](examples/index.md), each in notebook, CLI, Python and QGIS form |
| script many runs or extend the model | [Many runs from Python](examples/batch-runs.md), [For developers](reference/developers.md) |

## Learn the science

A free, interactive companion course walks through the physics from the ground
up (DEMs, delineation, runoff, and each routing scheme) with in-browser
simulations: [**the MRRpy course**](https://sauravbhattarai19.github.io/MRRpy/).
