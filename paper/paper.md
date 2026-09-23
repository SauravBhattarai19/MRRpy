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
  - GPU computing
  - semi-implicit methods
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

`MRRpy` is an open-source Python package for distributed, event-scale
rainfall-runoff simulation and channel flood routing. Given a digital
elevation model, it delineates a D8 drainage network, generates surface
runoff by one of several interchangeable methods, and routes the resulting
flow to a basin outlet using one of five interchangeable numerical schemes:
kinematic wave, explicit diffusive wave, variable-parameter
Muskingum–Cunge, local-inertial dynamic wave, and a semi-implicit diffusive
wave. The semi-implicit scheme takes advantage of a simple property of D8
networks. Because a filled DEM's flow directions form a tree rather than a
general graph, the linearized flow equations can be solved exactly, in time
linear in the number of cells, without the Courant restriction that limits
explicit schemes on steep terrain.

Runoff generation, channel routing, upstream boundary inflow, and
diagnostic output are independent stages of one pipeline, driven by a single
configuration object. Changing one field of that configuration is enough to
swap a runoff method, a routing scheme, or the source of soil and rainfall
forcing, which makes it straightforward both to isolate the effect of a
single modeling decision and to run many configurations in sequence for
calibration or uncertainty exploration. Every routing run produces an outlet
hydrograph and a mass-balance ledger; per-cell depth, velocity, and discharge
fields, and fixed-point gauge series, are recorded on request. An upstream
discharge hydrograph, from a gauge, a reservoir, or another model, can also
be injected directly into the channel network, with or without rainfall. The
same configuration and pipeline are exposed through a Python API, a
command-line interface, and a QGIS plugin, and can draw rainfall, soil, and
terrain data from Google Earth Engine when no local data exist for a basin.

# Statement of need

Isolating a single modeling decision in an event-scale flood study is harder
than it should be. A hydrologist who wants to know whether Green–Ampt
infiltration-excess or a saturation-excess variable source area produces a
better hydrograph, with routing held fixed, usually has to patch together
two independent research codes or rebuild the runoff-to-routing-to-diagnostics
plumbing by hand. The reverse comparison, holding runoff fixed while testing
routing numerics, is just as common and just as tedious to set up. Consistent
spatial inputs, boundary handling, mass-balance accounting, and output
formats are exactly the parts of that comparison that are easy to get
subtly wrong and expensive to rebuild for every new experiment. `MRRpy`
factors runoff generation and channel routing into independent, registrable
pipeline stages behind one configuration object, so changing the comparison
means changing one setting rather than one codebase.

Because every run is driven by the same configuration object, the same
design supports a second, equally important use: running many configurations
instead of one. A parameter sweep, or a full factorial across routing
scheme, runoff mechanism, and channel geometry, is simply a loop over
configuration values and pipeline calls, and the mass-balance ledger
accumulates one row per run so that dozens or hundreds of configurations stay
directly comparable in a single table instead of being scattered across
separate output folders. This is not a hypothetical capability: the
repository's own research tooling already uses this pattern to run
full-factorial studies of several hundred configurations across multiple
flood events, resumable across sessions and organized into a self-describing
folder tree. The same optional GPU backend that accelerates one run also
accelerates a sweep of many runs without any change to the model code, so a
small calibration exercise can stay on a laptop CPU while a larger one moves
to a GPU by changing a single configuration field.

That flexibility matters most when time is short. A flood emergency in a
basin with no rain gauges, no soil survey, and no existing hydrologic model
is common rather than rare. Because `MRRpy` can resolve rainfall, soil, and
terrain forcing directly from Google Earth Engine given only a watershed
boundary, a working model of an ungauged basin can be assembled without a
separate data-acquisition and GIS-preprocessing step. Because the runoff and
routing choices are configuration values rather than code, the same setup
can then be run across a plausible range of infiltration, source-area, and
routing assumptions instead of committing to a single untested guess. The
result is a bounded set of hydrographs rather than one, produced fast enough
to inform a response rather than a postmortem.

`MRRpy` serves environmental engineers and hydrologists running controlled
method comparisons or calibration sweeps, researchers coupling routing-only
runs to an external rainfall-runoff or reservoir model through the
boundary-condition interface, and instructors and students who need a
runnable, inspectable implementation of each method rather than a black box.
The same configuration and pipeline are exposed through a Python API, a
command-line interface, and a QGIS desktop plugin, so the package is usable
by a GIS practitioner as well as a programmer. An interactive textbook
bundled with the repository works through the physical assumptions behind
each modeling choice.

# State of the field

