# -*- coding: utf-8 -*-
"""
alg_nepal.py
============
QGIS Processing algorithms of MRRpy-Nepal:

``mrrpy_plugin:nepal_flood_estimates`` — "3. Nepal flood estimates (official methods)"
    The official Nepali flood methods for a catchment (the results folder of
    "1. DEM Pre-processing", or typed numbers): choose the manual (its
    methods are ticked) and the structure (its return periods), tick any
    other methods or return periods, and optionally run the MRRpy physics
    model with a design storm.  Writes nepal_flood_estimates.csv, a chart
    and a Markdown report, and prints the table in the log.

``mrrpy_plugin:nepal_design_storm`` — "4. Nepal design storm (rain-gauge CSVs)"
    A design storm from the T-year 24-hour rainfall (Mononobe curve,
    alternating blocks), written as the two rain-gauge CSVs the main dialog's
    Precipitation tab reads with Thiessen.

All the science is in MRRpy.nepal; the option mapping is in nepal_options.py.
"""

import io
import os
import sys

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingOutputFile,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProject,
)

from ..bridge import ensure_core


class _FeedbackWriter(io.TextIOBase):
    """Forwards print() output of the model to the Processing log."""

    def __init__(self, feedback):
        super().__init__()
        self._fb = feedback
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


def _options():
    """(nepal_options module, None) — or (None, reason) when the core can't load yet
    (e.g. its dependencies are not installed in this QGIS)."""
    try:
        ensure_core()
        from . import nepal_options
        return nepal_options, None
    except Exception as exc:              # noqa: BLE001 — shown in the dialog instead
        return None, str(exc)


class _Base(QgsProcessingAlgorithm):
    _unavailable = None

    def group(self):
        return ""

    def groupId(self):  # noqa: N802
        return ""

    def _core_missing(self):
        """Show why the dialog has no options (the core could not load)."""
        self._unavailable = (
            "The MRRpy core could not be loaded, so this tool has no options yet. Open the "
            "MRRpy_plugin dialog to install the missing packages, then restart QGIS.")
        self.addParameter(QgsProcessingParameterString(
            "UNAVAILABLE", self._unavailable, optional=True))

    def _check_available(self):
        if self._unavailable:
            from qgis.core import QgsProcessingException
            raise QgsProcessingException(self._unavailable)

    def _add_advanced(self, param):
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)

    def _number(self, parameters, name, context):
        """An optional number: None when left blank."""
        if parameters.get(name) in (None, ""):
            return None
        return self.parameterAsDouble(parameters, name, context)

    @staticmethod
    def _redirect(feedback):
        saved = (sys.stdout, sys.stderr)
        sys.stdout = sys.stderr = _FeedbackWriter(feedback)
        return saved


