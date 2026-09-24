# -*- coding: utf-8 -*-
"""
main_dialog.py
==============
MainDialog — the primary 5-tab QDialog of MRRpy_plugin.

Layout
------
  ┌──────────────────────────────────────────────┐
  │  [Tab 1: DEM] [Tab 2: Precip] [Tab 3: Runoff] │
  │  [Tab 4: Routing] [Tab 5: Results]            │
  ├──────────────────────────────────────────────┤
  │  Stage checkboxes:  ☑ DEM   ☑ Routing  ☐ VSA│
  ├──────────────────────────────────────────────┤
  │  Progress bar  ███████░░░░░  57 %            │
  ├──────────────────────────────────────────────┤
  │  Log panel (QPlainTextEdit, read-only)       │
  ├──────────────────────────────────────────────┤
  │  [Run] [Cancel] [Load] [Save] [Deps] [Close] │
  └──────────────────────────────────────────────┘
"""

import copy
import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QProgressBar, QPlainTextEdit,
    QGroupBox, QCheckBox, QMessageBox,
    QSizePolicy,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsApplication

from ..bridge.config_bridge import Config
from ..bridge.runner import PipelineWorker, DemStepWorker
from ..bridge.dependencies import missing as missing_deps
from .dependency_dialog import DependencyDialog
from .layer_utils import add_raster, add_vector, zoom_to_layer
from .tab_dem import TabDem
from .tab_precip import TabPrecip
from .tab_runoff import TabRunoff
from .tab_routing import TabRouting
from .tab_results import TabResults


