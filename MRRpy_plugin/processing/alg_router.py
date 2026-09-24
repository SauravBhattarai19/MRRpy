# -*- coding: utf-8 -*-
"""
alg_router.py
=============
QGIS Processing Algorithm: Routing (all schemes).

Wraps MRRpy.core.routing.router.initialise_grid() + run_time_loop() +
save_hydrograph() using a Config object.  Algorithm id:
``mrrpy_plugin:routing``.  Any routing scheme the core registers (kinematic,
diffusive, muskingum, dynamic, diffusive_implicit, …) can be selected.

Inputs (key ones — all config.py parameters are exposed)
------
  DEM_TIF         : clipped DEM raster
  FLOW_DIR_TIF    : flow direction raster
  FLOW_ACCUM_TIF  : flow accumulation raster
  WATERSHED_TIF   : watershed mask raster
  PRECIP_METHOD   : uniform | thiessen | idw | imerg_thiessen | imerg_idw
  RUNOFF_SOURCE   : none | coefficient | raster | scs_cn | physical
  ROUTING_SCHEME  : kinematic | diffusive | muskingum | dynamic | diffusive_implicit
  BACKEND         : cpu | gpu
  … (all routing parameters from config.py)

Outputs
-------
  HYDROGRAPH_CSV  : path to the output hydrograph CSV
"""

import os
import sys

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterEnum,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterFile,
    QgsProcessingParameterDefinition,
    QgsProcessingContext,
    QgsProcessingFeedback,
)

from ..bridge import ensure_core, core_choices


