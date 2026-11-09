# -*- coding: utf-8 -*-
"""
model2d.py — flood maps from a 2D flood simulation over one area
(``INUNDATION_METHOD: 2d``).

The routing covers the whole basin as usual; inside ``INUNDATION_AREA`` (or the
whole modelled area) the water is then moved in two dimensions (solver2d.py)
on the real ground:

1. Ground: the same DEM and flow paths as the HAND maps (finegrid.py), as it
   is.  Only the river cells are cleared so the river runs: lowered where they
   would rise downstream (bridges, DEM dams) and graded so that no river cell
   stands more than 1.5 × its reach slope × the distance above the next one
   (``network.graded_river_bed``); at a diagonal step the lower side cell is
   opened so the river stays connected across cell faces.  Nothing is cut
   below the DEM.
2. Roughness: the routed channel's Manning's n on the river cells, the land
   roughness of the routing elsewhere.
3. Water in: each river that enters the area brings its routed flow, spread
   over the low cells beside its entry; the land inside the area adds the
   water the routing passed into its rivers there (recorder.py).
4. Water out: at normal depth wherever the ground slopes out of the area,
   and across the valley floor beside every river that leaves it; the edge
   cells water flows into from outside (where rivers enter) are walls.
5. Time: the period around the largest flood entering the area.  The rivers
   are first filled with the flow at its start until they run steady.

Checked against observations in TestCases/flood_zoom_nakhu and
TestCases/flood_zoom_us (Nakhu 2024, Montpelier 2023, Pearl at Jackson 2020).
"""

import json
import math
import os
import time as _time

import numpy as np

from . import network as N
from .mapping import FloodGrid, _to_grid, _write_tif, write_flood_maps

MAX_CELLS = 5_000_000      # larger: a smaller INUNDATION_AREA or a coarser INUNDATION_DEM_SCALE_M
SPREAD_DZ = 2.0            # [m] an entering river spreads over edge cells at most this much higher
RISE_FRACTION = 0.3        # the flood: inflow above 30 % of the way from its lowest to its highest
PAD_S = 86400.0            # [s] simulated before the rise and after the fall
MAX_WINDOW_S = 30 * 86400.0
SPINUP_MAX_S = 48 * 3600.0  # filling the rivers at the starting flow, at most
FRAME_BYTES = 3.0e8        # depth over time kept for plots and the animation, at most
EDGE_DEPTH_M = 0.3         # deeper water against a wall edge is reported
OUTFLOW_SPAN_M = 3000.0    # [m] outflow beside a river leaving: this far along the edge ...
OUTFLOW_DZ = 20.0          # [m] ... and up to this height above the river


def _window(grid, area_bbox):
    """(r0, r1, c0, c1) of the simulated box on the grid."""
    if area_bbox:
        from rasterio.warp import transform_bounds
        x0, y0, x1, y1 = transform_bounds("EPSG:4326", grid.crs, *[float(v) for v in area_bbox],
                                          densify_pts=21)
        inv = ~grid.transform
        c0f, r1f = inv * (x0, y0)
        c1f, r0f = inv * (x1, y1)
        r0, r1 = max(int(np.floor(r0f)), 0), min(int(np.ceil(r1f)), int(grid.nrows))
        c0, c1 = max(int(np.floor(c0f)), 0), min(int(np.ceil(c1f)), int(grid.ncols))
    else:
        sel = grid.inside
        r0, r1 = int(grid.rows[sel].min()), int(grid.rows[sel].max()) + 1
        c0, c1 = int(grid.cols[sel].min()), int(grid.cols[sel].max()) + 1
    if r1 - r0 < 3 or c1 - c0 < 3:
        raise ValueError("The flood-map area (INUNDATION_AREA) does not overlap the modelled "
                         "area. Check it is west, south, east, north in degrees.")
    return r0, r1, c0, c1


def _edge_side(r, c, ny, nx):
    return "S" if r == ny - 1 else "N" if r == 0 else "W" if c == 0 else "E" if c == nx - 1 else None


