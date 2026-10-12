# Manuals, structures and recommendations

You do not need to know which methods to tick or which return periods to
compute. Choose **the manual** you design to and **what you are designing**,
and MRRpy-Nepal ticks the methods and return periods for you (compendium §2 and
§7). You can still change any tick.

The presets say which methods a manual *names*, according to the compendium.
They are a starting point, not a statement that a design complies with that
manual.

## Agency presets — `agency` {#agencies}

| Key | Manual | Methods ticked | Not yet in MRRpy-Nepal |
|---|---|---|---|
| `recommended` | Recommended for this catchment (the compendium's quick guide) | [chosen from the catchment and your data](#recommend) | |
| `dowri_2019` | DoWRI — Headworks & Cross-Drainage Guidelines (2019) | WECS/DHM, Modified Dickens, catchment area ratio, Rational | B.D. Richards |
| `dowri_pdsp_1990` | DoWRI (ex-DoI) — PDSP Irrigation Design Manuals (1990) | WECS/DHM, Modified Dickens, Rational (small catchments), frequency analysis | |
| `dolidar_2015` | DoLIDAR — Small-Scale Irrigation Design Manual (2015) | DHM 2004, Rational (C of 0.2–0.4), frequency analysis (Gumbel, LP-III) | |
| `doed_2018` | DoED — Hydropower Study Guidelines (2003/2018) | WECS/DHM, DHM 2004, MHSP, catchment area ratio, frequency analysis | PMF; GLOF/CLOF assessment |
| `wecs_2019` | WECS — Flood Control and Management Manual (2019) | WECS/DHM, DHM 2004, specific discharge, Rational (up to 50 km²) | |
| `dor_bridge` | DoR — Nepal Bridge Standards 2067 and Bridge Hydrology Guidelines (2021/22) | Rational, physics model, frequency analysis; WECS/DHM, DHM 2004, Modified Dickens as checks | B.D. Richards; IRC-based methods |
| `aepc_2004` | AEPC — Micro-Hydro Design Aids (2004) | WECS/DHM (reliable only above 100 km², not in the Siwalik or Terai) | |
| `nea_1997` | NEA — Medium Hydropower Study Project (1997) | MHSP | |
| `all` | Every method except the comparison-only formulas | all | |

The methods a manual names but MRRpy-Nepal does not yet implement are written
in the report's *Design basis*, so the gap stays visible.

**The DoR bridge preset.** Nepal Bridge Standards Cl. 3.2 do not allow formulas
developed for other catchments. Site-specific methods therefore lead
(rainfall–runoff, here the physics model and the Rational method; gauge records;
flood marks), and the national formulas serve as checks. The design flood is the
100-year flood.

## Structure presets — `structure` {#structures}

| Key | Structure | Design flood | Return periods ticked | Freeboard | Source |
|---|---|---|---|---|---|
| `study` | a study (every ToR return period) | 100 years | 2, 5, 10, 20, 50, 100, 200, 500 | | DoWRI pilot ToR (500 years as a safety check for higher-risk structures) |
| `bridge` | bridge | 100 years | 2, 100 | at least 1.0 m, rising to more than 2.0 m with discharge (Cl. 8.1) | DoR Nepal Bridge Standards 2067, Cl. 3.2 |
| `culvert` | culvert | 25 years | 2, 25 | | DoWRI Headworks & Cross-Drainage Guidelines 2019 |
| `aqueduct` | aqueduct | 50 years | 2, 50 | | DoWRI 2019 |
| `weir` | weir | 50–100 years | 2, 50, 100 | | DoWRI 2019; DoLIDAR manual 2015 |
| `barrage` | barrage | 100–500 years | 2, 100, 500 | | DoWRI 2019 |
| `embankment` | river embankment | 50–100 years | 2, 50, 100 | 1.0–1.5 m (DWIDM Pocket Diary) | DoWRI 2019; DWIDM/ADB embankment projects use 50 years including climate change |
| `intake` | small irrigation intake | 10–25 years | 2, 10, 25 | | DoLIDAR Small-Scale Irrigation Design Manual 2015 |

The 2-year flood is always ticked: it is close to the bankfull flow, and it
shows how the methods compare at the frequent end.

## What decides the methods and return periods

| Choice | First | Then | Otherwise |
|---|---|---|---|
| Methods | the methods you list (`methods=`, `--methods`) | the agency preset | the recommendation for the catchment |
| Return periods | the ones you list (`return_periods=`, `--T`) | the structure preset | the ToR set (2–500 years) |
| Physics runs | the ones you list ([details](design-floods.md#runs)) | the structure's design flood | 100 years, or the largest |

`--physics` adds the physics model to whatever methods were chosen;
`--no-physics` skips it.

## The quick guide: recommended methods {#recommend}

The agency `recommended` (the default when nothing is chosen) applies the
compendium's quick guide (§7) to the catchment and to the data you gave:

| Situation | Methods |
|---|---|
| $A$ < 12 km² | Rational, Modified Dickens, physics model. Add surveyed flood marks. |
| 12 ≤ $A$ ≤ 500 km² | WECS/DHM, DHM 2004, Modified Dickens, MHSP, specific discharge, physics model |
| $A$ > 500 km² | the same national methods with the physics model (they were fitted mostly to rivers of this size) |
| a gauge at the site (`flood_annual_max` given) | + frequency analysis with confidence bands |
| a gauge nearby (donor area and floods given) | + catchment area ratio |

It also adds these notes:

* for a Chure/Terai stream: the regional formulas use area only here, so give
  the rainfall-based methods and local flood marks more weight (§6);
* without a design rainfall: give the 24-hour design rainfall (or a station's
  annual maxima) for the Rational method and the physics model.

The compendium's table behind it:

| Situation | Commonly used in Nepal | Good practice — in MRRpy-Nepal |
|---|---|---|
| Flood, catchment under 12 km² | Rational; Modified Dickens | Rational with local rainfall, the physics model as the rainfall–runoff check, flood marks |
| Flood, 12–500 km², no gauge | WECS/DHM, DHM 2004, Modified Dickens, MHSP | the physics model, with the national methods as checks |
| Flood, gauge nearby | catchment area ratio, frequency analysis | frequency analysis with confidence bands; a similar donor gauge |
| Monthly flow for irrigation | MIP with one measurement; WECS/DHM | MIP with several measurements; the lower of WECS/DHM and MIP for low flows |
| Hydrograph and volume | Snyder / SCS unit hydrograph | the physics model (full hydrograph, routed on the DEM) |

## In code

```python
from MRRpy.nepal import AGENCIES, STRUCTURES, recommend_methods, CatchmentDescriptors

AGENCIES["dowri_2019"].methods          # ('wecs_dhm', 'modified_dickens', 'area_ratio', 'rational')
STRUCTURES["weir"].describe()           # 'Weir: 50- to 100-year flood (DoWRI …)'
keys, reasons = recommend_methods(CatchmentDescriptors(area_km2=8), has_rainfall=True)
```

```bash
MRRpy nepal methods          # every method, agency and structure preset
```
