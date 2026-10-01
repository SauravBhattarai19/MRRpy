# 11 Many runs from Python

**Goal:** run many configurations in a loop, for a sensitivity study, a
calibration or a comparison, and collect the results in one table.

Because every setting is a value on one `Config`, any comparison is a loop that
changes values. Each run goes into its own results folder.

## A sweep and a results table

```python
import pandas as pd
from MRRpy import Config, run_pipeline

base = Config.from_file("run.yaml")          # e.g. the file of Example 1

rows = []
for n in (0.05, 0.09, 0.15):                 # ground roughness
    for scheme in ("kinematic", "diffusive_implicit"):
        cfg = Config.from_dict(base.to_dict())
        cfg.MANNINGS_N = n
        cfg.ROUTING_SCHEME = scheme
        cfg.OUTPUT_DIR = f"results/sweep/n{n}_{scheme}/"
        cfg.update_output_paths()
        out = run_pipeline(cfg)

        hg = out["hydrograph_df"]
        mb = pd.read_csv(out["mass_balance_csv"]).iloc[-1]
        rows.append({"n": n, "scheme": scheme,
                     "peak_m3s": hg.Q_m3s.max(),
                     "peak_hr": hg.time_hr[hg.Q_m3s.idxmax()],
                     "runoff_ratio": mb.runoff_ratio,
                     "balance_error": mb.rel_error})

table = pd.DataFrame(rows)
print(table.to_string(index=False))
table.to_csv("results/sweep/summary.csv", index=False)
```

- `Config.from_dict(base.to_dict())` makes an independent copy, so one run
  can't change the next.
- `run_pipeline` returns the paths of what it wrote and the hydrograph as a
  DataFrame (`hydrograph_df`).
- The setting names are the ones in the [user manual](../manual/all-settings.md),
  and choices can be given by name or code: `ROUTING_SCHEME = 4` is
  `diffusive_implicit`.

## Reuse the terrain

The terrain stage is the same for every run on one basin. Run it once and
copy its files into each run folder, then run routing only:

```python
import os
import shutil
from MRRpy import Config, run_pipeline

TERRAIN = ("clipped_dem.tif", "flow_direction.tif", "clipped_flow_accumulation.tif",
           "watershed.tif", "watershed.geojson")

base = Config.from_file("run.yaml")
base.OUTPUT_DIR = "results/terrain/"
run_pipeline(base, stages=("process_dem",))

for ksat in (5.0, 12.0, 25.0):
    cfg = Config.from_dict(base.to_dict())
    cfg.RUNOFF_SOURCE = "physical"
    cfg.RUNOFF_MECHANISMS = ["infiltration_excess"]
    cfg.GA_KSAT_MMHR = ksat
    cfg.OUTPUT_DIR = f"results/ksat_{ksat:g}/"
    cfg.update_output_paths()
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    for name in TERRAIN:
        shutil.copy(os.path.join(base.OUTPUT_DIR, name), cfg.OUTPUT_DIR)
    run_pipeline(cfg, stages=("routing",))
```

## Run several config files from the terminal

```bash
for f in configs/*.yaml; do
    MRRpy run -c "$f"
done
```

## Faster sweeps

- Use a 90 m grid: a run of the 606 km² example basin takes 20–80 seconds on
  one CPU.
- The explicit methods run on an NVIDIA GPU with `BACKEND: gpu`.
- Independent runs can go in parallel, for example with
  `concurrent.futures.ProcessPoolExecutor`, one run per process and each with its
  own folder.

## Other options to try

| Change | Setting | See |
|---|---|---|
| sweep the runoff method | `RUNOFF_SOURCE` | [Example 4](runoff-methods.md) |
| sweep channel size | `CHANNEL_QBF_M3S` | [Example 9](roughness-channels.md) |
| record extra points in every run | `ROUTING_GAUGES` | [6.1](../manual/outputs.md#61-virtual-gauges) |
