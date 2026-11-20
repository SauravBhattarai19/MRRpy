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


def is_auto(crs):
    """True when TARGET_CRS_EPSG asks MRRpy to choose ("auto", empty or None)."""
    return crs is None or str(crs).strip().lower() in ("", "auto")


def crs_mismatch(crs, point, margin_deg=6.0):
    """
    A plain message when (lat, lon) *point* lies far outside the area projection
    *crs* is made for, else None.  "Far" is more than *margin_deg* of longitude
    beyond the projection's bounds — one UTM zone of slack, so a basin that
    straddles two zones is not flagged.  Unknown projections are not judged.
    """
    if is_auto(crs) or point is None:
        return None
    try:
        from pyproj import CRS
        lat, lon = (float(v) for v in point)
        area = CRS.from_user_input(str(crs)).area_of_use
    except Exception:            # noqa: BLE001 — not a CRS pyproj knows; checked elsewhere
        return None
    if area is None:
        return None
    west, east = area.west, area.east
    if west <= east:
        inside = west - margin_deg <= lon <= east + margin_deg
    else:                        # area crosses the 180° meridian
        inside = lon >= west - margin_deg or lon <= east + margin_deg
    if inside:
        return None
    suggestion = utm_epsg(lat, lon)
    return (f"TARGET_CRS_EPSG {crs} ({describe_utm(crs)}) is made for longitudes "
            f"{west:g}° to {east:g}°, but your area is at longitude {lon:.2f}°. "
            f"Use \"auto\"" + (f" or {suggestion}" if suggestion else "") + ".")


def resolve_target_crs(cfg, log=print):
    """
    Turn ``TARGET_CRS_EPSG = "auto"`` into an EPSG code — the UTM zone of the
    outlet, or of the DEM's centre when the whole DEM is modelled — and store
    it on *cfg*.  Does nothing when a projection is already set.  Returns the
    projection.
    """
    crs = getattr(cfg, "TARGET_CRS_EPSG", None)
    if not is_auto(crs):
        return crs
    from ..config_schema import crs_reference_point
    values = {k: getattr(cfg, k, None) for k in
              ("MODEL_AREA", "OUTPUT_POINT", "DEM_PATH", "DEM_BOUNDS_WGS84")}
    point = crs_reference_point(values)
    epsg = utm_epsg(*point) if point is not None else None
    if epsg is None:
        raise ValueError(
            "TARGET_CRS_EPSG is \"auto\", but there is no place to choose a map "
            "projection from: give OUTPUT_POINT (lat, lon), or a DEM, or set "
            "TARGET_CRS_EPSG to an EPSG code in metres such as your UTM zone.")
    where = ("the DEM's centre" if str(values.get("MODEL_AREA")) == "whole_dem"
             else "the outlet")
    log(f"  Map projection |  {epsg} ({describe_utm(epsg)}), chosen from {where} "
        f"(TARGET_CRS_EPSG = auto)")
    cfg.TARGET_CRS_EPSG = epsg
    return epsg
