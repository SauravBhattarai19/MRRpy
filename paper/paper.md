---
title: 'MRRpy: A modular Python model for distributed rainfall–runoff generation and flood routing'
tags:
  - Python
  - hydrology
  - hydrodynamics
  - flood modeling
  - rainfall-runoff
  - watershed delineation
  - kinematic wave
  - Muskingum-Cunge
  - Google Earth Engine
  - QGIS
authors:
  - name: Saurav Bhattarai
    orcid: 0009-0006-2627-8563
    corresponding: true
    affiliation: 1
  - name: Nawa Raj Pradhan
    orcid: 0000-0001-5210-0896
    corresponding: false
    affiliation: 2
  - name: Rocky Talchabhadel
    orcid: 0000-0003-0526-7663
    corresponding: false
    affiliation: 1
affiliations:
  - name: Department of Civil and Environmental Engineering, Jackson State University, Jackson, MS, USA
    index: 1
  - name: Coastal and Hydraulics Laboratory, U.S. Army Engineer Research and Development Center, Vicksburg, MS, USA
    index: 2
date: 22 September 2026
bibliography: paper.bib
---

# Summary

`MRRpy` is an open-source, MIT-licensed Python package for studying how
rainfall becomes surface runoff and moves through a watershed. Starting with a digital elevation model (DEM), it
delineates a drainage network, supplies or reads precipitation, generates runoff,
and routes water to an outlet hydrograph. Runoff generation and routing are
separate choices: researchers can compare methods on the same terrain and
forcing, route an externally computed runoff field, or add an upstream inflow
hydrograph. The package also records a routed-water mass-balance diagnostic.
Its Python API, command-line interface, and QGIS plugin use the same
configuration and pipeline.

# Statement of need

Flood-response studies often need to isolate one modeling decision. A hydrologist
might compare saturation-excess with infiltration-excess runoff while keeping
the routing scheme fixed, or compare routing numerics while keeping the runoff
field unchanged. Such experiments require consistent spatial inputs, boundary
conditions, outputs, and water accounting. `MRRpy` provides that common workflow
for environmental engineers, hydrologists, geospatial researchers, and
students. It supports event-scale rainfall-runoff experiments, routing-only
coupling with another model, and teaching in which the consequences of a
modeling choice can be inspected through comparable outlet and internal-gauge
hydrographs.

# State of the field

`pysheds` [@bartos2020] and `pyflwdir` [@eilander2021] provide useful terrain
and flow-network analysis; `MRRpy` uses them as alternative delineation engines
and continues through runoff generation and flood routing. Landlab
[@barnhart2020] offers a broad component framework, while GSSHA/CASC2D
[@downer2004] and LISFLOOD-FP [@bates2010] address related hydrologic or
hydrodynamic problems. `MRRpy` focuses on a narrower research task: selecting
among event runoff methods and D8 routing schemes through one Python
configuration, then evaluating their outputs with the same diagnostics. It is
a grid-network flood-routing model and does not claim to replace a
multidimensional floodplain-inundation solver. Packaging these choices together
also avoids repeatedly building the terrain, forcing, and reporting glue needed
for each comparison — a more focused contribution than extending a terrain
library into a complete hydrologic model.

# Software design

The architecture in \autoref{fig:architecture} separates inputs, DEM processing,
runoff generation, routing, and outputs. A `Config` object drives the same `run_pipeline`
orchestrator through Python, the CLI, or QGIS. DEM processing reprojects and
conditions terrain, computes D8 flow directions and accumulation, and
delineates the catchment to a selected outlet. Users can choose `pysheds`
[@bartos2020; @ocallaghan1984] or `pyflwdir` [@eilander2021; @wang2006].

