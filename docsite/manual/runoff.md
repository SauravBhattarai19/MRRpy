# 4 Runoff

Not all rain runs off. Some soaks into the soil, and how much depends on the
soil, how wet it already is, and the land cover. This step turns the rain rate of
every cell into a **runoff rate**, the part that flows over the surface and is
[routed](routing.md). Whatever soaks in leaves the model.

!!! info "Where to set it"
    Notebook form: step **4 Runoff** (for *physical*, each ticked process opens
    its own settings) · Wizard: part **3 Runoff** · QGIS: tab **3 · Runoff**.

## 4.1 Runoff method

| Method | `RUNOFF_SOURCE` | Idea | Needs |
|---|---|---|---|
| None | `none` (0) | all rain runs off | nothing |
| Coefficient | `coefficient` (1) | a fixed fraction of the rain runs off, per cell | a raster of fractions |
| Raster | `raster` (2) | you supply the runoff, from another model | runoff rasters over time |
| SCS Curve Number | `scs_cn` (3) | the classic empirical event method | a curve number (one value, a raster, or a global map) |
| Physical | `physical` (4) | soil physics: impervious areas, infiltration and/or saturation | soil values (typed, or from global maps) |

Which to choose:

- To **test routing**, or when rain already is runoff (say, on rock or pavement),
  use **`none`**. It gives the largest flood.
- For a **design study** with standard methods, use **`scs_cn`**. One number per
  cell, widely tabulated, and a global map exists.
- To **represent how a storm actually runs off**, use **`physical`**. It models
  storms on dry soil (infiltration excess) and on wet valleys (saturation excess),
  and it responds to how wet the basin is before the storm.
- To **couple MRRpy to another model**, use **`raster`**.

<!-- settings: RUNOFF_SOURCE -->

## 4.2 None: all rain runs off

The runoff rate equals the rain rate. Nothing soaks in, so the water balance is
simple: everything that falls either leaves at the outlet or is still on its way.

## 4.3 Runoff coefficient

Each cell sheds a fixed fraction $C$ of its rain, read from a raster:

$$
q = C \cdot P, \qquad 0 \le C \le 1
$$

It is the distributed form of the rational method. The raster may be in any
projection and resolution; it is resampled to the model grid. The fraction
never changes during the storm, so it can't tell a dry start from a wet one.

<!-- settings: RUNOFF_COEFFICIENT_PATH -->

## 4.4 Runoff from rasters (bring your own)

Use runoff maps computed elsewhere, such as a land-surface model. List them in a
CSV with the time each map applies (seconds from the start of the run):

```text
time_s,filepath
0,runoff_0000.tif
3600,runoff_3600.tif
7200,runoff_7200.tif
```

Each map holds the **runoff rate in m/s** (not mm). Between listed times the
rate is interpolated linearly. A single map is used for the whole run. Maps
may be in any projection; they are resampled to the model grid. The rain
settings are ignored for runoff in this mode.

<!-- settings: RUNOFF_RASTER_MANIFEST -->

## 4.5 SCS Curve Number

The Soil Conservation Service (now NRCS) method relates the **cumulative**
runoff depth $Q$ to the cumulative rain depth $P$ since the start of the storm,
through one number, the curve number $CN$ (from about 30 for very permeable
soil to 98 for pavement):

$$
S = \frac{25400}{CN} - 254, \qquad I_a = \lambda S, \qquad
Q = \begin{cases} \dfrac{(P - I_a)^2}{P - I_a + S} & P > I_a \\ 0 & P \le I_a \end{cases}
\quad [\text{mm}]
$$

$S$ is the soil's potential retention, $I_a$ the **initial abstraction** (rain
caught before any runoff starts), and $\lambda$ is `RUNOFF_SCS_Ia_FACTOR` (0.2 in
the original method; 0.05 is often better for urban areas). MRRpy evaluates this
for every cell at every step, and the runoff rate is the increase of $Q$ during
the step.

**Antecedent moisture** (`RUNOFF_CN_AMC`) shifts the curve number for a dry
(I), normal (II) or wet (III) start. Tables give AMC II values; MRRpy converts
them with the standard formulas (Chow, Maidment & Mays 1988):

$$
CN_{\text{I}} = \frac{CN_{\text{II}}}{2.281 - 0.01281\,CN_{\text{II}}}, \qquad
CN_{\text{III}} = \frac{CN_{\text{II}}}{0.427 + 0.00573\,CN_{\text{II}}}
$$

CN 75 becomes 57 dry and 88 wet, and the runoff changes by a lot (see
[Example 4](../examples/runoff-methods.md)).

**Where the curve numbers come from** (`RUNOFF_CN_SOURCE`):

