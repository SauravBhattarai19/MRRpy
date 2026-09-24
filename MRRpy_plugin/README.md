# MRRpy_plugin

**MRRpy_plugin** is the QGIS 3.x plugin for the **MRRpy** distributed rainfall–runoff and
flood-routing model — Variable Source Area – One Parameter Model (VSA-OPM,
Pradhan & Ogden 2010) runoff plus grid-based kinematic / diffusive / dynamic-wave
routing — enabling full model runs from within QGIS with optional GPU
(CuPy/CUDA) acceleration.

---

## Features

| Feature | Detail |
|---|---|
| DEM pre-processing | Reproject → fill sinks → D8 flow direction/accumulation → watershed delineation (pyflwdir or pysheds) |
| Precipitation engines | Uniform · Thiessen · IDW · **NASA GPM IMERG V07 satellite** (Thiessen/IDW) via Google Earth Engine |
| Runoff generation | None · Runoff coefficient · Pre-computed raster series · SCS-CN (scalar / GCN250 via GEE / raster CN, AMC I–III) · **VSA-OPM** |
| OPM mechanisms | Composable: **VSA** saturation-excess + **Green-Ampt** infiltration-excess (Horton) + **impervious** urban shedding |
| Satellite parameters | **SERVES** soil-moisture deficit, SoilGrids porosity/texture suction, HiHydroSoil vertical Ksat (all via GEE, optional) |
| Routing | **Kinematic** · **diffusive** (CASC2D/GSSHA) · **Muskingum–Cunge** · **dynamic** (local-inertial, LISFLOOD-FP) · **semi-implicit diffusive** (HEC-RAS-style, unconditionally stable); confined channel cross-sections, **adaptive CFL** time-stepping, optional Manning slope cap |
| Rain / snow | Optional elevation partition — precipitation above the freezing level is excluded from event runoff |
| Spatial roughness | Manning's n from scalar · ESA WorldCover (LULC) · WUDAPT LCZ · raster, with channel-cell override |
| Diagnostics | Per-run mass-balance report |
| GPU acceleration | CuPy/CUDA backend (optional; falls back to CPU automatically) |
| QGIS Processing | `mrrpy_plugin:process_dem` and `mrrpy_plugin:routing` Processing algorithms (Graphical Modeler compatible) |
| Results viewer | Embedded hydrograph plot · one-click layer loading · CSV/PNG export |

---

## Installation

> Earlier versions were called "VSA-OPM Hydrological Model" (folder `vsa_opm`
> or `vsa_opm_plugin`). Remove that folder first so QGIS loads only
> MRRpy_plugin.

### A. Install from ZIP (recommended, any OS)

```bash
cd /path/to/MRRpy
./build_windows_plugin.sh      # writes MRRpy_plugin.zip (+ _plugin_build/MRRpy_plugin/)
```

QGIS → **Plugins → Manage and Install Plugins → Install from ZIP** → choose
`MRRpy_plugin.zip` → **Install Plugin**. The zip bundles the plugin **and** a
vendored copy of the `MRRpy` core package (under `_vendor/MRRpy`).

### B. Prebuilt folder

