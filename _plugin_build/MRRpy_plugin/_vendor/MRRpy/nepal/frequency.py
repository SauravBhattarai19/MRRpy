# -*- coding: utf-8 -*-
"""
frequency.py
============
Frequency analysis of an annual-maximum series — floods at a gauge, or daily
rainfall at a DHM station — with the three distributions named in Nepali
manuals (compendium §3.11; the DoLIDAR manual names Gumbel and LP-III):

* **Gumbel (EV1)** by the method of moments, with the frequency factor

      K_T = −(√6/π)·[0.5772 + ln(ln(T/(T−1)))],   X_T = x̄ + K_T·s

* **Log-Pearson type III** on log10 of the data, with the station skew
  (bias-corrected); K_T(g) is the exact Pearson III quantile.
* **GEV** by L-moments (Hosking 1990, with Hosking's approximation for k).

``fit_annual_maxima`` adds a bootstrap confidence band to any of them (the
ToR asks for confidence bounds), and ``plotting_positions`` gives the Weibull
positions m/(n+1) for plots.  Pure NumPy/SciPy.

    from MRRpy.nepal import frequency
    fit = frequency.fit_annual_maxima(peaks, [2, 10, 100], "gev")
    fit.quantiles, fit.lower, fit.upper
"""

import math

import numpy as np
import pandas as pd

#: Distributions, in the order they are offered.
DISTRIBUTIONS = ("gumbel", "lp3", "gev")
DISTRIBUTION_LABELS = {
    "gumbel": "Gumbel (EV1, method of moments)",
    "lp3": "Log-Pearson III (station skew)",
    "gev": "GEV (L-moments)",
}

#: Fewer years than this and a fit is refused; fewer than RECOMMENDED_YEARS
#: and it carries a caution (the compendium: "needs at least about 20 years").
MIN_YEARS = 10
RECOMMENDED_YEARS = 20

_EULER = 0.5772          # the constant as printed in the compendium's Gumbel K_T


def as_return_periods(T):
    """*T* as a 1-D float array, checking every value is a return period > 1 year."""
    arr = np.atleast_1d(np.asarray(T, dtype=float))
    if arr.size == 0 or not np.all(np.isfinite(arr)) or np.any(arr <= 1.0):
        raise ValueError(f"Return periods must be numbers above 1 year (got {T!r}).")
    return arr


