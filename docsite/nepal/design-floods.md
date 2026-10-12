# Design floods with the physics model

The official formulas give one number per return period from the catchment
area. The physics model gives the whole flood — peak, timing and volume — from
the rain, the soil, the slopes and the river network of *this* catchment. For
small Chure and Terai streams that is exactly what the national formulas lack
(compendium §6). MRRpy-Nepal builds the physics model's design flood from the
same rainfall rules Nepali practice uses, so the two can be compared fairly.

## 1. The design rainfall

The T-year 24-hour rainfall $R_{24}$ comes from DHM data, given either way:

* **typed**, as `return period: mm` pairs — `2: 120, 50: 230, 100: 250` (other
  return periods in between are interpolated on a Gumbel scale), or
* **a rain-gauge record** — one annual maximum daily rainfall per year, fitted
  with Gumbel, LP-III or GEV (`rain_annual_max`, `rain_distribution`). The optional
  daily-to-24-hour factor (WMO: 1.13) corrects once-a-day readings.

Two optional factors multiply $R_{24}$:

| Factor | Default | Use |
|---|---|---|
| areal reduction | 1 | point rainfall → catchment average for larger basins |
| climate factor | 1 | e.g. 1.10 for +10 % — the ToR's climate delta factors |

## 2. The storm

$R_{24}$ is spread in time with the **Mononobe curve**, the rule the official
Rational method uses for the intensity at the time of concentration:

$$
I(t) = \frac{R_{24}}{24}\left(\frac{24}{t}\right)^{2/3}
\quad\Longrightarrow\quad
D(t) = R_{24}\left(\frac{t}{24}\right)^{1/3},
$$

where $D(t)$ is the depth in the most intense $t$ hours. The storm is built by
**alternating blocks**: the largest block in the middle, the next largest on
alternate sides. Every duration inside the storm then carries its Mononobe depth
— the most intense hour, the most intense 3 hours, the whole day — so one storm
suits catchments of any response time. A 24-hour storm holds $R_{24}$ exactly; a
shorter one holds the Mononobe depth for its length. A uniform storm is offered
too.

The storm is written as the two rain-gauge CSV files MRRpy already reads with
[[PRECIP_METHOD]] `thiessen` (one gauge), so the physics model needs no new rain
option. `MRRpy nepal design-storm --rain24 250` and the QGIS tool *4. Nepal design
storm* write them for any run of your own.

## 3. The model

By default (offline, no extra data):

| Part | Setting |
|---|---|
| Runoff | SCS curve number, one value (default 75), normal wetness — [[RUNOFF_SOURCE]] `scs_cn` |
| Routing | kinematic wave — [[ROUTING_SCHEME]] |
| Channels | sized by the official 2-year flood: [[CHANNEL_QBF_M3S]] `wecs_nepal` |
| High ground | rain share 1 below 3,000 m, falling to 0 at 5,000 m — [[RAIN_SNOW_ELEV_LOW]] / [[RAIN_SNOW_ELEV_HIGH]] |

The last row follows the idea behind the official A₃₀₀₀ rule: ground above
3,000 m gives little flood runoff (less rain, and snow). Untick *Less rain above
3,000 m* (or `--no-snow-ramp`) to switch it off.

For your own model — Green–Ampt with soils from Earth Engine, another routing
scheme, roughness by land cover — give a config file (*Model settings file*,
`--model-config run.yaml`, or a config file as the site). Only its rainfall is
replaced by the design storm.

The model runs once per return period: by default the structure's design return
period (100 years for a bridge), or any you list (*Return periods to simulate*,
`--physics-T 50 100`). The run length is the storm plus four Kirpich times of
concentration (at least 6 h).

## 4. The result

For each return period the physics flood is reported with its peak, the time of
the peak, the volume, the runoff ratio and its place against the official range.
This is the report line of the small synthetic basin in MRRpy's test suite
(0.11 km², a 3-hour storm, curve number 80):

```text
T = 100 years: 125 mm in 3 h (R24 250 mm) → peak 3.187 m³/s at 2.0 h,
volume 0.00774 Mm³, runoff ratio 0.57. It is below the official range
(4.169–15.77 m³/s), 0.3196× the official median.
```

Each run writes to `<results>/nepal/design_T<T>/`: `hyetograph.csv`, the storm's
gauge files, `hydrograph.csv`, and `gauges.csv` and maps when
[[ROUTING_GAUGES]] or [[SAVE_FIELDS]] are set — so the 100-year flood can be
mapped with [`export_peak_maps`](../reference/api.md#plotting). The results
folder's own `hydrograph.csv` and `gauges.csv` are left as they were.

!!! tip "When the physics flood is outside the official range"
    That is not by itself wrong — the national formulas were fitted mostly to
    large mountain rivers. Check the inputs first: the design rainfall, the
    curve number (or soil parameters) and the roughness. Then compare with any
    gauge nearby (frequency analysis) or surveyed flood marks (`observed_floods`).
    Calibrating the model to a gauge or to flood marks is planned (see
    `NEPAL_PLAN.md`).

## 5. Bankfull presets for any MRRpy run

The channel of every river cell carries the bankfull flow, about the 2-year
flood. Three Nepal presets of [[CHANNEL_QBF_M3S]] evaluate an official 2-year
flood at every cell:

| Preset | Formula |
|---|---|
| `wecs_nepal` | $1.8767\,(A_{3000}+1)^{0.8783}$ — WECS/DHM 1990 |
| `dhm2004_nepal` | $2.29\,A_{3000}^{0.86}$ — DHM 2004 |
| `specific_q_nepal` | $4.2\,A^{0.70}$ — WECS 2019 specific discharge |

```yaml
CHANNEL_QBF_M3S: dhm2004_nepal
```
