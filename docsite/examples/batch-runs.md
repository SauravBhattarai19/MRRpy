# 11 Many runs from Python

**Goal:** run many configurations in a loop, for a sensitivity study, a
calibration or a comparison, and collect the results in one table.

Because every setting is a value on one `Config`, any comparison is a loop that
changes values. Each run goes into its own results folder.

## Many runs in one call

`run_many` takes a base configuration and what each run changes, and returns one
table. The terrain is processed once and shared, a satellite or weather-model
rain download is shared, and the runs can go side by side:

```python
from MRRpy import Config, run_many

base = Config.from_file("run.yaml")          # e.g. the file of Example 1

table = run_many(base, {
    "smooth_kinematic": {"MANNINGS_N": 0.05},
    "rough_kinematic":  {"MANNINGS_N": 0.15},
    "smooth_implicit":  {"MANNINGS_N": 0.05, "ROUTING_SCHEME": "diffusive_implicit"},
    "rough_implicit":   {"MANNINGS_N": 0.15, "ROUTING_SCHEME": "diffusive_implicit"},
}, output_dir="results/sweep", workers=2)

print(table[["name", "status", "peak_m3s", "peak_time_hr", "runoff_ratio"]])
```

- Each run writes to its own folder, `results/sweep/<name>/`, complete with the
  terrain files, its `run.log` and its record. The table is also saved as
  `results/sweep/summary.csv`.
- The table has one row per run: its name, whether it finished, the settings it
  changed, the peak and its time, the volume, the runoff ratio, the
  water-balance error and the time it took. A run that fails does not stop the
  others; its row says why in the `error` column.
- `workers=2` runs two at a time, each in its own process, with the computer's
  threads shared out between them. Leave it at 1 with a GPU.
- A list works as well as a dict; the runs are then named `run_01`, `run_02`, …:

```python
from MRRpy import Config, run_many

base = Config.from_file("run.yaml")
runs = [{"GA_KSAT_MMHR": k, "RUNOFF_SOURCE": "physical",
         "RUNOFF_MECHANISMS": ["infiltration_excess"]} for k in (5.0, 12.0, 25.0)]
table = run_many(base, runs, output_dir="results/ksat")
```

Runs that change the terrain itself (another outlet, another DEM, another
delineation engine) each get their own terrain; runs that agree on it share one.

## A loop of your own

When each run needs something `run_many` does not do, write the loop yourself.

```python
import pandas as pd
from MRRpy import Config, run_pipeline

base = Config.from_file("run.yaml")          # e.g. the file of Example 1

rows = []
for n in (0.05, 0.09, 0.15):                 # ground roughness
    for scheme in ("kinematic", "diffusive_implicit"):
        cfg = base.copy(MANNINGS_N=n, ROUTING_SCHEME=scheme,
                        OUTPUT_DIR=f"results/sweep/n{n}_{scheme}/")
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

- `base.copy(...)` makes an independent copy with those settings changed, so
  one run can't change the next. The output files follow `OUTPUT_DIR` by
  themselves.
- `run_pipeline` returns the paths of what it wrote and the hydrograph as a
  DataFrame (`hydrograph_df`).
- The setting names are the ones in the [user manual](../manual/all-settings.md),
  and choices can be given by name or code: `ROUTING_SCHEME = 4` is
  `diffusive_implicit`.


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
