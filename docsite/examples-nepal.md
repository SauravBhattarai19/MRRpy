# Nepal flood example (Trishuli basin)

An end-to-end, real-data walkthrough on the **upper Gandaki / Narayani (Trishuli)
basin** in central Nepal — from delineation, through a satellite-driven monsoon
flood, to a shock-preserving **GLOF (glacial-lake outburst flood)** routing run
with the local-inertial `dynamic` scheme.

Two contrasting jobs on one basin:

1. **Rainfall flood** — IMERG rainfall → Green–Ampt + impervious runoff (soil and
   land cover from Earth Engine) → kinematic routing → outlet + station hydrographs.
2. **GLOF routing** — a burst inflow hydrograph at a headwater, routed with no
   rainfall using the `dynamic` scheme, calibrated to observed wave-arrival times.

!!! note "Prerequisites"
    `pip install pymrr[gee]`, an authenticated Earth Engine project (see
    [Configuration → Earth Engine setup](configuration.md#earth-engine-setup-first-time)),
    and a DEM covering the basin. GPU (`pip install pymrr[gpu]`) is optional but
    recommended for the 30–90 m grids below.

---

## 1. Delineate the basin (reservoir-safe engine)

The Trishuli has large flat reaches; use the `pyflwdir` engine, whose
priority-flood conditioning avoids the D8 flow collapse `pysheds` can show across
wide flats.

```python
from pymrr import Config, run_pipeline, plot_watershed

cfg = Config(
    DEM_PATH="dem.tif",                       # 30 m DEM covering the basin
    OUTPUT_DIR="trishuli/",
    OUTPUT_POINT=(27.802367, 84.843618),      # (lat, lon) — basin outlet
    TARGET_CRS_EPSG="EPSG:32645",             # UTM 45N
    DELINEATION_ENGINE="pyflwdir",            # reservoir-safe
)
cfg.update_output_paths()

out = run_pipeline(cfg, stages=("process_dem",))
plot_watershed(out)[0].savefig("trishuli/watershed.png")
# → ~6,220 km² basin: glaciated headwaters (>7000 m) down to the ~360 m outlet
```

---

## 2. Post-monsoon IMERG rainfall

pymrr pulls NASA GPM **IMERG V07** (half-hourly, 0.1°) straight from Earth Engine
and turns each pixel into a pseudo-gauge, so the same Thiessen/IDW machinery drives
the router. Point it at an event window with `EVENT_START_UTC` +
`TOTAL_SIMULATION_TIME_HOURS`; it downloads once and caches to `PRECIP_IMERG_DIR`.

The example event is the **late-September 2024 central-Nepal flood** — the record
post-monsoon storm on this basin (a ~44 h, ~240 mm basin-mean soaking).

```python
cfg.EVENT_START_UTC = "2024-09-26 00:00"      # UTC
cfg.TOTAL_SIMULATION_TIME_HOURS = 96.0
cfg.PRECIP_METHOD = "imerg_idw"               # IMERG pixels → IDW to the grid
cfg.PRECIP_IMERG_DIR = "trishuli/imerg/"
cfg.GEE_PROJECT = "your-ee-project"
```

!!! tip "Design-storm / frequency analysis"
    To *choose* an event objectively, fetch many post-monsoon seasons and rank them
    by basin-averaged accumulation at a flood-relevant duration (24–72 h), then fit
    an extreme-value (Gumbel/GEV) distribution. The 2024 storm is the record
    maximum at every duration here. See the standalone frequency-analysis recipe in
    the project's `tools/`.

---

## 3. Rainfall flood — Green–Ampt + impervious, kinematic routing

All soil and land-cover parameters come from Earth Engine; runoff is
infiltration-excess (Green–Ampt) plus impervious shedding, with **no**
saturation-excess. Because the basin reaches the freezing level, an
**elevation rain/snow partition** removes snow-zone precipitation from event
runoff, and rivers are routed as **confined channels** (Strahler-order widths).

```python
cfg = Config(
    OUTPUT_DIR="trishuli/",
    DEM_PATH="trishuli/clipped_dem.tif",
    TARGET_CRS_EPSG="EPSG:32645",
    GEE_PROJECT="your-ee-project",
    BACKEND="gpu",                            # falls back to CPU automatically
    EVENT_START_UTC="2024-09-26 00:00",
    TOTAL_SIMULATION_TIME_HOURS=96.0,

    # precipitation: per-pixel IMERG, IDW to the grid
    PRECIP_METHOD="imerg_idw",
    PRECIP_IMERG_DIR="trishuli/imerg/",

    # runoff: Green–Ampt infiltration-excess + impervious (no saturation-excess)
    RUNOFF_SOURCE="physical",
    RUNOFF_MECHANISMS=["impervious", "infiltration_excess"],
    GA_KSAT_SOURCE="gee",                     # HiHydroSoil conductivity
    GA_SUCTION_SOURCE="texture",              # SoilGrids texture → wetting-front suction
    VSA_SD_SOURCE="gee",                      # SERVES antecedent moisture deficit
    IMPERVIOUS_SOURCE="lulc",                 # ESA WorldCover impervious fraction

    # rain/snow partition: precip > 5000 m is snow (excluded); ramp 4500–5000 m
    RAIN_SNOW_ELEV_LOW=4500.0,
    RAIN_SNOW_ELEV_HIGH=5000.0,

    # routing: kinematic, confined channels, Manning's n from land cover
    ROUTING_SCHEME="kinematic",
    MANNINGS_N_SOURCE="lulc",
    MANNINGS_N_CHANNEL=0.035,
    CHANNEL_ROUTING=True,                     # Strahler-order channel widths
    ADAPTIVE_TIMESTEP=True,

    # virtual gauges along the Trishuli (snapped to channel)
    ROUTING_GAUGES=[
        {"name": "Timure",     "lat": 28.270,  "lon": 85.378},
        {"name": "Syabrubesi", "lat": 28.1636, "lon": 85.3364},
        {"name": "Betrawati",  "lat": 27.974,  "lon": 85.185},
        {"name": "Malekhu",    "lat": 27.802,  "lon": 84.844},
    ],
    # optional: per-cell depth/velocity/discharge archive for animation
    SAVE_FIELDS=True, FIELD_VARS=["depth", "velocity", "discharge"], FIELD_STRIDE=3,
)
cfg.update_output_paths()
cfg.PRECIP_IMERG_DIR = "trishuli/imerg/"      # re-assert after update_output_paths()

import os
out = run_pipeline(cfg, stages=("routing",))
print("outlet hydrograph :", out["hydrograph_csv"])              # trishuli/hydrograph.csv
print("station hydrographs:", os.path.join(cfg.OUTPUT_DIR, "gauges.csv"))
print("mass balance       :", cfg.MASS_BALANCE_CSV)             # closes to ~1e-12 %
```

The outlet peak, the runoff partition (Green–Ampt dominant, impervious minor,
saturation-excess zero), and per-station arrivals are all written to CSV; the
`gauges.csv` gives depth, discharge and velocity at each station every output step.

---

## 4. GLOF routing with the `dynamic` scheme

A sharp glacial-lake outburst surge propagating into a dry, steep channel is
exactly what the kinematic and Muskingum–Cunge schemes *cannot* preserve
(numerical diffusion / coefficient damping smear it away). The **local-inertial
`dynamic` scheme** keeps the ∂Q/∂t term, so the shock travels at the true
dynamic-wave celerity √(gh)+u and survives to the outlet — mass-conservatively.

This run has **no rainfall**: the only water source is an inflow hydrograph
injected at the Lende Khola headwater via `ROUTING_INFLOW_BC`.

### 4a. Build the burst hydrograph

A triangular outburst delivering 4 Mm³ over 7.5 min (peak ≈ 17,800 m³/s):

```python
import numpy as np, pandas as pd

V, dur = 4.0e6, 450.0                          # 4 Mm³ over 7.5 min
Qp = 2 * V / dur                               # triangular peak ≈ 17,778 m³/s
t = np.array([0, dur / 2, dur, dur + 1, 21600.0])
Q = np.array([0, Qp,      0,   0,       0.0])
pd.DataFrame({"time_s": t, "Q_m3s": Q}).to_csv("trishuli/inflow_lende.csv", index=False)
```

### 4b. Route it with elevation-wise Manning's n

Wave-arrival times are calibrated with **elevation-wise channel n** — low n in the
steep high headwaters (fast upper reach), higher n in the flat lower reach. Manning's
`n` accepts a `{(min_elev, max_elev): n}` dict of elevation bins for channel cells.

```python
cfg = Config(
    OUTPUT_DIR="trishuli_glof/",
    DEM_PATH="trishuli/clipped_dem.tif",       # 90 m routing grid recommended (see note)
    TARGET_CRS_EPSG="EPSG:32645",
    BACKEND="gpu",
    TOTAL_SIMULATION_TIME_HOURS=10.0,
    OUTPUT_INTERVAL_SECONDS=60,                 # 1-min output for arrival precision

    # no rainfall — pure downstream routing of the injected surge
    PRECIP_METHOD="uniform", RAIN_INTENSITY_MM_HR=0.0, RAIN_DURATION_HOURS=1.0,
    RUNOFF_SOURCE="none",

    # local-inertial dynamic wave (shock-preserving)
    ROUTING_SCHEME="dynamic",
    DYNAMIC_FLUX_THETA=0.85,                    # de Almeida flux-centering (damps oscillation)
    ADAPTIVE_TIMESTEP=True, CFL_TARGET=0.7,

    # confined channels + elevation-wise channel roughness (calibration lever)
    CHANNEL_ROUTING=True,
    CHANNEL_FACCUM_THRESHOLD=500,              # channelize down to the headwater reach
    MANNINGS_N_SOURCE="scalar", MANNINGS_N=0.06,
    MANNINGS_N_CHANNEL={                       # channel n by elevation band [m]
        (0, 600):     0.025,                   # flat lower reach (slower)
        (600, 1500):  0.004,                   # mid reach
        (1500, 9000): 0.004,                   # steep high reach (fast)
    },

    # burst inflow at Lende Khola (snapped to channel)
    ROUTING_INFLOW_BC=[{"name": "Lende", "lat": 28.284, "lon": 85.517,
                        "csv": "trishuli/inflow_lende.csv"}],

    # gauges with observed wave-arrival targets (min after burst): 23 / 43 / 193
    ROUTING_GAUGES=[
        {"name": "Syabrubesi", "lat": 28.1636, "lon": 85.3364},
        {"name": "Betrawati",  "lat": 27.9740, "lon": 85.1850},
        {"name": "Malekhu",    "lat": 27.8020, "lon": 84.8440},
    ],
)
cfg.update_output_paths()

out = run_pipeline(cfg, stages=("routing",))
# gauges.csv → wave arrival at each station; mass balance closes to ~1e-13 %
```

!!! note "Grid resolution for GLOF routing"
    Route the surge on a **~90 m** grid (resample the DEM and re-run
    `process_dem`). At 30 m the ~1,000-cell path and near-vertical cells make the
    explicit dt impractical; 90 m keeps the same basin (~6,220 km²) with ~9× fewer
    cells and finishes in seconds–minutes on GPU.

!!! warning "Physical caveats for GLOF runs"
    - **Arrival *times* are the robust output**; peak *magnitudes* can carry residual
      local-inertial oscillation — lower `DYNAMIC_FLUX_THETA` (0.6–0.8) to damp it.
    - A very flat lower reach can be a near-stalling regime where arrival is highly
      parameter-sensitive — treat downstream timing as a bracket.
    - Calibrated channel `n` can fall below clear-water values: a real GLOF is a
      **debris flow**, faster than clear-water Manning predicts. For full debris-flow
      dynamics, a dedicated model (e.g. r.avaflow) is more appropriate.

---

## What this example exercises

- `pyflwdir` delineation on a reservoir-prone basin
- IMERG rainfall + Green–Ampt/impervious runoff, all parameters from Earth Engine
- elevation rain/snow partition and confined (Strahler) channel routing
- named virtual gauges and per-cell field archives
- the shock-preserving `dynamic` (local-inertial) scheme for GLOF routing with an
  inflow boundary condition and elevation-wise `n`
