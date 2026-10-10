# -*- coding: utf-8 -*-
"""
config_schema.py
================
The human-facing catalogue of every ``Config`` parameter: a plain-language
label and explanation, unit, input kind, section, basic/advanced level, and
*when it matters* (e.g. ``RAIN_INTENSITY_MM_HR`` only for a uniform storm).

One catalogue drives every interactive front-end, so they always agree:

* the terminal wizard          — ``MRRpy wizard``           (MRRpy/interactive/wizard.py)
* the Jupyter form             — ``MRRpy.ConfigForm()``     (MRRpy/interactive/form.py)
* the commented YAML template  — ``MRRpy init-config``      (MRRpy/interactive/render.py)
* parameter help               — ``MRRpy explain NAME``

Defaults and fixed choices are deliberately *not* repeated here — they are
read from ``Config`` and ``config._ENUM_CHOICES`` — so this file can't drift
from the model.  ``tests/test_config_schema.py`` fails when a ``Config``
attribute is missing from the catalogue (or from ``NOT_ASKED``).

Adding a parameter
------------------
1. Add it to ``Config`` (MRRpy/config.py) as usual.
2. Add a ``P(...)`` entry below in the right section and position (the order
   is the order questions are asked), or list it in ``NOT_ASKED`` with the
   reason it should never be asked.
3. If it only matters for some settings, give it ``when=`` clauses.
"""

import ast
import datetime as _dt
import difflib
import os
import re

from .config import Config, _ENUM_CHOICES, _ENUM_LIST, _ENUM_NULLABLE
from .gee.dem_catalog import DEM_CATALOG as _DEM_CATALOG


# ═════════════════════════════════════════════════════════════════════════════
# Sections (the order of the wizard, the form tabs and the YAML template)
# ═════════════════════════════════════════════════════════════════════════════
class Section:
    def __init__(self, key, title, intro):
        self.key, self.title, self.intro = key, title, intro

    def __repr__(self):
        return f"Section({self.key!r})"


SECTIONS = [
    Section("project", "Basin, terrain and results folder",
            "Where your basin is, which elevation data to use, and where results go."),
    Section("rain", "Rainfall",
            "How much rain falls, where and when."),
    Section("runoff", "Runoff",
            "How the ground splits rain into runoff and water that soaks in."),
    Section("surface", "Roughness and river channels",
            "How rough the ground is and how river channels are shaped."),
    Section("routing", "Routing and simulation time",
            "How water moves downhill through the grid, and for how long to simulate."),
    Section("outputs", "Outputs and computer",
            "Extra results to record, and whether to use the CPU or a GPU."),
]
SECTION_BY_KEY = {s.key: s for s in SECTIONS}


# ═════════════════════════════════════════════════════════════════════════════
# "When does this parameter matter?" — small, testable predicates
# ═════════════════════════════════════════════════════════════════════════════
def _blank(v):
    return v is None or (isinstance(v, (str, list, tuple, dict)) and len(v) == 0)


class In:
    """The controlling value is one of *values*."""

    def __init__(self, *values):
        self.values = values

    def test(self, v):
        return v in self.values

    def example(self, ctrl):
        return self.values[0]

    def describe(self, name):
        if len(self.values) == 1:
            return f"{name} is {self.values[0]!r}"
        return f"{name} is one of " + ", ".join(repr(v) for v in self.values)


class NotIn(In):
    """The controlling value is none of *values*."""

    def test(self, v):
        return v not in self.values

    def example(self, ctrl):
        for value, _label in choices_for(ctrl):
            if value not in self.values:
                return value
        raise ValueError(f"no example for NotIn{self.values}")

    def describe(self, name):
        return f"{name} is not " + " or ".join(repr(v) for v in self.values)


class Has:
    """The controlling list contains *item*."""

    def __init__(self, item):
        self.item = item

    def test(self, v):
        return self.item in (v or [])

    def example(self, ctrl):
        return [self.item]

    def describe(self, name):
        return f"{name} includes {self.item!r}"


class On:
    """The controlling switch is on (truthy)."""

    def test(self, v):
        return bool(v)

    def example(self, ctrl):
        return True

    def describe(self, name):
        return f"{name} is on"


class Blank:
    """The controlling value is empty (None / '' / [])."""

    def test(self, v):
        return _blank(v)

    def example(self, ctrl):
        return "" if isinstance(Config.__dict__.get(ctrl.name), str) else None

    def describe(self, name):
        return f"{name} is empty"


class QbfIs:
    """CHANNEL_QBF_M3S is of the given kind(s): 'auto' | 'value' | 'formula'."""

    _EXAMPLES = {"auto": None, "value": 400.0, "formula": "global_area"}

    def __init__(self, *kinds):
        self.kinds = kinds

    def test(self, v):
        from .core.routing.qbf import classify_qbf
        try:
            return classify_qbf(v)[0] in self.kinds
        except ValueError:
            return False

    def example(self, ctrl):
        return self._EXAMPLES[self.kinds[0]]

    def describe(self, name):
        words = {"auto": "automatic", "value": "a number", "formula": "a formula"}
        return f"{name} is " + " or ".join(words[k] for k in self.kinds)


# ═════════════════════════════════════════════════════════════════════════════
# Parameter description
# ═════════════════════════════════════════════════════════════════════════════
#: Input kinds understood by every front-end.
KINDS = (
    "text",          # free text
    "file",          # path to an existing input file
    "folder",        # output folder (created if missing)
    "float", "int", "bool",
    "choice",        # one of a fixed list (enum or explicit `choices`)
    "multichoice",   # several of a fixed list
    "latlon",        # (lat, lon)
    "bbox",          # (min_lon, min_lat, max_lon, max_lat)
    "datetime",      # "YYYY-MM-DD HH:MM"
    "crs",           # projected CRS, e.g. "EPSG:32645"
    "order_table",   # {Strahler order: value}, typed "3, 5, 8, …"
    "points",        # list of point dicts (gauges / inflow hydrographs)
    "qbf",           # CHANNEL_QBF_M3S: automatic | number | formula
    "channel_n",     # MANNINGS_N_CHANNEL: off | number | by order | by elevation | raster
    "hg",            # CHANNEL_HG: preset name | {w_a, w_b, d_a, d_b}
    # sub-kinds used inside the composite kinds above
    "formula", "elev_table", "hg_coeffs",
)


class Param:
    """
    One configurable knob.

    name     Config attribute.
    section  key into SECTIONS.
    label    short plain-language name ("Rain intensity").
    help     one to three plain sentences: what it is and when to change it.
    kind     one of KINDS.
    unit     shown next to the value ("mm/h").
    level    'basic' (asked by default) or 'advanced' (asked on request).
    when     clauses ((NAME, predicate), …) that must ALL hold for it to matter.
    when_any alternatives (clauses, clauses, …): it matters if ANY group holds.
    optional None (or blank) is allowed; `none_label` says what it means.
    choice_groups  optional two-level layout of a choice (see PRECIP_METHOD).
    """

    def __init__(self, name, section, label, help, kind, unit="", level="basic",
                 when=(), when_any=(), optional=False, none_label="",
                 choices=None, choice_labels=None, min=None, max=None,
                 min_exclusive=False, min_items=0, needs_csv=False, example=None,
                 choice_groups=None, group_title="", sub_labels=None):
        self.name = name
        self.section = section
        self.label = label
        self.help = help
        self.kind = kind
        self.unit = unit
        self.level = level
        self.when = tuple(when)
        self.when_any = tuple(tuple(g) for g in when_any)
        self.optional = optional
        self.none_label = none_label
        self.choices = list(choices) if choices is not None else None
        self.choice_labels = dict(choice_labels or {})
        self.min = min
        self.max = max
        self.min_exclusive = min_exclusive
        self.min_items = min_items
        self.needs_csv = needs_csv
        self.example = example
        # Two-level choice for forms: [(group key, label, [choices])] — pick the
        # group first, then (if it has several) one of its choices.
        self.choice_groups = list(choice_groups or [])
        self.group_title = group_title
        self.sub_labels = dict(sub_labels or {})

    @property
    def default(self):
        """The Config default (a fresh copy, so callers may mutate it)."""
        return getattr(Config(), self.name)

    @property
    def title(self):
        """'Rain intensity (mm/h)'."""
        return f"{self.label} ({self.unit})" if self.unit else self.label

    def __repr__(self):
        return f"Param({self.name!r}, kind={self.kind!r}, level={self.level!r})"


P = Param   # short alias for the catalogue below

# Reusable conditions ---------------------------------------------------------
_PHYSICAL = ("RUNOFF_SOURCE", In("physical"))
_SAT = (_PHYSICAL, ("RUNOFF_MECHANISMS", Has("saturation_excess")))
_INF = (_PHYSICAL, ("RUNOFF_MECHANISMS", Has("infiltration_excess")))
_IMP = (_PHYSICAL, ("RUNOFF_MECHANISMS", Has("impervious")))
_SD_GEE = ("VSA_SD_SOURCE", In("gee"))
_SOIL = (_SAT, _INF)                                    # use as when_any
_SOIL_GEE = (_SAT + (_SD_GEE,), _INF + (_SD_GEE,))      # use as when_any
_IMERG = ("PRECIP_METHOD", In("imerg_thiessen", "imerg_idw"))
_GAUGES = ("PRECIP_METHOD", In("thiessen", "idw"))
_NO_DEM = ("DEM_PATH", Blank())
_CHANNELS = ("CHANNEL_ROUTING", On())
_BY_Q = (_CHANNELS, ("CHANNEL_GEOMETRY", In("discharge")))
_SCHEME = "ROUTING_SCHEME"
_ADAPTIVE = ("ADAPTIVE_TIMESTEP", On())
_FLOOD = ("INUNDATION_MAP", On())

_GEE_NOTE = " Needs Google Earth Engine (GEE_PROJECT)."


def _dem_labels():
    return {k: f"{k} — {v['title']}, {v['resolution_m']} m"
            for k, v in _DEM_CATALOG.items()}


