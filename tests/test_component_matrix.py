# -*- coding: utf-8 -*-
"""
tests/test_component_matrix.py
==============================
Every routing scheme × every runoff generator (and every combination of the
physical mechanisms, with Green-Ampt recovery on and off) on one basin, two
2-h storms separated by a 48-h dry spell — the case that exercises both soil
recovery and the implicit solver's first wet step after a dry spell.

Each run must:
  * close its mass balance (|error| < 1e-6 of the runoff that entered),
  * never generate more runoff than it rained,
  * split physical runoff exactly into impervious + Dunne + Horton,
  * give a finite, non-negative hydrograph.
And with infiltration excess (no saturation excess), letting the soil dry out
for 48 h must not produce more runoff than keeping it wet.

``dynamic`` is excluded (under development).  The basin is delineated once;
each case runs only the routing stage on a copy.
"""

import contextlib
import io
import itertools
import os
import shutil

import numpy as np
import pandas as pd
import pytest
import rasterio

from MRRpy import Config, run_pipeline

SCHEMES = ["kinematic", "diffusive", "muskingum", "diffusive_implicit"]
MECHS = ["impervious", "infiltration_excess", "saturation_excess"]
COMBOS = [list(c) for k in (1, 2, 3) for c in itertools.combinations(MECHS, k)]

CASES = []
for scheme in SCHEMES:
    CASES += [(scheme, "none", None, None), (scheme, "coefficient", None, None),
              (scheme, "scs_cn", None, None)]
    for combo in COMBOS:
        for rec in ((True, False) if "infiltration_excess" in combo else (None,)):
            CASES.append((scheme, "physical", tuple(combo), rec))


def _case_id(c):
    scheme, src, combo, rec = c
    tag = src if combo is None else "+".join(m.split("_")[0] for m in combo)
    return f"{scheme}-{tag}" + ("" if rec is None else f"-rec{'On' if rec else 'Off'}")


@pytest.fixture(autouse=True)
def _no_land_cover_download(monkeypatch):
    """Root-zone depth without Earth Engine (the basin sits near Kathmandu)."""
    from MRRpy.core.routing import surface
    monkeypatch.setattr(surface, "resolve_lulc_field",
                        lambda cfg, grid, column, default, source:
                            np.full(len(grid["s_rows"]), 0.5))


