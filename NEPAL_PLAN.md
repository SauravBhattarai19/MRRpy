# MRRpy-Nepal — plan

This branch makes MRRpy a **Nepal-specific, physics-based flood model that
works alongside the official Nepali estimation methods**. The physics core
(DEM → rain → runoff → routing) stays exactly as it is. A new layer,
`MRRpy.nepal`, adds:

* the official regional and rainfall-based methods,
* the return periods each agency's manual requires,
* design storms built the way Nepali practice builds them,
* a comparison of the physics result against the official range,
* simple interfaces (notebook, command line, QGIS) where you tick the
  methods you want.

It is built from the compendium *Nepal Flood Estimation Methods* (the
methods document shared for the DoWRI pilot ToR). Every coefficient in the
code comes from that document. Where the document says a value still has
to be checked against the original report, the code says so too.

---

## 1. Principles

1. **Official methods are first-class.** Reviewers in Nepal expect to see
   WECS/DHM, DHM 2004, Modified Dickens and the others. MRRpy-Nepal computes
   them automatically from the DEM: area, area below 3,000 m and 5,000 m, snow
   area, flow length and slope. Nobody has to measure them by hand in a GIS.
2. **The physics model is the site-specific method.** Section 6 of the
   compendium explains why the national formulas break down for small
   Chure/Terai streams: they use area only, and ignore rainfall, slope and
   soil. MRRpy adds exactly those three.
3. **The two are always shown together.** Every physics design flood is
   reported against the envelope of the official methods. Every method row
   carries a validity flag: *ok*, *caution*, *outside its range*, or *needs
   input*.
4. **No unverified numbers.** A method goes in only when the compendium gives
   its complete formula. The rest are listed in §2.3 with what is missing.
5. **Not confusing.** You choose an agency or manual, and the methods it names
   are ticked for you. You choose a structure, and its design return period is
   ticked. Only the inputs the ticked methods need appear on screen.
6. **No change for existing users.** Nothing in `Config`, the router or the
   existing forms changes behaviour. The only addition to the core is two Nepal
   presets for bankfull flow (§3).

---

## 2. Method filter

### 2.1 Adopted: computed by `MRRpy.nepal`

| Method (compendium §) | Key | What it gives | Inputs (auto = from the DEM) | Where it plugs in |
|---|---|---|---|---|
| WECS/DHM 1990, HYDEST (3.1) | `wecs_dhm` | instantaneous Q_T, any T | A₃₀₀₀ (auto) | official envelope |
| WECS/DHM 1990, daily (3.1) | `wecs_dhm_daily` | daily-mean Q_T | A₃₀₀₀ (auto) | table only (not a peak) |
| Sharma & Adhikari, DHM 2004 (3.2) | `dhm_2004` | instantaneous Q_T | A₃₀₀₀ (auto) | official envelope; bankfull preset |
| MHSP 1997, NEA (3.3) | `mhsp_1997` | Q_T for T = 5, 20, 50, 100 | A (auto), region (you choose) | official envelope |
| Modified Dickens (3.5) | `modified_dickens` | Q_T, any T | A, snow area above 5,000 m (auto) | official envelope |
| Specific discharge, WECS 2019 (3.15) | `specific_discharge` | Q_T for T = 2, 25, 50, 100 | A (auto) | official envelope; bankfull preset |
| Rational + Kirpich + Mononobe (3.8) | `rational` | Q_T | C; 24-h rain R₂₄; L, S (auto) | rainfall-based |
| Frequency analysis: Gumbel, LP-III, GEV (3.11) | `frequency` | Q_T with confidence band | annual-maximum floods | gauge-based |
| Catchment area ratio (3.12) | `area_ratio` | Q_T from a donor gauge | donor area and its Q_T (or its series) | gauge-based |
| Process-based model (3.19) and design-storm modelling (§8) | `physics` | full hydrograph, peak, volume | R₂₄, storm pattern, model settings | **MRRpy itself** |
| Flood marks, slope–area (3.13) | helper | an observed peak (no T) | surveyed area, perimeter, slope, n | evidence line on the chart |
| MIP 1982 (4.1) | flows | 12 mean monthly flows | region 1–7, one dry-season measurement | monthly-flows tab |
| WECS/DHM 1990 monthly (4.3) | flows | 12 mean monthly flows | A, A₅₀₀₀ (auto), MMP | monthly-flows tab |
| MHSP 1997 monthly (4.4) | flows | 12 mean monthly flows | A (auto), MMP | monthly-flows tab |
| CAR / similar catchment (4.5) | flows | a scaled donor series | donor series and areas (and rain) | monthly-flows tab |
| 80 % dependable flow (4.7) | flows | Q₈₀ per month | a multi-year monthly series | monthly-flows tab |
| E-flow rule (4.8) | flows | 10 % of the minimum monthly flow | monthly flows | monthly-flows tab |
| 7Q10, log-normal (4.9) | flows | 7-day, 10-year low flow | a daily series | monthly-flows tab |

