# -*- coding: utf-8 -*-
"""
__init__.py
===========
QGIS plugin entry point.

QGIS calls classFactory(iface) when the plugin is loaded.
"""


def classFactory(iface):  # noqa: N802
    """
    Required QGIS plugin entry point.

    Parameters
    ----------
    iface : QgisInterface
        QGIS application interface (access to map canvas, layers, menus …)

    Returns
    -------
    MRRpyPlugin instance
    """
    from .plugin import MRRpyPlugin
    return MRRpyPlugin(iface)
