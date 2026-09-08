# API reference

The public API is small: build a [`Config`](#config), then call
[`run_pipeline`](#run_pipeline). Both are importable from the top level:

```python
from hydroflow import Config, run_pipeline, OpmConfig, DEFAULT_STAGES
```

## `run_pipeline`

::: hydroflow.run_pipeline
    options:
      heading_level: 3

## `list_available_dems` / `describe_available_dems`

Browse the DEM datasets hydroflow can auto-download from Google Earth Engine
(see [Configuration → No local DEM?](configuration.md#no-local-dem-auto-download-from-earth-engine)).
No `[gee]` install required just to list them.

::: hydroflow.list_available_dems
    options:
      heading_level: 3

::: hydroflow.describe_available_dems
    options:
      heading_level: 3

## Plotting

Small helpers to visualize a run's outputs — each accepts a path, a
DataFrame, a `run_pipeline()` result dict, or a `Config`, and returns
`(fig, ax)`. See [Examples](examples.md) for them in context.

::: hydroflow.plot_watershed
    options:
      heading_level: 3

::: hydroflow.plot_hydrograph
    options:
      heading_level: 3

::: hydroflow.plot_raster
    options:
      heading_level: 3

::: hydroflow.plot_mass_balance
    options:
      heading_level: 3

## `mannings_n_from_dem`

Generate a spatially-varying Manning's-n raster from a DEM using an elevation
rule — see [Configuration → Elevation-based Manning's n](configuration.md#elevation-based-mannings-n).

::: hydroflow.mannings_n_from_dem
    options:
      heading_level: 3

## `apply_elevation_rule`

The elevation-rule dispatch shared by `mannings_n_from_dem` and by
`MANNINGS_N_CHANNEL` (channel-only elevation rules, no raster needed) — see
[Configuration → Elevation-based Manning's n](configuration.md#elevation-based-mannings-n).

::: hydroflow.apply_elevation_rule
    options:
      heading_level: 3

## Pluggable runoff modes

Runoff generation is pluggable: each `RUNOFF_SOURCE` is a small `RunoffMode`
subclass registered by name. Register your own — even from another package — to
add a method without editing hydroflow:

```python
from hydroflow.core.runoff import RunoffMode, register, RUNOFF_MODES

@register("my_method")                      # name used by RUNOFF_SOURCE
class MyMethod(RunoffMode):
    def __init__(self, cfg, grid_data):
        super().__init__(cfg, grid_data)    # stores grid handles + self._xp
        # read your own config knobs / rasters here

    def get_effective_1d(self, t_seconds, rain_1d):
        return rain_1d * 0.6                 # effective runoff [m/s], (n_cells,)

    def update_state(self, rain_1d, dt):
        ...                                  # advance state (forward Euler); optional

    def is_active(self, t_seconds):
        return True                          # optional
```

The forward-Euler contract the time loop uses is
`get_effective_1d(t, rain)` (current state) → `update_state(rain, dt)`
(advance). `self._xp` is numpy or cupy, so the same class runs on CPU and GPU.
`RUNOFF_MODES` maps every registered name to its class.

### SCS Curve Number knobs

When `RUNOFF_SOURCE="scs_cn"`: `RUNOFF_CN_SOURCE` (`scalar`/`gee`/`raster`)
chooses where curve numbers come from, `RUNOFF_CN_AMC` (`i`/`ii`/`iii`) sets the
antecedent moisture condition, `RUNOFF_CN` is the scalar CN, `RUNOFF_CN_PATH` a
CN GeoTIFF, and `RUNOFF_SCS_Ia_FACTOR` the initial-abstraction factor (0.2). The
`gee` source pulls the GCN250 global curve-number dataset via
`hydroflow.gee.cn_gee.download_cn_raster`.

## `Config`

The single configuration object for a run. `OpmConfig` is an alias of this
class. See [Configuration](configuration.md) for the parameter groups and the
string/integer option codes.

::: hydroflow.Config
    options:
      heading_level: 3
      members:
        - from_file
        - from_dict
        - save
        - validate
        - update_output_paths
        - describe_options
        - to_dict