### 2.2 Kept as comparison only (never in the design envelope)

| Method | Why it is kept | Why it is not trusted |
|---|---|---|
| Dickens original (3.4) | appears in older designs | no return period; the constant is a judgement |
| Ryves, Inglis (3.14) | used in DoR screening checks | fitted to South Indian and Maharashtra regions; the 65 km² example spans 165–928 m³/s |

### 2.3 Deferred: waiting for verified data

| Method | Missing piece | Plan |
|---|---|---|
| B.D. Richards (3.6) | the t_c relation and the intensity reduction are not given; the areal factor F is printed two ways (0.6628 vs 0.066628) | add once the DoR hydrology guideline text is at hand |
| PCJ 1996 / 2024 (3.7) | coefficient tables (O_p, φ, k_t, k_f) and C₁₀₀ are not reproduced | add from Jha's papers; Subedi et al. (2022) found it the most accurate of seven methods |
| Tahal index flood (3.10) | Narayani growth factors are not reproduced | superseded by our own regional L-moment growth curves (Phase 2) |
| Updated MIP 2016 (4.2) | the 22-region ratio tables are not reproduced | add with the WRPPF tables and region polygons |
| WECS/DHM low flows and FDC (4.3) | coefficients are not reproduced | add from the HYDEST report |
| Fuller (3.14) | C_f and the peak-to-daily adjustment are not given | only if a source is found |
| Envelope curves (3.16) | no Nepal-specific curve exists | build from DHM annual maxima in Phase 2 |

### 2.4 Not adopted

| Method | Reason |
|---|---|
| WECS 1982 (3.20) | superseded, and its coefficients could not be verified ("do not use for design") |
| Khosla (4.6) | ignores storage and baseflow; MRRpy's continuous simulation replaces it |
| Snyder / SCS unit hydrographs (3.9) | MRRpy routes the hydrograph physically on the DEM. SCS-CN losses are already a runoff option (`RUNOFF_SOURCE: scs_cn`) |
| GLOF / LDOF (3.18) | outside this package's scope (an unrelated study shares the workspace). MRRpy can already route a given outburst hydrograph with `ROUTING_INFLOW_BC` |

---

## 3. How the official methods power the physics model

1. **Design rainfall the Nepali way.** Annual-maximum daily rainfall at a DHM
   station is fitted with Gumbel, LP-III or GEV to get the T-year 24-hour
   rainfall R₂₄. That depth is spread in time with the **Mononobe curve, the
   same one the official Rational method uses**. MRRpy-Nepal turns it into a
   centre-peaked hyetograph (alternating blocks) and runs it through the
   physics model. Optional factors: areal reduction, climate change (the ToR's
   climate delta factors), and the WMO fixed-day to 24-hour factor.
2. **Channels sized by the official 2-year flood.** The model channel carries
   the bankfull flow, which is about the 2-year flood. `CHANNEL_QBF_M3S` already
   accepts `wecs_nepal`. This branch adds `dhm2004_nepal` and
   `specific_q_nepal`, evaluated at every river cell.
3. **High ground treated like the official A₃₀₀₀ rule.** WECS/DHM uses the area
   below 3,000 m because higher ground gives less flood runoff. Nepal design
   storms ramp the rain share from 1 at 3,000 m to 0 at 5,000 m, using the
   existing `RAIN_SNOW_ELEV_LOW/HIGH` settings. This can be switched off.
4. **The official envelope is the plausibility check.** The physics Q_T is
   reported as inside, above or below the range of the applicable official
   methods, along with its ratio to their median.
5. **Calibration targets (Phase 2).** The curve number or the Ksat multiplier
   is scaled so the physics Q₂ (or Q₁₀₀) matches a gauge's frequency analysis,
   a flood-mark discharge, or a chosen official estimate.

---

## 4. Architecture

```
MRRpy/nepal/
  descriptors.py   catchment numbers from the DEM results (A, A₃₀₀₀, A₅₀₀₀,
                   snow area, L, S, S10-85, Lc, elevations, outlet, river class)
  methods.py       registry of flood methods: formulas, validity flags,
                   estimate_floods() → FloodEstimates (table, envelope, notes)
  frequency.py     Gumbel, LP-III, GEV (L-moments), plotting positions,
                   bootstrap confidence bands
  design_storm.py  Mononobe intensity, design hyetographs, MRRpy rain-gauge CSVs
  physics.py       design-flood runs of the MRRpy model (one per return period)
  guidelines.py    agency presets → methods; structures → design return
                   periods; the compendium's §7 recommendation
  flows.py         MIP 1982, WECS/DHM and MHSP monthly, CAR, Q80, e-flow, 7Q10
  study.py         NepalStudy: settings → run() → NepalResult (CSV, report, plot)
  cli.py           `MRRpy nepal estimate | methods | frequency | monthly | design-storm`
  form.py          NepalForm(): the Jupyter interface (ipywidgets)
  report.py        the chart and the Markdown report
MRRpy_plugin/processing/alg_nepal.py
                   QGIS Processing: "Nepal flood estimates" and "Nepal design storm"
MRRpy_plugin/processing/nepal_options.py
                   the dialog → NepalStudy mapping (plain Python, tested without QGIS)
```

