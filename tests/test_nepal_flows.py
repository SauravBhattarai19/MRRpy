# -*- coding: utf-8 -*-
"""
tests/test_nepal_flows.py
=========================
Monthly and low flows (MRRpy.nepal.flows): the compendium's MIP example
(Region 4, 1.5 m³/s on 15 February), the WECS/DHM and MHSP regressions, the
low-flow design rule, 80 % dependable flow, e-flow and 7Q10.

Run:  pytest tests/test_nepal_flows.py -v
"""

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from MRRpy.nepal import CatchmentDescriptors
from MRRpy.nepal import flows as F


def test_mip_worked_example():
    s, q_apr, notes = F.mip_monthly(4, ("2024-02-15", 1.5))
    assert round(q_apr, 2) == 0.80 and notes == []
    printed = {"Jan": 2.07, "Feb": 1.50, "Mar": 1.10, "Apr": 0.80, "May": 1.75, "Jun": 2.99,
               "Jul": 5.50, "Aug": 21.76, "Sep": 16.68, "Oct": 5.50, "Nov": 3.99, "Dec": 2.74}
    assert {m: round(v, 2) for m, v in s.items()} == printed


def test_mip_table_shape_and_april_one():
    for region, ratios in F.MIP_1982.items():
        assert len(ratios) == 12 and ratios[3] == 1.0, region


def test_mip_ratio_interpolation_is_continuous():
    k15 = F.mip_ratio(4, "2024-02-15")
    assert k15 == pytest.approx(1.88)
    end_jan, start_feb = F.mip_ratio(4, "2024-01-31"), F.mip_ratio(4, "2024-02-01")
    assert end_jan == pytest.approx(start_feb)                 # same day-distance from the 15ths
    assert 1.88 < end_jan < 2.59
    assert F.mip_ratio(4, dt.date(2024, 1, 5)) > F.mip_ratio(4, "2024-01-15")   # towards December


def test_mip_lowest_measurement_and_season_warning():
    s, q_apr, notes = F.mip_monthly(4, [("2024-02-15", 1.5), ("2024-03-15", 0.9)])
    assert q_apr == pytest.approx(0.9 / 1.38)                  # March implies the lower April flow
    assert any("lowest" in n for n in notes)
    _s, _q, notes = F.mip_monthly(4, ("2024-07-15", 9.0))
    assert any("outside November–April" in n for n in notes)
    with pytest.raises(ValueError, match="1 to 7"):
        F.mip_monthly(9, ("2024-02-15", 1.0))


def test_wecs_and_mhsp_monthly_formulas():
    w = F.wecs_dhm_monthly(65.0, 65.0, 1500.0)
    assert w["Jan"] == pytest.approx(0.0142 * 66.0 ** 0.9777)
    assert w["Jun"] == pytest.approx(0.0069 * 65.0 ** 0.9968 * 1500.0 ** 0.2610)
    m = F.mhsp_monthly(65.0, 1500.0)
    assert m["Aug"] == pytest.approx(0.0259 * 65.0 ** 0.9095 * 1500.0 ** 0.3242)
    assert w.idxmax() == "Aug" and m.idxmax() == "Aug"
    with pytest.raises(ValueError):
        F.mhsp_monthly(65.0, 0)


def test_monthly_flows_table_and_rules():
    d = CatchmentDescriptors(area_km2=65.0)
    mf = F.monthly_flows(d, mip_region=4, measurements=("2024-02-15", 1.5), mmp_mm=1500.0)
    t = mf.table
    assert "Lower of WECS/DHM and MIP" in t.index and "Mean" in t.columns
    low = t.loc["Lower of WECS/DHM and MIP"]
    for m in F.MONTHS:
        assert low[m] == min(t.loc[F.MONTHLY_METHODS["mip_1982"], m],
                             t.loc[F.MONTHLY_METHODS["wecs_dhm"], m])
    assert mf.eflow["minimum_release"] == pytest.approx(0.1 * low[list(F.MONTHS)].min())
    assert any("E-flow" in n for n in mf.notes)
    assert "| Method |" in mf.to_markdown()


def test_monthly_flows_skip_methods_missing_inputs():
    mf = F.monthly_flows(None, mip_region=4, measurements=("2024-02-15", 1.5))
    assert list(mf.table.index) == [F.MONTHLY_METHODS["mip_1982"]]
    assert sum("skipped" in n for n in mf.notes) == 2


def test_area_ratio_flows():
    assert F.area_ratio_flows(10.0, 50.0, 100.0) == pytest.approx(5.0)
    assert F.area_ratio_flows(10.0, 50.0, 100.0, 2000.0, 1600.0) == pytest.approx(6.25)


def _monthly_series(years=10):
    idx = pd.date_range("2001-01-01", periods=years * 12, freq="MS")
    rng = np.random.default_rng(0)
    base = np.tile(np.arange(1, 13, dtype=float), years)
    return pd.Series(base + rng.normal(0, 0.3, len(idx)), index=idx)


def test_dependable_flow():
    s = _monthly_series()
    q = F.dependable_flow(s)
    jan = s[s.index.month == 1]
    assert q.loc["Jan", "mean"] == pytest.approx(jan.mean())
    assert q.loc["Jan", "q_normal"] == pytest.approx(jan.mean() - 0.8416 * jan.std(ddof=1), rel=1e-3)
    assert q.loc["Jan", "q_empirical"] < jan.mean()
    assert list(q.index) == list(F.MONTHS)


def test_environmental_flow():
    e = F.environmental_flow(pd.Series([5.0, 2.0, 8.0], index=["Jan", "Feb", "Mar"]))
    assert e["minimum_release"] == pytest.approx(0.2) and e["month_of_minimum"] == "Feb"


def test_seven_q_ten_lognormal_and_dry_rivers():
    years = range(2001, 2013)
    # falling year by year, so a 7-day window across New Year never sets a year's minimum
    mins = np.linspace(3.0, 1.0, len(years))
    parts = [pd.Series(m, index=pd.date_range(f"{y}-01-01", f"{y}-12-31", freq="D"))
             for y, m in zip(years, mins)]
    daily = pd.concat(parts)
    q, notes = F.seven_q_ten(daily)
    ln = np.log(mins)
    assert q == pytest.approx(math.exp(ln.mean() - 1.2816 * ln.std(ddof=1)), rel=1e-3)
    assert notes == []
    dry = daily.copy()
    dry[dry.index.year == 2005] = 0.0
    q0, notes0 = F.seven_q_ten(dry)
    assert q0 == 0.0 and any("dries up" in n for n in notes0)
