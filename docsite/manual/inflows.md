# 5.6 Water entering from upstream

Sometimes water enters the model from outside: a river flowing in from upstream
of your DEM, a dam release, or the output of another model. An **inflow
hydrograph** adds a flow $Q(t)$ in m³/s at a point, on top of any rain.

!!! info "Where to set it"
    Notebook form: step **5 Routing** → *Water entering from upstream* · Wizard:
    part **5 Routing and simulation time** (advanced) · QGIS: no field; put it
    in a config file and use **Load Config**.

Each inflow point has a location and a CSV file with the flow over time:

```text
time_hr,Q_m3s
0.0,2.0
1.0,12.0
3.0,2.0
6.0,2.0
```

- Time is in hours (`time_hr`) or seconds (`time_s`) from the start of the run;
  between rows the flow changes linearly.
- The location is a latitude and longitude, or `row`/`col` in the grid, or
  `easting`/`northing` in the model projection.
- The point is moved to the river cell with the largest drainage area within
  `snap_radius_cells` cells (3 by default), so it needn't be exactly on the river.
  Set `snap_to_channel: false` to use the exact cell.
- Two points that end up on the same cell add up.

In a config file:

```yaml
ROUTING_INFLOW_BC:
  - {name: upstream, lat: 27.80667, lon: 85.3983, csv: inflow_upstream.csv}
  - {name: dam, row: 120, col: 85, csv: dam_release.csv, snap_to_channel: false}
```

**Only routing, no rain.** For pure routing set the rain to zero:
`PRECIP_METHOD: uniform`, `RAIN_INTENSITY_MM_HR: 0` and `RUNOFF_SOURCE: none`. The
wizard's starting point *Route a known inflow hydrograph downstream* does this
for you.

The [water balance](outputs.md#64-the-water-balance) counts inflow water
separately (`bc_inflow_m3`), so it still closes. To see the flow at points along
the way, add [virtual gauges](outputs.md#61-virtual-gauges).

<!-- settings: ROUTING_INFLOW_BC -->

## Try it

- [Example 8 – Route an inflow hydrograph](../examples/inflow-hydrograph.md).