- `scalar`: one value, `RUNOFF_CN`, for every cell.
- `raster`: your GeoTIFF (`RUNOFF_CN_PATH`), as AMC II values. Gaps take `RUNOFF_CN`.
- `gee`: **GCN250** (Jaafar et al. 2019), a global 250 m curve-number map from
  soil and land cover, downloaded from Earth Engine. It has separate dry, average
  and wet maps, so the AMC picks the map instead of the formula. The map is saved
  as `cn_gcn250_amc<i|ii|iii>.tif` in the results folder. This is the default
  source, so `scs_cn` needs an Earth Engine sign-in unless you choose `scalar` or
  `raster`.

<!-- settings: RUNOFF_CN_SOURCE RUNOFF_CN_AMC RUNOFF_CN RUNOFF_CN_PATH RUNOFF_SCS_Ia_FACTOR -->

## 4.6 Physical runoff

The physical method builds runoff from up to three processes. You pick any
combination in `RUNOFF_MECHANISMS`:

| Process | Also called | What happens | Typical place |
|---|---|---|---|
| `impervious` | urban runoff | paved and built-up surfaces shed all their rain | cities |
| `infiltration_excess` | Hortonian flow | rain falls faster than the soil can take it in | intense storms, crusted or clay soils, dry slopes |
| `saturation_excess` | Dunne flow, variable source area | the soil is full, so all rain runs off | valley bottoms and near streams, long wet storms |

They are combined in each cell without counting any water twice. With $Imp$ the
impervious fraction of the cell:

$$
q = P \cdot \Big[\, Imp + (1 - Imp)\cdot \max\big(s,\ f_{\text{IE}}\big) \Big]
$$

where $s$ is 1 if the cell lies in the saturated area and 0 if not, and
$f_{\text{IE}}$ is the infiltration-excess fraction of the rain. The impervious
part always runs off. On the rest, a saturated cell sheds all its rain;
otherwise the infiltration-excess share runs off. A process you leave out counts
as zero: `["infiltration_excess"]` alone is a Green–Ampt model like those in GSSHA
or HEC-HMS, and `["saturation_excess"]` alone is the VSA-OPM model of Pradhan &
Ogden (2010).

The run's water balance reports how much runoff each process made: the
`dunne_*`, `horton_*` and `imperv_*` columns of `mass_balance.csv`, and over time
in `partition.csv`.

<!-- settings: RUNOFF_MECHANISMS -->

### 4.6.1 Impervious areas

Roofs, roads and paving shed all the rain that falls on them. Each cell gets an
impervious fraction $Imp$ between 0 and 1:

- `lulc`: from ESA WorldCover land cover (10 m, downloaded from Earth Engine)
  through the `impervious_fraction` column of the land-cover table. With the
  built-in table, *Built-up* is 0.85 and everything else 0.
- `lcz`: from the WUDAPT Local Climate Zones map: a finer split of urban types,
  from 0.95 for *compact high-rise* to 0.2 for *sparsely built*.
- `raster`: your own GeoTIFF of fractions.
- `none`: no impervious area (the process then does nothing).

