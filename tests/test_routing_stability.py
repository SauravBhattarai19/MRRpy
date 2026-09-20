"""Numerical invariants and adversarial routing cases on NumPy and real CUDA.

CUDA is explicitly skipped when unavailable, never counted as CPU validation.
Run with PYMRR_REQUIRE_GPU=1 on a CUDA worker to make absence a test failure.
"""
import contextlib
import io
import os
from unittest.mock import patch

import numpy as np
import pytest

from MRRpy import Config
from MRRpy.core.routing import hydraulics as h, router
from MRRpy.utils import gpu_utils
from tools.routing_stability_audit import grid, run_case, SCHEMES, CASES
from tools.routing_dam_break_experiments import diffusion_release, implicit_flat_release, swe_hll


@pytest.fixture(params=["cpu", "gpu"])
def xp(request):
    if request.param == "cpu":
        return np
    if not gpu_utils.cupy_available():
        if os.getenv("PYMRR_REQUIRE_GPU") == "1":
            pytest.fail("CUDA GPU required but unavailable")
        pytest.skip("Real CUDA GPU unavailable")
    import cupy
    cupy.zeros(1).sum().item()
    return cupy


def flux(depth, dem, xp, theta=1., eps=1e-6, slope=None, width=10., channel=False):
    depth, dem = xp.asarray(depth), xp.asarray(dem)
    size = len(depth)
    ds = xp.minimum(xp.arange(size) + 1, size - 1)
    valid = xp.arange(size) < size - 1
    slope = xp.full(size, 1e-4) if slope is None else xp.asarray(slope)
    return h.diffusive_wave_discharge(depth, dem, xp.full(size, 10.), slope,
        .03, ds, valid, theta, 10., xp, 1e-6, xp.full(size, width),
        xp.full(size, channel), slope_regularization=eps)


@pytest.mark.parametrize("dtype", ["float64", "float32"])
def test_level_water_and_dry_cells_have_zero_internal_flux(xp, dtype):
    # Flat bed floor must not manufacture a driving head; high elevation must
    # not absorb the small depth difference in float32 arithmetic.
    z = xp.asarray([10000., 10000., 10000.], dtype=dtype)
    q, _, _ = flux(xp.asarray([1., 1., 0.], dtype=dtype), z, xp)
    assert float(q[0].item()) == 0.
    assert float(q[-1].item()) == 0.
    q, _, _ = flux(xp.asarray([.0011, .001, .001], dtype=dtype), z, xp)
    assert float(q[0].item()) > 0.


def test_lake_at_rest_over_step(xp):
    q, _, _ = flux([.25, .5, 1.], [1.75, 1.5, 1.], xp)
    np.testing.assert_array_equal(gpu_utils.to_cpu(q)[:-1], 0.)


@pytest.mark.parametrize("stage_slope", [1e-7, 1e-5])
def test_diffusive_cfl_damps_near_level_checkerboard_without_sign_flip(xp, stage_slope):
    # Small alternating perturbation about a strictly downhill wet profile.
    # Positivity alone allowed an amplification near -0.70 below slope epsilon.
    n = 64
    depth = 1.-xp.arange(n, dtype=xp.float64)*10*stage_slope
    perturbation = 1e-8*(-1.)**xp.arange(n)
    ds = xp.minimum(xp.arange(n)+1, n-1)
    valid = xp.arange(n) < n-1
    q, area, slope = flux(depth, xp.zeros(n), xp, channel=True)
    qp, _, _ = flux(depth+perturbation, xp.zeros(n), xp, channel=True)
    rate = h.diffusive_inverse_timestep(q, area, slope, .03, xp.full(n, 10.),
        xp.ones(n, dtype=bool), 10., xp.full(n, 10.), xp.full(n, 100.),
        ds, valid, 1., 1e-6, xp)
    dt = .85/float(rate.max().item())
    # Interior cells only: equal-and-opposite transfers with no boundary effect.
    change = perturbation[1:]-dt*((qp-q)[1:]-(qp-q)[:-1])/100.
    amplification = gpu_utils.to_cpu(change[3:-4]/perturbation[4:-4])
    assert np.all(amplification >= 0.), amplification.min()
    assert np.all(amplification < 1.), amplification.max()


@pytest.mark.parametrize("channel", [False, True])
def test_theta_zero_matches_kinematic(xp, channel):
    d = xp.asarray([0., .01, 1., 20.])
    s = xp.asarray([1e-4, .01, .1, .02])
    q, a, _ = flux(d, [3., 2., 1., 0.], xp, theta=0, slope=s, width=2., channel=channel)
    expected, ea = h.mannings_discharge(d, s, .03, xp.full(4, 2.),
                                      xp.full(4, channel), 10., xp)
    np.testing.assert_allclose(gpu_utils.to_cpu(q), gpu_utils.to_cpu(expected), rtol=1e-13)
    np.testing.assert_allclose(gpu_utils.to_cpu(a), gpu_utils.to_cpu(ea))


