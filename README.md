# MRRpy

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Docs](https://img.shields.io/badge/docs-mrrpy.readthedocs.io-teal.svg)](https://mrrpy.readthedocs.io)

**Rainfall–runoff and flood routing for any basin on Earth, from a DEM and a storm.**

MRRpy, the **M**ulti-**M**echanism **R**unoff and **R**outing model, is a
distributed, physics-based flood model in Python. It traces the drainage network
of a DEM, works out how much rain runs off (SCS Curve Number, or Green–Ampt
infiltration, saturated source areas (VSA-OPM) and impervious cities in any
combination), and routes the water through every grid cell and sub-grid river
channel with a kinematic, Muskingum–Cunge or semi-implicit diffusion wave. You
get the outlet hydrograph, flood maps and a water-balance check. It runs offline
with your own data, or fetches DEMs, NASA IMERG rain, soil and land cover from
Google Earth Engine. Set it up in a Jupyter form, a terminal wizard, Python or
QGIS; it runs on a CPU or an NVIDIA GPU.

## 📖 Documentation

**Full docs, guides and API reference → [mrrpy.readthedocs.io](https://mrrpy.readthedocs.io)**

Learn the science interactively → [the MRRpy course](https://sauravbhattarai19.github.io/MRRpy/)

## Installation

```bash
pip install MRRpy            # core (CPU)
pip install "MRRpy[gpu]"     # + CuPy/CUDA acceleration
pip install "MRRpy[gee]"     # + Google Earth Engine forcing
```

## Quick example

```python
from MRRpy import Config, run_pipeline

cfg = Config(DEM_PATH="dem.tif", OUTPUT_DIR="results/",
             OUTPUT_POINT=(27.632, 85.293),   # (lat, lon) of the outlet
             TARGET_CRS_EPSG="EPSG:32645")    # a projection in metres (UTM zone)
run_pipeline(cfg)                             # → results/hydrograph.csv
```

Or from the command line:

```bash
MRRpy wizard                    # answer a few questions → run.yaml
MRRpy run -c run.yaml           # process_dem + routing
```

Prefer a form? In Jupyter, `MRRpy.ConfigForm()` is a step-by-step form like the QGIS
plugin (`pip install "MRRpy[notebook]"`).
Prefer a file? `MRRpy init-config -o run.yaml` writes a commented template, and
`MRRpy explain <SETTING>` explains any setting.

![Water depth and river discharge spreading over the whole Kathmandu-valley DEM](https://raw.githubusercontent.com/SauravBhattarai19/MRRpy/main/docsite/assets/img/whole_dem_flow.gif)

*One storm over a whole DEM, animated with `MRRpy.animate_fields(out, ["depth", "discharge"])`:
water depth, river flow drawn wider where it is larger, and the hydrograph.*

## What it offers

- **DEM → watershed** — reproject, pit-fill, D8 flow direction/accumulation and
  delineation (`pysheds` or `pyflwdir`) — or route the **whole DEM** with no
  outlet (`MODEL_AREA="whole_dem"`).
- **Flood maps** — save depth/discharge maps over time, then animate the flow
  spreading (`animate_fields`) or export peak-depth GeoTIFFs (`export_peak_maps`).
- **Runoff generation** — `none · coefficient · raster · scs_cn · physical`; for
  `physical`, VSA saturation-excess + Green-Ampt + impervious as composable
  mechanisms.
- **Flood routing** — kinematic wave, Muskingum–Cunge, or a semi-implicit
  diffusion wave (backwater, flat valleys, large stable steps), with sub-grid
  river channels sized from the 2-year flood and an always-on water-balance check.
- **Satellite forcing** — optional DEM download, IMERG rainfall, GCN250 curve
  numbers, SERVES soil deficit, SoilGrids, HiHydroSoil, LULC/LCZ via Google Earth
  Engine (every option also works offline with your own files).
- **CPU / GPU** — one code path (NumPy or CuPy), automatic CPU fallback.
- **Interfaces for every taste** — Python API, a `MRRpy` CLI with a
  question-and-answer `wizard`, a Jupyter form, and a QGIS plugin, all driven
  by one `Config` object.

## Links

- **Documentation:** <https://mrrpy.readthedocs.io>
- **Interactive course:** <https://sauravbhattarai19.github.io/MRRpy/>
- **Source & issues:** <https://github.com/SauravBhattarai19/MRRpy>

## License

[MIT](LICENSE) © Saurav Bhattarai.
