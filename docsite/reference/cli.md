# Command-line interface

Installing MRRpy provides the `MRRpy` command. It is config-file driven,
so a run is fully reproducible from a single `.yaml` / `.json` / `.py` file.

```bash
MRRpy --help
```

## Commands

### `wizard` — build a config by answering questions

```bash
MRRpy wizard                    # new config; asks where to save (run.yaml)
MRRpy wizard --edit run.yaml    # change an existing config
```

Asks only the questions that matter for your earlier answers, explains each
one, shows the current value in `[brackets]` (Enter keeps it), checks the result
and saves it. Type `?` for help, `back`, `done` or `quit` at any question.
Options: `-o FILE`, `--advanced` (ask advanced questions too), `--start KEY`,
`--write-all`, `--brief`. See [Ways to set up a run](../getting-started/interfaces.md).

### `init-config` — write a commented template

```bash
MRRpy init-config -o my_run.yaml           # every setting, each explained
MRRpy init-config --short -o my_run.yaml   # only the main settings
MRRpy init-config -i -o my_run.yaml        # = MRRpy wizard
```

Writes every parameter at its default, grouped by topic, each with a
plain-language explanation, its choices and when it applies. At minimum set
`DEM_PATH`, `OUTPUT_POINT`, `TARGET_CRS_EPSG`, and `OUTPUT_DIR`.

### `explain` — what does a setting do?

```bash
MRRpy explain ROUTING_SCHEME    # meaning, choices, default, when it applies
MRRpy explain rain              # search the settings
MRRpy explain --all             # list every setting
```

### `earth-engine-login` — sign in to Google Earth Engine

```bash
MRRpy earth-engine-login --project ee-yourname          # sign in once, then check
MRRpy earth-engine-login --project ee-yourname --check  # only check, never prompt
```

Needed only for Earth Engine options (DEM download, IMERG rain, curve-number,
soil and land-cover maps). If this computer has never signed in, it prints a
link: open it, sign in with your Google account, and paste the code back. That
also works over SSH. The sign-in is saved. Then one small request confirms that
the project works. Problems such as "not signed in" or "project not registered"
are explained in plain words. `--force` signs in again (e.g. with another
account). In Python: `MRRpy.connect_earth_engine("ee-yourname")`.

### `validate` — pre-flight checks

```bash
MRRpy validate -c my_run.yaml
```

Loads the config and runs sanity checks (DEM exists, GEE project present when
needed, valid option values, …) **without** starting a simulation. When the
checks pass, it prints a plain-language summary of what the run will do.

### `run` — run the pipeline

```bash
MRRpy run -c my_run.yaml
MRRpy run -c my_run.yaml --stages process_dem routing
MRRpy run -c my_run.yaml --backend gpu --output-dir results/
```

| Flag | Purpose |
|---|---|
| `--stages` | subset/order of `process_dem`, `routing`, `inundation`, `vsa_opm` (`inundation` redraws the flood maps of a routed run) |
| `--backend` | override `BACKEND` (`cpu`/`gpu`) |
| `--output-dir` | override `OUTPUT_DIR` |

### `list-options` — discover option codes

```bash
MRRpy list-options
```

Prints every fixed-choice option with its integer codes, e.g.
`PRECIP_METHOD : 0=uniform  1=thiessen  …`. Handy because config values accept
either the string or the code.

### `list-dems` — discover DEM sources

```bash
MRRpy list-dems
```

Prints every DEM dataset MRRpy can auto-download from Google Earth
Engine (dataset id, native resolution, coverage) — set `DEM_SOURCE` to one
of these keys and `DEM_BOUNDS_WGS84` to skip needing a local `DEM_PATH`. See
[1.1 Elevation data](../manual/terrain.md#11-elevation-data-dem).

## Typical session

```bash
MRRpy wizard -o run.yaml    # answer the questions (or: init-config + edit the file)
MRRpy validate -c run.yaml
MRRpy run -c run.yaml
```
