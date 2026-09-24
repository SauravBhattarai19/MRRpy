# -*- coding: utf-8 -*-
"""
layer_utils.py
==============
Small helpers for adding MRRpy_plugin output rasters/vectors to the QGIS canvas.

Shared by the guided DEM workflow (main_dialog) and the Results tab so the
"add a layer to the project" logic lives in exactly one place.
"""

import os

from qgis.core import QgsRasterLayer, QgsVectorLayer, QgsProject


def _remove_by_name(name: str):
    """Drop any existing project layers with this display name (avoid dupes on re-run)."""
    proj = QgsProject.instance()
    for lyr in proj.mapLayersByName(name):
        proj.removeMapLayer(lyr.id())


def add_raster(path, name, replace=True):
    """Add a raster to the project and return the layer, or None if missing/invalid."""
    if not path or not os.path.exists(path):
        return None
    if replace:
        _remove_by_name(name)
    lyr = QgsRasterLayer(path, name)
    if not lyr.isValid():
        return None
    QgsProject.instance().addMapLayer(lyr)
    return lyr


def add_vector(path, name, replace=True):
    """Add an OGR vector to the project and return the layer, or None if missing/invalid."""
    if not path or not os.path.exists(path):
        return None
    if replace:
        _remove_by_name(name)
    lyr = QgsVectorLayer(path, name, "ogr")
    if not lyr.isValid():
        return None
    QgsProject.instance().addMapLayer(lyr)
    return lyr


def zoom_to_layer(iface, layer):
    """Zoom the canvas to a layer's extent, reprojecting the extent to the map CRS."""
    if layer is None:
        return
    canvas = iface.mapCanvas()
    try:
        from qgis.core import QgsCoordinateTransform
        src = layer.crs()
        dst = canvas.mapSettings().destinationCrs()
        ext = layer.extent()
        if src.isValid() and dst.isValid() and src != dst:
            xform = QgsCoordinateTransform(src, dst, QgsProject.instance())
            ext = xform.transformBoundingBox(ext)
        canvas.setExtent(ext)
        canvas.refresh()
    except Exception:  # noqa: BLE001 — zoom is best-effort, never fatal
        pass
