# -*- coding: utf-8 -*-
"""
methods.py
==========
The flood-estimation methods used in Nepal (compendium *Nepal Flood
Estimation Methods*, §3), each a small documented function, and a registry
that runs any selection of them for one catchment:

    from MRRpy.nepal import CatchmentDescriptors, estimate_floods
    site = CatchmentDescriptors(area_km2=65)
    est = estimate_floods(site, ["wecs_dhm", "dhm_2004", "modified_dickens"])
    est.table          # Q (m³/s) by return period, with a status per method
    est.envelope       # min / median / max of the official regional methods

Groups
------
regional    official regressions on the catchment: WECS/DHM 1990 (HYDEST),
            DHM 2004 (Sharma & Adhikari), MHSP 1997 (NEA), Modified Dickens,
            specific discharge (WECS 2019), and WECS/DHM daily floods.
rainfall    the Rational method (Kirpich + Mononobe) and the MRRpy physics
            model with a design storm (run by ``MRRpy.nepal.physics``).
gauge       frequency analysis at the site; catchment area ratio from a
            donor gauge.
comparison  Dickens, Ryves, Inglis — Indian formulas, shown for comparison
            only and never part of the official range.

Every coefficient is the one printed in the compendium; its "Note on
sources" caveats travel with each method (``FloodMethod.source``).
"""

import math
import re

import numpy as np
import pandas as pd

from . import frequency as fq
from .descriptors import CatchmentDescriptors

#: The return periods of the DoWRI pilot ToR (500 years = safety check).
TOR_RETURN_PERIODS = (2, 5, 10, 20, 50, 100, 200, 500)

#: Return periods offered as tick boxes by the interfaces.
OFFERED_RETURN_PERIODS = (2, 5, 10, 20, 25, 50, 100, 200, 500, 1000)

GROUPS = {
    "regional": "Official regional formulas (need only the catchment)",
    "rainfall": "Rainfall-based (need a design rainfall)",
    "gauge": "Gauge-based (need a flow record)",
    "comparison": "Comparison only — Indian formulas, not for design",
}

STATUS_TEXT = {
    "ok": "ok",
    "caution": "use with caution",
    "outside": "outside its range",
    "needs input": "needs input",
    "not run": "not run",
    "comparison": "comparison only",
}


# ═════════════════════════════════════════════════════════════════════════════
# Shared pieces
# ═════════════════════════════════════════════════════════════════════════════
def normal_variate(T):
    """Standard normal variate S for return period T (0 for 2 years, 2.326 for 100)."""
    from scipy.stats import norm
    return norm.ppf(1.0 - 1.0 / fq.as_return_periods(T))


def lognormal_quantiles(q2, q100, T):
    """ln Q_T = ln Q2 + S·ln(Q100/Q2)/S100 — the WECS/DHM interpolation (§3.1)."""
    S = normal_variate(T)
    S100 = float(normal_variate(100.0)[0])
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.exp(np.log(q2) + S * np.log(q100 / q2) / S100)


def gumbel_variate(T):
    """Gumbel reduced variate y_T = −ln(−ln(1 − 1/T)) (used to interpolate rainfall)."""
    return -np.log(-np.log(1.0 - 1.0 / fq.as_return_periods(T)))


def _tabulated(T, tab, value_at):
    """
    Values of a method tabulated at a few return periods: exact at a
    tabulated T, interpolated (ln Q linear in the normal variate S) between
    them, NaN outside.  Returns (Q, flags).
    """
    tab = sorted(float(t) for t in tab)
    lnq = np.log([value_at(t) for t in tab])
    s_tab = normal_variate(tab)
    out = np.full(T.shape, np.nan)
    flags = []
    for i, t in enumerate(T):
        hit = [k for k, tt in enumerate(tab) if math.isclose(tt, t)]
        if hit:
            out[i] = math.exp(lnq[hit[0]])
            flags.append("")
        elif tab[0] < t < tab[-1]:
            out[i] = math.exp(np.interp(float(normal_variate(t)[0]), s_tab, lnq))
            flags.append("interpolated")
        else:
            flags.append("not tabulated")
    return out, flags


# ═════════════════════════════════════════════════════════════════════════════
# The formulas (pure functions — usable on their own)
# ═════════════════════════════════════════════════════════════════════════════
#: WECS/DHM (1990): Q = a·(A3000 + 1)^b  (compendium §3.1).
WECS_DHM_1990 = {
    "instantaneous": {"q2": (1.8767, 0.8783), "q100": (14.63, 0.7342)},
    "daily": {"q2": (0.8154, 0.9527), "q100": (4.144, 0.8448)},
}


def wecs_dhm_1990(a3000_km2, T, daily=False):
    """WECS/DHM 1990 (HYDEST) flood of return period T [m³/s] from the area below 3,000 m."""
    c = WECS_DHM_1990["daily" if daily else "instantaneous"]
    a = float(a3000_km2) + 1.0
    return lognormal_quantiles(c["q2"][0] * a ** c["q2"][1], c["q100"][0] * a ** c["q100"][1], T)


#: Sharma & Adhikari (DHM 2004): Q = a·A3000^b  (compendium §3.2).
DHM_2004 = {"q2": (2.29, 0.86), "q100": (20.7, 0.72)}


def dhm_2004(a3000_km2, T):
    """DHM 2004 (Sharma & Adhikari) flood of return period T [m³/s]."""
    a = float(a3000_km2)
    return lognormal_quantiles(DHM_2004["q2"][0] * a ** DHM_2004["q2"][1],
                               DHM_2004["q100"][0] * a ** DHM_2004["q100"][1], T)