PARAMS = [
    # ── 1. Basin, terrain and results folder ─────────────────────────────────
    P("DEM_PATH", "project", "Elevation model (DEM) file",
      "A GeoTIFF of ground elevation covering your basin, in any projection. "
      "Leave it empty to download a DEM from Google Earth Engine instead.",
      "file", example="dem.tif"),
    P("DEM_BOUNDS_WGS84", "project", "Area to download",
      "Only used when no DEM file is given: the box to download, in longitude/"
      "latitude degrees, e.g. 85.1, 27.5, 85.6, 27.9. Make it a little larger "
      "than the basin.", "bbox", unit="west, south, east, north", optional=True,
      none_label="no download", when=(_NO_DEM,), example=(85.1, 27.5, 85.6, 27.9)),
    P("DEM_SOURCE", "project", "DEM dataset to download",
      "Which global elevation dataset to download. 'MRRpy list-dems' compares "
      "coverage and resolution.", "choice", when=(_NO_DEM,),
      choice_labels=_dem_labels()),
    P("DEM_SCALE_M", "project", "Download resolution",
      "Average the downloaded DEM to this pixel size (e.g. 90 for faster runs). "
      "Empty keeps the dataset's native resolution.", "float", unit="m",
      level="advanced", optional=True, none_label="native resolution",
      min=0, min_exclusive=True, when=(_NO_DEM,), example=90.0),
    P("MODEL_AREA", "project", "Area to model",
      "Either the watershed that drains to one outlet point, or every cell of "
      "the DEM with no outlet. Use the whole DEM to see how water moves over a "
      "whole area, such as a city or a valley with several rivers. Water then "
      "leaves wherever it flows off the edge of the DEM, so the DEM should "
      "cover the uphill land that drains into your area.", "choice",
      choice_labels={"watershed": "watershed — everything upstream of an outlet point",
                     "whole_dem": "whole_dem — every cell of the DEM, no outlet needed"}),
    P("OUTPUT_POINT", "project", "Basin outlet",
      "The river point your basin drains to. MRRpy delineates everything "
      "upstream of it and reports the flow there. Latitude first, e.g. "
      "27.6322, 85.2933.", "latlon", unit="latitude, longitude",
      when=(("MODEL_AREA", In("watershed")),), example=(28.0, 84.5)),
    P("TARGET_CRS_EPSG", "project", "Map projection for the model grid",
      "A projected coordinate system in metres, as an EPSG code. The UTM zone "
      "of your outlet is a safe choice, and MRRpy suggests it for you.",
      "crs", example="EPSG:32644"),
    P("OUTPUT_DIR", "project", "Results folder",
      "Where every output is written. It is created if it does not exist.",
      "folder", example="results/"),
    P("GEE_PROJECT", "project", "Google Earth Engine project",
      "Only needed for options that download data from Earth Engine (DEM "
      "download, IMERG rain, global curve numbers, soil and land-cover maps). "
      "Leave it empty to work offline. The GEE_PROJECT environment variable "
      "works too.", "text", optional=True, none_label="not set (offline)",
      example="my-ee-project"),
    P("DELINEATION_ENGINE", "project", "Flow-direction engine",
      "The library that fills pits and traces flow directions on the DEM.",
      "choice", level="advanced",
      choice_labels={
          "pysheds": "pysheds — the original engine (keeps older validated runs identical)",
          "pyflwdir": "pyflwdir — priority-flood; handles large flat lakes (recommended)",
      }),
    P("DEM_CONDITIONING", "project", "DEM conditioning",
      "How pits and flats are removed before tracing flow.", "choice",
      level="advanced", optional=True,
      none_label="automatic (carve_spread for pyflwdir, fill for pysheds)",
      choice_labels={
          "fill": "fill — raise pits to their spill level (classic)",
          "carve": "carve — cut through barriers instead of filling (Yamazaki 2012)",
          "carve_spread": "carve_spread — carve, then give flats a gentle slope",
      }),
    P("DEM_LAKE_MASK", "project", "Lake / reservoir mask",
      "Optional raster where values above 0 mark lakes or reservoirs; they are "
      "kept flat during DEM conditioning so their storage is not carved away.",
      "file", level="advanced", optional=True, none_label="none", example="lakes.tif"),
    P("CELL_SIZE", "project", "Grid cell size",
      "Override the cell size read from the DEM. Leave empty unless you know "
      "you need it.", "float", unit="m", level="advanced", optional=True,
      none_label="read from the DEM", min=0, min_exclusive=True, example=90.0),

    # ── 2. Rainfall ──────────────────────────────────────────────────────────
    P("PRECIP_METHOD", "rain", "Rainfall input",
      "Where the rain comes from.", "choice",
      choice_labels={
          "uniform": "uniform — the same design storm everywhere (no data needed)",
          "thiessen": "thiessen — your rain-gauge records, nearest gauge per cell",
          "idw": "idw — your rain-gauge records, distance-weighted",
          "imerg_thiessen": "imerg_thiessen — NASA IMERG satellite rain, nearest pixel (Earth Engine)",
          "imerg_idw": "imerg_idw — NASA IMERG satellite rain, distance-weighted (Earth Engine)",
      },
      choice_groups=[
          ("storm", "Design storm — the same rain everywhere (no data needed)", ["uniform"]),
          ("gauges", "Rain gauges — your own CSV records", ["thiessen", "idw"]),
          ("imerg", "Satellite — NASA IMERG (Google Earth Engine)",
           ["imerg_thiessen", "imerg_idw"]),
      ],
      group_title="Spread the rain between points by",
      sub_labels={
          "thiessen": "Thiessen — each cell takes its nearest gauge",
          "idw": "IDW — a distance-weighted average of the gauges",
          "imerg_thiessen": "Thiessen — each cell takes its nearest satellite pixel",
          "imerg_idw": "IDW — a distance-weighted average of the pixels",
      }),
    P("RAIN_INTENSITY_MM_HR", "rain", "Rain intensity",
      "Constant rain rate of the design storm. Use 0 to route an inflow "
      "hydrograph only.", "float", unit="mm/h", min=0,
      when=(("PRECIP_METHOD", In("uniform")),), example=35.0),
    P("RAIN_DURATION_HOURS", "rain", "Storm duration",
      "How long the design storm lasts.", "float", unit="hours", min=0,
      when=(("PRECIP_METHOD", In("uniform")),), example=6.0),
    P("PRECIP_GAUGE_FILE", "rain", "Gauge locations (CSV)",
      "One row per gauge with columns gauge_id, name, easting_m, northing_m "
      "(coordinates in the map projection above).", "file", when=(_GAUGES,),
      example="gauges.csv"),
    P("PRECIP_TIMESERIES_FILE", "rain", "Gauge rainfall (CSV)",
      "Columns time_s, then one column per gauge_id holding the rain depth "
      "(mm) that fell in the interval ending at that time.", "file",
      when=(_GAUGES,), example="rain.csv"),
    P("PRECIP_IDW_POWER", "rain", "Distance-weighting power",
      "How quickly a gauge's influence fades with distance (2 is standard).",
      "float", level="advanced", min=0,
      when=(("PRECIP_METHOD", In("idw", "imerg_idw")),), example=3.0),
    P("PRECIP_EXCLUDE_OUTSIDE_STATIONS", "rain", "Ignore gauges outside the basin",
      "Use only gauges that lie inside the delineated watershed.", "bool",
      level="advanced", when=(_GAUGES,)),
    P("EVENT_START_UTC", "rain", "Storm start (UTC)",
      "When the event starts, as 'YYYY-MM-DD HH:MM' in UTC. Sets the satellite "
      "rain window and the date of the satellite soil-moisture map.",
      "datetime", optional=True, none_label="not set",
      when_any=((_IMERG,),) + tuple(g + (_SD_GEE,) for g in _SOIL),
      example="2024-09-27 00:00"),
    P("IMERG_UTC_OFFSET_HOURS", "rain", "Local time offset from UTC",
      "Hours to add to UTC to get local time (Nepal = 5.75). Used for the "
      "local-time IMERG window.", "float", unit="hours", level="advanced",
      when=(_IMERG,), example=5.0),
    P("IMERG_START_LOCAL", "rain", "IMERG window start (local time)",
      "Override the start of the satellite-rain window, 'YYYY-MM-DD HH:MM'.",
      "datetime", level="advanced", optional=True,
      none_label="from the storm start", when=(_IMERG,), example="2024-09-26 06:00"),
    P("IMERG_END_LOCAL", "rain", "IMERG window end (local time)",
      "Override the end of the satellite-rain window, 'YYYY-MM-DD HH:MM'.",
      "datetime", level="advanced", optional=True,
      none_label="storm start + simulation length", when=(_IMERG,),
      example="2024-09-30 06:00"),
    P("IMERG_DATASET", "rain", "IMERG Earth Engine collection",
      "The Earth Engine image collection to read.", "text", level="advanced",
      when=(_IMERG,), example="NASA/GPM_L3/IMERG_V06"),
    P("IMERG_BAND", "rain", "IMERG band", "The rain-rate band to read.", "text",
      level="advanced", when=(_IMERG,), example="precipitationCal"),
    P("PRECIP_IMERG_FORCE_DOWNLOAD", "rain", "Download IMERG again",
      "Ignore IMERG files cached in the results folder and download them again.",
      "bool", level="advanced", when=(_IMERG,)),
    P("IMERG_BBOX_BUFFER_M", "rain", "Margin around the basin for IMERG",
      "Extra distance around the basin when selecting satellite pixels.",
      "float", unit="m", level="advanced", min=0, when=(_IMERG,), example=20000.0),
    P("RAIN_SNOW_ELEV_LOW", "rain", "All rain below elevation",
      "Snow partition: at or below this elevation all precipitation is rain. "
      "Set it with the 'all snow above' elevation; set both equal for a sharp "
      "cutoff.", "float", unit="m", level="advanced", optional=True,
      none_label="off (all precipitation is rain)", example=3000.0),
    P("RAIN_SNOW_ELEV_HIGH", "rain", "All snow above elevation",
      "At or above this elevation precipitation falls as snow and does not run "
      "off during the event; in between, the rain share ramps down linearly.",
      "float", unit="m", level="advanced", optional=True,
      none_label="off (all precipitation is rain)", example=4500.0),

    # ── 3. Runoff ────────────────────────────────────────────────────────────
    P("RUNOFF_SOURCE", "runoff", "Runoff method",
      "How rain is split into runoff and water that soaks into the ground.",
      "choice",
      choice_labels={
          "none": "none — all rain becomes runoff (no losses; good for testing)",
          "coefficient": "coefficient — a fixed runoff fraction per cell, from a raster",
          "raster": "raster — runoff maps you computed elsewhere, over time",
          "scs_cn": "scs_cn — SCS Curve Number",
          "physical": "physical — impervious areas, infiltration and/or saturation (VSA-OPM)",
      }),
    P("RUNOFF_COEFFICIENT_PATH", "runoff", "Runoff-coefficient raster",
      "GeoTIFF of the fraction of rain that runs off, 0 to 1, per cell.",
      "file", when=(("RUNOFF_SOURCE", In("coefficient")),), example="cf.tif"),
    P("RUNOFF_RASTER_MANIFEST", "runoff", "Runoff raster list (CSV)",
      "CSV with columns time_s and filepath: one runoff GeoTIFF per time.",
      "file", when=(("RUNOFF_SOURCE", In("raster")),), example="manifest.csv"),
    P("RUNOFF_CN_SOURCE", "runoff", "Curve numbers from",
      "Where the per-cell curve number comes from.", "choice",
      when=(("RUNOFF_SOURCE", In("scs_cn")),),
      choice_labels={
          "scalar": "scalar — one curve number everywhere",
          "gee": "gee — GCN250 global curve-number map (Earth Engine)",
          "raster": "raster — your curve-number GeoTIFF",
      }),
    P("RUNOFF_CN_AMC", "runoff", "Soil wetness before the storm",
      "Antecedent moisture condition: dry, normal or wet.", "choice",
      when=(("RUNOFF_SOURCE", In("scs_cn")),),
      choice_labels={"i": "i — dry", "ii": "ii — normal", "iii": "iii — wet"}),
    P("RUNOFF_CN", "runoff", "Curve number",
      "From about 30 (very permeable) to 98 (paved). With a raster it fills "
      "the gaps.", "float", min=1, max=100,
      when=(("RUNOFF_SOURCE", In("scs_cn")),
            ("RUNOFF_CN_SOURCE", In("scalar", "raster"))), example=82.0),
    P("RUNOFF_CN_PATH", "runoff", "Curve-number raster",
      "GeoTIFF of curve numbers (taken as normal wetness).", "file",
      when=(("RUNOFF_SOURCE", In("scs_cn")), ("RUNOFF_CN_SOURCE", In("raster"))),
      example="cn.tif"),
    P("RUNOFF_SCS_Ia_FACTOR", "runoff", "Initial abstraction ratio (Ia/S)",
      "Share of the soil's storage that is filled before runoff starts "
      "(0.2 is the textbook value; 0.05 is common for urban areas).", "float",
      level="advanced", min=0, max=1,
      when=(("RUNOFF_SOURCE", In("scs_cn")),), example=0.05),
    P("RUNOFF_MECHANISMS", "runoff", "Processes to include",
      "Pick any combination; they are combined per cell without counting "
      "water twice.", "multichoice", min_items=1, when=(_PHYSICAL,),
      choice_labels={
          "impervious": "impervious — paved and built-up areas shed their rain",
          "infiltration_excess": "infiltration_excess — rain faster than the soil absorbs (Green-Ampt)",
          "saturation_excess": "saturation_excess — saturated soils near streams (VSA-OPM)",
      }, example=["infiltration_excess"]),
    P("IMPERVIOUS_SOURCE", "runoff", "Impervious areas from",
      "Where the paved / built-up fraction of each cell comes from.", "choice",
      when=_IMP,
      choice_labels={
          "none": "none — no impervious areas",
          "lcz": "lcz — WUDAPT Local Climate Zones (Earth Engine)",
          "lulc": "lulc — ESA WorldCover land cover (Earth Engine)",
          "raster": "raster — your impervious-fraction GeoTIFF (0 to 1)",
      }),
    P("IMPERVIOUS_RASTER_PATH", "runoff", "Impervious-fraction raster",
      "GeoTIFF with the impervious fraction (0 to 1) of each cell.", "file",
      optional=True, none_label="none",
      when=_IMP + (("IMPERVIOUS_SOURCE", In("raster")),), example="imperv.tif"),
    P("GA_SUCTION_SOURCE", "runoff", "Soil suction from",
      "Green-Ampt wetting-front suction: one value or from soil texture.",
      "choice", when=_INF,
      choice_labels={
          "scalar": "scalar — one value everywhere",
          "texture": "texture — from SoilGrids sand and clay (Earth Engine)",
      }),
    P("GA_SUCTION_M", "runoff", "Soil suction head",
      "Green-Ampt wetting-front suction (loam about 0.1 to 0.2 m). Also fills "
      "gaps in the texture map.", "float", unit="m", min=0, min_exclusive=True,
      when=_INF, example=0.25),
    P("GA_KSAT_SOURCE", "runoff", "Infiltration rate from",
      "Where the soil's vertical infiltration rate (Ksat) comes from.", "choice",
      when=_INF,
      choice_labels={
          "scalar": "scalar — one value everywhere",
          "gee": "gee — HiHydroSoil map (Earth Engine)",
          "raster": "raster — your Ksat GeoTIFF in mm/h",
      }),
    P("GA_KSAT_MMHR", "runoff", "Soil infiltration rate (vertical Ksat)",
      "How fast saturated soil soaks up water: sand about 50, loam about 10, "
      "clay about 1 mm/h. Also fills gaps in a map.", "float", unit="mm/h",
      min=0, min_exclusive=True, when=_INF, example=25.0),
    P("GA_KSAT_DEPTH_CM", "runoff", "Soil depth for the Ksat map",
      "The HiHydroSoil Ksat is averaged over this top layer of soil: 30 cm for "
      "short intense bursts, 60 cm as the all-round default, 100 cm for long "
      "frontal rain on tight clay subsoils.", "float", unit="cm",
      level="advanced", min=0, max=200, min_exclusive=True,
      when=_INF + (("GA_KSAT_SOURCE", In("gee")),), example=30.0),
    P("GA_RECOVERY", "runoff", "Let the soil dry out between storms",
      "Soaked-in water drains out of the top soil layer in dry weather, so a "
      "later storm meets drier soil again (the EPA SWMM method, from Ksat "
      "alone). Keep it on for runs of weeks to years. Off means the soil only "
      "gets wetter for the whole run.", "bool", level="advanced", when=_INF),
    P("GA_KSAT_RASTER", "runoff", "Ksat raster",
      "GeoTIFF of vertical Ksat in mm/h.", "file", optional=True,
      none_label="automatic file in the results folder",
      when=_INF + (("GA_KSAT_SOURCE", In("raster")),), example="ksat.tif"),
    P("GA_KSAT_SCALE", "runoff", "Ksat multiplier",
      "Calibration factor applied to the Ksat map.", "float", level="advanced",
      min=0, min_exclusive=True,
      when=_INF + (("GA_KSAT_SOURCE", In("gee", "raster")),), example=0.5),
    P("VSA_SD_SOURCE", "runoff", "Soil storage from",
      "Where the soil's water-storage capacity and starting dryness come from.",
      "choice", when_any=_SOIL,
      choice_labels={
          "manual": "manual — the values typed below",
          "gee": "gee — SERVES satellite soil moisture + SoilGrids (Earth Engine; needs the storm date)",
      }),
    P("VSA_SD_MAX_INITIAL", "runoff", "Root-zone depth (soil storage)",
      "Depth of soil that can hold water before it saturates. Replaced by "
      "satellite estimates when soil storage comes from SERVES.", "float",
      unit="m", min=0, min_exclusive=True, when_any=_SOIL, example=0.3),
    P("VSA_PHI", "runoff", "Drainable porosity",
      "Share of the soil volume that can drain (0 to 1).", "float",
      min=0, max=1, min_exclusive=True, when=_SAT, example=0.4),
    P("VSA_K_SAT", "runoff", "Sideways soil conductivity",
      "How fast water drains sideways through saturated soil toward streams "
      "(not the vertical infiltration rate).", "float", unit="m/day",
      min=0, min_exclusive=True, when=_SAT, example=20.0),
    P("VSA_Q_MAX", "runoff", "River flow before the storm",
      "Observed flow at the outlet just before the event; it sets how wet the "
      "basin starts.", "float", unit="m³/s", min=0.001, min_exclusive=True,
      when=_SAT, example=40.0),
    P("VSA_SD_MIN", "runoff", "Minimum soil deficit",
      "Floor on the saturation deficit, to keep the sandbox stable.", "float",
      unit="m", level="advanced", min=0, min_exclusive=True, when=_SAT,
      example=0.002),
    P("VSA_PER_POLYGON", "runoff", "Separate soil store per rainfall zone",
      "Run one saturation sandbox per rainfall zone instead of one for the "
      "whole basin.", "bool", level="advanced", when=_SAT),
    P("VSA_BASEFLOW", "runoff", "Add pre-storm flow to the hydrograph",
      "Add the pre-storm river flow to the reported outlet hydrograph, so it is "
      "directly comparable with gauge records.", "bool", level="advanced",
      when=_SAT),
    P("VSA_SD_REDUCER", "runoff", "Combine satellite deficit per zone by",
      "How the per-cell satellite deficit is summarised for each zone.",
      "choice", level="advanced", when_any=_SOIL_GEE,
      choice_labels={
          "mean": "mean — the zone average",
          "max": "max — the driest cell",
          "divide": "divide — the value at the zone's drainage divide",
      }),
    P("VSA_DEFICIT_RASTER", "runoff", "Deficit raster file",
      "Where the downloaded soil-deficit raster is cached.", "file",
      level="advanced", optional=True, none_label="automatic file in the results folder",
      when_any=_SOIL_GEE, example="deficit.tif"),
    P("SERVES_SATELLITE", "runoff", "Satellite for soil moisture (SERVES)",
      "Which satellite's land-surface data SERVES uses.", "choice",
      level="advanced", when_any=_SOIL_GEE,
      choice_labels={"landsat": "landsat — 30 m", "sentinel2": "sentinel2 — 10–20 m",
                     "modis": "modis — 500 m, daily"}),
    P("SERVES_SEARCH_WINDOW", "runoff", "Look back for a clear image",
      "How many days before the storm to search for a usable image.", "int",
      unit="days", level="advanced", min=1, when_any=_SOIL_GEE, example=45),
    P("SOILGRIDS_DEPTH", "runoff", "SoilGrids depth",
      "Which soil layer to read from SoilGrids.", "choice", level="advanced",
      when_any=_SOIL_GEE + (_INF + (("GA_SUCTION_SOURCE", In("texture")),),),
      choice_labels={"b0": "b0 — surface", "b10": "b10 — 10 cm", "b30": "b30 — 30 cm",
                     "b60": "b60 — 60 cm", "b100": "b100 — 100 cm",
                     "b200": "b200 — 200 cm"}),

    # ── 4. Roughness and river channels ──────────────────────────────────────
    P("MANNINGS_N_SOURCE", "surface", "Ground roughness from",
      "Where Manning's n (surface roughness) of each cell comes from.",
      "choice",
      choice_labels={
          "scalar": "scalar — one value everywhere",
          "lulc": "lulc — ESA WorldCover land cover (Earth Engine)",
          "lcz": "lcz — WUDAPT Local Climate Zones (Earth Engine)",
          "raster": "raster — your Manning's n GeoTIFF",
      }),
    P("MANNINGS_N", "surface", "Manning's n of the ground",
      "Surface roughness: pavement about 0.015, grass 0.03 to 0.05, forest "
      "about 0.1. Also fills gaps in maps.", "float", min=0, min_exclusive=True,
      example=0.05),
    P("MANNINGS_N_LULC_PATH", "surface", "Land-cover raster",
      "'gee' downloads ESA WorldCover; or give the path of your own "
      "WorldCover-coded GeoTIFF.", "text", level="advanced",
      when=(("MANNINGS_N_SOURCE", In("lulc")),), example="worldcover.tif"),
    P("MANNINGS_N_RASTER_PATH", "surface", "Manning's n raster",
      "GeoTIFF of Manning's n per cell.", "file", optional=True,
      none_label="none", when=(("MANNINGS_N_SOURCE", In("raster")),),
      example="n.tif"),
    P("LULC_LOOKUP_CSV", "surface", "Land-cover lookup table",
      "Maps ESA WorldCover classes to roughness, impervious share and root-zone "
      "depth. The default ships with MRRpy.", "file", level="advanced",
      example="my_lulc_lookup.csv"),
    P("LCZ_LOOKUP_CSV", "surface", "Local-climate-zone lookup table",
      "Maps WUDAPT LCZ classes to roughness, impervious share and root-zone "
      "depth. The default ships with MRRpy.", "file", level="advanced",
      example="my_lcz_lookup.csv"),
    P("MANNINGS_N_CHANNEL", "surface", "Manning's n in river channels",
      "Roughness used on river-channel cells instead of the ground value: one "
      "number, a value per stream order, values by elevation, or a raster.",
      "channel_n", optional=True, none_label="same as the ground",
      example=0.04),
    P("CHANNEL_MIN_AREA_KM2", "surface", "Smallest river (drainage area)",
      "Cells draining more than this area are river channels (capped at 10 % "
      "of the basin for small catchments).", "float", unit="km²",
      level="advanced", optional=True, none_label="the top 1 % of cells",
      min=0, min_exclusive=True, example=25.0),
    P("CHANNEL_FACCUM_THRESHOLD", "surface", "Smallest river (cells)",
      "The same threshold counted in upstream cells; overrides the drainage "
      "area above.", "int", unit="cells", level="advanced", optional=True,
      none_label="use the drainage area", min=1, example=5000),
    P("CHANNEL_ROUTING", "surface", "Give rivers a real channel",
      "Recommended. River cells get a channel narrower than the grid cell "
      "instead of spreading water over the whole cell.", "bool",
      level="advanced"),
    P("CHANNEL_GEOMETRY", "surface", "Channel size from",
      "How each river cell's width and bankfull depth are set.", "choice",
      level="advanced", when=(_CHANNELS,),
      choice_labels={
          "order": "order — tables by stream order (legacy)",
          "area": "area — US curves versus drainage area (Bieger 2015)",
          "discharge": "discharge — sized to carry the bankfull (2-year) flood (recommended)",
      }),
    P("CHANNEL_QBF_M3S", "surface", "Bankfull flow (about the 2-year flood)",
      "The flow the river carries before spilling onto its floodplain. "
      "Automatic uses a global estimate at the outlet (Earth Engine when "
      "available, otherwise drainage area), usually within a factor of 2. Or "
      "give your 2-year flood, or a regional formula.", "qbf", optional=True,
      none_label="automatic global estimate", when=_BY_Q, example=400.0),
    P("CHANNEL_QBF_AREA_KM2", "surface", "…measured at a gauge draining",
      "Drainage area of the gauge your 2-year flood comes from. Empty means "
      "the basin outlet.", "float", unit="km²", optional=True,
      none_label="the basin outlet", min=0, min_exclusive=True,
      when=_BY_Q + (("CHANNEL_QBF_M3S", QbfIs("value")),), example=585.0),
    P("CHANNEL_QBF_AREA_EXP", "surface", "Bankfull-flow growth exponent",
      "Bankfull flow grows downstream as drainage area to this power "
      "(0.75 fits most basins).", "float", level="advanced", min=0,
      when=_BY_Q + (("CHANNEL_QBF_M3S", QbfIs("auto", "value")),), example=0.7),
    P("CHANNEL_SLOPE_REACH_M", "surface", "Reach length for channel slope",
      "Distance over which the river slope is measured when sizing the channel "
      "depth.", "float", unit="m", level="advanced", min=0, min_exclusive=True,
      when=_BY_Q, example=2000.0),
    P("CHANNEL_MIN_DEPTH_M", "surface", "Minimum bankfull depth",
      "Floor on the channel's bankfull depth.", "float", unit="m",
      level="advanced", min=0, min_exclusive=True, when=_BY_Q, example=0.2),
    P("CHANNEL_HG", "surface", "Width and depth curve",
      "Bankfull width and depth versus drainage area: a published regional "
      "curve (Bieger et al. 2015) or your own coefficients.", "hg",
      when=(_CHANNELS, ("CHANNEL_GEOMETRY", In("area"))), example="bieger_apl"),
    P("CHANNEL_WIDTH_BY_ORDER", "surface", "Channel width by stream order",
      "Width for stream order 1, 2, 3, …, comma-separated. Higher orders "
      "reuse the last value.", "order_table", unit="m",
      when=(_CHANNELS, ("CHANNEL_GEOMETRY", In("order"))),
      example={1: 2.0, 2: 4.0, 3: 9.0}),
    P("CHANNEL_DEPTH_BY_ORDER", "surface", "Bankfull depth by stream order",
      "Bankfull depth for stream order 1, 2, 3, …, comma-separated.",
      "order_table", unit="m",
      when=(_CHANNELS, ("CHANNEL_GEOMETRY", In("order"))),
      example={1: 0.4, 2: 0.9, 3: 1.5}),
    P("CHANNEL_SUBGRID", "surface", "Cut the channel below the ground",
      "The channel bed sits its bankfull depth below the DEM; above bankfull, "
      "water spreads over the whole cell (LISFLOOD-FP style).", "bool",
      level="advanced", when=(_CHANNELS,)),
    P("MANNINGS_N_FLOODPLAIN", "surface", "Manning's n above the banks",
      "Roughness for flow above bankfull on river cells.", "float",
      level="advanced", optional=True, none_label="the ground's n",
      min=0, min_exclusive=True,
      when=(_CHANNELS, ("CHANNEL_SUBGRID", On())), example=0.08),
    P("BASEFLOW_SPECIFIC_Q", "surface", "Steady baseflow in rivers",
      "Constant flow per km² of drainage area; rivers then start at that "
      "depth. 0 starts them dry.", "float", unit="m³/s per km²",
      level="advanced", min=0, example=0.01),

    # ── 5. Routing and simulation time ───────────────────────────────────────
    P("ROUTING_SCHEME", "routing", "Routing method",
      "How water moves from cell to cell.", "choice",
      choice_labels={
          "kinematic": "kinematic — follows the ground slope (fast, simple)",
          "diffusive": "diffusive — explicit diffusion wave (deprecated: use diffusive_implicit)",
          "muskingum": "muskingum — Muskingum–Cunge (grid-independent attenuation)",
          "dynamic": "dynamic — local-inertial wave (experimental, under development)",
          "diffusive_implicit": "diffusive_implicit — stable diffusion wave, handles backwater and flat ground (CPU)",
      }, example="muskingum"),
    P("TOTAL_SIMULATION_TIME_HOURS", "routing", "Simulation length",
      "How long to simulate, from the start of the rain.", "float",
      unit="hours", min=0, min_exclusive=True, example=48.0),
    P("OUTPUT_INTERVAL_SECONDS", "routing", "Save results every",
      "How often the hydrograph (and any maps) are recorded.", "int",
      unit="seconds", min=1, example=900),
    P("TIME_STEP_SECONDS", "routing", "Time step",
      "The starting calculation step. With the adaptive time step on, MRRpy "
      "adjusts it for stability and speed.", "float", unit="seconds",
      level="advanced", min=0, min_exclusive=True, example=5.0),
    P("DIFFUSION_THETA", "routing", "Diffusion weight θ",
      "0 behaves like kinematic routing; 1 uses the full water-surface slope.",
      "float", level="advanced", min=0, max=1,
      when=((_SCHEME, In("diffusive")),), example=0.5),
    P("DYNAMIC_FLUX_THETA", "routing", "Flux-centering weight θ",
      "1.0 is the original Bates scheme; 0.7 to 0.9 damps oscillations.",
      "float", level="advanced", min=0, max=1,
      when=((_SCHEME, In("dynamic")),), example=0.7),
    P("IMPLICIT_SOLVER", "routing", "Implicit linear solver",
      "Back-end for each implicit step.", "choice", level="advanced",
      choices=["auto", "numba", "splu"],
      choice_labels={"auto": "auto — Numba if installed, otherwise SciPy",
                     "numba": "numba — fast parallel tree sweep",
                     "splu": "splu — SciPy sparse LU (no Numba needed)"},
      when=((_SCHEME, In("diffusive_implicit")),), example="splu"),
    P("IMPLICIT_NUM_THREADS", "routing", "Solver threads",
      "CPU threads for the implicit solver. More than about 32 usually gets "
      "slower.", "int", level="advanced", optional=True,
      none_label="automatic (up to 32)", min=1,
      when=((_SCHEME, In("diffusive_implicit")),), example=8),
    P("IMPLICIT_THETA", "routing", "Implicit time weighting θ",
      "1.0 is backward Euler (robust); 0.5 is Crank–Nicolson.", "float",
      level="advanced", min=0, max=1, min_exclusive=True,
      when=((_SCHEME, In("diffusive_implicit")),), example=0.6),
    P("IMPLICIT_MAX_ITERS", "routing", "Picard iterations per step",
      "Maximum iterations of the lagged-conveyance loop.", "int",
      level="advanced", min=1,
      when=((_SCHEME, In("diffusive_implicit")),), example=12),
    P("IMPLICIT_TOL", "routing", "Picard tolerance",
      "Convergence tolerance on the largest water-level change.", "float",
      unit="m", level="advanced", min=0, min_exclusive=True,
      when=((_SCHEME, In("diffusive_implicit")),), example=1e-5),
    P("IMPLICIT_RELAX", "routing", "Conductance relaxation",
      "Under-relaxation that helps the iterations converge at large steps "
      "(1.0 = off).", "float", level="advanced", min=0, max=1,
      min_exclusive=True, when=((_SCHEME, In("diffusive_implicit")),),
      example=0.5),
    P("IMPLICIT_SLOPE_FLOOR", "routing", "Water-surface slope floor",
      "Smallest water-surface slope used in the conductance.", "float",
      unit="m/m", level="advanced", min=0, min_exclusive=True,
      when=((_SCHEME, In("diffusive_implicit")),), example=1e-7),
    P("ROUTING_INFLOW_BC", "routing", "Inflow hydrographs",
      "Water entering the model from upstream: one point per line as "
      "'name, latitude, longitude, hydrograph.csv'. The CSV has columns "
      "time_hr (or time_s) and Q_m3s. Each point snaps to the nearest river "
      "cell.", "points", level="advanced", optional=True, none_label="none",
      needs_csv=True,
      example=[{"name": "us1", "lat": 27.7, "lon": 85.3, "csv": "inflow.csv"}]),
    P("ADAPTIVE_TIMESTEP", "routing", "Adaptive time step",
      "Let MRRpy grow or shrink the time step for stability and speed "
      "(recommended).", "bool", level="advanced"),
    P("CFL_TARGET", "routing", "Courant number target",
      "Stability target for the explicit methods (below 1).", "float",
      level="advanced", min=0, max=1.5, min_exclusive=True,
      when=(_ADAPTIVE, (_SCHEME, NotIn("diffusive_implicit"))), example=0.7),
    P("IMPLICIT_CFL_TARGET", "routing", "Courant target (implicit)",
      "The implicit method is stable at any step; this keeps each step "
      "accurate (1 to 3 is typical).", "float", level="advanced", min=0,
      min_exclusive=True,
      when=(_ADAPTIVE, (_SCHEME, In("diffusive_implicit"))), example=3.0),
    P("CFL_DT_MAX", "routing", "Largest time step", "Upper limit on the "
      "adaptive step.", "float", unit="seconds", level="advanced",
      optional=True, none_label="the output interval", min=0,
      min_exclusive=True, when=(_ADAPTIVE,), example=30.0),
    P("CFL_DT_MIN", "routing", "Smallest time step", "Lower limit on the "
      "adaptive step.", "float", unit="seconds", level="advanced", min=0,
      min_exclusive=True, when=(_ADAPTIVE,), example=0.05),
    P("CFL_DT_GROW", "routing", "Step growth factor",
      "How fast the step may grow from one step to the next.", "float",
      level="advanced", min=1, when=(_ADAPTIVE,), example=1.2),
    P("MIN_SLOPE", "routing", "Minimum slope",
      "Smallest bed slope used anywhere, so flat cells still drain.",
      "float", unit="m/m", level="advanced", min=0, min_exclusive=True,
      example=1e-3),
    P("MIN_DEPTH_M", "routing", "Minimum water depth",
      "Depths below this count as dry.", "float", unit="m", level="advanced",
      min=0, min_exclusive=True, example=1e-5),
    P("MANNING_SLOPE_CAP", "routing", "Cap on friction slope",
      "Limits the slope used for flow speed on near-vertical cells (e.g. "
      "0.05 to 0.10), to avoid unrealistic velocities.", "float", unit="m/m",
      level="advanced", optional=True, none_label="off", min=0,
      min_exclusive=True, example=0.08),
    P("FLUX_LIMITER", "routing", "Flux limiter",
      "Keeps a cell from sending out more water than it holds (the safety net "
      "of the explicit methods). Turn off only with an adaptive time step.",
      "bool", level="advanced",
      when=((_SCHEME, In("kinematic", "diffusive")),)),

    # ── 6. Outputs and computer ──────────────────────────────────────────────
    P("ROUTING_GAUGES", "outputs", "Virtual gauges",
      "Extra points where depth and flow are recorded (gauges.csv), one per "
      "line as 'name, latitude, longitude'. Each snaps to the nearest river "
      "cell.", "points", optional=True, none_label="none",
      example=[{"name": "bridge", "lat": 27.7, "lon": 85.3}]),
    P("SAVE_FIELDS", "outputs", "Save maps over time",
      "Record depth, velocity and discharge maps at every output time, for "
      "flood maps and animations.", "bool"),
    P("FIELD_VARS", "outputs", "Maps to save", "Which quantities to record.",
      "multichoice", level="advanced", min_items=1,
      choices=["depth", "velocity", "discharge", "volume"],
      choice_labels={"depth": "depth — water depth (m)",
                     "velocity": "velocity — flow speed (m/s)",
                     "discharge": "discharge — flow (m³/s)",
                     "volume": "volume — stored water (m³)"},
      when=(("SAVE_FIELDS", On()),), example=["depth"]),
    P("FIELD_STRIDE", "outputs", "Save maps every Nth output time",
      "Record maps less often to save memory and disk.", "int",
      level="advanced", min=1, when=(("SAVE_FIELDS", On()),), example=3),
    P("FIELD_OUTPUT_DIR", "outputs", "Folder for the maps",
      "Where the maps are written.", "folder", level="advanced",
      optional=True, none_label="a 'fields' folder inside the results folder",
      when=(("SAVE_FIELDS", On()),), example="maps/"),
    P("INUNDATION_MAP", "outputs", "Flood depth and extent maps",
      "Spread each river's flow sideways over the land beside it that lies below "
      "the water (the HAND method), and write maps of flood depth and extent. "
      "The routing itself does not change.", "bool"),
    P("INUNDATION_AREA", "outputs", "Area for the flood maps",
      "The box to map, in longitude/latitude degrees, e.g. a town or a valley. "
      "The flow still comes from the whole basin.", "bbox",
      unit="west, south, east, north", optional=True, none_label="the whole modelled area",
      when=(_FLOOD,), example=(85.25, 27.62, 85.35, 27.72)),
    P("INUNDATION_DEM", "outputs", "Elevation data for the flood maps",
      "A finer DEM draws sharper flood edges; the river flow is passed to it from "
      "the model. 'auto' uses your Earth Engine DEM at its finest resolution when "
      "the model ran coarser (e.g. FABDEM 30 m for a 90 m run), else the model grid.",
      "choice", when=(_FLOOD,),
      choice_labels=dict({"auto": "auto — a finer copy of the run's DEM when there is one",
                          "model_grid": "model_grid — the grid the model ran on",
                          "file": "file — my own finer DEM (e.g. LiDAR)"},
                         **{k: f"{k} — download {v['title']}, {v['resolution_m']} m"
                            for k, v in _DEM_CATALOG.items()})),
    P("INUNDATION_DEM_PATH", "outputs", "Finer DEM file for the flood maps",
      "A GeoTIFF of ground elevation, finer than the model grid, in any projection.",
      "file", optional=True, none_label="not set yet",
      when=(_FLOOD, ("INUNDATION_DEM", In("file"))), example="lidar_5m.tif"),
    P("INUNDATION_DEM_SCALE_M", "outputs", "Flood-map DEM resolution",
      "Cell size to download the flood-map DEM at. Empty uses the dataset's own "
      "finest resolution.", "float", unit="m", level="advanced", optional=True,
      none_label="the dataset's finest", min=0, min_exclusive=True,
      when=(_FLOOD, ("INUNDATION_DEM", NotIn("model_grid", "file"))), example=30.0),
    P("INUNDATION_ANIMATION", "outputs", "Flood animation (GIF)",
      "Also write an animation of the largest flood spreading and draining, with "
      "the hydrograph beside it.", "bool", when=(_FLOOD,)),
    P("INUNDATION_REACH_LENGTH_M", "outputs", "River reach length for flood maps",
      "Rivers are cut into reaches about this long; each gets its own "
      "level-versus-flow curve.", "float", unit="m", level="advanced", min=0,
      min_exclusive=True, when=(_FLOOD,), example=500.0),
    P("INUNDATION_BACKWATER", "outputs", "Big rivers back up into side streams",
      "Map the main rivers again on their own, so a high main river also floods the "
      "mouths of the streams that join it.", "bool", level="advanced", when=(_FLOOD,)),
    P("MASS_BALANCE_REPORT", "outputs", "Water-balance report",
      "Check that no water is lost or created, and write mass_balance.csv.",
      "bool", level="advanced"),
    P("BACKEND", "outputs", "Computer to run on",
      "A GPU can be much faster for large grids. If no GPU is found MRRpy "
      "falls back to the CPU and says so.", "choice",
      choice_labels={"cpu": "cpu — works everywhere",
                     "gpu": "gpu — NVIDIA GPU via CuPy (pip install MRRpy[gpu])"}),
    P("GPU_PRECISION", "outputs", "GPU number precision",
      "float32 is faster on most GPUs; float64 is more exact.", "choice",
      level="advanced", when=(("BACKEND", In("gpu")),),
      choice_labels={"float64": "float64 — double precision (exact)",
                     "float32": "float32 — single precision (faster)"}),
]

