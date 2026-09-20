# -*- coding: utf-8 -*-
"""
tests/test_surge_benchmark.py
=============================
Numerical-behaviour checks for a GLOF-style surge injected at a valley head
(see ``_surge_case.py``).  All four routing schemes must conserve the injected
volume; the local-inertial ``dynamic`` scheme must additionally deliver a
bounded front whose arrival agrees with the kinematic shock celerity.

Why no assertion on ``diffusive``: on this case the explicit water-surface-slope
scheme oscillates strongly behind the front (discharge at a gauge swings
between roughly 10 and 110 m3/s for a steady 50 m3/s inflow).  That is a known
limitation of the scheme for abrupt inflows — documented in the paper and docs —
so the test only requires it to conserve mass.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _surge_case import GAUGE_ROWS, SCHEMES, gauge_metrics, run_surge  # noqa: E402


@pytest.fixture(scope="module")
def surge_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("surge")
    return {s: run_surge(str(root / s), s) for s in SCHEMES}


@pytest.mark.parametrize("scheme", SCHEMES)
def test_surge_conserves_injected_volume(surge_results, scheme):
    assert abs(surge_results[scheme]["rel_error"]) < 1e-10


def test_dynamic_surge_is_bounded(surge_results):
    """A steady inflow must not be amplified: allow the modest overshoot a real
    bore has (<= +35 %), and require the plateau to actually arrive (>= 85 %)."""
    for r, m in gauge_metrics(surge_results["dynamic"]).items():
        assert 0.85 <= m["peak_ratio"] <= 1.35, (r, m)


def test_dynamic_front_speed_matches_kinematic_shock(surge_results):
    """Front arrival must be ordered down-valley and, averaged over the reach,
    within 20 % of the kinematic-wave shock speed (the exact front speed for a
    step inflow onto a dry bed in the kinematic limit)."""
    def mean_speed(scheme):
        m = gauge_metrics(surge_results[scheme])
        t = [m[r]["t50_s"] for r in GAUGE_ROWS]
        assert np.all(np.isfinite(t)) and np.all(np.diff(t) > 0), (scheme, t)
        return (GAUGE_ROWS[-1] - GAUGE_ROWS[0]) / (t[-1] - t[0])   # cells / s

    assert mean_speed("dynamic") == pytest.approx(mean_speed("kinematic"), rel=0.20)