#: MHSP 1997 (NEA): Q_T = k·A^b by region and return period (compendium §3.3,
#: as reproduced in Subedi et al. 2022).
MHSP_1997 = {
    "western": {5: (2.0409, 0.8632), 20: (3.2895, 0.8510), 50: (4.2570, 0.8444), 100: (5.2225, 0.8352)},
    "central": {5: (1.6762, 0.9660), 20: (3.2303, 0.9281), 50: (4.6090, 0.9071), 100: (5.9865, 0.8888)},
    "eastern": {5: (7.4008, 0.7862), 20: (13.0848, 0.7535), 50: (17.6058, 0.7380), 100: (21.5181, 0.7281)},
}
MHSP_REGIONS = ("western", "central", "eastern")


def mhsp_1997(area_km2, T, region):
    """MHSP 1997 flood [m³/s]; (Q, flags) — T outside 5…100 years gives NaN."""
    table = MHSP_1997[_mhsp_region(region)]
    a = float(area_km2)
    return _tabulated(fq.as_return_periods(T), table, lambda t: table[int(t)][0] * a ** table[int(t)][1])


def _mhsp_region(region):
    key = str(region or "").strip().lower()
    key = {"west": "western", "w": "western", "central": "central", "c": "central",
           "east": "eastern", "e": "eastern"}.get(key, key)
    if key not in MHSP_1997:
        raise ValueError(f"MHSP region must be one of {', '.join(MHSP_REGIONS)} (got {region!r}).")
    return key


def modified_dickens(area_km2, T, snow_km2=0.0, denominator="A+a"):
    """
    Modified Dickens flood [m³/s] (compendium §3.5):
        Q_T = C_T·A^(3/4),  C_T = 2.342·log10(0.6T)·log10(1185/p) + 4,
        p = 100·(a + 6)/(A + a)   (denominator="A" uses the variant /A).
    Returns (Q, C_T, p).
    """
    A, a = float(area_km2), float(snow_km2)
    p = 100.0 * (a + 6.0) / ((A + a) if denominator == "A+a" else A)
    T = fq.as_return_periods(T)
    C = 2.342 * np.log10(0.6 * T) * math.log10(1185.0 / p) + 4.0
    return C * A ** 0.75, C, p


#: Specific discharge (WECS 2019 manual, data to 1996): q_T = a·A^b [m³/s/km²]
#: (compendium §3.15, as printed in Subedi et al. 2022).
SPECIFIC_DISCHARGE_2019 = {2: (4.2, -0.30), 25: (30.8, -0.44), 50: (43.3, -0.46), 100: (61.4, -0.49)}


def specific_discharge(area_km2, T):
    """Specific-discharge flood Q_T = q_T·A [m³/s]; (Q, flags) for T in 2…100 years."""
    a = float(area_km2)
    tab = SPECIFIC_DISCHARGE_2019
    return _tabulated(fq.as_return_periods(T), tab, lambda t: tab[int(t)][0] * a ** tab[int(t)][1] * a)


def kirpich_tc_minutes(length_m, slope):
    """Kirpich time of concentration t_c = 0.0195·L^0.77·S^−0.385 [min] (L in m, S in m/m)."""
    return 0.0195 * float(length_m) ** 0.77 * float(slope) ** -0.385


def mononobe_intensity(r24_mm, duration_h):
    """Mononobe rainfall intensity I = (R24/24)·(24/t)^(2/3) [mm/h] for a duration t [h]."""
    return (np.asarray(r24_mm, dtype=float) / 24.0) * (24.0 / float(duration_h)) ** (2.0 / 3.0)


def rational_peak(c, intensity_mm_h, area_km2):
    """Rational method Q = C·I·A/3.6 [m³/s] (A in km², I in mm/h)."""
    return float(c) * np.asarray(intensity_mm_h, dtype=float) * float(area_km2) / 3.6


def dickens(area_km2, constant=11.4):
    """Original Dickens maximum flood Q = C_D·A^(3/4) [m³/s] — no return period."""
    return float(constant) * float(area_km2) ** 0.75


def ryves(area_km2, constant=10.2):
    """Ryves maximum flood Q = C_R·A^(2/3) [m³/s] — no return period."""
    return float(constant) * float(area_km2) ** (2.0 / 3.0)


def inglis(area_km2):
    """Inglis maximum flood Q = 124·A/√(A + 10.4) [m³/s] — no return period."""
    a = float(area_km2)
    return 124.0 * a / math.sqrt(a + 10.4)


def area_ratio(q_donor, area_site_km2, area_donor_km2, exponent=0.8):
    """Catchment area ratio Q_site = Q_donor·(A_site/A_donor)^n."""
    return np.asarray(q_donor, dtype=float) * (float(area_site_km2) / float(area_donor_km2)) ** float(exponent)


def slope_area_discharge(area_m2, perimeter_m, slope, n):
    """Peak from a surveyed flood mark: Q = (1/n)·A·R^(2/3)·S^(1/2), R = A/P (§3.13)."""
    area, per = float(area_m2), float(perimeter_m)
    return (1.0 / float(n)) * area * (area / per) ** (2.0 / 3.0) * math.sqrt(float(slope))


#: Typical runoff coefficients C for the Rational method (compendium §3.8).
RUNOFF_COEFFICIENTS = {"forest": 0.3, "agriculture": 0.5, "barren": 0.25, "built-up": 0.85}


_PAIR = re.compile(r"(\d+(?:\.\d+)?)\s*[:=]\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")


def parse_table(text):
    """
    Typed 'return period: value' pairs → {T: value}; empty text → None.
    Accepts '2: 120, 100: 250', '2=120 100=250' and mixtures (commas,
    semicolons, spaces or new lines between the pairs).
    """
    s = str(text or "").strip()
    if not s:
        return None
    pairs = _PAIR.findall(s)
    rest = _PAIR.sub(" ", s).replace(",", " ").replace(";", " ").strip()
    if not pairs or rest:
        raise ValueError(f"{s!r}: write 'return period: value' pairs, e.g. 2: 120, 100: 250 "
                         "(or 2=120 100=250).")
    return {float(t): float(v) for t, v in pairs}


