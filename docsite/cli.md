# Command-line interface

Installing MRRpy provides the `MRRpy` command. It is config-file driven,
so a run is fully reproducible from a single `.yaml` / `.json` / `.py` file.

```bash
MRRpy --help
```

## Commands

### `init-config` — write a template

```bash
MRRpy init-config -o my_run.yaml
```

Writes every parameter at its default, ready to edit. At minimum set
`DEM_PATH`, `OUTPUT_POINT`, `TARGET_CRS_EPSG`, and `OUTPUT_DIR`.

### `validate` — pre-flight checks

```bash
MRRpy validate -c my_run.yaml
```

Loads the config and runs sanity checks (DEM exists, GEE project present when
needed, valid option values, …) **without** starting a simulation.

### `run` — run the pipeline

```bash
MRRpy run -c my_run.yaml
MRRpy run -c my_run.yaml --stages process_dem routing
MRRpy run -c my_run.yaml --backend gpu --output-dir results/
```

| Flag | Purpose |
|---|---|
| `--stages` | subset/order of `process_dem`, `routing`, `vsa_opm` |
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
[Configuration → No local DEM?](configuration.md#no-local-dem-auto-download-from-earth-engine).

## Typical session

```bash
MRRpy init-config -o run.yaml
$EDITOR run.yaml            # set DEM_PATH, OUTPUT_POINT, TARGET_CRS_EPSG, OUTPUT_DIR
MRRpy validate -c run.yaml
MRRpy run -c run.yaml
```
