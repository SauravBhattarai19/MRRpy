---
title: 'hydroflow: A modular Python model for distributed rainfall–runoff generation and flood routing'
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
    corresponding: true
    affiliation: 2
  - name: Rocky Talchabhadel
    orcid: 0000-0003-0526-7663
    corresponding: true
    affiliation: 1
affiliations:
  - name: Department of Civil and Environmental Engineering, Jackson State University, Jackson, MS, USA
    index: 1
  - name: Coastal and Hydraulics Laboratory, U.S. Army Engineer Research and Development Center, Vicksburg, MS, USA
    index: 2
date: 11 September 2026
bibliography: paper.bib
---

# Summary

`hydroflow` is an open-source Python package for distributed rainfall–runoff
and flood-routing modeling. It is organized around two independent,
interchangeable layers connected by a simple contract: a **runoff-generation**
layer that converts precipitation into effective surface runoff, and a
**flood-routing** layer that moves that water across the terrain to produce a
hydrograph. Because the layers are decoupled, a user can combine any runoff
method with any routing scheme, swap either one in isolation, or bypass runoff
generation altogether and route a precomputed runoff field supplied as a raster
time series — for example, output from a separate land-surface or hydrologic
model.

Runoff generation is exposed as an extensible, two-tier system. At the top level
a user selects a runoff *method* from an open registry: a runoff coefficient, a
prescribed-raster time series (see below), the SCS Curve Number method
[@chow1988; @jaafar2019], a process-based mode, or none. The process-based mode
in turn *composes* established runoff mechanisms — Dunne saturation-excess via
the Variable Source Area one-parameter model of @pradhan2010, Hortonian
infiltration-excess via Green–Ampt [@green1911; @rawls1983], and impervious
urban shedding — which can be enabled individually or in any combination and are
merged without double-counting, with each mechanism's contribution tracked
separately. The registry is deliberately open: a `@register` decorator lets a
third-party package contribute an entirely new runoff method without modifying
`hydroflow`, so further established schemes can be added as needed. The routing
layer provides three interchangeable numerical schemes on the D8 drainage
network — kinematic-wave, diffusive-wave, and variable-parameter Muskingum–Cunge
[@cunge1969; @ponce1978] — with adaptive time-stepping and always-on
mass-balance verification, so different process representations and routing
numerics can be compared on identical terrain and forcing.

The scientific core is pure NumPy/SciPy/rasterio [@harris2020], with an optional
CuPy GPU backend that falls back to the CPU automatically. A single
configuration object drives three interfaces from the same code — a Python API,
a command-line interface, and a QGIS plugin — so the model is equally usable in
scripts, in reproducible batch pipelines, and through a graphical GIS workflow.
Optional Google Earth Engine [@gorelick2017] integration can supply satellite
rainfall [@huffman2020], soil properties [@poggio2021], land cover, and even the
DEM itself, while every method retains a fully offline fallback.

# Statement of need

Distributed hydrologic models typically bundle one runoff-generation scheme with
one routing solver behind a monolithic interface. This makes a common and
important task awkward: holding the terrain, forcing, and numerics fixed while
varying a *single* modeling choice — for example, testing whether
saturation-excess or infiltration-excess dominates a catchment's response, or how
a kinematic, diffusive, or Muskingum–Cunge router changes the simulated peak. The
tools most trusted in engineering practice — HEC-HMS/HEC-RAS, TUFLOW, and
comparable commercial packages — are largely closed-source and GUI-centric, and
are hard to script or embed in a reproducible pipeline. Powerful open-source
codes exist — LISFLOOD-FP [@bates2010], GSSHA/CASC2D [@downer2004], and the
Landlab framework [@barnhart2020] — but assembling an end-to-end run, or
substituting a single component, often demands substantial setup or familiarity
with the code base. Focused Python libraries such as `pysheds` [@bartos2020] and
`pyflwdir` [@eilander2021] handle terrain analysis and flow routing on grids but
stop short of coupled runoff generation and channel hydraulics.

`hydroflow` addresses this gap by making runoff generation and routing
**independent, interchangeable, and extensible** under one mass-conservative
engine. Its target users — environmental engineers, hydrologists, geospatial
researchers, and students — can mix and match built-in components from a single
`Config` object, register an entirely new runoff method from their own package
without touching the core, or drive the router directly with an externally
computed runoff field or an injected upstream discharge hydrograph, enabling
routing-only studies and loose coupling to other models.
Because every configuration is scored with the same always-on mass-balance and
runoff-partition diagnostics, results across combinations are directly
comparable, which makes the package as useful for controlled methodological
experiments and teaching as it is for applied flood simulation.

