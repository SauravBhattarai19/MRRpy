# -*- coding: utf-8 -*-
"""
hydroatlas.py — basin attributes at a point from HydroATLAS (Linke et al. 2019)
in Earth Engine: one small request, no download.

Used by the automatic bankfull-discharge estimate (core/routing/qbf.py).
"""

import json
import os

ASSET = "WWF/HydroATLAS/v1/Basins/level12"
FIELDS = ("UP_AREA", "dis_m3_pmx", "dis_m3_pyr", "pre_mm_uyr")


def basin_attributes(lat, lon, project=None, cache_path=None):
    """
    Attributes of the level-12 BasinATLAS sub-basin (~130 km²) that contains
    (lat, lon):

      UP_AREA     upstream area at the sub-basin pour point [km²]
      dis_m3_pmx  natural flow of the wettest month at the pour point [m³/s]
      dis_m3_pyr  natural mean annual flow at the pour point [m³/s]
      pre_mm_uyr  mean annual precipitation over the upstream area [mm]

    Returns a dict, or ``None`` when Earth Engine is unavailable or the point
    falls outside every basin (open sea, some coastal points).  Never opens an
    interactive sign-in.  ``cache_path`` (JSON) is reused for the same point.
    """
    key = f"{float(lat):.5f},{float(lon):.5f}"
    if cache_path and os.path.isfile(cache_path):
        try:
            with open(cache_path) as fh:
                cached = json.load(fh)
            if cached.get("point") == key:
                return cached.get("attrs")
        except (OSError, ValueError):
            pass
    try:
        import ee
        from .auth import authenticate
        if not authenticate(project, interactive=False):
            return None
        pt = ee.Geometry.Point(float(lon), float(lat))
        fc = ee.FeatureCollection(ASSET).filterBounds(pt)
        info = ee.Algorithms.If(fc.size().gt(0),
                                ee.Feature(fc.first()).toDictionary(list(FIELDS)),
                                None).getInfo()
    except Exception as exc:                          # no ee, no network, quota …
        print(f"  [WARN] HydroATLAS lookup failed ({str(exc)[:120]})")
        return None
    if not info or not all(info.get(k) is not None for k in ("UP_AREA", "dis_m3_pmx")):
        return None
    attrs = {k: float(info[k]) for k in FIELDS if info.get(k) is not None}
    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
            with open(cache_path, "w") as fh:
                json.dump({"point": key, "asset": ASSET, "attrs": attrs}, fh, indent=1)
        except OSError:
            pass
    return attrs
