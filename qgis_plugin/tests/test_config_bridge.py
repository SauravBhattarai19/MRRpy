# -*- coding: utf-8 -*-
"""
tests/test_config_bridge.py
===========================
Unit tests for OpmConfig (bridge/config_bridge.py).

These tests run with plain pytest — no QGIS installation required.
They verify that OpmConfig correctly mirrors every attribute in config.py
and that validation catches common errors.
"""

import os
import sys
import pytest

# ── Add OPM root to path ──────────────────────────────────────────────────────
_OPM_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _OPM_ROOT not in sys.path:
    sys.path.insert(0, _OPM_ROOT)

from qgis_plugin.bridge.config_bridge import OpmConfig  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
class TestOpmConfigDefaults:
    """OpmConfig default values match config.py shipped defaults."""

    def test_backend_default(self):
        cfg = OpmConfig()
        assert cfg.BACKEND == "cpu"

    def test_mannings_n_default(self):
        cfg = OpmConfig()
        assert pytest.approx(cfg.MANNINGS_N, abs=1e-6) == 0.09

    def test_vsa_phi_default(self):
        cfg = OpmConfig()
        assert pytest.approx(cfg.VSA_PHI, abs=1e-6) == 0.35

    def test_vsa_k_sat_default(self):
        cfg = OpmConfig()
        assert pytest.approx(cfg.VSA_K_SAT, abs=1e-6) == 44.0

    def test_precip_method_default(self):
        cfg = OpmConfig()
        assert cfg.PRECIP_METHOD == "uniform"

    def test_runoff_source_default(self):
        cfg = OpmConfig()
        assert cfg.RUNOFF_SOURCE == "none"

    def test_time_step_default(self):
        cfg = OpmConfig()
        assert cfg.TIME_STEP_SECONDS == 2   # matches config.py


# ─────────────────────────────────────────────────────────────────────────────
class TestOpmConfigMirrorsConfigPy:
    """OpmConfig must mirror every public UPPERCASE attribute in config.py."""

    def test_no_config_attribute_missing(self):
        import importlib.util
        cfg_path = os.path.join(_OPM_ROOT, "config.py")
        spec = importlib.util.spec_from_file_location("_real_config", cfg_path)
        real = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(real)

        real_attrs = {
            k for k in dir(real)
            if not k.startswith("_") and k.upper() == k and not callable(getattr(real, k))
        }
        mirror = set(OpmConfig().to_dict().keys())
        missing = real_attrs - mirror
        assert not missing, f"OpmConfig is missing config.py attributes: {sorted(missing)}"


# ─────────────────────────────────────────────────────────────────────────────
class TestOpmConfigKwargs:
    """Keyword argument overrides work correctly."""

    def test_single_override(self):
        cfg = OpmConfig(MANNINGS_N=0.05)
        assert pytest.approx(cfg.MANNINGS_N) == 0.05

    def test_multiple_overrides(self):
        cfg = OpmConfig(BACKEND="gpu", GPU_PRECISION="float32")
        assert cfg.BACKEND == "gpu"
        assert cfg.GPU_PRECISION == "float32"

    def test_invalid_attribute_raises(self):
        with pytest.raises(AttributeError, match="has no attribute"):
            OpmConfig(INVALID_PARAM=42)


# ─────────────────────────────────────────────────────────────────────────────
class TestOpmConfigUpdateOutputPaths:
    """update_output_paths() sets derived ROUTING_* paths correctly."""

    def test_output_paths_updated(self):
        cfg = OpmConfig()
        cfg.OUTPUT_DIR = "/data/sim_run_01"
        cfg.update_output_paths()
        assert cfg.ROUTING_DEM_PATH == "/data/sim_run_01/clipped_dem.tif"
        assert cfg.ROUTING_FLOW_DIR_PATH == "/data/sim_run_01/flow_direction.tif"
        assert cfg.ROUTING_FLOW_ACCUM_PATH == "/data/sim_run_01/clipped_flow_accumulation.tif"
        assert cfg.ROUTING_WATERSHED_MASK_PATH == "/data/sim_run_01/watershed.tif"
        assert cfg.HYDROGRAPH_CSV == "/data/sim_run_01/hydrograph.csv"


# ─────────────────────────────────────────────────────────────────────────────
class TestOpmConfigValidation:
    """validate() catches configuration errors."""

    def test_missing_dem_raises(self):
        cfg = OpmConfig(DEM_PATH="/nonexistent/dem.tif")
        with pytest.raises(ValueError, match="DEM_PATH"):
            cfg.validate()

    def test_zero_time_step_raises(self):
        cfg = OpmConfig(TIME_STEP_SECONDS=0, DEM_PATH=__file__)
        with pytest.raises(ValueError, match="TIME_STEP_SECONDS"):
            cfg.validate()

    def test_invalid_backend_raises(self):
        # Fixed-choice options are normalised (and rejected) at assignment,
        # so an invalid BACKEND raises at construction, not in validate().
        with pytest.raises(ValueError, match="BACKEND"):
            OpmConfig(BACKEND="tpu", DEM_PATH=__file__)

    def test_vsa_q_max_too_small_raises(self):
        cfg = OpmConfig(
            RUNOFF_SOURCE="physical",
            RUNOFF_MECHANISMS=["saturation_excess"],
            VSA_Q_MAX=0.0005,
            DEM_PATH=__file__,
        )
        with pytest.raises(ValueError, match="VSA_Q_MAX"):
            cfg.validate()

    def test_valid_config_passes(self, tmp_path):
        """A fully valid config should not raise."""
        dem = tmp_path / "dem.tif"
        dem.touch()
        cfg = OpmConfig(
            DEM_PATH=str(dem),
            BACKEND="cpu",
            TIME_STEP_SECONDS=5,
            TOTAL_SIMULATION_TIME_HOURS=24.0,
            MANNINGS_N=0.09,
            RUNOFF_SOURCE="none",
        )
        cfg.validate()   # must not raise


# ─────────────────────────────────────────────────────────────────────────────
class TestOpmConfigToDict:
    """to_dict() returns all public non-callable attributes."""

    def test_to_dict_has_backend(self):
        d = OpmConfig().to_dict()
        assert "BACKEND" in d

    def test_to_dict_has_no_private_keys(self):
        d = OpmConfig().to_dict()
        for k in d:
            assert not k.startswith("_"), f"Private key leaked: {k}"