PARAM_BY_NAME = {p.name: p for p in PARAMS}
_BY_UPPER = {p.name.upper(): p for p in PARAMS}     # case-insensitive lookup

#: Config attributes that are never asked, and why.
NOT_ASKED = {
    "ROUTING_DEM_PATH": "derived from OUTPUT_DIR",
    "ROUTING_FLOW_DIR_PATH": "derived from OUTPUT_DIR",
    "ROUTING_FLOW_ACCUM_PATH": "derived from OUTPUT_DIR",
    "ROUTING_WATERSHED_MASK_PATH": "derived from OUTPUT_DIR",
    "WATERSHED_GEOJSON": "derived from OUTPUT_DIR",
    "PRECIP_IMERG_DIR": "derived from OUTPUT_DIR",
    "HYDROGRAPH_CSV": "derived from OUTPUT_DIR",
    "MASS_BALANCE_CSV": "derived from OUTPUT_DIR",
    "SERVES_TARGET_DATE": "legacy, not read by the model (EVENT_START_UTC sets the date)",
    "MAX_DEPTH_M": "display-only, not read by the model",
}


# ═════════════════════════════════════════════════════════════════════════════
# Starting points — a few coherent presets so a new user picks a story, not knobs
# ═════════════════════════════════════════════════════════════════════════════
class StartingPoint:
    """A named preset: *values* to set, and *focus* params to ask even if advanced."""

    def __init__(self, key, label, values, focus=()):
        self.key, self.label = key, label
        self.values = dict(values)
        self.focus = tuple(focus)


