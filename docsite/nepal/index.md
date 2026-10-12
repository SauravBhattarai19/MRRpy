# MRRpy-Nepal

**MRRpy-Nepal** puts the official Nepali flood-estimation methods next to
MRRpy's physics-based model. One run of it:

1. **measures the catchment** from your DEM: the total area, the area below
   3,000 m and below 5,000 m, the permanent-snow area, the longest flow path
   and its slope. These are the numbers the official methods need, so nobody
   has to measure them by hand in a GIS;
2. **runs the official methods** — WECS/DHM 1990 (HYDEST), DHM 2004 (Sharma &
   Adhikari), MHSP 1997, Modified Dickens, the specific-discharge method, the
   Rational method, frequency analysis at a gauge and the catchment area
   ratio — with a validity flag for each;
3. **runs the physics model** with a design storm built the way Nepali practice
   builds it: the T-year 24-hour rainfall from DHM data, spread in time with the
   Mononobe curve that the Rational method uses;
4. **shows them side by side**: the range of the official methods, where the
   physics result falls in it, and what to watch out for. It writes a CSV
   table, a chart and a Markdown report.

Monthly and low flows (MIP 1982, WECS/DHM and MHSP monthly, the e-flow release)
are on a separate tab and command.

The physics core of MRRpy is unchanged; MRRpy-Nepal is a layer around it
(`MRRpy.nepal`). Every coefficient comes from the compendium *Nepal Flood
Estimation Methods*. Where the compendium says a value still has to be checked
against the original report, the method's notes say so too. The
[methods page](methods.md) lists every formula, and what was left out and why.

!!! note "Why both?"
    Section 6 of the compendium explains why the national formulas break down
    for small Terai and Chure rivers. They were fitted mostly to large mountain
    rivers, and in the Chure the area below 3,000 m is the whole catchment, so
    they use area only — no rainfall, slope or soil. The physics model adds
    exactly those three, and reviewers still see the official numbers they
    expect.

## Which method for what

The compendium's quick guide (§7), which MRRpy-Nepal applies when you choose
*Recommended for this catchment*:

| Situation | Commonly used in Nepal | Good practice — in MRRpy-Nepal |
|---|---|---|
| Flood, catchment under 12 km² | Rational; Modified Dickens | Rational with local rainfall, the physics model as the rainfall-runoff check, flood marks |
| Flood, 12–500 km², no gauge | WECS/DHM, DHM 2004, Modified Dickens, MHSP | the physics model, with the national methods as checks |
| Flood, gauge nearby | catchment area ratio, frequency analysis | frequency analysis with confidence bands; a similar donor gauge |
| Monthly flow for irrigation | MIP with one measurement; WECS/DHM | MIP with several measurements; the lower of WECS/DHM and MIP for low flows |
| Hydrograph and volume | Snyder / SCS unit hydrograph | the physics model (full hydrograph, routed on the DEM) |

## Choose a manual and a structure

You do not need to know which methods to tick. Choose **the manual** you design
to, and the methods it names are ticked. Choose **what you are designing**, and
its design return period is ticked:

| Manual (agency preset) | Methods it ticks |
|---|---|
| DoWRI — Headworks & Cross-Drainage Guidelines (2019) | WECS/DHM, Modified Dickens, catchment area ratio, Rational (B.D. Richards not yet in MRRpy-Nepal) |
| DoWRI (ex-DoI) — PDSP Irrigation Design Manuals (1990) | WECS/DHM, Modified Dickens, Rational, frequency analysis |
| DoLIDAR — Small-Scale Irrigation Design Manual (2015) | DHM 2004, Rational, frequency analysis |
| DoED — Hydropower Study Guidelines (2003/2018) | WECS/DHM, DHM 2004, MHSP, catchment area ratio, frequency analysis |
| WECS — Flood Control and Management Manual (2019) | WECS/DHM, DHM 2004, specific discharge, Rational |
| DoR — Nepal Bridge Standards 2067 / Bridge Hydrology Guidelines | Rational, physics model, frequency analysis; WECS/DHM, DHM 2004 and Modified Dickens as checks |
| AEPC — Micro-Hydro Design Aids (2004) | WECS/DHM |
| NEA — Medium Hydropower Study Project (1997) | MHSP |

| Structure | Design flood | Source |
|---|---|---|
| Bridge | 100 years; freeboard at least 1.0 m | DoR Nepal Bridge Standards 2067, Cl. 3.2 and 8.1 |
| Culvert | 25 years | DoWRI Headworks & Cross-Drainage Guidelines 2019 |
| Aqueduct | 50 years | DoWRI 2019 |
| Weir | 50–100 years | DoWRI 2019; DoLIDAR 2015 |
| Barrage | 100–500 years | DoWRI 2019 |
| River embankment | 50–100 years; freeboard 1.0–1.5 m | DoWRI 2019; DWIDM/ADB projects |
| Small irrigation intake | 10–25 years | DoLIDAR 2015 |
| Study | 2, 5, 10, 20, 50, 100, 200, 500 years | the DoWRI pilot ToR |

