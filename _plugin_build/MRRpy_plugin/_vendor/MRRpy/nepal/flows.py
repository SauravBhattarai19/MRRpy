# -*- coding: utf-8 -*-
"""
flows.py
========
Monthly and low flows by the methods in Nepali manuals (compendium §4).
These are calculators — they need no physics model:

    mip_monthly          MIP 1982 (Medium Irrigation Project): 7 regions, one or
                         more dry-season measurements → 12 mean monthly flows
    wecs_dhm_monthly     WECS/DHM 1990 (HYDEST) monthly regressions on A, A5000
                         and the mean monsoon precipitation MMP
    mhsp_monthly         MHSP 1997 (NEA) monthly regressions on A and MMP
    area_ratio_flows     a donor record scaled by area (and rainfall)
    dependable_flow      80 % dependable flow from a multi-year monthly series
    environmental_flow   the Hydropower Policy 2001 release rule
    seven_q_ten          7-day, 10-year low flow (log-normal) from daily flows
    monthly_flows        any of the first three side by side, plus the
                         "take the lower of WECS/DHM and MIP" design rule

Coefficients are as printed in the compendium (MIP from Baral and Shakya,
WRPPF/DoI; WECS/DHM and MHSP from Subedi et al. 2022).
"""

import datetime as _dt
import math

import numpy as np
import pandas as pd

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: MIP 1982 non-dimensional hydrographs: monthly flow ÷ April flow, Jan…Dec,
#: for the 7 hydrological regions (compendium §4.1, table 4.1).
MIP_1982 = {
    1: (2.40, 1.80, 1.30, 1.00, 2.60, 6.00, 14.50, 25.00, 16.50, 8.00, 4.10, 3.10),
    2: (2.24, 1.70, 1.33, 1.00, 1.21, 7.27, 18.18, 27.27, 20.91, 9.09, 3.94, 3.03),
    3: (2.71, 1.88, 1.38, 1.00, 1.88, 3.13, 13.54, 25.00, 20.83, 10.42, 5.00, 3.75),
    4: (2.59, 1.88, 1.38, 1.00, 2.19, 3.75, 6.89, 27.27, 20.91, 6.89, 5.00, 3.44),
    5: (2.42, 1.82, 1.36, 1.00, 0.91, 2.73, 11.21, 13.94, 10.00, 6.52, 4.55, 3.33),
    6: (2.03, 1.62, 1.27, 1.00, 2.57, 6.08, 24.32, 33.78, 27.03, 6.08, 3.38, 2.57),
    7: (3.30, 2.20, 1.40, 1.00, 3.50, 6.00, 14.00, 35.00, 24.00, 12.00, 7.50, 5.00),
}
MIP_DRY_MONTHS = (11, 12, 1, 2, 3, 4)          # November–April

#: WECS/DHM 1990 mean monthly flow Q = C·A^A1·(A5000+1)^A2·MMP^A3 (§4.3).
WECS_DHM_MONTHLY = {
    "Jan": (0.0142, 0.0, 0.9777, 0.0), "Feb": (0.0122, 0.0, 0.9766, 0.0),
    "Mar": (0.0100, 0.0, 0.9948, 0.0), "Apr": (0.0080, 0.0, 1.0435, 0.0),
    "May": (0.0084, 0.0, 1.0898, 0.0), "Jun": (0.0069, 0.9968, 0.0, 0.2610),
    "Jul": (0.0212, 0.0, 1.0093, 0.2523), "Aug": (0.0255, 0.0, 0.9963, 0.2620),
    "Sep": (0.0168, 0.0, 0.9894, 0.2878), "Oct": (0.0097, 0.0, 0.9880, 0.2508),
    "Nov": (0.0018, 0.9605, 0.0, 0.3910), "Dec": (0.0015, 0.9605, 0.0, 0.3607),
}

#: MHSP 1997 mean monthly flow Q = C·A^A1·MMP^A2 (§4.4).
MHSP_MONTHLY = {
    "Jan": (0.0312, 0.8644, 0.0), "Feb": (0.0242, 0.8752, 0.0), "Mar": (0.0205, 0.8902, 0.0),
    "Apr": (0.0178, 0.9558, 0.0), "May": (0.0119, 0.9657, 0.0), "Jun": (0.0114, 0.9466, 0.2402),
    "Jul": (0.0164, 0.9216, 0.3534), "Aug": (0.0259, 0.9095, 0.3242),
    "Sep": (0.0221, 0.8963, 0.3217), "Oct": (0.0150, 0.8772, 0.2848),
    "Nov": (0.0079, 0.8804, 0.2707), "Dec": (0.0054, 0.8890, 0.2580),
}