![MRRpy's processing chain, from terrain and precipitation inputs through D8 watershed delineation to selectable runoff-generation and routing methods, ending in an outlet hydrograph, watershed depth/flow/velocity fields, and a mass-balance diagnostic. Runoff generation offers a spatial coefficient, SCS Curve Number, or the process-based combination of saturation-excess, infiltration-excess, and impervious mechanisms; the resulting effective-runoff field, a prescribed runoff raster, or an external point-inflow boundary condition then drives one of four routing families — kinematic, diffusive (explicit or semi-implicit), Muskingum–Cunge, or local-inertial dynamic wave. Virtual gauges and per-cell field archives are optional and not shown. The direct-rainfall runoff mode is omitted from the schematic for clarity.\label{fig:architecture}](Process.png){width="100%"}

Precipitation can be a uniform event, a gauge field interpolated by Thiessen
polygons or inverse-distance weighting, or IMERG satellite rainfall
[@huffman2020]. An optional elevation rule excludes snow-zone precipitation
from event runoff. Soil and land-cover parameters can come from local inputs
or Google Earth Engine [@gorelick2017]: root-zone depth from ESA WorldCover
land cover [@zanaga2022], field capacity and wilting point from SoilGrids
[@poggio2021], and porosity and saturated hydraulic conductivity from
HiHydroSoil [@simons2020].

The runoff
layer converts rainfall to effective runoff in metres per second per active
cell. Its built-in choices are direct rainfall, a spatial runoff coefficient,
SCS Curve Number [@chow1988; @jaafar2019], a prescribed raster time series,
and a process-based mode. The latter combines Variable Source Area
saturation-excess [@pradhan2010], Green–Ampt infiltration-excess
[@green1911; @rawls1983], and impervious shedding without counting the same
rainfall twice. The `RunoffMode` interface exposes
`get_effective_1d` and `update_state`; a registration decorator allows new
methods, although the fixed-choice `Config` list must also be extended to use
a new name through the standard configuration path.

The router receives the same effective-runoff field regardless of its source.
It offers kinematic wave, explicit diffusive wave, variable-parameter
Muskingum–Cunge [@cunge1969; @ponce1978], local-inertial dynamic wave
[@bates2010; @dealmeida2012], and semi-implicit diffusive wave schemes.
External point inflow hydrographs enter the routing network separately.
Explicit storage-based branches can use adaptive Courant steps and a
volume-conservative flux limiter; Muskingum–Cunge instead advances discharge
as its state. The semi-implicit branch iterates a water-surface conductance and
solves a coupled linear system on the D8 tree. Its direct tree sweep costs
linear time per iteration, with optional Numba [@lam2015] acceleration and a
SciPy [@virtanen2020] sparse fallback. It runs on the CPU; the other routing
paths can use an optional CuPy
GPU backend. The linear solve removes the explicit diffusive scheme's CFL
stability restriction, but time-step size and nonlinear convergence still
require attention. Adding a new routing scheme requires both a registry entry
and integration with the time loop.

A routing run always computes an outlet hydrograph and writes a CSV
routed-water mass-balance ledger; a full pipeline run additionally writes the
watershed files from DEM processing. Virtual-gauge series and per-cell depth,
velocity, and discharge archives are optional. Process-based runoff runs
additionally partition runoff by generating mechanism. These common outputs
make comparisons across configurations inspectable without implying that
different schemes produce identical physical solutions.

# Research impact statement

The repository includes an end-to-end Trishuli basin example using satellite
rainfall and a separate upstream-inflow scenario, together with documentation
and an interactive course explaining the methods. These are reproducible use
cases, rather than claims of predictive validation. Automated tests cover
configuration, runoff composition, raster alignment, boundary inflow, and
end-to-end mass-balance closure; the continuous-integration workflow targets
Python 3.9–3.12. The semi-implicit branch is included in the end-to-end closure
test. A separate verification script compares its tree solve with dense and
sparse reference solvers and its routed response with a linear diffusion-wave
benchmark; that script is outside default `pytest` discovery. These materials
support controlled method comparisons and give researchers starting points for
independent evaluation on their own basins.

# AI usage disclosure

Generative AI assistance — Anthropic's Claude Code CLI, using several Claude
model versions (Sonnet 4.6, Opus 4.6, Opus 4.8, Sonnet 5, and Fable 5) over
the course of development — was used throughout this project for code
implementation, refactoring, test scaffolding, and documentation drafting, and
was used to draft and revise text in this manuscript. All AI-assisted code and
text were reviewed, tested, and edited by the human authors, who are
responsible for the correctness of the software, the validity of the reported
results, and the content of this paper.

# Acknowledgements

`MRRpy` is built on the open-source scientific-Python and geospatial
ecosystem — including NumPy [@harris2020], SciPy [@virtanen2020], `rasterio`,
GeoPandas, `pysheds`, and `pyflwdir` — and we thank their developers and
maintainers.

This research was supported in part by an appointment to the Department of
Defense (DOD) Research Participation Program administered by the Oak Ridge
Institute for Science and Education (ORISE) through an interagency agreement
between the U.S. Department of Energy (DOE) and the DOD. ORISE is managed by
ORAU under DOE contract number DE-SC0014664. All opinions expressed in this
paper are the authors' and do not necessarily reflect the policies and views of
DOD, DOE, or ORAU/ORISE.

This research is also supported by the Hydrological Impacts Computing, Outreach,
and Resiliency Partnership (HICORPS) Project, developed in collaboration with the
U.S. Army Engineer Research and Development Center (ERDC), WOOLPERT, and Taylor
Engineering. We thank Jackson State University (JSU) for providing computational
resources and infrastructure support throughout this research.

# References
