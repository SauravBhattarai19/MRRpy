# Build a configuration without typing it

MRRpy has about a hundred settings, but a typical run needs only a handful.
Three interactive tools build the configuration for you. They show only the
settings that matter for your choices, explain each one in plain language, check
your answers, and write the same `run.yaml` file that `MRRpy run` uses.

| You prefer… | Use | Needs |
|---|---|---|
| answering questions in a terminal (also over SSH) | `MRRpy wizard` | nothing extra |
| a form in Jupyter | `MRRpy.ConfigForm()` | `pip install "MRRpy[notebook]"` |
| editing a file yourself | `MRRpy init-config -o run.yaml` | nothing extra |
| Python code | `Config(...)` (the form writes it for you) | nothing extra |

All of them share one catalogue of settings (`MRRpy/config_schema.py`), so the
choices, explanations and checks are identical everywhere. You can switch
between them at any time: the wizard and the form both open an existing file.

## Terminal wizard

```bash
MRRpy wizard                     # new configuration
MRRpy wizard --edit run.yaml     # change an existing one
```

The wizard first asks what you want to simulate:

```text
What would you like to simulate?  This only pre-selects a few settings; you can
change everything afterwards.

     0  A design storm on my own DEM (works offline)  (current)
     1  A real storm with satellite rainfall (NASA IMERG, needs Earth Engine)
     2  A real storm with my rain-gauge records
     3  Route a known inflow hydrograph downstream (no rain)
     4  Start from the defaults and choose everything myself
Starting point [0 design_storm]:
```

Then it works through six short parts: basin, rain, runoff, channels, routing,
and outputs. Each question shows its current value in `[brackets]`, and
**Enter keeps it**, so you only answer what matters to you:

```text
  Constant rain rate of the design storm. Use 0 to route an inflow hydrograph only.
Rain intensity (mm/h) [20]: 50
```

- **Only relevant questions.** Gauge files are asked only for gauge rainfall,
  soil parameters only for the processes you picked, and so on. If a later
  answer makes an earlier question relevant (for example, satellite soil
  moisture needs the storm date), it is asked at the end.
- **Advanced settings are optional.** After each part, the wizard offers that
  part's advanced settings. Most people keep the defaults.
- **Type the number or the name** of a choice (`4`, `diffusive_implicit`, or
  just `diffusive_i`). The numbers are the same codes `MRRpy list-options`
  prints and a config file accepts.
- **Helpful defaults.** The map projection is suggested from your outlet (its
  UTM zone), and file names complete with the Tab key.
- **A review at the end** summarises the run in plain sentences, checks it, and
  offers to fix any problem by asking just those questions again.

| At any question, type | to |
|---|---|
| `?` | see the full explanation, choices, default and allowed range |
| `back` | return to the previous question |
| `done` | skip the remaining questions (they keep their values) |
| `quit` | stop without saving |

| Option | Effect |
|---|---|
| `-o run.yaml` | file name to offer when saving (`.yaml` or `.json`) |
| `--edit FILE` | start from an existing file |
| `--advanced` | ask the advanced questions too, without asking first |
| `--start KEY` | skip the first question (`design_storm`, `satellite_event`, `gauge_event`, `inflow_only`, `defaults`) |
| `--write-all` | save every setting, not only those that matter for your run |
| `--brief` | hide the explanation above each question |

The wizard uses plain text only: no colours, no cursor movement, no
box-drawing characters. It works in any terminal, over SSH, inside Jupyter, and
with screen readers. From Python, use `MRRpy.run_wizard()`.

## Jupyter form

```python
from MRRpy import ConfigForm

form = ConfigForm()              # or ConfigForm("run.yaml") to edit a file
form                             # shows the form
```

The form works step by step, laid out like the QGIS plugin, with **Next** and
**Back** buttons (or click a tab to jump):