class RoutingAlgorithm(QgsProcessingAlgorithm):
    """QGIS Processing wrapper for the kinematic-wave routing pipeline."""

    # Raster inputs
    DEM_TIF = "DEM_TIF"
    FLOW_DIR_TIF = "FLOW_DIR_TIF"
    FLOW_ACCUM_TIF = "FLOW_ACCUM_TIF"
    WATERSHED_TIF = "WATERSHED_TIF"

    # Routing parameters
    MANNINGS_N = "MANNINGS_N"
    TIME_STEP = "TIME_STEP"
    SIM_HOURS = "SIM_HOURS"
    OUT_INTERVAL = "OUT_INTERVAL"

    # Precipitation
    PRECIP_METHOD = "PRECIP_METHOD"
    RAIN_INTENSITY = "RAIN_INTENSITY"
    RAIN_DURATION = "RAIN_DURATION"
    GAUGE_FILE = "GAUGE_FILE"
    TS_FILE = "TS_FILE"

    # Runoff
    RUNOFF_SOURCE = "RUNOFF_SOURCE"
    VSA_SD_MAX = "VSA_SD_MAX"
    VSA_Q_MAX = "VSA_Q_MAX"
    VSA_PHI = "VSA_PHI"
    VSA_K_SAT = "VSA_K_SAT"
    INFILTRATION_EXCESS = "INFILTRATION_EXCESS"
    IMPERVIOUS_SOURCE = "IMPERVIOUS_SOURCE"
    VSA_SD_SOURCE = "VSA_SD_SOURCE"
    CN_SOURCE = "RUNOFF_CN_SOURCE"
    CN_VALUE = "RUNOFF_CN"
    CN_PATH = "RUNOFF_CN_PATH"
    CN_AMC = "RUNOFF_CN_AMC"

    # Manning source
    MANNINGS_N_SOURCE = "MANNINGS_N_SOURCE"

    # Routing scheme / numerics
    ROUTING_SCHEME = "ROUTING_SCHEME"
    CHANNEL_ROUTING = "CHANNEL_ROUTING"
    ADAPTIVE_TIMESTEP = "ADAPTIVE_TIMESTEP"
    DIFFUSION_THETA = "DIFFUSION_THETA"
    DYNAMIC_FLUX_THETA = "DYNAMIC_FLUX_THETA"
    IMPLICIT_CFL_TARGET = "IMPLICIT_CFL_TARGET"
    MANNING_SLOPE_CAP = "MANNING_SLOPE_CAP"
    FLUX_LIMITER = "FLUX_LIMITER"
    RAIN_SNOW_ELEV_LOW = "RAIN_SNOW_ELEV_LOW"
    RAIN_SNOW_ELEV_HIGH = "RAIN_SNOW_ELEV_HIGH"

    # Scenario / GEE
    GEE_PROJECT = "GEE_PROJECT"
    EVENT_START_UTC = "EVENT_START_UTC"

    # Backend
    BACKEND = "BACKEND"

    # Output
    HYDROGRAPH_CSV = "HYDROGRAPH_CSV"

    _PRECIP_OPTIONS = ["uniform", "thiessen", "idw", "imerg_thiessen", "imerg_idw"]
    _RUNOFF_OPTIONS = ["none", "coefficient", "raster", "scs_cn", "physical"]
    _BACKEND_OPTIONS = ["cpu", "gpu"]
    _INFIL_EXCESS_OPTIONS = ["off", "on"]
    _IMPERVIOUS_OPTIONS = ["none", "lcz", "lulc", "raster"]
    _SD_SOURCE_OPTIONS = ["manual", "gee"]
    _MANNINGS_SOURCE_OPTIONS = ["scalar", "lulc", "lcz", "raster"]
    _CN_SOURCE_OPTIONS = ["scalar", "gee", "raster"]
    _CN_AMC_OPTIONS = ["i", "ii", "iii"]
    # Read from the core registry (append-only order), so enum indices saved in
    # existing models stay valid and new schemes appear automatically.
    _SCHEME_OPTIONS = core_choices(
        "ROUTING_SCHEME",
        ["kinematic", "diffusive", "muskingum", "dynamic", "diffusive_implicit"])

    def createInstance(self):  # noqa: N802
        return RoutingAlgorithm()

    def name(self):
        return "routing"

    def displayName(self):  # noqa: N802
        return "2. Routing (kinematic / diffusive / dynamic / implicit)"

    # No group: the algorithms sit directly under the MRRpy_plugin provider.
    def group(self):
        return ""

    def groupId(self):  # noqa: N802
        return ""

    def shortHelpString(self):  # noqa: N802
        return (
            "Routes rainfall-runoff over the watershed grid and writes the outlet "
            "hydrograph CSV.  Schemes: kinematic wave, diffusive wave "
            "(CASC2D/GSSHA), Muskingum–Cunge, dynamic wave (local-inertial, "
            "LISFLOOD-FP) and a semi-implicit diffusive wave (HEC-RAS-style, "
            "unconditionally stable — use a larger time step; CPU only).  "
            "Supports CPU and GPU (CuPy/CUDA) backends.\n\n"
            "Run DEM Pre-processing first to generate the required input rasters."
        )

    def initAlgorithm(self, config=None):  # noqa: N802
        # ── Raster inputs ─────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterRasterLayer(self.DEM_TIF, "Clipped DEM"))
        self.addParameter(QgsProcessingParameterRasterLayer(self.FLOW_DIR_TIF, "Flow direction raster"))
        self.addParameter(QgsProcessingParameterRasterLayer(self.FLOW_ACCUM_TIF, "Flow accumulation raster"))
        self.addParameter(QgsProcessingParameterRasterLayer(self.WATERSHED_TIF, "Watershed mask raster"))

        # ── Routing parameters ────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterNumber(
            self.MANNINGS_N, "Manning's n",
            type=QgsProcessingParameterNumber.Double, defaultValue=0.09,
            minValue=0.001, maxValue=1.0
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.TIME_STEP, "Time step (seconds; initial Δt when adaptive)",
            type=QgsProcessingParameterNumber.Double, defaultValue=5,
            minValue=0.001, maxValue=3600
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.SIM_HOURS, "Simulation duration (hours)",
            type=QgsProcessingParameterNumber.Double, defaultValue=144.0,
            minValue=0.1
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.OUT_INTERVAL, "Output interval (seconds)",
            type=QgsProcessingParameterNumber.Integer, defaultValue=600,
            minValue=1
        ))

        # ── Precipitation ─────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterEnum(
            self.PRECIP_METHOD, "Precipitation method",
            options=self._PRECIP_OPTIONS, defaultValue=0
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.RAIN_INTENSITY, "Uniform rain intensity (mm/hr)",
            type=QgsProcessingParameterNumber.Double, defaultValue=20.0,
            minValue=0.0, optional=True
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.RAIN_DURATION, "Uniform rain duration (hours)",
            type=QgsProcessingParameterNumber.Double, defaultValue=3.0,
            minValue=0.0, optional=True
        ))
        self.addParameter(QgsProcessingParameterString(
            self.GAUGE_FILE, "Gauge metadata CSV path",
            defaultValue="", optional=True
        ))
        self.addParameter(QgsProcessingParameterString(
            self.TS_FILE, "Timeseries CSV path",
            defaultValue="", optional=True
        ))

        # ── Runoff ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterEnum(
            self.RUNOFF_SOURCE, "Runoff source",
            options=self._RUNOFF_OPTIONS, defaultValue=4  # physical
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.VSA_SD_MAX, "Saturation-excess SD_max initial (m)",
            type=QgsProcessingParameterNumber.Double, defaultValue=0.10,
            minValue=0.001, optional=True
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.VSA_Q_MAX, "Saturation-excess Q_max (m³/s)",
            type=QgsProcessingParameterNumber.Double, defaultValue=0.50,
            minValue=0.002, optional=True
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.VSA_PHI, "Saturation-excess phi (porosity)",
            type=QgsProcessingParameterNumber.Double, defaultValue=0.35,
            minValue=0.01, maxValue=0.99, optional=True
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.VSA_K_SAT, "Saturation-excess K_sat lateral (m/day)",
            type=QgsProcessingParameterNumber.Double, defaultValue=44.0,
            minValue=0.001, optional=True
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.INFILTRATION_EXCESS, "Infiltration-excess mechanism (Green-Ampt)",
            options=self._INFIL_EXCESS_OPTIONS, defaultValue=0  # off
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.IMPERVIOUS_SOURCE, "Impervious fraction source (needs GEE for lcz/lulc)",
            options=self._IMPERVIOUS_OPTIONS, defaultValue=0  # none
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.VSA_SD_SOURCE, "SD_max / phi source (gee = SERVES, needs GEE)",
            options=self._SD_SOURCE_OPTIONS, defaultValue=0  # manual
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.CN_SOURCE, "SCS-CN: curve-number source (gee = GCN250, needs GEE)",
            options=self._CN_SOURCE_OPTIONS, defaultValue=0  # scalar
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.CN_VALUE, "SCS-CN: curve number (scalar / raster nodata fill)",
            type=QgsProcessingParameterNumber.Double, defaultValue=75.0,
            minValue=1.0, maxValue=100.0, optional=True
        ))
        self.addParameter(QgsProcessingParameterFile(
            self.CN_PATH, "SCS-CN: curve-number GeoTIFF (raster source)",
            extension="tif", optional=True
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.CN_AMC, "SCS-CN: antecedent moisture condition",
            options=["I (dry)", "II (normal)", "III (wet)"], defaultValue=1
        ))

        # ── Manning source ────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterEnum(
            self.MANNINGS_N_SOURCE, "Manning's n source (needs GEE for lulc/lcz)",
            options=self._MANNINGS_SOURCE_OPTIONS, defaultValue=0  # scalar
        ))

        # ── Routing scheme / numerics ─────────────────────────────────────────
        self.addParameter(QgsProcessingParameterEnum(
            self.ROUTING_SCHEME, "Routing scheme",
            options=self._SCHEME_OPTIONS, defaultValue=1  # diffusive
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.CHANNEL_ROUTING, "Confined channel cross-section routing",
            defaultValue=True
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.ADAPTIVE_TIMESTEP, "Adaptive CFL timestep",
            defaultValue=True
        ))

        # ── Advanced (scheme-specific numerics, optional physics) ─────────────
        self._add_advanced(QgsProcessingParameterNumber(
            self.DIFFUSION_THETA, "Diffusive: diffusion weight θ (0 ≈ kinematic, 1 = full)",
            type=QgsProcessingParameterNumber.Double, defaultValue=1.0,
            minValue=0.0, maxValue=1.0
        ))
        self._add_advanced(QgsProcessingParameterNumber(
            self.DYNAMIC_FLUX_THETA, "Dynamic: de Almeida flux-centering θ (0.7–0.9 damps oscillation)",
            type=QgsProcessingParameterNumber.Double, defaultValue=0.8,
            minValue=0.0, maxValue=1.0
        ))
        self._add_advanced(QgsProcessingParameterNumber(
            self.IMPLICIT_CFL_TARGET, "Semi-implicit: adaptive Courant target (>1 allowed)",
            type=QgsProcessingParameterNumber.Double, defaultValue=2.0,
            minValue=0.1, maxValue=1000.0
        ))
        self._add_advanced(QgsProcessingParameterNumber(
            self.MANNING_SLOPE_CAP, "Manning friction-slope cap, m/m (0 = off; 0.05–0.10 for steep terrain)",
            type=QgsProcessingParameterNumber.Double, defaultValue=0.0,
            minValue=0.0
        ))
        self._add_advanced(QgsProcessingParameterBoolean(
            self.FLUX_LIMITER, "Volume-conservative flux limiter (kinematic/diffusive)",
            defaultValue=True
        ))
        self._add_advanced(QgsProcessingParameterNumber(
            self.RAIN_SNOW_ELEV_LOW, "Rain/snow: all rain below elevation (m; blank = off)",
            type=QgsProcessingParameterNumber.Double, optional=True
        ))
        self._add_advanced(QgsProcessingParameterNumber(
            self.RAIN_SNOW_ELEV_HIGH, "Rain/snow: all snow above elevation (m; blank = off)",
            type=QgsProcessingParameterNumber.Double, optional=True
        ))

        # ── Scenario / GEE ────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterString(
            self.GEE_PROJECT, "GEE project ID (for IMERG / SERVES / LULC / LCZ)",
            defaultValue="", optional=True
        ))
        self.addParameter(QgsProcessingParameterString(
            self.EVENT_START_UTC, "Event start UTC 'YYYY-MM-DD HH:MM' (IMERG/SERVES)",
            defaultValue="", optional=True
        ))

        # ── Backend ───────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterEnum(
            self.BACKEND, "Compute backend",
            options=self._BACKEND_OPTIONS, defaultValue=0  # cpu
        ))

        # ── Output ────────────────────────────────────────────────────────────
        self.addParameter(QgsProcessingParameterFileDestination(
            self.HYDROGRAPH_CSV, "Output hydrograph CSV",
            fileFilter="CSV files (*.csv)"
        ))

    def _add_advanced(self, param):
        """Add *param* under the dialog's collapsed "Advanced parameters" section."""
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)

    def _optional_double(self, parameters, name, context):
        """Value of an optional numeric parameter, or None when left blank."""
        if parameters.get(name) in (None, ""):
            return None
        return self.parameterAsDouble(parameters, name, context)

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        # ── Redirect stdout/stderr to QGIS Processing log ─────────────────────
        # QGIS Processing sets sys.stdout/stderr to None.
        # We replace them with a thin wrapper that forwards every print() call
        # from the model to feedback.pushInfo()
        # so users see full model output in the Processing log panel.
        import io

        class _FeedbackWriter(io.TextIOBase):
            """Forwards write() calls to QgsProcessingFeedback.pushInfo()."""
            def __init__(self, fb):
                super().__init__()
                self._fb = fb
                self._buf = ""
            def write(self, text):
                self._buf += text
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    self._fb.pushInfo(line)
                return len(text)
            def flush(self):
                if self._buf:
                    self._fb.pushInfo(self._buf)
                    self._buf = ""

        _orig_stdout = sys.stdout
        _orig_stderr = sys.stderr
        sys.stdout = _FeedbackWriter(feedback)
        sys.stderr = _FeedbackWriter(feedback)

        ensure_core()

        from MRRpy.config import Config
        from MRRpy.core.routing import router as kwr

        # ── Build config ──────────────────────────────────────────────────────
        cfg = Config()

        def _rpath(param_id):
            lyr = self.parameterAsRasterLayer(parameters, param_id, context)
            return lyr.source() if lyr else parameters.get(param_id, "")

        cfg.ROUTING_DEM_PATH = _rpath(self.DEM_TIF)
        cfg.ROUTING_FLOW_DIR_PATH = _rpath(self.FLOW_DIR_TIF)
        cfg.ROUTING_FLOW_ACCUM_PATH = _rpath(self.FLOW_ACCUM_TIF)
        cfg.ROUTING_WATERSHED_MASK_PATH = _rpath(self.WATERSHED_TIF)

        cfg.MANNINGS_N = self.parameterAsDouble(parameters, self.MANNINGS_N, context)
        cfg.TIME_STEP_SECONDS = self.parameterAsDouble(parameters, self.TIME_STEP, context)
        cfg.TOTAL_SIMULATION_TIME_HOURS = self.parameterAsDouble(parameters, self.SIM_HOURS, context)
        cfg.OUTPUT_INTERVAL_SECONDS = self.parameterAsInt(parameters, self.OUT_INTERVAL, context)

        cfg.PRECIP_METHOD = self._PRECIP_OPTIONS[
            self.parameterAsEnum(parameters, self.PRECIP_METHOD, context)
        ]
        cfg.RAIN_INTENSITY_MM_HR = self.parameterAsDouble(parameters, self.RAIN_INTENSITY, context)
        cfg.RAIN_DURATION_HOURS = self.parameterAsDouble(parameters, self.RAIN_DURATION, context)
        cfg.PRECIP_GAUGE_FILE = self.parameterAsString(parameters, self.GAUGE_FILE, context)
        cfg.PRECIP_TIMESERIES_FILE = self.parameterAsString(parameters, self.TS_FILE, context)

        cfg.RUNOFF_SOURCE = self._RUNOFF_OPTIONS[
            self.parameterAsEnum(parameters, self.RUNOFF_SOURCE, context)
        ]
        cfg.VSA_SD_MAX_INITIAL = self.parameterAsDouble(parameters, self.VSA_SD_MAX, context)
        cfg.VSA_Q_MAX = self.parameterAsDouble(parameters, self.VSA_Q_MAX, context)
        cfg.VSA_PHI = self.parameterAsDouble(parameters, self.VSA_PHI, context)
        cfg.VSA_K_SAT = self.parameterAsDouble(parameters, self.VSA_K_SAT, context)
        cfg.IMPERVIOUS_SOURCE = self._IMPERVIOUS_OPTIONS[
            self.parameterAsEnum(parameters, self.IMPERVIOUS_SOURCE, context)
        ]
        cfg.VSA_SD_SOURCE = self._SD_SOURCE_OPTIONS[
            self.parameterAsEnum(parameters, self.VSA_SD_SOURCE, context)
        ]
        cfg.RUNOFF_CN_SOURCE = self._CN_SOURCE_OPTIONS[
            self.parameterAsEnum(parameters, self.CN_SOURCE, context)
        ]
        _cn = self._optional_double(parameters, self.CN_VALUE, context)
        if _cn is not None:
            cfg.RUNOFF_CN = _cn
        cfg.RUNOFF_CN_PATH = self.parameterAsFile(parameters, self.CN_PATH, context) or ""
        cfg.RUNOFF_CN_AMC = self._CN_AMC_OPTIONS[
            self.parameterAsEnum(parameters, self.CN_AMC, context)
        ]

        # Compose the physical-runoff mechanisms from the toggles above:
        # saturation-excess (this OPM router) + infiltration-excess (if on) +
        # impervious (if a source is selected).
        _infil_on = self.parameterAsEnum(
            parameters, self.INFILTRATION_EXCESS, context) == 1
        _mechs = ["saturation_excess"]
        if _infil_on:
            _mechs.append("infiltration_excess")
        if cfg.IMPERVIOUS_SOURCE != "none":
            _mechs.append("impervious")
        cfg.RUNOFF_MECHANISMS = _mechs

        cfg.MANNINGS_N_SOURCE = self._MANNINGS_SOURCE_OPTIONS[
            self.parameterAsEnum(parameters, self.MANNINGS_N_SOURCE, context)
        ]

        cfg.ROUTING_SCHEME = self._SCHEME_OPTIONS[
            self.parameterAsEnum(parameters, self.ROUTING_SCHEME, context)
        ]
        cfg.CHANNEL_ROUTING = self.parameterAsBool(parameters, self.CHANNEL_ROUTING, context)
        cfg.ADAPTIVE_TIMESTEP = self.parameterAsBool(parameters, self.ADAPTIVE_TIMESTEP, context)
        cfg.DIFFUSION_THETA = self.parameterAsDouble(parameters, self.DIFFUSION_THETA, context)
        cfg.DYNAMIC_FLUX_THETA = self.parameterAsDouble(parameters, self.DYNAMIC_FLUX_THETA, context)
        cfg.IMPLICIT_CFL_TARGET = self.parameterAsDouble(parameters, self.IMPLICIT_CFL_TARGET, context)
        cfg.MANNING_SLOPE_CAP = (
            self.parameterAsDouble(parameters, self.MANNING_SLOPE_CAP, context) or None)
        cfg.FLUX_LIMITER = self.parameterAsBool(parameters, self.FLUX_LIMITER, context)
        cfg.RAIN_SNOW_ELEV_LOW = self._optional_double(parameters, self.RAIN_SNOW_ELEV_LOW, context)
        cfg.RAIN_SNOW_ELEV_HIGH = self._optional_double(parameters, self.RAIN_SNOW_ELEV_HIGH, context)

        _proj = self.parameterAsString(parameters, self.GEE_PROJECT, context).strip()
        cfg.GEE_PROJECT = _proj or None
        _evt = self.parameterAsString(parameters, self.EVENT_START_UTC, context).strip()
        cfg.EVENT_START_UTC = _evt or None

        cfg.BACKEND = self._BACKEND_OPTIONS[
            self.parameterAsEnum(parameters, self.BACKEND, context)
        ]

        hyd_csv = self.parameterAsFileOutput(parameters, self.HYDROGRAPH_CSV, context)
        cfg.HYDROGRAPH_CSV = hyd_csv
        cfg.OUTPUT_DIR = os.path.dirname(hyd_csv)

        # Save the raster paths that were explicitly set from QGIS parameters
        # BEFORE calling update_output_paths(), which would overwrite them.
        _dem       = cfg.ROUTING_DEM_PATH
        _fdir      = cfg.ROUTING_FLOW_DIR_PATH
        _faccum    = cfg.ROUTING_FLOW_ACCUM_PATH
        _watershed = cfg.ROUTING_WATERSHED_MASK_PATH

        cfg.update_output_paths()

        # Restore the QGIS-supplied raster paths
        cfg.ROUTING_DEM_PATH            = _dem
        cfg.ROUTING_FLOW_DIR_PATH       = _fdir
        cfg.ROUTING_FLOW_ACCUM_PATH     = _faccum
        cfg.ROUTING_WATERSHED_MASK_PATH = _watershed
        cfg.HYDROGRAPH_CSV              = hyd_csv

        # ── Run (stdout/stderr forwarded to Processing log) ───────────────────
        try:
            feedback.setProgress(5)
            grid_data = kwr.initialise_grid(cfg)

            feedback.setProgress(20)
            hydrograph = kwr.run_time_loop(grid_data, cfg)

            feedback.setProgress(90)
            kwr.save_hydrograph(hydrograph, cfg)

        finally:
            # Always restore stdout/stderr
            sys.stdout = _orig_stdout
            sys.stderr = _orig_stderr

        # ── Auto-load outputs into the QGIS map canvas ────────────────────────
        from qgis.core import QgsProcessingContext, QgsProject

        if hyd_csv and os.path.exists(hyd_csv):
            details = QgsProcessingContext.LayerDetails(
                "Hydrograph", QgsProject.instance(), self.HYDROGRAPH_CSV
            )
            context.addLayerToLoadOnCompletion(hyd_csv, details)

        # Also auto-load any raster outputs routing may produce
        routing_rasters = {
            "Routed Flow Depth": os.path.join(cfg.OUTPUT_DIR, "flow_depth.tif"),
            "Routed Velocity":   os.path.join(cfg.OUTPUT_DIR, "velocity.tif"),
        }
        for name, path in routing_rasters.items():
            if os.path.exists(path):
                details = QgsProcessingContext.LayerDetails(
                    name, QgsProject.instance(), name.replace(" ", "_")
                )
                context.addLayerToLoadOnCompletion(path, details)

        feedback.setProgress(100)
        feedback.pushInfo(f"\nRouting complete ({cfg.ROUTING_SCHEME}).")
        return {self.HYDROGRAPH_CSV: hyd_csv}
