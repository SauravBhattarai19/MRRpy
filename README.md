# MRRpy

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Docs](https://img.shields.io/badge/docs-mrrpy.readthedocs.io-teal.svg)](https://mrrpy.readthedocs.io)

**A distributed, physics-based hydrological + hydrodynamic model.** MRRpy —
the **M**ulti-**M**echanism **R**unoff and **R**outing model — turns a
bare-earth DEM and a rain event into a routed flood hydrograph —
Variable Source Area runoff, Green-Ampt infiltration and impervious shedding,
feeding grid-based kinematic / diffusive-wave / Muskingum–Cunge channel routing,
with optional GPU acceleration and Google Earth Engine forcing.

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
             OUTPUT_POINT=(27.632, 85.293))   # (lat, lon) of the outlet
cfg.update_output_paths()
run_pipeline(cfg, stages=("process_dem", "routing"))   # → results/hydrograph.csv
```

Or from the command line:

```bash
MRRpy init-config -o run.yaml   # template config
MRRpy run -c run.yaml           # process_dem + routing
```

## What it offers

- **DEM → watershed** — reproject, pit-fill, D8 flow direction/accumulation and
  delineation (`pysheds` or `pyflwdir`).
- **Runoff generation** — `none · coefficient · raster · scs_cn · vsa_opm`; VSA
  saturation-excess + Green-Ampt + impervious as composable mechanisms.
- **Flood routing** — kinematic, diffusive-wave, or Muskingum–Cunge, with
  always-on mass-balance checking.
- **Satellite forcing** — optional IMERG rainfall, SERVES soil deficit,
  SoilGrids, LULC/LCZ via Google Earth Engine (degrades gracefully offline).
- **CPU / GPU** — one code path (NumPy or CuPy), automatic CPU fallback.
- **Three interfaces** — Python API, a `MRRpy` CLI, and a QGIS plugin, all
  driven by one `Config` object.

## Links

- **Documentation:** <https://mrrpy.readthedocs.io>
- **Interactive course:** <https://sauravbhattarai19.github.io/MRRpy/>
- **Source & issues:** <https://github.com/SauravBhattarai19/MRRpy>

## License

[MIT](LICENSE) © Saurav Bhattarai.
