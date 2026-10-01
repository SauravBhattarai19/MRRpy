# 8 Route an inflow hydrograph

**Goal:** route water that enters from upstream (from a gauge, a dam release or
another model) with **no rain at all**, and watch it travel to the outlet.

**You need:** a hydrograph CSV ([inflow_upstream.csv](../assets/data/inflow_upstream.csv)):
2 m³/s of baseflow rising to 12 m³/s after 1 hour and falling back by hour 3.

```text
time_hr,Q_m3s
0.0,2.0
0.5,7.0
1.0,12.0
2.0,7.0
3.0,2.0
```

**Settings used:** [[ROUTING_INFLOW_BC]], [[RAIN_INTENSITY_MM_HR]] (0),
[[RUNOFF_SOURCE]] (`none`), [[ROUTING_GAUGES]].

The basin is a small tributary north-east of Kathmandu, downloaded from Earth
Engine as in [Example 2](download-dem.md). The inflow point is placed near the
upstream channel; MRRpy moves it to the nearest river cell.

## Set it up

=== "Notebook form"

    At the top, *Starting point* → **Route a known inflow hydrograph downstream
    (no rain)** → **Apply starting point**. It sets the rain to 0 and the runoff to
    `none`. Then in step **5 Routing**, *Water entering from upstream*, one line
    per point: `upstream, 27.80667, 85.3983, inflow_upstream.csv`.

=== "Config file + CLI"

    ```yaml
    DEM_BOUNDS_WGS84: [85.3809, 27.7625, 85.4773, 27.8223]
    DEM_SOURCE: nasadem
    GEE_PROJECT: ee-yourname
    OUTPUT_POINT: [27.77772, 85.42399]
    TARGET_CRS_EPSG: EPSG:32645
    OUTPUT_DIR: results/inflow/
    PRECIP_METHOD: uniform
    RAIN_INTENSITY_MM_HR: 0.0
    RUNOFF_SOURCE: none
    TOTAL_SIMULATION_TIME_HOURS: 6.0
    ROUTING_INFLOW_BC:
      - {name: upstream, lat: 27.80667, lon: 85.3983, csv: inflow_upstream.csv}
    ```

    ```bash
    MRRpy wizard --start inflow_only     # or answer the questions instead
    MRRpy run -c inflow.yaml
    ```

=== "Python"

    ```python
    from MRRpy import Config, run_pipeline, plot_hydrograph

    cfg = Config(
        DEM_BOUNDS_WGS84=(85.3809, 27.7625, 85.4773, 27.8223),
        DEM_SOURCE="nasadem",
        GEE_PROJECT="ee-yourname",
        OUTPUT_POINT=(27.77772, 85.42399),
        TARGET_CRS_EPSG="EPSG:32645",
        OUTPUT_DIR="results/inflow/",
        PRECIP_METHOD="uniform",
        RAIN_INTENSITY_MM_HR=0.0,          # no rain: pure routing
        RUNOFF_SOURCE="none",
        TOTAL_SIMULATION_TIME_HOURS=6.0,
        ROUTING_INFLOW_BC=[{"name": "upstream", "lat": 27.80667, "lon": 85.39830,
                            "csv": "inflow_upstream.csv"}],
    )
    out = run_pipeline(cfg)
    plot_hydrograph(out, label="outlet Q(t)")
    ```

=== "QGIS plugin"

    The dialog has no field for inflow hydrographs. Save the YAML above, open it
    with **Load Config** (the plugin keeps the inflow points), check the other tabs
    and press **Run**.

## Results

![Outlet hydrograph from an upstream inflow](../assets/img/bc_routing_hydrograph.png)

The 12 m³/s pulse reaches the outlet about 40 minutes later, at about
11.4 m³/s, after some 5 km of channel: the wave is delayed and slightly flattened,
as it should be. The water balance counts the inflow as its own input
(`bc_inflow_m3`), so it still closes.

## Inflow and a storm together

An inflow, a storm and physical runoff can run together, with roughness that
grows with elevation (made with `mannings_n_from_dem`, see
[Example 9](roughness-channels.md)):

```python
from MRRpy import (Config, run_pipeline, mannings_n_from_dem,
                   plot_hydrograph, plot_mass_balance)

cfg = Config(
    DEM_BOUNDS_WGS84=(85.3809, 27.7625, 85.4773, 27.8223), DEM_SOURCE="nasadem",
    GEE_PROJECT="ee-yourname", OUTPUT_POINT=(27.77772, 85.42399),
    TARGET_CRS_EPSG="EPSG:32645", OUTPUT_DIR="results/together/",
)
out = run_pipeline(cfg, stages=("process_dem",))

cfg.MANNINGS_N_SOURCE = "raster"
cfg.MANNINGS_N_RASTER_PATH = mannings_n_from_dem(
    dem_path=out["clipped_dem"],
    rule=[(1700, 0.035), (2000, 0.06), (2300, 0.10), (float("inf"), 0.14)],
    output_path="results/together/mannings_n_elev.tif")
cfg.RAIN_INTENSITY_MM_HR = 15.0
cfg.RAIN_DURATION_HOURS = 1.0
cfg.RUNOFF_SOURCE = "physical"
cfg.RUNOFF_MECHANISMS = ["impervious", "infiltration_excess", "saturation_excess"]
cfg.ROUTING_INFLOW_BC = [{"name": "upstream", "lat": 27.80667, "lon": 85.39830,
                          "csv": "inflow_upstream.csv"}]
cfg.TOTAL_SIMULATION_TIME_HOURS = 8.0
out.update(run_pipeline(cfg, stages=("routing",)))

plot_hydrograph(out)
plot_mass_balance(out)
```

![Outlet hydrograph: storm runoff on top of the upstream inflow](../assets/img/capstone_hydrograph.png)
![Water balance of the combined run](../assets/img/capstone_massbalance.png)

The storm's runoff peaks quickly, riding on the slower inflow pulse. The water
balance counts rain-made runoff and inflow as two separate inputs, and still
closes.

## Other options to try

| Change | Setting | See |
|---|---|---|
| inflow on top of a storm | set `RAIN_INTENSITY_MM_HR` above 0 | [3.2](../manual/precipitation.md#32-design-storm) |
| watch the wave at points on the way | `ROUTING_GAUGES: [{name: mid, lat: 27.79, lon: 85.41}]` | [6.1](../manual/outputs.md#61-virtual-gauges) |
| several inflows | add more points to the list; points on the same cell add up | [5.6](../manual/inflows.md) |
| an exact cell | `row`/`col` and `snap_to_channel: false` | [5.6](../manual/inflows.md) |
| a routing method with backwater | `ROUTING_SCHEME: diffusive_implicit` | [5.1](../manual/routing.md#51-routing-method) |
