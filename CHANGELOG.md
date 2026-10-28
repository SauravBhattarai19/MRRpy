# Changelog

## Unreleased

### Added
- Open-Meteo weather-model rain: `PRECIP_METHOD: openmeteo_thiessen` (code 5)
  or `openmeteo_idw` (code 6). Rain from the world's weather models (ECMWF,
  GFS, ICON, HRRR, …) and reanalyses (ERA5) for **a past storm or a forecast
  up to 16 days ahead**, from the storm start `EVENT_START_UTC` for the
  simulation length. It needs internet but no account or Earth Engine. Each
  model cell over the basin becomes a rain gauge at its centre, like the
  IMERG pixels. `OPENMETEO_SOURCE` (`auto` picks the forecast or the
  historical archive from the date), `OPENMETEO_MODEL`, `OPENMETEO_MINUTELY_15`,
  `OPENMETEO_POINT_SPACING_M`, `OPENMETEO_BBOX_BUFFER_M` and
  `PRECIP_OPENMETEO_FORCE_DOWNLOAD` tune it; the rain is cached in
  `<results>/openmeteo/` and downloaded again when the request changes.
- `OPENMETEO_SOURCE: single_run` with `OPENMETEO_RUN`: replay one model run as
  it was issued (ECMWF IFS from March 2024), for forecast hindcasts with no
  look-ahead.
- The manual lists the Open-Meteo models that give rain (global, regional and
  historical), what `best_match` uses, and the names that return no rain.
- A "real or forecast storm with weather-model rain" starting point in the
  wizard and the notebook form; Open-Meteo panels in the QGIS plugin and its
  Processing algorithm.

### Tests
- `tests/test_openmeteo.py`: API choice by date, the query grid, merging
  points into model cells, the time convention, trimming past the forecast
  horizon, single model runs, the cache, error messages, and full routed runs (against a fake
  server; `MRRPY_LIVE_OPENMETEO=1` also calls the real API).

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