class MainDialog(QDialog):
    """
    Main MRRpy_plugin modelling dialog.

    Parameters
    ----------
    iface : QgisInterface
    parent : QWidget, optional
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self._iface = iface
        self._worker = None
        self._dem_worker = None   # background worker for the guided DEM steps
        # Config loaded from a file.  Runs start from a copy of it, so settings
        # without a widget (virtual gauges, inflow BCs, field output, DEM
        # auto-download bounds, …) are carried through instead of reset.
        self._base_cfg = None
        # True while the DEM stage is unticked because the guided Delineate step
        # already produced the watershed (re-ticked if that watershed goes stale).
        self._dem_stage_skipped = False

        self.setWindowTitle("MRRpy_plugin")
        self.setMinimumSize(780, 680)
        self.resize(900, 760)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        self._build_ui()
        self._connect_signals()
        self._refresh_gee_needs()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ── Tab widget ────────────────────────────────────────────────────────
        self.tabs = QTabWidget()

        self.tab_dem = TabDem(self._iface)
        self.tab_precip = TabPrecip()
        self.tab_runoff = TabRunoff()
        self.tab_routing = TabRouting()
        self.tab_results = TabResults(self._iface)

        self.tabs.addTab(self.tab_dem,     "1 · DEM && Watershed")
        self.tabs.addTab(self.tab_precip,  "2 · Precipitation")
        self.tabs.addTab(self.tab_runoff,  "3 · Runoff")
        self.tabs.addTab(self.tab_routing, "4 · Routing")
        self.tabs.addTab(self.tab_results, "5 · Results")

        root.addWidget(self.tabs, stretch=3)

        # ── Stage selection ───────────────────────────────────────────────────
        grp_stages = QGroupBox("Pipeline Stages to Run")
        h_stages = QHBoxLayout(grp_stages)

        self.chk_dem = QCheckBox("DEM Pre-processing")
        self.chk_dem.setChecked(True)
        self.chk_dem.setToolTip(
            "Run process_dem.py: reproject, fill sinks, flow direction,\n"
            "flow accumulation, watershed delineation."
        )

        self.chk_routing = QCheckBox("Routing")
        self.chk_routing.setChecked(True)
        self.chk_routing.setToolTip(
            "Run the routing stage with the scheme chosen on the Routing tab\n"
            "(kinematic / diffusive / Muskingum–Cunge / dynamic / semi-implicit\n"
            "diffusive): initialise grid, time loop, save hydrograph CSV."
        )

        self.chk_vsa = QCheckBox("Standalone VSA-OPM")
        self.chk_vsa.setChecked(False)
        self.chk_vsa.setToolTip(
            "Run the standalone VSA-OPM model (MRRpy.core.opm) to generate\n"
            "vsa_opm_results.csv (inspect OPM dynamics without the router)."
        )

        h_stages.addWidget(self.chk_dem)
        h_stages.addWidget(self.chk_routing)
        h_stages.addWidget(self.chk_vsa)
        h_stages.addStretch()

        root.addWidget(grp_stages)

        # ── Progress bar ──────────────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        root.addWidget(self.progress_bar)

        # ── Log panel ─────────────────────────────────────────────────────────
        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(5000)   # keep last 5000 lines
        self.log_panel.setPlaceholderText("Model output will appear here during a run …")
        monofont = self.log_panel.font()
        monofont.setFamily("Monospace")
        monofont.setPointSize(9)
        self.log_panel.setFont(monofont)
        self.log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.log_panel, stretch=2)

        # ── Button row ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        self.run_btn = QPushButton(QgsApplication.getThemeIcon("/mActionStart.svg"), "Run")
        self.run_btn.setDefault(True)
        self.run_btn.setMinimumWidth(100)
        self.run_btn.setStyleSheet(
            "QPushButton { background-color: #2E86AB; color: white; "
            "font-weight: bold; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1B6CA8; }"
            "QPushButton:disabled { background-color: #aaa; }"
        )

        self.cancel_btn = QPushButton(QgsApplication.getThemeIcon("/mActionStop.svg"), "Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumWidth(90)

        self.load_cfg_btn = QPushButton(QgsApplication.getThemeIcon("/mActionFileOpen.svg"), "Load Config")
        self.load_cfg_btn.setToolTip(
            "Fill every tab from a config file (.yaml / .json / legacy .py) —\n"
            "the same files the MRRpy CLI uses.  Settings that have no widget\n"
            "here (virtual gauges, inflow hydrographs, field output, …) are\n"
            "kept and used for the run."
        )

        self.save_cfg_btn = QPushButton(QgsApplication.getThemeIcon("/mActionFileSave.svg"), "Save Config")
        self.save_cfg_btn.setToolTip(
            "Write the current settings to a config file: .yaml / .json\n"
            "(usable with `MRRpy run -c`) or a legacy config.py module."
        )

        self.deps_btn = QPushButton(QgsApplication.getThemeIcon("/mActionShowPluginManager.svg"), "Dependencies")
        self.deps_btn.setToolTip(
            "Check / install the Python packages the model needs\n"
            "(rasterio, pysheds, …) into QGIS's own Python."
        )

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)

        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.load_cfg_btn)
        btn_row.addWidget(self.save_cfg_btn)
        btn_row.addWidget(self.deps_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.close_btn)

        root.addLayout(btn_row)

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self):
        self.run_btn.clicked.connect(self._on_run)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.load_cfg_btn.clicked.connect(self._on_load_config)
        self.save_cfg_btn.clicked.connect(self._on_save_config)
        self.deps_btn.clicked.connect(self._open_dependencies)

        # Guided DEM workflow (Tab 1) — the tab only requests a step; the dialog
        # runs it off-thread and loads the resulting layers.
        self.tab_dem.request_analyze_terrain.connect(self._on_analyze_terrain)
        self.tab_dem.request_delineate.connect(self._on_delineate)

        # Keep the Earth Engine project id in sync across the Precip & Runoff tabs
        # (one config value, shown in two places).
        self.tab_precip.gee_project.textChanged.connect(self._sync_gee_project)
        self.tab_runoff._gee_project.textChanged.connect(self._sync_gee_project)

        # Earth Engine fields appear only when a selected option needs them.
        self.tab_runoff.gee_needs_changed.connect(self._refresh_gee_needs)
        self.tab_routing.mannings_source.currentIndexChanged.connect(self._refresh_gee_needs)

        # Guided delineation ↔ the "DEM Pre-processing" stage.
        self.tab_dem.watershed_stale.connect(self._on_watershed_stale)

    def _refresh_gee_needs(self, *args):
        """Tell the Precipitation tab (home of the GEE project / event date)
        what the Runoff and Routing tabs need from Earth Engine."""
        self.tab_precip.set_external_gee_needs(
            project=self.tab_runoff.uses_gee() or self.tab_routing.uses_gee(),
            event=self.tab_runoff.needs_event_date(),
        )

    def _on_watershed_stale(self):
        """An input of the delineated watershed changed → recompute it on Run."""
        if self._dem_stage_skipped:
            self._dem_stage_skipped = False
            self.chk_dem.setChecked(True)
            self._append_log("[INFO] Watershed inputs changed — “DEM Pre-processing” "
                             "is ticked again (or re-run Delineate on tab 1).")

    def _sync_gee_project(self, text):
        """Mirror the GEE project id between the Precip and Runoff tabs."""
        for widget in (self.tab_precip.gee_project, self.tab_runoff._gee_project):
            if widget.text() != text:
                widget.blockSignals(True)
                widget.setText(text)
                widget.blockSignals(False)

    # ── Guided DEM workflow ────────────────────────────────────────────────────

    def _on_analyze_terrain(self):
        """Run outlet-independent terrain analysis, then draw streams on the map."""
        if not self._deps_ok():
            return
        dem = self.tab_dem.get_dem_path()
        out = self.tab_dem.get_output_dir()
        if not dem or not os.path.exists(dem):
            QMessageBox.warning(self, "No DEM", "Select a valid DEM file first.")
            return
        if not out:
            QMessageBox.warning(self, "No output directory",
                                "Choose an output directory first.")
            return
        params = {
            "dem_path": dem,
            "target_crs_epsg": self.tab_dem.get_target_crs(),
            "output_dir": out,
            "engine": self.tab_dem.get_delineation_engine(),
        }
        self._start_dem_step("analyze_terrain", params)

    def _on_delineate(self):
        """Snap the picked outlet to the stream network and delineate the watershed."""
        if not self._deps_ok():
            return
        out = self.tab_dem.get_output_dir()
        if not out or not os.path.exists(os.path.join(out, "flow_direction.tif")):
            QMessageBox.warning(self, "Analyze terrain first",
                                "Run “Analyze terrain” before delineating the watershed.")
            return
        lat, lon = self.tab_dem.get_outlet_point()
        params = {
            "output_dir": out,
            "output_point_latlon": (lat, lon),
            "target_crs_epsg": self.tab_dem.get_target_crs(),
            "engine": self.tab_dem.get_delineation_engine(),
        }
        self._start_dem_step("delineate", params)

    def _start_dem_step(self, task, params):
        """Spawn the background DEM-step worker and route its signals."""
        self.log_panel.clear()
        self.run_btn.setEnabled(False)
        self.tab_dem.set_busy(True)
        self.progress_bar.setRange(0, 0)   # indeterminate/busy

        self._dem_worker = DemStepWorker(task, params, parent=self)
        self._dem_worker.log.connect(self._append_log)
        self._dem_worker.finished.connect(self._on_dem_step_finished)
        self._dem_worker.error.connect(self._on_dem_step_error)
        self._dem_worker.start()

    def _end_dem_step(self):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.run_btn.setEnabled(True)
        self.tab_dem.set_busy(False)

    def _on_dem_step_finished(self, result: dict):
        self._end_dem_step()
        task = result.get("task")
        if task == "analyze_terrain":
            dem = add_raster(result.get("reprojected_dem"), "DEM (reprojected)")
            add_raster(result.get("flow_accumulation"), "Flow accumulation")
            streams = add_vector(result.get("streams"), "Streams")
            zoom_to_layer(self._iface, streams or dem)
            self.tab_dem.set_terrain_ready(True)
            self.tab_dem.activate_pick()
            self._append_log("\n[OK] Terrain ready — pick your outlet on a stream.")
            self._iface.messageBar().pushInfo("MRRpy_plugin", "Streams drawn — pick your outlet on a stream, then Delineate.")
        elif task == "delineate":
            ws = add_vector(result.get("watershed_geojson"), "Watershed boundary")
            zoom_to_layer(self._iface, ws)
            self._append_log("\n[OK] Watershed delineated.")
            # The DEM stage would only redo this — skip it on Run.
            self.chk_dem.setChecked(False)
            self._dem_stage_skipped = True
            self._append_log("[INFO] “DEM Pre-processing” unticked — Run will use this "
                             "watershed. Tick it to recompute from the DEM.")
            self._iface.messageBar().pushSuccess("MRRpy_plugin", "Watershed delineated — you can now run Routing.")

    def _on_dem_step_error(self, message: str):
        self._end_dem_step()
        self._append_log(f"\n[ERROR] {message}")
        self._iface.messageBar().pushCritical("MRRpy_plugin", message.splitlines()[0])
        QMessageBox.critical(self, "MRRpy_plugin — DEM Step Error", message)

    def _deps_ok(self) -> bool:
        """Guard: ensure required Python packages are installed; offer the installer."""
        miss = missing_deps(include_optional=False)
        if not miss:
            return True
        names = ", ".join(m[1] for m in miss)
        resp = QMessageBox.question(
            self, "Missing Python packages",
            f"The model needs these packages, which are not installed in "
            f"QGIS's Python:\n\n    {names}\n\n"
            "Open the Dependencies manager to install them now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if resp == QMessageBox.Yes:
            self._open_dependencies()
        return False

    # ── Run / Cancel ──────────────────────────────────────────────────────────

    def _on_run(self):
        """Validate config, build stages list, spawn worker thread."""
        # ── Dependency guard ──────────────────────────────────────────────────
        # Catch missing packages up-front so users get a guided installer instead
        # of a cryptic "ModuleNotFoundError: No module named 'rasterio'".
        if not self._deps_ok():
            return

        cfg = self._collect_config()
        if cfg is None:
            return   # validation failed; user already shown a message

        stages = []
        if self.chk_dem.isChecked():
            stages.append("process_dem")
        if self.chk_routing.isChecked():
            stages.append("routing")
        if self.chk_vsa.isChecked():
            stages.append("vsa_opm")

        if not stages:
            QMessageBox.warning(self, "No stages selected",
                                "Please tick at least one pipeline stage to run.")
            return

        # Without the DEM stage, routing / VSA-OPM need an existing watershed.
        if "process_dem" not in stages:
            needed = [cfg.ROUTING_DEM_PATH, cfg.ROUTING_FLOW_DIR_PATH,
                      cfg.ROUTING_FLOW_ACCUM_PATH, cfg.ROUTING_WATERSHED_MASK_PATH]
            missing = [os.path.basename(p) for p in needed if not os.path.exists(p)]
            if missing:
                QMessageBox.warning(
                    self, "No watershed yet",
                    f"The output directory has no delineated watershed "
                    f"(missing: {', '.join(missing)}).\n\n"
                    "Delineate it on tab 1 (Analyze terrain → pick outlet → "
                    "Delineate watershed), or tick “DEM Pre-processing”.")
                return

        # ── GPU VRAM check ────────────────────────────────────────────────────
        if cfg.BACKEND == "gpu":
            self._check_gpu_vram()

        # ── Start worker ──────────────────────────────────────────────────────
        self.log_panel.clear()
        self.progress_bar.setValue(0)
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self._worker = PipelineWorker(cfg, stages, parent=self)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.log.connect(self._append_log)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.start()

    def _on_cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        self.cancel_btn.setEnabled(False)

    # ── Worker slots ──────────────────────────────────────────────────────────

    def _append_log(self, text: str):
        self.log_panel.appendPlainText(text)
        # Auto-scroll to bottom
        sb = self.log_panel.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_finished(self, result: dict):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self._append_log("\n[OK] Pipeline finished successfully.")

        # Push to results tab
        if result.get("hydrograph_df") is not None or result.get("watershed_tif"):
            self.tab_results.update_results(result)
            self.tabs.setCurrentWidget(self.tab_results)

        # QGIS message bar
        self._iface.messageBar().pushSuccess(
            "MRRpy_plugin", "Model run complete.  Check the Results tab.")

    def _on_cancelled(self):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self._append_log("\n[INFO] Run cancelled.")

    def _on_error(self, message: str):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._append_log(f"\n[ERROR] {message}")
        self._iface.messageBar().pushCritical("MRRpy_plugin", message.splitlines()[0])
        QMessageBox.critical(self, "MRRpy_plugin — Run Error", message)

    # ── Config helpers ────────────────────────────────────────────────────────

    def _build_config(self) -> Config:
        """Config from all UI tabs, on top of the loaded config (if any)."""
        cfg = copy.deepcopy(self._base_cfg) if self._base_cfg is not None else Config()
        self.tab_dem.write_to_config(cfg)
        self.tab_precip.write_to_config(cfg)
        self.tab_runoff.write_to_config(cfg)
        self.tab_routing.write_to_config(cfg)
        return cfg

    def _collect_config(self) -> Config:
        """
        Build a Config from all UI tabs.
        Returns None if validation fails (and shows a warning to the user).
        """
        cfg = self._build_config()

        try:
            cfg.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Configuration Error", str(exc))
            return None

        return cfg

    def _open_dependencies(self):
        """Open the dependency status/installer dialog (modal)."""
        dlg = DependencyDialog(parent=self)
        dlg.exec_()

    def load_config(self, path):
        """Load a .yaml / .json / .py config file into every tab."""
        cfg = Config.from_file(path)
        self._base_cfg = cfg
        self.tab_dem.apply_config(cfg)
        self.tab_precip.apply_config(cfg)
        self.tab_runoff.apply_config(cfg)
        self.tab_routing.apply_config(cfg)
        self._refresh_gee_needs()
        return cfg

    def _on_load_config(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Config", "",
            "Config files (*.yaml *.yml *.json *.py);;All files (*)"
        )
        if not path:
            return
        try:
            self.load_config(path)
        except Exception as exc:  # noqa: BLE001 — bad file / unknown key / missing PyYAML
            QMessageBox.warning(self, "Could not load config", f"{path}\n\n{exc}")
            return
        self._append_log(f"[INFO] Loaded config: {path}")
        self._iface.messageBar().pushSuccess("MRRpy_plugin", f"Config loaded ← {path}")

    def _on_save_config(self):
        """Export current settings to YAML / JSON, or a config.py-compatible module."""
        from qgis.PyQt.QtWidgets import QFileDialog
        path, selected = QFileDialog.getSaveFileName(
            self, "Save Config", "",
            "YAML (*.yaml *.yml);;JSON (*.json);;Python config module (*.py)"
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += {"JSON": ".json", "Python": ".py"}.get(selected.split(" ")[0], ".yaml")

        cfg = self._build_config()
        try:
            if path.lower().endswith(".py"):
                _write_config_py(cfg, path)
            else:
                cfg.save(path)
        except Exception as exc:  # noqa: BLE001 — e.g. PyYAML missing, unserialisable rule
            QMessageBox.warning(self, "Could not save config", f"{path}\n\n{exc}")
            return
        self._iface.messageBar().pushSuccess("MRRpy_plugin", f"Config saved → {path}"
        )

    # ── GPU VRAM advisory ─────────────────────────────────────────────────────

    def _check_gpu_vram(self):
        try:
            import cupy as cp
            free_b, total_b = cp.cuda.Device(0).mem_info
            free_gb = free_b / 1e9
            if free_gb < 0.5:
                QMessageBox.warning(
                    self, "Low GPU VRAM",
                    f"Only {free_gb:.2f} GB VRAM free.\n"
                    "The model may run out of memory.  "
                    "Consider switching to CPU or using float32 precision."
                )
        except Exception:  # noqa: BLE001
            pass   # CuPy not available — GPU toggle already disabled


# ── Config file writer ─────────────────────────────────────────────────────────

def _write_config_py(cfg: Config, path: str):
    """
    Write an Config to a config.py-compatible Python source file.
    The output file is valid Python and can replace config.py directly.

    Every attribute is dumped from cfg.to_dict(), so this export stays complete
    automatically as new parameters are added to Config / config.py.
    Parameters are grouped by section for readability; any attribute not
    assigned to a section falls into a final "OTHER" block.
    """
    # Section → ordered list of attribute names (mirrors config.py layout).
    sections = [
        ("1. EVENT & SCENARIO", [
            "DEM_PATH", "DEM_BOUNDS_WGS84", "DEM_SOURCE", "DEM_SCALE_M",
            "TARGET_CRS_EPSG", "OUTPUT_POINT", "OUTPUT_DIR",
            "DELINEATION_ENGINE", "EVENT_START_UTC", "TOTAL_SIMULATION_TIME_HOURS",
            "IMERG_UTC_OFFSET_HOURS", "LULC_LOOKUP_CSV", "LCZ_LOOKUP_CSV",
            "GEE_PROJECT",
        ]),
        ("2. WATERSHED PRE-PROCESSING OUTPUTS", [
            "ROUTING_DEM_PATH", "ROUTING_FLOW_DIR_PATH", "ROUTING_FLOW_ACCUM_PATH",
            "ROUTING_WATERSHED_MASK_PATH", "WATERSHED_GEOJSON",
        ]),
        ("3. PRECIPITATION", [
            "RAIN_INTENSITY_MM_HR", "RAIN_DURATION_HOURS", "PRECIP_METHOD",
            "PRECIP_GAUGE_FILE", "PRECIP_TIMESERIES_FILE", "PRECIP_IDW_POWER",
            "PRECIP_EXCLUDE_OUTSIDE_STATIONS", "IMERG_START_LOCAL",
            "IMERG_END_LOCAL", "PRECIP_IMERG_DIR", "IMERG_DATASET", "IMERG_BAND",
            "PRECIP_IMERG_FORCE_DOWNLOAD", "IMERG_BBOX_BUFFER_M",
            "RAIN_SNOW_ELEV_LOW", "RAIN_SNOW_ELEV_HIGH",
        ]),
        ("4. RUNOFF GENERATION", [
            "RUNOFF_SOURCE", "RUNOFF_COEFFICIENT_PATH", "RUNOFF_RASTER_MANIFEST",
            "RUNOFF_CN_SOURCE", "RUNOFF_CN_AMC", "RUNOFF_CN",
            "RUNOFF_CN_PATH", "RUNOFF_SCS_Ia_FACTOR",
        ]),
        ("5. PHYSICAL RUNOFF MECHANISMS", [
            "RUNOFF_MECHANISMS", "VSA_SD_MAX_INITIAL", "VSA_SD_MIN", "VSA_Q_MAX", "VSA_PHI",
            "VSA_K_SAT", "VSA_PER_POLYGON",
            "GA_SUCTION_SOURCE", "GA_SUCTION_M", "GA_KSAT_SOURCE",
            "GA_KSAT_MMHR", "GA_KSAT_RASTER", "GA_KSAT_SCALE",
            "IMPERVIOUS_SOURCE", "IMPERVIOUS_RASTER_PATH", "VSA_BASEFLOW",
        ]),
        ("6. SHARED SOIL / SATELLITE FORCING", [
            "VSA_SD_SOURCE", "VSA_SD_REDUCER", "VSA_DEFICIT_RASTER",
            "SERVES_SATELLITE", "SERVES_SEARCH_WINDOW", "SOILGRIDS_DEPTH",
            "SERVES_TARGET_DATE",
        ]),
        ("7. MANNING'S ROUGHNESS", [
            "MANNINGS_N_SOURCE", "MANNINGS_N", "MANNINGS_N_LULC_PATH",
            "MANNINGS_N_RASTER_PATH", "MANNINGS_N_CHANNEL", "CHANNEL_FACCUM_THRESHOLD",
        ]),
        ("8. GRID & NUMERICAL LIMITS", [
            "CELL_SIZE", "ROUTING_SCHEME", "DIFFUSION_THETA", "DYNAMIC_FLUX_THETA",
            "IMPLICIT_MAX_ITERS", "IMPLICIT_TOL", "IMPLICIT_SLOPE_FLOOR",
            "IMPLICIT_THETA", "IMPLICIT_RELAX", "IMPLICIT_CFL_TARGET",
            "IMPLICIT_SOLVER", "IMPLICIT_NUM_THREADS",
            "CHANNEL_ROUTING", "CHANNEL_WIDTH_BY_ORDER",
            "ROUTING_INFLOW_BC", "ROUTING_GAUGES",
            "TIME_STEP_SECONDS", "OUTPUT_INTERVAL_SECONDS",
            "ADAPTIVE_TIMESTEP", "CFL_TARGET", "CFL_DT_MAX", "CFL_DT_MIN",
            "CFL_DT_GROW", "MIN_SLOPE", "MIN_DEPTH_M", "MAX_DEPTH_M",
            "MANNING_SLOPE_CAP", "FLUX_LIMITER",
        ]),
        ("9. OUTPUTS", [
            "HYDROGRAPH_CSV", "MASS_BALANCE_REPORT", "MASS_BALANCE_CSV",
            "SAVE_FIELDS", "FIELD_VARS", "FIELD_STRIDE", "FIELD_OUTPUT_DIR",
        ]),
        ("10. COMPUTE BACKEND", [
            "BACKEND", "GPU_PRECISION",
        ]),
    ]

    data = cfg.to_dict()
    lines = [
        "# config.py  —  generated by MRRpy_plugin (QGIS)\n",
        "# Values only, no logic.  This file can replace config.py directly.\n\n",
    ]

    written = set()
    for title, names in sections:
        lines.append(f"# {'='*70}\n# {title}\n# {'='*70}\n\n")
        for name in names:
            if name in data:
                lines.append(f"{name} = {data[name]!r}\n")
                written.add(name)
        lines.append("\n")

    # Any attribute not assigned to a section (future-proofing).
    leftover = [k for k in data if k not in written]
    if leftover:
        lines.append(f"# {'='*70}\n# OTHER\n# {'='*70}\n\n")
        for name in leftover:
            lines.append(f"{name} = {data[name]!r}\n")
        lines.append("\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