MONTHLY_METHODS = {
    "mip_1982": "MIP 1982 (Medium Irrigation Project)",
    "wecs_dhm": "WECS/DHM 1990 (HYDEST)",
    "mhsp_1997": "MHSP 1997 (NEA)",
}


# ═════════════════════════════════════════════════════════════════════════════
# MIP 1982
# ═════════════════════════════════════════════════════════════════════════════
def _date(value):
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    return pd.Timestamp(str(value)).date()


def mip_ratio(region, date):
    """
    The MIP ratio (flow ÷ April flow) on *date*, interpolated linearly
    between the middles of the months (the 15th):
    k = k_m + (k_next − k_m)·(day − 15)/30 after the 15th, and the same
    towards the previous month before it.
    """
    table = MIP_1982[_region(region)]
    d = _date(date)
    m = d.month - 1
    if d.day >= 15:
        return table[m] + (table[(m + 1) % 12] - table[m]) * (d.day - 15) / 30.0
    return table[m - 1] + (table[m] - table[m - 1]) * (d.day + 15) / 30.0


def _region(region):
    try:
        r = int(region)
    except (TypeError, ValueError):
        r = None
    if r not in MIP_1982:
        raise ValueError(f"MIP 1982 region must be 1 to 7 (got {region!r}).")
    return r


def mip_monthly(region, measurements):
    """
    MIP 1982 mean monthly flows [m³/s] for Jan…Dec.

    region        1–7 (from the MIP regions map).
    measurements  one (date, Q m³/s) pair, or a list of them.  With several,
                  the lowest implied April flow is used — Shrestha et al.
                  (2010) found scaling from the driest measurement much closer
                  to the records than scaling from April.

    Returns (Series of 12 flows, April flow, notes).
    """
    pairs = [measurements] if _is_pair(measurements) else list(measurements)
    if not pairs:
        raise ValueError("MIP needs at least one dry-season flow measurement (date, Q).")
    table = MIP_1982[_region(region)]
    notes, aprils = [], []
    for date, q in pairs:
        d = _date(date)
        if float(q) <= 0:
            raise ValueError(f"The measured flow on {d} must be above 0 m³/s.")
        if d.month not in MIP_DRY_MONTHS:
            notes.append(f"the measurement on {d} is outside November–April; MIP expects a "
                         "dry-season flow, not within a few days of rain")
        aprils.append((float(q) / mip_ratio(region, d), d))
    q_apr, d_used = min(aprils)
    if len(aprils) > 1:
        notes.append(f"{len(aprils)} measurements: the lowest implied April flow (from {d_used}) "
                     "is used")
    flows = pd.Series([q_apr * k for k in table], index=MONTHS, name=MONTHLY_METHODS["mip_1982"])
    return flows, q_apr, notes


def _is_pair(x):
    return (isinstance(x, (tuple, list)) and len(x) == 2
            and not isinstance(x[0], (tuple, list)) and np.isscalar(x[1]))


# ═════════════════════════════════════════════════════════════════════════════
# Regional monthly regressions
# ═════════════════════════════════════════════════════════════════════════════
def wecs_dhm_monthly(area_km2, area_below_5000_km2, mmp_mm):
    """WECS/DHM 1990 mean monthly flows [m³/s]: C·A^A1·(A5000+1)^A2·MMP^A3."""
    a, a5, p = float(area_km2), float(area_below_5000_km2), float(mmp_mm)
    if not (a > 0 and p > 0):
        raise ValueError("WECS/DHM monthly flows need the area and the mean monsoon "
                         "precipitation (both above 0).")
    vals = [c * a ** a1 * (a5 + 1.0) ** a2 * p ** a3
            for c, a1, a2, a3 in WECS_DHM_MONTHLY.values()]
    return pd.Series(vals, index=MONTHS, name=MONTHLY_METHODS["wecs_dhm"])


