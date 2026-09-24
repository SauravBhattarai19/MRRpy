# -*- coding: utf-8 -*-
"""
plugin.py
=========
Main plugin class.  Registered with QGIS via classFactory in __init__.py.

Responsibilities
----------------
- Add toolbar button + menu item to open the main dialog.
- Register / deregister the Processing provider.
- Keep a reference to the main dialog so it can be shown/hidden.
"""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .processing.provider import ProcessingProvider


# Absolute path to THIS file's directory (= plugin root)
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


class MRRpyPlugin:
    """QGIS plugin class of MRRpy_plugin."""

    def __init__(self, iface):
        """
        Parameters
        ----------
        iface : QgisInterface
        """
        self.iface = iface
        self._action = None
        self._dialog = None
        self._provider = ProcessingProvider()

    # ── QGIS lifecycle ────────────────────────────────────────────────────────

    def initGui(self):  # noqa: N802
        """Called by QGIS when the plugin is loaded (after __init__)."""
        # ── Toolbar / menu action ────────────────────────────────────────────
        icon_path = os.path.join(PLUGIN_DIR, "resources", "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self._action = QAction(icon, "MRRpy_plugin", self.iface.mainWindow())
        self._action.setToolTip(
            "Open the MRRpy_plugin rainfall–runoff and flood-routing dialog"
        )
        self._action.triggered.connect(self._open_dialog)

        # Add to Plugins menu and toolbar
        self.iface.addToolBarIcon(self._action)
        self.iface.addPluginToMenu("&MRRpy_plugin", self._action)

        # ── Register Processing provider ──────────────────────────────────────
        QgsApplication.processingRegistry().addProvider(self._provider)

    def unload(self):
        """Called by QGIS when the plugin is unloaded."""
        # Remove menu / toolbar
        self.iface.removePluginMenu("&MRRpy_plugin", self._action)
        self.iface.removeToolBarIcon(self._action)

        # Close dialog if open
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None

        # Deregister Processing provider
        QgsApplication.processingRegistry().removeProvider(self._provider)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _open_dialog(self):
        """Show (or bring to front) the main modelling dialog."""
        if self._dialog is None and not self._ensure_dependencies():
            return

        # Lazy import so QGIS loads faster.  The main dialog imports the MRRpy
        # core, so it can only load once the core's dependencies are present.
        try:
            from .ui.main_dialog import MainDialog
        except ImportError as exc:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(
                self.iface.mainWindow(), "MRRpy_plugin — cannot start",
                f"The model could not be loaded:\n\n{exc}")
            return

        if self._dialog is None:
            self._dialog = MainDialog(self.iface, parent=self.iface.mainWindow())
            # When the dialog is closed, clear the reference so next open
            # creates a fresh instance (state is reset).
            self._dialog.finished.connect(self._on_dialog_closed)

        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def _ensure_dependencies(self) -> bool:
        """Offer the installer when required packages are missing.

        Runs before the main dialog is imported: that import needs the core
        package, which needs these packages, so without this check a fresh
        QGIS would fail to open the dialog that hosts the installer button.
        """
        from .bridge.dependencies import missing
        if not missing(include_optional=False):
            return True
        from .ui.dependency_dialog import DependencyDialog
        DependencyDialog(parent=self.iface.mainWindow()).exec_()
        return not missing(include_optional=False)

    def _on_dialog_closed(self):
        """Slot called when the dialog emits finished() (user closes it)."""
        self._dialog = None
