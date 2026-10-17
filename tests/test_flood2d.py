# -*- coding: utf-8 -*-
"""
tests/test_flood2d.py
=====================
The 2D flood solver (MRRpy/core/inundation/solver2d.py) and the river-bed
grading of the 2D ground (network.graded_river_bed):

1. a lake at rest over a bumpy bed stays at rest;
2. the water balance is exact with a source and an outflow, depth never < 0;
3. uniform flow down a slope reaches Manning's normal depth;
4. the Hunter et al. (2005) flood wave over a flat rough plane (the test of
   Bates et al. 2010) at low Froude number;
5. stopping and restarting the clock gives the same water;
6. grading removes a DEM dam's flat-then-drop and lowers only.

The full 2D flood maps (routing → 2D) are tested in test_inundation.py.

Run:  pytest tests/test_flood2d.py -v
"""

import math

import numpy as np
import pytest

pytest.importorskip("numba")

from MRRpy.core.inundation import network as N
from MRRpy.core.inundation.solver2d import Flood2D


def test_lake_at_rest():
    rng = np.random.default_rng(1)
    z = rng.uniform(0.0, 4.0, (40, 50))
    z[10:15, 10:15] = 12.0                                 # an island above the lake
    h0 = np.maximum(10.0 - z, 0.0)
    m = Flood2D(z, np.full(z.shape, 0.03), 30.0, h0=h0)
    m.run_until(3600.0)
    assert max(np.abs(m.qx).max(), np.abs(m.qy).max()) < 1e-10
    assert np.abs(m.h - h0).max() < 1e-10


def test_water_balance_exact():
    rng = np.random.default_rng(2)
    yy, _xx = np.mgrid[0:60, 0:40]
    z = (0.002 * 30.0 * yy + rng.uniform(0.0, 1.5, (60, 40)))[::-1].copy()   # down to the south
    m = Flood2D(z, np.full(z.shape, 0.04), 30.0)
    m.set_outflow([(59, c, "S", 0.002) for c in range(15, 25)])
    t = np.array([0.0, 1800.0, 3600.0, 7200.0])
    m.set_sources(np.array([45 * 40 + 20]), t, np.array([[0.0], [50.0], [80.0], [0.0]]))
    m.run_until(14400.0)
    # the inflow hydrograph's volume (steps across its corners are not exact)
    assert m.v_in == pytest.approx(0.5 * 1800 * 50 + 0.5 * 1800 * 130 + 0.5 * 3600 * 80, rel=1e-6)
    assert m.v_out > 0
    assert abs(m.mass_error()) < 1e-10
    assert m.h.min() >= 0.0
    assert np.nanmax(m.h_max) >= m.h.max()               # the records cover the run
    wet = m.first_wet[np.isfinite(m.first_wet)]
    assert wet.size and wet.min() > 0 and wet.max() <= 14400.0
    assert np.all(m.wet_time <= 14400.0 + 1e-9)


def test_normal_depth():
    S, n, q, dx, nx = 0.001, 0.03, 2.0, 30.0, 200
    z = (S * dx * (nx - 1 - np.arange(nx)))[None, :]       # slopes down to the east
    m = Flood2D(z, np.full(z.shape, n), dx)
    m.set_outflow([(0, nx - 1, "E", S)])
    m.set_sources(np.array([0]), np.array([0.0, 1.0]), np.array([[q * dx], [q * dx]]))
    m.run_until(6 * 3600.0)
    hn = (q * n / math.sqrt(S)) ** 0.6
    mid = m.h[0, nx // 4:3 * nx // 4]
    assert abs(mid.mean() / hn - 1) < 0.02
    v = m.speed()[0, nx // 2]
    assert v == pytest.approx(q / hn, rel=0.03)


def test_hunter_wave_low_froude():
    """Exact solution: h = (7/3 n² u² (u t − x))^(3/7), constant velocity u.
    Local-inertial flow drops the advection term, an error of order Fr²; at
    n 0.03, u 0.5 m/s (Fr² ≈ 0.04) the wave must match closely."""
    n, u, dx, L, t_end = 0.03, 0.5, 25.0, 5000.0, 3600.0
    nx = int(L / dx)
    m = Flood2D(np.zeros((1, nx)), np.full((1, nx), n), dx)
    exact = lambda x, t: (7.0 / 3.0 * n * n * u * u * np.maximum(u * t - x, 0.0)) ** (3.0 / 7.0)
    while m.t < t_end - 1e-9:                     # depth held at the exact value in cell 0
        m.h[0, 0] = exact(np.array([0.5 * dx]), m.t)[0]
        m.run_until(min(m.t + 5.0, t_end))
    x = (np.arange(nx) + 0.5) * dx
    he = exact(x, t_end)
    wet = he > 0.05
    assert math.sqrt(np.mean((m.h[0, wet] - he[wet]) ** 2)) < 0.03
    i = int(1000 // dx)
    u_num = 0.5 * (m.qx[0, i] + m.qx[0, i + 1]) / m.h[0, i]
    assert abs(u_num / u - 1) < 0.03


def test_restart_gives_same_water():
    rng = np.random.default_rng(3)
    z = rng.uniform(0.0, 2.0, (30, 30))
    src = (np.array([15 * 30 + 15]), np.array([0.0, 3600.0]), np.array([[20.0], [5.0]]))
    a = Flood2D(z, np.full(z.shape, 0.05), 20.0, threads=1)
    a.set_sources(*src)
    a.run_until(3000.0)
    b = Flood2D(z, np.full(z.shape, 0.05), 20.0, threads=4)
    b.set_sources(*src)
    for t in (700.0, 1500.0, 3000.0):
        b.run_until(t)
    assert a.t == b.t == 3000.0
    # different stops shorten single steps, so equal to round-off, not bit for bit
    assert np.abs(a.h - b.h).max() < 1e-2 and abs(a.volume() - b.volume()) < 1e-6 * a.volume()
    c = Flood2D(z, np.full(z.shape, 0.05), 20.0, threads=8)
    c.set_sources(*src)
    c.run_until(3000.0)
    assert np.array_equal(a.h, c.h)                       # threads never change the result


def test_graded_bed_removes_dam_steps_and_lowers_only():
    # river 0 → 1 → … → 9 (outlet), 100 m apart, falling 0.1 m per cell, with a
    # DEM dam (+3 m) at cells 4–5 and nothing else
    n = 10
    ds = np.r_[np.arange(1, n), -1]
    z = 10.0 - 0.1 * np.arange(n)
    z[4:6] += 3.0
    order = N.downstream_first_order(ds)
    dist = np.full(n, 100.0)
    river = np.ones(n, bool)
    S = np.full(n, 0.001)
    carved = N.river_bed_profile(order, ds, river, z)
    graded = N.graded_river_bed(order, ds, dist, river, z, S)
    assert np.all(graded <= carved + 1e-12) and np.all(graded <= z + 1e-12)
    rise = graded[:-1] - graded[1:]                       # drop to the next cell down
    assert np.all(rise >= -1e-12)                         # never rises downstream
    assert np.all(rise <= 1.5 * 0.001 * 100.0 + 1e-9)     # no step steeper than 1.5 × S
    assert graded[-1] == z[-1]                            # the outlet keeps its height