The tables are described under
[land-cover tables](roughness.md#543-land-cover-tables).

<!-- settings: IMPERVIOUS_SOURCE IMPERVIOUS_RASTER_PATH -->

### 4.6.2 Infiltration excess (Green–Ampt)

Soil can take in water only so fast. The Green–Ampt model gives that
**infiltration capacity** $f_p$, which is high at the start of a storm and falls
towards the saturated conductivity as the soil wets up:

$$
f_p = K_v \left( 1 + \frac{\psi \, \Delta\theta_0}{F} \right),
\qquad
f_{\text{IE}} = \frac{\max(P - f_p,\ 0)}{P}
$$

| Symbol | Meaning | Setting |
|---|---|---|
| $K_v$ | vertical saturated hydraulic conductivity: how fast saturated soil drains | `GA_KSAT_MMHR` or a map |
| $\psi$ | wetting-front suction head: how strongly dry soil pulls water in | `GA_SUCTION_M` or from texture |
| $\Delta\theta_0$ | initial moisture deficit: how much empty pore space the soil has at the start (fraction) | from the soil-storage settings below |
| $F$ | depth infiltrated since the current storm began (updated every step) | — |

**$K_v$, the most important value.** Typical values: sand ~50 mm/h, loam ~10,
clay ~1. `GA_KSAT_SOURCE = gee` reads the global **HiHydroSoil v2.0** map and
averages it over the top `GA_KSAT_DEPTH_CM` of soil (a layered, harmonic mean:
the slowest layer controls). Use 30 cm for short cloudbursts, 60 cm (default)
for most storms, and 100 cm for long frontal rain on soils with a tight clay
subsoil. `GA_KSAT_SCALE` multiplies the map, for calibration.

**$\psi$.** `GA_SUCTION_SOURCE = texture` reads sand and clay content from
SoilGrids, finds the USDA texture class and takes $\psi$ from Rawls et al.
(1983): sand 4.95 cm, loamy sand 6.13, sandy loam 11.01, loam 8.89, silt loam
16.68, sandy clay loam 21.85, clay loam 20.88, silty clay loam 27.30, sandy clay
23.90, silty clay 29.22, clay 31.63.

**$\Delta\theta_0$** is the soil-moisture deficit divided by the root-zone depth
of the cell's land cover. The deficit comes from the satellite soil-moisture map
when [soil storage comes from satellite data](#465-soil-from-satellite-data).
Otherwise it is `VSA_SD_MAX_INITIAL` divided by the mean root-zone depth, capped
at 1.

When saturation excess is on too, the infiltration capacity also limits how fast
rain can recharge its soil store (below).

**Drying out between storms.** Green–Ampt describes one storm. Without any
drying, $F$ keeps growing over a long run, and after a few storms $f_p$
stays at $K_v$ for good, as if the soil never dried. With `GA_RECOVERY` on
(the default), MRRpy uses the recovery method of EPA SWMM 5 (Rossman & Huber
2016). The water that soaks in fills a thin **upper soil zone**. That zone
drains in dry weather, and after a long enough dry spell the next rain counts
as a **new storm**, which meets partly dried soil. Everything follows from
$K_v$, written $K_s$ in inches per hour as in SWMM:

| Quantity | Formula | $K_v$ = 1 / 10 / 50 mm/h |
|---|---|---|
| depth of the upper zone, $L_u$ | $4\sqrt{K_s}$ inches | 20 / 64 / 143 mm |
| time for a full zone to drain, $1/k_r$ | $75/\sqrt{K_s}$ hours | 378 / 120 / 53 h |
| dry spell that ends a storm, $T_r$ | $4.5/\sqrt{K_s}$ hours | 22.7 / 7.2 / 3.2 h |

The zone holds at most $F_{u,max} = \Delta\theta_0 L_u$. Rain adds the
infiltrated depth to its content $F_u$. Each dry step drains
$k_r F_{u,max}\,\Delta t$ from both $F_u$ and $F$. Rain lighter than $K_v$
does not stop the dry-spell clock; rain heavier than $K_v$ restarts it. When
the clock passes $T_r$, a new storm starts with $F = 0$ and
$\Delta\theta = (F_{u,max} - F_u)/L_u$. A fully drained zone returns the soil
to $\Delta\theta_0$. So $\Delta\theta_0$ is both the starting dryness and
the driest the soil gets. For a run of months or years, start it in the dry
season, so that the starting soil moisture describes dry soil.

<!-- settings: GA_SUCTION_SOURCE GA_SUCTION_M GA_KSAT_SOURCE GA_KSAT_MMHR GA_KSAT_DEPTH_CM GA_KSAT_RASTER GA_KSAT_SCALE GA_RECOVERY -->

### 4.6.3 Saturation excess (VSA-OPM)

In humid, hilly basins most storm runoff comes from **saturated areas** near
streams and in hollows. They grow during a storm as the soil fills, and shrink
again afterwards: a *variable source area*. MRRpy uses the **One-Parameter Model
(OPM)** of Pradhan & Ogden (2010), which predicts the saturated area from
topography alone.

**Which cells are saturated.** A cell is saturated when the area draining
through it, $A$, exceeds a basin-wide **threshold area** $A_t$. Cells with a large
upslope area (valley bottoms) saturate first. The threshold at the start comes
from the river flow before the storm, $Q_{max}$ (`VSA_Q_MAX`):

$$
A_{t,0} = \frac{A_{outlet}}{1 - \ln\left(Q_{min}/Q_{max}\right)}, \qquad Q_{min} = 0.001\ \text{m}^3/\text{s}
$$

A larger pre-storm flow means a lower threshold: a wetter basin with more of it
saturated from the start.

**How the saturated area grows.** A one-cell "sandbox" at the drainage divide
tracks the thickness $z$ of the saturated layer. Rain that soaks in raises it;
water draining sideways downhill lowers it:

$$
\phi \frac{dz}{dt} = f - \frac{K_{sat}\, S_{div}\, z\, \Delta x}{A_{cell}}
$$

with $\phi$ the drainable porosity (`VSA_PHI`), $f$ the recharge (the rain on
the pervious part, limited by the Green–Ampt capacity when that process is on),
$K_{sat}$ the sideways conductivity (`VSA_K_SAT`), $S_{div}$ the slope at the
divide and $\Delta x$ the cell size. As $z$ rises, the soil's remaining storage
$SD_{max}(t) = \max(SD_{min},\ SD_{max,0} - z)$ shrinks (`VSA_SD_MAX_INITIAL`
and `VSA_SD_MIN`), and the threshold area falls:

$$
A_t = \frac{H_a\, A_{cell}}{H_a - \ln\!\big(SD_{min}/SD_{max}(t)\big)},
\qquad H_a = \frac{A_{t,0}}{A_{t,0} - A_{cell}} \ln\frac{SD_{min}}{SD_{max,0}}
$$

When the store is full ($SD_{max} = SD_{min}$), $A_t$ reaches one cell and the
whole basin is saturated. When rain stops, the store drains and the saturated
area shrinks again.

**Rainfall zones.** With gauge or satellite rain, each rainfall zone (see
[3.1](precipitation.md#31-rain-source)) can get its own sandbox
(`VSA_PER_POLYGON`), so a zone that got more rain saturates sooner. A design
storm has one zone.

<!-- settings: VSA_SD_MAX_INITIAL VSA_PHI VSA_K_SAT VSA_Q_MAX VSA_SD_MIN VSA_PER_POLYGON VSA_BASEFLOW -->

### 4.6.4 Choosing soil values

**Green–Ampt values by soil texture** (Rawls, Brakensiek & Miller 1983, as
tabulated by Chow, Maidment & Mays 1988). The suction column is the one MRRpy
uses for `GA_SUCTION_SOURCE = texture`. The conductivities were measured on soil
samples; soils with roots, worm holes and cracks often take water in several
times faster, so treat them as a lower bound.

| Texture | $\psi$ (`GA_SUCTION_M`, m) | $K_v$ (`GA_KSAT_MMHR`, mm/h) |
|---|---|---|
| Sand | 0.050 | 117.8 |
| Loamy sand | 0.061 | 29.9 |
| Sandy loam | 0.110 | 10.9 |
| Loam | 0.089 | 3.4 |
| Silt loam | 0.167 | 6.5 |
| Sandy clay loam | 0.219 | 1.5 |
| Clay loam | 0.209 | 1.0 |
| Silty clay loam | 0.273 | 1.0 |
| Sandy clay | 0.239 | 0.6 |
| Silty clay | 0.292 | 0.5 |
| Clay | 0.316 | 0.3 |

**Saturation-excess values** have no standard table; think about what each one
does:

- `VSA_Q_MAX`, the flow before the storm, sets how much of the basin is
  saturated at the start. Use the observed flow at the outlet if you have it.
- `VSA_SD_MAX_INITIAL`, the soil's storage, sets how much rain the basin can
  store before it saturates. Larger means saturated areas grow later.
- `VSA_PHI` turns infiltrated water into a rise of the saturated layer: a smaller
  value fills the store faster.
- `VSA_K_SAT` drains the store sideways between storms and during light rain.
  Larger means the saturated area shrinks faster.

If you have an observed hydrograph, compare the **runoff volume** first
([`runoff_ratio`](outputs.md#65-the-water-balance) in `mass_balance.csv`), then
the peak.

### 4.6.5 Soil from satellite data

With `VSA_SD_SOURCE = gee`, the soil storage comes from global maps for the day
of the storm instead of typed values:

$$
\text{deficit} = \big(\phi_{total} - \theta\big) \cdot Z_r
$$

- $\theta$, the soil moisture before the storm, by the **SERVES** method: the
  latest vegetation greenness (NDVI) from Landsat, Sentinel-2 or MODIS
  (`SERVES_SATELLITE`), up to `SERVES_SEARCH_WINDOW` days before
  `EVENT_START_UTC`, placed between the wilting point and field capacity from
  SoilGrids (layer `SOILGRIDS_DEPTH`).
- $\phi_{total}$, the porosity, from HiHydroSoil v2.0.
- $Z_r$, the root-zone depth of the land cover, from the
  [land-cover table](roughness.md#543-land-cover-tables).

The deficit map (saved as `deficit_serves_<date>.tif`) sets the starting
storage of each rainfall zone, summarised by `VSA_SD_REDUCER`, and the
Green–Ampt $\Delta\theta_0$ of every cell. The drainable porosity becomes the
basin mean of porosity minus field capacity. If the download fails, MRRpy
says so and uses the typed values.

<!-- settings: VSA_SD_SOURCE VSA_SD_REDUCER VSA_DEFICIT_RASTER SERVES_SATELLITE SERVES_SEARCH_WINDOW SOILGRIDS_DEPTH -->

## Try it

- [Example 4 – Runoff methods](../examples/runoff-methods.md): none vs SCS (dry, normal, wet) vs Green–Ampt.
- [Example 5 – Physical runoff processes](../examples/physical-runoff.md): infiltration, saturation, both.
- [Example 7 – A real storm from satellite](../examples/satellite-storm.md): GCN250 curve numbers with IMERG rain.

!!! tip "Your own runoff method"
    Runoff methods are plug-ins: a new `RUNOFF_SOURCE` can be registered from your
    own code without changing MRRpy. See [For developers](../reference/developers.md).