`pysheds` [@bartos2020] and `pyflwdir` [@eilander2021] are strong Python
libraries for D8 terrain and flow-network analysis, but they stop at
delineation and flow directions. `MRRpy` uses either as its delineation
engine and continues through runoff generation, routing, and diagnostics.
Landlab [@barnhart2020] is a general-purpose Earth-surface-dynamics
component framework capable of far more than event flood routing, though
assembling a model from its lower-level components takes more work than
`MRRpy`'s single configuration file, since `MRRpy` is purpose-built for the
narrower task of comparing runoff methods and routing schemes. GSSHA/CASC2D
[@downer2004] is a mature, physically comprehensive distributed model, and
`MRRpy`'s saturation-excess mechanism implements the same Pradhan and Ogden
variable source area formulation [@pradhan2010] published by one of
GSSHA's own authors. GSSHA is nonetheless a compiled model conventionally
driven through a separate desktop GUI, not an installable, scriptable Python
package with a registrable-mode API.

LISFLOOD-FP [@bates2010] and its local-inertial formulation
[@dealmeida2012] solve the fuller two-dimensional shallow-water problem
needed for floodplain inundation extent. `MRRpy` solves a cheaper, narrower
problem: one-dimensional flow on the D8 channel network rather than
inundation extent, with the same local-inertial equations available as one
routing choice among five rather than as its central contribution. Its
semi-implicit diffusive-wave scheme is best understood as a lightweight,
open, Python-native counterpart to the semi-implicit solvers used in tools
such as HEC-RAS [@brunner2021]. Because a D8-conditioned network is provably
a tree rather than a general graph, the same linearized-diffusion system
that such tools solve iteratively can instead be solved exactly, by one
forward-and-back sweep in time linear in the cell count. This simplification
is specific to tree-structured networks and would not carry over to a
general cross-section network with junctions and loops. `MRRpy` does not
claim to replace a multidimensional floodplain-inundation solver or a
general river-network hydraulics package. Packaging a focused set of runoff
and routing choices behind one configuration, with consistent forcing,
boundary handling, and diagnostics, is a more tractable contribution than
extending a terrain library or a general framework into a complete
hydrologic model.

# Software design

The architecture in \autoref{fig:architecture} separates inputs, DEM processing,
runoff generation, routing, and outputs. A `Config` object drives the same `run_pipeline`
orchestrator through Python, the CLI, or QGIS. DEM processing reprojects and
conditions terrain, computes D8 flow directions and accumulation, and
delineates the catchment to a selected outlet. Users can choose `pysheds`
[@bartos2020; @ocallaghan1984] or `pyflwdir` [@eilander2021; @wang2006].

