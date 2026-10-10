# Changelog

## 0.4.0 — HAND flood maps

### Added
- **Flood depth and extent maps (HAND).** With `INUNDATION_MAP: true` a run
  turns the routed river flow into flood maps. Every cell gets its height above
  the river it drains to; each ~1 km river reach gets a rating curve (the
  model's own bankfull channel plus the land beside it, each cell with its own
  roughness); the reach's peak flow gives the water level that floods all lower
  land. Main rivers are mapped again on their own so they back up into side
  streams (`INUNDATION_BACKWATER`). Writes `inundation/flood_depth_max.tif`,
  `flood_extent_max.tif/.geojson`, `flood_animation.gif`, the time of the peak,
  first-wet time and duration, HAND, per-reach tables and rating curves.
  Routing results do not change: the recorder only reads the flow. Flow paths
  for the maps are traced on the original DEM by least-cost search (Metz et al.
  2011), so rivers stay in their real channels across flat valley floors, and
  heights are measured on the original DEM above a river bed lowered only
  (NOAA OWP practice); on the Kathmandu valley floor, a filled DEM gave
  straight-line rivers and flood stripes.
- Finer flood maps than the model grid: `INUNDATION_DEM: auto` uses the run's
  Earth Engine DEM at its native resolution when the model ran coarser (e.g.
  FABDEM 30 m for a 90 m run); `file` takes your own DEM (e.g. LiDAR); a dataset
  name downloads one. Each fine river takes the flow of the routed river nearby
  that drains about the same area. `INUNDATION_AREA` limits the maps to a box;
  the flow still comes from the whole basin.
- A new `inundation` pipeline stage (`MRRpy run --stages inundation`) redraws
  the maps without routing again. `plot_inundation` and `animate_inundation` in
  Python.
- QGIS plugin: a flood-maps group on the Routing tab, **Load Flood Maps** and
  **Open Flood Animation** on the Results tab, and an `INUNDATION_MAP`
  Processing parameter.

### Tests
- `tests/test_inundation.py`: HAND and reaches on hand-built networks; the
  rating curve equals the model's channel section with no floodplain and the
  analytic V-valley; full runs (peak = hydrograph peak for kinematic,
  Muskingum–Cunge and implicit; routing unchanged; redraw; finer DEM; area;
  `auto` fallback; whole DEM).

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