@pytest.fixture(scope="module")
def prepared(tiny_basin, tmp_path_factory):
    """Delineate once; write rain, impervious and runoff-coefficient inputs."""
    dem_p, outlet = tiny_basin
    d = tmp_path_factory.mktemp("matrix")
    with rasterio.open(dem_p) as ds:
        prof = ds.profile
        cx, cy = ds.xy(ds.height // 2, ds.width // 2)
        rows, cols = np.mgrid[0:ds.height, 0:ds.width]
    g, r = str(d / "gauges.csv"), str(d / "rain.csv")
    pd.DataFrame({"gauge_id": ["G1"], "name": ["G1"], "easting_m": [cx],
                  "northing_m": [cy]}).to_csv(g, index=False)
    t = np.arange(0, 56 * 3600 + 1, 1800)
    storm = (t < 2 * 3600) | ((t >= 50 * 3600) & (t < 52 * 3600))
    pd.DataFrame({"time_s": t, "G1": np.where(storm, 30.0, 0.0)}).to_csv(r, index=False)
    prof.update(dtype="float32", nodata=-9999.0)
    imp_p, cf_p = str(d / "imperv.tif"), str(d / "coef.tif")
    with rasterio.open(imp_p, "w", **prof) as ds:            # a "town" in the east half
        ds.write(np.where(cols > cols.max() // 2, 0.6, 0.0).astype("float32"), 1)
    with rasterio.open(cf_p, "w", **prof) as ds:
        ds.write(np.full(rows.shape, 0.4, dtype="float32"), 1)
    base = str(d / "base")
    cfg = _cfg(dem_p, outlet, base, g, r, imp_p, cf_p, "kinematic", "none", None, None)
    with contextlib.redirect_stdout(io.StringIO()):
        run_pipeline(cfg, stages=("process_dem",), on_log=lambda *_: None)
    return dem_p, outlet, base, g, r, imp_p, cf_p


def _cfg(dem_p, outlet, out, g, r, imp_p, cf_p, scheme, source, combo, rec):
    kw = dict(DEM_PATH=dem_p, OUTPUT_POINT=outlet, OUTPUT_DIR=out,
              TARGET_CRS_EPSG="EPSG:32645", DELINEATION_ENGINE="pysheds",
              PRECIP_METHOD="thiessen", PRECIP_GAUGE_FILE=g, PRECIP_TIMESERIES_FILE=r,
              ROUTING_SCHEME=scheme, TOTAL_SIMULATION_TIME_HOURS=56.0, CFL_DT_MAX=30.0,
              OUTPUT_INTERVAL_SECONDS=600, CHANNEL_QBF_M3S=1.0, RUNOFF_SOURCE=source,
              RUNOFF_COEFFICIENT_PATH=cf_p, RUNOFF_CN_SOURCE="scalar", RUNOFF_CN=80.0,
              VSA_SD_SOURCE="manual", VSA_Q_MAX=0.5, GA_KSAT_MMHR=12.0,
              IMPERVIOUS_SOURCE="raster", IMPERVIOUS_RASTER_PATH=imp_p)
    if combo is not None:
        kw["RUNOFF_MECHANISMS"] = list(combo)
    if rec is not None:
        kw["GA_RECOVERY"] = rec
    return Config(**kw)


def _route(prepared, tmp_path, scheme, source, combo, rec, backend="cpu"):
    dem_p, outlet, base, g, r, imp_p, cf_p = prepared
    out = str(tmp_path / "run")
    shutil.copytree(base, out)
    cfg = _cfg(dem_p, outlet, out, g, r, imp_p, cf_p, scheme, source, combo, rec)
    cfg.BACKEND = backend
    with contextlib.redirect_stdout(io.StringIO()):
        run_pipeline(cfg, stages=("routing",), on_log=lambda *_: None)
    mb = pd.read_csv(cfg.MASS_BALANCE_CSV).iloc[-1]
    hyd = pd.read_csv(cfg.HYDROGRAPH_CSV)
    return mb, hyd


@pytest.mark.parametrize("case", CASES, ids=[_case_id(c) for c in CASES])
def test_every_scheme_and_runoff_component(prepared, tmp_path, case):
    scheme, source, combo, rec = case
    mb, hyd = _route(prepared, tmp_path, scheme, source, combo, rec)
    inp, rain = float(mb["input_m3"]), float(mb["rain_m3"])
    assert inp > 0.0
    assert abs(float(mb["rel_error"])) < 1e-6, f"mass closure {mb['rel_error']}"
    assert inp <= rain * (1 + 1e-9)
    q = hyd["Q_m3s"].to_numpy()
    assert np.all(np.isfinite(q)) and q.min() >= 0.0 and q.max() > 0.0
    if source == "physical":
        parts = sum(float(mb[c]) if pd.notna(mb[c]) else 0.0
                    for c in ("dunne_m3", "horton_m3", "imperv_m3"))
        assert parts == pytest.approx(inp, rel=1e-6, abs=1e-3)


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("combo", [("infiltration_excess",),
                                   ("impervious", "infiltration_excess")],
                         ids=["infil", "imperv+infil"])
def test_drying_out_never_adds_runoff_after_a_long_dry_spell(prepared, tmp_path, scheme, combo):
    vols = {}
    for rec in (False, True):
        mb, _ = _route(prepared, tmp_path / str(rec), scheme, "physical", combo, rec)
        vols[rec] = float(mb["input_m3"])
    assert 0.0 < vols[True] < vols[False]


@pytest.mark.parametrize("scheme", ["kinematic", "diffusive", "muskingum"])
def test_gpu_matches_cpu_with_every_mechanism(prepared, tmp_path, scheme):
    cp = pytest.importorskip("cupy")
    try:
        cp.zeros(1).sum().item()
    except Exception:
        pytest.skip("no usable GPU")
    combo = tuple(MECHS)
    mb_c, hyd_c = _route(prepared, tmp_path / "cpu", scheme, "physical", combo, True)
    mb_g, hyd_g = _route(prepared, tmp_path / "gpu", scheme, "physical", combo, True,
                         backend="gpu")
    assert abs(float(mb_g["rel_error"])) < 1e-6
    assert float(mb_g["input_m3"]) == pytest.approx(float(mb_c["input_m3"]), rel=1e-9)
    assert np.allclose(hyd_g["Q_m3s"], hyd_c["Q_m3s"], rtol=1e-6, atol=1e-9)
