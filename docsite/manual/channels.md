# 5.5 River channels

A 90 m cell is far wider than most rivers. If the river's water were spread over
the whole cell, it would be a few centimetres deep and would move far too
slowly. MRRpy therefore gives river cells a **channel**: a rectangular
cross-section narrower than the cell, cut into the ground, which carries the flow
until it spills over its banks onto the rest of the cell.

!!! info "Where to set it"
    Notebook form: step **5 Routing** → *River channels* · Wizard: part
    **4 Roughness and river channels** (mostly advanced) · QGIS: tab
    **4 · Routing**, *Confined Channel Routing*.

## 5.5.1 Which cells are rivers

A cell is a river (channel) cell when the area draining through it is larger
than `CHANNEL_MIN_AREA_KM2` (10 km² by default; at most 10 % of the basin, so
small basins still get rivers). You can give the same threshold as a number of
upstream cells, `CHANNEL_FACCUM_THRESHOLD`, which then wins. If both are empty,
the 1 % of cells with the most upstream area are rivers. The same channel cells
get the [channel roughness](roughness.md#542-roughness-of-river-channels).

<!-- settings: CHANNEL_MIN_AREA_KM2 CHANNEL_FACCUM_THRESHOLD -->

## 5.5.2 The channel cross-section

With `CHANNEL_ROUTING` on (the default, and recommended), a river cell has a
rectangular channel of width $W$ and bankfull depth $D$. Water of depth $h$ in
it has

$$
A = W h, \qquad P = W + 2h, \qquad R = \frac{A}{P} = \frac{W h}{W + 2h},
$$

so it runs deeper and faster than a sheet over the whole cell, which gives
realistic flood-wave speeds.

With `CHANNEL_SUBGRID` on (the default), the channel bed lies $D$ **below** the
DEM surface, as in LISFLOOD-FP (Neal et al. 2012). Up to bankfull, water stays
in the channel. Above it, water also spreads over the whole cell as a floodplain
sheet with roughness `MANNINGS_N_FLOODPLAIN` (empty: the ground roughness). The
channel beds are deepened where needed so a bed never steps uphill along a river,
which would make a false dam.

<!-- settings: CHANNEL_ROUTING CHANNEL_SUBGRID MANNINGS_N_FLOODPLAIN -->

## 5.5.3 Channel size

How wide and deep each channel is matters a lot for the flood peak: a channel
that is too small spills early and spreads the flood; one that is too big
carries it fast. `CHANNEL_GEOMETRY` picks how they are sized:

| `CHANNEL_GEOMETRY` | Sized from | Needs |
|---|---|---|
| `discharge` (2, default, recommended) | the **bankfull flow** $Q_{bf}$, about the 2-year flood | nothing (a global estimate), or your 2-year flood, or a formula |
| `area` (1) | drainage area, with regional curves from the USA | a curve choice |
| `order` (0) | Strahler stream order, from two tables | your tables |

### From bankfull flow (`discharge`)

A natural river is about big enough to carry its **bankfull flow** $Q_{bf}$,
the flood that comes about every 2 years (the median of the yearly peak flows).
For every river cell MRRpy:

1. finds $Q_{bf}$ at that cell (below);
2. sets the width from the global relation of Andreadis et al. (2013),
   $W = 7.2\,Q_{bf}^{0.5}$ (at most the cell size);
3. sets the depth so the channel carries exactly $Q_{bf}$ when full, from
   Manning's equation with the channel's $n$ and the river slope averaged over
   `CHANNEL_SLOPE_REACH_M` (at least `CHANNEL_MIN_DEPTH_M`). A steep gorge gets a
   shallower channel, a flat reach a deeper one.

**The bankfull flow**, `CHANNEL_QBF_M3S`, has three forms:

- **Empty: automatic.** A global estimate of the 2-year flood at the outlet. With
  Earth Engine it reads the wettest-month flow of HydroATLAS (Linke et al. 2019)
  at the outlet, $Q_2 = 15.1\,X^{0.644}$ with
  $X = Q_{\text{wettest month}} \cdot A/A_{\text{HydroATLAS}}$. Without Earth
  Engine it uses drainage area alone, $Q_2 = 1.73\,A^{0.606}$ ($A$ in km²). Both
  were fitted on 5,156 near-natural gauges in 62 countries; for 80 % of basins the
  estimate is within about 0.4–2.6× (HydroATLAS) or 0.3–3.9× (area only) of the
  observed value. The log prints the estimate and its range.
- **A number**: your 2-year flood in m³/s, best the median of 10 or more yearly
  peaks at a gauge. If the gauge isn't at the outlet, give its drainage area in
  `CHANNEL_QBF_AREA_KM2`.
- **A formula**: a regional relation, worked out at every cell with that cell's
  own drainage area. You can write it out, e.g. `"1.8767*(A_below(3000)+1)^0.8783"`,
  or name a preset.

For the automatic estimate and a number, the flow at other cells follows
$Q_{bf} \propto A^{\theta}$ with $\theta$ = `CHANNEL_QBF_AREA_EXP` (0.75; in
1,025 pairs of gauges on the same rivers the median was 0.69).

Formula variables and presets:

| In a formula | Meaning |
|---|---|
| `A` | the cell's drainage area (km²) |
| `A_below(z)`, `A_above(z)` | the part of that area below / above elevation `z` m (km²) |
| `H` | mean elevation of that area (m) |
| `P` | mean annual rain over the basin (mm, from HydroATLAS; needs Earth Engine) |
| `+ - * / ^`, `exp`, `log`, `log10`, `sqrt`, `abs`, `min`, `max` | operators and functions; a leading `Q2 =` is ignored |

| Preset | Formula | Notes |
|---|---|---|
| `wecs_nepal` | `1.8767 * (A_below(3000) + 1) ^ 0.8783` | WECS/DHM (1990) 2-year flood for Nepal; only area below 3,000 m counts |
| `global_area` | `1.73 * A ^ 0.606` | global fit on area only (offline); 80 % within 0.32–3.9× |
| `global_area_rain` | `1.72e-4 * A ^ 0.640 * P ^ 1.313` | global fit on area and rain; 80 % within 0.36–3.3× |

A regional formula is usually better than the global estimate **inside its
region** and should not be used outside it.

!!! warning "Use a 2-year flood, not a bridge or gorge capacity"
    The bank-top flow of a rating at a bridge or in a gorge is often far larger
    than the 2-year flood, because confined sections hold much more. Use the
    median of yearly peaks. `MRRpy.core.routing.surface.qbf_from_annual_peaks`
    computes it from a list of peaks.

### From drainage area (`area`)

Width and depth follow power laws of drainage area $A$ (km²):

$$
W = w_a A^{w_b}, \qquad D = d_a A^{d_b}
$$

`CHANNEL_HG` picks the coefficients: the US-wide or a regional curve of Bieger
et al. (2015), or your own `{w_a, w_b, d_a, d_b}` from local surveys.

| `CHANNEL_HG` | Region | $w_a$ | $w_b$ | $d_a$ | $d_b$ |
|---|---|---|---|---|---|
| `bieger_usa` | United States (1,279 sites) | 2.70 | 0.352 | 0.30 | 0.213 |
| `bieger_lup` | Laurentian Upland | 4.15 | 0.308 | 0.31 | 0.202 |
| `bieger_apl` | Atlantic Plain | 2.22 | 0.363 | 0.24 | 0.323 |
| `bieger_ahi` | Appalachian Highlands | 3.12 | 0.415 | 0.26 | 0.287 |
| `bieger_ipl` | Interior Plains | 2.56 | 0.351 | 0.38 | 0.191 |
| `bieger_ihi` | Interior Highlands | 23.23 | 0.121 | 0.27 | 0.267 |
| `bieger_rms` | Rocky Mountain System | 1.24 | 0.435 | 0.23 | 0.225 |
| `bieger_imp` | Intermontane Plateaus | 1.11 | 0.415 | 0.07 | 0.329 |
| `bieger_pms` | Pacific Mountain System | 2.76 | 0.399 | 0.23 | 0.294 |

### From stream order (`order`)

Width and depth are read from two tables by Strahler stream order (1 = the
smallest streams; two streams of order $k$ join into order $k+1$). Orders beyond
the table use the last value. This is the older method; the defaults are only
rough.

<!-- settings: CHANNEL_GEOMETRY CHANNEL_QBF_M3S CHANNEL_QBF_AREA_KM2 CHANNEL_QBF_AREA_EXP CHANNEL_SLOPE_REACH_M CHANNEL_MIN_DEPTH_M CHANNEL_HG CHANNEL_WIDTH_BY_ORDER CHANNEL_DEPTH_BY_ORDER -->

## 5.5.4 Baseflow

Rivers usually carry some water before a storm. `BASEFLOW_SPECIFIC_Q` adds a
steady flow per km² of drainage area along the river network, and rivers start
the run at the matching depth. 0 (the default) starts them dry, so the
hydrograph shows only the storm's runoff. For physical runoff,
[`VSA_BASEFLOW`](runoff.md#VSA_BASEFLOW) instead adds the pre-storm flow to the
reported hydrograph without changing the routing.

<!-- settings: BASEFLOW_SPECIFIC_Q -->

## Try it

- [Example 9 – Roughness and river channels](../examples/roughness-channels.md):
  automatic, measured and regional bankfull flow, compared.
