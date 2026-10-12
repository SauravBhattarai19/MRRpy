# Use cases: worked studies

Seven situations a Nepali engineer or hydrologist meets, each worked from start
to finish. They show which manual and structure to choose, what to type, what
comes out, and how to read it. Every number on this page was computed by
MRRpy-Nepal from the inputs shown.

!!! warning "Example inputs"
    The catchments, rainfalls and flow records on this page are **illustrative**:
    realistic in size, but not measurements from real stations. Use your own
    DHM data for a design.

| # | Use case | Manual / structure | Methods that matter |
|---|---|---|---|
| 1 | [A culvert on a small Chure stream](#culvert) | recommended / culvert | Rational, Modified Dickens, physics |
| 2 | [A weir on a 65 km² Chure river](#weir) | DoWRI 2019 / weir | WECS/DHM, Modified Dickens, Rational (outside) |
| 3 | [A hydropower intake on a snow-fed river](#hydropower) | DoED / study | WECS/DHM, DHM 2004, MHSP, area ratio |
| 4 | [A bridge at a gauged site, with flood marks](#bridge) | DoR bridge / bridge | frequency analysis, national checks, flood marks |
| 5 | [Monthly flows and e-flow for an irrigation intake](#irrigation) | — | MIP 1982, WECS/DHM, MHSP |
| 6 | [Climate change and the physics model](#climate) | DoR bridge / bridge | physics model with a climate factor |
| 7 | [Screening many sites at once](#screening) | — | the regional formulas in a loop |

## 1. A culvert on a small Chure stream {#culvert}

**Situation.** A road crosses a Chure stream of 8 km². Its longest flow path is
4 km, with a slope of 0.04, and the highest point is at 950 m. The nearest DHM
station gives a 24-hour rainfall of 120 mm (2 years), 205 mm (25 years) and
250 mm (100 years). The land is mostly forest and some cultivation, so
$C$ = 0.4. A culvert is designed for the 25-year flood (DoWRI 2019).

**Choose** *Recommended for this catchment* and *Culvert*. Under 12 km² the
quick guide ticks the Rational method, Modified Dickens and the physics model;
the culvert ticks 2 and 25 years.

=== "Python"

    ```python
    from MRRpy.nepal import NepalStudy

    study = NepalStudy.from_numbers(
        8.0, flow_length_km=4.0, flow_path_slope=0.04, max_elevation_m=950,
        name="Chure culvert", structure="culvert",
        inputs={"runoff_coefficient": 0.4, "rain_24h": {2: 120, 25: 205, 100: 250}})
    result = study.run()
    ```

=== "Command line"

    ```bash
    MRRpy nepal estimate --area 8 --length-km 4 --slope 0.04 --max-elevation 950 \
        --structure culvert --C 0.4 --rain24 2=120 25=205 100=250 --name "Chure culvert"
    ```

**Result** (m³/s):

| Method | Status | Q2 | Q25 |
|---|---|---|---|
| Modified Dickens | use with caution | 20.08 | 34.73 |
| Rational method | ok | 48.47 | 82.81 |
| MRRpy physics model | needs input | – | – |

**Reading it.**

* The Rational method gives 82.8 m³/s at 25 years ($t_c$ = 40 min, the
  25-year intensity 93.2 mm/h; [worked step by step](rainfall-methods.md#worked-examples)),
  2.4 times Modified Dickens.
* Modified Dickens is *use with caution*: with no snow, $p = 100 \times 6/8 =
  75$, and the "+6" decides the answer. It is the only official method here, so
  the official range is that single value.
* The catchment is class III (highest point 950 m), and the result warns that
  rainfall-based methods and flood marks deserve more weight here.
* The physics model *needs input*: it needs a DEM. Run the study on a DEM (*A
  DEM file and an outlet*) to get the physics flood as the rainfall–runoff check
  the quick guide asks for. Then survey flood marks at the crossing.

A culvert sized on Modified Dickens alone would be too small if the Rational
method is right. This is the situation the compendium's §6 describes.

## 2. A weir on a 65 km² Chure river {#weir}

**Situation.** The compendium's own example: a 65 km² snow-free Chure catchment
($L$ = 15 km, $S$ = 0.015, highest point 1,350 m), with a weir designed to the
DoWRI Headworks & Cross-Drainage Guidelines (2019). $C$ = 0.45; $R_{24}$ = 120,
230 and 250 mm for 2, 50 and 100 years.

=== "Study file"

    ```yaml
    site:
      numbers: {area_km2: 65, flow_length_km: 15, flow_path_slope: 0.015,
                max_elevation_m: 1350}
    name: Chure weir
    agency: dowri_2019
    structure: weir
    inputs:
      runoff_coefficient: 0.45
      rain_24h: {2: 120, 50: 230, 100: 250}
    ```

    ```bash
    MRRpy nepal estimate --study weir.yaml
    ```

=== "Python"

    ```python
    study = NepalStudy.from_numbers(
        65.0, flow_length_km=15, flow_path_slope=0.015, max_elevation_m=1350,
        name="Chure weir", agency="dowri_2019", structure="weir",
        inputs={"runoff_coefficient": 0.45, "rain_24h": {2: 120, 50: 230, 100: 250}})
    result = study.run()
    ```

**Result** (m³/s):

| Method | Status | Q2 | Q50 | Q100 |
|---|---|---|---|---|
| WECS/DHM 1990 | use with caution | 74.39 | 267.5 | 317.1 |
| Modified Dickens | use with caution | 100.5 | 258.5 | 292.6 |
| Rational method | outside its range | 174.8 | 335.0 | 364.1 |
| Catchment area ratio | needs input | – | – | – |

Official range: 292.6–317.1 m³/s at 100 years (2 methods, spread 1.08).

**Reading it.**

* The two official methods agree closely, but both carry cautions: WECS/DHM
  because the catchment is under 100 km² and a Chure stream, so $A_{3000} = A$;
  Modified Dickens because of the "+6".
* The Rational method is *outside its range* (65 km² > 50 km², WECS 2019). It is
  shown, at 364.1 m³/s, but kept out of the range.
* The area ratio *needs input*: DoWRI names it, but it needs a donor gauge
  (`donor_area_km2` and `donor_floods` or `donor_annual_max`).
* The DoWRI preset does not include DHM 2004 or the specific-discharge method.
  With all the regional methods ticked, the 100-year range becomes 170.6–516.1
  m³/s ([side by side](regional-formulas.md#side-by-side)),
  a factor of 3. The close agreement above comes from the choice of methods,
  not from the catchment. Add the physics model on the DEM (`--physics`) before
  settling on a design flood.

## 3. A hydropower intake on a snow-fed river {#hydropower}

**Situation.** A run-of-river scheme in the central hills. The catchment is
420 km²: 260 km² lies below 3,000 m, 380 km² below 5,000 m, and 40 km² is
permanent snow (highest point 5,900 m). A gauge on a similar river nearby
(600 km²) has 20 years of annual maxima. The study follows the DoED guidelines
and reports every ToR return period.

=== "Python"

    ```python
    donor_peaks = [410, 380, 655, 520, 300, 720, 450, 390, 610, 505,
                   470, 820, 360, 540, 430, 600, 495, 380, 700, 455]
    study = NepalStudy.from_numbers(
        420.0, area_below_3000_km2=260, area_below_5000_km2=380,
        flow_length_km=48, flow_path_slope=0.06, max_elevation_m=5900,
        name="Snow-fed hydropower", agency="doed_2018", structure="study",
        inputs={"mhsp_region": "central", "donor_area_km2": 600,
                "donor_annual_max": donor_peaks, "flood_distribution": "gev"})
    result = study.run()
    ```

=== "Command line"

    ```bash
    MRRpy nepal estimate --area 420 --area-below-3000 260 --area-below-5000 380 \
        --length-km 48 --slope 0.06 --max-elevation 5900 \
        --agency doed_2018 --structure study --region central \
        --donor-area 600 --donor-series donor_peaks.csv --flood-dist gev
    ```

**Result** (m³/s):

| Method | Status | Q2 | Q5 | Q10 | Q20 | Q50 | Q100 | Q200 | Q500 |
|---|---|---|---|---|---|---|---|---|---|
| WECS/DHM 1990 | ok | 248.8 | 391.4 | 495.9 | 603 | 751.3 | 870 | \*995 | \*1171 |
| DHM 2004 | ok | 273.3 | 457.4 | 598.7 | 747.7 | 960.1 | 1134 | \*1321 | \*1590 |
| MHSP 1997 (Central) | ok | – | 573.3 | ≈724.4 | 878.8 | 1104 | 1284 | – | – |
| Frequency analysis | needs input | – | – | – | – | – | – | – | – |
| Area ratio (GEV donor) | ok | 364.4 | 460.8 | 525.3 | 587.7 | 669.1 | 730.7 | 792.5 | 874.8 |

Official range at 100 years: 870–1,284 m³/s, median 1,134 (3 methods).

**Reading it.**

* The catchment is class I (snow-fed). WECS/DHM and DHM 2004 use only the
  260 km² below 3,000 m, and MHSP the total 420 km², so MHSP gives the highest
  values here.
* Frequency analysis *needs input*: the DoED preset names it, but there is no
  gauge at the site itself.
* The donor gauge, moved by $(420/600)^{0.8} = 0.752$, gives 730.7 m³/s at 100
  years, below the official range. Its GEV band (drawn on the chart) shows how
  uncertain that is. 20 years of record is short for 100 years.
* The site is 0.7 times the donor's area, inside the 0.5–2 window, so the area
  ratio is *ok*. Similarity still has to be argued (elevation range, snow share).
* For the design discharge of the scheme itself, use the
  [monthly flows](monthly-flows.md) and the flow-duration analysis of the
  hydropower guidelines; the flood table gives the diversion and spillway floods.

## 4. A bridge at a gauged site, with flood marks {#bridge}

**Situation.** A bridge on a 350 km² hill river ($A_{3000}$ = 310 km², $L$ =
42 km, $S$ = 0.03, highest point 3,600 m). A gauge at the site has 20 years of
annual maxima. After the 2021 monsoon flood the high-water marks were surveyed,
and the slope–area method gave 1,010 m³/s. DoR Bridge Standards apply: 100-year
design flood, site-specific methods first.

=== "Python"

    ```python
    study = NepalStudy.from_numbers(
        350.0, area_below_3000_km2=310, flow_length_km=42, flow_path_slope=0.03,
        max_elevation_m=3600, name="Gauged bridge", agency="dor_bridge",
        structure="bridge",
        inputs={"flood_annual_max": "peaks.csv", "runoff_coefficient": 0.4,
                "rain_24h": {2: 130, 100: 260}},
        observed_floods=[("2021 flood marks", 1010)])
    result = study.run()
    ```

=== "Command line"

    ```bash
    MRRpy nepal estimate --area 350 --area-below-3000 310 --length-km 42 --slope 0.03 \
        --max-elevation 3600 --agency dor_bridge --structure bridge \
        --flood-series peaks.csv --C 0.4 --rain24 2=130 100=260 \
        --observed "2021 flood marks=1010"
    ```

(`peaks.csv` holds the same 20 example values as use case 3.)

**Result** (m³/s):

| Method | Status | Q2 | Q100 |
|---|---|---|---|
| WECS/DHM 1990 | ok | 290.3 | 989.5 |
| DHM 2004 | ok | 318.0 | 1288 |
| Modified Dickens | ok | 366.3 | 1281 |
| Rational method | outside its range | 638.2 | 1276 |
| MRRpy physics model | needs input | – | – |
| Frequency analysis (Gumbel) | ok | 487.0 | \*938.9 |

Official range at 100 years: 989.5–1,288 m³/s (median 1,281).

**Reading it.**

* The gauge leads (Cl. 3.2). Its 100-year flood, 938.9 m³/s, is extrapolated
  (100 years is more than twice the 20-year record), with a 90 % band of about
  783–1,051 m³/s.
* The 2021 flood marks, **1,010 m³/s**, are already above the gauge's 100-year
  estimate. Either 2021 was rarer than a 100-year flood, or the 20-year record
  underestimates the tail. A reviewer will ask. Compare the GEV and LP-III fits
  (`MRRpy nepal frequency peaks.csv`), add 2021 to the series if it is not in
  it, and look at the upper band.
* The national checks give 989.5–1,288 m³/s. Together with the flood marks,
  the evidence points above the gauge's central estimate; the design flood has
  to be argued from all of it, not from the gauge fit alone.
* Add the physics model on the DEM (the DoR preset ticks it) as the
  rainfall–runoff evidence. Then check the freeboard: at least 1.0 m (Cl. 8.1).

## 5. Monthly flows and e-flow for an irrigation intake {#irrigation}

**Situation.** A farmer-managed irrigation scheme takes water from a 65 km²
stream in MIP Region 4. A flow of 1.5 m³/s was measured on 15 February, and the
mean monsoon rainfall is 1,500 mm. What flow can the intake count on each
month, and what must it release?

=== "Command line"

    ```bash
    MRRpy nepal monthly --area 65 --mip-region 4 --measured 2024-02-15=1.5 \
        --mmp 1500 -o monthly.csv
    ```

=== "Python"

    ```python
    from MRRpy.nepal import CatchmentDescriptors, flows
    mf = flows.monthly_flows(CatchmentDescriptors(area_km2=65), mip_region=4,
                             measurements=("2024-02-15", 1.5), mmp_mm=1500)
    mf.table, mf.eflow
    ```

**Result** (m³/s, dry season and the monsoon peak):

| Method | Jan | Feb | Mar | Apr | May | Aug |
|---|---|---|---|---|---|---|
| MIP 1982 | 2.07 | 1.50 | 1.10 | 0.80 | 1.75 | 21.76 |
| WECS/DHM 1990 | 0.85 | 0.73 | 0.65 | 0.63 | 0.81 | 11.26 |
| MHSP 1997 | 1.15 | 0.93 | 0.84 | 0.96 | 0.67 | 12.35 |
| **Lower of WECS/DHM and MIP** | **0.85** | **0.73** | **0.65** | **0.63** | **0.81** | **11.26** |

E-flow: at least **0.063 m³/s** (10 % of the April flow of the lower row).

**Reading it.**

* For low-flow design take the lower row (Shrestha et al. 2010): about 0.63 m³/s
  in April, the critical month, minus the e-flow, leaves about 0.57 m³/s for
  the canal.
* The regional formulas give less than half of what the MIP measurement implies
  in the dry season. Measure again in March or April. With several measurements
  MIP uses the lowest implied April flow, which makes the estimate safer.
* With a few years of gauged or simulated flows, `flows.dependable_flow` gives
  the 80 % dependable flow per month, the usual basis for irrigation design.
* The intake's flood (10–25 years, structure `intake`) is a separate
  `estimate` run.

[All monthly formulas](monthly-flows.md).

## 6. Climate change and the physics model {#climate}

**Situation.** A bridge study needs the 100-year flood today and under a
scenario with 10 % more extreme rainfall (the ToR's climate delta factor). The
catchment is on a DEM, so the physics model can run.

=== "Python"

    ```python
    base = NepalStudy.from_dem("dem.tif", (27.654, 85.281), "results",
                               agency="dor_bridge", structure="bridge",
                               inputs={"rain_24h": {2: 120, 100: 250}},
                               physics={"curve_number": 80, "duration_h": 3})
    future = NepalStudy.from_results("results", agency="dor_bridge", structure="bridge",
                                     inputs={"rain_24h": {2: 120, 100: 250}},
                                     physics={"curve_number": 80, "duration_h": 3,
                                              "climate_factor": 1.1})
    for s in (base, future):
        print(s.run().physics[100.0].summary())
    ```

=== "Command line"

    ```bash
    MRRpy nepal estimate --dem dem.tif --outlet 27.654 85.281 --folder results \
        --agency dor_bridge --structure bridge --rain24 2=120 100=250 \
        --physics --cn 80 --duration 3
    MRRpy nepal estimate --results results --agency dor_bridge --structure bridge \
        --rain24 2=120 100=250 --physics --cn 80 --duration 3 --climate-factor 1.1
    ```

**Result** on the small synthetic test basin (0.108 km²):

| Run | Storm | Peak | Volume | Runoff ratio |
|---|---|---|---|---|
| Today | 125 mm in 3 h | 3.187 m³/s at 2.0 h | 7,740 m³ | 0.57 |
| +10 % rainfall | 138 mm in 3 h | 3.755 m³/s at 2.0 h | 8,920 m³ | 0.60 |

**Reading it.** 10 % more rain gives 18 % more peak, because the soil losses
hardly change and the extra rain runs off almost in full. Only a rainfall–runoff
model can show this; a regional formula has no rainfall to scale. The same
run also gives the flood volume and the hydrograph, and maps of depth and
velocity if [[SAVE_FIELDS]] is on in a model settings file. More on the choices
(curve number, storm pattern) in
[design floods](design-floods.md#how-the-choices-change-the-flood).

## 7. Screening many sites at once {#screening}

**Situation.** A municipality has dozens of stream crossings and wants a first
idea of the 100-year flood at each before choosing which to study in detail.

```python
import pandas as pd
from MRRpy.nepal import estimate_floods

sites = {"Khola A": 5, "Khola B": 20, "Khola C": 80}          # area in km²
rows = []
for name, area in sites.items():
    est = estimate_floods({"area_km2": area, "name": name},
                          ["wecs_dhm", "dhm_2004", "modified_dickens", "specific_discharge"],
                          return_periods=[25, 100])
    env = est.envelope.loc[100]
    rows.append({"site": name, "area_km2": area, "min": env["min"],
                 "median": env["median"], "max": env["max"], "methods": env["n_methods"]})
pd.DataFrame(rows)
```

| Site | Area (km²) | Q100 min | Q100 median | Q100 max | Methods |
|---|---|---|---|---|---|
| Khola A | 5 | 27.22 | 54.52 | 65.95 | 3 |
| Khola B | 20 | 100.7 | 157.9 | 282.9 | 4 |
| Khola C | 80 | 351.9 | 427.0 | 573.8 | 4 |

Khola A has 3 methods because specific discharge is *outside its range* below
12 km². With `measure_catchment` in the loop, each site can be measured from
its own `process_dem` results folder. Sites with a wide range, or that are
class III, are the ones to study with rainfall and the physics model.
