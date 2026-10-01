# -*- coding: utf-8 -*-
"""
notebook_map.py
================
Jupyter-only interactive bounding-box picker, for drawing ``DEM_BOUNDS_WGS84``
on a map instead of typing coordinates by hand. Not usable from a plain
``.py`` script or the CLI — it needs a live ipywidgets/ipyleaflet frontend.

Drawing a box needs **no Earth Engine sign-in**: the map is plain ipyleaflet
and the box is just four numbers.  (Earth Engine is needed later, to download
the DEM — see ``MRRpy.connect_earth_engine``.)

Requires the ``notebook`` extra: ``pip install MRRpy[notebook]``
(ipyleaflet, ipywidgets).  The step-by-step ``MRRpy.ConfigForm`` has the same
picker built in.

Usage (in a Jupyter cell)::

    from MRRpy.utils.notebook_map import pick_bounds_map, get_drawn_bounds

    m = pick_bounds_map(center=(27.7, 85.3), zoom=9)
    m   # display the map, draw a rectangle with the toolbar

    bounds = get_drawn_bounds(m)   # after drawing
    # -> (min_lon, min_lat, max_lon, max_lat), feed straight into
    #    Config(DEM_BOUNDS_WGS84=bounds, ...)
"""


def _require_ipyleaflet():
    try:
        import ipyleaflet
        return ipyleaflet
    except ImportError as exc:
        raise ImportError(
            "Interactive map picking needs the notebook extra: "
            "pip install MRRpy[notebook]"
        ) from exc


def pick_bounds_map(center=(27.7, 85.3), zoom=9, **kwargs):
    """
    Create an interactive map with a rectangle draw tool, for picking a
    ``DEM_BOUNDS_WGS84`` box in a Jupyter notebook.

    Parameters
    ----------
    center : (lat, lon), initial map center.
    zoom : int, initial zoom level.
    **kwargs
        Passed through to ``ipyleaflet.Map()`` (``ee_initialize``, accepted by
        older MRRpy versions that used geemap, is ignored).

    Returns
    -------
    ipyleaflet.Map
        Display it as a cell's last expression (or ``display(m)``), draw a
        rectangle using the toolbar, then call ``get_drawn_bounds(m)``.

    Raises
    ------
    ImportError
        If ipyleaflet/ipywidgets aren't installed (``pip install MRRpy[notebook]``).
    """
    L = _require_ipyleaflet()
    kwargs.pop("ee_initialize", None)
    kwargs.setdefault("scroll_wheel_zoom", True)
    m = L.Map(center=center, zoom=zoom, **kwargs)
    draw = L.DrawControl(polyline={}, polygon={}, circlemarker={}, marker={},
                         rectangle={"shapeOptions": {"weight": 2}})
    m.draw_features = []          # the drawn rectangles, newest last (GeoJSON)

    def _remember(target, action, geo_json):
        if action == "created":
            m.draw_features.append(geo_json)
        elif action == "deleted" and m.draw_features:
            m.draw_features.pop()

    draw.on_draw(_remember)
    m.add(draw)
    m.draw_control = draw
    return m


def get_drawn_bounds(map_obj):
    """
    Extract ``(min_lon, min_lat, max_lon, max_lat)`` from the last rectangle
    drawn on *map_obj* (as created by :func:`pick_bounds_map`).

    Parameters
    ----------
    map_obj : ipyleaflet.Map
        A map returned by :func:`pick_bounds_map`, after the user has drawn
        a rectangle using its draw toolbar.

    Returns
    -------
    (min_lon, min_lat, max_lon, max_lat) : tuple of float
        Directly usable as ``Config(DEM_BOUNDS_WGS84=...)``.

    Raises
    ------
    RuntimeError
        No shape has been drawn yet on *map_obj*.
    """
    features = getattr(map_obj, "draw_features", None) or []
    if not features:
        raise RuntimeError(
            "No shape has been drawn yet — draw a rectangle on the map's "
            "toolbar first, then call get_drawn_bounds(map_obj)."
        )
    last = features[-1]
    feature = last.__geo_interface__ if hasattr(last, "__geo_interface__") else last
    return _bounds_from_geojson_feature(feature)


def _bounds_from_geojson_feature(feature):
    """
    Pure function: a GeoJSON Feature/geometry dict (Polygon coordinates, as
    produced by ipyleaflet's DrawControl) -> (min_lon, min_lat, max_lon,
    max_lat). Factored out so it's testable without constructing any real
    map/widget.
    """
    geometry = feature.get("geometry", feature)
    if geometry.get("type") != "Polygon":
        raise RuntimeError(
            f"Expected a drawn rectangle (Polygon), got '{geometry.get('type')}' "
            "— use the rectangle tool on the map's draw toolbar."
        )
    coords = geometry["coordinates"][0]
    lons = [pt[0] for pt in coords]
    lats = [pt[1] for pt in coords]
    return (min(lons), min(lats), max(lons), max(lats))