| Step | What you choose |
|---|---|
| 1 Terrain | *I have a DEM file* → its path, **or** *Download a DEM* → area (typed or drawn on the map), dataset, resolution; then the basin outlet and the results folder |
| 2 Coordinate system | the projection in metres (one click uses your outlet's UTM zone) |
| 3 Precipitation | *Design storm*, *Rain gauges* or *Satellite (IMERG)* first; only then Thiessen or IDW, and the files or storm date that source needs |
| 4 Runoff | the runoff method; for *physical*, each ticked process opens its own settings |
| 5 Routing | the routing method (its settings open underneath), simulation time, ground roughness, river channels, inflows |
| 6 Outputs and run | gauges, maps, CPU/GPU, then check, save and run |

**Every choice opens its own branch directly underneath it, and only while
it is selected.** Choosing *Satellite (IMERG)* reveals the Thiessen/IDW choice and
the storm start. Choosing *diffusive_implicit* reveals the implicit-solver
settings. Ticking *infiltration excess* reveals the Green-Ampt settings under
that tick box. Rarely changed settings of a branch stay folded in a *More
options* section inside it. When a choice needs Google Earth Engine, a box for
your Earth Engine project appears in that step.

The tree is derived from the conditions in the parameter catalogue, so a
new setting appears in the right branch automatically.

Step 6 has a live summary and these buttons:

- **Check settings** lists everything that would stop a run, in words.
- **Save** writes the YAML file (tick *Write every setting* for a full reference file).
- **Show YAML** / **Show Python code** show the same configuration as a file or as code.
- **Run the model** runs it in the notebook. The line beside the button says
  *Status: Running — 45 % done*, then *Status: Finished at 11:04:07 — took 23 s*
  (or *Stopped with an error*). Everything the model prints scrolls in the log
  and is saved as `mrrpy_run.log` in the results folder. A **Results** panel then
  shows the peak flow, the water-balance check, the files written and a hydrograph
  plot. In code, `form.run_state` and `form.results` give the same answer.
- **Show results and plot the hydrograph** reads the results folder at any
  time, so it works for any run (even one started with `MRRpy run`) and in
  editors that miss live updates. A form opened on a folder that already
  holds a finished run shows those results straight away.

With `ipyleaflet` installed (part of the `notebook` extra), *Pick the outlet or
download area on a map* (step 1) lets you click the outlet and draw the DEM
download box. Typing coordinates works just as well.

The form is also an ordinary Python object:

```python
cfg = form.config                # a Config, ready for run_pipeline(cfg)
form.problems()                  # [] when the configuration is ready to run
print(form.summary())            # what the run will do, in sentences
form.set_values(ROUTING_SCHEME="diffusive_implicit", TOTAL_SIMULATION_TIME_HOURS=48)
form.go("routing")              # jump to a step
form.save("run.yaml")
```

**Accessibility.** Every input has a real label, and every explanation is
visible text under its setting rather than a hover tooltip (a checkbox turns
them off). Problems start with the word *Problem:* and are announced to screen
readers, so they never rely on colour alone. Long labels wrap instead of being
cut off. Everything works from the keyboard: Tab moves between fields, Space
toggles a box, and the arrow keys pick a radio option.

A worked example is in `notebooks/configure_and_run.ipynb`.

## Google Earth Engine sign-in

Only the Earth Engine options need it: DEM download, IMERG rain, the GCN250,
SERVES, SoilGrids and HiHydroSoil maps, and land-cover roughness. When you pick
one, the form shows an *Earth Engine* box in that step, with your project ID and
a **Connect to Earth Engine** button. The button checks that the sign-in and the
project work, and says in plain words what is wrong if not.

A button can't ask for a sign-in code, so sign in **once per computer** first:

```python
import MRRpy
MRRpy.connect_earth_engine("ee-yourname")   # prints a link; sign in, paste the code back
```

or `MRRpy earth-engine-login --project ee-yourname` in a terminal. Both work
over SSH and the sign-in is saved. Drawing on the maps never needs Earth Engine.

## A commented template

```bash
MRRpy init-config -o run.yaml            # every setting, each with its explanation
MRRpy init-config --short -o run.yaml    # only the main settings
```

Settings are grouped into the same six parts. Each entry lists its choices,
what an empty value (`null`) means, and the conditions under which it applies:

```yaml
# Rain intensity (mm/h) — Constant rain rate of the design storm. Use 0 to
# route an inflow hydrograph only.
#   Not used with your current choices (applies when PRECIP_METHOD is 'uniform').
RAIN_INTENSITY_MM_HR: 20.0
```

## Explain any setting

```bash
MRRpy explain ROUTING_SCHEME     # one setting: meaning, choices, default, when it applies
MRRpy explain manning            # search: every setting that mentions Manning
MRRpy explain --all              # every setting, grouped by part
```

```python
import MRRpy
print(MRRpy.explain("CHANNEL_QBF_M3S"))
```

## For developers: adding a setting

When you add a knob to `Config`, also add a `P(...)` entry to
`MRRpy/config_schema.py`. Give it a short label, one to three plain sentences
of help, its kind (number, file, choice, …), and `when=` conditions if it only
matters for some choices. The wizard, the form, the template and `explain` then
pick it up automatically.

`tests/test_config_schema.py` fails for any `Config` attribute that is missing
from the catalogue. Other tests check that every setting can be answered in the
wizard, set in the form, and written to YAML and read back unchanged.