class NepalFloodEstimatesAlgorithm(_Base):
    """The official Nepali flood methods (and the physics model) for one catchment."""

    RESULTS_DIR = "RESULTS_DIR"
    AREA = "AREA"
    AREA_BELOW_3000 = "AREA_BELOW_3000"
    AREA_BELOW_5000 = "AREA_BELOW_5000"
    SNOW_AREA = "SNOW_AREA"
    LENGTH_KM = "LENGTH_KM"
    SLOPE = "SLOPE"
    SITE_NAME = "SITE_NAME"
    AGENCY = "AGENCY"
    METHODS = "METHODS"
    STRUCTURE = "STRUCTURE"
    RETURN_PERIODS = "RETURN_PERIODS"
    MHSP_REGION = "MHSP_REGION"
    RUNOFF_COEFF = "RUNOFF_COEFF"
    RAIN_24H = "RAIN_24H"
    RAIN_SERIES = "RAIN_SERIES"
    RAIN_DIST = "RAIN_DIST"
    FLOOD_SERIES = "FLOOD_SERIES"
    FLOOD_DIST = "FLOOD_DIST"
    DONOR_AREA = "DONOR_AREA"
    DONOR_FLOODS = "DONOR_FLOODS"
    DONOR_SERIES = "DONOR_SERIES"
    AREA_EXPONENT = "AREA_EXPONENT"
    RUN_PHYSICS = "RUN_PHYSICS"
    CURVE_NUMBER = "CURVE_NUMBER"
    PHYSICS_T = "PHYSICS_T"
    STORM_DURATION = "STORM_DURATION"
    CLIMATE_FACTOR = "CLIMATE_FACTOR"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    OUTPUT_CSV = "OUTPUT_CSV"
    OUTPUT_REPORT = "OUTPUT_REPORT"
    OUTPUT_CHART = "OUTPUT_CHART"

    def createInstance(self):  # noqa: N802
        return NepalFloodEstimatesAlgorithm()

    def name(self):
        return "nepal_flood_estimates"

    def displayName(self):  # noqa: N802
        return "3. Nepal flood estimates (official methods)"

    def shortHelpString(self):  # noqa: N802
        return (
            "Flood estimates for one catchment by the official Nepali methods — WECS/DHM 1990 "
            "(HYDEST), DHM 2004 (Sharma & Adhikari), MHSP 1997, Modified Dickens, specific "
            "discharge (WECS 2019), the Rational method, frequency analysis at a gauge and the "
            "catchment area ratio — side by side, with the range of the official methods and a "
            "validity flag for each.\n\n"
            "Catchment: the results folder of '1. DEM Pre-processing' (the area below 3,000 m, "
            "the snow area, the flow length and slope are measured from the DEM), or the typed "
            "numbers.\n\n"
            "Manual: ticks the methods that manual names (DoWRI, DoLIDAR, DoED, WECS, DoR, …). "
            "Methods: tick any to replace that list. Structure: ticks its design return "
            "period (bridge 100, culvert 25, weir 50–100, …); Return periods: tick any to "
            "replace them.\n\n"
            "Physics model: with a results folder and a 24-hour design rainfall, the MRRpy model "
            "is run with a design storm (Mononobe curve) for the design return period.\n\n"
            "Coefficients come from the compendium 'Nepal Flood Estimation Methods'; see the "
            "report for each method's notes.")

    def initAlgorithm(self, config=None):  # noqa: N802
        o, _why = _options()
        if o is None:
            self._core_missing()
            return

        self.addParameter(QgsProcessingParameterFile(
            self.RESULTS_DIR, "Results folder of '1. DEM Pre-processing' (empty: type the numbers)",
            behavior=QgsProcessingParameterFile.Folder, optional=True))
        for pid, label in ((self.AREA, "…or typed catchment area A (km²)"),
                           (self.AREA_BELOW_3000, "Typed area below 3,000 m (km², empty = all)"),
                           (self.AREA_BELOW_5000, "Typed area below 5,000 m (km², empty = all)"),
                           (self.SNOW_AREA, "Typed permanent-snow area (km², empty = 0)"),
                           (self.LENGTH_KM, "Typed longest flow path L (km, Rational only)"),
                           (self.SLOPE, "Typed slope of L (m/m, Rational only)")):
            p = QgsProcessingParameterNumber(pid, label, type=QgsProcessingParameterNumber.Double,
                                             optional=True, minValue=0.0)
            if pid == self.AREA:
                self.addParameter(p)
            else:
                self._add_advanced(p)
        self.addParameter(QgsProcessingParameterString(self.SITE_NAME, "Site name", optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.AGENCY, "Which manual or approach (ticks its methods)",
            options=o.labels(o.AGENCIES), defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(
            self.METHODS, "Methods (leave empty to use the manual's)",
            options=o.labels(o.METHODS), allowMultiple=True, optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.STRUCTURE, "What are you designing (ticks its return periods)",
            options=o.labels(o.STRUCTURES), defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(
            self.RETURN_PERIODS, "Return periods (leave empty to use the structure's)",
            options=o.labels(o.PERIODS), allowMultiple=True, optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.MHSP_REGION, "MHSP region (for MHSP 1997)", options=o.labels(o.REGIONS),
            defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.RUNOFF_COEFF, "Runoff coefficient C (Rational; 0.3 forest … 0.85 built-up)",
            type=QgsProcessingParameterNumber.Double, optional=True, minValue=0.0, maxValue=1.0))
        self.addParameter(QgsProcessingParameterString(
            self.RAIN_24H, "24-hour design rainfall R24, 'T=mm' pairs (e.g. 2=120, 100=250)",
            optional=True))
        self.addParameter(QgsProcessingParameterFile(
            self.RAIN_SERIES, "…or a CSV of annual maximum daily rainfall (mm)",
            extension="csv", optional=True))
        self._add_advanced(QgsProcessingParameterEnum(
            self.RAIN_DIST, "Distribution for the rainfall series",
            options=o.labels(o.DISTRIBUTIONS), defaultValue=0))
        self.addParameter(QgsProcessingParameterFile(
            self.FLOOD_SERIES, "CSV of annual maximum floods at the site (frequency analysis)",
            extension="csv", optional=True))
        self._add_advanced(QgsProcessingParameterEnum(
            self.FLOOD_DIST, "Distribution for flood series", options=o.labels(o.DISTRIBUTIONS),
            defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.DONOR_AREA, "Donor gauge catchment area (km², catchment area ratio)",
            type=QgsProcessingParameterNumber.Double, optional=True, minValue=0.0))
        self.addParameter(QgsProcessingParameterString(
            self.DONOR_FLOODS, "Donor design floods, 'T=m³/s' pairs", optional=True))
        self._add_advanced(QgsProcessingParameterFile(
            self.DONOR_SERIES, "…or a CSV of the donor's annual maximum floods", extension="csv",
            optional=True))
        self._add_advanced(QgsProcessingParameterNumber(
            self.AREA_EXPONENT, "Area-ratio exponent n", type=QgsProcessingParameterNumber.Double,
            defaultValue=0.8, minValue=0.0, maxValue=1.0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.RUN_PHYSICS, "Also run the MRRpy physics model with a design storm", defaultValue=False))
        self._add_advanced(QgsProcessingParameterNumber(
            self.CURVE_NUMBER, "Physics model: SCS curve number", type=QgsProcessingParameterNumber.Double,
            defaultValue=75.0, minValue=1.0, maxValue=100.0))
        self._add_advanced(QgsProcessingParameterString(
            self.PHYSICS_T, "Physics model: return periods to simulate (empty = design)", optional=True))
        self._add_advanced(QgsProcessingParameterNumber(
            self.STORM_DURATION, "Physics model: storm duration (h)",
            type=QgsProcessingParameterNumber.Double, defaultValue=24.0, minValue=0.25))
        self._add_advanced(QgsProcessingParameterNumber(
            self.CLIMATE_FACTOR, "Physics model: climate factor on R24",
            type=QgsProcessingParameterNumber.Double, defaultValue=1.0, minValue=0.1))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Folder for the table, chart and report"))
        self.addOutput(QgsProcessingOutputFile(self.OUTPUT_CSV, "Flood estimates CSV"))
        self.addOutput(QgsProcessingOutputFile(self.OUTPUT_REPORT, "Report (Markdown)"))
        self.addOutput(QgsProcessingOutputFile(self.OUTPUT_CHART, "Chart (PNG)"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        self._check_available()
        saved = self._redirect(feedback)
        try:
            ensure_core()
            from MRRpy.nepal.cli import format_table
            from . import nepal_options as o

            out_dir = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
            values = {
                "results_dir": self.parameterAsFile(parameters, self.RESULTS_DIR, context),
                "area": self._number(parameters, self.AREA, context),
                "area_below_3000": self._number(parameters, self.AREA_BELOW_3000, context),
                "area_below_5000": self._number(parameters, self.AREA_BELOW_5000, context),
                "snow_area": self._number(parameters, self.SNOW_AREA, context),
                "length_km": self._number(parameters, self.LENGTH_KM, context),
                "slope": self._number(parameters, self.SLOPE, context),
                "site_name": self.parameterAsString(parameters, self.SITE_NAME, context),
                "agency": o.key(o.AGENCIES, self.parameterAsEnum(parameters, self.AGENCY, context)),
                "methods": o.keys(o.METHODS, self.parameterAsEnums(parameters, self.METHODS, context)),
                "structure": o.key(o.STRUCTURES,
                                   self.parameterAsEnum(parameters, self.STRUCTURE, context)),
                "return_periods": o.keys(o.PERIODS, self.parameterAsEnums(
                    parameters, self.RETURN_PERIODS, context)),
                "mhsp_region": o.key(o.REGIONS,
                                     self.parameterAsEnum(parameters, self.MHSP_REGION, context)),
                "runoff_coefficient": self._number(parameters, self.RUNOFF_COEFF, context),
                "rain_24h": self.parameterAsString(parameters, self.RAIN_24H, context),
                "rain_series": self.parameterAsFile(parameters, self.RAIN_SERIES, context),
                "rain_distribution": o.key(o.DISTRIBUTIONS, self.parameterAsEnum(
                    parameters, self.RAIN_DIST, context)),
                "flood_series": self.parameterAsFile(parameters, self.FLOOD_SERIES, context),
                "flood_distribution": o.key(o.DISTRIBUTIONS, self.parameterAsEnum(
                    parameters, self.FLOOD_DIST, context)),
                "donor_area": self._number(parameters, self.DONOR_AREA, context),
                "donor_floods": self.parameterAsString(parameters, self.DONOR_FLOODS, context),
                "donor_series": self.parameterAsFile(parameters, self.DONOR_SERIES, context),
                "area_exponent": self._number(parameters, self.AREA_EXPONENT, context),
                "curve_number": self._number(parameters, self.CURVE_NUMBER, context),
                "physics_T": self.parameterAsString(parameters, self.PHYSICS_T, context),
                "storm_duration": self._number(parameters, self.STORM_DURATION, context),
                "climate_factor": self._number(parameters, self.CLIMATE_FACTOR, context),
                "output_dir": out_dir,
            }
            physics = self.parameterAsBool(parameters, self.RUN_PHYSICS, context)
            study = o.build_study(values)
            feedback.setProgress(5)
            result = study.run(physics=True if physics else False, save=False,
                               log=feedback.pushInfo)
            feedback.setProgress(90)
            files = result.save(out_dir)
        finally:
            sys.stdout, sys.stderr = saved

        feedback.pushInfo("")
        feedback.pushInfo(result.descriptors.summary())
        for line in format_table(result.estimates).splitlines():
            feedback.pushInfo(line)
        for line in result.summary_lines()[1:]:
            feedback.pushInfo(line)
        for w in result.warnings():
            feedback.reportError(f"Warning: {w}", fatalError=False)
        details = QgsProcessingContext.LayerDetails("Nepal flood estimates", QgsProject.instance(),
                                                    self.OUTPUT_CSV)
        context.addLayerToLoadOnCompletion(files["table"], details)
        feedback.setProgress(100)
        feedback.pushInfo(f"\nWritten: {', '.join(files.values())}")
        return {self.OUTPUT_FOLDER: out_dir, self.OUTPUT_CSV: files["table"],
                self.OUTPUT_REPORT: files["report"], self.OUTPUT_CHART: files.get("chart", "")}


class NepalDesignStormAlgorithm(_Base):
    """A design storm as rain-gauge CSVs for the main dialog (Precipitation → Thiessen)."""

    RAIN_24H = "RAIN_24H"
    DURATION = "DURATION"
    STEP = "STEP"
    PATTERN = "PATTERN"
    AREAL_REDUCTION = "AREAL_REDUCTION"
    CLIMATE_FACTOR = "CLIMATE_FACTOR"
    SIM_HOURS = "SIM_HOURS"
    RESULTS_DIR = "RESULTS_DIR"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    GAUGE_CSV = "GAUGE_CSV"
    RAIN_CSV = "RAIN_CSV"
    HYETOGRAPH_CSV = "HYETOGRAPH_CSV"

    def createInstance(self):  # noqa: N802
        return NepalDesignStormAlgorithm()

    def name(self):
        return "nepal_design_storm"

    def displayName(self):  # noqa: N802
        return "4. Nepal design storm (rain-gauge CSVs)"

    def shortHelpString(self):  # noqa: N802
        return (
            "A design storm from the T-year 24-hour rainfall R24 (DHM data), spread in time "
            "with the Mononobe curve — the rule the official Rational method uses — into a "
            "centre-peaked storm (alternating blocks), or a uniform one.\n\n"
            "Writes a gauge file and a rainfall file: choose them on the main dialog's "
            "Precipitation tab with Thiessen, and run the model for a physics-based design "
            "flood. With a results folder the gauge sits at the catchment outlet.")

    def initAlgorithm(self, config=None):  # noqa: N802
        o, _why = _options()
        if o is None:
            self._core_missing()
            return
        self.addParameter(QgsProcessingParameterNumber(
            self.RAIN_24H, "T-year 24-hour design rainfall R24 (mm)",
            type=QgsProcessingParameterNumber.Double, defaultValue=250.0, minValue=0.1))
        self.addParameter(QgsProcessingParameterNumber(
            self.DURATION, "Storm duration (h)", type=QgsProcessingParameterNumber.Double,
            defaultValue=24.0, minValue=0.25))
        self.addParameter(QgsProcessingParameterNumber(
            self.STEP, "Time step (min; must divide the duration)",
            type=QgsProcessingParameterNumber.Double, defaultValue=15.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.PATTERN, "Time pattern", options=o.labels(o.PATTERNS), defaultValue=0))
        self._add_advanced(QgsProcessingParameterNumber(
            self.AREAL_REDUCTION, "Areal reduction factor (1 = none)",
            type=QgsProcessingParameterNumber.Double, defaultValue=1.0, minValue=0.01, maxValue=1.0))
        self._add_advanced(QgsProcessingParameterNumber(
            self.CLIMATE_FACTOR, "Climate factor (e.g. 1.1 for +10 %)",
            type=QgsProcessingParameterNumber.Double, defaultValue=1.0, minValue=0.1))
        self._add_advanced(QgsProcessingParameterNumber(
            self.SIM_HOURS, "Pad the rain file with zeros to (h)",
            type=QgsProcessingParameterNumber.Double, optional=True, minValue=0.0))
        self.addParameter(QgsProcessingParameterFile(
            self.RESULTS_DIR, "Results folder (puts the gauge at the outlet; optional)",
            behavior=QgsProcessingParameterFile.Folder, optional=True))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Folder for the storm files"))
        self.addOutput(QgsProcessingOutputFile(self.GAUGE_CSV, "Rain-gauge locations CSV"))
        self.addOutput(QgsProcessingOutputFile(self.RAIN_CSV, "Rainfall time-series CSV"))
        self.addOutput(QgsProcessingOutputFile(self.HYETOGRAPH_CSV, "Hyetograph table CSV"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        self._check_available()
        saved = self._redirect(feedback)
        try:
            ensure_core()
            from MRRpy.nepal import design_storm as ds
            from . import nepal_options as o
            r24 = self.parameterAsDouble(parameters, self.RAIN_24H, context)
            duration = self.parameterAsDouble(parameters, self.DURATION, context)
            step = self.parameterAsDouble(parameters, self.STEP, context)
            pattern = o.key(o.PATTERNS, self.parameterAsEnum(parameters, self.PATTERN, context))
            depth = ds.design_depth(r24, self.parameterAsDouble(parameters, self.AREAL_REDUCTION, context),
                                    self.parameterAsDouble(parameters, self.CLIMATE_FACTOR, context))
            hyeto = ds.design_hyetograph(depth, duration, step, pattern)
            folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
            x = y = 0.0
            results = self.parameterAsFile(parameters, self.RESULTS_DIR, context)
            if results:
                from MRRpy.nepal import measure_catchment
                x, y = measure_catchment(results).outlet_xy
            gauge, rain = ds.write_storm_files(hyeto, folder, x, y,
                                               sim_hours=self._number(parameters, self.SIM_HOURS, context),
                                               name=f"design storm {depth:.0f} mm")
            hyeto_csv = os.path.join(folder, "hyetograph.csv")
            hyeto.to_csv(hyeto_csv, index=False)
        finally:
            sys.stdout, sys.stderr = saved
        feedback.pushInfo(f"Design storm: {hyeto['rain_mm'].sum():.1f} mm in {duration:g} h, peak "
                          f"{hyeto['intensity_mm_h'].max():.1f} mm/h ({pattern}).")
        feedback.pushInfo(f"On the Precipitation tab choose Thiessen, the gauge file {gauge} and "
                          f"the rainfall file {rain}; set the simulation longer than {duration:g} h.")
        return {self.OUTPUT_FOLDER: folder, self.GAUGE_CSV: gauge, self.RAIN_CSV: rain,
                self.HYETOGRAPH_CSV: hyeto_csv}
