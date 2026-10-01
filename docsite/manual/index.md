# User manual

This manual explains **every setting in MRRpy**: what it does, what values it
takes, its default, and when it matters. It follows the same steps as the
notebook form, so you can read it side by side with whatever tool you use to set
up a run.

| Chapter | What you decide |
|---|---|
| [1 Terrain](terrain.md) | the elevation data (your file or a download), the area to model, the results folder |
| [2 Coordinate system](coordinate-system.md) | the map projection, in metres, that the model grid uses |
| [3 Precipitation](precipitation.md) | where the rain comes from: a design storm, rain gauges or satellite; snow |
| [4 Runoff](runoff.md) | how rain is split into runoff and water that soaks in |
| [5.1–5.3 Routing method and time](routing.md) | how water moves from cell to cell, for how long, and with what time step |
| [5.4 Ground roughness](roughness.md) | Manning's n on the ground and in the rivers |
| [5.5 River channels](channels.md) | which cells are rivers and how big their channels are |
| [5.6 Water entering from upstream](inflows.md) | inflow hydrographs injected at points |
| [6 Outputs and run](outputs.md) | extra results (gauges, maps), CPU or GPU, the files a run writes |
| [Google Earth Engine](earth-engine.md) | signing in, and which options download data |
| [All settings A–Z](all-settings.md) | every setting with a link to its explanation |

## How the model works

A run has two stages. **`process_dem`** turns a DEM into a drainage network.
**`routing`** steps through time: each step it reads the rain, turns it into
runoff, and moves the water downhill from cell to cell until it leaves the model.

```text
 DEM ─▶ 1 Terrain ─▶ 2 Coordinate system ─▶ D8 flow directions + watershed      (stage process_dem)
                                                     │
 3 Precipitation ─▶ rain [m/s] per cell              │
                        │                            ▼
                 4 Runoff ─▶ runoff [m/s] ─▶ 5 Routing (time loop) ─▶ 6 Outputs   (stage routing)
                                               ▲                      hydrograph.csv
          5.4 roughness · 5.5 channels · 5.6 inflows                  mass_balance.csv, maps …
```

Runoff and routing are independent: **any runoff method works with any routing
method**. The model runs on a regular grid of square cells (the DEM's pixels).
Every cell drains to one of its 8 neighbours (the D8 rule), so the cells form a
tree that ends at the outlet.

## How to read the setting tables

Each chapter explains the physics first, then lists the settings in a table, in
the style of the GSSHA wiki's project-file cards:

| Column | Meaning |
|---|---|
| **Setting** | the name to use in a config file or in Python (`RAIN_INTENSITY_MM_HR`), then its plain-language label. *advanced* marks settings most people leave at the default; the wizard and the form fold them away. |
| **Value** | what kind of value it takes: a number with its unit and allowed range, a file, a choice, … with an example. |
| **Default** | the value used when you don't set it. `null` means empty; the description says what empty means. |
| **Description** | what it does, every choice with its **code**, and **Applies when**: the other settings that make it matter. A setting that doesn't apply is ignored. |

The tables are generated from the same catalogue that drives the wizard, the
notebook form and `MRRpy explain`, so all of them always say the same thing.

## One setting, five ways to set it

Every setting can be set from any interface. They all build the same
configuration, so you can switch at any time. For example, the rain intensity of
a design storm:

=== "Notebook form"

    Step **3 Precipitation** → *Design storm* → **Rain intensity (mm/h)**.

=== "Terminal wizard"

    `MRRpy wizard` → part **2 Rainfall** → answer `Rain intensity (mm/h) [20]:`.

=== "Config file (YAML)"

    ```yaml
    RAIN_INTENSITY_MM_HR: 35.0
    ```

    then `MRRpy run -c run.yaml`.

=== "Python"

    ```python
    from MRRpy import Config
    cfg = Config(RAIN_INTENSITY_MM_HR=35.0)
    ```

=== "QGIS plugin"

    Tab **2 · Precipitation** → *Uniform Rainfall Parameters* → **Rainfall intensity**.

Where each chapter lives in each tool:

| Manual chapter | Notebook form step | Wizard part | QGIS plugin tab |
|---|---|---|---|
| 1 Terrain | 1 Terrain | 1 Basin, terrain and results folder | 1 · DEM & Watershed |
| 2 Coordinate system | 2 Coordinate system | 1 Basin, terrain and results folder | 1 · DEM & Watershed (*Target CRS*) |
| 3 Precipitation | 3 Precipitation | 2 Rainfall | 2 · Precipitation |
| 4 Runoff | 4 Runoff | 3 Runoff | 3 · Runoff |
| 5.1–5.3 Routing method and time | 5 Routing | 5 Routing and simulation time | 4 · Routing |
| 5.4 Ground roughness, 5.5 River channels | 5 Routing | 4 Roughness and river channels | 4 · Routing |
| 5.6 Water entering from upstream | 5 Routing | 5 Routing (advanced) | not on a tab: load a config file |
| 6 Outputs and run | 6 Outputs and run | 6 Outputs and computer | 4 · Routing (*Compute Backend*, *Save maps*) and 5 · Results |

!!! note "Settings the QGIS plugin has no field for"
    A few rarely used settings (for example inflow hydrographs, virtual gauges or
    the DEM download box) have no field in the QGIS dialog. Put them in a config
    file and open it with **Load Config**: the plugin keeps every value it has no
    field for and passes it to the run.

## Fixed choices: name or code

Every setting with a fixed list of choices takes the **name or its number**
(code). `PRECIP_METHOD: thiessen` and `PRECIP_METHOD: 1` are the same. The codes
are listed in each table and by `MRRpy list-options`. Codes never change for an
existing choice; new choices are added at the end.

## Quick help in the terminal

```bash
MRRpy explain RAIN_INTENSITY_MM_HR     # one setting
MRRpy explain manning                  # search
MRRpy list-options                     # every choice and its code
```