# ═════════════════════════════════════════════════════════════════════════════
# Inputs the methods ask for (one catalogue for the form, the CLI and QGIS)
# ═════════════════════════════════════════════════════════════════════════════
class Input:
    """One input a method needs beyond the catchment numbers."""

    def __init__(self, key, label, help, kind, default=None, unit="", choices=None,
                 minimum=None, maximum=None, example=None, advanced=False):
        self.key, self.label, self.help, self.kind = key, label, help, kind
        self.default, self.unit, self.choices = default, unit, choices
        self.minimum, self.maximum, self.example = minimum, maximum, example
        self.advanced = advanced

    def __repr__(self):
        return f"Input({self.key!r}, kind={self.kind!r})"


INPUTS = {i.key: i for i in [
    Input("mhsp_region", "MHSP region",
          "Western, Central or Eastern Nepal — the region whose MHSP constants apply. The "
          "compendium notes the far west (e.g. Kailali) probably uses the Western pair; "
          "check the MHSP 1997 report.", "choice", choices=MHSP_REGIONS, example="western"),
    Input("runoff_coefficient", "Runoff coefficient C",
          "Share of the rain that runs off: about 0.3 forest, 0.5 agriculture, 0.25 barren, "
          "0.85 built-up (Subedi et al. 2022); the DoLIDAR manual suggests 0.2–0.4.",
          "float", minimum=0.0, maximum=1.0, example=0.45),
    Input("rain_24h", "24-hour design rainfall R24",
          "The T-year 24-hour rainfall at the site, from DHM data or an IDF study, as "
          "'T: mm' pairs, e.g. 2: 120, 100: 250. Return periods in between are "
          "interpolated on a Gumbel scale.", "table", unit="mm", example={2: 120.0, 100: 250.0}),
    Input("rain_annual_max", "Annual maximum daily rainfall",
          "One value per year from a DHM station near the site (mm), or a CSV of them; "
          "R24 for every return period is then fitted.", "series", unit="mm"),
    Input("rain_distribution", "Distribution for the rainfall series",
          "Which distribution to fit to the annual maximum rainfall.", "choice",
          default="gumbel", choices=fq.DISTRIBUTIONS),
    Input("rain_fixed_day_factor", "Daily-to-24-hour factor",
          "DHM records are once-a-day readings. WMO practice multiplies a fixed-day maximum "
          "by 1.13 to get the true 24-hour maximum; 1 uses the series as it is.",
          "float", default=1.0, minimum=1.0, maximum=1.5, example=1.13, advanced=True),
    Input("flood_annual_max", "Annual maximum floods at the site",
          "One instantaneous peak per year at a gauge on this river (m³/s), or a CSV of "
          "them. At least 10 years; about 20 or more for a dependable fit.", "series",
          unit="m³/s"),
    Input("flood_distribution", "Distribution for the flood series",
          "Gumbel and Log-Pearson III are named in the DoLIDAR manual; GEV (L-moments) is "
          "the modern choice.", "choice", default="gumbel", choices=fq.DISTRIBUTIONS),
    Input("donor_area_km2", "Donor catchment area",
          "Area of the gauged, hydrologically similar catchment.", "float", unit="km²",
          minimum=0.0, example=1148.0),
    Input("donor_floods", "Donor design floods",
          "The donor gauge's T-year floods as 'T: m³/s' pairs (or give its annual maxima).",
          "table", unit="m³/s", example={2: 900.0, 100: 4200.0}),
    Input("donor_annual_max", "Donor annual maximum floods",
          "One peak per year at the donor gauge (m³/s), or a CSV; fitted with the flood "
          "distribution.", "series", unit="m³/s"),
    Input("area_ratio_exponent", "Area-ratio exponent n",
          "Q_site = Q_donor·(A_site/A_donor)^n: about 0.5–0.85 for floods (0.75–0.85 for "
          "mountain streams); 1 for mean flows.", "float", default=0.8, minimum=0.0,
          maximum=1.0, example=0.75),
    Input("dickens_constant", "Dickens constant C_D",
          "6 for the North Indian plains, 11–14 for North Indian hills, 14–28 Central India.",
          "float", default=11.4, minimum=0.0, example=14.0),
    Input("ryves_constant", "Ryves constant C_R",
          "6.8 near the coast, 8.5 at 80–240 km, 10.2 near hills (South India).",
          "float", default=10.2, minimum=0.0, example=8.5),
]}


