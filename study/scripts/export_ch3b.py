"""Data for the D8-tree interlude (Ch 3b) of the study course, made with MRRpy's own code.

    ~/.conda/envs/mrrpy/bin/python study/scripts/export_ch3b.py

Writes
  src/data/ch3b/presets.json        the small DEMs the widgets start from
  scripts/fixtures/ch3b_expected.json
                                    what MRRpy computes on them; the browser code
                                    (src/lib/tree/tree.ts) is checked against it by
                                    scripts/check_tree_lib.ts

The DEM steps are the ones `dem_processing` runs for the default pyflwdir engine
(`pyflwdir.dem.fill_depressions` → D8, `upstream_area(unit="cell")`); the tree
steps are `routing.terrain` and the two sequential tree walks
(`hydraulics._mc_sweep`, `implicit._sweep_solve`).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
REPO = os.path.dirname(STUDY)
sys.path.insert(0, REPO)

import numpy as np
import pyflwdir

from MRRpy.core.routing import terrain as T
from MRRpy.core.routing.hydraulics import _mc_sweep
from MRRpy.core.routing.implicit import _sweep_solve, _build_children_csr

DATA = os.path.join(STUDY, "src", "data", "ch3b")
FIX = os.path.join(HERE, "fixtures")

# Elevations in metres; integer (or half-metre) values so the browser sees exactly
# the DEM MRRpy ran on.
PRESETS = {
    "valley": {
        "label": "Valley",
        "z": [[9, 8, 7, 8, 9], [8, 6, 5, 6, 8], [7, 5, 4, 5, 7], [6, 4, 3, 4, 6], [6, 5, 1, 5, 6]],
    },
    "tributaries": {
        "label": "Two tributaries",
        "z": [[4, 8, 9, 8, 4], [5, 3, 8, 3, 5], [7, 5, 2, 5, 7], [8, 6, 1.5, 6, 8], [9, 8, 1, 8, 9]],
    },
    "flat": {
        "label": "Flat plateau",
        "z": [[9, 9, 9, 9, 9], [9, 6, 6, 6, 9], [9, 6, 6, 6, 9], [9, 7, 5, 7, 9], [9, 9, 4, 9, 9]],
    },
    "ridge": {
        "label": "Ridge (several outlets)",
        "z": [[3, 4, 6, 4, 2], [3, 5, 7, 5, 3], [4, 6, 8, 6, 3], [3, 5, 7, 5, 4], [1, 4, 6, 4, 3]],
    },
    # the small basin the "three walks" widget runs on
    "mini": {
        "label": "Small valley (12 cells)",
        "z": [[9, 8, 7, 6], [8, 5, 4, 3], [9, 7, 6, 1]],
    },
}


def run_preset(z):
    z = np.asarray(z, dtype=np.float64)
    ny, nx = z.shape
    filled, d8 = pyflwdir.dem.fill_depressions(z, outlets="edge", nodata=-9999.0)
    flw = pyflwdir.from_array(d8, ftype="d8", check_ftype=False)
    fa = flw.upstream_area(unit="cell")

    # watershed of the cell with the largest accumulation (MRRpy's outlet)
    outlet = int(np.argmax(fa))
    mask = flw.basins(idxs=np.array([outlet], dtype=np.intp)) > 0

    rows, cols, _ = T.topological_order(fa, d8, mask)
    ds_idx = T.build_downstream_map(rows, cols, d8, mask, ny, nx)
    strahler = T.compute_strahler_order(ds_idx, len(rows))

    flat = (rows * nx + cols).astype(int)
    ds_flat = {int(f): (int(flat[d]) if d >= 0 else -1) for f, d in zip(flat, ds_idx)}
    str_flat = {int(f): int(s) for f, s in zip(flat, strahler)}

    # whole-DEM mode: every cell, many roots
    wmask = np.ones_like(mask)
    wr, wc, _ = T.topological_order(fa, d8, wmask)
    wds = T.build_downstream_map(wr, wc, d8, wmask, ny, nx)
    wflat = (wr * nx + wc).astype(int)

    return {
        "filled": filled.ravel().tolist(),
        "d8": d8.ravel().astype(int).tolist(),
        "fa": fa.ravel().astype(int).tolist(),
        "mask": mask.ravel().astype(int).tolist(),
        "outlet": outlet,
        "order": flat.tolist(),
        "ds_flat": [ds_flat.get(i, -2) for i in range(ny * nx)],
        "strahler": [str_flat.get(i, 0) for i in range(ny * nx)],
        "whole_order": wflat.tolist(),
        "whole_ds_flat": [int(wflat[d]) if d >= 0 else -1 for d in wds],
        "_ds_idx": ds_idx,
    }


def mc_case(ds_idx, rng):
    n = len(ds_idx)
    # Muskingum–Cunge weights sum to one (C0+C1+C2 = 1); C3 scales the lateral inflow
    C0 = rng.uniform(0.2, 0.5, n)
    C1 = rng.uniform(0.1, 0.3, n)
    C2 = 1.0 - C0 - C1
    C3 = rng.uniform(0.3, 0.6, n)
    I1 = rng.uniform(0.0, 3.0, n)
    O1 = rng.uniform(0.0, 3.0, n)
    QL = rng.uniform(0.0, 1.0, n)
    ds = np.asarray(ds_idx, dtype=np.int64)
    O2, I2, neg = _mc_sweep(C0, C1, C2, C3, I1, O1, QL, ds)
    child_off, child_idx = _build_children_csr(ds, ds >= 0, n)
    arr = lambda a: [float(x) for x in a]
    return {"C0": arr(C0), "C1": arr(C1), "C2": arr(C2), "C3": arr(C3), "I1": arr(I1),
            "O1": arr(O1), "QL": arr(QL), "ds_idx": [int(d) for d in ds_idx],
            "O2": arr(O2), "I2": arr(I2), "neg": int(neg),
            "child_off": [int(x) for x in child_off], "child_idx": [int(x) for x in child_idx]}


def solve_case(rng, n=40):
    # random tree in topological order: parent[i] > i, a few roots
    parent = np.full(n, -1, dtype=np.int64)
    for i in range(n - 1):
        if rng.random() > 0.08:
            parent[i] = rng.integers(i + 1, n)
    is_root = parent < 0
    K = rng.uniform(0.2, 3.0, n) * ~is_root
    off = -K
    diag = rng.uniform(0.1, 1.0, n)            # storage / dt
    np.add.at(diag, np.arange(n)[~is_root], K[~is_root])
    np.add.at(diag, parent[~is_root], K[~is_root])
    rhs = rng.uniform(-5, 5, n)
    z = _sweep_solve(diag.copy(), off.copy(), parent, is_root, rhs.copy())
    # dense reference
    M = np.diag(diag)
    for i in np.nonzero(~is_root)[0]:
        M[i, parent[i]] = M[parent[i], i] = off[i]
    z_dense = np.linalg.solve(M, rhs)
    arr = lambda a: [float(x) for x in a]
    return {"diag": arr(diag), "off": arr(off), "parent": [int(p) for p in parent],
            "rhs": arr(rhs), "z": arr(z), "max_err_vs_dense": float(np.abs(z - z_dense).max())}


def main():
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(FIX, exist_ok=True)
    rng = np.random.default_rng(7)

    presets, expected = {}, {}
    for name, p in PRESETS.items():
        z = p["z"]
        ny, nx = len(z), len(z[0])
        presets[name] = {"label": p["label"], "ny": ny, "nx": nx,
                         "z": [float(v) for row in z for v in row]}
        res = run_preset(z)
        ds_idx = res.pop("_ds_idx")
        res["mc"] = mc_case(ds_idx, rng)
        expected[name] = res
    expected["_solve"] = solve_case(rng)
    # random DEMs with pits and flats: the fill/D8/accumulation port must match on edits
    rand = []
    for k in range(6):
        z = rng.integers(1, 7, size=(7, 7)).astype(float)
        filled, d8 = pyflwdir.dem.fill_depressions(z, outlets="edge", nodata=-9999.0)
        fa = pyflwdir.from_array(d8, ftype="d8", check_ftype=False).upstream_area(unit="cell")
        rand.append({"z": z.ravel().tolist(), "filled": filled.ravel().tolist(),
                     "d8": d8.ravel().astype(int).tolist(), "fa": fa.ravel().astype(int).tolist()})
    expected["_random"] = rand

    with open(os.path.join(DATA, "presets.json"), "w") as f:
        json.dump(presets, f, indent=1)
    with open(os.path.join(FIX, "ch3b_expected.json"), "w") as f:
        json.dump(expected, f)
    print("wrote", os.path.join(DATA, "presets.json"))
    print("wrote", os.path.join(FIX, "ch3b_expected.json"))
    print("tree solve vs dense: max error %.2e" % expected["_solve"]["max_err_vs_dense"])


if __name__ == "__main__":
    main()