STARTING_POINTS = [
    StartingPoint("design_storm",
                  "A design storm on my own DEM (works offline)",
                  {"PRECIP_METHOD": "uniform"}),
    StartingPoint("satellite_event",
                  "A real storm with satellite rainfall (NASA IMERG, needs Earth Engine)",
                  {"PRECIP_METHOD": "imerg_thiessen"}),
    StartingPoint("gauge_event",
                  "A real storm with my rain-gauge records",
                  {"PRECIP_METHOD": "thiessen"}),
    StartingPoint("inflow_only",
                  "Route a known inflow hydrograph downstream (no rain)",
                  {"PRECIP_METHOD": "uniform", "RAIN_INTENSITY_MM_HR": 0.0,
                   "RUNOFF_SOURCE": "none"},
                  focus=("ROUTING_INFLOW_BC",)),
    StartingPoint("defaults",
                  "Start from the defaults and choose everything myself", {}),
]
STARTING_POINT_BY_KEY = {s.key: s for s in STARTING_POINTS}


def apply_starting_point(cfg, key):
    """Set *cfg*'s values from starting point *key*; returns [(name, value)] set."""
    sp = STARTING_POINT_BY_KEY[key]
    for name, value in sp.values.items():
        setattr(cfg, name, value)
    return list(sp.values.items())


