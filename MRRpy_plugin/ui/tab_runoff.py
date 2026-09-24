# -*- coding: utf-8 -*-
"""
tab_runoff.py
=============
Tab 3 — Runoff Generation Engine.

Generators (RUNOFF_SOURCE): none · coefficient · raster · scs_cn · physical

The 'physical' panel composes any subset of the three physics MECHANISMS and uses
PROGRESSIVE DISCLOSURE — only the fields for the checked mechanisms are shown:
  • saturation_excess (VSA-OPM) on  → show the VSA sandbox parameters + SD source
    (SD source = GEE/SERVES → hide manual SD_max & phi, show SERVES options).
  • infiltration_excess (Green-Ampt) on → show the Green-Ampt group.
  • impervious on → show the impervious group.
  • A "…source" set to raster → show its file picker; scalar → show its value.
  • The Earth Engine project field appears only when a selected source
    downloads from Earth Engine (``uses_gee()``; ``gee_needs_changed`` tells
    the dialog so the Precipitation tab can show the event date too).

Activating infiltration_excess both reports Hortonian runoff AND caps the VSA
sandbox recharge by infiltration capacity — there is no longer a separate
"sandbox recharge" toggle (see MRRpy/core/runoff/physical.py).
"""

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox, QComboBox,
    QDoubleSpinBox, QSpinBox, QLabel, QCheckBox,
    QScrollArea, QFrame, QLineEdit,
)
from qgis.gui import QgsFileWidget


def _set_row_visible(form: QFormLayout, field, visible: bool):
    """Show/hide a QFormLayout row (both the field and its label, if any)."""
    field.setVisible(visible)
    lbl = form.labelForField(field)
    if lbl is not None:
        lbl.setVisible(visible)


