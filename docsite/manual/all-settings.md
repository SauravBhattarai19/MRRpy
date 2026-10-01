# All settings A–Z

Every setting of MRRpy, with a link to the table that explains it. The same list
is in your terminal: `MRRpy explain --all`.

<!-- settings-index -->

## Set automatically

These are also `Config` attributes, but MRRpy fills them in itself. You rarely
need to touch them.

| Setting | What it is |
|---|---|
| `ROUTING_DEM_PATH`, `ROUTING_FLOW_DIR_PATH`, `ROUTING_FLOW_ACCUM_PATH`, `ROUTING_WATERSHED_MASK_PATH`, `WATERSHED_GEOJSON` | the terrain files in the results folder, which routing reads |
| `HYDROGRAPH_CSV`, `MASS_BALANCE_CSV` | the output files in the results folder |
| `PRECIP_IMERG_DIR` | where downloaded IMERG rain is cached (`<results>/imerg/`) |
| `SERVES_TARGET_DATE` | old name, not used: `EVENT_START_UTC` sets the date |
| `MAX_DEPTH_M` | display only, not used by the model |

The path settings follow `OUTPUT_DIR`. In Python, call
`cfg.update_output_paths()` after changing `OUTPUT_DIR`; `run_pipeline`, the CLI
and the form do it for you.
