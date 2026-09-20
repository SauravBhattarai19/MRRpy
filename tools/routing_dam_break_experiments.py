"""Dam-release ablations and a separate full-SWE HLL/Ritter reference experiment.

The HLL prototype is flat-bed, frictionless, 1-D only; it is not a production
terrain solver. The diffusion ablation freezes the old discharge law explicitly
so the before/after evidence can be reproduced without a private checkout.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MRRpy.core.routing import hydraulics
from MRRpy.utils import gpu_utils
from tools.routing_stability_audit import backend


def diffusion_release(mode="guarded", xp=np, dt_max=.5, eps=1e-6,
                      duration=20., terrain="steep_flat", theta=1., cells=48):
    count, dx, width, roughness = cells, 480./cells, 10., .025
    dist = xp.full(count, dx)
    z = .1*xp.maximum(160-dx*xp.arange(count), 0.) if terrain == "steep_flat" else xp.zeros(count)
    slope = xp.maximum((z-xp.roll(z, -1))/dx, 1e-4)
    slope[-1] = 0.  # closed boundary for reservoir-volume test
    ds = xp.minimum(xp.arange(count)+1, count-1)
    valid = xp.arange(count) < count-1
    widths, chan, store = xp.full(count, width), xp.ones(count, dtype=bool), xp.full(count, width*dx)
    depth = xp.where(dx*xp.arange(count)<80, 10., 0.)
    volume = depth*store
    pending = xp.zeros(count)
    time, steps, max_depth, clipped, history = 0., 0, 10., 0, []
    next_out = .5
    while time < duration-1e-10:
        depth = volume/store
        if mode in ("legacy", "small_dt", "theta_blend", "slope_cap", "synchronous"):
            th = .2 if mode == "theta_blend" else theta
            s0 = xp.minimum(slope, .02) if mode == "slope_cap" else slope
            seff = xp.maximum(s0 + th*(depth-depth[ds])/dist, 0.)
            hf = xp.maximum(depth, 1e-6)  # downhill forward flux uses own depth
            area = widths*hf
            radius = area/(widths+2*hf)
            q = area*radius**(2/3)*xp.sqrt(seff)/roughness
            q[-1] = 0.
        else:
            q, area, seff = hydraulics.diffusive_wave_discharge(depth, z, dist, slope,
                roughness, ds, valid, theta, dx, xp, 1e-6, widths, chan,
                slope_regularization=eps)
        dt = min(dt_max, duration-time, next_out-time)
        if mode == "guarded":
            rate = hydraulics.diffusive_inverse_timestep(q, area, seff, roughness,
                widths, chan, dx, dist, store, ds, valid, theta, eps, xp)
            dt = min(dt, .8/max(float(rate.max().item()), 1e-30))
        clipped += int(bool((q*dt>volume+1e-12).any().item()))
        transfer = xp.minimum(q*dt, volume)
        incoming = xp.zeros(count)
        delayed = mode in ("legacy", "small_dt", "theta_blend", "slope_cap")
        incoming[1:] = pending[:-1] if delayed else transfer[:-1]
        volume = volume-transfer+incoming
        pending = transfer
        time += dt
        steps += 1
        max_depth = max(max_depth, float((volume/store).max().item()))
        if time >= next_out-1e-10:
            history.append(gpu_utils.to_cpu(volume/store).copy())
            next_out += .5
        if steps > 2000000:
            raise RuntimeError("Experiment exceeded step budget")
    profiles = np.asarray(history)
    final = gpu_utils.to_cpu(volume/store)
    total = float(volume.sum().item()) + (float(pending[:-1].sum().item()) if delayed else 0.)
    # Upward jumps on an initially monotone *flat* reservoir profile flag new extrema.
    reversal = float(np.maximum(np.diff(profiles, axis=1), 0).max())
    metrics = dict(mode=mode, terrain=terrain, cells=cells, dt_max=dt_max,
        slope_eps=eps, theta=.2 if mode == "theta_blend" else theta,
        steps=steps, clipped_steps=clipped, max_depth=max_depth,
        largest_upward_depth_jump=reversal, mass_error_m3=total-8000.,
        temporal_curvature=float(np.abs(np.diff(profiles, n=2, axis=0)).sum()/max(profiles.sum(), 1e-30)))
    return metrics, final, profiles


def ritter(x, t, h_left=10., g=9.81):
    c = np.sqrt(g*h_left)
    return np.where(x <= -c*t, h_left,
                    np.where(x >= 2*c*t, 0., (2*c-x/t)**2/(9*g)))


def implicit_flat_release(dt_max=.5, duration=20., eps=1e-6):
    """CPU experiment: converged backward Euler with damped Picard conductance.

    Restricted to a flat, closed, 1-D rectangular reservoir. Never accepts an
    unconverged nonlinear step. This is not connected to the production router.
    """
    from scipy.linalg import solve_banded
    count, dx, B, n = 48, 10., 10., .025
    h = np.where(np.arange(count)<8, 10., 0.)
    t, steps, iterations, retries = 0., 0, 0, 0
    history = []
    next_out = .5
    while t < duration-1e-10:
        dt = min(dt_max, duration-t, next_out-t)
        while True:
            iterate = h.copy()
            for k in range(300):
                s = (iterate[:-1]-iterate[1:])/dx
                area = B*iterate[:-1]
                K = area*(area/(B+2*iterate[:-1]))**(2/3)/n
                G = np.where(s>=0, K/(dx*np.sqrt(np.maximum(s, eps))), 0.)
                diag = np.full(count, B*dx)
                diag[:-1] += dt*G
                diag[1:] += dt*G
                band = np.zeros((3, count))
                band[0, 1:], band[1], band[2, :-1] = -dt*G, diag, -dt*G
                solved = solve_banded((1, 1), band, B*dx*h)
                iterations += 1
                if np.max(np.abs(solved-iterate)) < 1e-10:
                    break
                iterate = .5*(iterate+solved)
            else:
                dt *= .5
                retries += 1
                if dt < 1e-7:
                    raise RuntimeError("Implicit Picard failed to converge")
                continue
            break
        if solved.min() < -1e-12:
            raise FloatingPointError("Implicit experiment lost positivity")
        h = solved
        t += dt
        steps += 1
        if t >= next_out-1e-10:
            history.append(h.copy())
            next_out += .5
    profiles = np.asarray(history)
    return dict(dt_max=dt_max, steps=steps, iterations=iterations, retries=retries,
                mass_error_m3=float(h.sum()*B*dx-8000.),
                largest_upward_depth_jump=float(np.maximum(np.diff(profiles, axis=1), 0).max())), h


def swe_hll(cells=400, xp=np, duration=5.):
    """Conservative first-order HLL, dry-bed wave speeds, flat frictionless bed."""
    dx, g = 400./cells, 9.81
    x = (xp.arange(cells)+.5)*dx-200.
    U = xp.stack((xp.where(x<0, 10., 0.), xp.zeros(cells)))
    t = 0.
    min_h = 0.
    while t < duration-1e-12:
        vel = U[1]/xp.maximum(U[0], 1e-30)
        dt = min(.4*dx/float((xp.abs(vel)+xp.sqrt(g*U[0])).max().item()), duration-t)
        ext = xp.concatenate((U[:, :1], U, U[:, -1:]), axis=1)
        left, right = ext[:, :-1], ext[:, 1:]
        hl, hr = left[0], right[0]
        ul, ur = left[1]/xp.maximum(hl, 1e-30), right[1]/xp.maximum(hr, 1e-30)
        cl, cr = xp.sqrt(g*hl), xp.sqrt(g*hr)
        sl = xp.minimum(ul-cl, ur-cr)
        sr = xp.maximum(ul+cl, ur+cr)
        sl = xp.where(hl <= 1e-14, ur-2*cr, sl)
        sr = xp.where(hr <= 1e-14, ul+2*cl, sr)
        fl = xp.stack((left[1], left[1]*ul+.5*g*hl*hl))
        fr = xp.stack((right[1], right[1]*ur+.5*g*hr*hr))
        f = (sr*fl-sl*fr+sl*sr*(right-left))/xp.maximum(sr-sl, 1e-30)
        f = xp.where(sl>=0, fl, xp.where(sr<=0, fr, f))
        U -= dt/dx*(f[:, 1:]-f[:, :-1])
        min_h = min(min_h, float(U[0].min().item()))
        if min_h < -1e-12:
            raise FloatingPointError("HLL lost positivity")
        t += dt
    xc, hc = gpu_utils.to_cpu(x), gpu_utils.to_cpu(U[0])
    exact = ritter(xc, duration)
    return dict(cells=cells, l1_depth_m=float(np.mean(np.abs(hc-exact))),
                min_depth_m=min_h, mass_error_m2=float(hc.sum()*dx-2000.)), xc, hc, exact


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=("cpu", "gpu"), default="cpu")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    xp = backend(args.backend)
    args.output.mkdir(parents=True, exist_ok=True)
    results, profiles = [], {}
    for terrain in ("flat", "steep_flat"):
        reference, ref, _ = diffusion_release(xp=xp, dt_max=.002, terrain=terrain)
        for mode, dt in (("legacy", .5), ("small_dt", .05), ("theta_blend", .5),
                         ("slope_cap", .5), ("synchronous", .5),
                         ("regularized_only", .5), ("guarded", .5), ("guarded", .1),
                         ("guarded", .02)):
            m, final, frames = diffusion_release(mode, xp, dt_max=dt, terrain=terrain)
            m["l1_to_ref_m"] = float(np.mean(np.abs(final-ref)))
            results.append(m)
            profiles[f"{terrain}_{mode}_{dt}"] = frames
            print(json.dumps(m), flush=True)
        for eps in (1e-4, 1e-5, 1e-7):
            m, final, frames = diffusion_release(xp=xp, dt_max=.1, eps=eps, terrain=terrain)
            m["l1_to_ref_m"] = float(np.mean(np.abs(final-ref)))
            results.append(m)
    swe = []
    for cells in (200, 400, 800):
        m, x, numerical, exact = swe_hll(cells, xp)
        swe.append(m)
        profiles[f"swe_{cells}"] = np.stack((x, numerical, exact))
    implicit = []
    if args.backend == "cpu":
        _, ref, _ = diffusion_release(xp=xp, dt_max=.0005, terrain="flat")
        for dt in (.5, .1, .02):
            m, final = implicit_flat_release(dt)
            m["l1_to_explicit_ref_m"] = float(np.mean(np.abs(final-ref)))
            implicit.append(m)
    np.savez_compressed(args.output / "profiles.npz", **profiles)
    (args.output / "summary.json").write_text(json.dumps(dict(
        backend=args.backend, diffusion=results, swe_hll=swe, implicit_flat=implicit), indent=2))
    print(json.dumps(swe), flush=True)


if __name__ == "__main__":
    main()