def mhsp_monthly(area_km2, mmp_mm):
    """MHSP 1997 mean monthly flows [m³/s]: C·A^A1·MMP^A2."""
    a, p = float(area_km2), float(mmp_mm)
    if not (a > 0 and p > 0):
        raise ValueError("MHSP monthly flows need the area and the mean monsoon "
                         "precipitation (both above 0).")
    vals = [c * a ** a1 * p ** a2 for c, a1, a2 in MHSP_MONTHLY.values()]
    return pd.Series(vals, index=MONTHS, name=MONTHLY_METHODS["mhsp_1997"])


def area_ratio_flows(donor_flows, area_site_km2, area_donor_km2, p_site_mm=None,
                     p_donor_mm=None):
    """
    A donor record moved to the site (compendium §4.5):
    Q_site = Q_donor·(A_site/A_donor), optionally ×(P_site/P_donor).
    Works on a number, an array, a Series or a DataFrame.
    """
    factor = float(area_site_km2) / float(area_donor_km2)
    if p_site_mm is not None and p_donor_mm is not None:
        factor *= float(p_site_mm) / float(p_donor_mm)
    return donor_flows * factor


# ═════════════════════════════════════════════════════════════════════════════
# Flow statistics from records (gauged or simulated)
# ═════════════════════════════════════════════════════════════════════════════
def _monthly_matrix(monthly):
    """Years × 12 months from a dated Series of monthly flows or a years×months table."""
    if isinstance(monthly, pd.DataFrame):
        df = monthly.copy()
        if df.shape[1] != 12:
            raise ValueError("A monthly table needs 12 columns (Jan…Dec).")
        df.columns = list(MONTHS)
        return df
    s = pd.Series(monthly).dropna()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    s = s.groupby([s.index.year, s.index.month]).mean()
    df = s.unstack()
    df = df.reindex(columns=range(1, 13))
    df.columns = list(MONTHS)
    return df


def dependable_flow(monthly, probability=0.8):
    """
    The flow equalled or exceeded in *probability* of years, per month —
    the 80 % dependable flow of Nepali irrigation design (compendium §4.7).

    monthly   a dated Series of monthly (or daily) flows, or a years × 12 table.
    Returns a table: mean, sd, q_normal (mean − z·sd, the compendium's formula)
    and q_empirical (from the ranked years) for each month.
    """
    from scipy.stats import norm
    df = _monthly_matrix(monthly)
    z = float(norm.ppf(probability))
    rows = {}
    for m in MONTHS:
        v = df[m].dropna().to_numpy(dtype=float)
        if v.size < 2:
            rows[m] = dict(years=v.size, mean=np.nan, sd=np.nan, q_normal=np.nan, q_empirical=np.nan)
            continue
        mean, sd = v.mean(), v.std(ddof=1)
        rows[m] = dict(years=v.size, mean=mean, sd=sd, q_normal=max(mean - z * sd, 0.0),
                       q_empirical=float(np.quantile(v, 1.0 - probability, method="weibull")))
    return pd.DataFrame(rows).T


def environmental_flow(monthly_flows, fraction=0.10):
    """
    The release below an intake (compendium §4.8): at least 10 % of the
    minimum mean monthly flow (Hydropower Development Policy 2001); also
    returns 30 % of each month's mean, which guidance with MIP 2016 rates
    as 'satisfactory'.  Returns dict(minimum_release, month_of_minimum,
    satisfactory_by_month).
    """
    s = pd.Series(monthly_flows, dtype=float)
    month = s.idxmin()
    return {"minimum_release": float(fraction) * float(s.min()), "month_of_minimum": month,
            "satisfactory_by_month": 0.30 * s}


def seven_q_ten(daily, return_period=10.0):
    """
    The 7-day low flow with a 10-year return period, log-normal
    (compendium §4.9): 7Q10 = exp(mean(ln Q7) − 1.2816·sd(ln Q7)), where Q7
    is each year's lowest 7-day mean flow.

    daily  a Series of daily flows with a DatetimeIndex.
    Returns (7Q10, notes).  When some year's 7-day minimum is 0 the river
    dries up and 0 is returned (a log-normal cannot hold zeros).
    """
    from scipy.stats import norm
    s = pd.Series(daily).dropna()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    q7 = s.rolling(7).mean().dropna()
    annual = q7.groupby(q7.index.year).min()
    notes = []
    if annual.size < 10:
        notes.append(f"only {annual.size} years; 10 or more are needed for a dependable value")
    if annual.size < 2:
        raise ValueError("7Q10 needs at least two years of daily flows.")
    if (annual <= 0).any():
        notes.append("the 7-day flow falls to 0 in some years — the river dries up")
        return 0.0, notes
    z = float(norm.ppf(1.0 - 1.0 / float(return_period)))
    ln = np.log(annual.to_numpy(dtype=float))
    return float(math.exp(ln.mean() - z * ln.std(ddof=1))), notes


