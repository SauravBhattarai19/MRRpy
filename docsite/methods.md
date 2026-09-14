# Methods

hydroflow separates **runoff generation** (turning rainfall into effective
surface runoff) from **flood routing** (moving that water across the terrain to
the outlet). The two are independent, so *any* runoff method can feed *any*
routing scheme — pick one of each.

Every fixed-choice option accepts its canonical **string** or a 0-based
**integer code** (they are equivalent). List them anytime with
`hydroflow list-options` or `Config.describe_options()`.

```python
Config(RUNOFF_SOURCE="scs_cn",  ROUTING_SCHEME="diffusive")   # strings
Config(RUNOFF_SOURCE=3,         ROUTING_SCHEME=1)             # codes — identical
```

## Runoff generation (`RUNOFF_SOURCE`)

| Method | Code | What it does | Reach for it when… |
|---|---|---|---|
| `none` | 0 | all rainfall becomes runoff | routing-only tests, or runoff handled elsewhere |
| `coefficient` | 1 | rainfall × a static runoff-coefficient map | you have a rational-method / land-cover coefficient |
| `raster` | 2 | replays a precomputed runoff time series | coupling to another model (bring your own runoff) |
| `scs_cn` | 3 | SCS Curve Number | a standard, data-light design-storm method |
| `physical` | 4 | process-based, composable mechanisms | you want explicit infiltration / saturation / urban physics |