# ═════════════════════════════════════════════════════════════════════════════
# The registry
# ═════════════════════════════════════════════════════════════════════════════
class FloodMethod:
    """
    One method: what it is, who uses it, what it needs, and how to compute it.

    compute(desc, T, inputs) → (Q array, per-T flags, notes, band or None)
    check(desc, inputs)      → [(level, message)], level 'caution' | 'outside'
    """

    def __init__(self, key, name, group, year, used_by, gives, formula, source="",
                 inputs=(), needs=(), tabulated=None, peak=True, compute=None, check=None,
                 section=""):
        self.key, self.name, self.group, self.year = key, name, group, year
        self.used_by, self.gives, self.formula, self.source = used_by, gives, formula, source
        self.inputs = tuple(inputs)          # keys of INPUTS (alternatives as tuples)
        self.needs = tuple(needs)            # descriptor fields that must be known
        self.tabulated = tabulated
        self.peak = peak                     # instantaneous peak (False: daily mean / no T)
        self._compute = compute
        self._check = check
        self.section = section

    def __repr__(self):
        return f"FloodMethod({self.key!r})"

    def missing(self, desc, inputs):
        """Plain list of what is missing before this method can run."""
        out = []
        for f in self.needs:
            v = getattr(desc, f, None)
            if v is None or not (isinstance(v, (int, float)) and v > 0):
                out.append(_NEED_TEXT.get(f, f))
        for item in self.inputs:
            alts = item if isinstance(item, tuple) else (item,)
            if not any(_given(inputs.get(k)) for k in alts):
                out.append(" or ".join(INPUTS[k].label for k in alts))
        return out

    def run(self, desc, T, inputs):
        """{status, Q, flags, notes, band} for this method (never raises on bad input)."""
        if self._compute is None:
            return dict(status="not run", Q=np.full(T.shape, np.nan), flags=[""] * T.size,
                        notes=["runs the MRRpy model with a design storm — use NepalStudy "
                               "or MRRpy.nepal.physics.run_design_floods"], band=None)
        missing = self.missing(desc, inputs)
        if missing:
            return dict(status="needs input", Q=np.full(T.shape, np.nan),
                        flags=[""] * T.size, notes=["needs " + "; ".join(missing)], band=None)
        try:
            Q, flags, notes, band = self._compute(desc, T, inputs)
        except ValueError as exc:
            return dict(status="needs input", Q=np.full(T.shape, np.nan),
                        flags=[""] * T.size, notes=[str(exc)], band=None)
        checks = self._check(desc, inputs) if self._check else []
        levels = [lvl for lvl, _m in checks]
        status = ("comparison" if self.group == "comparison" else
                  "outside" if "outside" in levels else
                  "caution" if "caution" in levels else "ok")
        notes = [m for _l, m in checks] + list(notes)
        return dict(status=status, Q=np.asarray(Q, dtype=float), flags=list(flags),
                    notes=notes, band=band)


_NEED_TEXT = {"flow_length_km": "the longest flow path L (measure it from the DEM, or type it)",
              "flow_path_slope": "the slope S of the longest flow path"}


def _given(v):
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (dict, list, tuple, np.ndarray, pd.Series)):
        return len(v) > 0
    return True


# ── compute / check functions ────────────────────────────────────────────────
def _extrapolation_flags(T, limit=100.0):
    return ["extrapolated" if t > limit else "" for t in T]


def _c_wecs(desc, T, inp):
    flags = _extrapolation_flags(T)
    notes = desc.assumptions()
    return wecs_dhm_1990(desc.a3000, T), flags, notes, None


def _c_wecs_daily(desc, T, inp):
    return (wecs_dhm_1990(desc.a3000, T, daily=True), _extrapolation_flags(T),
            ["daily mean flood, not an instantaneous peak"], None)


def _c_dhm2004(desc, T, inp):
    if desc.a3000 <= 0:                       # no "+1" in DHM 2004: no area, no flood
        return np.full(T.shape, np.nan), [""] * T.size, [], None
    return dhm_2004(desc.a3000, T), _extrapolation_flags(T), desc.assumptions(), None


def _c_mhsp(desc, T, inp):
    region = _mhsp_region(inp.get("mhsp_region"))
    Q, flags = mhsp_1997(desc.area_km2, T, region)
    notes = [f"{region.capitalize()} region"]
    if any(f == "not tabulated" for f in flags):
        notes.append("MHSP tabulates only T = 5, 20, 50 and 100 years")
    return Q, flags, notes, None


def _c_dickens_mod(desc, T, inp):
    Q, C, p = modified_dickens(desc.area_km2, T, desc.snow)
    return Q, [""] * T.size, [f"p = {p:.4g} (snow area {desc.snow:.4g} km²)"], None


def _c_specific(desc, T, inp):
    Q, flags = specific_discharge(desc.area_km2, T)
    notes = []
    if any(f == "not tabulated" for f in flags):
        notes.append("tabulated only for T = 2, 25, 50 and 100 years")
    return Q, flags, notes, None


def design_rainfall(inputs, T):
    """
    The T-year 24-hour rainfall [mm] from the inputs: the typed 'T: mm' table
    (interpolated on a Gumbel scale between the given return periods), or a
    distribution fitted to the annual maximum series.  Returns
    (R24 array with NaN where unknown, flags, notes, FrequencyFit or None).
    """
    T = fq.as_return_periods(T)
    table = inputs.get("rain_24h")
    if _given(table):
        tab = {float(k): float(v) for k, v in dict(table).items()}
        if any(v <= 0 for v in tab.values()):
            raise ValueError("24-hour rainfall values must be above 0 mm")
        ts = np.array(sorted(tab))
        ys = gumbel_variate(ts) if ts.size else ts
        vals = np.array([tab[t] for t in ts])
        out, flags = np.full(T.shape, np.nan), []
        for i, t in enumerate(T):
            hit = [k for k, tt in enumerate(ts) if math.isclose(tt, t)]
            if hit:
                out[i] = vals[hit[0]]
                flags.append("")
            elif ts.size > 1 and ts[0] < t < ts[-1]:
                out[i] = float(np.interp(float(gumbel_variate(t)[0]), ys, vals))
                flags.append("rain interpolated")
            else:
                flags.append("no rainfall for this T")
        return out, flags, ["R24 from the typed table"], None
    series = inputs.get("rain_annual_max")
    if _given(series):
        values = fq.read_series(series) if isinstance(series, str) else series
        factor = float(inputs.get("rain_fixed_day_factor") or 1.0)
        dist = inputs.get("rain_distribution") or "gumbel"
        fit = fq.fit_annual_maxima(np.asarray(values, dtype=float) * factor, T, dist)
        note = f"R24 from a {fit.label} fit to {fit.n} years of annual maxima"
        if factor != 1.0:
            note += f" × {factor:g} (daily → 24 h)"
        return fit.quantiles, [""] * T.size, [note] + fit.warnings, fit
    raise ValueError("needs the 24-hour design rainfall (a 'T: mm' table or an annual "
                     "maximum series)")