# ═════════════════════════════════════════════════════════════════════════════
# Lookup and visibility
# ═════════════════════════════════════════════════════════════════════════════
def param(name):
    """The Param called *name* (case-insensitive), with a did-you-mean error."""
    p = PARAM_BY_NAME.get(str(name).strip()) or _BY_UPPER.get(str(name).strip().upper())
    if p is not None:
        return p
    close = difflib.get_close_matches(str(name).upper(), list(PARAM_BY_NAME), n=3)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise KeyError(f"No setting called {name!r}.{hint}")


def values_of(cfg):
    """{name: value} for every catalogued parameter of *cfg*."""
    return {p.name: getattr(cfg, p.name) for p in PARAMS}


def _clauses_hold(clauses, values):
    return all(pred.test(values.get(name)) for name, pred in clauses)


def is_visible(p, values):
    """Does parameter *p* matter for these *values*?"""
    if isinstance(p, str):
        p = param(p)
    if not _clauses_hold(p.when, values):
        return False
    if p.when_any and not any(_clauses_hold(g, values) for g in p.when_any):
        return False
    return True


def visible_params(values, section=None, level=None):
    """Catalogue params (in order) that matter for *values*, optionally filtered."""
    return [p for p in PARAMS
            if (section is None or p.section == section)
            and (level is None or p.level == level)
            and is_visible(p, values)]