### `none` — all rainfall runs off
The whole rainfall rate is passed straight to routing. It is the simplest
setting and the backward-compatible default — useful for testing the router or
for pure routing-only runs (see [Examples #3](examples.md#3-add-an-upstream-boundary-condition-hydrograph)).

### `coefficient` — static runoff coefficient
Effective runoff is `rain × Cf`, where `Cf ∈ [0, 1]` is a per-cell coefficient
read from a GeoTIFF (`RUNOFF_COEFFICIENT_PATH`). This is the distributed analogue
of the rational method. The raster may be in any CRS/resolution — it is
reprojected onto the model grid.

### `raster` — bring your own runoff
Replays a **precomputed effective-runoff time series** (in m/s) so you can bypass
runoff generation entirely and drive the router with output from another
land-surface or hydrologic model. Point `RUNOFF_RASTER_MANIFEST` at a CSV with two
columns:

```csv
time_s,filepath
0,runoff_0000.tif
3600,runoff_3600.tif
7200,runoff_7200.tif
```

Each `filepath` is a single-band, GDAL-readable raster of the runoff **rate in
m/s**; frames may be at irregular times (they are sorted automatically), are
**linearly interpolated** between listed times, and are **reprojected/resampled
onto the model grid** (so any CRS/resolution/extent works). A single frame is
treated as a constant field.

### `scs_cn` — SCS Curve Number
The classic event-cumulative Curve Number method
(`S = 25400/CN − 254`, `Ia = 0.2·S`, `Pe = (P−Ia)²/(P−Ia+S)`). Curve numbers come
from `RUNOFF_CN_SOURCE`: a `scalar` (`RUNOFF_CN`, default 75), a `gee` download of
the global GCN250 dataset [Jaafar et al. 2019], or your own `raster`. Antecedent
moisture (`RUNOFF_CN_AMC`: `i` dry / `ii` normal / `iii` wet) shifts the response.
Full walkthrough in [Examples #6](examples.md#6-scs-curve-number-runoff-gcn250-or-your-own-raster).

### `physical` — process-based, composable mechanisms
Builds effective runoff from explicit physical mechanisms that you enable
individually or together — see the next section.

## Process-based mechanisms (`RUNOFF_MECHANISMS`)

Used only when `RUNOFF_SOURCE="physical"`. Three mechanisms are available and can
be composed in any subset:

| Mechanism | Code | Process | Key parameters |
|---|---|---|---|
| `impervious` | 0 | urban / impervious shedding | `IMPERVIOUS_SOURCE` (LULC · LCZ · raster) |
| `infiltration_excess` | 1 | Hortonian, via Green–Ampt | `GA_KSAT_MMHR`, `GA_SUCTION_M`, `GA_KSAT_SOURCE`, `GA_SUCTION_SOURCE` |
| `saturation_excess` | 2 | Dunne, via the VSA one-parameter model | `VSA_SD_MAX_INITIAL`, `VSA_PHI`, `VSA_K_SAT`, `VSA_SD_SOURCE` |

### `impervious`
An impervious fraction `Imp ∈ [0, 1]` per cell sheds 100 % of its rainfall
regardless of soil. The fraction comes from a land-cover lookup (LULC or LCZ) or
a continuous raster, via `IMPERVIOUS_SOURCE`.

### `infiltration_excess` (Hortonian)
Infiltration-excess ("Horton") overland flow using Green–Ampt infiltration
capacity `f_p = K_v·(1 + ψ·Δθ₀ / F)`, with runoff = `max(rain − f_p, 0)`.
Hydraulic conductivity `K_v` (`GA_KSAT_MMHR`, default 12 mm/hr) and wetting-front
suction ψ (`GA_SUCTION_M`, default 0.15 m) can be scalars, gridded from Earth
Engine, or derived from SoilGrids texture (USDA class → Rawls et al. 1983).

### `saturation_excess` (Dunne)
Saturation-excess ("Dunne") runoff from a dynamically growing/shrinking saturated
source area, using the Variable Source Area **one-parameter model** of
Pradhan & Ogden (2010). A per-zone "sandbox" water balance tracks the
saturated-zone thickness and updates the contributing area each step. Deficit and
soil parameters (`VSA_SD_MAX_INITIAL`, `VSA_PHI`, `VSA_K_SAT`) can be set manually
or sourced from Earth Engine (SERVES) via `VSA_SD_SOURCE`.

### Composing mechanisms
`RUNOFF_MECHANISMS` is any subset of the three — so you can isolate a single
process or combine them:

```python
cfg.RUNOFF_MECHANISMS = ["infiltration_excess"]                     # Horton only
cfg.RUNOFF_MECHANISMS = ["saturation_excess"]                       # VSA / Dunne only
cfg.RUNOFF_MECHANISMS = ["impervious"]                              # urban shedding only
cfg.RUNOFF_MECHANISMS = ["impervious", "infiltration_excess",
                         "saturation_excess"]                       # all three (default)
```

The mechanisms are combined without double-counting:

```
runoff = rain · [ Imp + (1 − Imp) · max(in_VSA, infiltration_excess_fraction) ]
```

On the pervious fraction a cell sheds all rain if it lies in the saturated source
area (Dunne), otherwise the Green–Ampt infiltration-excess fraction (Horton) — the
two are mutually exclusive per cell. The Dunne / Horton / impervious split is
reported in the mass-balance output, and always sums exactly to the effective
runoff. A worked, everything-on run is [Examples #5](examples.md#5-capstone-everything-together).

## Routing (`ROUTING_SCHEME`)

Three interchangeable channel-routing schemes run on the D8 drainage network:

| Scheme | Code | What it is | Reach for it when… |
|---|---|---|---|
| `kinematic` | 0 | kinematic wave (Manning on bed slope) | steep terrain; fastest; no backwater |
| `diffusive` | 1 | diffusive wave (water-surface slope) | mild slopes / backwater matter |
| `muskingum` | 2 | variable-parameter Muskingum–Cunge | channel routing with matched diffusion |

### `kinematic`
Discharge from Manning's equation on the **bed** slope. The lightest, fastest
option; it cannot represent backwater or adverse gradients.

### `diffusive`
Diffusive-wave routing (CASC2D/GSSHA-style): the friction slope is the
**water-surface** slope, so the scheme captures backwater and flow over mild or
flat reaches. `DIFFUSION_THETA` blends bed and water-surface slope
(0 → kinematic, 1 → full diffusion; default 1).

### `muskingum`
Variable-parameter Muskingum–Cunge (Ponce–Yevjevich): the routing coefficients
are tuned so the scheme's numerical diffusion matches the reach's physical
hydraulic diffusivity.

!!! note "Shared routing machinery"
    All three schemes use the same adaptive CFL time-stepping, a
    volume-conservative flux limiter, and always-on mass-balance reporting — so
    results from different schemes are directly comparable on the same terrain and
    forcing.

## Selecting a method

Set `RUNOFF_SOURCE`, `RUNOFF_MECHANISMS`, and `ROUTING_SCHEME` on the
[`Config`](configuration.md) object (by name or code), then run the pipeline. See
the [Configuration](configuration.md) reference for every parameter and the
[Examples](examples.md) for end-to-end recipes.

!!! tip "Add your own runoff method"
    Runoff generation is pluggable: you can register a brand-new `RUNOFF_SOURCE`
    from your own package without editing hydroflow. See the
    [API reference](api.md) for the `@register` decorator and the `RunoffMode`
    contract.