![MRRpy's processing chain, from terrain and precipitation inputs through D8 watershed delineation to selectable runoff-generation and routing methods, ending in an outlet hydrograph, watershed depth/flow/velocity fields, and a mass-balance diagnostic. Runoff generation offers a spatial coefficient, SCS Curve Number, or the process-based combination of saturation-excess, infiltration-excess, and impervious mechanisms; the resulting effective-runoff field, a prescribed runoff raster, or an external point-inflow boundary condition then drives one of four routing families: kinematic, diffusive (explicit or semi-implicit), Muskingum–Cunge, and local-inertial dynamic wave. Virtual gauges and per-cell field archives are optional and not shown. The direct-rainfall runoff mode is omitted from the schematic for clarity.\label{fig:architecture}](Process.png){width="100%"}

Precipitation can be a uniform event, a gauge field interpolated by Thiessen
polygons or inverse-distance weighting, or IMERG satellite rainfall
[@huffman2020]. An optional elevation rule excludes snow-zone precipitation
from event runoff. Soil and land-cover parameters can come from local inputs
or Google Earth Engine [@gorelick2017]: root-zone depth from ESA WorldCover
land cover [@zanaga2022], field capacity and wilting point from SoilGrids
[@poggio2021], and porosity and saturated hydraulic conductivity from
HiHydroSoil [@simons2020].

The runoff layer converts rainfall to effective runoff in metres per second per active
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
Explicit storage-based branches can use adaptive Courant steps and a
volume-conservative flux limiter; Muskingum–Cunge instead advances discharge
as its state. The semi-implicit branch iterates a water-surface conductance and
solves a coupled linear system on the D8 tree. Its direct tree sweep costs
linear time per iteration, with optional Numba [@lam2015] acceleration and a
SciPy [@virtanen2020] sparse fallback. It runs on the CPU; the other routing
paths can use an optional CuPy GPU backend. The linear solve removes the explicit diffusive scheme's CFL
stability restriction, but time-step size and nonlinear convergence still
require attention. Adding a new routing scheme requires both a registry entry
and integration with the time loop.

An upstream discharge hydrograph can be injected into the routing network
independently of rainfall-runoff generation. A boundary-condition entry
locates the injection point by row and column, by projected easting and
northing, or by latitude and longitude, snaps it to the nearest channel cell
(the cell of highest flow accumulation within a configurable radius), and
reads a discharge time series from a CSV file. The value is linearly
interpolated in time and holds at the last recorded value beyond the series,
with a warning printed to the log. Multiple boundary points are supported
and summed where two of them snap to the same cell. Setting rainfall to zero
then yields a pure boundary-driven routing run, the mechanism for routing an
upstream gauge record, a reservoir release schedule, or another model's
discharge output through the channel network without invoking runoff
generation at all.

Every routing run writes an outlet hydrograph CSV, reporting peak discharge
and time to peak, and appends one row to a routed-water mass-balance ledger
recording rainfall input, boundary inflow, outflow, storage change, and
closure error. That ledger accumulates across successive runs rather than
being overwritten, so a parameter sweep remains self-describing and directly
comparable in a single table. A full pipeline run additionally writes the
watershed files produced by DEM processing. Two further outputs are
optional. Named virtual gauges record depth, discharge, and velocity at
fixed, channel-snapped locations at every output step, a memory-cheap way to
obtain fine-cadence series at specific points without saving the whole
domain. A field archive records per-cell depth, velocity, discharge, and
volume at a configurable stride, into a compact, georeferenced archive that
a loader scatters back onto the two-dimensional grid for plotting or
animation. Process-based runoff runs additionally partition the outlet
volume by generating mechanism (saturation-excess, infiltration-excess,
impervious). A bundled plotting module provides one-call helpers for the
hydrograph, a raster, the watershed boundary, and the mass-balance ledger,
each accepting a file path, a DataFrame, a pipeline result, or the `Config`
object itself, so a run's results can be inspected without hand-written
`matplotlib` or `rasterio` code. These common outputs make comparisons
across configurations inspectable, without implying that different schemes
produce identical physical solutions.

# Research impact statement

`MRRpy`'s exact, linear-time tree solve for the semi-implicit diffusive-wave
scheme is, on its own, a transferable numerical-methods contribution. It
removes a stability restriction that has historically forced a choice
between small time steps and an iterative implicit solve, by exploiting a
structural property that other D8-based grid routers already have but do
not currently use this way: D8 flow direction is a tree, not a general
graph. This claim is verified rather than asserted. A dedicated
verification script compares the tree solve against dense and sparse
reference linear solvers, checks mass-balance closure on a synthetic valley
DEM, confirms convergence to the Manning normal-depth solution in the
kinematic limit, reproduces the expected diffusion-wave attenuation and lag
signature, and compares the routed response against the analytical Hayami
linear diffusion-wave benchmark. The scheme is also exercised inside the
end-to-end mass-balance closure test that continuous integration runs
across Python 3.9 through 3.12.

Accessibility is a second channel of impact. Exposing one configuration and
pipeline through a Python API, a command-line interface, and a QGIS desktop
plugin means the same runoff and routing choices are usable by a
programmer-researcher and by a GIS-trained practitioner or agency
hydrologist, without either needing the other's tooling. Optional Google
Earth Engine integration removes the largest practical barrier to an event
study on an ungauged or data-sparse basin, the local acquisition and
preprocessing of satellite rainfall, soil, and terrain rasters, reducing that
step to specifying a watershed boundary. Combined with the
configuration-driven sweep pattern described above, this makes rapid,
multi-scenario model setup practical for basins and situations, including
time-critical ones, where no dedicated hydrologic model previously existed.

The repository includes an end-to-end Trishuli basin example in Nepal,
driven by satellite rainfall, and a separate upstream-inflow
boundary-condition scenario, together with an interactive textbook that
works through the physical assumptions behind each runoff and routing
choice, including the graph-theoretic argument for the semi-implicit
scheme's exact solve. These are reproducible use cases and teaching
material, not claims of predictive validation against observed streamflow.
Automated tests separately cover configuration round-tripping,
runoff-mechanism composition, raster alignment, boundary inflow, and
end-to-end mass-balance closure across all five routing schemes. Together,
these materials support controlled method comparisons, give researchers a
starting point for independent evaluation on their own basins, and give
instructors a runnable reference implementation rather than a black box.

# AI usage disclosure

Generative AI assistance, Anthropic's Claude Code CLI using several Claude
model versions (Sonnet 4.6, Opus 4.6, Opus 4.8, Sonnet 5, and Fable 5) over
the course of development, was used throughout this project for code
implementation, refactoring, test scaffolding, and documentation drafting,
and was used to draft and revise text in this manuscript. All AI-assisted
code and text were reviewed, tested, and edited by the human authors, who
are responsible for the correctness of the software, the validity of the
reported results, and the content of this paper.

# Acknowledgements

`MRRpy` is built on the open-source scientific-Python and geospatial
ecosystem, including NumPy [@harris2020], SciPy [@virtanen2020], `rasterio`,
GeoPandas, `pysheds`, and `pyflwdir`, and we thank their developers and
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