def test_regularization_continuous_and_preserves_manning_above_threshold(xp):
    eps = 1e-6
    slopes = np.array([0., eps/100, eps*(1-1e-7), eps, eps*(1+1e-7), .01])
    results = []
    for slope in slopes:
        q, _, _ = flux([1., 1.], [10*slope, 0.], xp, eps=eps)
        results.append(float(q[0].item()))
    expected = 10/.03 * slopes / np.sqrt(np.maximum(slopes, eps))
    np.testing.assert_allclose(results, expected, rtol=1e-8, atol=1e-12)


def test_receiving_cell_and_tributaries_control_diffusive_step(xp):
    # Three tributaries feed a receiver with 100 times smaller storage area.
    n = 4
    q = xp.zeros(n)
    area = xp.full(n, 10.)
    store = xp.asarray([100., 100., 100., 1.])
    ds = xp.asarray([3, 3, 3, 0])
    valid = xp.asarray([True, True, True, False])
    rates = h.diffusive_inverse_timestep(q, area, q, .03, xp.full(n, 10.),
        xp.zeros(n, dtype=bool), 10., xp.full(n, 10.), store, ds, valid, 1., 1e-6, xp)
    values = gpu_utils.to_cpu(rates)
    assert values[3] == pytest.approx(300*values[0])
    assert np.isfinite(values).all() and values[0] > 0  # level Q=0 still constrains dt


@pytest.mark.parametrize("channel", [False, True])
def test_celerity_matches_manning_derivative(xp, channel):
    depths = xp.asarray([.001, .1, 1., 10., 100.])
    B, mask = xp.full(5, 2.), xp.full(5, channel)
    q, a = h.mannings_discharge(depths, .01, .03, B, mask, 2., xp)
    c = h.mannings_celerity(q, a, B, mask, xp)
    dh = depths*1e-5
    qp, _ = h.mannings_discharge(depths+dh, .01, .03, B, mask, 2., xp)
    qm, _ = h.mannings_discharge(depths-dh, .01, .03, B, mask, 2., xp)
    np.testing.assert_allclose(gpu_utils.to_cpu(c), gpu_utils.to_cpu((qp-qm)/(2*dh*B)), rtol=1e-8)


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("precision", ["float64", "float32"])
def test_adversarial_production_routing(xp, scheme, case, precision):
    metrics, arrays, _ = run_case(scheme, case, xp, precision, duration=12.)
    assert metrics["finite"]
    assert abs(metrics["rel_error"]) < (2e-5 if precision == "float32" else 1e-10)
    assert (arrays["q"] >= 0).all()
    if scheme != "muskingum":
        assert metrics["min_storage_m3"] >= 0
    else:
        # MC is only a signed ledger; this test deliberately does NOT treat
        # mass closure as a positivity or dam-break accuracy assertion.
        assert "min_storage_m3" in metrics


def test_mc_negative_storage_is_reported():
    metrics, _, log = run_case("muskingum", "steep", duration=20.)
    assert metrics["min_storage_m3"] < 0
    assert "negative cell storage" in log


@pytest.mark.parametrize("scheme", SCHEMES)
def test_point_inflow_budget(scheme, xp):
    gd = grid(xp=xp)
    class BC:
        def rate_1d(self, t):
            out = xp.zeros(gd["n_cells"])
            out[0] = 3.
            return out
    gd["inflow_bc"] = BC()
    gd["precip_engine"].get_field_1d = lambda t: xp.zeros(gd["n_cells"])
    cfg = Config(ROUTING_SCHEME=scheme, TOTAL_SIMULATION_TIME_HOURS=10/3600,
                 TIME_STEP_SECONDS=.5, OUTPUT_INTERVAL_SECONDS=1., CFL_DT_MAX=.5)
    with patch.object(router, "append_mass_balance_csv") as budget, contextlib.redirect_stdout(io.StringIO()):
        router.run_time_loop(gd, cfg)
    args, kwargs = budget.call_args
    assert kwargs["bc_m3"] == pytest.approx(30.)
    assert abs(args[8]) < 1e-10
    assert args[5] + args[6] == pytest.approx(30.)


def test_dt_min_never_overrides_stability():
    metrics, _, _ = run_case("diffusive", "flat", duration=3., CFL_DT_MIN=.4)
    assert metrics["below_dt_min"] > 0
    assert metrics["dt_min_s"] < .4


@pytest.mark.parametrize("name,value", [("CFL_TARGET", 0.), ("CFL_TARGET", 1.1),
    ("CFL_DT_MAX", float("nan")), ("DIFFUSION_THETA", 2.),
    ("DIFFUSION_SLOPE_EPS", 0.), ("CFL_DT_GROW", .5)])
def test_invalid_controls_fail_early(name, value):
    gd = grid()
    cfg = Config(**{name: value})
    with pytest.raises(ValueError, match=name), contextlib.redirect_stdout(io.StringIO()):
        router.run_time_loop(gd, cfg)


