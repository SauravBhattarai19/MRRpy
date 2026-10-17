# Changelog

## Unreleased

### Added
- **Flood depth and extent maps.** With `INUNDATION_MAP: true` a run turns the
  routed river flow into flood maps, drawn on the real ground: the DEM as it
  is, with no channel cut below it (a DEM's river surface is already the water
  of the day it was made; cutting the model's bankfull channel below a 30 m DEM
  drew floods 1–8 m too low at Nakhu, Montpelier and the Pearl River). Only
  bridges and DEM bumps across the river line are cleared. Writes
  `inundation/flood_depth_max.tif`, `flood_extent_max.tif/.geojson`,
  `flood_animation.gif`, the time of the peak, first-wet time and duration.
  Routing results do not change: the recorder only reads the flow. Flow paths
  for the maps are traced on the original DEM by least-cost search (Metz et al.
  2011), so rivers stay in their real channels across flat valley floors; on
  the Kathmandu valley floor, a filled DEM gave straight-line rivers and flood
  stripes. `INUNDATION_METHOD` picks how the water is spread:
  - `hand` (default): every cell gets its height above the river it drains to;
    each ~1 km reach gets a rating curve from the land that drains to it, each
    cell with its own roughness; the reach's flow gives the water level that
    floods all lower land, and main rivers are mapped again on their own so
    they back up into side streams. Seconds for a whole basin. Also writes
    HAND, per-reach tables and rating curves.
  - `2d`: a 2D flood simulation over `INUNDATION_AREA` (local-inertial
    equations, Bates et al. 2010, compiled and parallel): every river entering
    the area brings its routed flow, the land inside adds the water the routing
    passed into its rivers there, and water leaves at normal depth where the
    rivers leave the area. Water spreads, ponds and backs up as on the ground.
    MRRpy simulates the period around the largest flood, after filling the
    rivers with its starting flow. Also writes the fastest flow and the
    inflows; warns when the flood reaches the edge of the area. Tested against
    high-water marks (Montpelier, VT, 2023: water level within 0.2–0.4 m on
    LiDAR), a gauge (Pearl River at Jackson, MS, 2020: 0.4 m RMSE) and
    satellite flood traces (Kathmandu 2024), closer than `hand` everywhere.
- Finer flood maps than the model grid: `INUNDATION_DEM: auto` uses the run's
  Earth Engine DEM at its native resolution when the model ran coarser (e.g.
  FABDEM 30 m for a 90 m run); `file` takes your own DEM (e.g. LiDAR); a dataset
  name downloads one. Each fine river takes the flow of the routed river nearby
  that drains about the same area. `INUNDATION_AREA` limits the maps to a box;
  the flow still comes from the whole basin. A finer DEM cut out around the
  area lets water out only where the routed water leaves it, so rivers flowing
  in cannot drain the land behind a DEM dam backwards (the Kathmandu valley
  floor behind the Chobhar gorge), an entering river joins the fine network at
  the lowest ground near where the routed river crosses the edge, and a river
  that leaves and re-enters the cut-out DEM round a meander brings its area
  once (the Ahr had doubled).
- Example 13 and `notebooks/flood_maps_2d.ipynb`: a 2D flood map for a town
  from satellite rain, step by step, with how big to make the area and measured
  run times at five places (Montpelier, Kathmandu, East Rapti, the Ahr valley,
  the Pearl at Jackson). In the notebook form's map, the rectangle tool now sets
  either the area to download or the area for the flood maps.
- A new `inundation` pipeline stage (`MRRpy run --stages inundation`) redraws
  the maps without routing again. `plot_inundation` and `animate_inundation` in
  Python.
- QGIS plugin: a flood-maps group on the Routing tab (with the method),
  **Load Flood Maps** and **Open Flood Animation** on the Results tab, and
  `INUNDATION_MAP`, `INUNDATION_METHOD` and `INUNDATION_AREA` Processing
  parameters.

### Fixed
- Earth Engine downloads (terrain, soils, land cover) no longer hang a run on a
  stalled connection: a connection silent for 5 minutes is dropped and the
  download tried again, then reported.

### Tests
- `tests/test_inundation.py`: HAND and reaches on hand-built networks; the
  rating curve equals the model's channel section with no floodplain and the
  analytic V-valley; full runs (peak = hydrograph peak for kinematic,
  Muskingum–Cunge and implicit; routing unchanged; redraw; finer DEM; area;
  `auto` fallback; whole DEM); the maps lie on the DEM (no channel below it);
  the 2D maps (water balance, a river flowing into an area with its routed
  flow, redraw, switching methods, old flood-map data); a DEM cut out around
  an area with a 15 m DEM dam still drains down the valley.
- `tests/test_flood2d.py`: the 2D solver — lake at rest, exact water balance,
  Manning normal depth, the Hunter et al. (2005) flood wave, restarting, the
  same result on any number of threads; river-bed grading.
- `tests/test_gee_download.py`: a stalled download ends in a clear error, a good
  one arrives whole (a local server, no Earth Engine needed).

## 0.3.0

**Results change for Green-Ampt runs longer than one storm.** Set
`GA_RECOVERY: false` to reproduce 0.2.0.

### Added
- `GA_RECOVERY` (on by default): Green-Ampt soil dries out between storms,
  using the EPA SWMM 5 method (Rossman & Huber 2016). Soaked-in water fills a
  shallow upper soil layer that drains in dry weather. After a dry spell the
  next rain starts a new storm on drier soil. Every parameter follows from
  Ksat, so no extra data is needed. Without recovery the soil only gets wetter
  for the whole run. Checked against the SWMM 5.2 engine.
- QGIS plugin 3.1.0: a "Let the soil dry out between storms" checkbox on the
  Runoff tab.

### Fixed
- `diffusive_implicit` could create water on the first storm after a dry
  spell. The adaptive time step had grown to the output interval, and the
  first wet step over-drained cells that were then reset to zero (+11.5 % water
  in a two-storm test). Such steps are now retried at half the time step. The
  log reports how many steps were retried.

### Tests
- `tests/test_runoff_recovery.py`: recovery over dry spells, short gaps and
  repeating storms; mass conservation; GPU matching CPU; and
  `GA_RECOVERY: false` reproducing the 0.2.0 update exactly.
- `tests/test_component_matrix.py`: every routing scheme with every runoff
  mechanism, including CPU against GPU.

## 0.2.0

First release under the `MRRpy` name.
