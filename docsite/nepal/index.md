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
against the original report, the method's notes say so too. These pages explain
every formula with a worked example ([all formulas at a glance](methods.md)),
and what was left out and why.

!!! note "Why both?"
    Section 6 of the compendium explains why the national formulas break down
    for small Terai and Chure rivers. They were fitted mostly to large mountain
    rivers, and in the Chure the area below 3,000 m is the whole catchment, so
    they use area only — no rainfall, slope or soil. The physics model adds
    exactly those three, and reviewers still see the official numbers they
    expect.

## Where to start

| I want to… | Read |
|---|---|
| see a whole study for my kind of structure | [use cases](use-cases.md): culvert, weir, hydropower, bridge, irrigation, climate, screening |
| know which methods my manual asks for | [manuals, structures and recommendations](guidelines.md) |
| understand a formula and check a number by hand | [all formulas at a glance](methods.md), then its page |
| know how the catchment numbers are measured | [catchment numbers from the DEM](catchment.md) |
| run the physics model with a design storm | [design floods](design-floods.md) |
| estimate monthly flows, the e-flow or low flows | [monthly and low flows](monthly-flows.md) |
| understand a status, a flag or the official range | [reading the results](results.md) |

## Choose a manual and a structure

You do not need to know which methods to tick. Choose **the manual** you design
to (DoWRI 2019, DoLIDAR 2015, DoED, WECS 2019, DoR bridges, AEPC, NEA, or
*Recommended for this catchment*), and the methods it names are ticked. Choose
**what you are designing** (bridge, culvert, aqueduct, weir, barrage,
embankment, intake, or a study), and its design return period is ticked. The
full tables are on [manuals, structures and recommendations](guidelines.md).

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

The table gives each method's flood by return period with a status (*ok*, *use
with caution*, *outside its range*, *needs input*, *comparison only*) and marks
interpolated (≈) and extrapolated (\*) values. The **official range** is the
minimum, median and maximum of the regional peak methods that are usable for
this catchment. The report says whether the physics flood is inside, above or
below it. A range wider than a factor of 3 is flagged. Every rule is on
[reading the results](results.md).

Next: [use cases](use-cases.md) · [all formulas at a glance](methods.md) ·
[design floods with the physics model](design-floods.md).
