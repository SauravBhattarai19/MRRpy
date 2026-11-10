---
title: 'MRRpy: A modular Python model for distributed rainfall–runoff, flood routing, and inundation mapping'
tags:
  - Python
  - hydrology
  - hydrodynamics
  - flood modeling
  - rainfall-runoff
  - watershed delineation
  - kinematic wave
  - Muskingum-Cunge
  - flood inundation mapping
  - flood forecasting
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
    ror: 01ecnnp60
  - name: Coastal and Hydraulics Laboratory, U.S. Army Engineer Research and Development Center, Vicksburg, MS, USA
    index: 2
    ror: 027mhn368
date: 9 November 2026
bibliography: paper.bib
---

# Summary

`MRRpy` is an open-source, modular Python package that simulates floods,
from rain to flood map, for a river basin anywhere on Earth. From a digital
elevation model (DEM) and rainfall from a design storm, rain gauges,
satellites, or weather-model forecasts, it traces the drainage network,
estimates how much rain runs off, routes the water through every grid cell
and river channel, and maps flood depth and extent along every river or, in
two dimensions (2D), over a chosen town, river segment, or whole watershed.
Every step offers interchangeable methods, and any combination runs from one
configuration through a Python API, a command-line wizard, a Jupyter form
[@kluyver2016], or a QGIS plugin [@qgis2026]. Missing inputs are fetched
from Google Earth Engine and Open-Meteo, so even a basin with no local data
can be modeled, and its floods forecast, within minutes. `MRRpy` installs
from PyPI and is documented at <https://mrrpy.readthedocs.io>.

# Statement of need

Floods expose about 1.8 billion people to significant risk
[@rentschler2022], many in basins with few or no gauges, where models must
start from global data [@hrachowitz2013]. Flood studies usually chain
separate tools for rainfall, runoff, routing, and mapping, each with its own
formats. Comparing two runoff methods with routing held fixed, testing a new
infiltration model, or turning a weather forecast into a flood map means
rebuilding that chain by hand, and inputs, mass accounting, and outputs are
easily made inconsistent. `MRRpy` factors precipitation, runoff generation,
routing, and flood mapping into independent stages behind one configuration,
so a comparison is a change of setting and a new method inherits the rest of
the model, its inputs, outputs, and tests. Because each stage hands the next
only a field, users can bring their own physics: their own rainfall product
(as gauge-style series) or runoff algorithm (a registered class, or runoff
rasters from another model) drives `MRRpy`'s routing and flood mapping
unchanged, and a user who already has runoff and needs only a router can use
those stages alone. With `MRRpy`, users can:

- **model an ungauged basin** from global terrain, soils, land cover, and
  satellite or weather-model rainfall, then swap in local data;
- **compare methods** with everything else held fixed, or sweep every
  combination of methods and channel geometry;
- **forecast floods** from weather-model rainfall up to 16 days ahead,
  continuing each update from the saved model state, or replay archived
  forecasts as hindcasts;
- **route known inflows** (a gauge record, a reservoir release, a dam-break
  or lake-outburst hydrograph) from any river point, with or without rain;
- **map floods** along every river in seconds, or in 2D over a town, several
  river segments, or a whole watershed.

