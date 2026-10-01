# 6 Outputs and run

Every run writes the outlet hydrograph and checks its water balance. This step
adds optional results, **virtual gauges** and **maps over time**, and picks the
**computer** (CPU or GPU). It ends with the files a run writes and how to plot
them.

!!! info "Where to set it"
    Notebook form: step **6 Outputs and run** (with *Check settings*, *Save* and
    *Run the model*) · Wizard: part **6 Outputs and computer** · QGIS: tab
    **4 · Routing** (*Compute Backend*, *Save maps over time*) and tab
    **5 · Results**.

## 6.1 Virtual gauges

A virtual gauge records the water depth, flow and speed at a point, every
`OUTPUT_INTERVAL_SECONDS`, into `gauges.csv`. Use gauges where you have
observations, at bridges or towns, or along a river to watch a flood travel.
Each point is moved to the nearest river cell, like an
[inflow point](inflows.md).

```yaml
ROUTING_GAUGES:
  - {name: Sundarijal, lat: 27.76, lon: 85.42}
  - {name: Kathmandu, lat: 27.70, lon: 85.32}
```

<!-- settings: ROUTING_GAUGES -->

## 6.2 Maps over time

With `SAVE_FIELDS` on, the run keeps a map of each quantity in `FIELD_VARS`
(depth, velocity, discharge, volume) at every output time. They are written as
one compact file, `fields/fields.npz`, with `fields_meta.json`. From them MRRpy
draws maps and animations, and writes peak maps as GeoTIFFs for QGIS:

```python
from MRRpy import plot_field, animate_fields, export_peak_maps
plot_field(out, "depth")                     # the deepest water each cell reached
plot_field(out, "discharge", time=2.5)       # the flow 2.5 h into the run
animate_fields(out, ["depth", "discharge"])  # a GIF, side by side, with the hydrograph
export_peak_maps(out)                        # max_<var>.tif and time_of_max_<var>_hours.tif
```

The maps stay in memory until the run ends: about *(number of output times) ×
(cells) × (quantities) × 4 bytes*. The log prints the estimate and warns above
2 GB. For big grids, save fewer times (a larger `OUTPUT_INTERVAL_SECONDS` or
`FIELD_STRIDE`) or fewer quantities.

<!-- settings: SAVE_FIELDS FIELD_VARS FIELD_STRIDE FIELD_OUTPUT_DIR -->

## 6.3 Computer: CPU or GPU

The **CPU** works everywhere. An NVIDIA **GPU** (`pip install "MRRpy[gpu]"`) can
be much faster for large grids with the explicit routing methods. If no usable
GPU is found, MRRpy says so and runs on the CPU. The implicit diffusive method
always runs on the CPU. On a GPU, `float32` is faster and `float64` more exact.

<!-- settings: BACKEND GPU_PRECISION -->

## 6.4 The water balance

At the end of every routing run MRRpy checks that no water was lost or created:

$$
\text{error} = \text{input} - \text{outflow} - \text{storage},
\qquad \text{input} = \text{runoff} + \text{inflow hydrographs}
$$

It prints the result and, with `MASS_BALANCE_REPORT` on, **adds one row** to
`mass_balance.csv`. Rows accumulate, so many runs into the same folder line up in
one table. Columns:

| Column | Meaning |
|---|---|
| `timestamp`, `run_tag`, `scheme`, `theta`, `runoff_source`, `sd_source`, `sd_max`, `ksat_scale`, `infiltration`, `impervious` | what was run |
| `rain_m3` | rain that fell on the modelled area (m³) |
| `input_m3` | water that entered the routing: runoff plus inflow hydrographs |
| `bc_inflow_m3` | of which, inflow hydrographs |
| `outflow_m3` | water that left the model |
| `storage_m3` | water still in the model at the end |
| `error_m3`, `rel_error` | the closure error, in m³ and as a fraction of the input (about 1e-15 is machine precision) |
| `runoff_ratio` | runoff ÷ rain: the share of the rain that ran off |
| `dunne_m3`, `horton_m3`, `imperv_m3` and `*_frac` | physical runoff by process: saturation excess, infiltration excess, impervious |

<!-- settings: MASS_BALANCE_REPORT -->

## 6.5 Running

A run has two **stages**; you can run them separately:

| Stage | Does | Writes |
|---|---|---|
| `process_dem` | [1 Terrain](terrain.md): DEM, flow directions, the area to model | the terrain files |
| `routing` | rain → runoff → routing | `hydrograph.csv`, `mass_balance.csv`, … |

Running `routing` alone reuses the terrain already in the results folder, which
is the quick way to try other rain, runoff or routing settings on the same basin.

=== "Notebook form"

    Step **6**: **Check settings**, then **Run the model**. *What to run* picks a
    full run, delineation only, or routing only. The log scrolls underneath and
    is saved as `mrrpy_run.log`; a **Results** panel then shows the peak flow,
    the water-balance check, the files and a hydrograph.

=== "Terminal"

    ```bash
    MRRpy validate -c run.yaml
    MRRpy run -c run.yaml                          # both stages
    MRRpy run -c run.yaml --stages routing         # routing only
    MRRpy run -c run.yaml --backend gpu --output-dir results_gpu/
    ```

=== "Python"

    ```python
    from MRRpy import Config, run_pipeline
    cfg = Config.from_file("run.yaml")
    out = run_pipeline(cfg)                                # both stages
    out = run_pipeline(cfg, stages=("routing",))           # routing only
    ```

=== "QGIS plugin"

    Tab **1**: **Analyze terrain**, then **Delineate watershed** (or **Use whole
    DEM**). Then **Run** at the bottom of the dialog. Tab **5 · Results** shows
    the hydrograph; **Load Layers into QGIS**, **Load Peak Maps** and **Save Flow
    Animation…** load the results.

## 6.6 Files a run writes

| File | Contents |
|---|---|
| `hydrograph.csv` | `time_s`, `time_hr`, `Q_m3s` at the outlet; whole-DEM runs add `Q_total_outflow_m3s` |
| `mass_balance.csv` | one row per run (above) |
| `partition.csv` | physical runoff: cumulative volume by process over time |
| `gauges.csv` | virtual gauges: `time_s`, `time_hr`, then `<name>_depth_m`, `<name>_Q_m3s`, `<name>_vel_ms` for each gauge |
| `fields/fields.npz`, `fields/fields_meta.json` | maps over time |
| `max_<var>.tif`, `time_of_max_<var>_hours.tif` | peak maps, from `export_peak_maps` |
| `mrrpy_run.log` | the run's log (notebook form) |
| the terrain files | see [1.3 Results folder](terrain.md#13-results-folder) |
| downloads | `raw_dem_gee.tif`, `imerg/`, `cn_gcn250_amc*.tif`, `ksat_hihydro_*.tif`, `deficit_serves_*.tif`, … reused by later runs |

Plot them in Python. Each function takes the result of `run_pipeline`, a
`Config` or the results folder:

```python
from MRRpy import plot_hydrograph, plot_watershed, plot_mass_balance
plot_hydrograph(out)       # Q(t) at the outlet, peak marked
plot_watershed(out)        # the DEM with the basin outline
plot_mass_balance(out)     # input, outflow, storage, error
```
