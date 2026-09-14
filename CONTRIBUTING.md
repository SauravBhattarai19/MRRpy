# Contributing to hydroflow

Thanks for your interest in improving **hydroflow** — a distributed,
physics-based rainfall–runoff and flood-routing model. Contributions of all
kinds are welcome: bug reports, documentation fixes, new examples, and code.

## Getting help / seeking support

- **Questions and usage help:** open a
  [GitHub Discussion](https://github.com/SauravBhattarai19/hydroflow/discussions)
  or a [GitHub Issue](https://github.com/SauravBhattarai19/hydroflow/issues)
  with the `question` label.
- **Documentation:** <https://pyhydroflow.readthedocs.io>.

## Reporting a bug or problem

Please open an [issue](https://github.com/SauravBhattarai19/hydroflow/issues)
and include, where possible:

1. What you did (the `Config` settings, CLI command, or a minimal code snippet).
2. What you expected to happen and what actually happened (full traceback).
3. Your environment: OS, Python version, `hydroflow` version
   (`python -c "import hydroflow; print(hydroflow.__version__)"`), and whether
   you use the `[gpu]` or `[gee]` extras.
4. A minimal, reproducible example if you can — a small synthetic DEM is often
   enough (see `tests/test_core_science.py` for how to build one in-memory).

## Requesting a feature

Open an issue describing the hydrologic or software use case, why existing
options do not cover it, and (if you have one) a sketch of the interface you
would expect on the `Config` object.

## Contributing code

1. **Fork** the repository and create a topic branch off `main`.
2. **Set up a dev environment:**
   ```bash
   git clone https://github.com/<you>/hydroflow
   cd hydroflow
   pip install -e ".[gee]"   # add [gpu] only if you have CUDA 12.x
   pip install pytest
   ```
3. **Make your change.** Please keep the scientific core
   (`hydroflow/core/`) free of QGIS/Qt and of hard Earth Engine dependencies —
   all Earth Engine code is optional and lazily imported, and every GEE-backed
   option must retain an offline fallback. New configuration knobs go on
   `hydroflow/config.py::Config` first (see the `_ENUM_CHOICES` / `_ENUM_LIST`
   registries for fixed-choice options).
4. **Add or update tests** for your change (see below) and make sure the whole
   suite passes.
5. **Update the docs** in `docsite/` if you changed user-facing behaviour.
6. **Open a pull request** against `main` with a clear description of the change
   and the motivation. Small, focused PRs are easiest to review.

## Running the tests

The primary automated suite is run with `pytest` from the repository root:

```bash
pytest
```

This runs the config-bridge tests (`qgis_plugin/tests/test_config_bridge.py`),
the data-free scientific-core and end-to-end tests
(`tests/test_core_science.py`), and an integration test
(`qgis_plugin/tests/test_runner.py`, which is skipped automatically unless the
`output/` rasters are present). The same suite runs in CI on every push and
pull request.

The numbered scripts in `tests/` (`tests/NN_*.py`) are standalone
verification/demo programs (not collected by `pytest`); run them individually,
e.g. `python tests/10_test_runoff_mechanisms.py`.

## Code of conduct

Please be respectful and constructive in all project spaces. By participating,
you agree to uphold a welcoming, harassment-free environment for everyone.

## License

By contributing, you agree that your contributions will be licensed under the
project's [MIT License](LICENSE).