def _c_rational(desc, T, inp):
    c = float(inp["runoff_coefficient"])
    if not 0 < c <= 1:
        raise ValueError(f"the runoff coefficient C must be in (0, 1] (got {c:g})")
    r24, flags, notes, _fit = design_rainfall(inp, T)
    tc_min = kirpich_tc_minutes(desc.flow_length_km * 1000.0, desc.flow_path_slope)
    intensity = mononobe_intensity(r24, tc_min / 60.0)
    Q = rational_peak(c, intensity, desc.area_km2)
    notes = [f"t_c = {tc_min:.0f} min (Kirpich, L = {desc.flow_length_km:.3g} km, "
             f"S = {desc.flow_path_slope:.3g}); C = {c:g}"] + notes
    return Q, flags, notes, None


def _fit_flood(values, T, inp, what):
    data = fq.read_series(values) if isinstance(values, str) else values
    fit = fq.fit_annual_maxima(data, T, inp.get("flood_distribution") or "gumbel")
    band = {fq._tkey(t): (float(lo), float(hi)) for t, lo, hi in zip(T, fit.lower, fit.upper)}
    note = f"{fit.label} fit to {fit.n} years of {what}"
    return fit, band, [note] + fit.warnings


def _c_frequency(desc, T, inp):
    fit, band, notes = _fit_flood(inp["flood_annual_max"], T, inp, "annual maxima at the site")
    flags = ["extrapolated" if t > 2 * fit.n else "" for t in T]
    return fit.quantiles, flags, notes, band


def _c_area_ratio(desc, T, inp):
    a_donor = float(inp["donor_area_km2"])
    if a_donor <= 0:
        raise ValueError("the donor area must be above 0 km²")
    n = float(inp.get("area_ratio_exponent") if inp.get("area_ratio_exponent") is not None else 0.8)
    if _given(inp.get("donor_floods")):
        tab = {float(k): float(v) for k, v in dict(inp["donor_floods"]).items()}
        q_d = np.array([next((v for k, v in tab.items() if math.isclose(k, t)), np.nan) for t in T])
        flags = ["" if np.isfinite(q) else "no donor flood for this T" for q in q_d]
        notes, band = ["donor floods from the typed table"], None
    else:
        fit, band, notes = _fit_flood(inp["donor_annual_max"], T, inp, "donor annual maxima")
        q_d, flags = fit.quantiles, [""] * T.size
        ratio = (desc.area_km2 / a_donor) ** n
        band = {k: (lo * ratio, hi * ratio) for k, (lo, hi) in band.items()}
    notes = [f"area ratio {desc.area_km2 / a_donor:.3g}, exponent n = {n:g} "
             f"(factor {(desc.area_km2 / a_donor) ** n:.3g})"] + notes
    return area_ratio(q_d, desc.area_km2, a_donor, n), flags, notes, band


def _no_T(fn):
    def compute(desc, T, inp):
        q = fn(desc, inp)
        return np.full(T.shape, q), [""] * T.size, ["a single maximum flood, the same for every T"], None
    return compute


def _k_wecs(desc, inp):
    out = []
    if desc.area_km2 < 100:
        out.append(("caution", "the AEPC design aids call WECS/DHM reliable only above 100 km² "
                               "and not in the Siwalik or Terai (Subedi et al. 2022 say the "
                               "opposite — check the 1990 report)"))
    if desc.is_chure_or_terai:
        out.append(("caution", "fitted mostly to larger hill and snow-fed rivers; for a Chure/"
                               "Terai stream A3000 = A, so it uses area only (compendium §6)"))
    return out


def _k_dhm2004(desc, inp):
    if desc.a3000 <= 0:
        return [("outside", "the whole catchment lies above 3,000 m, where DHM 2004 (which "
                            "has no '+1') gives no flood")]
    if desc.is_chure_or_terai:
        return [("caution", "same structure as WECS/DHM (area only, one national region, few "
                            "small-river gauges)")]
    return []


def _k_mhsp(desc, inp):
    if desc.area_km2 < 100 or desc.is_chure_or_terai:
        return [("caution", "developed for medium hydropower sites on hill and mountain rivers; "
                            "it gives much lower values than WECS/DHM for small catchments")]
    return []


def _k_dickens_mod(desc, inp):
    p = 100.0 * (desc.snow + 6.0) / (desc.area_km2 + desc.snow)
    if p >= 1185:
        return [("outside", f"p = {p:.4g} is 1185 or more, so log(1185/p) ≤ 0: the catchment "
                            "is too small for Modified Dickens")]
    if desc.snow == 0 and desc.area_km2 < 100:
        return [("caution", "for small snow-free catchments the result depends strongly on the "
                            "'+6' constant in p")]
    return []


def _k_specific(desc, inp):
    if desc.area_km2 < 12:
        return [("outside", "stations below about 12 km² were excluded from the analysis")]
    return []


def _k_rational(desc, inp):
    if desc.area_km2 > 50:
        return [("outside", "the WECS Flood Control and Management Manual (2019) allows the "
                            "Rational method only up to 50 km²")]
    if desc.area_km2 > 12:
        return [("caution", "many design manuals use the Rational method only up to about "
                            "12 km²")]
    return []


