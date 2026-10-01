# Google Earth Engine

MRRpy runs fully **offline** with your own files and typed values. Google Earth
Engine is needed only for the options that **download global data** for you.

| Option | Dataset | Chapter |
|---|---|---|
| `DEM_PATH` empty + `DEM_BOUNDS_WGS84` | NASADEM, MERIT, ALOS, Copernicus, FABDEM, 3DEP, … | [1.1](terrain.md#11-elevation-data-dem) |
| `PRECIP_METHOD: imerg_thiessen` / `imerg_idw` | NASA GPM IMERG V07 rain | [3.4](precipitation.md#34-satellite-rain-nasa-imerg) |
| `RUNOFF_CN_SOURCE: gee` (the default for `scs_cn`) | GCN250 curve numbers | [4.5](runoff.md#45-scs-curve-number) |
| `IMPERVIOUS_SOURCE: lulc` / `lcz` | ESA WorldCover / WUDAPT LCZ | [4.6.1](runoff.md#461-impervious-areas) |
| `GA_KSAT_SOURCE: gee` | HiHydroSoil v2.0 conductivity | [4.6.2](runoff.md#462-infiltration-excess-greenampt) |
| `GA_SUCTION_SOURCE: texture` | SoilGrids sand and clay | [4.6.2](runoff.md#462-infiltration-excess-greenampt) |
| `VSA_SD_SOURCE: gee` | SERVES soil moisture, SoilGrids, HiHydroSoil, WorldCover | [4.6.5](runoff.md#465-soil-from-satellite-data) |
| `MANNINGS_N_SOURCE: lulc` / `lcz` | ESA WorldCover / WUDAPT LCZ | [5.4.1](roughness.md#541-roughness-of-the-ground) |
| `CHANNEL_QBF_M3S` empty (automatic) | HydroATLAS; without Earth Engine it falls back to drainage area | [5.5.3](channels.md#553-channel-size) |

Every download is saved in the results folder and reused by later runs into the
same folder.

## Setting it up (once per computer)

1. **Get access.** Register for Earth Engine at
   [earthengine.google.com](https://earthengine.google.com/). Non-commercial use
   is free.
2. **Get a Cloud project ID.** Earth Engine needs a Google Cloud project; you
   get one when you register, or create one at
   [code.earthengine.google.com/register](https://code.earthengine.google.com/register).
   Use its **ID** (such as `ee-yourname`), not its display name.
3. **Install the extra:** `pip install "MRRpy[gee]"`.
4. **Sign in**, once per computer:

    === "Terminal"

        ```bash
        MRRpy earth-engine-login --project ee-yourname
        ```

    === "Python / notebook"

        ```python
        import MRRpy
        MRRpy.connect_earth_engine("ee-yourname")
        ```

    If this computer has never signed in, it prints a link. Open it in any
    browser, sign in with your Google account and paste the code back. This works
    over SSH too. The sign-in is saved; afterwards the command only checks that
    the project works, and explains any problem in plain words. `--force` signs in
    again (for example with another account).

5. **Give the project to MRRpy**: set `GEE_PROJECT` in the configuration, or once
   for all runs with the environment variable:

    ```bash
    export GEE_PROJECT=ee-yourname
    ```

In the notebook form, a box for the project appears in any step whose choice
needs Earth Engine, with a **Connect to Earth Engine** button that checks it.
In QGIS, the *GEE project* field is on the Precipitation and Runoff tabs.

**Servers and automated runs** can use a service account instead: create one
with Earth Engine access, download its JSON key and set
`GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json` (or save the file as
`key.json` in the folder you run from). MRRpy looks for credentials in that
order: `GOOGLE_APPLICATION_CREDENTIALS`, a `key.json`, then the saved sign-in.

!!! note "Checked before the run"
    `MRRpy validate` and the form's *Check settings* report a missing project
    before anything runs, so an offline run never stops halfway on Earth Engine.

<!-- settings: GEE_PROJECT -->