def parent_of(p):
    """
    (controller name, item) that *p* hangs under in a tree layout, or None.

    The controller is the last clause of the conditions (by convention the
    most specific one).  *item* is set when the controller is a multi-choice
    and *p* belongs to one of its items (e.g. GA_KSAT_MMHR under the
    'infiltration_excess' box of RUNOFF_MECHANISMS); None means "shared".
    """
    if isinstance(p, str):
        p = param(p)
    groups = [p.when + g for g in p.when_any] if p.when_any else ([p.when] if p.when else [])
    if not groups:
        return None
    lasts = [g[-1] for g in groups]
    name, pred = lasts[0]
    items = {getattr(pr, "item", None) for _n, pr in lasts}
    if len(lasts) > 1 and all(n == name for n, _ in lasts) and len(items) > 1:
        return name, None
    return name, (pred.item if isinstance(pred, Has) else None)


def extra_parents(p):
    """
    [(controller name, groups)] — other places *p* matters, for a when_any
    whose alternatives hang under different controllers (EVENT_START_UTC is
    needed by IMERG rain *and* by satellite soil moisture).
    """
    if isinstance(p, str):
        p = param(p)
    first = parent_of(p)
    if not p.when_any or first is None:
        return []
    out = {}
    for g in p.when_any:
        full = p.when + g
        name = full[-1][0]
        if name != first[0]:
            out.setdefault(name, []).append(full)
    return list(out.items())


def condition_text(p):
    """Plain-language 'applies when …' for a param ('always' when unconditional)."""
    parts = [pred.describe(name) for name, pred in p.when]
    if p.when_any:
        alts = [" and ".join(pred.describe(n) for n, pred in g) for g in p.when_any]
        parts.append("(" + ") or (".join(alts) + ")" if len(alts) > 1 else alts[0])
    return " and ".join(parts) if parts else "always"


def choices_for(p):
    """[(value, label)] for a choice / multichoice param, in code order."""
    if isinstance(p, str):
        p = param(p)
    values = p.choices or _ENUM_CHOICES.get(p.name) or _ENUM_LIST.get(p.name)
    if values is None:
        raise ValueError(f"{p.name} is not a choice parameter")
    return [(v, p.choice_labels.get(v, v)) for v in values]


# ═════════════════════════════════════════════════════════════════════════════
# Composite kinds: a mode plus (maybe) a sub-value
# ═════════════════════════════════════════════════════════════════════════════
class Mode:
    def __init__(self, key, label, sub=None):
        self.key, self.label, self.sub = key, label, sub   # sub: Param or None


def _sub(p, kind, label, **kw):
    return Param(p.name, p.section, label, p.help, kind, **kw)


def modes_for(p, value=None):
    """The modes of a composite param ('qbf', 'channel_n', 'hg')."""
    if p.kind == "qbf":
        return [
            Mode("auto", "Automatic global estimate (no data needed)"),
            Mode("value", "My 2-year flood at the outlet or a gauge",
                 _sub(p, "float", "2-year flood", unit="m³/s", min=0, min_exclusive=True)),
            Mode("formula", "A formula or regional preset",
                 _sub(p, "formula", "Formula or preset name")),
        ]
    if p.kind == "channel_n":
        modes = [
            Mode("off", "Same as the ground (no channel override)"),
            Mode("value", "One value for every river cell",
                 _sub(p, "float", "Channel n", min=0, min_exclusive=True)),
            Mode("order", "A value per stream order",
                 _sub(p, "order_table", "Channel n for order 1, 2, 3, …")),
            Mode("elevation", "Values by elevation band",
                 _sub(p, "elev_table", "Elevation limits and n", unit="m")),
            Mode("raster", "From a raster of n on river cells",
                 _sub(p, "file", "Channel n raster")),
        ]
        if value is not None and _channel_n_mode(value) == "custom":
            modes.append(Mode("custom", "Custom rule from your Python config (kept as is)"))
        return modes
    if p.kind == "hg":
        from .core.routing.surface import BIEGER_2015 as _HG_PRESETS
        return [
            Mode("preset", "A published regional curve (Bieger et al. 2015)",
                 _sub(p, "choice", "Curve", choices=list(_HG_PRESETS),
                      choice_labels=_hg_labels())),
            Mode("custom", "My own coefficients",
                 _sub(p, "hg_coeffs", "w_a, w_b, d_a, d_b")),
        ]
    raise ValueError(f"{p.name} ({p.kind}) is not a composite parameter")


def _hg_labels():
    names = {"usa": "US national", "lup": "Laurentian Upland", "apl": "Atlantic Plain",
             "ahi": "Appalachian Highlands", "ipl": "Interior Plains",
             "ihi": "Interior Highlands", "rms": "Rocky Mountain System",
             "imp": "Intermontane Plateaus", "pms": "Pacific Mountain System"}
    return {f"bieger_{k}": f"bieger_{k} — {v}" for k, v in names.items()}


def _channel_n_mode(v):
    if v is None:
        return "off"
    if isinstance(v, bool):
        return "custom"
    if isinstance(v, (int, float)):
        return "value"
    if isinstance(v, str):
        return "raster"
    if isinstance(v, dict) and v and all(isinstance(k, int) and not isinstance(k, bool) for k in v):
        return "order"
    if isinstance(v, (list, tuple)) and v and all(
            isinstance(x, (list, tuple)) and len(x) == 2 for x in v):
        return "elevation"
    return "custom"


def mode_of(p, value):
    """The mode key a composite *value* is in."""
    if p.kind == "qbf":
        from .core.routing.qbf import classify_qbf
        return classify_qbf(value)[0]
    if p.kind == "channel_n":
        return _channel_n_mode(value)
    if p.kind == "hg":
        return "custom" if isinstance(value, dict) else "preset"
    raise ValueError(f"{p.name} is not a composite parameter")


def split_composite(p, value):
    """(mode, sub-value) of a composite value."""
    mode = mode_of(p, value)
    if p.kind == "qbf":
        if mode == "value":
            return mode, float(value)
        if mode == "formula":
            return mode, str(value).strip()
        return mode, None
    if p.kind == "channel_n":
        if mode == "value":
            return mode, float(value)
        if mode == "elevation":
            return mode, [tuple(x) for x in value]
        return mode, (None if mode == "off" else value)
    return mode, value


def join_composite(p, mode, sub):
    """Inverse of split_composite: the Config value for (mode, sub-value)."""
    if mode in ("auto", "off"):
        return None
    if mode == "elevation":
        return [list(x) for x in sub]
    return sub


# ═════════════════════════════════════════════════════════════════════════════
# Text ⇄ value  (shared by the wizard, the form's text boxes and the docs)
# ═════════════════════════════════════════════════════════════════════════════
_NONE_WORDS = {"none", "null", "auto", "off", "-", "default"}
_TRUE_WORDS = {"y", "yes", "true", "on", "1"}
_FALSE_WORDS = {"n", "no", "false", "off", "0"}


def _num(s, what="a number"):
    try:
        return float(s)
    except (TypeError, ValueError):
        raise ValueError(f"{s!r} is not {what}.") from None


def _numbers(s, n=None, what="numbers"):
    parts = [x for x in re.split(r"[,;\s]+", s.strip().strip("()[]")) if x]
    vals = [_num(x) for x in parts]
    if n is not None and len(vals) != n:
        raise ValueError(f"Expected {n} {what}, got {len(vals)}.")
    return vals


def _clean_path(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1]
    return os.path.expanduser(s)