# ═════════════════════════════════════════════════════════════════════════════
# Side by side
# ═════════════════════════════════════════════════════════════════════════════
class MonthlyFlows:
    """Mean monthly flows by several methods: ``table`` (m³/s) and ``notes``."""

    def __init__(self, table, notes, eflow=None):
        self.table = table
        self.notes = list(notes)
        self.eflow = eflow

    def to_csv(self, path):
        self.table.to_csv(path)
        return path

    def to_markdown(self):
        cols = list(self.table.columns)
        lines = ["| Method | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
        for name, row in self.table.iterrows():
            lines.append(f"| {name} | " + " | ".join(f"{v:.3g}" if np.isfinite(v) else "–"
                                                       for v in row) + " |")
        return "\n".join(lines)

    def _repr_html_(self):
        return self.table.round(3).to_html()

    def __repr__(self):
        return f"MonthlyFlows({list(self.table.index)})"


def monthly_flows(descriptors=None, methods=("mip_1982", "wecs_dhm", "mhsp_1997"),
                  mip_region=None, measurements=None, mmp_mm=None):
    """
    Mean monthly flows by the chosen methods, side by side, plus:

    * the row "Lower of WECS/DHM and MIP" when both ran — the practical rule
      of Shrestha et al. (2010) for low-flow design;
    * the e-flow release (10 % of the minimum monthly flow of that row, or of
      the first method).

    descriptors   CatchmentDescriptors (for the area and A5000).
    mip_region / measurements   for MIP 1982;  mmp_mm  for WECS/DHM and MHSP.
    Methods missing an input are skipped with a note.
    """
    rows, notes = {}, []
    for key in methods:
        if key not in MONTHLY_METHODS:
            raise ValueError(f"Unknown monthly method {key!r}; use {', '.join(MONTHLY_METHODS)}.")
        try:
            if key == "mip_1982":
                if mip_region is None or not measurements:
                    raise ValueError("MIP 1982 needs its region (1–7) and a dry-season "
                                     "measurement")
                s, q_apr, n = mip_monthly(mip_region, measurements)
                notes += [f"MIP 1982: region {int(mip_region)}, April flow {q_apr:.3g} m³/s"] + \
                         [f"MIP 1982: {x}" for x in n]
            elif key == "wecs_dhm":
                if descriptors is None or mmp_mm is None:
                    raise ValueError("WECS/DHM monthly flows need the catchment and the mean "
                                     "monsoon precipitation")
                s = wecs_dhm_monthly(descriptors.area_km2, descriptors.a5000, mmp_mm)
            else:
                if descriptors is None or mmp_mm is None:
                    raise ValueError("MHSP monthly flows need the catchment and the mean "
                                     "monsoon precipitation")
                s = mhsp_monthly(descriptors.area_km2, mmp_mm)
        except ValueError as exc:
            notes.append(f"{MONTHLY_METHODS[key]} skipped: {exc}")
            continue
        rows[s.name] = s
    table = pd.DataFrame(rows).T if rows else pd.DataFrame(columns=list(MONTHS))
    mip, wecs = MONTHLY_METHODS["mip_1982"], MONTHLY_METHODS["wecs_dhm"]
    if mip in table.index and wecs in table.index:
        table.loc["Lower of WECS/DHM and MIP"] = table.loc[[mip, wecs]].min()
        notes.append("Low-flow design: Shrestha et al. (2010) advise taking the lower of "
                     "WECS/DHM and MIP for each month.")
    if len(table):
        table["Mean"] = table[list(MONTHS)].mean(axis=1)
    eflow = None
    if len(table):
        basis = "Lower of WECS/DHM and MIP" if "Lower of WECS/DHM and MIP" in table.index \
            else table.index[0]
        eflow = environmental_flow(table.loc[basis, list(MONTHS)])
        eflow["basis"] = basis
        notes.append(f"E-flow: at least {eflow['minimum_release']:.3g} m³/s (10 % of the "
                     f"{eflow['month_of_minimum']} flow of '{basis}'; Hydropower Policy 2001) — "
                     "confirm the rule that applies to irrigation intakes.")
    return MonthlyFlows(table, notes, eflow)
