# 5.4 Ground roughness

Manning's roughness coefficient $n$ says how much a surface slows the water
flowing over it. In Manning's equation the speed is proportional to $1/n$:
doubling $n$ halves the speed, which delays and flattens the flood peak. It is
usually the first value to calibrate.

!!! info "Where to set it"
    Notebook form: step **5 Routing** → *Ground roughness* and *River channels* ·
    Wizard: part **4 Roughness and river channels** · QGIS: tab **4 · Routing**,
    *Manning's Roughness*.

## 5.4.1 Roughness of the ground

`MANNINGS_N_SOURCE` says where the roughness of every cell comes from:

- `scalar`: one value, `MANNINGS_N`, everywhere.
- `lulc`: from the ESA WorldCover land-cover map (10 m, 2021), through the
  `mannings_n` column of the [land-cover table](#543-land-cover-tables). The map
  is downloaded from Earth Engine, or read from your own WorldCover-coded raster
  (`MANNINGS_N_LULC_PATH`).
- `lcz`: from the WUDAPT Local Climate Zones map: finer classes for cities.
- `raster`: your own GeoTIFF of $n$ (any projection; it is resampled).

`MANNINGS_N` also fills any cell a map leaves empty.

Values for very shallow **sheet flow**, from the US NRCS method TR-55
(USDA 1986, table 3-1):

| Surface | $n$ |
|---|---|
| Smooth: concrete, asphalt, gravel, bare soil | 0.011 |
| Fallow, no residue | 0.05 |
| Cultivated, residue cover ≤ 20 % / > 20 % | 0.06 / 0.17 |
| Short-grass prairie | 0.15 |
| Dense grass | 0.24 |
| Natural range | 0.13 |
| Woods, light / dense underbrush | 0.40 / 0.80 |

Sheet flow is only a few centimetres deep. In a 30–90 m cell the water gathers
in rills and small gullies, so lower values, like those in the
[land-cover tables](#543-land-cover-tables), are common in grid models. Treat
$n$ as a calibration value within a sensible range.

!!! tip "Roughness from elevation"
    To give the whole grid an elevation rule (rougher, rockier ground higher up),
    make a raster with `MRRpy.mannings_n_from_dem` and use `raster`. See
    [Example 9](../examples/roughness-channels.md).

<!-- settings: MANNINGS_N_SOURCE MANNINGS_N MANNINGS_N_LULC_PATH MANNINGS_N_RASTER_PATH -->

## 5.4.2 Roughness of river channels

River channels are smoother than the land around them, so channel cells (see
[5.5](channels.md#551-which-cells-are-rivers)) usually get their own $n$ with
`MANNINGS_N_CHANNEL`. It is independent of the ground source, so you can mix,
for example, land-cover roughness on the hillslopes with an elevation rule in
the rivers. Its forms:

| Form | Config file (YAML) | Meaning |
|---|---|---|
| empty | `null` | channels keep the ground roughness |
| a number | `0.035` | the same $n$ in every channel cell (default) |
| by stream order | `{1: 0.06, 2: 0.045, 3: 0.035}` | $n$ per Strahler order; higher orders reuse the last value |
| by elevation | `[[1700, 0.03], [2000, 0.05], [9000, 0.08]]` | ascending `[upper elevation, n]` pairs: the first pair whose elevation is above the cell's wins |
| a raster | `channel_n.tif` | $n$ read on channel cells only |

In Python it can also be a dictionary of elevation bands, `{(0, 1500): 0.03,
(1500, 3000): 0.08}`, or a function of elevation, `lambda z: 0.02 + 0.00002 * z`.

Typical values: a straight, clean channel 0.025–0.033; a winding channel with
pools 0.033–0.045; a mountain stream with boulders 0.04–0.07 (Chow 1959).

<!-- settings: MANNINGS_N_CHANNEL -->

## 5.4.3 Land-cover tables

Two tables translate land-cover classes into model values. MRRpy ships both. To
change them, copy one, edit it and point the setting at your copy. Columns:

| Column | Used for |
|---|---|
| `class_code` | the class number in the land-cover map |
| `root_zone_depth_m` | soil depth that stores water (physical runoff: the deficit and Green–Ampt $\Delta\theta_0$) |
| `mannings_n` | ground roughness, when `MANNINGS_N_SOURCE` is `lulc` or `lcz` |
| `impervious_fraction` | impervious share, when `IMPERVIOUS_SOURCE` is `lulc` or `lcz` |

**ESA WorldCover** (`LULC_LOOKUP_CSV`):

| Code | Class | Root zone (m) | $n$ | Impervious |
|---|---|---|---|---|
| 10 | Tree cover | 2.0 | 0.15 | 0 |
| 20 | Shrubland | 1.5 | 0.10 | 0 |
| 30 | Grassland | 0.8 | 0.04 | 0 |
| 40 | Cropland | 1.0 | 0.06 | 0 |
| 50 | Built-up | 0.3 | 0.015 | 0.85 |
| 60 | Bare / sparse vegetation | 0.3 | 0.03 | 0 |
| 70 | Snow and ice | 0.1 | 0.05 | 0 |
| 80 | Permanent water bodies | 0.1 | 0.03 | 0 |
| 90 | Herbaceous wetland | 0.5 | 0.05 | 0 |
| 95 | Mangroves | 0.8 | 0.07 | 0 |
| 100 | Moss and lichen | 0.3 | 0.04 | 0 |

**WUDAPT Local Climate Zones** (`LCZ_LOOKUP_CSV`):

| Code | Class | Root zone (m) | $n$ | Impervious |
|---|---|---|---|---|
| 1 | Compact high-rise | 0.10 | 0.013 | 0.95 |
| 2 | Compact mid-rise | 0.10 | 0.013 | 0.90 |
| 3 | Compact low-rise | 0.20 | 0.016 | 0.85 |
| 4 | Open high-rise | 0.30 | 0.020 | 0.65 |
| 5 | Open mid-rise | 0.30 | 0.020 | 0.60 |
| 6 | Open low-rise | 0.60 | 0.030 | 0.50 |
| 7 | Lightweight low-rise | 0.10 | 0.018 | 0.75 |
| 8 | Large low-rise | 0.20 | 0.013 | 0.90 |
| 9 | Sparsely built | 0.80 | 0.040 | 0.20 |
| 10 | Heavy industry | 0.20 | 0.016 | 0.65 |
| 11 | Dense trees | 2.00 | 0.150 | 0 |
| 12 | Scattered trees | 1.50 | 0.120 | 0 |
| 13 | Bush, scrub | 1.00 | 0.100 | 0 |
| 14 | Low plants | 0.80 | 0.040 | 0 |
| 15 | Bare rock or paved | 0.30 | 0.015 | 0.90 |
| 16 | Bare soil or sand | 0.30 | 0.030 | 0 |
| 17 | Water | 0.10 | 0.030 | 0 |

The root-zone depths come from the WorldCover table, unless the roughness source
is `lcz`.

<!-- settings: LULC_LOOKUP_CSV LCZ_LOOKUP_CSV -->

## Try it

- [Example 9 – Roughness and river channels](../examples/roughness-channels.md).