def check_value(p, value):
    """
    Validate an already-typed *value* for *p* (range, choice, shape) and return
    it normalised.  Raises ValueError with a plain-language message.
    """
    k = p.kind
    if value is None or (k in ("text", "file", "folder") and value == ""):
        if p.optional or (k == "choice" and p.name in _ENUM_NULLABLE):
            return None
        if k == "file" and value == "":
            return ""                                     # e.g. DEM_PATH: "download one"
        raise ValueError(f"{p.label} needs a value.")
    if k in ("float", "int"):
        if isinstance(value, bool):
            raise ValueError(f"{p.label} must be a number.")
        v = float(value)
        if k == "int":
            if v != int(v):
                raise ValueError(f"{p.label} must be a whole number.")
            v = int(v)
        if p.min is not None and (v < p.min or (p.min_exclusive and v == p.min)):
            raise ValueError(f"{p.label} must be {'more than' if p.min_exclusive else 'at least'} {p.min:g}.")
        if p.max is not None and v > p.max:
            raise ValueError(f"{p.label} must be at most {p.max:g}.")
        return v
    if k == "choice":
        valid = [c for c, _ in choices_for(p)]
        if p.name in _ENUM_CHOICES:
            from .config import _normalize_enum
            return _normalize_enum(p.name, value, _ENUM_CHOICES[p.name])
        if value not in valid:
            raise ValueError(f"{value!r} is not one of: {', '.join(valid)}.")
        return value
    if k == "multichoice":
        valid = [c for c, _ in choices_for(p)]
        vals = list(value)
        bad = [v for v in vals if v not in valid]
        if bad:
            raise ValueError(f"Unknown choice(s) {bad}; use: {', '.join(valid)}.")
        if len(vals) < p.min_items:
            raise ValueError(f"Choose at least {p.min_items}.")
        return [c for c in valid if c in vals]          # canonical order, no repeats
    if k == "latlon":
        lat, lon = (float(x) for x in value)
        if not -90 <= lat <= 90:
            hint = " Did you put longitude first? Latitude comes first." if -90 <= lon <= 90 else ""
            raise ValueError(f"Latitude {lat:g} is outside -90…90.{hint}")
        if not -180 <= lon <= 180:
            raise ValueError(f"Longitude {lon:g} is outside -180…180.")
        return (lat, lon)
    if k == "bbox":
        w, s, e, n = (float(x) for x in value)
        if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= 90 and -90 <= n <= 90):
            raise ValueError("Use longitudes -180…180 and latitudes -90…90, in the "
                             "order west, south, east, north.")
        if w >= e or s >= n:
            raise ValueError("West must be less than east and south less than north "
                             "(order: west, south, east, north).")
        return (w, s, e, n)
    if k == "order_table":
        table = {int(o): float(v) for o, v in dict(value).items()}
        if not table:
            raise ValueError(f"{p.label} needs at least one value.")
        if any(o < 1 for o in table) or any(v <= 0 for v in table.values()):
            raise ValueError("Orders start at 1 and values must be positive.")
        return table
    if k == "points":
        pts = [dict(x) for x in value]
        if not pts:
            return None if p.optional else []
        for i, pt in enumerate(pts, 1):
            has_loc = (("lat" in pt and "lon" in pt) or ("row" in pt and "col" in pt)
                       or ("easting" in pt and "northing" in pt))
            if not has_loc:
                raise ValueError(f"Point {i} needs a location (latitude, longitude).")
            if p.needs_csv and not pt.get("csv"):
                raise ValueError(f"Point {i} needs a hydrograph CSV file.")
        return pts
    if k == "qbf":
        from .core.routing.qbf import classify_qbf
        kind, v = classify_qbf(value)
        if kind == "value" and v <= 0:
            raise ValueError("The 2-year flood must be more than 0 m³/s.")
        return value if kind != "auto" else None
    if k == "formula":
        from .core.routing.qbf import QbfFormula
        QbfFormula(value)                                 # raises with a clear message
        return str(value).strip()
    if k == "channel_n":
        mode = _channel_n_mode(value)
        if mode == "value" and float(value) <= 0:
            raise ValueError("Channel n must be more than 0.")
        if mode == "elevation":
            return check_value(_sub(p, "elev_table", ""), value)
        if mode == "order":
            return check_value(_sub(p, "order_table", ""), value)
        return value
    if k == "elev_table":
        rows = [(float(a), float(b)) for a, b in value]
        if not rows:
            raise ValueError("Give at least one 'elevation: n' pair.")
        if [a for a, _ in rows] != sorted(a for a, _ in rows):
            raise ValueError("List the elevation limits from low to high.")
        if any(b <= 0 for _, b in rows):
            raise ValueError("Manning's n values must be positive.")
        return [list(r) for r in rows]
    if k == "hg":
        if isinstance(value, dict):
            return check_value(_sub(p, "hg_coeffs", ""), value)
        from .core.routing.surface import BIEGER_2015 as _HG_PRESETS
        if str(value).lower() not in _HG_PRESETS:
            raise ValueError(f"Unknown curve {value!r}; use one of {', '.join(_HG_PRESETS)} "
                             "or four numbers w_a, w_b, d_a, d_b.")
        return str(value).lower()
    if k == "hg_coeffs":
        need = ("w_a", "w_b", "d_a", "d_b")
        missing = [x for x in need if x not in value]
        if missing:
            raise ValueError(f"Missing coefficient(s): {', '.join(missing)}.")
        out = {x: float(value[x]) for x in need}
        if out["w_a"] <= 0 or out["d_a"] <= 0:
            raise ValueError("w_a and d_a must be positive.")
        return out
    if k == "datetime":
        return _parse_datetime(str(value))
    if k == "crs":
        return _parse_crs(str(value))
    if k == "bool":
        return bool(value)
    if k in ("file", "folder"):
        return os.path.expanduser(str(value))
    return value


def _parse_datetime(s):
    s = s.strip().replace("T", " ").rstrip("Z")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    raise ValueError(f"{s!r} is not a date and time; use 'YYYY-MM-DD HH:MM', "
                     "e.g. 2024-09-27 06:00.")


def _parse_crs(s):
    s = s.strip()
    if re.fullmatch(r"\d{4,6}", s):
        s = f"EPSG:{s}"
    if re.fullmatch(r"(?i)epsg:\d{4,6}", s):
        s = s.upper()
    try:
        from pyproj import CRS
        crs = CRS.from_user_input(s)
    except Exception:   # noqa: BLE001 — pyproj raises several types
        raise ValueError(f"{s!r} is not a coordinate system pyproj recognises; use an "
                         "EPSG code such as EPSG:32645.") from None
    if not crs.is_projected:
        raise ValueError(f"{s} is in degrees; the model grid needs a projected system "
                         "in metres, such as the UTM zone of your outlet.")
    return s


def parse_value(p, text):
    """
    Turn typed *text* into a value for *p* (the inverse of format_value).
    An empty string means "nothing" (None for optional params).  Raises
    ValueError with a plain-language message the user can act on.
    """
    if isinstance(p, str):
        p = param(p)
    s = "" if text is None else str(text).strip()
    k = p.kind
    low = s.lower()
    nullable = p.optional or (k == "choice" and p.name in _ENUM_NULLABLE)

    if k == "points":
        if low in _NONE_WORDS:
            return check_value(p, [])
        return check_value(p, _parse_points(s, p))
    if s == "" or (nullable and low in _NONE_WORDS and k not in ("bool",)):
        if nullable:
            return None
        return check_value(p, "" if k in ("file", "text", "folder") else None)

    if k in ("float", "int"):
        return check_value(p, _num(s, "a number"))
    if k == "bool":
        if low in _TRUE_WORDS:
            return True
        if low in _FALSE_WORDS:
            return False
        raise ValueError(f"{s!r} is not yes or no.")
    if k == "choice":
        return check_value(p, _match_choice(p, s))
    if k == "multichoice":
        if low in ("none", "-"):
            return check_value(p, [])
        return check_value(p, [_match_choice(p, x) for x in re.split(r"[,;\s]+", s) if x])
    if k == "latlon":
        return check_value(p, _numbers(s, 2, "numbers (latitude, longitude)"))
    if k == "bbox":
        return check_value(p, _numbers(s, 4, "numbers (west, south, east, north)"))
    if k == "order_table":
        if ":" in s:
            pairs = [x.split(":") for x in re.split(r"[,;]+", s.strip("{} ")) if x.strip()]
            return check_value(p, {int(_num(a)): _num(b) for a, b in pairs})
        return check_value(p, {i: v for i, v in enumerate(_numbers(s), start=1)})
    if k == "elev_table":
        rows = []
        for item in re.split(r"[,;]+", s.strip("[] ")):
            if not item.strip():
                continue
            if ":" not in item:
                raise ValueError("Write each band as 'upper elevation: n', e.g. "
                                 "1500: 0.06, 9000: 0.04.")
            a, b = item.split(":", 1)
            rows.append((_num(a), _num(b)))
        return check_value(p, rows)
    if k == "hg_coeffs":
        return check_value(p, dict(zip(("w_a", "w_b", "d_a", "d_b"),
                                       _numbers(s, 4, "coefficients"))))
    if k == "hg":
        if re.search(r"\d", s) and "," in s:
            return check_value(p, dict(zip(("w_a", "w_b", "d_a", "d_b"),
                                           _numbers(s, 4, "coefficients"))))
        return check_value(p, s)
    if k == "qbf":
        return check_value(p, float(s) if _looks_numeric(s) else s)
    if k == "channel_n":
        if _looks_numeric(s):
            return check_value(p, float(s))
        if s.startswith("{"):
            return check_value(p, {int(a): float(b)
                                   for a, b in _literal(s, dict).items()})
        if s.startswith("["):
            return check_value(p, [list(x) for x in _literal(s, list)])
        return check_value(p, _clean_path(s))
    if k in ("file", "folder"):
        return check_value(p, _clean_path(s))
    return check_value(p, s)


def _literal(s, typ):
    try:
        v = ast.literal_eval(s)
    except (ValueError, SyntaxError):
        raise ValueError(f"Could not read {s!r}.") from None
    if not isinstance(v, typ):
        raise ValueError(f"Could not read {s!r}.")
    return v