`MRRpy` serves hydrologists, engineers, and forecasters; developers testing
new components; GIS practitioners through its QGIS plugin; and students,
through readable code and an interactive textbook
(<https://sauravbhattarai19.github.io/MRRpy/>).

# State of the field

`pysheds` [@bartos2020] and `pyflwdir` [@eilander2021] are strong Python
libraries for D8 terrain analysis but stop at flow directions and
delineation; `MRRpy` uses either and continues through runoff, routing, and
flood mapping. Landlab [@barnhart2020] is a general Earth-surface-dynamics
framework from whose components a comparable model could be assembled, with
more effort. GSSHA [@downer2004] is a mature, physically based distributed
hydrologic model under continued development [@pradhan2019water;
@pradhan2024], while LISFLOOD-FP [@bates2010; @dealmeida2012] and HEC-RAS
[@brunner2021] provide advanced floodplain hydraulic modeling capabilities,
and Height Above Nearest Drainage (HAND) methods [@nobre2011; @zheng2018]
map the U.S. National Water Model's forecasts [@aristizabal2023].
Complementing these established modeling systems, `MRRpy` emphasizes a
modular Python-based architecture that facilitates the integration,
interchange, and evaluation of runoff-generation, routing, and flood-mapping
methods through standardized interfaces. We are not aware of an open tool
that lets a user combine any rainfall source, runoff method, and routing
scheme on the same grid, add a new method that immediately works with all
the others, check every combination for mass conservation, and carry the
result to a flood map. For engineering design around levees, culverts, or
bridges, a dedicated hydraulic model remains the right tool.

# Software design

One configuration object drives the pipeline (\autoref{fig:architecture})
from every interface, and one parameter catalog generates the wizard, the
notebook form, and the manual's tables.

![MRRpy's processing chain, from terrain and precipitation (including weather-model forecasts) through selectable runoff and routing methods and optional flood maps (HAND, or 2D over a town, river segments, or the whole watershed) to the outputs, including restart files for forecast updates. Flood-map panels: `MRRpy` results for Kathmandu, Nepal (HAND), and Montpelier, Vermont (2D).\label{fig:architecture}](Process.png){width="100%"}

**Terrain and parameters.** DEM processing conditions the terrain (by
default least-cost carving [@yamazaki2012] with `pyflwdir` [@wang2006];
`pysheds` [@ocallaghan1984] with filling remains available), computes D8
flow directions, and delineates the catchment above an outlet or keeps the
whole DEM. The DEM, soil, and land-cover parameters come from local inputs
or Earth Engine [@gorelick2017], including ESA WorldCover [@zanaga2022],
SoilGrids [@poggio2021], and HiHydroSoil [@simons2020].

**Precipitation** returns a rain-rate field per cell at any time. Sources
are a uniform hyetograph, rain gauges (Thiessen polygons or inverse-distance
weighting), IMERG satellite rainfall [@huffman2020], and Open-Meteo
[@zippenfenig2023] weather-model reanalyses, forecasts, and archived
forecast runs; satellite pixels and model cells become pseudo-gauges for the
same interpolators.

**Runoff generation** is a registry of interchangeable modes behind one
interface: direct rainfall, a runoff coefficient, SCS Curve Number
[@chow1988; @jaafar2019], a prescribed raster, and a process-based mode. The
process-based mode is itself a second registry of mechanisms composed per
cell without counting rainfall twice; the built-in ones are Green–Ampt
infiltration excess [@green1911; @rawls1983], saturation excess, and
impervious shedding, with soil recovery between storms following EPA SWMM 5
[@rossman2016]. Saturation excess uses the variable-source-area theory of
@pradhan2010, which needs only an initial soil-moisture deficit, here from
the satellite-based SERVES method [@pradhan2019serves]; developed earlier as
a stand-alone theory, it is applied here for distributed simulation
alongside standard Green–Ampt. A new method is a class registered with a
decorator.

**Routing** schemes are likewise registered. Kinematic wave,
variable-parameter Muskingum–Cunge [@cunge1969; @ponce1978], and a
semi-implicit diffusive wave are supported, and a local-inertial scheme
[@dealmeida2012] is experimental. Channel cells carry a sub-grid channel
[@neal2012] sized to a bankfull discharge that is user-given or estimated
globally [@linke2019; @andreadis2013]. The semi-implicit scheme applies the
classical direct elimination for tree-structured systems to the whole D8
grid, giving an exact implicit solve in linear time without the explicit
Courant limit, using Numba [@lam2015] or SciPy [@virtanen2020]. Kinematic
routing, runoff, and precipitation can run on a CuPy [@okuta2017] GPU backend. Inflow
hydrographs can enter at any channel point, with or without rain.

**Flood maps.** Routing keeps overbank water in a D8 ribbon one cell wide,
so an optional stage spreads it over the land. Maps are drawn after routing
from the saved discharge, on a finer DEM where one exists (such as LiDAR or
30 m FABDEM [@hawker2022]), so they can be redrawn without rerouting and 2D
effort goes only where needed. HAND mapping [@nobre2011] turns each reach's
flow into a water level with a synthetic rating curve [@zheng2018] and
floods all land below it: every river in seconds, but blind to backwater.
The 2D option solves the local-inertial equations [@bates2010] over a town,
several river segments, or the whole watershed, each fed by the routed
rivers and inflow, so water spreads, ponds, and backs up while mass is
conserved exactly.

**Outputs** are common to every combination: an outlet hydrograph, a
mass-balance ledger, and optionally virtual gauges, per-cell fields, runoff
by mechanism, and flood depth, extent, and timing maps. Restart files carry
the model state between forecast updates, reproducing an uninterrupted run.

**Testing.** Because every method meets the same interface, the model is
tested as a whole. Continuous integration (Python 3.9–3.12) runs each
supported routing scheme with each runoff method and every subset of the
physical mechanisms over two storms separated by a dry spell; each run must
close its mass balance to $10^{-6}$ and never produce more runoff than rain,
so a new component is checked against every existing one. Further tests
compare restarted with uninterrupted runs and GPU with CPU, check the 2D
solver against a lake at rest and an analytic flood wave [@hunter2005], and
verify the semi-implicit solve against direct solvers.

# Research impact statement

`MRRpy` 1.0 is released on PyPI with a QGIS plugin, a manual, 13 worked
examples, Jupyter notebooks, and an interactive textbook, so each capability
can be reproduced. Several examples simulate historical floods in Nepal, the
United States, and Germany from global data alone.

`MRRpy` drives an experimental, automated flood forecast for Lynch Creek, a
38 km² urban basin in Jackson, Mississippi
(<https://github.com/SauravBhattarai19/lynch-forecast>). Every six hours it
takes rainfall forecasts from five weather models, continues the model from
its saved state, maps flood depth along every creek on 1 m lidar, and
publishes a public dashboard
(<https://sauravbhattarai19.github.io/lynch-forecast/>); the same setup
maps the 10- and 20-year return-period floods (NOAA Atlas 14 design storms)
in 2D over four river segments. All of its hydrology comes from `MRRpy`, so
another basin needs only its own configuration files. More applications will
follow as worked examples.

Its significance is practical. Once a basin is set up, the same model can be
calibrated against gauges by sweeping parameters such as roughness or soil
conductivity, run for many scenarios (design storms, land-use change, or
upstream, reservoir-release, and dam-break hydrographs as boundary
conditions), and tracked at any point through virtual gauges and flood maps.
Driven by weather-model forecasts, it maps the coming inundation before the
flood arrives, so early warning and flood-risk planning become feasible in
basins with little data, and a shared interface spares method research new
plumbing.

# AI usage disclosure

Anthropic's Claude Code CLI (Claude Sonnet 4.6, Opus 4.6, Opus 4.8, Sonnet 5,
Fable 5, and Opus 5.5) was used for code implementation, refactoring, test
scaffolding, documentation, and drafting and revising this manuscript. All AI-assisted
code and text were reviewed, tested, and edited by the human authors, who
are responsible for the correctness of the software, the validity of the
reported results, and the content of this paper.

# Acknowledgements

`MRRpy` is built on the open-source scientific-Python and geospatial
ecosystem, including NumPy [@harris2020], SciPy [@virtanen2020], pandas
[@mckinney2010; @pandas2020], Matplotlib [@hunter2007], `rasterio`
[@gillies2013], GeoPandas [@fleischmann2026], `pysheds`, and `pyflwdir`, and
on the Google Earth Engine [@gorelick2017] and Open-Meteo [@zippenfenig2023]
data services. We thank their developers and maintainers.

This research was supported in part by an appointment to the Department of
Defense (DOD) Research Participation Program administered by the Oak Ridge
Institute for Science and Education (ORISE) through an interagency agreement
between the U.S. Department of Energy (DOE) and the DOD. ORISE is managed by
ORAU under DOE contract number DE-SC0014664. All opinions expressed in this
paper are the authors' and do not necessarily reflect the policies and views of
DOD, DOE, or ORAU/ORISE.

This research was also supported by the U.S. Army Engineer Research and
Development Center, Coastal and Hydraulics Laboratory (ERDC–CHL), through its
Earth System Hydrology research initiative, with technical support provided
under the ERDC–CHL professional services contract with Taylor–Woolpert, LLC.

`MRRpy`, an open-source hydrologic modeling software package, was developed
through research collaboration between the U.S. Army Engineer Research and
Development Center, Coastal and Hydraulics Laboratory (ERDC–CHL), and the
Hydrology Laboratory at Jackson State University (JSU).

# References
