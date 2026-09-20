"""Reproducible routing stress experiments; GPU requests never fall back to CPU.

Run from the repository root:
    python tools/routing_stability_audit.py --backend cpu --output /tmp/audit
    python tools/routing_stability_audit.py --backend gpu --output /tmp/audit-gpu
The JSON and NPZ artifacts include interior fields, not just outlet averages.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MRRpy import Config
from MRRpy.core.routing import router, hydraulics
from MRRpy.utils import gpu_utils

SCHEMES = ("kinematic", "diffusive", "muskingum", "dynamic")
CASES = ("steep_flat", "flat", "steep", "contraction", "confluence", "diagonal")


def backend(name):
    if name == "cpu":
        return np
    if not gpu_utils.cupy_available():
        raise RuntimeError("CUDA GPU unavailable: refusing CPU fallback for GPU audit")
    import cupy as cp
    cp.zeros(1).sum().item()  # force context creation and actual device execution
    return cp


def grid(case="steep_flat", xp=np, precision="float64", cells=32, dx=10., pulse=2.):
    dtype = np.dtype(precision)
    dist = np.full(cells, dx * (2**.5 if case == "diagonal" else 1.))
    slopes = np.full(cells, .08)
    if case in ("steep_flat", "confluence", "diagonal", "contraction"):
        slopes[cells // 3:] = 0.
    if case == "flat":
        slopes[:] = 0.
    z = np.cumsum((slopes * dist)[::-1])[::-1]
    width = np.full(cells, dx)
    if case == "contraction":
        width[cells // 2:] = dx / 10
    ds = np.arange(1, cells + 1)
    ds[-1] = -1
    source_cells = [0]
    if case == "confluence":
        ds[:4] = 4
        z[:4] = z[4] + .08 * dx
        source_cells = list(range(4))
    valid = ds >= 0
    s = np.full(cells, 1e-4)
    s[valid] = np.maximum((z[valid] - z[ds[valid]]) / dist[valid], 1e-4)
    src = np.zeros(cells)
    src[source_cells] = 10. / pulse  # 10 m equivalent pulse at each headwater
    class Rain:
        def get_field_1d(self, t):
            return xp.asarray(src if t < pulse - 1e-10 else src * 0, dtype=dtype)
    return dict(n_cells=cells, cell_size=dx, cell_area=dx*dx,
                s_rows=np.arange(cells), s_cols=np.zeros(cells, dtype=int),
                slope_1d=xp.asarray(s, dtype=dtype), dem_1d=xp.asarray(z, dtype=dtype),
                dist_1d=xp.asarray(dist, dtype=dtype), width_1d=xp.asarray(width, dtype=dtype),
                store_area_1d=xp.asarray(width*dist, dtype=dtype),
                chan_mask_1d=xp.ones(cells, dtype=bool), ds_idx=xp.asarray(ds),
                outlet_pos=cells-1, ws_mask=np.ones((cells, 1), dtype=bool),
                n_1d=xp.full(cells, .025, dtype=dtype), precip_engine=Rain(), xp=xp)


def run_case(scheme, case, xp=np, precision="float64", dt=.5, duration=60., **overrides):
    gd = grid(case, xp, precision)
    cfg = Config(ROUTING_SCHEME=scheme, TIME_STEP_SECONDS=dt,
                 OUTPUT_INTERVAL_SECONDS=.5, TOTAL_SIMULATION_TIME_HOURS=duration/3600,
                 ADAPTIVE_TIMESTEP=True, CFL_DT_MAX=dt, GPU_PRECISION=precision,
                 SAVE_FIELDS=True, MASS_BALANCE_REPORT=True, **overrides)
    frames, ledger = [], {}
    class Recorder:
        active = True
        def __init__(self, *args):
            pass
        def record(self, t, h, q, a, v, xp):
            frames.append((t, gpu_utils.to_cpu(v).copy(), gpu_utils.to_cpu(q).copy()))
        def save(self):
            pass
    def budget(*args, **kwargs):
        ledger.update(input_m3=args[4] + kwargs.get("bc_m3", 0.),
                      outflow_m3=args[5], storage_m3=args[6], rel_error=args[8])
    stream = io.StringIO()
    with patch("MRRpy.core.routing.fields.FieldRecorder", Recorder), \
            patch.object(router, "append_mass_balance_csv", budget), \
            contextlib.redirect_stdout(stream):
        hg = np.asarray(router.run_time_loop(gd, cfg))
    v = np.asarray([f[1] for f in frames])
    q = np.asarray([f[2] for f in frames])
    h = v / gpu_utils.to_cpu(gd["store_area_1d"])
    # Normalized second temporal differences measure ringing, not an accuracy norm.
    ringing = np.abs(np.diff(q, n=2, axis=0)).sum() / max(np.abs(q).sum(), 1e-30)
    metrics = dict(scheme=scheme, case=case, precision=precision, dt_max=dt,
                   finite=bool(np.isfinite(v).all() and np.isfinite(q).all()),
                   min_volume_m3=float(v.min()), max_depth_m=float(h.max()),
                   peak_outlet_m3s=float(hg[:, 1].max()), ringing=float(ringing), **ledger)
    metrics.update(gd.get("routing_diagnostics", {}))
    return metrics, dict(time=np.asarray([f[0] for f in frames]), h=h, q=q, hg=hg), stream.getvalue()


def refinement_experiments(xp=np):
    from tools.routing_dam_break_experiments import diffusion_release
    results, refinement = [], []
    for scheme in SCHEMES:
        for case in ("steep_flat", "steep"):
            runs = [run_case(scheme, case, xp, dt=dt) for dt in (.5, .1, .02)]
            for metrics, arrays, _ in runs:
                metrics["l1_depth_to_dt002"] = float(np.mean(abs(arrays["h"]-runs[-1][1]["h"])))
                results.append(metrics)
    for terrain in ("flat", "steep_flat"):
        runs = [diffusion_release(cells=c, xp=xp, terrain=terrain, duration=5.) for c in (24, 48, 96)]
        for metrics, depths, _ in runs[:-1]:
            reference = runs[-1][1].reshape(metrics["cells"], -1).mean(axis=1)
            metrics["l1_depth_to_96"] = float(np.mean(abs(depths-reference)))
            refinement.append(metrics)
    return dict(time_refinement=results, space_refinement=refinement)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("cpu", "gpu"), default="cpu")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--refinement", action="store_true")
    args = parser.parse_args()
    xp = backend(args.backend)
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for precision in (("float64",) if args.quick else ("float64", "float32")):
        for scheme in SCHEMES:
            for case in CASES:
                metrics, arrays, log = run_case(scheme, case, xp, precision)
                key = f"{scheme}_{case}_{precision}"
                np.savez_compressed(args.output / f"{key}.npz", **arrays)
                (args.output / f"{key}.log").write_text(log)
                results.append(metrics)
                print(json.dumps(metrics), flush=True)
    device = "NumPy CPU"
    if xp is not np:
        props = xp.cuda.runtime.getDeviceProperties(xp.cuda.Device().id)
        device = str(props["name"])
        xp.cuda.Stream.null.synchronize()
    (args.output / "summary.json").write_text(json.dumps(
        dict(backend=args.backend, device=device, numpy=np.__version__, results=results), indent=2))
    if args.refinement:
        (args.output / "refinement.json").write_text(json.dumps(refinement_experiments(xp), indent=2))


if __name__ == "__main__":
    main()
