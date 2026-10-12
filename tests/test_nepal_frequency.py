# -*- coding: utf-8 -*-
"""
tests/test_nepal_frequency.py
=============================
Frequency analysis (MRRpy.nepal.frequency): the Gumbel frequency factor of
the compendium, Log-Pearson III, GEV by L-moments (checked against SciPy),
bootstrap bands, and reading annual-maximum series.

Run:  pytest tests/test_nepal_frequency.py -v
"""

import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from MRRpy.nepal import frequency as fq

PEAKS = np.array([120, 95, 160, 140, 210, 130, 175, 99, 150, 188, 142, 115, 230, 165,
                  128, 170, 111, 145, 198, 155], dtype=float)


def test_gumbel_frequency_factor():
    K = fq.gumbel_frequency_factor([2, 10, 100])
    assert np.allclose(K, [-0.1643, 1.3046, 3.1367], atol=2e-4)


def test_gumbel_quantiles_are_mean_plus_k_sd():
    q = fq.gumbel_quantiles(PEAKS, [100])
    assert q[0] == pytest.approx(PEAKS.mean() + 3.13668 * PEAKS.std(ddof=1), rel=1e-4)


def test_lp3_with_no_skew_is_lognormal():
    y = np.array([1.7, 1.8, 1.9, 2.0, 2.0, 2.1, 2.2, 2.3])       # symmetric in log10
    x = 10 ** y
    assert fq.station_skew(y) == pytest.approx(0.0, abs=1e-12)
    q = fq.lp3_quantiles(x, [100])
    expected = 10 ** (y.mean() + stats.norm.ppf(0.99) * y.std(ddof=1))
    assert q[0] == pytest.approx(expected, rel=1e-9)
    with pytest.raises(ValueError, match="above 0"):
        fq.lp3_quantiles([10, -1, 3, 4, 5], [10])


def test_sample_lmoments_symmetric():
    l1, l2, t3, t4 = fq.sample_lmoments([1, 2, 3, 4, 5])
    assert (l1, l2, t3) == pytest.approx((3.0, 1.0, 0.0))


def test_gev_matches_scipy_and_recovers_parameters():
    q = fq.gev_quantiles(PEAKS, [10, 100])
    xi, a, k = fq.gev_parameters(PEAKS)
    assert np.allclose(q, stats.genextreme.ppf([0.9, 0.99], k, loc=xi, scale=a))
    sample = stats.genextreme.rvs(-0.1, loc=100, scale=30, size=20000, random_state=1)
    xi, a, k = fq.gev_parameters(sample)
    assert xi == pytest.approx(100, abs=1.5) and a == pytest.approx(30, abs=1.0)
    assert k == pytest.approx(-0.1, abs=0.03)


def test_gev_gumbel_limit():
    sample = stats.gumbel_r.rvs(loc=50, scale=10, size=20000, random_state=2)
    xi, a, k = fq.gev_parameters(sample)
    assert abs(k) < 0.03 and a == pytest.approx(10, rel=0.05)


def test_fit_with_band_and_warnings():
    fit = fq.fit_annual_maxima(PEAKS, [2, 10, 100], "gumbel", ci=0.9, n_boot=400)
    assert fit.n == 20 and fit.distribution == "gumbel"
    assert np.all(fit.lower < fit.quantiles) and np.all(fit.quantiles < fit.upper)
    assert any("twice" in w for w in fit.warnings)            # 100 > 2 × 20 years
    again = fq.fit_annual_maxima(PEAKS, [2, 10, 100], "gumbel", ci=0.9, n_boot=400)
    assert np.array_equal(fit.lower, again.lower)             # fixed seed → reproducible
    assert fit.value(10) == fit.as_dict()[10]
    df = fit.to_frame()
    assert list(df.columns) == ["T_years", "value", "lower_90", "upper_90"]
    short = fq.fit_annual_maxima(PEAKS[:12], [10], "lp3", n_boot=50)
    assert any("12 years" in w for w in short.warnings)
    with pytest.raises(ValueError, match="at least 10"):
        fq.fit_annual_maxima(PEAKS[:6], [10])
    with pytest.raises(ValueError, match="Unknown distribution"):
        fq.fit_annual_maxima(PEAKS, [10], "weibull")


def test_distribution_aliases():
    assert fq._distribution("Log-Pearson III") == "lp3" and fq._distribution("EV1") == "gumbel"


def test_compare_distributions_table():
    df = fq.compare_distributions(PEAKS, [2, 100], n_boot=50)
    assert len(df) == 3 and "notes" in df.columns
    neg = np.r_[PEAKS, -5.0]
    df2 = fq.compare_distributions(neg, [2, 100], n_boot=50)
    assert "above 0" in df2.loc[fq.DISTRIBUTION_LABELS["lp3"], "notes"]


def test_plotting_positions():
    xs, T = fq.plotting_positions([3, 1, 4, 2])
    assert list(xs) == [4, 3, 2, 1] and np.allclose(T, [5, 2.5, 5 / 3, 1.25])


def test_annual_maxima_from_daily():
    idx = pd.date_range("2001-01-01", "2003-12-31", freq="D")
    s = pd.Series(np.arange(len(idx), dtype=float) % 400, index=idx)
    am = fq.annual_maxima(s)
    assert list(am.index) == [2001, 2002, 2003] and am.max() == 399
    shifted = fq.annual_maxima(s, start_month=4)
    assert 2000 in shifted.index                               # Jan–Mar 2001 belong to 2000


def test_read_series_variants(tmp_path):
    p1 = tmp_path / "with_year.csv"
    pd.DataFrame({"Year": [2001, 2002, 2003], "max_mm": [120, 98, 140]}).to_csv(p1, index=False)
    assert list(fq.read_series(p1)) == [120, 98, 140]
    p2 = tmp_path / "bare.csv"
    p2.write_text("120\n98\n140\n")
    assert list(fq.read_series(p2)) == [120, 98, 140]
    p3 = tmp_path / "two.csv"
    pd.DataFrame({"year": [1, 2], "a": [5, 6], "b": [7, 8]}).to_csv(p3, index=False)
    assert list(fq.read_series(p3)) == [7, 8] and list(fq.read_series(p3, "a")) == [5, 6]
    with pytest.raises(ValueError, match="no column"):
        fq.read_series(p3, "c")


def test_return_period_validation():
    with pytest.raises(ValueError):
        fq.as_return_periods([0.5])
    assert math.isclose(fq.as_return_periods(100)[0], 100.0)
