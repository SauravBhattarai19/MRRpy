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