def _series(x, positive=False):
    """Finite values of *x* as a float array (NaN/blank years dropped)."""
    arr = np.asarray(x, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if positive and np.any(arr <= 0):
        raise ValueError("Log-Pearson III needs every annual maximum to be above 0.")
    return arr


# ═════════════════════════════════════════════════════════════════════════════
# The three distributions
# ═════════════════════════════════════════════════════════════════════════════
def gumbel_frequency_factor(T):
    """K_T = −(√6/π)·[0.5772 + ln(ln(T/(T−1)))] (compendium §3.11)."""
    T = as_return_periods(T)
    return -(math.sqrt(6.0) / math.pi) * (_EULER + np.log(np.log(T / (T - 1.0))))


def gumbel_quantiles(x, T):
    """Gumbel X_T = x̄ + K_T·s, with s the sample standard deviation (n−1)."""
    x = _series(x)
    return x.mean() + gumbel_frequency_factor(T) * x.std(ddof=1)


def station_skew(y):
    """Bias-corrected sample skew  g = n·Σ(y−ȳ)³ / ((n−1)(n−2)·s³)."""
    y = np.asarray(y, dtype=float)
    n = y.size
    s = y.std(ddof=1)
    if n < 3 or s == 0:
        return 0.0
    return float(n * np.sum((y - y.mean()) ** 3) / ((n - 1) * (n - 2) * s ** 3))


def lp3_quantiles(x, T):
    """Log-Pearson III: log10 Q_T = ȳ + K_T(g)·s_y on y = log10(x)."""
    from scipy.stats import pearson3
    y = np.log10(_series(x, positive=True))
    g = station_skew(y)
    K = pearson3.ppf(1.0 - 1.0 / as_return_periods(T), g)
    return 10.0 ** (y.mean() + K * y.std(ddof=1))


def sample_lmoments(x):
    """(λ1, λ2, τ3, τ4) from the unbiased probability-weighted moments."""
    xs = np.sort(_series(x))
    n = xs.size
    if n < 4:
        raise ValueError("L-moments need at least 4 values.")
    j = np.arange(1, n + 1, dtype=float)
    b0 = xs.mean()
    b1 = np.sum((j - 1) / (n - 1) * xs) / n
    b2 = np.sum((j - 1) * (j - 2) / ((n - 1) * (n - 2)) * xs) / n
    b3 = np.sum((j - 1) * (j - 2) * (j - 3) / ((n - 1) * (n - 2) * (n - 3)) * xs) / n
    l1 = b0
    l2 = 2 * b1 - b0
    l3 = 6 * b2 - 6 * b1 + b0
    l4 = 20 * b3 - 30 * b2 + 12 * b1 - b0
    if l2 <= 0:
        raise ValueError("Every value is the same — no spread to fit a distribution to.")
    return float(l1), float(l2), float(l3 / l2), float(l4 / l2)


def gev_parameters(x):
    """
    GEV location ξ, scale α and shape k by L-moments (Hosking 1990).

    Hosking's sign convention: k > 0 bounds the upper tail, k < 0 gives a
    heavy tail (the same sign as SciPy's ``genextreme`` shape c).
    """
    l1, l2, t3, _t4 = sample_lmoments(x)
    c = 2.0 / (3.0 + t3) - math.log(2.0) / math.log(3.0)
    k = 7.8590 * c + 2.9554 * c * c
    if abs(k) < 1e-6:                                   # Gumbel limit
        alpha = l2 / math.log(2.0)
        return l1 - 0.5772156649 * alpha, alpha, 0.0
    g = math.gamma(1.0 + k)
    alpha = l2 * k / ((1.0 - 2.0 ** (-k)) * g)
    xi = l1 - alpha * (1.0 - g) / k
    return xi, alpha, k


def gev_quantiles(x, T):
    """GEV X_T = ξ + α/k·(1 − (−ln F)^k), F = 1 − 1/T."""
    xi, alpha, k = gev_parameters(x)
    y = -np.log(1.0 - 1.0 / as_return_periods(T))
    if k == 0.0:
        return xi - alpha * np.log(y)
    return xi + alpha / k * (1.0 - y ** k)


_QUANTILE_FUNCS = {"gumbel": gumbel_quantiles, "lp3": lp3_quantiles, "gev": gev_quantiles}


def quantiles(x, T, distribution="gumbel"):
    """T-year values of the series *x* for one distribution (no confidence band)."""
    return _QUANTILE_FUNCS[_distribution(distribution)](x, T)


def _distribution(name):
    key = str(name).strip().lower().replace("-", "").replace(" ", "")
    key = {"ev1": "gumbel", "logpearson3": "lp3", "logpearsoniii": "lp3", "lpiii": "lp3",
           "lp-iii": "lp3"}.get(key, key)
    if key not in _QUANTILE_FUNCS:
        raise ValueError(f"Unknown distribution {name!r}; use one of {', '.join(DISTRIBUTIONS)}.")
    return key


# ═════════════════════════════════════════════════════════════════════════════
# A fit with a confidence band
# ═════════════════════════════════════════════════════════════════════════════
class FrequencyFit:
    """
    One distribution fitted to an annual-maximum series.

    Attributes: ``distribution``, ``label``, ``n`` (years), ``T`` (return
    periods), ``quantiles``, ``lower`` / ``upper`` (bootstrap band, NaN when
    not computed), ``ci`` (its coverage, e.g. 0.9), ``params`` and
    ``warnings``.
    """

    def __init__(self, distribution, n, T, quantiles, lower, upper, ci, params, warnings):
        self.distribution = distribution
        self.label = DISTRIBUTION_LABELS[distribution]
        self.n = n
        self.T = T
        self.quantiles = quantiles
        self.lower = lower
        self.upper = upper
        self.ci = ci
        self.params = params
        self.warnings = list(warnings)

    def value(self, T):
        """The fitted value at one return period *T* (must be one of ``self.T``)."""
        idx = np.flatnonzero(np.isclose(self.T, float(T)))
        if not idx.size:
            raise KeyError(f"T={T} was not fitted (fitted: {list(self.T)})")
        return float(self.quantiles[idx[0]])

    def as_dict(self):
        """{T: value} for every fitted return period."""
        return {_tkey(t): float(q) for t, q in zip(self.T, self.quantiles)}

    def to_frame(self):
        """A table: one row per return period with the value and its band."""
        pct = int(round(self.ci * 100)) if self.ci else None
        df = pd.DataFrame({"T_years": self.T, "value": self.quantiles})
        if pct:
            df[f"lower_{pct}"] = self.lower
            df[f"upper_{pct}"] = self.upper
        return df

    def __repr__(self):
        vals = ", ".join(f"{_tkey(t)}y: {q:.4g}" for t, q in zip(self.T, self.quantiles))
        return f"FrequencyFit({self.distribution}, n={self.n}, {vals})"


def _tkey(t):
    """Return periods print as integers when they are whole (100, not 100.0)."""
    t = float(t)
    return int(t) if t.is_integer() else t


def fit_annual_maxima(x, T, distribution="gumbel", ci=0.90, n_boot=1000, seed=20241012):
    """
    Fit *distribution* to the annual maxima *x* and return a ``FrequencyFit``.

    ci       coverage of the bootstrap band (0 or None for no band).
    n_boot   bootstrap resamples (resampling the years with replacement).
    seed     fixes the resampling so a result can be reproduced exactly.

    Raises ValueError for fewer than MIN_YEARS values.
    """
    dist = _distribution(distribution)
    data = _series(x, positive=(dist == "lp3"))
    n = data.size
    if n < MIN_YEARS:
        raise ValueError(f"Frequency analysis needs at least {MIN_YEARS} years of annual "
                         f"maxima (got {n}).")
    T = as_return_periods(T)
    fn = _QUANTILE_FUNCS[dist]
    q = np.asarray(fn(data, T), dtype=float)
    warnings = []
    if n < RECOMMENDED_YEARS:
        warnings.append(f"only {n} years of record; about {RECOMMENDED_YEARS} or more are "
                        "needed for a dependable fit")
    if np.max(T) > 2 * n:
        warnings.append(f"T = {_tkey(np.max(T))} years is more than twice the {n}-year record "
                        "(extrapolated)")
    params = _params(dist, data)
    if dist == "gev" and not -0.5 < params["t3"] < 0.5:
        warnings.append("the L-skewness is outside -0.5…0.5, where Hosking's shape "
                        "approximation loses accuracy")
    lower = upper = np.full(T.shape, np.nan)
    if ci:
        lower, upper = _bootstrap(data, T, fn, n_boot, ci, seed)
    return FrequencyFit(dist, n, T, q, lower, upper, ci or None, params, warnings)


def _params(dist, data):
    if dist == "gumbel":
        return {"mean": float(data.mean()), "std": float(data.std(ddof=1))}
    if dist == "lp3":
        y = np.log10(data)
        return {"mean_log10": float(y.mean()), "std_log10": float(y.std(ddof=1)),
                "skew_log10": station_skew(y)}
    xi, alpha, k = gev_parameters(data)
    _l1, _l2, t3, _t4 = sample_lmoments(data)
    return {"location": xi, "scale": alpha, "shape_k": k, "t3": t3}


def _bootstrap(data, T, fn, n_boot, ci, seed):
    rng = np.random.default_rng(seed)
    n = data.size
    sims = np.full((int(n_boot), T.size), np.nan)
    with np.errstate(all="ignore"):
        for b in range(int(n_boot)):
            sample = data[rng.integers(0, n, n)]
            try:
                sims[b] = fn(sample, T)
            except (ValueError, ZeroDivisionError, OverflowError):
                continue                       # a degenerate resample (e.g. all equal)
    sims[~np.isfinite(sims)] = np.nan
    alpha = (1.0 - float(ci)) / 2.0
    lower = np.nanpercentile(sims, 100 * alpha, axis=0)
    upper = np.nanpercentile(sims, 100 * (1 - alpha), axis=0)
    return lower, upper


def compare_distributions(x, T, ci=0.90, n_boot=1000, seed=20241012):
    """
    Every distribution fitted to *x*, as one table (rows = distributions,
    columns = return periods) — the usual way to choose one in a report.
    LP-III is skipped (with a note) when a value is not above 0.
    """
    rows, notes = {}, {}
    T = as_return_periods(T)
    for dist in DISTRIBUTIONS:
        label = DISTRIBUTION_LABELS[dist]
        try:
            fit = fit_annual_maxima(x, T, dist, ci=ci, n_boot=n_boot, seed=seed)
        except ValueError as exc:
            rows[label] = {_tkey(t): np.nan for t in T}       # keep the row, say why it is empty
            notes[label] = str(exc)
            continue
        rows[label] = fit.as_dict()
        notes[label] = "; ".join(fit.warnings)
    df = pd.DataFrame(rows).T
    df["notes"] = pd.Series(notes)
    return df


def plotting_positions(x):
    """
    (values sorted largest first, their Weibull return periods (n+1)/m) —
    the points to draw on a frequency plot.
    """
    xs = np.sort(_series(x))[::-1]
    m = np.arange(1, xs.size + 1, dtype=float)
    return xs, (xs.size + 1.0) / m


# ═════════════════════════════════════════════════════════════════════════════
# Reading series
# ═════════════════════════════════════════════════════════════════════════════
def annual_maxima(series, start_month=1):
    """
    The largest value of each year of a dated series (a pandas Series with a
    DatetimeIndex, e.g. daily rainfall), as a Series indexed by year.

    start_month starts the year in another month (e.g. 4 for a year that
    begins in April); the year label is the calendar year it starts in.
    Years with no data are dropped.
    """
    s = pd.Series(series).dropna()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    year = s.index.year - (s.index.month < int(start_month)).astype(int)
    return s.groupby(year).max()


def read_series(path, column=None):
    """
    Values from a CSV of annual maxima: a single column of numbers, or a
    table with a year column and a value column (the last numeric column,
    or *column*).  Blank or non-numeric entries are dropped.
    """
    df = pd.read_csv(path)
    if column is None and all(_is_number(c) for c in df.columns):
        df = pd.read_csv(path, header=None)          # no header row: the first line is data
    if column is not None:
        if column not in df.columns:
            raise ValueError(f"{path}: no column {column!r} (columns: {', '.join(map(str, df.columns))})")
        values = pd.to_numeric(df[column], errors="coerce")
    else:
        numeric = df.apply(pd.to_numeric, errors="coerce")
        cols = [c for c in numeric.columns if numeric[c].notna().any()
                and str(c).strip().lower() not in ("year", "yr", "water_year", "date")]
        if not cols:
            raise ValueError(f"{path}: no numeric column found")
        values = numeric[cols[-1]]
    values = values.dropna().to_numpy(dtype=float)
    if values.size == 0:
        raise ValueError(f"{path}: no values found")
    return values


def _is_number(text):
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False
