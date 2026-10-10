# Examples

Each example is a complete run you can repeat. It is shown four ways, in tabs:
the **notebook form**, a **config file** with the `MRRpy` command, **Python**, and
the **QGIS plugin**. All four build the same configuration. Each example ends
with **other options to try**, and every setting links to its explanation in the
[user manual](../manual/index.md).

Most examples use the same basin: the **Bagmati River above Khokana**, which
drains the Kathmandu valley in Nepal (606 km², a 90 m DEM of 74,795 cells, outlet
at 27.6322 N, 85.2933 E). The figures and numbers on these pages come from real
runs with MRRpy 0.2.0 on a 90 m ALOS DEM. On your own DEM they will differ.

| Example | Shows | Main settings | Needs Earth Engine |
|---|---|---|---|
| [1 Your first run](first-run.md) | a design storm on your DEM; virtual gauges | `DEM_PATH`, `OUTPUT_POINT`, `RAIN_INTENSITY_MM_HR`, `ROUTING_GAUGES` | no |
| [2 Download a DEM](download-dem.md) | no DEM file: download one and delineate | `DEM_BOUNDS_WGS84`, `DEM_SOURCE`, `DEM_SCALE_M` | yes |
| [3 Compare routing methods](routing-schemes.md) | kinematic, Muskingum–Cunge, implicit diffusive | `ROUTING_SCHEME` | no |
| [4 Runoff methods](runoff-methods.md) | none, SCS Curve Number (dry, normal, wet), Green–Ampt | `RUNOFF_SOURCE`, `RUNOFF_CN_AMC` | no (optional GCN250) |
| [5 Physical runoff processes](physical-runoff.md) | infiltration excess, saturation excess, both | `RUNOFF_MECHANISMS`, `GA_*`, `VSA_*` | no (optional soil maps) |
| [6 Rain gauges](rain-gauges.md) | your gauge records, Thiessen vs IDW | `PRECIP_METHOD`, `PRECIP_GAUGE_FILE` | no |
| [7 A real storm from satellite](satellite-storm.md) | NASA IMERG rain for the September 2024 flood | `PRECIP_METHOD: imerg_*`, `EVENT_START_UTC` | yes |
| [8 Route an inflow hydrograph](inflow-hydrograph.md) | water from upstream, no rain | `ROUTING_INFLOW_BC` | no |
| [9 Roughness and river channels](roughness-channels.md) | roughness by elevation; channel size from the 2-year flood | `MANNINGS_N_*`, `CHANNEL_QBF_M3S` | no (optional) |
| [10 The whole DEM and flood maps](whole-dem.md) | every DEM cell, maps and animations | `MODEL_AREA`, `SAVE_FIELDS` | no |
| [11 Many runs from Python](batch-runs.md) | sweeps and comparison tables | Python loops | no |
| [12 Flood depth and extent maps](flood-maps.md) | how far rivers spread: depth, extent, animation, at 30 m | `INUNDATION_MAP`, `INUNDATION_DEM` | yes (or your own fine DEM) |
| [Case study: Nepal (Trishuli)](nepal-case-study.md) | a large Himalayan basin, satellite storm and an outburst flood | many | yes |

!!! tip "Before you start"
    [Install MRRpy](../getting-started/installation.md). For the notebook form,
    `pip install "MRRpy[notebook]"`. For Earth Engine examples,
    `pip install "MRRpy[gee]"` and [sign in once](../manual/earth-engine.md). For
    QGIS, install the plugin (see [Ways to set up a run](../getting-started/interfaces.md#qgis-plugin)).
    Example data: [gauges.csv](../assets/data/gauges.csv),
    [rain.csv](../assets/data/rain.csv),
    [inflow_upstream.csv](../assets/data/inflow_upstream.csv).
