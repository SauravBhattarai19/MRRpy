# API reference

The public API is small: build a [`Config`](#config), then call
[`run_pipeline`](#run_pipeline). Both are importable from the top level:

```python
from MRRpy import Config, run_pipeline, OpmConfig, DEFAULT_STAGES
```

## `run_pipeline`

::: MRRpy.run_pipeline
    options:
      heading_level: 3

## `list_available_dems` / `describe_available_dems`

Browse the DEM datasets MRRpy can auto-download from Google Earth Engine
(see [1.1 Elevation data](../manual/terrain.md#11-elevation-data-dem)).
No `[gee]` install required just to list them.

::: MRRpy.list_available_dems
    options:
      heading_level: 3

::: MRRpy.describe_available_dems
    options:
      heading_level: 3

## Plotting

Small helpers to visualize a run's outputs — each accepts a path, a
DataFrame, a `run_pipeline()` result dict, or a `Config`, and returns
`(fig, ax)`. See the [examples](../examples/index.md) for them in context.

::: MRRpy.plot_watershed
    options:
      heading_level: 3

::: MRRpy.plot_hydrograph
    options:
      heading_level: 3

::: MRRpy.plot_raster
    options:
      heading_level: 3

::: MRRpy.plot_mass_balance
    options:
      heading_level: 3

### Maps over time (`SAVE_FIELDS=True`)

These read the per-cell maps a run saves with `SAVE_FIELDS=True` — see
[Example 10](../examples/whole-dem.md).

::: MRRpy.plot_field
    options:
      heading_level: 3

::: MRRpy.animate_fields
    options:
      heading_level: 3

::: MRRpy.export_peak_maps
    options:
      heading_level: 3

## `mannings_n_from_dem`

Generate a spatially-varying Manning's-n raster from a DEM using an elevation
rule — see [Example 9](../examples/roughness-channels.md).

::: MRRpy.mannings_n_from_dem
    options:
      heading_level: 3

## `apply_elevation_rule`

The elevation-rule dispatch shared by `mannings_n_from_dem` and by
`MANNINGS_N_CHANNEL` (channel-only elevation rules, no raster needed) — see
[5.4.2 Roughness of river channels](../manual/roughness.md#542-roughness-of-river-channels).

::: MRRpy.apply_elevation_rule
    options:
      heading_level: 3

## Pluggable runoff modes

`MRRpy.core.runoff.register` adds a new `RUNOFF_SOURCE` from your own code; see
[For developers](developers.md#add-a-runoff-method).

## `Config`

The single configuration object for a run. `OpmConfig` is an alias of this
class. Every setting is explained in the [user manual](../manual/index.md)
([A–Z list](../manual/all-settings.md)).

::: MRRpy.Config
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
