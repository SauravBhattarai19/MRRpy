# Changelog

## Unreleased — MRRpy-Nepal

Nothing changes for existing runs: the physics core is untouched, and the only
core addition is two bankfull-flow presets.

### Added
- `MRRpy.nepal` (MRRpy-Nepal): the official Nepali flood-estimation methods next
  to the physics model, built from the compendium *Nepal Flood Estimation
  Methods*. See `NEPAL_PLAN.md` for which methods are in, deferred or left out.
  - Catchment numbers measured from the DEM results (`measure_catchment`): A, the
    area below 3,000 m and 5,000 m, permanent snow, the longest flow path and its
    slope, Lc, elevations, and an approximate river class.
  - Flood methods (`estimate_floods`): WECS/DHM 1990 (instantaneous and daily),
    DHM 2004, MHSP 1997, Modified Dickens, specific discharge (WECS 2019),
    Rational (Kirpich + Mononobe), frequency analysis, catchment area ratio;
    Dickens, Ryves and Inglis for comparison only. Each method carries a
    validity flag and its source caveats, and the official range is computed
    per return period.
  - Frequency analysis: Gumbel, Log-Pearson III and GEV (L-moments), each with
    bootstrap confidence bands.
  - Agency presets (DoWRI, DoLIDAR, DoED, WECS, DoR, AEPC, NEA), design return
    periods by structure, and the compendium's quick guide.
  - Design storms: R24 spread with the Mononobe curve into alternating blocks,
    written as rain-gauge CSVs; physics design-flood runs (`run_design_floods`)
    with an offline default model (SCS-CN, WECS/DHM channels, less rain above
    3,000 m).
  - Monthly and low flows: MIP 1982, WECS/DHM and MHSP monthly, the
    lower-of-two low-flow rule, e-flow, 80 % dependable flow, 7Q10.
  - `NepalStudy`: site → methods → table, chart and Markdown report; saved and
    loaded as YAML.
  - Interfaces: the `MRRpy nepal` CLI (`methods`, `estimate`, `frequency`,
    `monthly`, `design-storm`), `NepalForm` for Jupyter, and the notebook
    `notebooks/nepal_flood_study.ipynb`.
- `CHANNEL_QBF_M3S` presets `dhm2004_nepal` and `specific_q_nepal`.
- QGIS plugin: Processing tools "3. Nepal flood estimates (official methods)" and
  "4. Nepal design storm (rain-gauge CSVs)", plus a menu entry.
- Docs for mrrpy-nepal.readthedocs.io: a Nepal-first home page, seven worked use
  cases (culvert, weir, hydropower, gauged bridge, irrigation monthly flows,
  climate factor, screening), and one page per formula family — catchment
  numbers, regional formulas, Rational method and design rainfall, frequency
  analysis, design floods, monthly and low flows — each formula with its
  symbols, derivation, a step-by-step worked example and its validity rules;
  plus manuals/structures and reading the results.

### Fixed
- Docs: `[[NAME]]` setting links now work for names with lower-case letters
  (e.g. `RUNOFF_SCS_Ia_FACTOR`), and `tests/test_docs.py` fails on any link left
  unexpanded.

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
