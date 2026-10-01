# For developers

## Add a setting

1. Add the attribute to `Config` in `MRRpy/config.py`, with its default. A
   setting with a fixed list of choices goes into `_ENUM_CHOICES` too; append new
   choices at the end, because the list position is the choice's code.
2. Add a `P(...)` entry to the catalogue in `MRRpy/config_schema.py`: a short
   label, one to three plain sentences of help, its kind (number, file, choice, …),
   unit, range, an `example=`, and `when=` conditions if it matters only for some
   choices.
3. Put its name in a settings table in the [user manual](../manual/index.md):
   a line `<!-- settings: NAME -->` in the right chapter (or add it to an
   existing one). Explain the physics in the text around it.

The wizard, the notebook form, `MRRpy init-config`, `MRRpy explain` and the
manual's tables then pick it up automatically. Tests check each step:
`tests/test_config_schema.py` fails for a `Config` attribute missing from the
catalogue, and `tests/test_docs.py` fails for a catalogued setting missing from
the manual. Other tests check that every setting can be answered in the wizard,
set in the form, and written to YAML and read back unchanged.

For the QGIS plugin, add a widget to the matching `MRRpy_plugin/ui/tab_*.py`
(`apply_config` and `write_to_config`), then rebuild the plugin with
`./build_windows_plugin.sh`.

## The documentation

The site is built with MkDocs and Material from `docsite/` (`mkdocs.yml`):

```bash
pip install -r docs-requirements.txt
mkdocs serve          # preview at http://127.0.0.1:8000
mkdocs build --strict # what Read the Docs builds; warnings are errors
```

`tools/mkdocs_hooks.py` expands three pieces of syntax:

| In a page | Becomes |
|---|---|
| `<!-- settings: NAME NAME … -->` on its own line | a table of those settings: value, default, description, choices and codes, when it applies |
| `<!-- settings-index -->` | the A–Z list of every setting |
| `[[NAME]]` | a link to the setting's row in its table |

Each setting must be in exactly one table. The tables are generated from
`config_schema.py`, so improve the wording there, not in the page.

## Add a runoff method

Runoff methods are plug-ins: each `RUNOFF_SOURCE` is a small `RunoffMode` class
registered by name. You can register one from your own package, without editing
MRRpy:

```python
from MRRpy.core.runoff import RunoffMode, register, RUNOFF_MODES

@register("my_method")                      # the RUNOFF_SOURCE name
class MyMethod(RunoffMode):
    def __init__(self, cfg, grid_data):
        super().__init__(cfg, grid_data)    # stores grid handles and self._xp
        # read your own settings or rasters here

    def get_effective_1d(self, t_seconds, rain_1d):
        return rain_1d * 0.6                 # runoff [m/s] for each cell, shape (n_cells,)

    def update_state(self, rain_1d, dt):
        ...                                  # advance your state by one step (optional)

    def is_active(self, t_seconds):
        return True                          # optional
```

Then `Config(RUNOFF_SOURCE="my_method")`. Each step the time loop calls
`get_effective_1d(t, rain)` (with the current state), then
`update_state(rain, dt)` (forward Euler). `self._xp` is NumPy or CuPy, so the
same class runs on the CPU and the GPU. `RUNOFF_MODES` maps every registered
name to its class.

A new physical *process* for `RUNOFF_SOURCE: physical` registers one level down,
with `@register_mechanism` in `MRRpy/core/runoff/mechanisms.py`.

## Tests

```bash
pytest tests/                                        # unit and integration tests
python tests/03_test_vsa_opm.py                      # the numbered scripts are standalone demos
pytest MRRpy_plugin/tests/test_config_bridge.py -v   # plugin, no QGIS needed
```
