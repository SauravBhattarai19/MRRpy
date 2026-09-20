# HPC routing validation instructions

Validate the routing changes on branch `fix/diffusive-routing-gpu-validation`
using a real NVIDIA CUDA GPU. Produce a reproducible report and raw artifacts
that can be returned for review. Do the work, including investigating failures;
do not stop after proposing a plan. Use neutral filenames and ordinary Git
authorship, with no AI signature, co-author trailer, or acknowledgement.

## Scope and baseline

Read `docsite/routing-stability-audit.md` and
`docsite/diffusive-flat-water-investigation.md`, then inspect the routing kernels
and the test/experiment scripts. The branch contains explicit kinematic,
diffusive, Muskingum–Cunge, and local-inertial routing. Independent implicit/tree
and flux-variable solvers are CPU research prototypes, not GPU production
options. The full shallow-water HLL/Ritter experiment is a separate benchmark.

The clean branch's CPU verification passed **160 tests with 78 skips** (76 CUDA
and two external-data cases). Its log is
`docsite/assets/diffusive-lab/branch-validation.txt`. The earlier development
workspace passed 174 tests but also contained unrelated uncommitted tests that
were excluded from this branch. Report actual collection and skip counts on
HPC; do not use a matching test count as the acceptance criterion.

Known issues must remain visible: Muskingum–Cunge can produce negative storage;
local-inertia routing can clip heavily; float32 diffusive mass error reached
about 1e-5 relative. The diffusion fixes do not establish physical validity for
fast dam breaks. A passing suite is not permission to label every scheme valid.

## Obtain and verify a GPU allocation

Use the cluster's allocated compute node, not a login node. Inspect available
scheduler/environment configuration; ask for missing partition/account or
allocation details if necessary. Do not invent an account or request a large
multi-GPU job. One GPU is enough. Record the scheduler job ID and wall-time limit.

Record commit SHA, working-tree status, OS, Python, NumPy, SciPy, CuPy, driver,
CUDA runtime, GPU model, device count, and visible devices. Use a dedicated
environment. Install this checkout with its declared dependencies and pytest;
the repository's `[gpu]` extra targets CUDA 12.x. Check cluster compatibility
before installing an appropriate CuPy distribution. Do not install multiple
conflicting CuPy distributions or alter a shared system environment.

Run `nvidia-smi` and the following in the same environment/allocation as tests:

```python
import pathlib
import cupy as cp
import MRRpy
print("Package:", pathlib.Path(MRRpy.__file__).resolve())
print("Devices:", cp.cuda.runtime.getDeviceCount())
assert cp.cuda.runtime.getDeviceCount() > 0
x = cp.arange(4096, dtype=cp.float64)
assert float(cp.sum(x).get()) == 4095 * 4096 / 2
cp.cuda.Stream.null.synchronize()
cp.show_config()
```

Confirm the imported package comes from this checkout. Stop GPU validation with
a clear infrastructure failure if the CUDA probe fails. Never substitute NumPy
for CuPy or count a skipped CUDA test as a pass. If GDAL/PROJ reports conflicting
databases, diagnose the environment before changing numerical code.

## Execute the tests and experiments

Create a fresh results directory outside tracked sources, such as
`/scratch/$USER/routing-validation-<job-id>`. Set `AUDIT_RESULTS` to that actual
path. Keep complete stdout/stderr, exit statuses, test JUnit XML, JSON and NPZ
artifacts. Capture failed commands too. When using `tee`, enable `set -o pipefail`.
Run long commands through the scheduler or a persistent session.

Run these commands from the repository root, without `--quick`:

```sh
export PYMRR_REQUIRE_GPU=1
python -m pytest tests/test_routing_stability.py -ra -v --junitxml="$AUDIT_RESULTS/routing-tests.xml"
python -m pytest -ra -v --junitxml="$AUDIT_RESULTS/full-suite.xml"

python tools/routing_stability_audit.py --backend cpu --refinement --output "$AUDIT_RESULTS/routing-cpu"
python tools/routing_stability_audit.py --backend gpu --refinement --output "$AUDIT_RESULTS/routing-gpu-1"
python tools/routing_stability_audit.py --backend gpu --output "$AUDIT_RESULTS/routing-gpu-2"
python tools/routing_stability_audit.py --backend gpu --output "$AUDIT_RESULTS/routing-gpu-3"

python tools/routing_dam_break_experiments.py --backend cpu --output "$AUDIT_RESULTS/dam-cpu"
python tools/routing_dam_break_experiments.py --backend gpu --output "$AUDIT_RESULTS/dam-gpu"

python tools/diffusive_independent_lab.py --output "$AUDIT_RESULTS/independent-cpu"
python tools/plot_diffusive_lab.py "$AUDIT_RESULTS/independent-cpu"
```

