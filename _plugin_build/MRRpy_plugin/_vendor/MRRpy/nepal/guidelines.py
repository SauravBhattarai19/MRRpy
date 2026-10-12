# -*- coding: utf-8 -*-
"""
guidelines.py
=============
What the Nepali agency manuals ask for, as presets the interfaces offer
(compendium §2 and §7):

* ``AGENCIES``    each manual's flood methods — choosing a manual ticks the
                  methods it names;
* ``STRUCTURES``  design return periods by type of structure — choosing a
                  structure ticks its return periods;
* ``recommend_methods()``  the compendium's quick guide ("which method to
                  use for what") applied to one catchment.

Only methods MRRpy-Nepal implements can be ticked.  A manual's other
methods are listed in ``Agency.not_yet`` so the gap stays visible.  The
presets say which methods a manual *names* (per the compendium); they are
not a statement that a design complies with that manual.
"""

from .methods import FLOOD_METHODS, TOR_RETURN_PERIODS, resolve_methods


class Agency:
    """A manual and the flood methods it names."""

    def __init__(self, key, label, methods, not_yet=(), note=""):
        self.key, self.label = key, label
        self.methods = tuple(methods)
        self.not_yet = tuple(not_yet)
        self.note = note

    def __repr__(self):
        return f"Agency({self.key!r})"


AGENCIES = {a.key: a for a in [
    Agency("recommended", "Recommended for this catchment (compendium quick guide)", (),
           note="Chosen from the catchment's size and the data you have (compendium §7)."),
    Agency("dowri_2019", "DoWRI — Headworks & Cross-Drainage Guidelines (2019)",
           ("wecs_dhm", "modified_dickens", "area_ratio", "rational"),
           not_yet=("B.D. Richards",),
           note="HYDEST (WECS/DHM), Modified Dickens, B.D. Richards, catchment area ratio and "
                "Rational."),
    Agency("dowri_pdsp_1990", "DoWRI (ex-DoI) — PDSP Irrigation Design Manuals (1990)",
           ("wecs_dhm", "modified_dickens", "rational", "frequency"),
           note="WECS/DHM, Modified Dickens, Rational for small catchments, and frequency "
                "analysis where there is a gauge."),
    Agency("dolidar_2015", "DoLIDAR — Small-Scale Irrigation Design Manual (2015)",
           ("dhm_2004", "rational", "frequency"),
           note="Sharma & Adhikari (DHM 2004), Rational with C of 0.2–0.4, Gumbel and LP-III."),
    Agency("doed_2018", "DoED — Hydropower Study Guidelines (2003/2018)",
           ("wecs_dhm", "dhm_2004", "mhsp_1997", "area_ratio", "frequency"),
           not_yet=("PMF", "GLOF/CLOF assessment"),
           note="WECS/DHM, DHM 2004, MHSP, catchment area ratio and frequency analysis; PMF "
                "and GLOF/CLOF checks for large headworks."),
    Agency("wecs_2019", "WECS — Flood Control and Management Manual (2019)",
           ("wecs_dhm", "dhm_2004", "specific_discharge", "rational"),
           note="WECS/DHM, DHM 2004, the specific-discharge method, and Rational up to 50 km²."),
    Agency("dor_bridge", "DoR — Nepal Bridge Standards 2067 and Bridge Hydrology Guidelines "
                         "(2021/22)",
           ("rational", "physics", "frequency", "wecs_dhm", "dhm_2004", "modified_dickens"),
           not_yet=("B.D. Richards", "IRC-based methods"),
           note="Bridge Standards Cl. 3.2 do not allow formulas developed for other catchments, "
                "so site-specific methods (rainfall-runoff, gauge records, flood marks) lead "
                "and the Nepal formulas serve as checks; 100-year design flood."),
    Agency("aepc_2004", "AEPC — Micro-Hydro Design Aids (2004)", ("wecs_dhm",),
           note="WECS/DHM, which the manual calls reliable only above 100 km² and not in the "
                "Siwalik or Terai."),
    Agency("nea_1997", "NEA — Medium Hydropower Study Project (1997)", ("mhsp_1997",),
           note="The MHSP regional power law."),
    Agency("all", "Every method (except the comparison-only formulas)",
           tuple(k for k, m in FLOOD_METHODS.items() if m.group != "comparison")),
]}


class Structure:
    """A type of structure and the return periods its design uses."""

    def __init__(self, key, label, design, return_periods, source, freeboard=""):
        self.key, self.label = key, label
        self.design = tuple(design)                   # the design return period(s)
        self.return_periods = tuple(return_periods)   # what to tick (design + context)
        self.source, self.freeboard = source, freeboard

    def __repr__(self):
        return f"Structure({self.key!r})"

    def describe(self):
        """'Bridge: 100-year flood (DoR …); freeboard …'."""
        if len(self.design) == 1:
            years = f"{self.design[0]}-year flood"
        else:
            years = f"{self.design[0]}- to {self.design[-1]}-year flood"
        text = f"{self.label}: {years} ({self.source})"
        if self.freeboard:
            text += f"; freeboard {self.freeboard}"
        return text


