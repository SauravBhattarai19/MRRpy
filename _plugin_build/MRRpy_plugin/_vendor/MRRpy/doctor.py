# -*- coding: utf-8 -*-
"""
doctor.py
=========
``MRRpy doctor`` — check this computer before a run: the Python version, the
packages MRRpy needs, the optional ones (GPU, Earth Engine, Jupyter form, USGS),
whether the data services can be reached, and whether results can be written.

Each line says OK, MISSING or PROBLEM in words, with what to do about it.
Nothing is installed, signed in or changed.
"""

import importlib
import os
import platform
import sys

#: (import name, pip name) of the packages a run cannot do without.
REQUIRED = [
    ("numpy", "numpy"), ("pandas", "pandas"), ("scipy", "scipy"),
    ("matplotlib", "matplotlib"), ("rasterio", "rasterio"), ("geopandas", "geopandas"),
    ("shapely", "shapely"), ("pyproj", "pyproj"), ("fiona", "fiona"),
    ("pyflwdir", "pyflwdir"), ("pysheds", "pysheds"), ("numba", "numba"),
    ("affine", "affine"), ("yaml", "pyyaml"),
]
#: Services a run may read from: (what for, address).
SERVICES = [
    ("Open-Meteo (weather-model rain, forecasts)",
     "https://api.open-meteo.com/v1/forecast?latitude=0&longitude=0&hourly=precipitation&forecast_days=1"),
    ("Copernicus DEM open data (DEM download, no account)",
     "https://copernicus-dem-90m.s3.amazonaws.com/readme.html"),
    ("Google Earth Engine", "https://earthengine.googleapis.com/$discovery/rest?version=v1"),
]


def _version(module):
    return str(getattr(module, "__version__", "") or "")


def _reach(url, timeout=8):
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MRRpy"})
        with urllib.request.urlopen(req, timeout=timeout):
            return True, ""
    except urllib.error.HTTPError as exc:
        return exc.code < 500, f"HTTP {exc.code}"          # it answered: reachable
    except Exception as exc:                               # noqa: BLE001
        return False, str(getattr(exc, "reason", exc))


def check(online=True, folder="."):
    """
    Run every check → list of (status, what, detail), status one of
    'OK', 'MISSING' (an optional part is not installed), 'PROBLEM'.
    """
    out = []

    def add(status, what, detail=""):
        out.append((status, what, detail))

    from . import __version__
    add("OK", f"MRRpy {__version__}", os.path.dirname(os.path.abspath(__file__)))
    py = sys.version_info
    if py < (3, 9):
        add("PROBLEM", f"Python {platform.python_version()}", "MRRpy needs Python 3.9 or newer.")
    else:
        add("OK", f"Python {platform.python_version()}", f"{platform.system()} {platform.machine()}")

    # ── What every run needs ─────────────────────────────────────────────────
    for name, pip_name in REQUIRED:
        try:
            mod = importlib.import_module(name)
            add("OK", f"{pip_name} {_version(mod)}".strip())
        except Exception as exc:                           # noqa: BLE001
            add("PROBLEM", pip_name,
                f"cannot be imported ({type(exc).__name__}: {exc}). Install it with: "
                f"pip install {pip_name}")
    try:
        import rasterio
        add("OK", f"GDAL {rasterio.__gdal_version__} (inside rasterio)")
    except Exception:                                      # noqa: BLE001
        pass
    try:
        import numba
        add("OK", f"Numba can use {numba.config.NUMBA_NUM_THREADS} threads on "
                  f"{os.cpu_count()} cores",
            "set NUMBA_NUM_THREADS to use fewer on a shared computer")
    except Exception:                                      # noqa: BLE001
        pass

    # ── Optional parts ───────────────────────────────────────────────────────
    try:
        from .utils import gpu_utils
        if gpu_utils.cupy_available():
            import cupy
            add("OK", f"GPU: CuPy {cupy.__version__} with a CUDA device", "BACKEND: gpu will work")
        else:
            add("MISSING", "GPU (optional)",
                "no CuPy with a usable NVIDIA GPU; runs use the CPU. For a GPU: "
                "pip install 'MRRpy[gpu]'")
    except Exception as exc:                               # noqa: BLE001
        add("MISSING", "GPU (optional)", f"not usable ({exc}); runs use the CPU.")
    try:
        import ee  # noqa: F401
        from .gee import auth
        ok, _message = auth.status() if online else (False, "")
        if ok:
            add("OK", "Google Earth Engine: signed in and working")
        elif not online:
            add("OK", "Google Earth Engine: installed (sign-in not checked, --offline)")
        else:
            add("MISSING", "Google Earth Engine: not signed in (optional)",
                "needed only for Earth Engine options (IMERG rain, soil and land-cover "
                "maps). Sign in once with: MRRpy earth-engine-login --project YOUR_PROJECT")
    except ImportError:
        add("MISSING", "Google Earth Engine (optional)",
            "earthengine-api is not installed. For it: pip install 'MRRpy[gee]'")
    except Exception as exc:                               # noqa: BLE001
        add("MISSING", "Google Earth Engine (optional)", f"could not be checked ({exc})")
    for name, extra, what in (("ipywidgets", "notebook", "the Jupyter form"),
                              ("ipyleaflet", "notebook", "the map in the Jupyter form"),
                              ("dataretrieval", "usgs", "USGS gauge records")):
        try:
            mod = importlib.import_module(name)
            add("OK", f"{name} {_version(mod)} ({what})")
        except Exception:                                  # noqa: BLE001
            add("MISSING", f"{name} (optional, {what})", f"pip install 'MRRpy[{extra}]'")

    # ── The internet ─────────────────────────────────────────────────────────
    if online:
        for what, url in SERVICES:
            ok, why = _reach(url)
            if ok:
                add("OK", f"Reached: {what}")
            else:
                add("PROBLEM", f"Cannot reach: {what}",
                    f"{why}. Runs with your own files still work offline.")
    else:
        add("OK", "Internet checks skipped (--offline)")

    # ── A place to write ─────────────────────────────────────────────────────
    folder = os.path.abspath(folder)
    try:
        probe = os.path.join(folder, ".mrrpy_write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        add("OK", f"Can write results in {folder}")
    except OSError as exc:
        add("PROBLEM", f"Cannot write in {folder}",
            f"{exc}. Set OUTPUT_DIR to a folder you can write to.")
    return out


def report(online=True, folder=".", out=print):
    """Print the checks in plain lines; returns True when nothing a run needs is wrong."""
    results = check(online=online, folder=folder)
    out("MRRpy doctor — checking this computer")
    out("")
    for status, what, detail in results:
        out(f"  {status + ':':9s}{what}")
        if detail and status != "OK":
            out(f"           {detail}")
    problems = [r for r in results if r[0] == "PROBLEM"]
    missing = [r for r in results if r[0] == "MISSING"]
    out("")
    if problems:
        out(f"{len(problems)} problem(s) to fix (lines marked PROBLEM above).")
    else:
        out("Everything a run needs is here."
            + (f" {len(missing)} optional part(s) are not installed (MISSING above); "
               "install them only if you want what they add." if missing else ""))
        out("Try it:  MRRpy demo")
    return not problems
