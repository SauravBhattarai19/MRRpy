# 3 Precipitation

This step decides **where the rain comes from**: the same design storm
everywhere, your own rain-gauge records, or NASA's IMERG satellite rainfall. Each
step of a run, every cell gets a rain rate in metres per second; the
[runoff step](runoff.md) then decides how much of it runs off.

!!! info "Where to set it"
    Notebook form: step **3 Precipitation** (pick the source first; Thiessen or
    IDW appears underneath it) · Wizard: part **2 Rainfall** · QGIS: tab
    **2 · Precipitation**.

## 3.1 Rain source

| Source | `PRECIP_METHOD` | Needs | Use it for |
|---|---|---|---|
| Design storm | `uniform` (0) | nothing | testing, "what if" storms, design events |
| Rain gauges | `thiessen` (1) or `idw` (2) | two CSV files | a real event with gauge records |
| Satellite | `imerg_thiessen` (3) or `imerg_idw` (4) | an Earth Engine sign-in and the storm date | a real event anywhere, with no gauges |

The gauge and satellite sources both start from rain at **points** (gauges, or
the centres of satellite pixels) and spread it to the cells in one of two ways:

**Thiessen** (nearest point): each cell takes the rain of its nearest point. The
basin is divided into one zone per point (Thiessen polygons), and rain changes
in steps at the zone borders.

**IDW** (inverse-distance weighting): each cell takes a weighted average of
*all* points, the closer the heavier:

$$
P_{\text{cell}} = \frac{\sum_i P_i \, d_i^{-p}}{\sum_i d_i^{-p}}
$$

where $d_i$ is the distance from the cell to point $i$ and $p$ is
`PRECIP_IDW_POWER` (2 by default). A larger $p$ makes it look more like
Thiessen; a smaller $p$ smooths the field. IDW gives a smooth rain field.

The zones of the points (nearest point, also with IDW) are the **rainfall zones**
that the saturation-excess runoff process can use; see
[`VSA_PER_POLYGON`](runoff.md#VSA_PER_POLYGON).

<!-- settings: PRECIP_METHOD -->

## 3.2 Design storm

A design storm rains at the same constant rate on every cell, from the start of
the run for `RAIN_DURATION_HOURS`, then stops. The total depth is intensity ×
duration (20 mm/h for 3 h = 60 mm). Set the intensity to 0 to route only an
[inflow hydrograph](inflows.md).

<!-- settings: RAIN_INTENSITY_MM_HR RAIN_DURATION_HOURS -->

## 3.3 Rain gauges

Gauge rain needs **two CSV files**.

**Gauge locations** (`PRECIP_GAUGE_FILE`), one row per gauge. The coordinates are
in the model's projection ([2 Coordinate system](coordinate-system.md)), in metres:

```text
gauge_id,name,easting_m,northing_m
G01,Sundarijal,344296,3071617
G02,Kathmandu,334349,3065100
G03,Lalitpur,335261,3059546
```

**Rainfall** (`PRECIP_TIMESERIES_FILE`): a `time_s` column (seconds from the start
of the run, increasing) and one column per `gauge_id` with the rain **depth in mm
that fell in the interval ending at that time**:

```text
time_s,G01,G02,G03
0,0.0,0.0,0.0
1800,12.1,1.6,0.4
3600,17.7,3.9,1.2
5400,20.0,7.3,2.9
```

The row at 1800 s says 12.1 mm fell at G01 between 0 and 1800 s, a rate of
24.2 mm/h. Between rows the rate changes linearly; before the first row and after
the last there is no rain. Intervals don't have to be equal. Download these
example files: [gauges.csv](../assets/data/gauges.csv),
[rain.csv](../assets/data/rain.csv).

<!-- settings: PRECIP_GAUGE_FILE PRECIP_TIMESERIES_FILE PRECIP_IDW_POWER PRECIP_EXCLUDE_OUTSIDE_STATIONS -->

## 3.4 Satellite rain (NASA IMERG)

IMERG (GPM Integrated Multi-satellitE Retrievals, version 7) gives rain every
**30 minutes** on a **0.1° grid** (about 11 km) over the whole globe. MRRpy
downloads the pixels over your basin from Google Earth Engine and treats the
centre of each pixel as a rain gauge, so Thiessen and IDW work exactly as above.

The download window starts at the storm start, `EVENT_START_UTC`, and lasts for the
simulation length ([`TOTAL_SIMULATION_TIME_HOURS`](routing.md#TOTAL_SIMULATION_TIME_HOURS)).
Times are in **UTC**; the IMERG window can also be given in local time
(`IMERG_START_LOCAL`, `IMERG_END_LOCAL`) with the offset `IMERG_UTC_OFFSET_HOURS`.
The pixels are saved in the results folder (`imerg/gauges.csv`,
`imerg/timeseries.csv`), in the gauge format above, and reused by later runs; tick
`PRECIP_IMERG_FORCE_DOWNLOAD` to fetch them again. The same storm start also sets
the date of the satellite soil-moisture map used by
[soil from satellite](runoff.md#465-soil-from-satellite-data).

IMERG sees large storms well but smooths small, intense cells: an 11 km pixel
averages over the cloudburst. For a small basin, expect peaks to be too low.

<!-- settings: EVENT_START_UTC IMERG_UTC_OFFSET_HOURS IMERG_START_LOCAL IMERG_END_LOCAL IMERG_DATASET IMERG_BAND PRECIP_IMERG_FORCE_DOWNLOAD IMERG_BBOX_BUFFER_M -->

## 3.5 Snow (optional)

In high mountains part of the precipitation falls as snow, which doesn't run off
during a storm. With both elevations set, each cell's precipitation is multiplied
by its **rain fraction**:

$$
f_{\text{rain}}(z) = \min\!\left(1,\ \max\!\left(0,\ \frac{z_{\text{high}} - z}{z_{\text{high}} - z_{\text{low}}}\right)\right)
$$

All rain at or below `RAIN_SNOW_ELEV_LOW`, all snow at or above
`RAIN_SNOW_ELEV_HIGH`, a straight line in between. Set both to the same value for
a sharp snow line. The snow is simply left out of the event; snowmelt isn't
modelled.

<!-- settings: RAIN_SNOW_ELEV_LOW RAIN_SNOW_ELEV_HIGH -->

## Try it

- [Example 1 – Your first run](../examples/first-run.md): a design storm.
- [Example 6 – Rain gauges](../examples/rain-gauges.md): Thiessen and IDW with the files above.
- [Example 7 – A real storm from satellite](../examples/satellite-storm.md): IMERG.
