# -*- coding: utf-8 -*-
"""
restart.py — save the model state during a run, and start a later run from it.

A state file (``.npz``) holds what the time loop carries from one step to the
next: the water stored in every cell, the Muskingum–Cunge flows, the step-size
controller and the runoff state (Green-Ampt soil water, the saturation-excess
sandbox, SCS-CN totals).  It also describes the grid and the parameters fixed at
start-up — channel size, roughness, soil — so a state is never loaded into a
different model by mistake: a changed grid or scheme, or a soil raster that went
missing so Ksat fell back to a constant, is refused with a plain message.

``SAVE_STATE_AT_HOURS`` lists when a run writes a state
(``{OUTPUT_DIR}/state/state_<hours>h.npz``, listed in ``state/index.csv``);
``RESTART_FROM`` names the file a run starts from.  Times in the new run count
from its own start (t = 0), like every other input.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np

from ...utils import gpu_utils

FORMAT = 1

# Routing parameters compared on restart, and how a message names them.
ROUTING_PARAMS = {
    "slope_1d":      "the ground slopes",
    "width_1d":      "the river widths",
    "store_area_1d": "the river storage areas",
    "bank_1d":       "the bankfull depths",
    "n_1d":          "Manning's roughness",
    "chan_mask_1d":  "which cells are rivers",
    "base_rate_1d":  "the baseflow",
}
_RUNOFF_PARAM_WORDS = {
    "_ksat": "the soil infiltration rate (Ksat)",
    "_psi": "the soil suction",
    "_dtheta0": "the starting soil moisture deficit",
    "_Lu": "the soil recovery parameters", "_kr": "the soil recovery parameters",
    "_Tr": "the soil recovery parameters", "_Fumax": "the soil recovery parameters",
    "frac": "the impervious fraction",
    "_S_1d": "the curve numbers", "_Ia_1d": "the curve numbers",
    "_Cf_1d": "the runoff coefficients",
    "_SD_max_initial": "the saturation-excess sandbox",
    "_opm_H_a": "the saturation-excess sandbox",
    "_ksat_ms": "the saturation-excess sandbox",
    "_cell_polygon": "the rain-gauge zones",
    "_polygon_divide_idx": "the rain-gauge zones",
    "_divide_cell": "the rain-gauge zones",
}
# Schemes whose whole state is the stored volume (interchangeable on restart).
_VOLUME_SCHEMES = ("kinematic", "diffusive", "diffusive_implicit")


class RestartError(ValueError):
    """A state file that does not fit this model."""


# ── Description of the model a state belongs to ──────────────────────────────

def _summary(value):
    """[size, sum, sum of squares, min, max, n_nan] of an array (or None)."""
    if value is None:
        return None
    a = np.asarray(gpu_utils.to_cpu(value), dtype=np.float64).ravel()
    if a.size == 0:
        return [0, 0.0, 0.0, 0.0, 0.0, 0]
    ok = a[np.isfinite(a)]
    if ok.size == 0:
        return [int(a.size), 0.0, 0.0, 0.0, 0.0, int(a.size)]
    return [int(a.size), float(ok.sum()), float((ok * ok).sum()),
            float(ok.min()), float(ok.max()), int(a.size - ok.size)]


def _grid_key(grid_data):
    h = hashlib.sha1()
    for k in ("s_rows", "s_cols"):
        h.update(np.ascontiguousarray(gpu_utils.to_cpu(grid_data[k]), dtype=np.int64).tobytes())
    t = grid_data["transform"]
    h.update(json.dumps([round(float(v), 6) for v in tuple(t)[:6]]).encode())
    return h.hexdigest()


def _runoff_signature(grid_data, cfg):
    engine = grid_data.get("runoff_engine")
    if engine is None:
        return {"mode": "none", "mechanisms": [], "ga_recovery": None}, {}
    mode = str(getattr(cfg, "RUNOFF_SOURCE", "none")).lower()
    mechs = sorted(getattr(cfg, "RUNOFF_MECHANISMS", []) or []) if mode == "physical" else []
    sig = {"mode": mode, "mechanisms": mechs,
           "ga_recovery": (bool(getattr(cfg, "GA_RECOVERY", True))
                           if "infiltration_excess" in mechs else None)}
    return sig, engine.get_params()


def describe(grid_data, cfg, scheme):
    """The model a state belongs to: grid, scheme, runoff and fixed parameters."""
    runoff, runoff_params = _runoff_signature(grid_data, cfg)
    return {
        "format": FORMAT,
        "n_cells": int(grid_data["n_cells"]),
        "grid": _grid_key(grid_data),
        "scheme": scheme,
        "runoff": runoff,
        "routing_params": {k: _summary(grid_data.get(k)) for k in ROUTING_PARAMS},
        "runoff_params": {k: _summary(v) for k, v in runoff_params.items()},
    }


# ── Save ─────────────────────────────────────────────────────────────────────

def state_dir(cfg):
    return os.path.join(getattr(cfg, "OUTPUT_DIR", "output/"), "state")


def state_file_name(hours):
    return f"state_{hours:08.2f}h.npz"


def save_state(cfg, grid_data, scheme, t_seconds, routing):
    """Write the state at *t_seconds* → path.  *routing*: {name: array or float}."""
    from ... import __version__

    meta = describe(grid_data, cfg, scheme)
    hours = t_seconds / 3600.0
    meta.update({
        "hours": hours,
        "mrrpy_version": __version__,
        "saved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "valid_utc": None,
    })
    start = getattr(cfg, "EVENT_START_UTC", None)
    if start:
        try:
            meta["valid_utc"] = (datetime.fromisoformat(str(start).strip())
                                 + timedelta(seconds=t_seconds)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass

    arrays = {"meta": np.array(json.dumps(meta))}
    for k, v in routing.items():
        arrays[f"routing.{k}"] = (np.asarray(float(v)) if np.isscalar(v)
                                  else np.asarray(gpu_utils.to_cpu(v), dtype=np.float64))
    engine = grid_data.get("runoff_engine")
    if engine is not None:
        for k, v in engine.get_state().items():
            arrays[f"runoff.{k}"] = v

    out_dir = state_dir(cfg)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, state_file_name(hours))
    tmp = path + ".part.npz"
    np.savez_compressed(tmp, **arrays)
    os.replace(tmp, path)                          # readers never see half a file

    index = os.path.join(out_dir, "index.csv")
    new = not os.path.isfile(index)
    with open(index, "a") as f:
        if new:
            f.write("file,hours,valid_utc\n")
        f.write(f"{os.path.basename(path)},{hours:g},{meta['valid_utc'] or ''}\n")
    print(f"  State saved     |  t={hours:g} h"
          + (f" ({meta['valid_utc']} UTC)" if meta["valid_utc"] else "") + f"  → {path}")
    return path


# ── Load ─────────────────────────────────────────────────────────────────────

def read_meta(path):
    """The description stored in a state file (no checks)."""
    with np.load(path, allow_pickle=False) as z:
        return json.loads(str(z["meta"]))


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if a[0] != b[0] or a[5] != b[5]:
        return False
    return np.allclose(a[1:5], b[1:5], rtol=1e-5, atol=1e-12)


def _check(saved, now, path):
    where = f"The state file {path}"
    if saved.get("format") != FORMAT:
        raise RestartError(f"{where} was written by another MRRpy version "
                           f"(format {saved.get('format')}, this MRRpy reads {FORMAT}).")
    if saved["n_cells"] != now["n_cells"] or saved["grid"] != now["grid"]:
        raise RestartError(
            f"{where} was saved on a different grid ({saved['n_cells']:,} cells, this model "
            f"has {now['n_cells']:,}). Use a state from a run with the same DEM, outlet "
            "and resolution.")
    s, n = saved["scheme"], now["scheme"]
    if s != n and not (s in _VOLUME_SCHEMES and n in _VOLUME_SCHEMES):
        raise RestartError(f"{where} was saved with ROUTING_SCHEME='{s}'; this run uses "
                           f"'{n}'. Muskingum–Cunge states only fit Muskingum–Cunge runs.")
    if saved["runoff"] != now["runoff"]:
        raise RestartError(f"{where} was saved with different runoff settings "
                           f"({saved['runoff']}); this run has {now['runoff']}.")
    for k, label in ROUTING_PARAMS.items():
        if not _same(saved["routing_params"].get(k), now["routing_params"].get(k)):
            raise RestartError(
                f"{where} does not fit this model: {label} changed since it was saved "
                f"({k}). A setting or an input file (a land-cover raster, the "
                "channel-size data) is different.")
    # In the order the model lists them, so a cause (Ksat) comes before what it sets.
    names = list(now["runoff_params"]) + [k for k in saved["runoff_params"]
                                          if k not in now["runoff_params"]]
    for k in names:
        if not _same(saved["runoff_params"].get(k), now["runoff_params"].get(k)):
            attr = k.rsplit(".", 1)[-1]
            label = _RUNOFF_PARAM_WORDS.get(attr, attr)
            raise RestartError(
                f"{where} does not fit this model: {label} changed since it was saved "
                f"({k}). A soil or land-cover file that is missing or changed is the usual "
                "cause (MRRpy then falls back to the plain setting); or the rain gauges "
                "changed, which moves the saturation-excess zones.")


def load_state(path, grid_data, cfg, scheme):
    """
    Check *path* against this model, restore the runoff state and return the
    routing state {name: numpy array or float} (``volume_1d``, plus the
    Muskingum–Cunge flows and step-size controller when saved).
    """
    if not os.path.isfile(str(path)):
        raise RestartError(f"RESTART_FROM file not found: {path}")
    with np.load(path, allow_pickle=False) as z:
        saved = json.loads(str(z["meta"]))
        routing = {k[len("routing."):]: z[k] for k in z.files if k.startswith("routing.")}
        runoff = {k[len("runoff."):]: z[k] for k in z.files if k.startswith("runoff.")}
    _check(saved, describe(grid_data, cfg, scheme), path)

    engine = grid_data.get("runoff_engine")
    if engine is not None:
        try:
            engine.set_state(runoff)
        except ValueError as exc:
            raise RestartError(f"The state file {path} does not fit this runoff model: "
                               f"{exc}.") from None
    out = {}
    for k, v in routing.items():
        out[k] = float(v) if v.ndim == 0 else v
    if saved["scheme"] != scheme:                  # volume schemes: keep the water only
        out = {"volume_1d": out["volume_1d"]}
    print(f"  Restart         |  from {path}  (saved at t={saved['hours']:g} h"
          + (f", {saved['valid_utc']} UTC" if saved.get("valid_utc") else "") + ")")
    return out
