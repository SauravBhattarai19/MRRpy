"""Independent mathematical oracles for the diffusion research prototypes.

The lab imports no production kernel. Comparisons with production are explicit
here; agreement between two implementations is supplemented by analytic checks.
"""
from dataclasses import replace

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from tools import diffusive_independent_lab as lab
from MRRpy.core.routing.hydraulics import diffusive_wave_discharge


@pytest.mark.parametrize("seed", range(8))
def test_tree_elimination_against_dense_nonsymmetric_forest(seed):
    rng = np.random.default_rng(seed)
    n = 30
    parent = np.array([rng.integers(i+1, n) for i in range(n-1)]+[-1])
    parent[rng.choice(n-1, 4, replace=False)] = -1
    net = replace(lab.case(cells=n), parent=parent)
    upper = -rng.uniform(.1, 10, len(net.child))
    lower = -rng.uniform(.1, 10, len(net.child))
    diag = np.ones(n)
    diag[net.child] += abs(upper)
    np.add.at(diag, net.receiver, abs(lower))
    rhs = rng.normal(size=n)
    matrix = lab.sparse_matrix(net, diag, upper, lower).toarray()
    actual = lab.tree_solve(net, diag, upper, lower, rhs)
    np.testing.assert_allclose(actual, np.linalg.solve(matrix, rhs), atol=2e-14)
    np.testing.assert_allclose(matrix@actual, rhs, atol=2e-14)


def test_cycles_are_rejected():
    with pytest.raises(ValueError, match="topologically"):
        replace(lab.case(cells=4), parent=np.array([1, 2, 0, -1]))


@pytest.mark.parametrize("signed", [False, True])
@pytest.mark.parametrize("eps", [1e-6, .1])
def test_face_jacobian_against_finite_differences(signed, eps):
    rng = np.random.default_rng(17)
    net = replace(lab.case(cells=12), bed=rng.uniform(0, .5, 12), reverse=signed)
    h = rng.uniform(.5, 2, 12)
    q, a, b = lab.flux_jacobian(net, h, eps)
    J = np.zeros((len(q), len(h)))
    J[np.arange(len(q)), net.child] = a
    J[np.arange(len(q)), net.receiver] = b
    for k in range(len(h)):
        d = np.zeros_like(h)
        d[k] = 1e-6
        approx = (lab.flux_jacobian(net, h+d, eps)[0]-lab.flux_jacobian(net, h-d, eps)[0])/2e-6
        np.testing.assert_allclose(J[:, k], approx, rtol=2e-7, atol=2e-7)
    assert abs(lab.divergence(net, q).sum()) < 1e-12


@pytest.mark.parametrize("name", ["flat_dam", "steep_flat", "adverse_step", "contraction", "near_level", "lake_at_rest"])
def test_independent_law_matches_production_interior(name):
    net = lab.case(name)
    safe = np.maximum(net.parent, 0)
    q, _, _ = diffusive_wave_discharge(net.initial, net.bed, net.length,
        np.full(len(safe), 1e-4), net.roughness, safe, net.parent >= 0,
        1., 10., np, 1e-6, net.width, np.ones(len(safe), dtype=bool), 1e-6)
    independent = lab.flux_jacobian(net, net.initial)[0]
    np.testing.assert_allclose(q[net.child], independent, rtol=2e-13, atol=1e-11)


@pytest.mark.parametrize("eps", [0., 1e-8, 1e-6, 1e-4])
def test_two_cell_analytic_solution_against_independent_radau(eps):
    # Frozen conveyance has a scalar exact solution, independent of lab kernels.
    def rhs(t, y):
        d = max(y[0], 0.)
        return [-.2*(np.sqrt(d/10.) if eps == 0 else (d/10.)/np.sqrt(max(d/10., eps)))]
    ts = np.linspace(0, .2, 21)  # includes epsilon transition, precedes zero extinction
    sol = solve_ivp(rhs, (0, .2), [1e-4], t_eval=ts, method="Radau", rtol=1e-10, atol=1e-14)
    np.testing.assert_allclose(sol.y[0], lab.two_cell_exact(ts, eps=eps), rtol=2e-7, atol=2e-12)


def test_epsilon_changes_relaxation_not_just_timestep():
    assert lab.two_cell_exact(1.) == 0.
    assert lab.two_cell_exact(1., eps=1e-4) > 1e-5
    assert lab.two_cell_exact(1., eps=1e-6) < 1e-10


