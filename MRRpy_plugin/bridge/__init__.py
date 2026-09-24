# -*- coding: utf-8 -*-
"""
bridge package — glue between the QGIS plugin (UI/Processing) and the
pip-installable ``MRRpy`` core package.

The core science lives entirely in ``MRRpy`` (no QGIS imports there);
this package holds the QGIS-side wrappers (QThread worker, dependency
installer) plus :func:`ensure_core`, which makes the core importable in
every deployment mode.
"""

import os
import sys

# Plugin root is 1 level up from bridge/
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_core():
    """
    Make the ``MRRpy`` core package importable inside QGIS.

    Resolution order:
      1. Already importable (pip-installed into the QGIS interpreter).
      2. Vendored copy shipped inside the plugin zip:  <plugin>/_vendor/MRRpy
      3. Development checkout: the plugin folder is a symlink into the
         repository (install_plugin.sh), so the package sits next to it
         in the repo root.
    """
    def _try_import():
        """True if MRRpy imports; False if MRRpy itself isn't on sys.path.

        Any *other* ImportError means the core was found but one of its
        dependencies is missing — re-raise that so the user sees e.g.
        "No module named 'geopandas'" rather than "MRRpy not found".
        """
        try:
            import MRRpy  # noqa: F401
            return True
        except ImportError as exc:
            if (getattr(exc, "name", None) or "").split(".")[0] == "MRRpy":
                return False
            raise ImportError(
                f"The MRRpy core package was found but a dependency is missing: "
                f"{exc}.  Open the plugin's Dependencies manager to install it."
            ) from exc

    if _try_import():
        return

    candidates = [
        os.path.join(_PLUGIN_DIR, "_vendor"),
        os.path.dirname(os.path.realpath(_PLUGIN_DIR)),   # repo root (dev symlink)
    ]
    for cand in candidates:
        if os.path.isdir(os.path.join(cand, "MRRpy")):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            if _try_import():
                return

    raise ImportError(
        "The 'MRRpy' core package could not be found. Install it into the "
        "QGIS Python interpreter (pip install MRRpy) or rebuild the plugin "
        "zip so it ships a vendored copy (_vendor/MRRpy)."
    )


def core_choices(key, fallback):
    """
    Ordered valid values of a fixed-choice Config option (e.g. ROUTING_SCHEME),
    read from the installed core so new options appear in the UI without a
    plugin change.  Falls back to *fallback* if the core can't be imported.
    """
    try:
        ensure_core()
        from MRRpy.config import _ENUM_CHOICES
        return list(_ENUM_CHOICES[key])
    except Exception:  # noqa: BLE001
        return list(fallback)
