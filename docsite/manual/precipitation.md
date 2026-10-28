# 3 Precipitation

This step decides **where the rain comes from**: the same design storm
everywhere, your own rain-gauge records, NASA's IMERG satellite rainfall, or
weather-model rain from Open-Meteo, for a past storm or a forecast. Each
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
| Weather models | `openmeteo_thiessen` (5) or `openmeteo_idw` (6) | internet and the storm date | a past event anywhere, a **forecast** up to 16 days ahead, or a forecast hindcast |

The gauge, satellite and weather-model sources all start from rain at **points**
(gauges, or the centres of satellite pixels or model cells) and spread it to the
cells in one of two ways:

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

## 3.5 Weather-model rain (Open-Meteo)

[Open-Meteo](https://open-meteo.com) serves the rain of the world's weather
models (ECMWF, NOAA GFS and HRRR, DWD ICON, Météo-France, JMA and others) and of
reanalyses such as ERA5 through a free web API. It needs an internet
connection but **no account and no Earth Engine**. One setting covers both a
**past storm** and a **forecast**: set the storm start, `EVENT_START_UTC`, and
MRRpy downloads the rain from then for the simulation length
([`TOTAL_SIMULATION_TIME_HOURS`](routing.md#TOTAL_SIMULATION_TIME_HOURS)), in UTC.
A start today or in the next few days gives the latest forecast.

### Which archive

`OPENMETEO_SOURCE` says which Open-Meteo archive to read:

| `OPENMETEO_SOURCE` | Open-Meteo API | Covers | Use it for |
|---|---|---|---|
| `auto` (default) | forecast or historical, picked from the storm date | everything below except single runs | most runs |
| `forecast` | Forecast API | the last 3 months and up to 16 days ahead | a forecast, a recent storm |
| `historical` | Historical Weather API | 1940 to a few days ago | old storms, long records |
| `historical_forecast` | Historical Forecast API | the high-resolution models, from 2021 to 2023 depending on the model | a past storm as the models saw it |
| `single_run` | Single Runs API | one model run, from March 2024 for ECMWF IFS (later for the others) | a forecast hindcast |

`historical_forecast` joins the first hours of every model run end to end, so it
is close to what really fell, not to what was forecast days ahead. To see what a
forecast issued at a given time predicted, with no look-ahead, use `single_run`:
set `OPENMETEO_RUN` to the time the run was issued (it defaults to the storm
start) and a specific `OPENMETEO_MODEL`. The time from `OPENMETEO_RUN` to
`EVENT_START_UTC` is the lead time.

```yaml
PRECIP_METHOD: openmeteo_thiessen
EVENT_START_UTC: "2024-09-27 00:00"
OPENMETEO_SOURCE: single_run
OPENMETEO_RUN: "2024-09-25 00:00"       # the ECMWF forecast issued two days earlier
OPENMETEO_MODEL: ecmwf_ifs
```

### Which model

`OPENMETEO_MODEL` picks the model by its Open-Meteo name. The default is
`best_match`.

**What `best_match` is.** Despite the name, it is **not** the model that
matches observations best: it uses no rain gauges and no accuracy scores, so it
works the same in an ungauged basin. It is a fixed rule of Open-Meteo's. On a
backbone of three global models (ECMWF IFS, NOAA GFS and DWD ICON) it adds the
regional high-resolution models that cover the place. For every hour the
**finest-grid model with data wins**, and coarser ones fill in where it stops
(past its forecast length, or outside its area). In the historical archive it
joins ECMWF IFS (9 km, from 2017), ERA5 and ERA5-Land. Over Nepal it gives
ECMWF IFS; in the historical archive, ERA5 up to 2016 and ECMWF IFS from 2017
(set `OPENMETEO_MODEL: era5` for ERA5 in every year).

Which regional models are added depends on where the basin is. Open-Meteo checks
its regions in this order and the first that contains the basin wins
([its list](https://open-meteo.com/en/docs) may change):

| Region | Added on top of the global models |
|---|---|
| Netherlands and Belgium | KNMI HARMONIE, ICON-EU, ICON-D2 |
| Scandinavia | MET Nordic |
| UK and Ireland | UK Met Office 2 km and 10 km |
| Central Europe (Germany) | ICON-EU, ICON-D2 (true 15-minute rain) |
| France and Western Europe | AROME France HD (1.5 km), ARPEGE (true 15-minute rain) |
| Northern Europe and Iceland | DMI HARMONIE |
| North America | NOAA HRRR (true 15-minute rain) |
| Japan | JMA MSM |
| the rest of Europe | ICON-EU |
| everywhere else | nothing: the global models only |

So one forecast can come from several models, one after another. Checked hour by
hour in October 2026: over **Kathmandu** it was ECMWF IFS from the start to about
day 10; over **Denver**, HRRR for the first day and then GFS; over **Berlin**,
ICON-D2 for the first day, then ICON-EU and ICON, and ECMWF IFS by days 7–10. The
switches are blended over a few hours. Where the global models are the only
choice, `best_match` is in practice ECMWF IFS, and `OPENMETEO_MODEL: ecmwf_ifs`
gives nearly the same rain under a name you know.

MRRpy places its rain gauges at the cell centres of the **first** model (the
finest). Later hours may come from a coarser model, read at its own cell nearest
the same point: the gauges stay put, but the rain of a forecast several days out
is coarser than the gauge spacing suggests.

So "best" means "finest grid available here", which is a sensible guess where
rain depends on terrain, but not proof of accuracy. MRRpy uses it as the default
because it is the **only name that works everywhere and in every archive** (a
named model can be empty outside its area or before its archive starts), not
because it is the most accurate. `single_run` needs a named model.

Observations still sit behind every model: each starts its run from the world's
satellite, weather-station and balloon data (data assimilation), and ERA5 is
built entirely that way. None of them is corrected to the rain that fell in
your basin. Models give quite different rain for the same storm (61 to 174 mm
over Kathmandu on 27 September 2024), so in an ungauged basin it is worth
running a few models, or IMERG as well, and looking at the spread. These names gave rain when tested in October 2026;
the full list is on [open-meteo.com](https://open-meteo.com/en/docs).

**Global models** (with `forecast`, `historical_forecast` and, for recent runs,
`single_run`):

| `OPENMETEO_MODEL` | Model |
|---|---|
| `best_match` | the finest-grid model covering the place, hour by hour (default) |
| `ecmwf_ifs`, `ecmwf_ifs025` | ECMWF IFS, 9 km and 0.25° |
| `ecmwf_aifs025_single` | ECMWF AIFS, the machine-learning model |
| `gfs_seamless`, `gfs_global` | NOAA GFS (seamless adds HRRR over the USA) |
| `ncep_aigfs025` | NOAA's machine-learning GFS |
| `icon_seamless`, `icon_global` | DWD ICON (seamless adds ICON-EU and ICON-D2) |
| `ukmo_seamless`, `ukmo_global_deterministic_10km` | UK Met Office |
| `meteofrance_seamless`, `meteofrance_arpege_world` | Météo-France ARPEGE (seamless adds AROME) |
| `gem_seamless`, `gem_global` | Environment Canada GEM |
| `jma_seamless`, `jma_gsm` | Japan Meteorological Agency |
| `cma_grapes_global` | China Meteorological Administration GRAPES |
| `metno_seamless` | MET Norway, with a global model outside the Nordic area |

**Regional high-resolution models** (only inside their area):

| `OPENMETEO_MODEL` | Area |
|---|---|
| `icon_eu`, `icon_d2` | Europe; Germany and the Alps (DWD) |
| `meteofrance_arpege_europe`, `meteofrance_arome_france`, `meteofrance_arome_france_hd` | Europe; France |
| `knmi_harmonie_arome_europe`, `knmi_harmonie_arome_netherlands`, `knmi_seamless` | Europe; the Netherlands |
| `dmi_harmonie_arome_europe`, `dmi_seamless` | Europe; Denmark |
| `meteoswiss_icon_ch1`, `meteoswiss_icon_ch2` | Switzerland and the Alps |
| `ukmo_uk_deterministic_2km` | the UK |
| `metno_nordic` | Norway, Sweden, Finland |
| `italia_meteo_arpae_icon_2i` | Italy |
| `gfs_hrrr`, `ncep_hrrr_conus`, `ncep_nbm_conus`, `ncep_nam_conus` | the contiguous USA |
| `gem_regional`, `gem_hrdps_continental` | Canada |
| `jma_msm` | Japan |

**Historical archive** (`OPENMETEO_SOURCE: historical`):

| `OPENMETEO_MODEL` | Data |
|---|---|
| `best_match` | ERA5 up to 2016, ECMWF IFS from 2017 |
| `era5`, `era5_seamless` | ERA5 reanalysis, 0.25°, hourly, from 1940 |
| `era5_ensemble` | the mean of the ERA5 ensemble |
| `ecmwf_ifs` | ECMWF IFS analyses, 9 km, from 2017 |
| `ecmwf_ifs_analysis_long_window` | ECMWF IFS long-window analyses |

Some names that Open-Meteo lists return **no rain**: `era5_land`, `cerra`,
`bom_access_global`, `kma_seamless`, `kma_gdps` and `kma_ldps`. A model outside
its area, or dates before its archive starts, also return nothing. MRRpy then
stops with "Open-Meteo returned no precipitation for this area and window"
instead of running with zero rain.

**How the rain becomes gauges.** MRRpy asks for rain at a regular grid of points
over the basin, `OPENMETEO_POINT_SPACING_M` apart (5 km) and reaching
`OPENMETEO_BBOX_BUFFER_M` (10 km) beyond it. Open-Meteo answers each point from
the model cell it falls in and says where that cell's centre is. Points in the
same cell merge, so every model cell becomes one rain gauge at its centre, like
the IMERG pixels, and Thiessen or IDW spread the rain over the basin. A spacing
smaller than the model's cells samples every cell; MRRpy widens it if more than
400 points would be needed.

**Time step.** Open-Meteo always returns rain **every hour** (every 15 minutes
with `OPENMETEO_MINUTELY_15`), as the depth that fell in the hour before each
time: the same convention as the [gauge file](#33-rain-gauges). But not every
model computes rain that often. Where a model only gives a 3- or 6-hour total,
Open-Meteo spreads it evenly over those hours, so the hourly values are flat
and short bursts are averaged out. Measured in October 2026 (hours of forecast
lead time):

| Data | 0–90 h | 90–144 h | after 144 h |
|---|---|---|---|
| `best_match`, `ecmwf_ifs` | 1 h | 3 h | 6 h |
| `ecmwf_ifs025` | 3 h | 3 h | 6 h |
| `ecmwf_aifs025_single`, `jma_gsm` | 6 h | 6 h | 6 h |
| `gfs_seamless`, `gem_global`, `icon_global` | 1 h for the first 2–4 days, then 3 h | | |
| `cma_grapes_global` | 3 h | 3 h | — |
| `historical` archive (`era5`, `ecmwf_ifs`) | 1 h | | |
| `historical_forecast` | the first hours of each run: mostly 1 h | | |

A forecast more than about 4 days ahead therefore smooths the storm into 3- or
6-hour blocks; expect lower peak flows than the same rain hourly would give. A
`single_run` follows the same table, counted from `OPENMETEO_RUN`. (IMERG, for
comparison, is every 30 minutes.)

`OPENMETEO_MINUTELY_15` asks for 15-minute rain. It is truly 15-minute only from
the regional models that compute it (HRRR over the USA, ICON-D2 over Germany and
the Alps, and other European regional models); elsewhere each hour is spread
evenly over its four quarters, which adds nothing. The historical archive has
hourly rain only.

**Saved files.** The rain is saved in the results folder
(`openmeteo/gauges.csv`, `openmeteo/timeseries.csv`, in the gauge format above,
and `openmeteo/openmeteo_meta.json`, which records what was asked). A later run
with the same date, source, model, run and spacing reuses it; changing any of them
downloads the rain again. A saved forecast isn't refreshed by itself: tick
`PRECIP_OPENMETEO_FORCE_DOWNLOAD` to fetch the latest one. If the window runs past
the end of the forecast (or of the archive), the rain stops there and MRRpy
warns you.

```yaml
PRECIP_METHOD: openmeteo_thiessen
EVENT_START_UTC: "2024-09-27 00:00"     # a past storm; today's date gives a forecast
TOTAL_SIMULATION_TIME_HOURS: 72
OPENMETEO_MODEL: best_match
```

Like IMERG, a weather model smooths small cloudbursts over its cells (2–25 km),
and a forecast is less certain the further ahead it looks: treat a forecast
flood as one possible outcome, not the outcome.

!!! note "Credit Open-Meteo"
    Open-Meteo data are licensed CC BY 4.0: credit "Weather data by
    Open-Meteo.com" when you publish results. The free API is for
    non-commercial use, with a daily limit of about 10 000 requests (each point
    counts roughly as one). For a commercial subscription, set the
    `OPENMETEO_API_KEY` environment variable.

<!-- settings: OPENMETEO_SOURCE OPENMETEO_MODEL OPENMETEO_RUN OPENMETEO_MINUTELY_15 OPENMETEO_POINT_SPACING_M OPENMETEO_BBOX_BUFFER_M PRECIP_OPENMETEO_FORCE_DOWNLOAD -->

## 3.6 Snow (optional)

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
  For weather-model rain instead, set `PRECIP_METHOD: openmeteo_thiessen` in that
  example and keep the rest.
