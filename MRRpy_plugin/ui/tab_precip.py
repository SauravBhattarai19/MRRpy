# -*- coding: utf-8 -*-
"""
tab_precip.py
=============
Tab 2 — Precipitation Engine.

Methods
-------
  uniform         constant intensity + duration
  thiessen        Voronoi nearest-gauge weighting (CSV gauges)
  idw             Inverse Distance Weighting (CSV gauges)
  imerg_thiessen  NASA GPM IMERG V07 from GEE, Thiessen weighting
  imerg_idw       same IMERG source, IDW weighting

The IMERG event window is derived from the "Event start (UTC)" set on the
DEM & Watershed tab plus the simulation duration on the Routing tab, so the
IMERG panel here only carries the weighting/download knobs.
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox, QComboBox,
    QDoubleSpinBox, QLabel, QCheckBox,
    QLineEdit, QDateTimeEdit,
)
from qgis.PyQt.QtCore import QDateTime
from qgis.gui import QgsFileWidget


class TabPrecip(QWidget):
    """Precipitation engine configuration tab."""

    _METHODS = ["uniform", "thiessen", "idw", "imerg_thiessen", "imerg_idw"]
    _METHOD_LABELS = [
        "Uniform (constant rate)",
        "Thiessen polygons (gauge CSV)",
        "Inverse Distance Weighting — IDW (gauge CSV)",
        "IMERG V07 satellite — Thiessen (Earth Engine)",
        "IMERG V07 satellite — IDW (Earth Engine)",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ext_gee_project = False   # set by the dialog from the other tabs
        self._ext_gee_event = False
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Method selector ───────────────────────────────────────────────────
        grp_method = QGroupBox("Precipitation Method")
        form_method = QFormLayout(grp_method)

        self.method_combo = QComboBox()
        self.method_combo.addItems(self._METHOD_LABELS)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        form_method.addRow("Method:", self.method_combo)

        self.exclude_outside = QCheckBox(
            "Exclude gauge/pixel centroids that fall outside the watershed"
        )
        self.exclude_outside.setToolTip(
            "False (default): keep all stations; boundary cells use the nearest\n"
            "outside station.  True: drop outside stations entirely."
        )
        form_method.addRow(self.exclude_outside)

        root.addWidget(grp_method)

        # ── Stacked panel (one per method) ────────────────────────────────────
        # One panel per method (same order as _METHODS); only the selected one
        # is shown, so the tab doesn't reserve space for the largest panel.
        self._panels = [
            self._build_uniform_panel(),
            self._build_gauge_panel("thiessen"),
            self._build_gauge_panel("idw"),
            self._build_imerg_panel("imerg_thiessen"),
            self._build_imerg_panel("imerg_idw"),
        ]
        for w in self._panels:
            root.addWidget(w)

        # ── Rain / snow partition (applies to every method) ───────────────────
        root.addWidget(self._build_snow_group())

        # ── Earth Engine (satellite data) ─────────────────────────────────────
        root.addWidget(self._build_ee_group())
        root.addStretch()
        self._on_method_changed(self.method_combo.currentIndex())

    def _build_ee_group(self):
        """Earth Engine account + event window.

        Only IMERG rainfall (and SERVES soil moisture on the Runoff tab) need
        these; a gauge-only run can leave them blank.  This is the canonical home
        for GEE_PROJECT / EVENT_START_UTC / IMERG_UTC_OFFSET_HOURS — the Runoff
        tab shows a mirror of just the project id.
        """
        grp = self._grp_ee = QGroupBox("Earth Engine")
        form = self._ee_form = QFormLayout(grp)

        self.gee_project = QLineEdit()
        self.gee_project.setPlaceholderText(
            "ee-yourusername  (or leave blank to use the GEE_PROJECT env var)")
        self.gee_project.setToolTip(
            "Google Earth Engine cloud project ID.\n"
            "Required for IMERG rainfall, SERVES deficit, gridded Ksat, and\n"
            "LULC/LCZ downloads.  Authenticate GEE once in the QGIS Python\n"
            "console (import ee; ee.Authenticate()) or place a key.json beside\n"
            "the plugin's serves_gee.py.  Not needed for DEM preprocessing or\n"
            "gauge-based rainfall."
        )
        form.addRow("GEE project:", self.gee_project)

        self.use_event = QCheckBox("Set an event start date (UTC)")
        self.use_event.setToolTip(
            "Required for IMERG rainfall and SERVES soil-moisture deficit.\n"
            "The IMERG download window and the SERVES antecedent-moisture date\n"
            "are both derived from this single timestamp."
        )
        self.use_event.toggled.connect(self._on_use_event_toggled)
        form.addRow(self.use_event)

        self.event_dt = QDateTimeEdit()
        self.event_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.event_dt.setCalendarPopup(True)
        self.event_dt.setDateTime(QDateTime.currentDateTimeUtc())
        self.event_dt.setEnabled(False)
        form.addRow("Event start (UTC):", self.event_dt)

        self.utc_offset = QDoubleSpinBox()
        self.utc_offset.setRange(-12.0, 14.0)
        self.utc_offset.setDecimals(2)
        self.utc_offset.setValue(5.75)   # Nepal Standard Time (UTC+5:45)
        self.utc_offset.setSuffix(" h")
        self.utc_offset.setToolTip(
            "UTC offset for local-time conversion of the IMERG window.\n"
            "Nepal Standard Time = UTC + 5:45 → 5.75.  Use 0 to work in UTC."
        )
        form.addRow("UTC offset:", self.utc_offset)

        return grp

    def _on_use_event_toggled(self, on):
        self.event_dt.setEnabled(on)

    def set_external_gee_needs(self, project: bool, event: bool):
        """Other tabs' Earth Engine needs (runoff / Manning sources)."""
        self._ext_gee_project, self._ext_gee_event = project, event
        self._apply_ee_disclosure()

    def _apply_ee_disclosure(self):
        """Show the Earth Engine fields only when a selected option uses them."""
        imerg = self.get_method().startswith("imerg")
        need_project = imerg or self._ext_gee_project
        need_event = imerg or self._ext_gee_event
        self._grp_ee.setVisible(need_project or need_event)
        # When a date is needed it is simply required — no opt-in checkbox.
        if need_event:
            self.use_event.setChecked(True)
        self.use_event.setVisible(False)
        for w, on in ((self.event_dt, need_event), (self.utc_offset, imerg)):
            w.setVisible(on)
            lbl = self._ee_form.labelForField(w)
            if lbl is not None:
                lbl.setVisible(on)

    def _build_snow_group(self):
        """Optional rain/snow elevation partition (RAIN_SNOW_ELEV_LOW/HIGH).

        Above the freezing level precipitation falls as snow and does not run
        off during the event.  The rain fraction ramps linearly from 1 at the
        low elevation to 0 at the high one; equal values give a hard cutoff.
        """
        grp = QGroupBox("Rain / Snow Partition by Elevation  (optional)")
        form = QFormLayout(grp)

        self.snow_partition = QCheckBox("Treat high-elevation precipitation as snow (no event runoff)")
        self.snow_partition.setToolTip(
            "Scales precipitation per cell by a rain fraction that ramps from 1\n"
            "(at or below the rain elevation) to 0 (at or above the snow elevation).\n"
            "Set both elevations equal for a single hard freezing level.")
        self.snow_partition.toggled.connect(self._on_snow_toggled)
        form.addRow(self.snow_partition)

        self.snow_low = QDoubleSpinBox()
        self.snow_low.setRange(-500.0, 9000.0); self.snow_low.setDecimals(0)
        self.snow_low.setValue(3000.0); self.snow_low.setSuffix(" m")
        self.snow_low.setToolTip("All precipitation is rain at or below this elevation.")
        form.addRow("All rain below:", self.snow_low)

        self.snow_high = QDoubleSpinBox()
        self.snow_high.setRange(-500.0, 9000.0); self.snow_high.setDecimals(0)
        self.snow_high.setValue(4000.0); self.snow_high.setSuffix(" m")
        self.snow_high.setToolTip("All precipitation is snow (excluded) at or above this elevation.")
        form.addRow("All snow above:", self.snow_high)

        self._snow_form = form
        self._on_snow_toggled(False)
        return grp

    def _on_snow_toggled(self, on):
        for w in (self.snow_low, self.snow_high):
            w.setVisible(on)
            lbl = self._snow_form.labelForField(w)
            if lbl is not None:
                lbl.setVisible(on)

    def _build_uniform_panel(self):
        w = QGroupBox("Uniform Rainfall Parameters")
        form = QFormLayout(w)

        self.intensity_spin = QDoubleSpinBox()
        self.intensity_spin.setRange(0.0, 9999.0)
        self.intensity_spin.setDecimals(2)
        self.intensity_spin.setValue(20.0)
        self.intensity_spin.setSuffix(" mm/hr")
        form.addRow("Rainfall intensity:", self.intensity_spin)

        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.0, 9999.0)
        self.duration_spin.setDecimals(2)
        self.duration_spin.setValue(3.0)
        self.duration_spin.setSuffix(" hours")
        form.addRow("Rainfall duration:", self.duration_spin)

        return w

    def _build_gauge_panel(self, method):
        w = QGroupBox("Gauge-Based Rainfall Parameters")
        form = QFormLayout(w)

        gauge_file = QgsFileWidget()
        gauge_file.setStorageMode(QgsFileWidget.GetFile)
        gauge_file.setFilter("CSV files (*.csv);;All files (*)")
        gauge_file.setDialogTitle("Select gauge metadata CSV (gauge_id, name, easting_m, northing_m)")
        form.addRow("Gauge metadata CSV:", gauge_file)

        ts_file = QgsFileWidget()
        ts_file.setStorageMode(QgsFileWidget.GetFile)
        ts_file.setFilter("CSV files (*.csv);;All files (*)")
        ts_file.setDialogTitle("Select timeseries CSV (time_s, G01, G02, …)")
        form.addRow("Timeseries CSV:", ts_file)

        power_spin = None
        if method == "idw":
            power_spin = QDoubleSpinBox()
            power_spin.setRange(0.1, 10.0)
            power_spin.setDecimals(1)
            power_spin.setValue(2.0)
            power_spin.setToolTip("IDW distance exponent p (standard: 2)")
            form.addRow("IDW power (p):", power_spin)

        if method == "thiessen":
            self._thiessen_gauge = gauge_file
            self._thiessen_ts = ts_file
        else:
            self._idw_gauge = gauge_file
            self._idw_ts = ts_file
            self._idw_power = power_spin

        return w

    def _build_imerg_panel(self, method):
        w = QGroupBox("IMERG Satellite Rainfall (NASA GPM V07 via Earth Engine)")
        form = QFormLayout(w)

        note = QLabel(
            "Downloads IMERG V07 pixels as pseudo-gauges over the watershed.\n"
            "Requires a GEE project + event start date (set in the Earth Engine\n"
            "section below).  The window is EVENT_START_UTC … +simulation-duration."
        )
        note.setWordWrap(True)
        form.addRow(note)

        force = QCheckBox("Force re-download (ignore cached IMERG CSVs)")
        form.addRow(force)

        power_spin = None
        if method == "imerg_idw":
            power_spin = QDoubleSpinBox()
            power_spin.setRange(0.1, 10.0)
            power_spin.setDecimals(1)
            power_spin.setValue(2.0)
            power_spin.setToolTip("IDW distance exponent p (standard: 2)")
            form.addRow("IDW power (p):", power_spin)

        if method == "imerg_thiessen":
            self._imerg_th_force = force
        else:
            self._imerg_idw_force = force
            self._imerg_idw_power = power_spin

        return w

    # ── Slot ─────────────────────────────────────────────────────────────────

    def _on_method_changed(self, idx):
        for i, w in enumerate(self._panels):
            w.setVisible(i == idx)
        self._apply_ee_disclosure()
        # "Exclude outside stations" only applies to gauge/pixel methods.
        self.exclude_outside.setVisible(self._METHODS[idx] != "uniform")

    # ── Public getters ────────────────────────────────────────────────────────

    def get_method(self) -> str:
        return self._METHODS[self.method_combo.currentIndex()]

    # ── Config I/O ────────────────────────────────────────────────────────────

    def apply_config(self, cfg):
        idx = self._METHODS.index(cfg.PRECIP_METHOD) if cfg.PRECIP_METHOD in self._METHODS else 0
        self.method_combo.setCurrentIndex(idx)
        self.exclude_outside.setChecked(bool(getattr(cfg, "PRECIP_EXCLUDE_OUTSIDE_STATIONS", False)))
        self.intensity_spin.setValue(cfg.RAIN_INTENSITY_MM_HR)
        self.duration_spin.setValue(cfg.RAIN_DURATION_HOURS)
        if cfg.PRECIP_GAUGE_FILE:
            self._thiessen_gauge.setFilePath(cfg.PRECIP_GAUGE_FILE)
            self._idw_gauge.setFilePath(cfg.PRECIP_GAUGE_FILE)
        if cfg.PRECIP_TIMESERIES_FILE:
            self._thiessen_ts.setFilePath(cfg.PRECIP_TIMESERIES_FILE)
            self._idw_ts.setFilePath(cfg.PRECIP_TIMESERIES_FILE)
        self._idw_power.setValue(cfg.PRECIP_IDW_POWER)
        self._imerg_idw_power.setValue(cfg.PRECIP_IDW_POWER)
        force = bool(getattr(cfg, "PRECIP_IMERG_FORCE_DOWNLOAD", False))
        self._imerg_th_force.setChecked(force)
        self._imerg_idw_force.setChecked(force)

        # Earth Engine + event window
        if getattr(cfg, "EVENT_START_UTC", None):
            self.use_event.setChecked(True)
            dt = QDateTime.fromString(str(cfg.EVENT_START_UTC).strip(), "yyyy-MM-dd HH:mm")
            if dt.isValid():
                self.event_dt.setDateTime(dt)
        else:
            self.use_event.setChecked(False)
        self.utc_offset.setValue(float(getattr(cfg, "IMERG_UTC_OFFSET_HOURS", 5.75)))
        if getattr(cfg, "GEE_PROJECT", None):
            self.gee_project.setText(str(cfg.GEE_PROJECT))

        # Rain/snow partition: either bound alone means a hard cutoff there
        # (the router substitutes the missing one), so mirror that here.
        lo = getattr(cfg, "RAIN_SNOW_ELEV_LOW", None)
        hi = getattr(cfg, "RAIN_SNOW_ELEV_HIGH", None)
        self.snow_partition.setChecked(lo is not None or hi is not None)
        if lo is not None or hi is not None:
            self.snow_low.setValue(float(lo if lo is not None else hi))
            self.snow_high.setValue(float(hi if hi is not None else lo))

    def write_to_config(self, cfg):
        method = self.get_method()
        cfg.PRECIP_METHOD = method
        cfg.PRECIP_EXCLUDE_OUTSIDE_STATIONS = self.exclude_outside.isChecked()
        cfg.RAIN_INTENSITY_MM_HR = self.intensity_spin.value()
        cfg.RAIN_DURATION_HOURS = self.duration_spin.value()

        # Earth Engine + event window (canonical home for these settings)
        if self.use_event.isChecked():
            cfg.EVENT_START_UTC = self.event_dt.dateTime().toString("yyyy-MM-dd HH:mm")
        else:
            cfg.EVENT_START_UTC = None
        cfg.IMERG_UTC_OFFSET_HOURS = self.utc_offset.value()
        cfg.GEE_PROJECT = self.gee_project.text().strip() or None

        if self.snow_partition.isChecked():
            cfg.RAIN_SNOW_ELEV_LOW = self.snow_low.value()
            cfg.RAIN_SNOW_ELEV_HIGH = self.snow_high.value()
        else:
            cfg.RAIN_SNOW_ELEV_LOW = None
            cfg.RAIN_SNOW_ELEV_HIGH = None

        if method == "thiessen":
            cfg.PRECIP_GAUGE_FILE = self._thiessen_gauge.filePath()
            cfg.PRECIP_TIMESERIES_FILE = self._thiessen_ts.filePath()
        elif method == "idw":
            cfg.PRECIP_GAUGE_FILE = self._idw_gauge.filePath()
            cfg.PRECIP_TIMESERIES_FILE = self._idw_ts.filePath()
            cfg.PRECIP_IDW_POWER = self._idw_power.value()
        elif method == "imerg_thiessen":
            cfg.PRECIP_IMERG_FORCE_DOWNLOAD = self._imerg_th_force.isChecked()
        elif method == "imerg_idw":
            cfg.PRECIP_IMERG_FORCE_DOWNLOAD = self._imerg_idw_force.isChecked()
            cfg.PRECIP_IDW_POWER = self._imerg_idw_power.value()
