# -*- coding: utf-8 -*-
"""
batch.py
========
Many runs in one call.

``run_many`` runs a list of variations of one configuration — a sensitivity
study, a comparison of methods, the members of an ensemble — and returns one
summary table.  The terrain is processed once and shared, rain downloads are
shared, and the runs can go side by side on several processor cores.

``run_ensemble`` runs every member of an Open-Meteo ensemble forecast and
writes the range of floods they give.

    from MRRpy import Config, run_many

    base = Config.from_file("run.yaml")
    table = run_many(base, {
        "smooth": {"MANNINGS_N": 0.05},
        "rough":  {"MANNINGS_N": 0.15},
    }, output_dir="results/roughness", workers=2)
    print(table[["name", "peak_m3s", "peak_time_hr"]])
"""

import os
import shutil
import time

#: Settings that change the terrain files; runs that agree on all of them share one terrain.
TERRAIN_SETTINGS = (
    "DEM_PATH", "DEM_BOUNDS_WGS84", "DEM_SOURCE", "DEM_SCALE_M", "TARGET_CRS_EPSG",
    "MODEL_AREA", "OUTPUT_POINT", "DELINEATION_ENGINE", "DEM_CONDITIONING",
    "DEM_LAKE_MASK", "MIN_SLOPE",
)
#: Settings that define a rain download; runs that agree on all of them share it.
_RAIN_SETTINGS = (
    "PRECIP_METHOD", "EVENT_START_UTC", "TOTAL_SIMULATION_TIME_HOURS",
    "IMERG_START_LOCAL", "IMERG_END_LOCAL", "IMERG_DATASET", "IMERG_BAND",
    "IMERG_BBOX_BUFFER_M", "IMERG_UTC_OFFSET_HOURS",
    "OPENMETEO_SOURCE", "OPENMETEO_MODEL", "OPENMETEO_RUN", "OPENMETEO_MINUTELY_15",
    "OPENMETEO_POINT_SPACING_M", "OPENMETEO_BBOX_BUFFER_M",
)


def _key(cfg, names):
    return repr([getattr(cfg, n, None) for n in names])


def _share(src_dir, dst_dir):
    """Make every file of *src_dir* appear in *dst_dir* (hard link; copy if it can't)."""
    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        src, dst = os.path.join(src_dir, name), os.path.join(dst_dir, name)
        if not os.path.isfile(src) or name in ("run.log", "run_info.json", "run_config.yaml"):
            continue
        if os.path.exists(dst):
            os.remove(dst)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)


def _named(runs):
    """[(name, overrides)] from a dict {name: overrides} or a list of overrides."""
    if isinstance(runs, dict):
        items = [(str(k), dict(v)) for k, v in runs.items()]
    else:
        items = []
        width = max(2, len(str(len(runs))))
        for i, over in enumerate(runs, 1):
            over = dict(over)
            items.append((str(over.pop("name", f"run_{i:0{width}d}")), over))
    names = [n for n, _ in items]
    bad = [n for n in names if not n or os.sep in n or n.startswith(("_", "."))]
    if bad or len(set(names)) != len(names):
        raise ValueError("Each run needs its own plain name (it becomes a folder name); "
                         f"got {names}.")
    return items


def _one_run(job):
    """Run one prepared job (in this process or a worker); returns its summary row."""
    from .config import Config
    from .pipeline import run_pipeline

    name, cfg_dict, stages, overrides, quiet = job
    row = {"name": name, "status": "finished"}
    row.update({k: v for k, v in overrides.items()
                if isinstance(v, (int, float, str, bool)) or v is None})
    t0 = time.time()
    try:
        cfg = Config.from_dict(cfg_dict)
        out = run_pipeline(cfg, stages=stages, quiet=quiet)
        info = out.info or {}
        row.update(status="cancelled" if out.cancelled else "finished",
                   peak_m3s=out.peak_m3s, peak_time_hr=out.peak_time_hr,
                   runoff_ratio=info.get("runoff_ratio"),
                   balance_error=info.get("mass_balance_rel_error"))
        hyd = out.hydrograph
        if hyd is not None and len(hyd) > 1:
            dt = hyd["time_s"].diff().fillna(hyd["time_s"].iloc[0])
            row["volume_m3"] = float((hyd["Q_m3s"] * dt).sum())
    except Exception as exc:               # noqa: BLE001 — one bad run must not stop the rest
        row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    row["wall_s"] = round(time.time() - t0, 1)
    row["output_dir"] = cfg_dict["OUTPUT_DIR"]
    return row


