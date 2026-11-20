# 14 Compare a run with a flow record

**Goal:** set a run next to a flow record, in one figure and a few scores:
your own gauge file, a USGS stream gauge, or the GloFAS reference flow that
exists everywhere.

**You need:** a run with a start date, so that its hydrograph has clock times.

**Settings used:** [[EVENT_START_UTC]], [[TOTAL_SIMULATION_TIME_HOURS]],
[[PRECIP_METHOD]].

## The run needs clock times

A flow record is in clock time; a design storm is not. Give the run a start
date and `hydrograph.csv` gets a last column `time_utc`:

```yaml
EVENT_START_UTC: "2024-09-27 00:00"
TOTAL_SIMULATION_TIME_HOURS: 72
```

Runs with satellite or weather-model rain already have one.

## Three kinds of record

Every reader returns the same table, with the columns `time_utc` and `Q_m3s`.

=== "Your own file"

    Any CSV with a time column and a flow column. They are found by name
    (`time`, `datetime`, `date`; `Q_m3s`, `flow`, `discharge`, `Q`), or you
    name them. Give the unit if it is not m³/s, and the clock's offset from UTC
    if the file is in local time:

    ```python
    from MRRpy import observed

    obs = observed.read_flow_csv("khokana_2024.csv", utc_offset_hours=5.75)   # Nepal time
    obs = observed.read_flow_csv("gauge.csv", time_column="Date", flow_column="cfs",
                                 unit="ft3/s")
    ```

=== "A USGS stream gauge"

    Needs `pip install "MRRpy[usgs]"`. Readings are usually every 15 minutes.

    ```python
    from MRRpy import observed

    obs = observed.usgs_flow("04286000", "2023-07-09", "2023-07-13")   # Winooski at Montpelier
    ```

=== "GloFAS, anywhere"

    Modelled daily river flow from the Global Flood Awareness System, through
    Open-Meteo: no account, from 1984 to about seven months ahead.

    ```python
    from MRRpy import observed

    ref = observed.glofas_flow(27.632, 85.293, "2024-09-25", "2024-10-01")
    print(ref.attrs["cell"])       # the model cell that was served
    ```

!!! warning "GloFAS is a reference, not a measurement"
    It is another model's result on a grid of about 5 km, as one value per day.
    On a river that drains thousands of km² it is a fair second opinion. On a
    small basin its cell may not even be on your river, and a daily mean sits
    far below a flash flood's peak: at the Khokana outlet (606 km²) it gives
    58 m³/s for 28 September 2024, a day on which the Bagmati peaked many times
    higher. If the cell served is not on your river, move the point by
    0.05–0.1°.

## One figure, a few scores

```python
from MRRpy import Config, run_pipeline, plot_hydrograph, observed

cfg = Config.from_file("run.yaml")
out = run_pipeline(cfg)

obs = observed.read_flow_csv("gauge.csv")
plot_hydrograph(out, observed=obs)             # add reference=ref for the GloFAS line

scores = observed.skill(out, obs)
for name, value in scores.items():
    print(f"{name:20s} {value:.3g}")
```

The figure draws the model as a line, the record as dark dots and a reference
as a grey stepped line. `skill` reads the model at the record's times, over the
hours both cover:

| Score | Meaning |
|---|---|
| `nse` | Nash–Sutcliffe efficiency: 1 is perfect, 0 is no better than the record's mean |
| `kge` | Kling–Gupta efficiency: 1 is perfect |
| `bias_percent` | modelled volume against the record |
| `peak_obs_m3s`, `peak_sim_m3s`, `peak_error_percent` | the two peaks and their difference |
| `peak_timing_hours` | modelled peak minus recorded peak; positive means late |
| `n` | how many values were compared |

One flood is a small sample. A model that fits one event may miss the next, so
compare several before you trust a setting.

## The 2-year flood where there is no gauge

The river channel is sized from the 2-year flood
([5.5 River channels](../manual/channels.md)). Where no gauge exists, the GloFAS
record gives a second estimate to set beside MRRpy's own:

```python
from MRRpy import observed

q2 = observed.glofas_two_year_flood(27.632, 85.293)
print(q2["q2_m3s"], "m³/s from", q2["years"], "years")
```

It is the median of the yearly peaks of the daily record, so it is low for
small, fast rivers. MRRpy does not use it by itself: if you decide it suits your
river, pass the number to `CHANNEL_QBF_M3S`.

## Other options to try

- Compare at a virtual gauge instead of the outlet: `gauges.csv` has the same
  `time_utc` column ([6.1 Virtual gauges](../manual/outputs.md#61-virtual-gauges)).
- Score every run of a batch: loop over the folders `run_many` made
  ([Example 11](batch-runs.md)) and call `observed.skill(folder, obs)`.