@pytest.mark.parametrize("name", ["flat_dam", "steep_flat", "confluence", "contraction", "adverse_step", "backwater_signed"])
def test_implicit_conservation_residual_and_sparse_equivalence(name):
    net = lab.case(name, cells=16)
    dt = .1
    h, _, residual = lab.implicit_step(net, net.initial, dt)
    hs, _, _ = lab.implicit_step(net, net.initial, dt, linear_solver="sparse")
    np.testing.assert_allclose(h, hs, atol=2e-10, rtol=1e-9)
    assert h.min() >= -1e-12
    assert abs(net.storage@(h-net.initial)) < 1e-7
    continuity = net.storage*(h-net.initial)+dt*lab.divergence(net, lab.flux_jacobian(net, h)[0])
    assert max(abs(continuity)/net.storage) < 1e-10
    assert residual < 1e-10


def test_unconverged_implicit_solve_is_rejected():
    net = lab.case()
    with pytest.raises(RuntimeError, match="iteration limit"):
        lab.implicit_step(net, net.initial, 1., max_iterations=1)


def test_contraction_requires_nonlinear_step_rejection_and_recovers():
    net = lab.case("contraction", cells=16)
    # This reproducible active-set transition defeats the initial 0.5 s Newton
    # solve. Unconditional linear stability does not guarantee Newton convergence.
    with pytest.raises(RuntimeError):
        lab.implicit_step(net, net.initial, .5)
    h, result = lab.integrate(net, duration=.5, dt_max=.5)
    assert result["rejected_steps"] > 0
    assert result["max_residual_depth_m"] < 1e-10
    assert h.min() >= -1e-12
    assert abs(result["mass_error_m3"]) < 1e-7


@pytest.mark.parametrize("method", ["explicit", "newton_tree", "frozen_flux"])
def test_rest_and_below_lip_do_not_move(method):
    net = lab.case("lake_at_rest")
    result, _ = lab.integrate(net, method, duration=.1)
    np.testing.assert_allclose(result, net.initial, atol=1e-13)
    net = lab.case("adverse_step")
    net.initial *= .2  # 0.4 m pool below 1 m bed step
    result, _ = lab.integrate(net, method, duration=.1)
    np.testing.assert_allclose(result, net.initial, atol=1e-13)


@pytest.mark.parametrize("method", ["newton_tree", "frozen_flux"])
def test_temporal_refinement_toward_independent_radau(method):
    net = lab.case("flat_dam", cells=12)
    eps = 1e-10 if method == "frozen_flux" else 1e-6
    ref, _ = lab.radau_reference(net, duration=1., eps=eps)
    tighter, _ = lab.radau_reference(net, duration=1., eps=eps, rtol=1e-10, atol=1e-12)
    assert max(abs(ref-tighter)) < 2e-7
    errors = []
    for dt in (.2, .05, .0125):
        h, result = lab.integrate(net, method, duration=1., dt_max=dt)
        assert h.min() >= -1e-10
        assert abs(result["mass_error_m3"]) < 1e-7
        errors.append(np.mean(abs(h-ref)))
    assert errors[1] < .5*errors[0]
    assert errors[2] < .5*errors[1]


def test_directed_backwater_is_a_model_limitation():
    net = lab.case("backwater_directed", cells=12)
    directed, _ = lab.integrate(net, duration=1.)
    signed, _ = lab.integrate(replace(net, reverse=True), duration=1.)
    np.testing.assert_array_equal(directed, net.initial)
    assert signed[5] > .1  # upstream wetting is possible only with signed links


def test_implicit_stability_does_not_imply_no_ringing():
    r = lab.linear_diffusion_experiment()
    assert r["explicit"]["min_depth"] < 0
    assert r["crank_nicolson"]["amplitude_ratio"] == pytest.approx(-19/21)
    assert r["backward_euler"]["amplitude_ratio"] == pytest.approx(1/41)
    assert r["rannacher_start"]["amplitude_ratio"] == pytest.approx(1/441)


def test_flat_water_stiffness_scales_with_dx_squared_and_sqrt_epsilon():
    net = lab.case("near_level", cells=8)
    h = np.ones(8)
    def rate(n, eps):
        _, a, b = lab.flux_jacobian(n, h, eps)
        diag, _, _ = lab.jacobian_bands(n, a, b, 1.)
        return max((diag-n.storage)/n.storage)
    base = rate(net, 1e-6)
    assert rate(net, 1e-8)/base == pytest.approx(10.)
    assert rate(replace(net, length=net.length/2, storage=net.storage/2), 1e-6)/base == pytest.approx(4.)
