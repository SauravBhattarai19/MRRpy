"""Independent diffusion experiments: no MRRpy kernels used by the solvers.

Closed rectangular storage networks; parents are topologically ordered, with
each parent index larger than its child. Research prototypes, not model options.
python tools/diffusive_independent_lab.py --output /tmp/diffusive-lab
"""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import time

import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import spsolve


@dataclass
class Network:
    parent: np.ndarray
    bed: np.ndarray
    storage: np.ndarray
    width: np.ndarray
    length: np.ndarray
    roughness: np.ndarray
    initial: np.ndarray
    reverse: bool = False

    def __post_init__(self):
        self.child = np.flatnonzero(self.parent >= 0)
        self.receiver = self.parent[self.child]
        if np.any(self.receiver <= self.child) or np.any(self.receiver >= len(self.parent)):
            raise ValueError("A topologically ordered tree/forest is required")
        if any(np.any(a <= 0) for a in (self.storage, self.width, self.length, self.roughness)):
            raise ValueError("Positive geometry and roughness required")


def case(name="flat_dam", cells=32):
    parent = np.r_[np.arange(1, cells), -1]
    length = np.full(cells, 10.)
    bed = np.zeros(cells)
    width = np.full(cells, 10.)
    initial = np.where(np.arange(cells) < cells//4, 2., 0.)
    reverse = False
    if name == "steep_flat":
        bed = np.maximum(cells//4-np.arange(cells), 0.)
    elif name == "contraction":
        width[cells//4:] = 1.
    elif name == "confluence":
        parent[:4] = 4
        initial[:] = 0.
        initial[:4] = 2.
    elif name == "adverse_step":
        bed[cells//4:] = 1.
    elif name == "lake_at_rest":
        bed = np.maximum(cells//2-np.arange(cells), 0.)*.1
        initial = 3.-bed
    elif name == "near_level":
        initial = 1.+1e-4*np.cos(np.linspace(0, np.pi, cells))
    elif name in ("backwater_directed", "backwater_signed"):
        initial = np.where(np.arange(cells) >= cells//2, 2., 0.)
        reverse = name.endswith("signed")
    elif name != "flat_dam":
        raise ValueError(name)
    return Network(parent, bed, width*length, width, length,
                   np.full(cells, .03), initial, reverse)


def flux_jacobian(net, depth, eps=1e-6):
    """Independent rectangular Manning law and exact piecewise face Jacobian.

    Returns q, dq/dh_child, dq/dh_parent. No artificial wet-depth floor.
    With reverse=False, adverse heads block discharge as in the production D8 law.
    """
    i, j = net.child, net.receiver
    delta = net.bed[i]-net.bed[j]+depth[i]-depth[j]
    magnitude = abs(delta)/net.length[i]
    donor_child = delta >= 0
    higher_bed = np.maximum(net.bed[i], net.bed[j])
    hf = np.maximum(np.maximum(net.bed[i]+depth[i], net.bed[j]+depth[j])-higher_bed, 0.)
    B = net.width[i]
    A = B*hf
    R = A/(B+2*hf)
    K = A*R**(2/3)/net.roughness[i]
    Kprime = B*R**(2/3)/net.roughness[i]*(1.+(2/3)*B/(B+2*hf))
    root = np.sqrt(np.maximum(magnitude, eps))
    phi = magnitude/root
    phi_prime = np.where(magnitude < eps, 1./root, .5/root)
    direction = np.where(donor_child, 1., -1.)
    q = direction*K*phi
    g = K*phi_prime/net.length[i]
    a = direction*Kprime*phi*donor_child+g
    b = direction*Kprime*phi*(~donor_child)-g
    if not net.reverse:
        active = delta >= 0
        q, a, b = q*active, a*active, b*active
    return q, a, b


def divergence(net, q):
    out = np.zeros(len(net.parent))
    out[net.child] += q
    np.add.at(out, net.receiver, -q)
    return out


def jacobian_bands(net, a, b, dt):
    diag = net.storage.copy()
    diag[net.child] += dt*a
    np.add.at(diag, net.receiver, -dt*b)
    return diag, dt*b, -dt*a


def tree_solve(net, diag, upper, lower, rhs):
    """O(N) Gaussian elimination on a forest, allowing nonsymmetric edge entries.

    upper[k]=A[child,parent], lower[k]=A[parent,child]. No fill beyond the tree.
    Independent implementation checked against scipy sparse and dense solves.
    """
    d, b = diag.copy(), rhs.copy()
    for k, (i, j) in enumerate(zip(net.child, net.receiver)):
        multiplier = lower[k]/d[i]
        d[j] -= multiplier*upper[k]
        b[j] -= multiplier*b[i]
    roots = np.flatnonzero(net.parent < 0)
    x = np.zeros_like(b)
    x[roots] = b[roots]/d[roots]
    for k in range(len(net.child)-1, -1, -1):
        i, j = net.child[k], net.receiver[k]
        x[i] = (b[i]-upper[k]*x[j])/d[i]
    return x


def sparse_matrix(net, diag, upper, lower):
    n = len(diag)
    return coo_matrix((np.r_[diag, upper, lower],
        (np.r_[np.arange(n), net.child, net.receiver],
         np.r_[np.arange(n), net.receiver, net.child])), shape=(n, n)).tocsc()


def implicit_step(net, old, dt, eps=1e-6, linear_solver="tree", tolerance=1e-10,
                  max_iterations=60):
    """Fully nonlinear backward Euler with analytic Jacobian and line search.

    A step must satisfy the *continuity residual*, not merely a small iterate
    change. Failed nonlinear solves are rejected by the caller and dt is halved.
    No depth/flux clipping is applied to accepted steps.
    """
    x = old.copy()
    for iteration in range(max_iterations):
        q, a, b = flux_jacobian(net, x, eps)
        residual = net.storage*(x-old)+dt*divergence(net, q)
        norm = np.max(abs(residual)/net.storage)
        if norm < tolerance:
            return x, iteration, float(norm)
        diag, upper, lower = jacobian_bands(net, a, b, dt)
        if linear_solver == "tree":
            update = tree_solve(net, diag, upper, lower, -residual)
        else:
            update = spsolve(sparse_matrix(net, diag, upper, lower), -residual)
        # Do not silently clip negative water: reject the trial or the whole step.
        damping = 1.
        for _ in range(32):
            trial = x+damping*update
            if trial.min() >= -1e-13:
                tq, _, _ = flux_jacobian(net, trial, eps)
                tr = net.storage*(trial-old)+dt*divergence(net, tq)
                if np.max(abs(tr)/net.storage) <= (1-1e-4*damping)*norm:
                    x = trial
                    break
            damping *= .5
        else:
            raise RuntimeError("Newton line search failed")
    raise RuntimeError("Newton iteration limit reached")


def explicit_step(net, old, dt_ceiling, eps=1e-6):
    q, a, b = flux_jacobian(net, old, eps)
    diag, _, _ = jacobian_bands(net, a, b, 1.)
    rate = (diag-net.storage)/net.storage
    # Factor two below the frozen-coefficient bound also covers the jump in
    # slope derivative at epsilon. Dry-front positivity is checked separately.
    dt = min(dt_ceiling, .4/max(float(rate.max()), 1e-30))
    # Conservative donor-volume bound, including signed reverse flow.
    outgoing = np.zeros(len(old))
    np.add.at(outgoing, net.child, np.maximum(q, 0.))
    np.add.at(outgoing, net.receiver, np.maximum(-q, 0.))
    wet_out = outgoing > 0
    if wet_out.any():
        dt = min(dt, .9*np.min(net.storage[wet_out]*old[wet_out]/outgoing[wet_out]))
    return old-dt*divergence(net, q)/net.storage, dt


def frozen_flux_step(net, old, dt):
    """Unregularized, semi-implicit flux-variable experiment (lagged conveyance).

    q*abs(q)*L/K_old² + dt*B.T*M^-1*B*q = B.T*eta_old.
    The square-root head singularity is absent from this formulation. Directed
    links use the corresponding q>=0 convex constrained problem. No claim of
    fully nonlinear backward Euler: conveyance is frozen at the old state.
    """
    i, j = net.child, net.receiver
    eta = net.bed+old
    hf = np.maximum(np.maximum(eta[i], eta[j])-np.maximum(net.bed[i], net.bed[j]), 0.)
    area = net.width[i]*hf
    K = area*(area/(net.width[i]+2*hf))**(2/3)/net.roughness[i]
    active = K > 1e-14
    if not active.any():
        return old.copy(), 0
    ii, jj = i[active], j[active]
    m = len(ii)
    B = coo_matrix((np.r_[np.ones(m), -np.ones(m)],
        (np.r_[ii, jj], np.r_[np.arange(m), np.arange(m)])), shape=(len(old), m)).tocsc()
    H = dt*B.T@diags(1/net.storage)@B
    nonlinear = net.length[ii]/K[active]**2
    delta = eta[ii]-eta[jj]
    # Exact coordinate minimization avoids badly scaled dry-face K^-2 Hessians.
    # This is a validation prototype, not an optimized linear-algebra strategy.
    matrix = H.tocsr()
    diagonal = matrix.diagonal()
    q = np.zeros(m)
    for iteration in range(5000):
        for k in range(m):
            a, b = matrix.indptr[k:k+2]
            rhs = delta[k]-matrix.data[a:b]@q[matrix.indices[a:b]]+diagonal[k]*q[k]
            if not net.reverse:
                rhs = max(rhs, 0.)
            q[k] = np.sign(rhs)*2*abs(rhs)/(diagonal[k]+np.sqrt(
                diagonal[k]**2+4*nonlinear[k]*abs(rhs)))
        gradient = H@q+nonlinear*q*abs(q)-delta
        projected = gradient if net.reverse else np.where(q > 0, gradient, np.minimum(gradient, 0.))
        if np.max(abs(projected)) < 1e-9:
            break
    else:
        raise RuntimeError("Flux-form optimization did not satisfy its KKT residual")
    new = old-dt*(B@q)/net.storage
    if new.min() < -1e-10:
        raise RuntimeError("Frozen-conveyance flux step lost positivity")
    return new, iteration+1


def integrate(net, method="newton_tree", duration=5., dt_max=.5, eps=1e-6,
              tolerance=1e-10):
    h = net.initial.copy()
    t, steps, iterations, rejects, residual = 0., 0, 0, 0, 0.
    min_depth, max_depth = float(h.min()), float(h.max())
    wall = time.perf_counter()
    while t < duration-1e-12:
        dt = min(dt_max, duration-t)
        if method == "explicit":
            hn, dt = explicit_step(net, h, dt, eps)
        elif method in ("newton_tree", "newton_sparse", "frozen_flux"):
            while True:
                try:
                    if method == "frozen_flux":
                        hn, nit = frozen_flux_step(net, h, dt)
                        res = 0.  # residual is checked in flux KKT units, not depth
                    else:
                        hn, nit, res = implicit_step(net, h, dt, eps,
                            "tree" if method.endswith("tree") else "sparse", tolerance)
                    iterations += nit
                    residual = max(residual, res)
                    break
                except RuntimeError:
                    rejects += 1
                    dt *= .5
                    if dt < 1e-9:
                        raise
        else:
            raise ValueError(method)
        if not np.isfinite(hn).all() or hn.min() < -1e-10 or dt <= 0:
            raise FloatingPointError("Invalid depth or timestep")
        h = hn
        t += dt
        steps += 1
        min_depth = min(min_depth, float(h.min()))
        max_depth = max(max_depth, float(h.max()))
        if steps > 500000:
            raise RuntimeError("Experiment step budget exceeded")
    return h, dict(method=method, dt_max=dt_max, slope_eps=0. if method=="frozen_flux" else eps, steps=steps,
        nonlinear_iterations=iterations, rejected_steps=rejects,
        nonlinear_solver="coordinate_minimization" if method=="frozen_flux" else "newton" if method.startswith("newton") else None,
        max_residual_depth_m=residual if method.startswith("newton") else None,
        wall_s=time.perf_counter()-wall, min_depth=min_depth, max_depth=max_depth,
        mass_error_m3=float(np.dot(net.storage, h-net.initial)))


def radau_reference(net, duration=5., eps=1e-6, rtol=1e-9, atol=1e-11):
    """Independent integration algorithm from SciPy, sharing only this lab's law."""
    def rhs(t, h):
        return -divergence(net, flux_jacobian(net, h, eps)[0])/net.storage
    def jac(t, h):
        _, a, b = flux_jacobian(net, h, eps)
        diag, upper, lower = jacobian_bands(net, a, b, 1.)
        return -diags(1/net.storage)@sparse_matrix(net, diag-net.storage, upper, lower)
    sol = solve_ivp(rhs, (0., duration), net.initial, method="Radau", jac=jac,
                    rtol=rtol, atol=atol)
    if not sol.success:
        raise RuntimeError(sol.message)
    return sol.y[:, -1], dict(nfev=sol.nfev, njev=sol.njev, nlu=sol.nlu,
        mass_error_m3=float(np.dot(net.storage, sol.y[:, -1]-net.initial)))


def two_cell_exact(t, delta0=1e-4, conductance=10., volume_area=100., length=10., eps=0.):
    """Exact frozen-conveyance head-difference decay, including epsilon bias.

    d(delta)/dt = -a sqrt(delta) above L*eps; below it the regularized law
    decays exponentially. This scalar oracle does not call a numerical solver.
    """
    t = np.asarray(t)
    a = 2*conductance/(volume_area*np.sqrt(length))
    if eps == 0:
        return np.maximum(np.sqrt(delta0)-a*t/2, 0.)**2
    threshold = length*eps
    if delta0 <= threshold:
        return delta0*np.exp(-a*t/np.sqrt(threshold))
    switch = 2*(np.sqrt(delta0)-np.sqrt(threshold))/a
    return np.where(t <= switch, np.maximum(np.sqrt(delta0)-a*t/2, 0.)**2,
                    threshold*np.exp(-a*np.maximum(t-switch, 0)/np.sqrt(threshold)))


def linear_diffusion_experiment():
    """Exact semidiscrete eigenmode oracle exposes Crank-Nicolson ringing."""
    count, fourier = 16, 10.
    h0 = 1.+.2*(-1.)**np.arange(count)
    # Periodic Laplacian, coefficient D*dt/dx² = fourier.
    L = -2*np.eye(count)+np.roll(np.eye(count), 1, axis=1)+np.roll(np.eye(count), -1, axis=1)
    identity = np.eye(count)
    explicit = h0+fourier*L@h0
    backward = np.linalg.solve(identity-fourier*L, h0)
    crank = np.linalg.solve(identity-.5*fourier*L, (identity+.5*fourier*L)@h0)
    exact = 1.+np.exp(-4*fourier)*(h0-1.)
    # Rannacher start: two BE half steps for this first discontinuous time interval.
    rannacher = np.linalg.solve(identity-.5*fourier*L,
        np.linalg.solve(identity-.5*fourier*L, h0))
    return {name: dict(min_depth=float(h.min()), max_depth=float(h.max()),
        amplitude_ratio=float((h[0]-1.)/.2), l1_error=float(np.mean(abs(h-exact))))
        for name, h in (("explicit", explicit), ("backward_euler", backward),
                        ("crank_nicolson", crank), ("rannacher_start", rannacher))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    names = ("flat_dam", "steep_flat", "contraction", "confluence", "adverse_step",
             "lake_at_rest", "near_level", "backwater_directed", "backwater_signed")
    results, profiles, references = [], {}, {}
    for name in names:
        net = case(name)
        reference, info = radau_reference(net)
        tight_reference, tight_info = radau_reference(net, rtol=1e-10, atol=1e-12)
        info["tolerance_refinement_linf_m"] = float(np.max(abs(reference-tight_reference)))
        # The flux-variable method has no epsilon; compare against a small-epsilon
        # approximation separately, not just against a different constitutive law.
        small_eps_reference, small_eps_info = radau_reference(net, eps=1e-10)
        info["epsilon_1e6_vs_1e10_l1_m"] = float(np.mean(abs(reference-small_eps_reference)))
        references[name] = info
        profiles[name+"_radau"] = reference
        profiles[name+"_radau_eps1e10"] = small_eps_reference
        for method in ("explicit", "newton_tree", "newton_sparse", "frozen_flux"):
            for dt in ((.5,) if args.quick or method=="explicit" else (.5, .1, .02)):
                h, result = integrate(net, method, dt_max=dt)
                result.update(case=name, l1_error_m=float(np.mean(abs(h-reference))))
                if method == "frozen_flux":
                    result["l1_error_small_epsilon_reference_m"] = float(np.mean(abs(h-small_eps_reference)))
                results.append(result)
                profiles[f"{name}_{method}_{dt}"] = h
                print(json.dumps(result), flush=True)
    bias = []
    for eps in (1e-2, 1e-4, 1e-6, 1e-8):
        bias.append(dict(eps=eps, exact_delta_at_1s=float(two_cell_exact(1., eps=eps))))
    summary = dict(hardware="NumPy/SciPy CPU; no GPU claims", results=results,
        references=references, linear_diffusion=linear_diffusion_experiment(),
        regularization_bias=bias, unregularized_delta_at_1s=float(two_cell_exact(1.)))
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2))
    np.savez_compressed(args.output/"profiles.npz", **profiles)


if __name__ == "__main__":
    main()