Three further design choices lower the barrier to entry. A single duck-typed
`Config` object is the entire contract: every knob lives in one place,
fixed-choice options accept either a canonical string or an integer code and are
normalized on assignment, and a cross-field `validate()` step catches errors
before a run starts. The same `run_pipeline` orchestrator backs all three
interfaces, so a workflow prototyped interactively in the QGIS plugin reproduces
verbatim from the CLI or the Python API. Finally, optional Google Earth Engine
integration removes the traditional data-gathering bottleneck — a DEM, IMERG
satellite rainfall [@huffman2020], SoilGrids soil texture [@poggio2021], and land
cover can be fetched automatically — yet the identical model runs entirely
offline from local files when Earth Engine is unavailable.

# Software architecture and functionality

A `hydroflow` run is organized as an ordered pipeline of stages. `process_dem`
reprojects, pit-fills, and computes D8 flow direction and accumulation, then
delineates the contributing watershed to a chosen outlet; two interchangeable
engines are provided (`pysheds` [@bartos2020], following @ocallaghan1984, and
`pyflwdir` [@eilander2021; @wang2006], which better handles flow across large
flat water bodies). A runoff engine then converts precipitation into effective
surface runoff under a documented forward-Euler contract (`get_effective_1d`
then `update_state`), dispatching by name to the selected method in the
registry. This contract is the seam that decouples the two layers: the router
sees only an effective-runoff field, so a prescribed-runoff series (a CSV
manifest of single-band, GDAL-readable rasters in m/s, each reprojected and
resampled onto the model grid) or an injected boundary discharge hydrograph can
drive it with no runoff generation at all. Finally, the
`routing` stage flattens the grid into topological, upstream-first order and
advances an explicit finite-volume time loop in which each cell's storage is
updated from upstream inflow and Manning-based outflow. Numerical robustness
comes from adaptive Courant–Friedrichs–Lewy time-stepping, a volume-conservative
flux limiter, and a mass-balance ledger that is reported for every run —
regardless of the chosen method or scheme — and by design closes to near
machine precision.

The model is backend-agnostic: every hot kernel is written against an array
module (`xp`) that is NumPy on the CPU or CuPy on a CUDA GPU, selected at grid
initialization with automatic CPU fallback when no device is present. Outputs
include the delineated watershed (GeoTIFF and GeoJSON), the outlet hydrograph
and mass-balance record as CSV, and optional virtual-gauge time series and
compact per-cell field archives for animation and post-processing. Land-cover
lookup tables ship inside the package, and all Earth Engine functionality is
lazily imported so that the core has no cloud or GUI dependencies.

The project is distributed on the Python Package Index with `[gpu]`, `[gee]`,
and `[notebook]` extras, is licensed under MIT, and supports Python 3.9–3.12.
Documentation is published on Read the Docs, and a separate free interactive
course explains the underlying physics. Quality is supported by a `pytest`
suite covering the configuration bridge and an end-to-end routing run, together
with a set of standalone verification scripts that double as reproducible demos
of each major feature.

# Acknowledgements

`hydroflow` is built on the open-source scientific-Python and geospatial
ecosystem — including NumPy, SciPy, `rasterio`, GeoPandas, `pysheds`, and
`pyflwdir` — and we thank their developers and maintainers.

This research was supported in part by an appointment to the Department of
Defense (DOD) Research Participation Program administered by the Oak Ridge
Institute for Science and Education (ORISE) through an interagency agreement
between the U.S. Department of Energy (DOE) and the DOD. ORISE is managed by
ORAU under DOE contract number DE-SC0014664. All opinions expressed in this
paper are the author's and do not necessarily reflect the policies and views of
DOD, DOE, or ORAU/ORISE.

This research is also supported by the Hydrological Impacts Computing, Outreach,
and Resiliency Partnership (HICORPS) Project, developed in collaboration with the
U.S. Army Engineer Research and Development Center (ERDC), WOOLPERT, and Taylor
Engineering. We thank Jackson State University (JSU) for providing computational
resources and infrastructure support throughout this research.

# References
