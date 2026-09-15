"""
tests/08_test_mannings_n_channel_modes.py
==========================================
Verification tests for independent overland / channel Manning's-n sources
(resolve_mannings_n's MANNINGS_N_CHANNEL dispatch in
pymrr/core/routing/surface.py).

Uses a small synthetic grid_data built in-memory — no real DEM/watershed
needed — so these checks isolate the channel-override dispatch logic.

Tests
-----
1. Overland/channel decoupling — overland cells keep MANNINGS_N regardless
   of MANNINGS_N_CHANNEL; channel cells take the new elevation-bin,
   elevation-breakpoint, and callable forms and land in the expected ranges.
2. Backward compatibility — existing None / float / dict{order:n} behavior
   for MANNINGS_N_CHANNEL is unchanged.
3. apply_elevation_rule matches mannings_n_from_dem's raster output for the
   same rule (confirms the refactor extracting the shared helper didn't
   change behavior).

Run from the project root:
    python tests/08_test_mannings_n_channel_modes.py

Each test prints PASS or FAIL with a short reason.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pymrr.core.routing.surface import resolve_mannings_n
from pymrr.utils.terrain_rules import apply_elevation_rule, mannings_n_from_dem

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


class _Cfg:
    """Minimal stand-in for pymrr.Config exposing only what
    resolve_mannings_n reads."""
    MANNINGS_N_SOURCE = "scalar"
    MANNINGS_N = 0.09
    MANNINGS_N_CHANNEL = None
    CHANNEL_FACCUM_THRESHOLD = 5
    ROUTING_DEM_PATH = None


def _synthetic_grid():
    """
    A 10-cell linear chain (no confluences, so Strahler order is 1
    everywhere), elevation decreasing downstream from 100 to 10, with the
    5 highest-accumulation cells (faccum > 5) treated as channel cells.
    """
    n = 10
    s_rows = np.arange(n)
    s_cols = np.zeros(n, dtype=int)
    dem_1d = np.linspace(100.0, 10.0, n)
    faccum_1d = np.arange(1, n + 1)
    ds_idx = np.arange(1, n + 1)
    ds_idx[-1] = -1
    return dict(s_rows=s_rows, s_cols=s_cols, dem_1d=dem_1d,
                faccum_1d=faccum_1d, ds_idx=ds_idx), (faccum_1d > 5)


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — overland/channel decoupling across the new MANNINGS_N_CHANNEL forms
# ─────────────────────────────────────────────────────────────────────────────
def test_channel_modes_decoupled():
    name = "1 · overland/channel decoupling (elevation-bins/breakpoints/callable)"
    try:
        grid_data, channel_mask = _synthetic_grid()
        overland_mask = ~channel_mask

        cases = {
            "list (breakpoints)": [(30, 0.03), (70, 0.05), (float("inf"), 0.08)],
            "dict (bins)": {(0, 30): 0.02, (30, 200): 0.06},
            "callable": (lambda z: 0.001 * z),
        }

        ok = True
        reasons = []
        for label, rule in cases.items():
            cfg = _Cfg()
            cfg.MANNINGS_N_CHANNEL = rule
            n_1d = resolve_mannings_n(cfg, grid_data)

            if not np.allclose(n_1d[overland_mask], cfg.MANNINGS_N):
                ok = False
                reasons.append(f"{label}: overland cells changed")
            if np.isnan(n_1d).any():
                ok = False
                reasons.append(f"{label}: NaN in output")
            if not (0.005 <= n_1d[channel_mask].min() and
                    n_1d[channel_mask].max() <= 1.0):
                ok = False
                reasons.append(f"{label}: channel n outside sane range")

        if ok:
            print(f"  {PASS}  {name}")
        else:
            print(f"  {FAIL}  {name}  {'; '.join(reasons)}")
    except Exception as e:
        print(f"  {FAIL}  {name}  Exception: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — backward compatibility (None / float / dict{order:n})
# ─────────────────────────────────────────────────────────────────────────────
def test_backward_compatible_modes():
    name = "2 · backward compatibility (None / float / Strahler-order dict)"
    try:
        grid_data, channel_mask = _synthetic_grid()

        cfg = _Cfg()
        cfg.MANNINGS_N_CHANNEL = None
        n_none = resolve_mannings_n(cfg, grid_data)
        none_ok = np.allclose(n_none, cfg.MANNINGS_N)

        cfg.MANNINGS_N_CHANNEL = 0.035
        n_scalar = resolve_mannings_n(cfg, grid_data)
        scalar_ok = (np.allclose(n_scalar[channel_mask], 0.035) and
                     np.allclose(n_scalar[~channel_mask], cfg.MANNINGS_N))

        # Linear chain -> Strahler order 1 everywhere -> every channel cell
        # takes the order-1 value.
        cfg.MANNINGS_N_CHANNEL = {1: 0.10, 2: 0.05}
        n_strahler = resolve_mannings_n(cfg, grid_data)
        strahler_ok = (np.allclose(n_strahler[channel_mask], 0.10) and
                       np.allclose(n_strahler[~channel_mask], cfg.MANNINGS_N))

        # Mixed-key dict must raise a clear error, not silently misbehave.
        cfg.MANNINGS_N_CHANNEL = {1: 0.1, (0, 10): 0.2}
        raised = False
        try:
            resolve_mannings_n(cfg, grid_data)
        except ValueError:
            raised = True

        if none_ok and scalar_ok and strahler_ok and raised:
            print(f"  {PASS}  {name}")
        else:
            print(f"  {FAIL}  {name}  none_ok={none_ok} scalar_ok={scalar_ok} "
                  f"strahler_ok={strahler_ok} mixed_dict_raised={raised}")
    except Exception as e:
        print(f"  {FAIL}  {name}  Exception: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — apply_elevation_rule extraction is byte-compatible with
#           mannings_n_from_dem's raster output
# ─────────────────────────────────────────────────────────────────────────────
def test_apply_elevation_rule_matches_raster(tmp_dir):
    name = "3 · apply_elevation_rule matches mannings_n_from_dem raster output"
    try:
        import rasterio
        from rasterio.transform import from_origin

        elev = np.array([[100.0, 80.0], [60.0, 20.0]], dtype=np.float64)
        dem_path = os.path.join(tmp_dir, "dem_test.tif")
        n_path = os.path.join(tmp_dir, "n_test.tif")
        transform = from_origin(0, 2, 1, 1)
        profile = dict(driver="GTiff", height=2, width=2, count=1,
                       dtype="float64", crs="EPSG:4326", transform=transform,
                       nodata=-9999.0)
        with rasterio.open(dem_path, "w", **profile) as dst:
            dst.write(elev, 1)

        rule = [(30, 0.03), (70, 0.05), (float("inf"), 0.08)]
        mannings_n_from_dem(dem_path, rule, n_path)

        with rasterio.open(n_path) as src:
            raster_out = src.read(1)

        direct_out = apply_elevation_rule(elev, rule)

        if np.allclose(raster_out, direct_out):
            print(f"  {PASS}  {name}")
        else:
            print(f"  {FAIL}  {name}  raster={raster_out.tolist()} "
                  f"direct={direct_out.tolist()}")
    except Exception as e:
        print(f"  {FAIL}  {name}  Exception: {e}")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("Manning's-n channel-mode Verification Tests")
    print("=" * 60)
    print()

    test_channel_modes_decoupled()
    test_backward_compatible_modes()
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_apply_elevation_rule_matches_raster(tmp_dir)

    print()
    print("Done.")