def _k_area_ratio(desc, inp):
    try:
        r = desc.area_km2 / float(inp["donor_area_km2"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return []
    if not 0.5 <= r <= 2.0:
        return [("caution", f"the site is {r:.2g}× the donor area — area transfers are usually "
                            "trusted only within about a factor of 2; show the donor is "
                            "hydrologically similar")]
    return []


_INDIAN = "Indian formula fitted to Indian regions — a rough comparison, not for design"

#: Every method, in the order tables list them.
FLOOD_METHODS = {m.key: m for m in [
    FloodMethod("wecs_dhm", "WECS/DHM 1990 (HYDEST)", "regional", "1990",
                "DoWRI, DoED, DoR, DHM, AEPC, consultants", "instantaneous peak, any T",
                "Q2 = 1.8767·(A3000+1)^0.8783; Q100 = 14.63·(A3000+1)^0.7342; "
                "ln Q_T = ln Q2 + S·ln(Q100/Q2)/2.326",
                source="Some papers print the Q2 exponent as 0.8737 or leave out the '+1' — the "
                       "WECS/DHM 1990 report is the reference. Sources disagree on the size "
                       "range (AEPC: above 100 km²; Subedi et al. 2022: 100 km² or less).",
                compute=_c_wecs, check=_k_wecs, section="3.1"),
    FloodMethod("dhm_2004", "DHM 2004 (Sharma & Adhikari)", "regional", "2004",
                "DHM, DoLIDAR, DoED, consultants", "instantaneous peak, any T",
                "Q2 = 2.29·A3000^0.86; Q100 = 20.7·A3000^0.72; ln Q_T as WECS/DHM",
                source="Confirm in the DHM publication whether mean basin elevation enters the "
                       "formula. It usually gives higher floods than WECS/DHM 1990.",
                compute=_c_dhm2004, check=_k_dhm2004, section="3.2"),
    FloodMethod("mhsp_1997", "MHSP 1997 (NEA)", "regional", "1997",
                "NEA, DoED, hydropower consultants", "peak for T = 5, 20, 50, 100",
                "Q_T = k·A^b, k and b by region (Western, Central, Eastern) and T",
                source="Coefficients as reproduced in Subedi et al. (2022); confirm against the "
                       "MHSP 1997 report. Other T are interpolated on the normal variate.",
                inputs=("mhsp_region",), tabulated=(5, 20, 50, 100),
                compute=_c_mhsp, check=_k_mhsp, section="3.3"),
    FloodMethod("modified_dickens", "Modified Dickens", "regional", "—",
                "DoWRI, DoR, DWIDM, consultants (often as a check)", "peak, any T",
                "Q_T = C_T·A^0.75; C_T = 2.342·log(0.6T)·log(1185/p) + 4; p = 100·(a+6)/(A+a)",
                source="Form after Subedi et al. (2022) and the MBMAN lecture note (the two "
                       "logarithms multiply; denominator A + a). Some sources write A. "
                       "Permanent snow a is taken as the area above 5,000 m.",
                compute=_c_dickens_mod, check=_k_dickens_mod, section="3.5"),
    FloodMethod("specific_discharge", "Specific discharge (WECS 2019)", "regional", "2019",
                "WECS; river training and flood management studies",
                "peak for T = 2, 25, 50, 100",
                "q2 = 4.2·A^-0.30; q25 = 30.8·A^-0.44; q50 = 43.3·A^-0.46; q100 = 61.4·A^-0.49; "
                "Q_T = q_T·A",
                source="Coefficients as printed in Subedi et al. (2022), citing WECS (2019). "
                       "Fitted to 51 DHM stations with data to 1996.",
                tabulated=(2, 25, 50, 100), compute=_c_specific, check=_k_specific,
                section="3.15"),
    FloodMethod("wecs_dhm_daily", "WECS/DHM 1990 daily flood", "regional", "1990",
                "DoED, DHM, consultants", "daily mean flood, any T",
                "Q2 = 0.8154·(A3000+1)^0.9527; Q100 = 4.144·(A3000+1)^0.8448",
                source="A daily mean, not an instantaneous peak, so it is left out of the "
                       "official range.", peak=False, compute=_c_wecs_daily, section="3.1"),
    FloodMethod("rational", "Rational method", "rainfall", "—",
                "DoLIDAR, DoR (culverts), DoWRI (small schemes), municipalities",
                "peak for small catchments",
                "Q = C·I·A/3.6; t_c = 0.0195·L^0.77·S^-0.385 min (Kirpich); "
                "I = (R24/24)·(24/t_c)^(2/3) (Mononobe)",
                source="Valid only for small catchments: WECS (2019) allows it up to 50 km², "
                       "many manuals about 12 km². The choice of C dominates the answer.",
                inputs=("runoff_coefficient", ("rain_24h", "rain_annual_max")),
                needs=("flow_length_km", "flow_path_slope"),
                compute=_c_rational, check=_k_rational, section="3.8"),
    FloodMethod("physics", "MRRpy physics model (design storm)", "rainfall", "—",
                "consultants and academia (process-based models, compendium §3.19)",
                "full hydrograph, peak and volume",
                "design storm (R24 by Mononobe, alternating blocks) → runoff → routing on the DEM",
                source="Uncalibrated unless calibrated to a gauge or flood marks; its result "
                       "depends on the rainfall, soil and roughness inputs.",
                inputs=(("rain_24h", "rain_annual_max"),), section="3.19"),
    FloodMethod("frequency", "Frequency analysis at the site", "gauge", "—",
                "all agencies when data exist", "peak with a confidence band",
                "Gumbel X_T = x̄ + K_T·s; LP-III; GEV by L-moments",
                source="Needs about 20 years or more of annual maxima at the site.",
                inputs=("flood_annual_max",), compute=_c_frequency, section="3.11"),
    FloodMethod("area_ratio", "Catchment area ratio (donor gauge)", "gauge", "—",
                "DoED, consultants", "peak from a nearby gauge",
                "Q_site = Q_donor·(A_site/A_donor)^n",
                source="Only as good as the similarity of the donor catchment.",
                inputs=("donor_area_km2", ("donor_floods", "donor_annual_max")),
                compute=_c_area_ratio, check=_k_area_ratio, section="3.12"),
    FloodMethod("dickens", "Dickens (original)", "comparison", "1865",
                "older designs", "maximum flood, no return period", "Q = C_D·A^(3/4)",
                source=_INDIAN, peak=False, inputs=(),
                compute=_no_T(lambda d, i: dickens(d.area_km2, i.get("dickens_constant") or 11.4)),
                section="3.4"),
    FloodMethod("ryves", "Ryves", "comparison", "—", "older or student reports; DoR screening",
                "maximum flood, no return period", "Q = C_R·A^(2/3)", source=_INDIAN,
                peak=False,
                compute=_no_T(lambda d, i: ryves(d.area_km2, i.get("ryves_constant") or 10.2)),
                section="3.14"),
    FloodMethod("inglis", "Inglis", "comparison", "—", "older or student reports; DoR screening",
                "maximum flood, no return period", "Q = 124·A/√(A + 10.4)", source=_INDIAN,
                peak=False, compute=_no_T(lambda d, i: inglis(d.area_km2)), section="3.14"),
]}

#: The official regional methods (the default selection).
REGIONAL_METHODS = tuple(k for k, m in FLOOD_METHODS.items() if m.group == "regional")


def method(key):
    """The FloodMethod called *key* (with a did-you-mean error)."""
    k = str(key).strip().lower()
    if k in FLOOD_METHODS:
        return FLOOD_METHODS[k]
    import difflib
    close = difflib.get_close_matches(k, list(FLOOD_METHODS), n=3)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise ValueError(f"Unknown method {key!r}.{hint} Methods: {', '.join(FLOOD_METHODS)}.")


def describe_methods():
    """A printable list of every method, grouped, with what it needs."""
    lines = []
    for g, title in GROUPS.items():
        lines.append(title + ":")
        for m in FLOOD_METHODS.values():
            if m.group != g:
                continue
            needs = [INPUTS[k].label if isinstance(k, str) else " or ".join(INPUTS[x].label for x in k)
                     for k in m.inputs] + [_NEED_TEXT[f].split(" (")[0] for f in m.needs]
            lines.append(f"  {m.key:<19} {m.name} — {m.gives}")
            lines.append(f"  {'':<19} needs: {', '.join(needs) or 'the catchment only'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ═════════════════════════════════════════════════════════════════════════════
# Running a selection of methods
# ═════════════════════════════════════════════════════════════════════════════
def resolve_methods(methods):
    """Method keys in table order, without repeats; None → the regional methods."""
    if methods is None:
        return list(REGIONAL_METHODS)
    if isinstance(methods, str):
        methods = [m for m in methods.replace(",", " ").split() if m]
    keys = {method(m).key for m in methods}
    return [k for k in FLOOD_METHODS if k in keys]


def estimate_floods(descriptors, methods=None, return_periods=TOR_RETURN_PERIODS, **inputs):
    """
    Run the selected methods for one catchment.

    descriptors     CatchmentDescriptors (or a dict of them, e.g. {"area_km2": 65}).
    methods         method keys (see FLOOD_METHODS); None = the regional methods.
    return_periods  years, e.g. (2, 10, 100).
    **inputs        what the methods need (see INPUTS): mhsp_region,
                    runoff_coefficient, rain_24h, flood_annual_max, …

    Returns a FloodEstimates table.  A method that is missing an input, or
    whose input is unusable, gets status 'needs input' instead of an error.
    """
    if isinstance(descriptors, dict):
        descriptors = CatchmentDescriptors.from_dict(descriptors)
    unknown = sorted(set(inputs) - set(INPUTS))
    if unknown:
        raise ValueError(f"Unknown input(s) {', '.join(unknown)}; known: {', '.join(INPUTS)}.")
    inp = {k: i.default for k, i in INPUTS.items() if i.default is not None}
    inp.update({k: v for k, v in inputs.items() if v is not None})
    T = fq.as_return_periods(return_periods)
    est = FloodEstimates(descriptors, T, inp)
    for key in resolve_methods(methods):
        m = FLOOD_METHODS[key]
        est._add(m.key, m.name, m.group, m.peak, **m.run(descriptors, T, inp))
    return est


class FloodEstimates:
    """
    The comparison table: one row per method, one column per return period.

    table      DataFrame — group, status, Q<T> columns [m³/s], notes
    flags      DataFrame — per value: '', 'interpolated', 'extrapolated', …
    envelope   DataFrame — per T: min / median / max of the official
               regional peak methods that are usable here, and their spread
    """

    def __init__(self, descriptors, T, inputs):
        self.descriptors = descriptors
        self.T = fq.as_return_periods(T)
        self.inputs = dict(inputs)
        self.rows = []

    # ── building ─────────────────────────────────────────────────────────────
    def _add(self, key, name, group, peak, status, Q, flags, notes, band):
        self.rows = [r for r in self.rows if r["key"] != key]
        self.rows.append(dict(key=key, name=name, group=group, peak=peak, status=status,
                              Q=np.asarray(Q, dtype=float), flags=list(flags),
                              notes=list(notes), band=band))
        order = list(FLOOD_METHODS)
        self.rows.sort(key=lambda r: order.index(r["key"]) if r["key"] in order else len(order))

    def add_result(self, key, name, values, group="rainfall", status="ok", notes=(), peak=True,
                   band=None):
        """Add (or replace) a row from {T: Q} — e.g. the physics model's peaks."""
        vals = {float(k): float(v) for k, v in dict(values).items()}
        Q = np.array([next((v for k, v in vals.items() if math.isclose(k, t)), np.nan)
                      for t in self.T])
        flags = ["" if np.isfinite(q) else "not run" for q in Q]
        self._add(key, name, group, peak, status, Q, flags, list(notes), band)

    # ── reading ──────────────────────────────────────────────────────────────
    @property
    def columns(self):
        """The Q column names: 'Q2', 'Q100', …"""
        return [f"Q{fq._tkey(t)}" for t in self.T]

    def row(self, key):
        """The row dict of method *key*."""
        for r in self.rows:
            if r["key"] == key:
                return r
        raise KeyError(f"{key!r} is not in this table (rows: {[r['key'] for r in self.rows]})")

    def values(self, key):
        """{T: Q} of one method (NaN where it gives nothing)."""
        r = self.row(key)
        return {fq._tkey(t): float(q) for t, q in zip(self.T, r["Q"])}

    @property
    def table(self):
        """DataFrame indexed by method name: group, status, Q<T> [m³/s], flags, notes."""
        recs = []
        for r in self.rows:
            rec = {"method": r["name"], "key": r["key"], "group": r["group"],
                   "status": STATUS_TEXT.get(r["status"], r["status"])}
            rec.update({c: _round(q) for c, q in zip(self.columns, r["Q"])})
            rec["flags"] = "; ".join(f"{c} {f}" for c, f, q in zip(self.columns, r["flags"], r["Q"])
                                     if f and f != "not tabulated" and np.isfinite(q))
            rec["notes"] = "; ".join(r["notes"])
            recs.append(rec)
        cols = ["method", "key", "group", "status"] + self.columns + ["flags", "notes"]
        return pd.DataFrame(recs, columns=cols).set_index("method")

    @property
    def flags(self):
        """DataFrame like ``table``'s Q columns, saying which values are interpolated etc."""
        return pd.DataFrame({r["name"]: r["flags"] for r in self.rows}, index=self.columns).T

    def official_rows(self):
        """Rows that make up the official range: regional peak methods, usable here."""
        return [r for r in self.rows if r["group"] == "regional" and r["peak"]
                and r["status"] in ("ok", "caution")]

    @property
    def envelope(self):
        """Per return period: n, min, median, max and spread of the official methods."""
        recs = []
        rows = self.official_rows()
        for i, t in enumerate(self.T):
            vals = [(r["Q"][i], r["name"]) for r in rows if np.isfinite(r["Q"][i])]
            q = np.array([v for v, _n in vals])
            recs.append({"T_years": fq._tkey(t), "n_methods": len(q),
                         "min": _round(q.min()) if q.size else np.nan,
                         "median": _round(np.median(q)) if q.size else np.nan,
                         "max": _round(q.max()) if q.size else np.nan,
                         "spread": _round(q.max() / q.min()) if q.size > 1 and q.min() > 0 else np.nan,
                         "methods": ", ".join(n for _v, n in vals)})
        return pd.DataFrame(recs).set_index("T_years")

    def compare(self, key):
        """
        How one row (e.g. 'physics') sits against the official range, per T:
        its value, the range, 'inside' / 'above' / 'below' and the ratio to
        the official median.
        """
        r, env = self.row(key), self.envelope
        recs = []
        for i, t in enumerate(self.T):
            q = r["Q"][i]
            e = env.loc[fq._tkey(t)]
            where = ""
            if np.isfinite(q) and e["n_methods"]:
                where = ("above" if q > e["max"] * (1 + 1e-9) else
                         "below" if q < e["min"] * (1 - 1e-9) else "inside")
            recs.append({"T_years": fq._tkey(t), "value": _round(q), "official_min": e["min"],
                         "official_median": e["median"], "official_max": e["max"],
                         "position": where,
                         "ratio_to_median": _round(q / e["median"]) if np.isfinite(q)
                         and e["median"] and np.isfinite(e["median"]) else np.nan})
        return pd.DataFrame(recs).set_index("T_years")

    def warnings(self):
        """Plain sentences worth reading before using the numbers."""
        out = []
        cls, why = self.descriptors.river_class()
        if cls == "III":
            out.append("This looks like a small Chure/Terai stream. The national regional "
                       "formulas use area only here and were fitted to few such catchments; "
                       "rainfall-based methods, the physics model and local flood marks "
                       "deserve more weight (compendium §6).")
        for r in self.rows:
            if r["status"] == "outside":
                out.append(f"{r['name']} is outside its range for this catchment: "
                           f"{r['notes'][0] if r['notes'] else ''}.")
        env = self.envelope
        wide = env[env["spread"] > 3]
        if len(wide):
            out.append("The official methods differ by more than a factor of 3 at "
                       + ", ".join(f"{t} years" for t in wide.index) + " — explain the choice "
                       "and check against the nearest gauges.")
        return out

    # ── output ───────────────────────────────────────────────────────────────
    def to_csv(self, path):
        """Write the table to *path* (numbers stay numbers; the 'flags' column says
        which values are interpolated or extrapolated)."""
        self.table.to_csv(path)
        return path

    def to_markdown(self, digits=4):
        """The table as Markdown (value, ≈ for interpolated, * for extrapolated)."""
        head = "| Method | Status | " + " | ".join(self.columns) + " |"
        lines = [head, "|" + "---|" * (len(self.columns) + 2)]
        for r in self.rows:
            cells = [_cell(q, f, digits) for q, f in zip(r["Q"], r["flags"])]
            lines.append(f"| {r['name']} | {STATUS_TEXT.get(r['status'], r['status'])} | "
                         + " | ".join(cells) + " |")
        return "\n".join(lines)

    def _repr_html_(self):
        return self.table.drop(columns=["key"]).to_html(na_rep="–")

    def __repr__(self):
        return f"FloodEstimates({len(self.rows)} methods, T={[fq._tkey(t) for t in self.T]})"


def _round(q, digits=4):
    """4 significant figures (floods are not known better than that)."""
    try:
        q = float(q)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(q):
        return np.nan
    if q == 0:
        return 0.0
    return float(f"{q:.{digits}g}")


def _cell(q, flag, digits=4):
    if not np.isfinite(q):
        return "–"
    mark = {"interpolated": "≈", "rain interpolated": "≈", "extrapolated": "*"}.get(flag, "")
    return f"{mark}{_round(q, digits):g}"
