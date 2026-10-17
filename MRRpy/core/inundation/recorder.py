# -*- coding: utf-8 -*-
"""
recorder.py — discharge for the flood maps, recorded during the time loop.

Every step the router hands over the volume that left each cell; at each
OUTPUT_INTERVAL the recorder turns it into the interval-mean discharge (the
same quantity as hydrograph.csv) and keeps

* the peak of it at every cell and the time of that peak,
* its time series at the river cells (for maps over time and the animation),
* the time series of the water entering each river cell from its side: the
  flow of the land cells that drain into it, the runoff of the rain on it and
  any inflow boundary or baseflow there (the local inflow of a 2D flood
  simulation, model2d.py),

each series averaged over a few output intervals only if both together would
exceed ~1 GB.  It never changes the routing state.  ``save()`` writes the
network snapshot (see snapshot.py) together with these flows.
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
        is_river = river_mask(cfg, grid_data)
        self._river = np.flatnonzero(is_river).astype(np.int64)
        self._river_dev = xp.asarray(self._river)
        # Land cells that drain straight into a river cell, and which river cell.
        ds = gpu_utils.to_cpu(grid_data["ds_idx"]).astype(np.int64)
        pos = np.full(n, -1, dtype=np.int64)
        pos[self._river] = np.arange(self._river.size)
        side = np.flatnonzero(~is_river & (ds >= 0))
        side = side[is_river[ds[side]]]
        self._side_dev = xp.asarray(side)
        self._side_to = xp.asarray(pos[ds[side]])
        self._lat_vol = xp.zeros(self._river.size, dtype=dtype)

        interval = float(getattr(cfg, "OUTPUT_INTERVAL_SECONDS", None) or cfg.TIME_STEP_SECONDS)
        n_out = math.ceil(float(cfg.TOTAL_SIMULATION_TIME_HOURS) * 3600.0 / interval)
        size = 2 * n_out * max(self._river.size, 1) * 4        # flow + local inflow series
        self._stride = max(1, math.ceil(size / _SERIES_BYTES))
        self._acc = np.zeros(self._river.size)       # river-cell volume over a stride window
        self._lat_acc = np.zeros(self._river.size)   # local inflow volume over a stride window
        self._acc_t = 0.0
        self._count = 0
        self._series = []
        self._lat_series = []
        self._times = []
        note = (f", averaged over {self._stride} output intervals to stay under 1 GB"
                if self._stride > 1 else "")
        print(f"  Flood maps     |  recording peak flow at every cell and the flow of "
              f"{self._river.size:,} river cells over time{note}")

    def accumulate(self, Q_out_vol_1d):
        """Add this step's outflow volume [m³] (called every step)."""
        self._vol += Q_out_vol_1d
        if self._side_dev.size:
            self._lat_vol += self._xp.bincount(self._side_to, weights=Q_out_vol_1d[self._side_dev],
                                               minlength=self._river.size)

    def add_input(self, rain_vol, bc_rate_1d, dt):
        """Add the water put into the river cells this step [m³]: runoff of the
        rain on them, and inflow boundaries / baseflow (called every step)."""
        v = rain_vol[self._river_dev]
        if bc_rate_1d is not None:
            v = v + bc_rate_1d[self._river_dev] * dt
        self._lat_vol += v

    def record(self, t_seconds, interval):
        """Close an output interval (called at each OUTPUT_INTERVAL)."""
        xp = self._xp
        q = self._vol / max(float(interval), 1e-12)
        newer = q > self._q_peak
        self._t_peak = xp.where(newer, float(t_seconds), self._t_peak)
        self._q_peak = xp.maximum(self._q_peak, q)
        self._acc += gpu_utils.to_cpu(q[self._river_dev]) * float(interval)
        self._lat_acc += gpu_utils.to_cpu(self._lat_vol)
        self._acc_t += float(interval)
        self._vol.fill(0)
        self._lat_vol.fill(0)
        self._count += 1
        if self._count % self._stride == 0:
            self._series.append((self._acc / self._acc_t).astype(np.float32))
            self._lat_series.append((self._lat_acc / self._acc_t).astype(np.float32))
            self._times.append(float(t_seconds))
            self._acc[:] = 0.0
            self._lat_acc[:] = 0.0
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
        arrays["lat_series"] = (np.stack(self._lat_series) if self._lat_series
                                else np.zeros((0, self._river.size), dtype=np.float32))
        meta["series_stride"] = self._stride
        path = save_snapshot(snapshot_path(self._cfg), arrays, meta)
        print(f"  Flood-map data → {path}")
        return path