The production audit must contain 48 cases per full run: four schemes × six
geometries × two precisions. Refinement and dam-release scripts use additional
cases; inspect their actual coverage instead of assuming they test both dtypes.
The existing parity test covers confluence; compare saved CPU/GPU fields for
**all six geometries** as an additional analysis. Do not mistake CPU-only surge,
implicit, or analytic checks for GPU validation just because a GPU is allocated.

Also repeat the shared surge fixture on GPU for all four schemes, both
`CHANNEL_ROUTING=False/True`, and float64/float32. Adapt it in a results-side
runner (keep production code unchanged for the baseline): explicitly set
`BACKEND="gpu"`, `GPU_PRECISION`, and `CHANNEL_ROUTING`. Merely setting channel
width does not enable channels. Instrument/assert that `run_time_loop` receives
CuPy-backed grid state; do not rely solely on the configuration label. Capture
the router's `routing_diagnostics`, gauge hydrographs, mass ledger, and warnings.
Keep the 50 m³/s baseline pulse and add the user's actual dam-release dataset
only if it is available; label synthetic and supplied-data results separately.

## Analysis required

- Check the near-flat checkerboard regression at stage slopes 1e-7 and 1e-5.
  Before the final guard, the low-slope mode's amplification was about -0.70;
  after the fix it was about +0.15 at CFL target 0.85. Confirm damping without
  sign reversal on CUDA, not merely finite/nonnegative depths.
- Check lake-at-rest, dry cells, adverse bed lips, true elevation differences,
  narrow receiving storage, confluence contributions, static subcycling, and
  the rule that `CFL_DT_MIN` cannot raise an unsafe timestep.
- Tabulate finiteness, minimum storage/depth, absolute and relative volume
  error, interior/gauge oscillation, limiter fraction, timestep extrema/count,
  Froude diagnostics, and MC coefficient violations by scheme/case/precision.
  A warning or known expected failure is not an unexplained success.
- Compare CPU/GPU depth, discharge, and hydrographs with maximum absolute and
  scaled errors. Inspect saved time arrays; interpolate onto common times only
  when necessary and document it. Existing parity tolerances are 1e-8/1e-9
  (relative/absolute) for float64 and 3e-4/3e-5 for float32. Do not loosen them to
  pass; report whether failures arise from time-grid differences, reductions,
  precision sensitivity, or different mathematical behavior.
- Compare all three GPU runs for nondeterministic scatter/reduction effects.
  Report observed differences; do not demand bitwise equality unless justified.
- Assess timestep/grid/epsilon refinement, reservoir-release ablations, and HLL
  convergence against Ritter. Distinguish numerical convergence from physical
  suitability. Check internal fields, not only averaged outlet hydrographs.
- Separate runtime observations from equal-accuracy performance comparisons.
  If timing GPU kernels, warm up and synchronize; report setup/JIT and I/O
  separately where possible. Tiny synthetic cases do not establish basin-scale
  acceleration.

If a test fails, preserve the original failure and reproduce the smallest case.
Explain the likely cause before changing anything. Keep the baseline commit
unchanged. Put any necessary fix in a separate local commit/patch, then rerun
the affected tests and full suite. Do not suppress assertions, alter reference
results, weaken tolerances, or hide known MC/local-inertia defects. Do not push
changes or send results elsewhere unless the user explicitly asks.

## Deliverables

Create `GPU_VALIDATION_REPORT.md` and `GPU_VALIDATION_SUMMARY.json` under the
results directory. Include the exact tested SHA, environment/allocation,
commands and exit codes, pass/fail/skip counts with reasons, case coverage,
CPU/GPU and repeatability tables, refinement plots, failures with reproduction
commands, any patch, and an explicit verdict for each routing scheme/precision.
Answer: which diffusive oscillation defects are fixed on GPU, which restrictions
remain, and whether evidence supports the user's intended dam-release regime.

Bundle the report, summary, environment details, JUnit/logs, JSON, NPZ/CSV,
figures, and any patch into a compressed archive with checksums. Exclude secrets,
credentials, unrelated datasets, and the environment itself. Finish with the
report/archive paths and a concise evidence-based verdict so the user can send
the results back for review.
