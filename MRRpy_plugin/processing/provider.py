# -*- coding: utf-8 -*-
"""
provider.py
===========
ProcessingProvider — registers all MRRpy_plugin algorithms with the
QGIS Processing Framework.

Registered algorithms appear under:
  Processing Toolbox → MRRpy_plugin
    ├─ 1. DEM Pre-processing
    └─ 2. Routing (kinematic / diffusive / dynamic / implicit)
    (the standalone VSA-OPM stage runs from the main dialog)

Adding new algorithms later
---------------------------
1. Create a new alg_*.py in this package.
2. Import the class here and add an instance to _algorithms().
"""

import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .alg_process_dem import ProcessDemAlgorithm
from .alg_router import RoutingAlgorithm

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ProcessingProvider(QgsProcessingProvider):
    """QGIS Processing provider of MRRpy_plugin."""

    def id(self):  # noqa: A003
        return "mrrpy_plugin"

    def name(self):
        return "MRRpy_plugin"

    def longName(self):  # noqa: N802
        return "MRRpy_plugin — rainfall–runoff and flood routing"

    def icon(self):
        icon_path = os.path.join(_PLUGIN_DIR, "resources", "icon.png")
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return super().icon()

    def loadAlgorithms(self):  # noqa: N802
        """Register all algorithms.  Called once by QGIS at provider load."""
        for alg in self._algorithms():
            self.addAlgorithm(alg)

    @staticmethod
    def _algorithms():
        return [
            ProcessDemAlgorithm(),
            RoutingAlgorithm(),
        ]
