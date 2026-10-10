# -*- coding: utf-8 -*-
"""
recorder.py — discharge for the flood maps, recorded during the time loop.

Every step the router hands over the volume that left each cell; at each
OUTPUT_INTERVAL the recorder turns it into the interval-mean discharge (the
same quantity as hydrograph.csv) and keeps

* the peak of it at every cell and the time of that peak, and
* its time series at the river cells (for maps over time and the animation),
  averaged over a few output intervals only if it would exceed ~1 GB.

It never changes the routing state.  ``save()`` writes the network snapshot
(see snapshot.py) together with these flows.
"""

import math

import numpy as np

from ...utils import gpu_utils
from .snapshot import build_snapshot, river_mask, save_snapshot, snapshot_path

_SERIES_BYTES = 1.0e9


class PeakDischargeRecorder:
    def __init__(self, cfg, grid_data):
        self._cfg = cfg
        self._grid = grid_data
        xp = self._xp = grid_data.get("xp", np)
        n = int(grid_data["n_cells"])
        dtype = gpu_utils.get_dtype(cfg)
        self._vol = xp.zeros(n, dtype=dtype)
        self._q_peak = xp.zeros(n, dtype=dtype)
        self._t_peak = xp.zeros(n, dtype=dtype)
        self._river = np.flatnonzero(river_mask(cfg, grid_data)).astype(np.int64)
        self._river_dev = xp.asarray(self._river)

        interval = float(getattr(cfg, "OUTPUT_INTERVAL_SECONDS", None) or cfg.TIME_STEP_SECONDS)
        n_out = math.ceil(float(cfg.TOTAL_SIMULATION_TIME_HOURS) * 3600.0 / interval)
        size = n_out * max(self._river.size, 1) * 4
        self._stride = max(1, math.ceil(size / _SERIES_BYTES))
        self._acc = np.zeros(self._river.size)       # river-cell volume over a stride window
        self._acc_t = 0.0
        self._count = 0
        self._series = []
        self._times = []
        note = (f", averaged over {self._stride} output intervals to stay under 1 GB"
                if self._stride > 1 else "")
        print(f"  Flood maps     |  recording peak flow at every cell and the flow of "
              f"{self._river.size:,} river cells over time{note}")

    def accumulate(self, Q_out_vol_1d):
        """Add this step's outflow volume [m³] (called every step)."""
        self._vol += Q_out_vol_1d

    def record(self, t_seconds, interval):
        """Close an output interval (called at each OUTPUT_INTERVAL)."""
        xp = self._xp
        q = self._vol / max(float(interval), 1e-12)
        newer = q > self._q_peak
        self._t_peak = xp.where(newer, float(t_seconds), self._t_peak)
        self._q_peak = xp.maximum(self._q_peak, q)
        self._acc += gpu_utils.to_cpu(q[self._river_dev]) * float(interval)
        self._acc_t += float(interval)
        self._vol.fill(0)
        self._count += 1
        if self._count % self._stride == 0:
            self._series.append((self._acc / self._acc_t).astype(np.float32))
            self._times.append(float(t_seconds))
            self._acc[:] = 0.0
            self._acc_t = 0.0

    def save(self):
        """Write {OUTPUT_DIR}/inundation/network.npz.  Returns its path."""
        arrays, meta = build_snapshot(self._cfg, self._grid)
        arrays["q_peak"] = gpu_utils.to_cpu(self._q_peak).astype(np.float32)
        arrays["t_peak_s"] = gpu_utils.to_cpu(self._t_peak).astype(np.float32)
        arrays["river_idx"] = self._river.astype(np.int32)
        arrays["times_s"] = np.asarray(self._times, dtype=np.float64)
        arrays["q_series"] = (np.stack(self._series) if self._series
                              else np.zeros((0, self._river.size), dtype=np.float32))
        meta["series_stride"] = self._stride
        path = save_snapshot(snapshot_path(self._cfg), arrays, meta)
        print(f"  Flood-map data → {path}")
        return path