class Box:
    """The simulated box: ground, roughness, rivers, sources and outflow."""

    def __init__(self, grid, arrays, meta, area_bbox, mannings_n=0.05):
        g = grid
        self.grid = g
        r0, r1, c0, c1 = self.win = _window(g, area_bbox)
        ny, nx = self.shape = (r1 - r0, c1 - c0)
        if ny * nx > MAX_CELLS:
            raise ValueError(
                f"The 2D flood simulation would cover {ny * nx:,} cells of {g.cell_size:g} m "
                f"(limit {MAX_CELLS:,}). Choose a smaller INUNDATION_AREA, or a coarser "
                "INUNDATION_DEM_SCALE_M.")
        self.dx = float(g.cell_size)
        self.transform = g.transform * g.transform.translation(c0, r0)
        inwin = (g.rows >= r0) & (g.rows < r1) & (g.cols >= c0) & (g.cols < c1)
        lr, lc = g.rows - r0, g.cols - c0
        self.inwin, self.lr, self.lc = inwin, lr, lc

        def to2d(v, fill):
            out = np.full((ny, nx), fill, dtype=np.asarray(v).dtype)
            out[lr[inwin], lc[inwin]] = np.asarray(v)[inwin]
            return out
        self.to2d = to2d

        # Ground: the DEM as it is, the river cells cleared (module docstring).
        river_all = g.area_km2 >= float(meta["a_channel_km2"])
        bed = N.graded_river_bed(g.order, g.ds, g.dist, river_all, g.z_raw, g.slope_reach)
        z2d = to2d(np.where(river_all, bed, g.z_raw), np.nan)
        for i in np.flatnonzero(river_all & inwin):
            d = g.ds[i]
            if d < 0 or not inwin[d] or g.rows[i] == g.rows[d] or g.cols[i] == g.cols[d]:
                continue
            a, b = (lr[i], lc[d]), (lr[d], lc[i])        # diagonal step: open a side cell
            za = z2d[a] if np.isfinite(z2d[a]) else np.inf
            zb = z2d[b] if np.isfinite(z2d[b]) else np.inf
            side = a if za <= zb else b
            if np.isfinite(z2d[side]) and z2d[side] > bed[i]:
                z2d[side] = bed[i]
        self.inside = np.isfinite(z2d)
        if not self.inside.any():
            raise ValueError("The flood-map area (INUNDATION_AREA) has no elevation data.")
        self.ground = z2d                                  # NaN outside the DEM
        self.z = np.where(self.inside, z2d, np.nanmax(z2d) + 50.0)   # walls outside the DEM
        self.river = to2d(river_all, False)

        # Roughness: the routed channel's n on the river, the land's n elsewhere.
        flow = g.river & (g.src >= 0)
        pick = flow & inwin if (flow & inwin).any() else flow
        n_river = float(np.median(g.n_ch[pick])) if pick.any() else float(mannings_n)
        n_ch = to2d(np.where(flow, g.n_ch, n_river), n_river)
        n_fp = to2d(g.n_fp, float(mannings_n))
        self.n = np.where(self.river, n_ch, np.where(np.isfinite(n_fp) & (n_fp > 0), n_fp,
                                                     float(mannings_n)))
        self.n = np.where(self.n > 0, self.n, float(mannings_n))

        self._sources(arrays, meta, flow, river_all)
        self._outflow(river_all)

    # ── water in ─────────────────────────────────────────────────────────────
    def _sources(self, arrays, meta, flow, river_all):
        """Entering rivers (routed flow × area ratio, spread over the low edge
        cells beside the entry) and the local inflow of the river cells inside
        (the water the routing passed into them from their side)."""
        from affine import Affine
        from pyproj import Transformer
        from scipy.spatial import cKDTree
        g, (ny, nx), inwin, lr, lc = self.grid, self.shape, self.inwin, self.lr, self.lc
        z = self.z
        q_series = arrays["q_series"]
        self.times = np.asarray(arrays["times_s"], dtype=np.float64)
        to_ll = Transformer.from_crs(g.crs, "EPSG:4326", always_xy=True)
        cells, cols, info, entry_cells = [], [], [], []

        ent = np.flatnonzero(flow & ~inwin & (g.ds >= 0))
        ent = ent[inwin[g.ds[ent]]]
        for u in ent[np.argsort(-g.area_km2[ent])]:
            e = g.ds[u]
            er, ec = lr[e], lc[e]
            row_edge = er in (0, ny - 1)
            span = max(3, int(math.ceil(0.5 * float(g.W[u]) / self.dx)) + 1)
            cand = [(er, ec + k) if row_edge else (er + k, ec) for k in range(-span, span + 1)]
            cand = [p for p in cand if 0 <= p[0] < ny and 0 <= p[1] < nx and self.inside[p]
                    and z[p] <= z[er, ec] + SPREAD_DZ]
            q = q_series[:, g.src[u]].astype(np.float64) * float(g.scale[u])
            for p in cand:
                cells.append(p[0] * nx + p[1])
                cols.append(q / len(cand))
                entry_cells.append(p[0] * nx + p[1])
            lon, lat = to_ll.transform(*(self.transform * (ec + 0.5, er + 0.5)))
            info.append(dict(kind="river entering the area", lat=round(lat, 5), lon=round(lon, 5),
                             drainage_km2=round(float(g.area_km2[u]), 3),
                             peak_m3s=round(float(q.max()), 3) if q.size else 0.0,
                             cells=len(cand)))
        self.n_entering = len(info)
        self.entry_cells = np.asarray(entry_cells, dtype=np.int64)

        # Local inflow, routed river cell by routed river cell.
        lat = arrays.get("lat_series")
        if lat is None:
            raise RuntimeError(
                "This run's flood-map data were saved by an older MRRpy without the local "
                "inflow the 2D simulation needs. Route the run again (MRRpy run -c run.yaml).")
        ri = arrays["river_idx"].astype(np.int64)
        ctr = Affine(*meta["transform"])
        cx, cy = ctr * (arrays["s_cols"][ri] + 0.5, arrays["s_rows"][ri] + 0.5)
        fc, fr = ~self.transform * (np.asarray(cx), np.asarray(cy))
        fr, fc = np.floor(fr).astype(np.int64), np.floor(fc).astype(np.int64)
        inside_c = (fr >= 0) & (fr < ny) & (fc >= 0) & (fc < nx)
        k_in = np.flatnonzero(inside_c & (lat.max(axis=0) > 0)) if lat.shape[0] else np.zeros(0, int)
        riv_in = np.flatnonzero(river_all & inwin)
        mine = np.flatnonzero(flow & inwin)
        by_src = {}
        for i in mine:
            by_src.setdefault(int(g.src[i]), []).append(i)
        tree = cKDTree(np.column_stack([lr[riv_in], lc[riv_in]])) if riv_in.size else None
        for k in k_in:
            targets = by_src.get(int(k))
            if targets:
                pts = [(lr[i], lc[i]) for i in targets]
            elif tree is not None:
                j = tree.query((fr[k], fc[k]))[1]
                pts = [(lr[riv_in[j]], lc[riv_in[j]])]
            elif self.inside[fr[k], fc[k]]:
                pts = [(fr[k], fc[k])]
            else:
                continue
            q = lat[:, k].astype(np.float64)
            for p in pts:
                cells.append(p[0] * nx + p[1])
                cols.append(q / len(pts))
        if k_in.size:
            q_loc = lat[:, k_in].astype(np.float64).sum(axis=1)
            info.append(dict(kind="local inflow (land inside the area)", lat=None, lon=None,
                             drainage_km2=None, peak_m3s=round(float(q_loc.max()), 3),
                             cells=int(k_in.size)))
        if not cells:
            raise ValueError("No river of the model runs into or through the flood-map area "
                             "(INUNDATION_AREA); choose an area on a river of the modelled basin.")
        self.src_cells = np.asarray(cells, dtype=np.int64)
        self.src_q = (np.column_stack(cols) if self.times.size
                      else np.zeros((0, len(cells))))           # (T, k) m³/s
        self.inflows = info

    # ── water out ────────────────────────────────────────────────────────────
    def _outflow(self, river_all):
        """Normal-depth outflow (with the reach slope) at every edge cell where
        the ground slopes out of the box, and across the valley floor beside
        every river that leaves it (within OUTFLOW_SPAN_M along the edge and
        OUTFLOW_DZ above the river: the floodplain there drains sideways to the
        river, not out).  Edge cells a river flows into from outside, and the
        cells an entering river is spread over, stay walls, so its water is
        never drained again at once.  Water leaves only
        where it is: a dry cell lets nothing out."""
        g, (ny, nx), inwin, lr, lc = self.grid, self.shape, self.inwin, self.lr, self.lc
        z = self.z

        def side_of(i):
            d = g.ds[i]
            r, c = int(lr[i]), int(lc[i])
            if d < 0:                                    # the end of the DEM
                return _edge_side(r, c, ny, nx)
            dr, dc = g.rows[d] - g.rows[i], g.cols[d] - g.cols[i]
            return ("S" if r + dr >= ny else "N" if r + dr < 0 else
                    "E" if c + dc >= nx else "W" if c + dc < 0 else None)

        # where rivers come in from outside (a hillside trickle does not count)
        fed = np.zeros((ny, nx), dtype=bool)
        src = np.flatnonzero(river_all & ~inwin & (g.ds >= 0))
        tgt = g.ds[src]
        tgt = tgt[inwin[tgt]]
        fed[lr[tgt], lc[tgt]] = True
        for k in self.entry_cells:
            fed[divmod(int(k), nx)] = True

        out = {}
        on_edge = inwin & ((lr == 0) | (lr == ny - 1) | (lc == 0) | (lc == nx - 1))
        cand = np.flatnonzero(on_edge)
        cand = cand[(g.ds[cand] < 0) | ~inwin[np.maximum(g.ds[cand], 0)]]
        for i in cand:                                   # the ground slopes out here
            side = side_of(i)
            if side is not None:
                out[(int(lr[i]), int(lc[i]), side)] = float(max(g.slope_reach[i], 1e-4))
        self.ends_inside = 0
        exits = np.flatnonzero(river_all & inwin & ((g.ds < 0) | ~inwin[np.maximum(g.ds, 0)]))
        span = int(round(OUTFLOW_SPAN_M / self.dx))
        for i in exits:                                  # the valley floor beside a river leaving
            side = side_of(i)
            if side is None:                             # a river ending inside the box
                self.ends_inside += 1
                continue
            r, c = int(lr[i]), int(lc[i])
            s = float(max(g.slope_reach[i], 1e-4))
            top = z[r, c] + OUTFLOW_DZ
            for k in range(-span, span + 1):
                p = (r, c + k) if side in "NS" else (r + k, c)
                if 0 <= p[0] < ny and 0 <= p[1] < nx and self.inside[p] and z[p] <= top:
                    key = (int(p[0]), int(p[1]), side)
                    out[key] = max(out.get(key, 0.0), s)
        self.outflow = [(r, c, side, s) for (r, c, side), s in sorted(out.items())
                        if self.inside[r, c] and not fed[r, c]]

    # ── when ─────────────────────────────────────────────────────────────────
    def flood_window(self):
        """(start, end, peak) [s since the run start] around the largest flood
        entering the box."""
        t = self.times
        if not t.size:
            raise RuntimeError("No flows over time were saved for this run, so the 2D "
                               "simulation has nothing to run on. Route it again.")
        q = self.src_q.sum(axis=1)
        i_pk = int(np.argmax(q))
        thr = q.min() + RISE_FRACTION * (q[i_pk] - q.min())
        below = np.flatnonzero(q < thr)
        before, after = below[below <= i_pk], below[below >= i_pk]
        i0 = int(before[-1]) if before.size else 0
        i1 = int(after[0]) if after.size else t.size - 1
        t0, t1 = max(t[i0] - PAD_S, t[0]), min(t[i1] + PAD_S, t[-1])
        if t1 - t0 > MAX_WINDOW_S:
            t0 = max(t0, t[i_pk] - 0.5 * MAX_WINDOW_S)
            t1 = min(t1, t0 + MAX_WINDOW_S)
        return float(t0), float(t1), float(t[i_pk])

    def source_slice(self, t0, t1):
        """Source records covering [t0, t1]."""
        t = self.times
        j0 = max(int(np.searchsorted(t, t0, side="right")) - 1, 0)
        j1 = min(int(np.searchsorted(t, t1, side="left")) + 1, t.size)
        return t[j0:j1], self.src_q[j0:j1]

    def edge_pools(self, depth_max):
        """Where deep water stood against a wall edge of the box, which held it
        back: [(lat, lon, deepest m)] for up to three stretches, deepest first."""
        from pyproj import Transformer
        from scipy import ndimage
        ny, nx = self.shape
        wall = np.zeros((ny, nx), dtype=bool)
        wall[[0, -1], :] = True
        wall[:, [0, -1]] = True
        for r, c, _side, _s in self.outflow:
            wall[r, c] = False
        for k in self.src_cells:                   # water put in at the edge is not held back
            r, c = divmod(int(k), nx)
            wall[max(r - 2, 0):r + 3, max(c - 2, 0):c + 3] = False
        hit = wall & self.inside & (depth_max >= EDGE_DEPTH_M)
        lab, n_lab = ndimage.label(hit, structure=np.ones((3, 3)))
        if not n_lab:
            return []
        to_ll = Transformer.from_crs(self.grid.crs, "EPSG:4326", always_xy=True)
        found = []
        for k in range(1, n_lab + 1):
            rr, cc = np.nonzero(lab == k)
            j = int(np.argmax(depth_max[rr, cc]))
            lon, lat = to_ll.transform(*(self.transform * (cc[j] + 0.5, rr[j] + 0.5)))
            found.append((round(lat, 4), round(lon, 4), round(float(depth_max[rr[j], cc[j]]), 2)))
        return sorted(found, key=lambda v: -v[2])[:3]