@pytest.mark.parametrize("scheme", ["kinematic", "diffusive", "dynamic"])
def test_static_step_is_subcycled(scheme):
    gd = grid()
    cfg = Config(ROUTING_SCHEME=scheme, TOTAL_SIMULATION_TIME_HOURS=3/3600,
                 TIME_STEP_SECONDS=2., OUTPUT_INTERVAL_SECONDS=1.,
                 ADAPTIVE_TIMESTEP=False, MASS_BALANCE_REPORT=False)
    with contextlib.redirect_stdout(io.StringIO()):
        router.run_time_loop(gd, cfg)
    assert gd["routing_diagnostics"]["stability_substeps"] > 0


def test_gpu_probe_queries_runtime(monkeypatch):
    class Runtime:
        @staticmethod
        def getDeviceCount():
            raise RuntimeError("No CUDA driver")
    class CUDA:
        runtime = Runtime
    class CP:
        cuda = CUDA
    monkeypatch.setattr(gpu_utils, "_CUPY_AVAILABLE", True)
    monkeypatch.setattr(gpu_utils, "_cupy", CP)
    assert not gpu_utils.cupy_available()


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("precision", ["float64", "float32"])
def test_cuda_cpu_parity(scheme, precision):
    if not gpu_utils.cupy_available():
        if os.getenv("PYMRR_REQUIRE_GPU") == "1":
            pytest.fail("CUDA GPU required but unavailable")
        pytest.skip("Real CUDA GPU unavailable")
    import cupy
    _, cpu, _ = run_case(scheme, "confluence", np, precision, duration=10.)
    _, gpu, _ = run_case(scheme, "confluence", cupy, precision, duration=10.)
    for key in ("h", "q", "hg"):
        np.testing.assert_allclose(gpu[key], cpu[key],
            rtol=3e-4 if precision == "float32" else 1e-8,
            atol=3e-5 if precision == "float32" else 1e-9)


def test_flat_reservoir_has_no_new_extrema_with_guards(xp):
    metrics, _, _ = diffusion_release(xp=xp, terrain="flat", duration=3.)
    assert metrics["largest_upward_depth_jump"] < 1e-12
    assert metrics["max_depth"] <= 10.+1e-12
    assert metrics["clipped_steps"] == 0
    assert abs(metrics["mass_error_m3"]) < 1e-8


def test_limiter_alone_conserves_mass_but_does_not_prevent_oscillation():
    metrics, _, _ = diffusion_release("legacy", terrain="flat", duration=3.)
    assert abs(metrics["mass_error_m3"]) < 1e-8
    assert metrics["largest_upward_depth_jump"] > 1.


def test_implicit_prototype_is_positive_conservative_and_converges():
    _, reference, _ = diffusion_release(terrain="flat", dt_max=.0005, duration=2.)
    coarse, hc = implicit_flat_release(.5, duration=2.)
    fine, hf = implicit_flat_release(.05, duration=2.)
    assert np.mean(abs(hf-reference)) < np.mean(abs(hc-reference))
    assert hf.min() >= 0.
    assert abs(fine["mass_error_m3"]) < 1e-7
    assert coarse["largest_upward_depth_jump"] < 1e-10


def test_full_swe_reference_converges_to_ritter(xp):
    coarse, _, _, _ = swe_hll(200, xp)
    fine, _, _, _ = swe_hll(400, xp)
    assert fine["l1_depth_m"] < .8*coarse["l1_depth_m"]
    assert fine["min_depth_m"] >= -1e-12
    assert abs(fine["mass_error_m2"]) < 1e-8


def test_muskingum_negative_coefficients_are_not_always_c0(xp):
    # High Dg makes C1 negative even when C0 is positive. A falling input can
    # therefore require clipping; "Cr+Dg<1" alone misses this failure.
    a = xp.ones(1)
    q, neg = h.muskingum_cunge_step(0*a, 10*a, 0*a, 0*a, a, a,
        a, .01*a, a, .5, xp)
    assert float(neg.item()) == 1.
    assert float(q[0].item()) == 0.


def test_rectangular_normal_depth_inverts_rating(xp):
    rng = np.random.default_rng(482)
    count = 500
    Q = xp.asarray(10**rng.uniform(-9, 7, count))
    s = xp.asarray(10**rng.uniform(-8, -.2, count))
    B = xp.asarray(10**rng.uniform(-1, 2, count))
    n = xp.asarray(10**rng.uniform(-2, -.5, count))
    mask = xp.ones(count, dtype=bool)
    depth, _ = h.normal_depth(Q, s, n, B, mask, xp)
    recovered, _ = h.mannings_discharge(depth, s, n, B, mask, 10., xp)
    np.testing.assert_allclose(gpu_utils.to_cpu(recovered), gpu_utils.to_cpu(Q), rtol=1e-9)


def test_diffusive_small_step_reference_convergence(xp):
    _, reference, _ = diffusion_release(xp=xp, terrain="steep_flat", duration=2., dt_max=.0005)
    _, coarse, _ = diffusion_release(xp=xp, terrain="steep_flat", duration=2., dt_max=.01)
    _, fine, _ = diffusion_release(xp=xp, terrain="steep_flat", duration=2., dt_max=.002)
    assert np.mean(abs(fine-reference)) < np.mean(abs(coarse-reference))