The presets say which methods a manual names (per the compendium). They are a
starting point, not a statement that a design complies with that manual.

## Run it

The example: a Chure stream, delineated in an earlier MRRpy run (`results/`), to
be checked for a weir under the DoWRI 2019 guidelines, with the 24-hour design
rainfall from the nearest DHM station.

=== "Notebook form"

    ```python
    from MRRpy.nepal import NepalForm
    form = NepalForm()
    form
    ```

    1. **Site**: *A results folder from an MRRpy run* → `results/`. Press
       **Measure the catchment**: the table shows A, A₃₀₀₀, the snow area, L, S
       and the river class.
    2. **Methods**: *Which manual* → DoWRI Headworks & Cross-Drainage Guidelines
       (2019); *What are you designing* → Weir. The methods and the return periods
       (2, 50, 100) are ticked. Under each ticked method only its inputs appear:
       the runoff coefficient for Rational, the design rainfall
       `2: 120, 50: 230, 100: 250`. Tick **MRRpy physics model** too.
    3. **Results**: **Compute the estimates**. The table, the official range, the
       physics flood and a chart appear; they are saved in `results/nepal/`.

    The form is ordinary Python: `form.study` is the study it describes,
    `form.result` the outcome, **Show Python code** prints the same study as
    code. No ipywidgets? Use the command line or the Python tab.

=== "Command line"

    ```bash
    MRRpy nepal estimate --results results/ --agency dowri_2019 --structure weir \
        --C 0.45 --rain24 2=120 50=230 100=250 --physics \
        --save-study weir_study.yaml

    MRRpy nepal estimate --study weir_study.yaml     # again, later
    MRRpy nepal methods                              # every method and preset
    ```

    The saved study is a short YAML file:

    ```yaml
    site:
      results: results/
    agency: dowri_2019
    structure: weir
    methods: [wecs_dhm, modified_dickens, rational, area_ratio, physics]
    inputs:
      runoff_coefficient: 0.45
      rain_24h: {2: 120.0, 50: 230.0, 100: 250.0}
    ```

=== "Python"

    ```python
    from MRRpy.nepal import NepalStudy

    study = NepalStudy.from_results(
        "results/", agency="dowri_2019", structure="weir",
        methods=["wecs_dhm", "modified_dickens", "rational", "area_ratio", "physics"],
        inputs={"runoff_coefficient": 0.45, "rain_24h": {2: 120, 50: 230, 100: 250}},
    )
    result = study.run()          # measure → methods → physics → results/nepal/
    result.table                  # Q by return period, status and notes per method
    result.envelope               # min / median / max of the official methods
    result.plot()                 # the chart
    print(result.report())        # the Markdown report
    ```

    No DEM yet? `NepalStudy.from_numbers(65, flow_length_km=15,
    flow_path_slope=0.015, …)` runs every method that needs only the numbers.
    `NepalStudy.from_dem("dem.tif", (lat, lon))` delineates first.

=== "QGIS plugin"

    1. Run **1. DEM Pre-processing** (Processing Toolbox → MRRpy_plugin) or the
       main dialog's DEM tab, so the results folder holds the watershed.
    2. Open **3. Nepal flood estimates (official methods)** — also in the
       *Plugins → MRRpy_plugin* menu. Choose the results folder, the manual and
       the structure. Enter the runoff coefficient and the design rainfall
       `2=120, 50=230, 100=250`, and tick *Also run the MRRpy physics model*.
    3. The table is printed in the log and added to the map as a table layer; the
       chart and the report are written to the output folder.

    **4. Nepal design storm** writes a design storm as the two rain-gauge CSV
    files the main dialog's Precipitation tab reads with Thiessen, for a run with
    your own runoff and routing settings.

## Reading the results

| In the table | Meaning |
|---|---|
| *ok* | inside the method's range |
| *use with caution* | usable, with a caveat in its notes (e.g. AEPC calls WECS/DHM reliable only above 100 km²) |
| *outside its range* | computed but outside the method's stated range (e.g. Rational above 50 km²); left out of the official range |
| *needs input* | something is missing; the notes say what |
| *comparison only* | the Indian formulas (Dickens, Ryves, Inglis); never in the official range |
| ≈ | interpolated between tabulated return periods (MHSP, specific discharge) or design rainfalls |
| \* | extrapolated beyond 100 years, or beyond twice a gauge record |

The **official range** is the minimum, median and maximum of the regional peak
methods that are usable for this catchment. The report says whether the physics
flood is inside, above or below it, and its ratio to the median. A wide range
(more than a factor of 3) is flagged, because then the choice of method needs to
be explained and checked against the nearest gauges.

Next: [the methods and their formulas](methods.md) ·
[design floods with the physics model](design-floods.md).