# ── The 2D flood maps ────────────────────────────────────────────────────────
def _hours(t):
    return f"{t / 3600.0:.1f} h"


def make_2d_flood_maps(cfg, arrays, meta, grid, out_dir, log=print):
    """Simulate the largest flood in 2D over the area and write the maps;
    returns {name: path}."""
    import pandas as pd
    from .solver2d import Flood2D

    area = getattr(cfg, "INUNDATION_AREA", None)
    w0 = _time.time()
    box = Box(grid, arrays, meta, area, mannings_n=float(getattr(cfg, "MANNINGS_N", 0.05)))
    ny, nx = box.shape
    dx = box.dx
    log(f"  Flood maps     |  2D simulation on {grid.label}: {nx} × {ny} cells "
        f"({ny * nx * dx * dx / 1e6:.1f} km²); {box.n_entering} river(s) flow in, "
        f"{len(box.outflow)} edge cells let water out")
    if box.ends_inside:
        log(f"  [WARN] {box.ends_inside} river(s) end inside the area (the DEM stops there); "
            "water collects at their ends.")

    t0, t1, t_pk = box.flood_window()
    t_src, q_src = box.source_slice(t0, t1)
    q_start = np.array([np.interp(t0, t_src, q_src[:, k]) for k in range(q_src.shape[1])]) \
        if t_src.size else np.zeros(q_src.shape[1])
    model = Flood2D(box.z, box.n, dx, t0=t0 - SPINUP_MAX_S)
    model.set_outflow(box.outflow)

    # Fill the rivers with the starting flow until they run steady.
    spin = 0.0
    if q_start.sum() > 0:
        model.set_sources(box.src_cells, np.array([0.0]), q_start[None, :])
        steady = 0
        while model.t < t0 - 1e-6:
            v_in, v_out = model.v_in, model.v_out
            model.run_until(min(model.t + 3600.0, t0))
            d_in, d_out = model.v_in - v_in, model.v_out - v_out
            steady = steady + 1 if d_in > 0 and abs(d_out - d_in) <= 0.02 * d_in else 0
            if steady >= 2:
                break
        spin = model.t - (t0 - SPINUP_MAX_S)
    model.start_record(t0)
    model.set_sources(box.src_cells, t_src, q_src)
    log(f"  Flood maps     |  simulating hours {t0 / 3600:.1f}–{t1 / 3600:.1f} of the run, "
        f"around the largest flood entering the area (peak inflow at {_hours(t_pk)})"
        + (f"; the rivers were first filled for {spin / 3600:.1f} h" if spin else ""))

    # Run, keeping the depth at the output times (for plots and the animation).
    rec = box.times[(box.times > t0) & (box.times <= t1)]
    n_keep = max(24, int(FRAME_BYTES // max(ny * nx * 2, 1)))
    rec = rec[::max(1, int(math.ceil(rec.size / n_keep)))]
    frames, frame_t = [], []
    next_note = _time.time() + 60.0
    for k, tf in enumerate(rec):
        model.run_until(tf)
        frames.append(model.h.astype(np.float16).ravel())
        frame_t.append(model.t)
        if _time.time() > next_note:
            log(f"  Flood maps     |  2D: {100.0 * (tf - t0) / max(t1 - t0, 1.0):.0f} % "
                f"({_time.time() - w0:.0f} s)")
            next_note = _time.time() + 60.0
    model.run_until(t1)
    wall_s = _time.time() - w0

    # Maps
    rows, cols = np.divmod(np.arange(ny * nx), nx)
    inside = box.inside.ravel()
    bg = FloodGrid(label=f"{grid.label} (2D)", fine=getattr(grid, "fine", False), nrows=ny,
                   ncols=nx, transform=box.transform, crs=grid.crs, cell_size=dx, rows=rows,
                   cols=cols, inside=inside, z=box.ground.ravel(), z_raw=box.ground.ravel())
    depth = np.where(inside, model.h_max.ravel(), 0.0)
    out, win, sel, wet = write_flood_maps(bg, out_dir, None, depth, model.t_max.ravel(),
                                          model.first_wet.ravel(), model.wet_time.ravel() / 3600.0)
    p = lambda name: os.path.join(out_dir, name)
    for stale in ("hand.tif", "reaches.csv", "reaches.geojson", "rating_curves.csv"):
        if os.path.exists(p(stale)):                  # left by an earlier HAND run
            os.remove(p(stale))
    speed = model.v_max.ravel()
    out["flood_velocity_max"] = _write_tif(
        p("flood_velocity_max.tif"), _to_grid(np.where(wet & (speed > 0), speed, np.nan), bg, sel, win),
        bg, win)
    out["inflows_csv"] = p("inflows.csv")
    pd.DataFrame(box.inflows).to_csv(out["inflows_csv"], index=False)

    # Data for plots and the animation (mapping.SavedFlood)
    smeta = dict(label=bg.label, nrows=ny, ncols=nx, transform=list(box.transform)[:6],
                 crs=grid.crs, cell_size=dx, n_levels=0, method="2d",
                 dt_series_s=float(np.median(np.diff(frame_t))) if len(frame_t) > 1 else 0.0,
                 hydrograph_csv=meta.get("hydrograph_csv"))
    out["flood_model"] = p("flood_model.npz")
    np.savez_compressed(
        out["flood_model"], meta_json=np.array(json.dumps(smeta)), rows=rows.astype(np.int32),
        cols=cols.astype(np.int32), z=box.ground.ravel().astype(np.float32), inside=inside,
        river=box.river.ravel(), times_s=np.asarray(frame_t, dtype=np.float64),
        frames=(np.stack(frames) if frames else np.zeros((0, ny * nx), np.float16)),
        depth_max=depth.astype(np.float32), time_of_max_s=model.t_max.ravel().astype(np.float32))

    # Summary
    pools = box.edge_pools(model.h_max)
    in_area = sel & wet
    summ = dict(
        method="2d", grid=bg.label, cell_size_m=dx, cells=int(ny * nx),
        area_km2=round(ny * nx * dx * dx / 1e6, 3),
        flooded_km2=float(in_area.sum() * dx * dx / 1e6),
        max_depth_m=float(depth[in_area].max()) if in_area.any() else 0.0,
        max_speed_m_s=float(speed[in_area].max()) if in_area.any() else 0.0,
        simulated_hours=[round(t0 / 3600.0, 2), round(t1 / 3600.0, 2)],
        rivers_filled_hours=round(spin / 3600.0, 2),
        rivers_entering=box.n_entering, outflow_edge_cells=len(box.outflow),
        water_in_hm3=model.v_in / 1e6, water_out_hm3=model.v_out / 1e6,
        water_balance_error=model.mass_error(), steps=model.steps, seconds=round(wall_s, 1),
        water_against_edge=[dict(lat=a, lon=b, depth_m=d) for a, b, d in pools],
        area_bbox=list(area) if area else None,
        discharge_transfer=getattr(grid, "match", None),
    )
    out["summary_json"] = p("inundation_summary.json")
    with open(out["summary_json"], "w") as f:
        json.dump(summ, f, indent=2)
    log(f"  Flood maps     |  2D done in {wall_s:.0f} s ({model.steps:,} steps, water balance "
        f"error {abs(summ['water_balance_error']):.0e}): {summ['flooded_km2']:.2f} km² under "
        f"water (rivers included), deepest {summ['max_depth_m']:.2f} m, fastest "
        f"{summ['max_speed_m_s']:.1f} m/s.")
    if pools:
        where = "; ".join(f"{_latlon(a, b)} ({d:.1f} m deep)" for a, b, d in pools)
        log(f"  [WARN] The flood reached the edge of the area, which held it back like a wall "
            f"(near {where}). Make INUNDATION_AREA larger there.")
    return out


def _latlon(lat, lon):
    return (f"{abs(lat):.4f} {'N' if lat >= 0 else 'S'}, "
            f"{abs(lon):.4f} {'E' if lon >= 0 else 'W'}")