def _match_choice(p, s):
    """A choice by code number, exact name, or unique prefix (case-insensitive)."""
    options = [c for c, _ in choices_for(p)]
    s = s.strip()
    if s.isdigit():
        i = int(s)
        if 0 <= i < len(options):
            return options[i]
        raise ValueError(f"{s} is not one of the numbers 0–{len(options) - 1}.")
    low = s.lower()
    if low in options:
        return low
    hits = [c for c in options if c.startswith(low)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        # the words after the name in its label: "iii — wet" → "wet"
        desc = {c: label.split(" — ", 1)[1].lower() for c, label in choices_for(p)
                if " — " in label}
        exact = [c for c, d in desc.items() if d == low]
        words = [c for c, d in desc.items() if d.startswith(low)]
        if len(exact) == 1:
            return exact[0]
        if len(words) == 1:
            return words[0]
    listing = ", ".join(f"{i}={c}" for i, c in enumerate(options))
    if hits:
        raise ValueError(f"{s!r} could mean {' or '.join(hits)}; type more of the name.")
    raise ValueError(f"{s!r} is not an option. Choose one of: {listing}.")


_POINT_KEYS = ("name", "lat", "lon", "row", "col", "easting", "northing", "csv",
               "snap_to_channel", "snap_radius_cells")


def _parse_points(s, p):
    """
    One point per line: positional 'name, lat, lon[, csv]' and/or key=value
    fields (row=, col=, easting=, northing=, snap_radius_cells=, …).
    """
    pts = []
    for n, line in enumerate(s.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [f.strip() for f in line.split(",")]
        pt, positional = {}, []
        for f in fields:
            if "=" in f:
                key, val = (x.strip() for x in f.split("=", 1))
                if key not in _POINT_KEYS:
                    raise ValueError(f"Line {n}: unknown field {key!r}; use "
                                     f"{', '.join(_POINT_KEYS)}.")
                pt[key] = val
            else:
                positional.append(f)
        order = ["name", "lat", "lon"] + (["csv"] if p.needs_csv else [])
        if positional and not _looks_numeric(positional[0]):
            pass                                          # name first
        elif positional:
            order = order[1:]                             # no name given
        if len(positional) > len(order):
            raise ValueError(f"Line {n}: too many values; expected "
                             f"{', '.join(order)}.")
        for key, val in zip(order, positional):
            pt.setdefault(key, val)
        for key in ("lat", "lon", "easting", "northing"):
            if key in pt:
                pt[key] = _num(pt[key], f"a number for {key} on line {n}")
        for key in ("row", "col", "snap_radius_cells"):
            if key in pt:
                pt[key] = int(_num(pt[key], f"a whole number for {key} on line {n}"))
        if "snap_to_channel" in pt and isinstance(pt["snap_to_channel"], str):
            pt["snap_to_channel"] = pt["snap_to_channel"].lower() in _TRUE_WORDS
        if "csv" in pt:
            pt["csv"] = _clean_path(pt["csv"])
        if "lat" in pt and "lon" in pt:
            check_value(Param("", "", f"Line {n} location", "", "latlon"),
                        (pt["lat"], pt["lon"]))
        pts.append(pt)
    return pts


def _looks_numeric(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def _g(v):
    """Compact float formatting that round-trips (0.035, 1e-08, 400)."""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    r = repr(float(v))
    return r[:-2] if r.endswith(".0") else r


def format_value(p, value):
    """The text a user would type to get *value* (inverse of parse_value)."""
    if isinstance(p, str):
        p = param(p)
    k = p.kind
    if value is None:
        return ""
    if k == "bool":
        return "yes" if value else "no"
    if k in ("float", "int"):
        return _g(value)
    if k == "multichoice":
        return ", ".join(value)
    if k in ("latlon", "bbox"):
        return ", ".join(_g(x) for x in value)
    if k == "order_table":
        orders = sorted(int(o) for o in value)
        if orders == list(range(1, len(orders) + 1)):
            return ", ".join(_g(value[o]) for o in orders)
        return ", ".join(f"{o}: {_g(value[o])}" for o in orders)
    if k == "elev_table":
        return ", ".join(f"{_g(a)}: {_g(b)}" for a, b in value)
    if k == "hg_coeffs":
        return ", ".join(_g(value[x]) for x in ("w_a", "w_b", "d_a", "d_b"))
    if k == "hg":
        return format_value(_sub(p, "hg_coeffs", ""), value) if isinstance(value, dict) else str(value)
    if k == "qbf":
        return _g(value) if isinstance(value, (int, float)) else str(value)
    if k == "channel_n":
        mode = _channel_n_mode(value)
        if mode == "value":
            return _g(value)
        if mode == "order":
            return "{" + ", ".join(f"{o}: {_g(n)}" for o, n in sorted(value.items())) + "}"
        if mode == "elevation":
            return "[" + ", ".join(f"[{_g(a)}, {_g(b)}]" for a, b in value) + "]"
        if mode == "raster":
            return str(value)
        return repr(value)
    if k == "points":
        return "\n".join(_format_point(pt, p) for pt in value)
    return str(value)


def _format_point(pt, p):
    pt = dict(pt)
    out = []
    if "name" in pt:
        out.append(str(pt.pop("name")))
    if "lat" in pt and "lon" in pt:
        out += [_g(pt.pop("lat")), _g(pt.pop("lon"))]
        if p.needs_csv and "csv" in pt:
            out.append(str(pt.pop("csv")))
    for key in _POINT_KEYS:
        if key in pt:
            v = pt.pop(key)
            out.append(f"{key}={'yes' if v is True else 'no' if v is False else v}")
    out += [f"{k}={v}" for k, v in pt.items()]
    return ", ".join(out)


# ═════════════════════════════════════════════════════════════════════════════
# Small helpers shared by the front-ends
# ═════════════════════════════════════════════════════════════════════════════
def suggest_crs(values):
    """(EPSG string, reason) for the UTM zone of the outlet — or, when the
    whole DEM is modelled, of the DEM's centre — or (None, '')."""
    from .utils.crs import utm_epsg, describe_utm
    if values.get("MODEL_AREA") == "whole_dem":
        pt, where = _dem_centre(values), "the centre of your DEM"
    else:
        pt, where = values.get("OUTPUT_POINT"), "your outlet"
    try:
        epsg = utm_epsg(*pt)
    except (TypeError, ValueError):
        return None, ""
    if epsg is None:
        return None, ""
    return epsg, f"{describe_utm(epsg)}, the zone of {where}"


def _dem_centre(values):
    """(lat, lon) of the centre of DEM_BOUNDS_WGS84, else of the DEM file; None."""
    bounds = values.get("DEM_BOUNDS_WGS84")
    if not values.get("DEM_PATH") and bounds:
        try:
            w, s, e, n = (float(x) for x in bounds)
            return (s + n) / 2.0, (w + e) / 2.0
        except (TypeError, ValueError):
            return None
    path = values.get("DEM_PATH")
    if not path or not os.path.exists(path):
        return None
    try:
        import rasterio
        from rasterio.warp import transform_bounds
        with rasterio.open(path) as src:
            w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        return (s + n) / 2.0, (w + e) / 2.0
    except Exception:            # unreadable file / no CRS — no suggestion
        return None


def _same(a, b):
    """Value equality that treats tuples and lists alike (YAML round trips)."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return a == b


def config_changes(cfg):
    """{name: value} of catalogued params that differ from the Config defaults."""
    base = Config()
    return {p.name: getattr(cfg, p.name) for p in PARAMS
            if not _same(getattr(cfg, p.name), getattr(base, p.name))}


def earth_engine_uses(values):
    """
    [(what, required)] — the selected options that download from Earth Engine.
    required=False means the option falls back to an offline method.
    """
    return [(what, req) for what, req, _name in earth_engine_triggers(values)]


def earth_engine_triggers(values):
    """[(what, required, setting that asks for it)] — see earth_engine_uses."""
    v = values
    uses = []

    def use(what, required, name):
        uses.append((what, required, name))

    phys = v.get("RUNOFF_SOURCE") == "physical"
    mech = v.get("RUNOFF_MECHANISMS") or []
    sat, inf, imp = (phys and m in mech for m in
                     ("saturation_excess", "infiltration_excess", "impervious"))
    if _blank(v.get("DEM_PATH")) and v.get("DEM_BOUNDS_WGS84"):
        use("DEM download", True, "DEM_BOUNDS_WGS84")
    if str(v.get("PRECIP_METHOD", "")).startswith("imerg"):
        use("IMERG satellite rainfall", True, "PRECIP_METHOD")
    if v.get("RUNOFF_SOURCE") == "scs_cn" and v.get("RUNOFF_CN_SOURCE") == "gee":
        use("GCN250 curve numbers", True, "RUNOFF_CN_SOURCE")
    if (sat or inf) and v.get("VSA_SD_SOURCE") == "gee":
        use("SERVES soil-moisture deficit", True, "VSA_SD_SOURCE")
    if inf and v.get("GA_KSAT_SOURCE") == "gee":
        use("HiHydroSoil infiltration map", True, "GA_KSAT_SOURCE")
    if inf and v.get("GA_SUCTION_SOURCE") == "texture":
        use("SoilGrids soil texture", True, "GA_SUCTION_SOURCE")
    if v.get("MANNINGS_N_SOURCE") == "lcz" or (
            v.get("MANNINGS_N_SOURCE") == "lulc" and v.get("MANNINGS_N_LULC_PATH") == "gee"):
        use("land-cover roughness map", True, "MANNINGS_N_SOURCE")
    if imp and v.get("IMPERVIOUS_SOURCE") in ("lulc", "lcz"):
        use("impervious land-cover map", True, "IMPERVIOUS_SOURCE")
    if v.get("CHANNEL_ROUTING") and v.get("CHANNEL_GEOMETRY") == "discharge":
        try:
            from .core.routing.qbf import classify_qbf
            kind, f = classify_qbf(v.get("CHANNEL_QBF_M3S"))
        except ValueError:
            kind, f = None, None
        if kind == "auto":
            use("automatic bankfull flow (falls back to drainage area offline)", False,
                "CHANNEL_QBF_M3S")
        elif kind == "formula" and "P" in f.uses:
            use("mean annual rain P in the bankfull-flow formula", True, "CHANNEL_QBF_M3S")
    return uses


def problems(cfg):
    """Config.validate() as a list of plain messages ([] when the config is fine)."""
    try:
        cfg.validate()
    except ValueError as exc:
        lines = str(exc).splitlines()[1:]
        return [ln.strip().lstrip("•").strip() for ln in lines if ln.strip()]
    return []


def params_in_message(message):
    """Catalogued parameter names mentioned in a validation message, in order."""
    found = []
    for name in re.findall(r"\b[A-Z][A-Za-z0-9_]*[A-Za-z0-9]\b", message):
        if name in PARAM_BY_NAME and name not in found:
            found.append(name)
    return found