def _run_side_by_side(jobs, workers, threads, report):
    """
    Run *jobs*, *workers* at a time, each as its own Python process started
    with ``python -m MRRpy.batch <job file>``.  Separate programs rather than
    a multiprocessing pool, so this works from a notebook or a plain script
    (no ``if __name__ == "__main__":`` needed), and each one's thread count
    is set before its numeric libraries load.
    """
    import json
    import subprocess
    import sys

    env = dict(os.environ)
    for var in ("NUMBA_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS"):
        env[var] = str(threads)
    waiting, running = list(jobs), []
    while waiting or running:
        while waiting and len(running) < workers:
            job = waiting.pop(0)
            name, cfg_dict, stages, overrides, quiet = job
            folder = cfg_dict["OUTPUT_DIR"]
            os.makedirs(folder, exist_ok=True)
            job_file = os.path.join(folder, "batch_job.json")
            try:
                with open(job_file, "w", encoding="utf-8") as f:
                    json.dump(job, f)
            except TypeError:
                # A setting that is a Python function cannot cross to another
                # process: run this one here.
                report(_one_run(job))
                continue
            proc = subprocess.Popen([sys.executable, "-m", "MRRpy.batch", job_file], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            running.append((proc, job, job_file, time.time()))
        for item in list(running):
            proc, job, job_file, t0 = item
            if proc.poll() is None:
                continue
            running.remove(item)
            result = job_file.replace("batch_job.json", "batch_result.json")
            try:
                with open(result, encoding="utf-8") as f:
                    row = json.load(f)
                os.remove(result)
            except (OSError, ValueError):
                row = {"name": job[0], "status": "failed", "wall_s": round(time.time() - t0, 1),
                       "error": f"the run's process stopped (exit code {proc.returncode}); "
                                "see run.log in its folder",
                       "output_dir": job[1]["OUTPUT_DIR"]}
            if os.path.exists(job_file):
                os.remove(job_file)
            report(row)
        if running:
            time.sleep(0.2)


def run_many(base, runs, output_dir=None, workers=1, stages=None, reuse_terrain=True,
             share_rain=True, quiet=True, log=print):
    """
    Run variations of *base* and return a summary table (a pandas DataFrame).

    Parameters
    ----------
    base : Config
        The configuration every run starts from.
    runs : dict {name: {SETTING: value, …}} or list of such dicts
        What each run changes.  Each run writes to ``<output_dir>/<name>/``
        (a list is named run_01, run_02, … unless a dict has a "name").
    output_dir : folder for the whole batch (default: base.OUTPUT_DIR).
    workers : how many runs go at the same time, each in its own process with
        the processor's threads shared out between them.  Use 1 with a GPU.
    stages : pipeline stages of each run (default: process_dem, routing).
    reuse_terrain : process the terrain once per distinct terrain setting
        (in ``<output_dir>/_terrain/``) and share its files with the runs.
    share_rain : runs with the same IMERG / Open-Meteo request share one
        download (in ``<output_dir>/_rain/``).
    quiet : each run prints only warnings (its full report is in its run.log).

    Returns
    -------
    DataFrame, one row per run: name, status, the changed settings, peak_m3s,
    peak_time_hr, volume_m3, runoff_ratio, balance_error, wall_s, output_dir
    (and error for a failed run).  Also saved as ``<output_dir>/summary.csv``.
    """
    import pandas as pd
    from .pipeline import DEFAULT_STAGES, run_pipeline

    items = _named(runs)
    stages = list(stages or DEFAULT_STAGES)
    root = os.path.abspath(output_dir or base.OUTPUT_DIR or "output")
    os.makedirs(root, exist_ok=True)
    run_stages = [s for s in stages if s != "process_dem"] if reuse_terrain else stages

    # ── One terrain per distinct terrain setting ─────────────────────────────
    terrains, rains, jobs = {}, {}, []
    for name, over in items:
        cfg = base.copy(**over)
        cfg.OUTPUT_DIR = os.path.join(root, name)
        if reuse_terrain and "process_dem" in stages:
            key = _key(cfg, TERRAIN_SETTINGS)
            if key not in terrains:
                tdir = os.path.join(root, "_terrain" + (f"_{len(terrains) + 1}" if terrains else ""))
                log(f"[batch] Terrain {len(terrains) + 1}: processing once in {tdir}")
                tcfg = cfg.copy(OUTPUT_DIR=tdir)
                run_pipeline(tcfg, stages=("process_dem",), quiet=quiet)
                terrains[key] = (tdir, tcfg.TARGET_CRS_EPSG, tcfg.DEM_PATH)
            tdir, crs, dem = terrains[key]
            _share(tdir, cfg.OUTPUT_DIR)
            cfg.TARGET_CRS_EPSG, cfg.DEM_PATH = crs, dem
        # ── One rain download per distinct request ───────────────────────────
        method = str(cfg.PRECIP_METHOD)
        if share_rain and method.startswith(("imerg", "openmeteo")):
            attr = "PRECIP_IMERG_DIR" if method.startswith("imerg") else "PRECIP_OPENMETEO_DIR"
            if attr not in cfg.explicit_paths():
                key = _key(cfg, _RAIN_SETTINGS + TERRAIN_SETTINGS)
                if key not in rains:
                    rains[key] = os.path.join(root, "_rain" + (f"_{len(rains) + 1}" if rains else ""))
                    setattr(cfg, attr, rains[key])
                    if "routing" in run_stages and os.path.exists(cfg.WATERSHED_GEOJSON):
                        log(f"[batch] Rain {len(rains)}: downloading once into {rains[key]}")
                        if method.startswith("imerg"):
                            from .gee.imerg_gee import ensure_imerg_data
                            ensure_imerg_data(cfg)
                        else:
                            from .core.precip.openmeteo import _ensure_download
                            _ensure_download(cfg)
                setattr(cfg, attr, rains[key])
        jobs.append((name, cfg.to_dict(), run_stages, over, quiet))

    # ── The runs ─────────────────────────────────────────────────────────────
    rows, n = [], len(jobs)

    def report(row):
        rows.append(row)
        if row["status"] == "finished" and row.get("peak_m3s") is not None:
            what = f"peak {row['peak_m3s']:.2f} m³/s at {row['peak_time_hr']:.2f} h"
        else:
            what = row["status"] + (f" — {row['error']}" if row.get("error") else "")
        log(f"[batch] {len(rows)}/{n}  {row['name']}: {what}  ({row['wall_s']:.0f} s)")

    workers = max(1, min(int(workers), n))
    if workers == 1:
        for job in jobs:
            report(_one_run(job))
    else:
        threads = max(1, min(32, (os.cpu_count() or 1) // workers))
        log(f"[batch] {n} runs, {workers} at a time, {threads} threads each")
        _run_side_by_side(jobs, workers, threads, report)

    order = {name: i for i, (name, _o) in enumerate(items)}
    table = pd.DataFrame(sorted(rows, key=lambda r: order[r["name"]]))
    last = [c for c in ("wall_s", "output_dir", "error") if c in table.columns]
    table = table[[c for c in table.columns if c not in last] + last]
    table.to_csv(os.path.join(root, "summary.csv"), index=False)
    failed = int((table["status"] == "failed").sum())
    log(f"[batch] Done: {n - failed} of {n} runs finished"
        + (f", {failed} failed (see the 'error' column)" if failed else "")
        + f". Summary: {os.path.join(root, 'summary.csv')}")
    return table


# ── Ensemble forecast ──────────────────────────────────────────────────────────

def run_ensemble(cfg, members=None, output_dir=None, workers=1, quiet=True, log=print):
    """
    Run every member of an Open-Meteo ensemble forecast and write the spread.

    *cfg* is an Open-Meteo run (PRECIP_METHOD openmeteo_thiessen / openmeteo_idw)
    with an ensemble OPENMETEO_MODEL such as ``gfs_seamless`` (31 members) or
    ``ecmwf_ifs025`` (51); OPENMETEO_SOURCE is set to 'ensemble' for you.
    *members*: the member numbers to run (default: all; 0 is the control run).

    Each member's results go to ``<output_dir>/member_NN/``.  Returns a dict:
    ``table`` (the run_many summary), ``hydrographs`` (DataFrame: time columns,
    one column per member, then min / p10 / p25 / median / p75 / p90 / max /
    mean) and ``csv`` (its file, ``<output_dir>/ensemble_hydrograph.csv``).
    ``MRRpy.plot_ensemble`` draws it.
    """
    import numpy as np
    import pandas as pd

    if not str(cfg.PRECIP_METHOD).startswith("openmeteo"):
        raise ValueError("run_ensemble needs Open-Meteo rain: set PRECIP_METHOD to "
                         "'openmeteo_thiessen' or 'openmeteo_idw'.")
    base = cfg.copy(OPENMETEO_SOURCE="ensemble")
    base.validate()
    root = os.path.abspath(output_dir or os.path.join(base.OUTPUT_DIR or "output", "ensemble"))

    # Terrain and the one download first, to learn how many members there are.
    from .core.precip.openmeteo import ensemble_members
    from .pipeline import run_pipeline
    tdir = os.path.join(root, "_terrain")
    probe = base.copy(OUTPUT_DIR=tdir)
    if not os.path.exists(probe.WATERSHED_GEOJSON):
        log(f"[ensemble] Processing the terrain once in {tdir}")
        run_pipeline(probe, stages=("process_dem",), quiet=quiet)
    probe.PRECIP_OPENMETEO_DIR = os.path.join(root, "_rain")
    have = ensemble_members(probe)
    chosen = have if members is None else [int(m) for m in members]
    missing = [m for m in chosen if m not in have]
    if missing:
        raise ValueError(f"Members {missing} are not in this ensemble "
                         f"(it has {have[0]} to {have[-1]}; 0 is the control run).")
    log(f"[ensemble] {base.OPENMETEO_MODEL}: running {len(chosen)} of {len(have)} members")

    base.TARGET_CRS_EPSG, base.DEM_PATH = probe.TARGET_CRS_EPSG, probe.DEM_PATH
    base.PRECIP_OPENMETEO_DIR = probe.PRECIP_OPENMETEO_DIR
    runs = {f"member_{m:02d}": {"OPENMETEO_MEMBER": m} for m in chosen}
    for name in runs:                                   # terrain: shared, not redone
        _share(tdir, os.path.join(root, name))
    table = run_many(base, runs, output_dir=root, workers=workers, stages=("routing",),
                     reuse_terrain=False, share_rain=False, quiet=quiet, log=log)

    series, frame = {}, None
    for name, row in zip(runs, table.to_dict("records")):
        path = os.path.join(row["output_dir"], "hydrograph.csv")
        if row["status"] != "finished" or not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        if frame is None:
            frame = df[[c for c in ("time_s", "time_hr", "time_utc") if c in df.columns]].copy()
        series[name] = df["Q_m3s"].values[:len(frame)]
    if frame is None:
        raise RuntimeError("No ensemble member finished; see the 'error' column of "
                           f"{os.path.join(root, 'summary.csv')}.")
    q = np.column_stack(list(series.values()))
    for name, col in zip(series, q.T):
        frame[name] = col
    frame["min"], frame["max"], frame["mean"] = q.min(axis=1), q.max(axis=1), q.mean(axis=1)
    for label, pct in (("p10", 10), ("p25", 25), ("median", 50), ("p75", 75), ("p90", 90)):
        frame[label] = np.percentile(q, pct, axis=1)
    csv = os.path.join(root, "ensemble_hydrograph.csv")
    frame.to_csv(csv, index=False)
    peaks = q.max(axis=0)
    log(f"[ensemble] Peak flow across {q.shape[1]} members: {peaks.min():.1f} to "
        f"{peaks.max():.1f} m³/s (median {np.median(peaks):.1f}). Spread: {csv}")
    return {"table": table, "hydrographs": frame, "csv": csv, "output_dir": root}


if __name__ == "__main__":
    # python -m MRRpy.batch <batch_job.json> — one run of run_many, in its own process.
    import json
    import sys

    with open(sys.argv[1], encoding="utf-8") as _f:
        _job = json.load(_f)
    _row = _one_run(tuple(_job))
    with open(sys.argv[1].replace("batch_job.json", "batch_result.json"), "w",
              encoding="utf-8") as _f:
        json.dump(_row, _f, default=str)