The repository also tracks the same build unzipped at
`_plugin_build/MRRpy_plugin/`. Copy that folder into your QGIS plugins
directory, then enable **MRRpy_plugin** under *Plugins → Manage and Install
Plugins → Installed*:
- **Windows:** `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
- **Linux:** `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- **macOS:** `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

### C. Development symlink (Linux/macOS)

```bash
./install_plugin.sh            # symlinks MRRpy_plugin/ → the QGIS plugins dir
./install_plugin.sh --remove   # uninstall
```
> In symlink mode the plugin finds the core package in the repository root
> automatically (`bridge.ensure_core()`); pip-installing `MRRpy` into the
> QGIS interpreter also works for any install mode (a pip-installed copy takes
> precedence over the vendored one).

---

## Google Earth Engine (for IMERG / SERVES / LULC / LCZ / GCN250)

The satellite-backed options (IMERG rainfall, SERVES deficit, gridded Ksat,
texture suction, LULC/LCZ Manning's & impervious, GCN250 curve numbers) need
Earth Engine access.

- Set the **GEE project** on the *Precipitation* or *Runoff* tab (the two
  fields are kept in sync), or the `GEE_PROJECT` environment variable.
- Authenticate once in the QGIS Python console:
  ```python
  import ee
  ee.Authenticate()
  ```
- Or place a service-account `key.json` next to `serves_gee.py` inside the
  installed plugin's `_vendor/MRRpy/gee/` folder. **`key.json` is never
  committed to git** — you must supply your own.
- These options are entirely optional: scalar/manual/gauge settings run fully
  offline.

---

## Dependencies

All dependencies must be importable from **QGIS's bundled Python** (NOT your
system Python — a normal `pip install` in a terminal targets the wrong
interpreter and QGIS will still fail with `ModuleNotFoundError`).

### Easiest: the built-in Dependencies manager

Open the plugin dialog and click **Dependencies**. It shows which packages
are present in QGIS's Python and installs the missing ones into that same
interpreter with one click (with a live log and a copyable manual command if an
install needs elevated permissions). The dialog also pops up automatically if
you press **Run** — or open the plugin — while something required is missing.

| Package | Purpose | Required? |
|---|---|---|
| `numpy`, `pandas` | Array math / CSV I/O | required (usually pre-installed) |
| `scipy` | Spatial weights (KDTree) | required |
| `rasterio` | Raster read/write | required |
| `pyflwdir`, `pysheds`, `numba` | DEM watershed delineation | required |
| `geopandas`, `shapely`, `pyproj` | Watershed / stream vectors, CRS transforms | required |
| `matplotlib` | Plots (imported by the core package) | required |
| `pyyaml` | Load / save `.yaml` config files | optional |
| `earthengine-api` | GEE / IMERG / SERVES / GCN250 | optional (satellite features) |
| `cupy` | GPU acceleration | optional (`pip install cupy-cuda12x`) |

### Manual fallback (Windows)

If a one-click install hits a permission error, open **Start → OSGeo4W →
OSGeo4W Shell** and run the command the Dependencies dialog shows, e.g.:
```
python -m pip install rasterio pyflwdir pysheds geopandas scipy pandas matplotlib
```
then restart QGIS. On Linux/macOS run the same command against the QGIS Python.

**Check inside the QGIS Python console:**
```python
import rasterio, pyflwdir, pysheds, geopandas, scipy, numpy, pandas, matplotlib
import ee      # optional (satellite features)
import cupy    # optional (GPU)
```

---

## Typical workflow

Open **Plugins → MRRpy_plugin** (or the toolbar button). The defaults run fully
offline — no Earth Engine account is needed until you pick an option that
downloads satellite data.

1. **DEM & Watershed** — choose the DEM, target CRS and output directory, then
   **Analyze terrain**: the stream network is drawn and map-pick mode turns on.
   Click your outlet on a stream (or type lat/lon) and press
   **Delineate watershed**. The watershed is added to the map and
   *DEM Pre-processing* is unticked, because Run can reuse it; changing the DEM,
   CRS, engine, outlet or output directory ticks it again.
   *(Shortcut: skip the guided steps, type the outlet, leave DEM Pre-processing
   ticked and press Run.)*
2. **Precipitation** — uniform, gauge (Thiessen / IDW) or IMERG. Earth Engine
   fields (project, event start, UTC offset) appear only when needed.
3. **Runoff** — none, coefficient, raster series, SCS-CN or physical mechanisms
   (saturation-excess VSA-OPM, Green-Ampt infiltration-excess, impervious).
4. **Routing** — Manning's n, routing scheme, channel geometry, time stepping.
   Expert settings (semi-implicit solver, adaptive-Δt limits, numerical floors)
   are in collapsed groups and keep sensible defaults.
5. **Run** → the **Results** tab shows the outlet hydrograph, loads the output
   layers and exports CSV / PNG. **Cancel** stops after the current stage.

Every setting maps 1:1 to an attribute on `MRRpy.config.Config` (re-exported by
`bridge/config_bridge.py`). The routing-scheme list is read from the core, so a
scheme added to MRRpy appears in the dialog and the Processing algorithm
without a plugin change.

**Load Config** fills every tab from a `.yaml` / `.json` / legacy `.py` file —
the same files `MRRpy run -c <file>` uses. Settings that have no widget
(virtual gauges `ROUTING_GAUGES`, inflow hydrographs `ROUTING_INFLOW_BC`,
`SAVE_FIELDS`, DEM auto-download bounds, …) are kept and used for the run.
**Save Config** writes YAML / JSON (CLI-ready) or a `config.py` module.

### Choosing a routing scheme

| Scheme | Use it for | Time step |
|---|---|---|
| `kinematic` | Fast, steep terrain, no backwater | adaptive CFL (C ≤ 1) |
| `diffusive` | General overland + channel flow with ponding/backwater | small static Δt or adaptive |
| `muskingum` | Grid-independent channel attenuation | adaptive CFL |
| `dynamic` | Surges, dam-break/GLOF-type waves, inertia matters | adaptive (gravity-wave CFL) |
| `diffusive_implicit` | Large or flat domains where explicit Δt collapses | large Δt — Courant target ~1–3 (> 1 allowed); CPU only |

---

## GPU / CPU Notes

- The plugin detects CuPy at load time (`gpu_utils.cupy_available()`); the GPU
  radio button is disabled with an install hint when CuPy is absent.
- Runs execute in a `QThread` — the QGIS GUI stays responsive.
- GPU memory pools are freed after each run; a VRAM check warns if < 0.5 GB free.

---

## Running Tests

```bash
cd /path/to/MRRpy
pytest MRRpy_plugin/tests/test_config_bridge.py -v   # no QGIS required
pytest MRRpy_plugin/tests/test_runner.py -v          # needs output/ rasters
# Headless UI tests — run with the Python that QGIS uses (skipped elsewhere):
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m pytest MRRpy_plugin/tests/test_ui.py -v
```

---

## Reference

Pradhan, N.R. and Ogden, F.L. (2010). *Development of a one-parameter variable
source area runoff model for ungauged basins.* Advances in Water Resources,
33(5), pp. 572–584.
