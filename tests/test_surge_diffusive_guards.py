"""Production surge regression in both overland and confined-channel modes.

The shared fixture sets channel widths but leaves CHANNEL_ROUTING at its False
default. Exercise both explicitly, without changing the existing benchmark.
Hydrograph shape checks complement, not replace, internal-state stress tests.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest


@pytest.mark.parametrize("channel", [False, True])
def test_diffusive_surge_has_bounded_single_pulse(tmp_path, monkeypatch, channel):
    spec = importlib.util.spec_from_file_location("surge_fixture", Path(__file__).with_name("_surge_case.py"))
    surge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(surge)
    config = surge.Config

    def configured(**kwargs):
        return config(**dict(kwargs, CHANNEL_ROUTING=channel))

    monkeypatch.setattr(surge, "Config", configured)
    result = surge.run_surge(str(tmp_path), "diffusive")
    assert abs(result["rel_error"]) < 1e-10
    for row in surge.GAUGE_ROWS:
        q = result["gauges"][f"g{row}_Q_m3s"].to_numpy()
        assert np.isfinite(q).all() and q.min() >= 0
        assert .85 <= q.max()/result["q_peak"] <= 1.02
        # A single pulse rising from and returning to zero has TV = 2*peak.
        # Allow small output/roundoff effects; reject repeated large ringing.
        assert np.abs(np.diff(q)).sum() <= 2.05*q.max()