class TabRunoff(QWidget):
    """Runoff generation engine configuration tab."""

    gee_needs_changed = pyqtSignal()   # uses_gee() / needs_event_date() may have changed

    _MODES = ["none", "coefficient", "raster", "scs_cn", "physical"]
    _MODE_LABELS = [
        "None — all rainfall is runoff",
        "Runoff coefficient (static Cf raster)",
        "Pre-computed runoff raster time series",
        "SCS Curve Number",
        "Physical — composable mechanisms (impervious / infiltration / saturation)",
    ]

    _SD_REDUCERS = ["mean", "max", "divide"]
    _SATELLITES = ["landsat", "sentinel2", "modis"]
    _SOILGRIDS_DEPTHS = ["b0", "b10", "b30", "b60", "b100", "b200"]
    _SUCTION_SOURCES = ["scalar", "texture"]
    _KSAT_SOURCES = ["scalar", "gee", "raster"]
    _IMPERVIOUS_UI = ["lcz", "lulc", "raster"]   # 'none' handled by the checkbox
    _CN_SOURCES = ["scalar", "gee", "raster"]
    _CN_AMC = ["i", "ii", "iii"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._wire_disclosure()
        self._apply_disclosure()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        page = QWidget()
        scroll.setWidget(page)
        root = QVBoxLayout(page)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        grp_mode = QGroupBox("Runoff Source")
        form_mode = QFormLayout(grp_mode)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(self._MODE_LABELS)
        self.mode_combo.setCurrentIndex(4)   # default: physical
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form_mode.addRow("Mode:", self.mode_combo)
        root.addWidget(grp_mode)

        # Earth Engine project — only used when a physical-mechanism satellite
        # source is selected (SD=GEE, gridded Ksat, texture suction, LULC/LCZ
        # Manning's n or impervious).  Mirrors the same field on the
        # Precipitation tab; the event date lives there.  Blank is fine for
        # gauge/manual runs.
        grp_ee = self._grp_ee = QGroupBox("Earth Engine")
        form_ee = QFormLayout(grp_ee)
        self._gee_project = QLineEdit()
        self._gee_project.setPlaceholderText(
            "ee-yourusername  (shared with the Precipitation tab)")
        self._gee_project.setToolTip(
            "Google Earth Engine cloud project ID.  Needed when a physical\n"
            "mechanism downloads satellite data (SERVES deficit, gridded Ksat,\n"
            "SoilGrids texture, LULC/LCZ) or SCS-CN uses the GCN250 grid.\n"
            "Kept in sync with the Precipitation tab."
        )
        form_ee.addRow("GEE project:", self._gee_project)
        self._ee_event_note = QLabel("The event start date is set on the Precipitation tab.")
        self._ee_event_note.setStyleSheet("color: #666;")
        form_ee.addRow(self._ee_event_note)
        root.addWidget(grp_ee)

        # One panel per mode (same order as _MODES); only the selected one is shown.
        self._panels = [
            self._build_none_panel(),
            self._build_coefficient_panel(),
            self._build_raster_panel(),
            self._build_scs_cn_panel(),
            self._build_physical_panel(),
        ]
        for w in self._panels:
            root.addWidget(w)
        root.addStretch()
        self._on_mode_changed(self.mode_combo.currentIndex())

    def _build_none_panel(self):
        w = QGroupBox("No Runoff Transformation")
        QFormLayout(w).addRow(QLabel("All rainfall reaches the channel as direct runoff.\nNo files required."))
        return w

    def _build_coefficient_panel(self):
        w = QGroupBox("Runoff Coefficient")
        form = QFormLayout(w)
        self._cf_file = QgsFileWidget()
        self._cf_file.setStorageMode(QgsFileWidget.GetFile)
        self._cf_file.setFilter("GeoTIFF (*.tif *.tiff);;All files (*)")
        form.addRow("Cf raster (0–1):", self._cf_file)
        return w

    def _build_raster_panel(self):
        w = QGroupBox("Pre-computed Runoff Raster Series")
        form = QFormLayout(w)
        self._raster_manifest = QgsFileWidget()
        self._raster_manifest.setStorageMode(QgsFileWidget.GetFile)
        self._raster_manifest.setFilter("CSV (*.csv);;All files (*)")
        form.addRow("Manifest CSV:", self._raster_manifest)
        return w

    def _build_scs_cn_panel(self):
        w = QGroupBox("SCS Curve Number")
        form = self._cn_form = QFormLayout(w)

        self._cn_source = QComboBox()
        self._cn_source.addItems([
            "scalar — uniform CN everywhere",
            "gee — GCN250 global curve-number grid (needs GEE)",
            "raster — CN GeoTIFF",
        ])
        self._cn_source.setToolTip(
            "Where the per-cell curve number comes from.  GCN250 (Jaafar et al.\n"
            "2019) is downloaded from Earth Engine and needs a GEE project.")
        form.addRow("CN source:", self._cn_source)

        self._cn_amc = QComboBox()
        self._cn_amc.addItems([
            "I — dry antecedent moisture",
            "II — normal (standard CN)",
            "III — wet antecedent moisture",
        ])
        self._cn_amc.setCurrentIndex(1)
        self._cn_amc.setToolTip(
            "Antecedent Moisture Condition.  For GEE this picks the GCN250 variant;\n"
            "for scalar/raster (taken as AMC-II) I/III apply the standard conversion.")
        form.addRow("AMC:", self._cn_amc)

        self._cn_value = QDoubleSpinBox()
        self._cn_value.setRange(1.0, 100.0); self._cn_value.setDecimals(1)
        self._cn_value.setValue(75.0)
        self._cn_value.setToolTip("Uniform curve number (scalar source) / nodata fill (raster source).")
        form.addRow("Curve number:", self._cn_value)

        self._cn_file = QgsFileWidget()
        self._cn_file.setStorageMode(QgsFileWidget.GetFile)
        self._cn_file.setFilter("GeoTIFF (*.tif *.tiff);;All files (*)")
        form.addRow("CN raster:", self._cn_file)
        self._ia_factor = QDoubleSpinBox()
        self._ia_factor.setRange(0.0, 0.5)
        self._ia_factor.setDecimals(3)
        self._ia_factor.setValue(0.2)
        form.addRow("Ia factor:", self._ia_factor)
        return w

    # ── Physical panel ─────────────────────────────────────────────────────────

    def _build_physical_panel(self):
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # ── Runoff mechanisms ──────────────────────────────────────────────
        grp_mech = QGroupBox("Runoff Mechanisms  (any combination)")
        h_mech = QVBoxLayout(grp_mech)
        self._chk_imperv = QCheckBox("Impervious (urban) — needs an impervious raster or Earth Engine")
        self._chk_imperv.setChecked(False)
        self._chk_infil = QCheckBox("Infiltration-excess (Green-Ampt / Horton)")
        self._chk_infil.setChecked(True)
        self._chk_sat = QCheckBox("Saturation-excess (VSA-OPM / Dunne)")
        self._chk_sat.setChecked(True)
        for c in (self._chk_sat, self._chk_infil, self._chk_imperv):
            h_mech.addWidget(c)
        grp_mech.setToolTip(
            "Effective runoff = rain · [ Imp + (1 − Imp) · max(in_VSA, infil_excess) ].\n"
            "Activating infiltration-excess also caps the VSA sandbox recharge by\n"
            "the Green-Ampt infiltration capacity (physically consistent)."
        )
        v.addWidget(grp_mech)

        # ── Saturation-excess (VSA-OPM) parameters ─────────────────────────
        self._grp_core = QGroupBox("Saturation-Excess Parameters  (VSA-OPM, Pradhan && Ogden 2010)")
        self._core_form = QFormLayout(self._grp_core)

        self._sd_max = QDoubleSpinBox()
        self._sd_max.setRange(0.001, 5.0); self._sd_max.setDecimals(4)
        self._sd_max.setValue(0.10); self._sd_max.setSuffix(" m")
        self._sd_max.setToolTip("Root-zone depth D at the divide (physical height). Overridden per-zone when SD source = GEE.")
        self._core_form.addRow("SD_max initial (root-zone depth):", self._sd_max)

        self._q_max = QDoubleSpinBox()
        self._q_max.setRange(0.002, 99999.0); self._q_max.setDecimals(4)
        self._q_max.setValue(100.0); self._q_max.setSuffix(" m³/s")
        self._q_max.setToolTip("Observed baseflow / initial outlet discharge (Eq 10 calibration).")
        self._core_form.addRow("Q_max (initial discharge):", self._q_max)

        self._phi = QDoubleSpinBox()
        self._phi.setRange(0.01, 0.99); self._phi.setDecimals(3); self._phi.setValue(0.35)
        self._phi.setToolTip("Drainable porosity. Overridden when SD source = GEE.")
        self._core_form.addRow("phi (porosity):", self._phi)

        self._k_sat = QDoubleSpinBox()
        self._k_sat.setRange(0.001, 500.0); self._k_sat.setDecimals(3)
        self._k_sat.setValue(44.0); self._k_sat.setSuffix(" m/day")
        self._k_sat.setToolTip("LATERAL saturated conductivity (sandbox Darcy drainage).")
        self._core_form.addRow("K_sat (lateral):", self._k_sat)

        self._per_polygon = QCheckBox("Per-polygon sandbox (each precip zone gets its own OPM)")
        self._per_polygon.setChecked(True)
        self._core_form.addRow(self._per_polygon)

        self._baseflow = QCheckBox("Seed baseflow from Q_max (start hydrograph at pre-storm discharge)")
        self._core_form.addRow(self._baseflow)

        v.addWidget(self._grp_core)

        # ── Soil-moisture deficit source (saturation-excess) ───────────────
        self._grp_sd = QGroupBox("Soil-Moisture Deficit  (SD_max && phi source)")
        form_sd = QFormLayout(self._grp_sd)
        self._sd_source = QComboBox()
        self._sd_source.addItems([
            "Manual (use SD_max & phi above)",
            "GEE / SERVES (satellite deficit + SoilGrids porosity + LULC/LCZ depth)",
        ])
        self._sd_source.setToolTip("GEE/SERVES needs an Earth Engine project and the event start\n"
                                   "date (set on the Precipitation tab).")
        form_sd.addRow("SD source:", self._sd_source)
        v.addWidget(self._grp_sd)

        # SERVES sub-options (shown only when SD source = GEE)
        self._grp_serves = QGroupBox("SERVES / SoilGrids Options")
        form_serves = QFormLayout(self._grp_serves)
        self._sd_reducer = QComboBox()
        self._sd_reducer.addItems([
            "mean — zone-average deficit (robust)",
            "max — largest deficit / storage-capacity cell",
            "divide — deficit at each zone's divide cell",
        ])
        form_serves.addRow("Zone reducer:", self._sd_reducer)
        self._satellite = QComboBox(); self._satellite.addItems(self._SATELLITES)
        form_serves.addRow("SERVES satellite:", self._satellite)
        self._search_window = QSpinBox()
        self._search_window.setRange(1, 365); self._search_window.setValue(30)
        self._search_window.setSuffix(" days")
        form_serves.addRow("Search window:", self._search_window)
        self._soilgrids_depth = QComboBox(); self._soilgrids_depth.addItems(self._SOILGRIDS_DEPTHS)
        self._soilgrids_depth.setCurrentText("b30")
        form_serves.addRow("SoilGrids depth band:", self._soilgrids_depth)
        v.addWidget(self._grp_serves)

        # ── Infiltration-excess: Green-Ampt ────────────────────────────────
        self._grp_ga = QGroupBox("Infiltration-Excess  (Green-Ampt)")
        self._ga_form = QFormLayout(self._grp_ga)

        self._suction_source = QComboBox()
        self._suction_source.addItems(["scalar — uniform value", "texture — SoilGrids per-cell (needs GEE)"])
        self._ga_form.addRow("Suction ψ source:", self._suction_source)

        self._suction_m = QDoubleSpinBox()
        self._suction_m.setRange(0.0, 2.0); self._suction_m.setDecimals(3)
        self._suction_m.setValue(0.15); self._suction_m.setSuffix(" m")
        self._suction_m.setToolTip("Wetting-front suction head ψ (loam ≈ 0.1–0.2 m).")
        self._ga_form.addRow("Suction ψ:", self._suction_m)

        self._ksat_source = QComboBox()
        self._ksat_source.addItems(["scalar — uniform value", "gee — HiHydroSoil grid (needs GEE)", "raster — GeoTIFF"])
        self._ga_form.addRow("Vertical Ksat source:", self._ksat_source)

        self._ga_ksat = QDoubleSpinBox()
        self._ga_ksat.setRange(0.01, 500.0); self._ga_ksat.setDecimals(2)
        self._ga_ksat.setValue(12.0); self._ga_ksat.setSuffix(" mm/hr")
        self._ga_ksat.setToolTip("VERTICAL (surface) Ksat — NOT the lateral K_sat. Sand≈50, loam≈10, clay≈1 mm/hr.")
        self._ga_form.addRow("Vertical Ksat:", self._ga_ksat)

        self._ga_ksat_raster = QgsFileWidget()
        self._ga_ksat_raster.setStorageMode(QgsFileWidget.GetFile)
        self._ga_ksat_raster.setFilter("GeoTIFF (*.tif *.tiff);;All files (*)")
        self._ga_form.addRow("Ksat raster:", self._ga_ksat_raster)

        self._ga_ksat_scale = QDoubleSpinBox()
        self._ga_ksat_scale.setRange(0.01, 100.0); self._ga_ksat_scale.setDecimals(2)
        self._ga_ksat_scale.setValue(1.0)
        self._ga_ksat_scale.setToolTip("Calibration multiplier on the (gridded) Ksat.")
        self._ga_form.addRow("Ksat calibration scale:", self._ga_ksat_scale)

        v.addWidget(self._grp_ga)

        # ── Impervious (urban shedding) ────────────────────────────────────
        self._grp_imp = QGroupBox("Impervious Fraction  (urban shedding)")
        self._imp_form = QFormLayout(self._grp_imp)
        self._imperv_source = QComboBox()
        self._imperv_source.addItems([
            "lcz — WUDAPT LCZ column (needs GEE)",
            "lulc — ESA WorldCover column (needs GEE)",
            "raster — pre-computed GeoTIFF",
        ])
        self._imp_form.addRow("Impervious source:", self._imperv_source)
        self._imperv_raster = QgsFileWidget()
        self._imperv_raster.setStorageMode(QgsFileWidget.GetFile)
        self._imperv_raster.setFilter("GeoTIFF (*.tif *.tiff);;All files (*)")
        self._imp_form.addRow("Impervious raster:", self._imperv_raster)
        v.addWidget(self._grp_imp)

        v.addStretch()
        return panel

    # ── Progressive disclosure wiring ──────────────────────────────────────────

    def _wire_disclosure(self):
        self._chk_sat.toggled.connect(self._apply_disclosure)
        self._chk_infil.toggled.connect(self._apply_disclosure)
        self._chk_imperv.toggled.connect(self._apply_disclosure)
        self._sd_source.currentIndexChanged.connect(self._apply_disclosure)
        self._suction_source.currentIndexChanged.connect(self._apply_disclosure)
        self._ksat_source.currentIndexChanged.connect(self._apply_disclosure)
        self._imperv_source.currentIndexChanged.connect(self._apply_disclosure)
        self._cn_source.currentIndexChanged.connect(self._apply_disclosure)

    def _apply_disclosure(self, *args):
        self._grp_ee.setVisible(self.uses_gee())
        self._ee_event_note.setVisible(self.needs_event_date())
        self.gee_needs_changed.emit()

        # SCS-CN: scalar → CN value; raster → file picker (+ CN as nodata fill).
        cn_src = self._CN_SOURCES[self._cn_source.currentIndex()]
        _set_row_visible(self._cn_form, self._cn_value, cn_src in ("scalar", "raster"))
        _set_row_visible(self._cn_form, self._cn_file, cn_src == "raster")

        # Saturation-excess: show the VSA sandbox parameters + SD source.
        sat = self._chk_sat.isChecked()
        self._grp_core.setVisible(sat)
        self._grp_sd.setVisible(sat)
        gee_sd = sat and self._sd_source.currentIndex() == 1
        if sat:
            _set_row_visible(self._core_form, self._sd_max, not gee_sd)
            _set_row_visible(self._core_form, self._phi, not gee_sd)
        self._grp_serves.setVisible(gee_sd)

        # Infiltration-excess: show the Green-Ampt group.
        infil = self._chk_infil.isChecked()
        self._grp_ga.setVisible(infil)
        if infil:
            scalar_psi = self._suction_source.currentIndex() == 0
            _set_row_visible(self._ga_form, self._suction_m, scalar_psi)
            ksat_scalar = self._ksat_source.currentIndex() == 0
            ksat_raster = self._ksat_source.currentIndex() == 2
            _set_row_visible(self._ga_form, self._ga_ksat, ksat_scalar)
            _set_row_visible(self._ga_form, self._ga_ksat_raster, ksat_raster)

        # Impervious group only when the mechanism is active.
        imperv = self._chk_imperv.isChecked()
        self._grp_imp.setVisible(imperv)
        if imperv:
            _set_row_visible(self._imp_form, self._imperv_raster,
                             self._imperv_source.currentIndex() == 2)

    # ── Slot ─────────────────────────────────────────────────────────────────

    def _on_mode_changed(self, idx):
        for i, w in enumerate(self._panels):
            w.setVisible(i == idx)
        if hasattr(self, "_grp_imp"):       # disclosure is wired after the build
            self._apply_disclosure()

    # ── Earth Engine needs (drive what the dialog shows) ──────────────────────

    def uses_gee(self) -> bool:
        """True if the selected runoff sources download from Earth Engine."""
        mode = self.get_mode()
        if mode == "scs_cn":
            return self._CN_SOURCES[self._cn_source.currentIndex()] == "gee"
        if mode != "physical":
            return False
        return bool(
            (self._chk_sat.isChecked() and self._sd_source.currentIndex() == 1)
            or (self._chk_infil.isChecked()
                and (self._KSAT_SOURCES[self._ksat_source.currentIndex()] == "gee"
                     or self._SUCTION_SOURCES[self._suction_source.currentIndex()] == "texture"))
            or (self._chk_imperv.isChecked()
                and self._IMPERVIOUS_UI[self._imperv_source.currentIndex()] in ("lcz", "lulc"))
        )

    def needs_event_date(self) -> bool:
        """SERVES soil-moisture deficit is queried for the event date."""
        return (self.get_mode() == "physical" and self._chk_sat.isChecked()
                and self._sd_source.currentIndex() == 1)

    # ── Public getters ────────────────────────────────────────────────────────

    def get_mode(self) -> str:
        return self._MODES[self.mode_combo.currentIndex()]

    def _mechanisms(self):
        mechs = []
        if self._chk_imperv.isChecked():
            mechs.append("impervious")
        if self._chk_infil.isChecked():
            mechs.append("infiltration_excess")
        if self._chk_sat.isChecked():
            mechs.append("saturation_excess")
        return mechs

    # ── Config I/O ────────────────────────────────────────────────────────────

    def apply_config(self, cfg):
        mode = getattr(cfg, "RUNOFF_SOURCE", "none")
        self.mode_combo.setCurrentIndex(self._MODES.index(mode) if mode in self._MODES else 0)

        if cfg.RUNOFF_COEFFICIENT_PATH:
            self._cf_file.setFilePath(cfg.RUNOFF_COEFFICIENT_PATH)
        if cfg.RUNOFF_RASTER_MANIFEST:
            self._raster_manifest.setFilePath(cfg.RUNOFF_RASTER_MANIFEST)
        if cfg.RUNOFF_CN_PATH:
            self._cn_file.setFilePath(cfg.RUNOFF_CN_PATH)
        self._cn_source.setCurrentIndex(self._idx(self._CN_SOURCES, getattr(cfg, "RUNOFF_CN_SOURCE", "scalar")))
        self._cn_amc.setCurrentIndex(self._idx(self._CN_AMC, getattr(cfg, "RUNOFF_CN_AMC", "ii")))
        self._cn_value.setValue(float(getattr(cfg, "RUNOFF_CN", 75.0)))
        self._ia_factor.setValue(cfg.RUNOFF_SCS_Ia_FACTOR)

        mechs = getattr(cfg, "RUNOFF_MECHANISMS", None) \
            or ["impervious", "infiltration_excess", "saturation_excess"]
        imp_src = getattr(cfg, "IMPERVIOUS_SOURCE", "none") or "none"
        self._chk_sat.setChecked("saturation_excess" in mechs)
        self._chk_infil.setChecked("infiltration_excess" in mechs)
        # Impervious with source 'none' has zero impervious fraction, i.e. no
        # effect — show it unticked rather than defaulting its source to LCZ.
        self._chk_imperv.setChecked(imp_src in self._IMPERVIOUS_UI)

        self._sd_max.setValue(cfg.VSA_SD_MAX_INITIAL)
        self._q_max.setValue(cfg.VSA_Q_MAX)
        self._phi.setValue(cfg.VSA_PHI)
        self._k_sat.setValue(cfg.VSA_K_SAT)
        self._per_polygon.setChecked(bool(getattr(cfg, "VSA_PER_POLYGON", True)))
        self._baseflow.setChecked(bool(getattr(cfg, "VSA_BASEFLOW", False)))

        self._sd_source.setCurrentIndex(1 if getattr(cfg, "VSA_SD_SOURCE", "manual") == "gee" else 0)
        self._sd_reducer.setCurrentIndex(self._idx(self._SD_REDUCERS, getattr(cfg, "VSA_SD_REDUCER", "mean")))
        self._satellite.setCurrentIndex(self._idx(self._SATELLITES, getattr(cfg, "SERVES_SATELLITE", "landsat")))
        self._search_window.setValue(int(getattr(cfg, "SERVES_SEARCH_WINDOW", 30)))
        self._soilgrids_depth.setCurrentText(getattr(cfg, "SOILGRIDS_DEPTH", "b30"))

        self._suction_source.setCurrentIndex(self._idx(self._SUCTION_SOURCES, getattr(cfg, "GA_SUCTION_SOURCE", "scalar")))
        self._suction_m.setValue(float(getattr(cfg, "GA_SUCTION_M", 0.15)))
        self._ksat_source.setCurrentIndex(self._idx(self._KSAT_SOURCES, getattr(cfg, "GA_KSAT_SOURCE", "scalar")))
        self._ga_ksat.setValue(float(getattr(cfg, "GA_KSAT_MMHR", 12.0)))
        if getattr(cfg, "GA_KSAT_RASTER", None):
            self._ga_ksat_raster.setFilePath(cfg.GA_KSAT_RASTER)
        self._ga_ksat_scale.setValue(float(getattr(cfg, "GA_KSAT_SCALE", 1.0)))

        if imp_src in self._IMPERVIOUS_UI:
            self._imperv_source.setCurrentIndex(self._IMPERVIOUS_UI.index(imp_src))
        if getattr(cfg, "IMPERVIOUS_RASTER_PATH", None):
            self._imperv_raster.setFilePath(cfg.IMPERVIOUS_RASTER_PATH)

        if getattr(cfg, "GEE_PROJECT", None):
            self._gee_project.setText(str(cfg.GEE_PROJECT))

        self._apply_disclosure()

    def write_to_config(self, cfg):
        cfg.RUNOFF_SOURCE = self.get_mode()
        cfg.RUNOFF_COEFFICIENT_PATH = self._cf_file.filePath()
        cfg.RUNOFF_RASTER_MANIFEST = self._raster_manifest.filePath()
        cfg.RUNOFF_CN_PATH = self._cn_file.filePath()
        cfg.RUNOFF_CN_SOURCE = self._CN_SOURCES[self._cn_source.currentIndex()]
        cfg.RUNOFF_CN_AMC = self._CN_AMC[self._cn_amc.currentIndex()]
        cfg.RUNOFF_CN = self._cn_value.value()
        cfg.RUNOFF_SCS_Ia_FACTOR = self._ia_factor.value()

        cfg.RUNOFF_MECHANISMS = self._mechanisms()

        cfg.VSA_SD_MAX_INITIAL = self._sd_max.value()
        cfg.VSA_Q_MAX = self._q_max.value()
        cfg.VSA_PHI = self._phi.value()
        cfg.VSA_K_SAT = self._k_sat.value()
        cfg.VSA_PER_POLYGON = self._per_polygon.isChecked()
        cfg.VSA_BASEFLOW = self._baseflow.isChecked()

        cfg.VSA_SD_SOURCE = "gee" if self._sd_source.currentIndex() == 1 else "manual"
        cfg.VSA_SD_REDUCER = self._SD_REDUCERS[self._sd_reducer.currentIndex()]
        cfg.SERVES_SATELLITE = self._SATELLITES[self._satellite.currentIndex()]
        cfg.SERVES_SEARCH_WINDOW = self._search_window.value()
        cfg.SOILGRIDS_DEPTH = self._soilgrids_depth.currentText()

        cfg.GA_SUCTION_SOURCE = self._SUCTION_SOURCES[self._suction_source.currentIndex()]
        cfg.GA_SUCTION_M = self._suction_m.value()
        cfg.GA_KSAT_SOURCE = self._KSAT_SOURCES[self._ksat_source.currentIndex()]
        cfg.GA_KSAT_MMHR = self._ga_ksat.value()
        cfg.GA_KSAT_RASTER = self._ga_ksat_raster.filePath() or None
        cfg.GA_KSAT_SCALE = self._ga_ksat_scale.value()

        # Impervious source is gated by the Impervious mechanism.
        if self._chk_imperv.isChecked():
            cfg.IMPERVIOUS_SOURCE = self._IMPERVIOUS_UI[self._imperv_source.currentIndex()]
            cfg.IMPERVIOUS_RASTER_PATH = self._imperv_raster.filePath() or None
        else:
            cfg.IMPERVIOUS_SOURCE = "none"
            cfg.IMPERVIOUS_RASTER_PATH = None

        # Earth Engine project (kept in sync with the Precipitation tab).
        cfg.GEE_PROJECT = self._gee_project.text().strip() or None

    @staticmethod
    def _idx(options, value):
        return options.index(value) if value in options else 0
