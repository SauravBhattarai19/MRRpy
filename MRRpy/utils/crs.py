# -*- coding: utf-8 -*-
"""
crs.py
======
Small coordinate-reference-system helpers for choosing ``TARGET_CRS_EPSG``.

Most users don't know which projected CRS to use; the UTM zone that contains
the basin outlet is a safe, metric default anywhere between 80°S and 84°N.
"""


def utm_epsg(lat, lon):
    """
    EPSG code string of the WGS 84 / UTM zone containing (*lat*, *lon*).

    Returns e.g. ``"EPSG:32645"`` (zone 45 north) or ``"EPSG:32719"``
    (zone 19 south), or ``None`` outside UTM's latitude range (polar
    regions need a polar stereographic CRS instead).  The Norway/Svalbard
    zone exceptions are ignored — the regular zone is still a valid metric
    projection there, just not the official one.
    """
    lat = float(lat)
    lon = float(lon)
    if not (-80.0 <= lat <= 84.0) or not (-180.0 <= lon <= 180.0):
        return None
    zone = min(int((lon + 180.0) // 6.0) + 1, 60)
    base = 32600 if lat >= 0 else 32700
    return f"EPSG:{base + zone}"


def describe_utm(epsg):
    """'EPSG:32645' → 'UTM zone 45N'; any other code is returned as is."""
    try:
        code = int(str(epsg).upper().replace("EPSG:", ""))
    except ValueError:
        return str(epsg)
    if 32601 <= code <= 32660:
        return f"UTM zone {code - 32600}N"
    if 32701 <= code <= 32760:
        return f"UTM zone {code - 32700}S"
    return f"EPSG:{code}"
