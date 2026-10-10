# -*- coding: utf-8 -*-
"""
tab_results.py
==============
Tab 5 — Results viewer.

Features
--------
- Embedded hydrograph plot (matplotlib embedded in Qt)
- "Load output layers into QGIS" button
- Export: PNG, CSV buttons
- Peak discharge & timing summary label
- Flood maps from the saved fields (SAVE_FIELDS): peak-depth/discharge
  GeoTIFFs loaded as layers, and an animation of the flow spreading
- Flood depth and extent maps (INUNDATION_MAP, HAND): the depth GeoTIFF and
  extent outlines loaded as layers, and the flood animation opened
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QSizePolicy, QFrame,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsApplication

# Matplotlib embedded in Qt (optional — graceful fallback if not available)
try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    _MPL_AVAILABLE = True
except ImportError:
    _MPL_AVAILABLE = False


class TabResults(QWidget):
    """Results viewer tab."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self._iface = iface
        self._result = {}      # populated by the runner after a successful run
        self._df = None        # hydrograph DataFrame
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Summary label ─────────────────────────────────────────────────────
        self.summary_label = QLabel("No simulation results yet.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setFrameShape(QFrame.StyledPanel)
        self.summary_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.summary_label.setMinimumHeight(48)
        root.addWidget(self.summary_label)

        # ── Hydrograph plot ───────────────────────────────────────────────────
        grp_plot = QGroupBox("Outlet Hydrograph")
        v_plot = QVBoxLayout(grp_plot)

        if _MPL_AVAILABLE:
            self._fig = Figure(figsize=(6, 2.8), tight_layout=True)
            self._ax = self._fig.add_subplot(111)
            self._canvas = FigureCanvas(self._fig)
            self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            v_plot.addWidget(self._canvas)
            self._draw_empty_plot()
        else:
            v_plot.addWidget(QLabel(
                "matplotlib not available in QGIS's Python environment.\n"
                "Install it to enable the embedded hydrograph viewer."
            ))

        root.addWidget(grp_plot)

        # ── Action buttons ────────────────────────────────────────────────────
        grp_actions = QGroupBox("Actions")
        h_actions = QHBoxLayout(grp_actions)

        self.load_layers_btn = QPushButton(QgsApplication.getThemeIcon("/mActionAddLayer.svg"), "Load Layers into QGIS")
        self.load_layers_btn.setToolTip(
            "Add watershed, DEM, flow accumulation, and hydrograph CSV\n"
            "to the QGIS project as layers."
        )
        self.load_layers_btn.setEnabled(False)
        self.load_layers_btn.clicked.connect(self._load_layers)

        self.export_csv_btn = QPushButton(QgsApplication.getThemeIcon("/mIconTableLayer.svg"), "Export Hydrograph CSV")
        self.export_csv_btn.setEnabled(False)
        self.export_csv_btn.clicked.connect(self._export_csv)

        self.export_png_btn = QPushButton(QgsApplication.getThemeIcon("/mActionSaveMapAsImage.svg"), "Export Plot PNG")
        self.export_png_btn.setEnabled(False)
        self.export_png_btn.clicked.connect(self._export_png)

        h_actions.addWidget(self.load_layers_btn)
        h_actions.addWidget(self.export_csv_btn)
        h_actions.addWidget(self.export_png_btn)
        h_actions.addStretch()

        root.addWidget(grp_actions)

        # ── Flood maps from the saved fields (needs "Save maps over time") ────
        grp_maps = QGroupBox("Flood maps")
        v_maps = QVBoxLayout(grp_maps)
        self.maps_hint = QLabel(
            "Turn on “save maps over time” before running to get peak-depth maps "
            "and an animation of the flow.")
        self.maps_hint.setWordWrap(True)
        v_maps.addWidget(self.maps_hint)
        h_maps = QHBoxLayout()
        self.peak_maps_btn = QPushButton(QgsApplication.getThemeIcon("/mActionAddRasterLayer.svg"),
                                         "Load Peak Maps")
        self.peak_maps_btn.setToolTip(
            "Write max_depth.tif, max_discharge.tif and the time each cell peaked,\n"
            "and add them to the QGIS project.")
        self.peak_maps_btn.setEnabled(False)
        self.peak_maps_btn.clicked.connect(self._load_peak_maps)
        self.animate_btn = QPushButton(QgsApplication.getThemeIcon("/mActionSaveMapAsImage.svg"),
                                       "Save Flow Animation…")
        self.animate_btn.setToolTip(
            "Save a GIF of the water depth and the discharge spreading over the\n"
            "map, side by side, with the hydrograph. Large areas can take a minute.")
        self.animate_btn.setEnabled(False)
        self.animate_btn.clicked.connect(self._save_animation)
        h_maps.addWidget(self.peak_maps_btn)
        h_maps.addWidget(self.animate_btn)
        h_maps.addStretch()
        v_maps.addLayout(h_maps)
        root.addWidget(grp_maps)

        # ── Flood depth and extent (needs "flood depth and extent maps") ──────
        grp_flood = QGroupBox("Flood depth and extent (HAND)")
        v_flood = QVBoxLayout(grp_flood)
        self.flood_hint = QLabel(
            "Turn on “flood depth and extent maps” on the Routing tab before running "
            "to see how far the rivers spread.")
        self.flood_hint.setWordWrap(True)
        v_flood.addWidget(self.flood_hint)
        h_flood = QHBoxLayout()
        self.flood_maps_btn = QPushButton(QgsApplication.getThemeIcon("/mActionAddRasterLayer.svg"),
                                          "Load Flood Maps")
        self.flood_maps_btn.setToolTip(
            "Add the deepest flood water (m) and the outline of the flooded area\n"
            "to the QGIS project.")
        self.flood_maps_btn.setEnabled(False)
        self.flood_maps_btn.clicked.connect(self._load_flood_maps)
        self.flood_gif_btn = QPushButton(QgsApplication.getThemeIcon("/mActionPlay.svg"),
                                         "Open Flood Animation")
        self.flood_gif_btn.setToolTip("Open flood_animation.gif in your image viewer.")
        self.flood_gif_btn.setEnabled(False)
        self.flood_gif_btn.clicked.connect(self._open_flood_animation)
        h_flood.addWidget(self.flood_maps_btn)
        h_flood.addWidget(self.flood_gif_btn)
        h_flood.addStretch()
        v_flood.addLayout(h_flood)
        root.addWidget(grp_flood)
        root.addStretch()

    # ── Plot helpers ──────────────────────────────────────────────────────────

    def _draw_empty_plot(self):
        if not _MPL_AVAILABLE:
            return
        self._ax.clear()
        self._ax.set_xlabel("Time (hours)")
        self._ax.set_ylabel("Q (m³/s)")
        self._ax.set_title("Outlet Hydrograph")
        self._ax.text(0.5, 0.5, "Run the model to see results",
                      ha="center", va="center", transform=self._ax.transAxes,
                      color="grey", fontsize=10)
        self._ax.grid(True, alpha=0.3)
        self._canvas.draw()

    def _draw_hydrograph(self, df):
        if not _MPL_AVAILABLE:
            return
        self._ax.clear()
        # Plain arrays: older matplotlib (e.g. 3.5 in Ubuntu 22.04's QGIS) fails
        # on pandas-2 Series ("Multi-dimensional indexing ... no longer supported").
        t_hr = df["time_hr"].to_numpy(dtype=float)
        q = df["Q_m3s"].to_numpy(dtype=float)
        self._ax.plot(t_hr, q, color="#1f6aa5", lw=1.8)
        self._ax.fill_between(t_hr, q, alpha=0.12, color="#1f6aa5")
        self._ax.set_xlabel("Time (hours)")
        self._ax.set_ylabel("Discharge (m³/s)")
        self._ax.set_title("Outlet Hydrograph")
        self._ax.grid(True, alpha=0.3, ls="--")

        i_peak = int(q.argmax())
        peak_q, peak_t = float(q[i_peak]), float(t_hr[i_peak])
        self._ax.annotate(
            f"Peak: {peak_q:.3f} m³/s\n@ {peak_t:.2f} h",
            xy=(peak_t, peak_q),
            xytext=(peak_t + max(peak_t * 0.05, 0.5), peak_q * 0.85),
            arrowprops=dict(arrowstyle="->", color="#1f6aa5"),
            fontsize=8, color="#1f6aa5",
        )
        self._canvas.draw()

    # ── Public API ────────────────────────────────────────────────────────────

    def update_results(self, result: dict):
        """
        Called by the main dialog when the worker emits finished().

        Parameters
        ----------
        result : dict
            Keys: hydrograph_csv, hydrograph_df, watershed_tif, clipped_dem, …
        """
        self._result = result
        self._df = result.get("hydrograph_df")

        # Summary text
        if self._df is not None:
            peak_q = self._df["Q_m3s"].max()
            peak_t = self._df.loc[self._df["Q_m3s"].idxmax(), "time_hr"]
            self.summary_label.setText(
                f"Simulation complete.\n"
                f"Peak discharge: {peak_q:.4f} m³/s  at  t = {peak_t:.2f} h\n"
                f"Hydrograph rows: {len(self._df):,}  |  "
                f"CSV: {result.get('hydrograph_csv', '—')}"
            )
            self._draw_hydrograph(self._df)
        else:
            self.summary_label.setText("Run complete (no hydrograph — the routing stage was not run).")

        self.load_layers_btn.setEnabled(True)
        self.export_csv_btn.setEnabled(self._df is not None)
        self.export_png_btn.setEnabled(_MPL_AVAILABLE and self._df is not None)
        has_maps = self._fields_dir() is not None
        self.peak_maps_btn.setEnabled(has_maps)
        self.animate_btn.setEnabled(_MPL_AVAILABLE and has_maps)
        self.maps_hint.setText(
            "Maps over time were saved — load the peak maps or save an animation."
            if has_maps else
            "Turn on “save maps over time” before running to get peak-depth maps "
            "and an animation of the flow.")
        import os
        has_flood = bool(result.get("flood_depth_max")) and os.path.isfile(
            result.get("flood_depth_max", ""))
        has_gif = bool(result.get("flood_animation")) and os.path.isfile(
            result.get("flood_animation", ""))
        self.flood_maps_btn.setEnabled(has_flood)
        self.flood_gif_btn.setEnabled(has_gif)
        if has_flood:
            summary = self._flood_summary()
            self.flood_hint.setText(summary or "Flood maps were made — load them.")
        else:
            self.flood_hint.setText(
                "Turn on “flood depth and extent maps” on the Routing tab before running "
                "to see how far the rivers spread.")

    def _flood_summary(self):
        """One plain sentence from inundation_summary.json, or ''."""
        import json
        try:
            with open(self._result["summary_json"]) as fh:
                s = json.load(fh)
        except (OSError, KeyError, ValueError):
            return ""
        return (f"Flood maps on the {s['grid']} grid: {s['flooded_km2']:.2f} km² flooded, "
                f"deepest {s['max_depth_m']:.2f} m; {s['reaches_above_bank']} of "
                f"{s['reaches']} river reaches went above their banks.")

    # ── Button slots ──────────────────────────────────────────────────────────

    def _load_layers(self):
        """Add output rasters and vector layers to the QGIS project."""
        from .layer_utils import add_raster, add_vector
        loaded = []

        layer_defs = [
            ("watershed_tif",     "Watershed mask",        "raster"),
            ("clipped_dem",       "Clipped DEM",           "raster"),
            ("flow_accumulation", "Flow accumulation",     "raster"),
            ("flow_direction",    "Flow direction",        "raster"),
            ("watershed_geojson", "Watershed boundary",    "vector"),
        ]

        for key, name, kind in layer_defs:
            path = self._result.get(key)
            lyr = add_raster(path, name) if kind == "raster" else add_vector(path, name)
            if lyr is not None:
                loaded.append(name)

        if loaded:
            self._iface.messageBar().pushSuccess("MRRpy_plugin", f"Loaded {len(loaded)} layer(s): {', '.join(loaded)}"
            )
        else:
            self._iface.messageBar().pushWarning("MRRpy_plugin", "No valid output layers found. Run the model first."
            )

    def _fields_dir(self):
        """The run's saved-maps folder, or None when SAVE_FIELDS was off."""
        import os
        d = self._result.get("fields_dir")
        return d if d and os.path.isfile(os.path.join(d, "fields.npz")) else None

    def _saved_vars(self):
        """Quantities recorded in the saved maps (from fields_meta.json)."""
        import json
        import os
        try:
            with open(os.path.join(self._fields_dir(), "fields_meta.json")) as fh:
                return json.load(fh).get("vars", [])
        except (OSError, ValueError, TypeError):
            return []

    def _load_peak_maps(self):
        """Write the peak GeoTIFFs from the saved maps and add them as layers."""
        from qgis.PyQt.QtWidgets import QApplication
        from .layer_utils import add_raster
        from MRRpy.plotting import export_peak_maps
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            written = export_peak_maps(self._fields_dir())
        except Exception as exc:  # noqa: BLE001
            self._iface.messageBar().pushCritical("MRRpy_plugin", f"Peak maps failed: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        names = {"max_depth": "Peak water depth (m)",
                 "max_discharge": "Peak discharge (m³/s)",
                 "max_velocity": "Peak velocity (m/s)",
                 "time_of_max_depth_hours": "Time of peak depth (h)"}
        loaded = [n for k, n in names.items() if k in written and add_raster(written[k], n)]
        self._iface.messageBar().pushSuccess(
            "MRRpy_plugin", f"Loaded {len(loaded)} map(s): {', '.join(loaded)}")

    def _load_flood_maps(self):
        """Add the flood depth raster and the flooded-area outlines as layers."""
        from .layer_utils import add_raster, add_vector
        loaded = []
        if add_raster(self._result.get("flood_depth_max"), "Flood depth, deepest (m)"):
            loaded.append("flood depth")
        if add_vector(self._result.get("flood_extent_geojson"), "Flooded area"):
            loaded.append("flooded area")
        if loaded:
            self._iface.messageBar().pushSuccess("MRRpy_plugin", f"Loaded {', '.join(loaded)}")
        else:
            self._iface.messageBar().pushWarning("MRRpy_plugin", "No flood maps found.")

    def _open_flood_animation(self):
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._result.get("flood_animation", "")))

    def _save_animation(self):
        """Ask for a .gif path and render the flow animation there."""
        import os
        from qgis.PyQt.QtWidgets import QApplication, QFileDialog
        from MRRpy.plotting import animate_fields
        start = os.path.join(os.path.dirname(self._fields_dir()), "depth_discharge_animation.gif")
        path, _ = QFileDialog.getSaveFileName(self, "Save Flow Animation", start,
                                              "GIF animation (*.gif)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            have = [v for v in ("depth", "discharge") if v in self._saved_vars()]
            animate_fields(self._fields_dir(), have or "depth", path)
        except Exception as exc:  # noqa: BLE001
            self._iface.messageBar().pushCritical("MRRpy_plugin", f"Animation failed: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._iface.messageBar().pushSuccess("MRRpy_plugin", f"Animation saved → {path}")

    def _export_csv(self):
        """Save / copy the hydrograph CSV to a user-chosen location."""
        if self._df is None:
            return
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Hydrograph CSV", "", "CSV files (*.csv)"
        )
        if path:
            self._df.to_csv(path, index=False)
            self._iface.messageBar().pushSuccess("MRRpy_plugin", f"Hydrograph saved → {path}")

    def _export_png(self):
        """Export the embedded plot to a PNG file."""
        if not _MPL_AVAILABLE:
            return
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Hydrograph Plot", "", "PNG images (*.png)"
        )
        if path:
            self._fig.savefig(path, dpi=150, bbox_inches="tight")
            self._iface.messageBar().pushSuccess("MRRpy_plugin", f"Plot saved → {path}")