Outputs go to `<results folder>/nepal/`:

* `nepal_flood_estimates.csv` and `nepal_report.md` (table, range, warnings, sources)
* `nepal_flood_estimates.png` (Q against return period for every method, with the official range shaded)
* `catchment.csv` (the measured catchment numbers)
* `design_T<T>/` (storm CSVs, hydrograph, gauges, maps)
* `mass_balance_design.csv` (one water-balance row per design run)

---

## 5. Interface design

The same three questions appear in the notebook form, the command line and QGIS:

1. **Site.** Choose one: a DEM file and an outlet (delineated on the spot), the
   results folder of an earlier MRRpy run, or the catchment numbers typed in.
2. **Design.**
   * *Agency / manual* ticks the methods that manual names: DoWRI 2019, DoWRI
     PDSP 1990, DoLIDAR 2015, DoED 2018, WECS 2019, DoR bridges, AEPC 2004,
     NEA MHSP, *recommended for this catchment*, or *all*.
   * *Structure* ticks its design return period: bridge 100; culvert 25;
     aqueduct 50; weir 50–100; barrage 100–500; embankment 50–100; intake
     10–25; study 2–500.
   * Under each ticked method, only its inputs appear (MHSP region; C and R₂₄;
     the donor gauge; the annual-maximum series).
3. **Results.** A table of Q by return period with validity flags, the official
   range, the physics result, a chart, and a saved CSV and report.

Monthly and low flows sit on a separate tab, so the flood steps stay short.

---

## 6. Roadmap

**Phase 1 — done in this branch**

* `MRRpy.nepal` with every method in §2.1 and §2.2, plus the design storms,
  physics runs, guidelines, recommendation and report.
* `MRRpy nepal …` CLI, `NepalForm`, and QGIS Processing algorithms.
* Bankfull presets `dhm2004_nepal` and `specific_q_nepal`.
* Tests that reproduce every worked example in the compendium, and an
  end-to-end physics test on a small synthetic basin (`tests/test_nepal_*.py`,
  `MRRpy_plugin/tests/test_nepal_options.py`).
* Documentation pages (`docsite/nepal/`) and an example notebook
  (`notebooks/nepal_flood_study.ipynb`).
* Not yet tried inside a real QGIS: the Processing algorithms are checked only
  against a stand-in for `qgis.core`, and the option mapping by unit tests.
  Run them once in QGIS before relying on them.

**Phase 2 — needs data or verification**

* B.D. Richards and PCJ once their full formulas are confirmed.
* Regional L-moment frequency analysis (Hosking & Wallis): discordancy and
  heterogeneity tests, growth curve times index flood, and an index-flood
  regression on catchment descriptors (area, rain, slope, land cover). This is
  the method the ToR names.
* Calibrating the physics model to a gauge frequency analysis or flood marks.
* Satellite depth–duration–frequency curves (IMERG/CHIRPS annual maxima)
  where no DHM gauge is close.
* A dedicated "Nepal" tab in the QGIS dialog (built on the same core
  functions, once it can be tested in QGIS).
* DHM station-file readers.

**Phase 3**

* Updated MIP 2016 (22 regions), WECS/DHM low flows and FDC, FDC
  regionalisation, and baseflow index.
* Climate delta factors from CMIP6 (NEX-GDDP), applied to the design rainfall.
* GloFAS-ERA5 donors, bias-checked.

---

## 7. To check against the original reports

These come from the compendium's "Note on sources" boxes. Each is flagged in
the method's notes in the code as well.

* WECS/DHM Q₂ exponent: 0.8783 is used; some papers print 0.8737 or drop the "+1".
* WECS/DHM size range: AEPC says over 100 km² and not in the Siwalik or Terai;
  Subedi et al. (2022) say 100 km² or less.
* DHM 2004: does mean basin elevation enter the formula?
* MHSP: the regional coefficients (as reproduced in Subedi et al. 2022) and
  the region boundaries. The compendium says Kailali is probably Western.
* Modified Dickens: the denominator of p is A + a (the published form);
  some sources write A.
* B.D. Richards: the areal reduction factor F.
* MIP 1982 and 2016: which region the far-western Terai and Chure fall in.
* E-flow rule that applies to irrigation intakes.

---

## 8. Validation

* **Worked examples.** Every number in the compendium's 65 km² Chure example,
  the MIP Region 4 example and the CAR example is a unit test.
* **Published comparisons.** Next, compute the six basins of Subedi et al.
  (2022) and the seven of Shrestha et al. (2010) and compare with their tables.
* **ToR Task 1.** Apply every method, and the physics model, to the small
  gauged far-western catchments and compare with the observed floods and low
  flows.