STRUCTURES = {s.key: s for s in [
    Structure("study", "Study — every ToR return period", (100,), TOR_RETURN_PERIODS,
              "DoWRI pilot ToR: 2–500 years, 500 years as a safety check for higher-risk "
              "structures"),
    Structure("bridge", "Bridge", (100,), (2, 100), "DoR Nepal Bridge Standards 2067, Cl. 3.2",
              freeboard="at least 1.0 m, rising to more than 2.0 m with discharge (Cl. 8.1)"),
    Structure("culvert", "Culvert", (25,), (2, 25),
              "DoWRI Headworks & Cross-Drainage Guidelines 2019"),
    Structure("aqueduct", "Aqueduct", (50,), (2, 50),
              "DoWRI Headworks & Cross-Drainage Guidelines 2019"),
    Structure("weir", "Weir", (50, 100), (2, 50, 100),
              "DoWRI Headworks & Cross-Drainage Guidelines 2019; DoLIDAR manual 2015"),
    Structure("barrage", "Barrage", (100, 500), (2, 100, 500),
              "DoWRI Headworks & Cross-Drainage Guidelines 2019"),
    Structure("embankment", "River embankment", (50, 100), (2, 50, 100),
              "DoWRI Headworks & Cross-Drainage Guidelines 2019; DWIDM/ADB embankment "
              "projects use 50 years including climate change",
              freeboard="1.0–1.5 m (DWIDM Pocket Diary)"),
    Structure("intake", "Small irrigation intake", (10, 25), (2, 10, 25),
              "DoLIDAR Small-Scale Irrigation Design Manual 2015"),
]}


def recommend_methods(descriptors, has_rainfall=False, has_gauge=False, has_donor=False):
    """
    The compendium's quick guide (§7) for one catchment.

    Returns (method keys, reasons).  The physics model is always included —
    it is the rainfall-runoff model the guide calls good practice; it waits
    for a design rainfall like the Rational method.
    """
    a = descriptors.area_km2
    keys, why = [], []
    if a < 12:
        keys += ["rational", "modified_dickens", "physics"]
        why.append("Under 12 km²: the Rational method with local rainfall, Modified Dickens as "
                   "the common check, and a rainfall-runoff check (here the physics model). "
                   "Add surveyed flood marks.")
    elif a <= 500:
        keys += ["wecs_dhm", "dhm_2004", "modified_dickens", "mhsp_1997", "specific_discharge",
                 "physics"]
        why.append("12–500 km² with no gauge: WECS/DHM, DHM 2004, Modified Dickens and MHSP are "
                   "the common methods. Good practice adds a rainfall-runoff model (the physics "
                   "model) and keeps the national methods as checks.")
    else:
        keys += ["wecs_dhm", "dhm_2004", "mhsp_1997", "specific_discharge", "modified_dickens",
                 "physics"]
        why.append("Above 500 km²: the national methods, which were fitted mostly to rivers of "
                   "this size, together with the physics model.")
    if has_gauge:
        keys.append("frequency")
        why.append("A gauge at the site: frequency analysis with confidence intervals.")
    if has_donor:
        keys.append("area_ratio")
        why.append("A gauge nearby: catchment area ratio from a hydrologically similar donor.")
    if descriptors.is_chure_or_terai:
        why.append("A Chure/Terai stream: the regional formulas use area only here, so give the "
                   "rainfall-based methods and local flood marks more weight (compendium §6).")
    if not has_rainfall:
        why.append("Give the 24-hour design rainfall (or a station's annual maxima) for the "
                   "Rational method and the physics model.")
    return resolve_methods(keys), why


def methods_for(agency, descriptors=None, **data_flags):
    """
    The method keys an agency preset ticks.  'recommended' needs the
    catchment (and optionally has_rainfall / has_gauge / has_donor).
    """
    a = AGENCIES[agency] if isinstance(agency, str) else agency
    if a.key == "recommended":
        if descriptors is None:
            return list(resolve_methods(None))
        return recommend_methods(descriptors, **data_flags)[0]
    return resolve_methods(a.methods)


def return_periods_for(structure):
    """The return periods a structure preset ticks."""
    s = STRUCTURES[structure] if isinstance(structure, str) else structure
    return list(s.return_periods)


def describe_presets():
    """Printable list of the agency and structure presets."""
    lines = ["Agency / manual presets (--agency):"]
    for a in AGENCIES.values():
        lines.append(f"  {a.key:<16} {a.label}")
        if a.methods:
            lines.append(f"  {'':<16} methods: {', '.join(a.methods)}")
        if a.not_yet:
            lines.append(f"  {'':<16} not yet in MRRpy-Nepal: {', '.join(a.not_yet)}")
    lines += ["", "Structure presets (--structure):"]
    for s in STRUCTURES.values():
        lines.append(f"  {s.key:<16} {s.describe()}")
    return "\n".join(lines) + "\n"
