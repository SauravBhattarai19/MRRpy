"""Data for Chapter 7 (HAND) of the study course, made with MRRpy's own code.

    ~/.conda/envs/mrrpy/bin/python study/scripts/export_ch7.py

Writes
  src/data/ch7/valley.json   synthetic valley with a tributary (the guide's valley)
  src/data/ch7/gorge.json    9 km valley with a gorge + MRRpy 2D depth frames
  scripts/fixtures/ch7_expected.json
                             what MRRpy computes on the valley; the browser code
                             (src/lib/flood) is checked against it by
                             scripts/check_flood_lib.mjs

Elevations are rounded to whole centimetres *before* MRRpy runs, so the browser
sees exactly the DEM the expected answers were computed on.
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
REPO = os.path.dirname(STUDY)
sys.path.insert(0, REPO)
os.environ.setdefault("NUMBA_NUM_THREADS", "8")

import numpy as np
from scipy.ndimage import gaussian_filter

from MRRpy.core.inundation import network as N
from MRRpy.core.inundation.mapping import FloodGrid, FloodModel
from MRRpy.core.inundation.solver2d import Flood2D
from MRRpy.core.routing.surface import reach_slope

DATA = os.path.join(STUDY, "src", "data", "ch7")
FIX = os.path.join(HERE, "fixtures")


def smooth_noise(shape, sigma, amp, seed=0):
    rng = np.random.default_rng(seed)
    n = gaussian_filter(rng.standard_normal(shape), sigma)
    return amp * n / max(np.abs(n).max(), 1e-12)


def b64(arr, dtype):
    return base64.b64encode(np.ascontiguousarray(arr, dtype=dtype).tobytes()).decode()


def width_rule(a):
    return 7.2 * (0.6 * a) ** 0.5


def synth_grid(dem, dx, a_channel_km2, outlets, n_fp=0.06, n_ch=0.035, extra_km2=None,
               reach_m=1000.0, s_floor=1e-4):
    """FloodGrid on a fully valid synthetic DEM (as finegrid.dem_flood_grid does)."""
    dem = np.asarray(dem, dtype=np.float64)
    H, W_ = dem.shape
    valid = np.ones(dem.shape, dtype=bool)
    no_outlet = np.zeros_like(valid)
    no_outlet[0, :] = no_outlet[-1, :] = no_outlet[:, 0] = no_outlet[:, -1] = True
    for r, c in outlets:
        no_outlet[r, c] = False
    d8 = N.least_cost_d8(dem, valid, no_outlet)
    ds, dist = N.downstream_from_d8(d8, valid, dx)
    order = N.downstream_first_order(ds)
    n = H * W_
    rows, cols = np.divmod(np.arange(n), W_)
    z_raw = dem.ravel()
    z = N.river_bed_profile(order, ds, np.ones(n, dtype=bool), z_raw)
    extra = np.zeros(n)
    for (r, c), a in (extra_km2 or {}).items():
        extra[r * W_ + c] += a
    area = N.upstream_area(order, ds, dx * dx / 1e6, extra)
    river = area >= a_channel_km2
    slope_loc = np.where(ds >= 0, (z - z[np.maximum(ds, 0)]) / dist, s_floor)
    s_reach = reach_slope(dict(ds_idx=ds, dem_1d=z, dist_1d=dist, cell_size=dx, faccum_1d=area,
                               slope_1d=np.maximum(slope_loc, s_floor)), reach_m, s_floor)
    Wc = np.where(river, width_rule(area), 0.0)
    src = np.full(n, -1, dtype=np.int64)
    src[river] = np.arange(int(river.sum()))
    from affine import Affine
    g = FloodGrid(label="synthetic", fine=False, nrows=H, ncols=W_,
                  transform=Affine(dx, 0, 0, 0, -dx, H * dx), crs="EPSG:32645", cell_size=dx,
                  rows=rows, cols=cols, ds=ds, order=order, z=z, z_raw=z_raw, dist=dist,
                  area_km2=area, slope_reach=s_reach, n_fp=np.full(n, n_fp), river=river,
                  W=Wc, n_ch=np.full(n, n_ch), src=src, scale=np.ones(n),
                  inside=np.ones(n, dtype=bool), match=None)
    g.d8 = d8.ravel()
    return g


def flood(g, q_river, a_ch, q_series=None, times=None):
    nr = int(g.river.sum())
    if q_series is None:
        q_series, times = np.asarray(q_river, dtype=np.float32)[None, :], np.array([3600.0])
    arrays = dict(river_idx=np.arange(nr), q_peak=np.asarray(q_river, dtype=np.float64),
                  t_peak_s=np.zeros(nr), times_s=np.asarray(times, dtype=np.float64),
                  q_series=np.asarray(q_series, dtype=np.float32))
    meta = dict(a_channel_km2=a_ch, output_interval_s=float(times[1] - times[0])
                if len(times) > 1 else 3600.0, series_stride=1)
    return FloodModel(g, arrays, meta)


# ── the guide's valley with a tributary ──────────────────────────────────────
def valley_dem(ny=200, nx=134, dx=30.0, seed=1):
    r, c = np.mgrid[0:ny, 0:nx]
    y, x = r * dx, c * dx
    xc = 2000 + 350 * np.sin(2 * np.pi * y / 2600)
    d = np.abs(x - xc)
    base = 1300 - 0.0015 * y
    fp = 350.0
    z = base + np.where(d < fp, 0.004 * d, 0.004 * fp + 0.15 * (d - fp))
    yJ = 3600.0
    xJ = 2000 + 350 * np.sin(2 * np.pi * yJ / 2600)
    u = np.array([1.0, -0.8]) / np.hypot(1.0, 0.8)
    px, py = x - xJ, y - yJ
    s = px * u[0] + py * u[1]
    p = np.abs(px * u[1] - py * u[0])
    zt = (1300 - 0.0015 * yJ) + 0.006 * np.maximum(s, 0) + np.where(
        p < 120, 0.01 * p, 1.2 + 0.18 * (p - 120))
    use = (s > -50) & (zt < z)
    z = np.where(use, zt, z)
    dmin = np.where(use, p * fp / 120.0, d)
    hills = np.clip((dmin - fp) / 300.0, 0, 1)
    z = z + hills * smooth_noise(z.shape, 4.0, 14.0, seed + 10) + smooth_noise(z.shape, 1.5, 0.3, seed)
    return z, (ny - 1, int(np.argmin(z[-1]))), (0, int(np.argmin(z[0])))


def export_valley():
    dx, a_ch, a_enter, q_spec = 30.0, 0.8, 400.0, 1.0
    z, outlet, entry = valley_dem()
    z = np.round(z * 100) / 100
    zmin = float(z.min())
    g = synth_grid(z, dx, a_ch, [outlet], extra_km2={entry: a_enter})
    q = q_spec * g.area_km2[g.river]
    fm = flood(g, q, a_ch)
    depth, _ = fm.depth_peak()
    ny, nx = z.shape
    json.dump(dict(ny=ny, nx=nx, dx=dx, zmin=zmin, z_cm=b64(np.rint((z - zmin) * 100), "<i4"),
                   outlet=outlet, entry=entry, aEnterKm2=a_enter, aChannelKm2=a_ch,
                   qSpecific=q_spec, nFloodplain=0.06, nChannel=0.035),
              open(os.path.join(DATA, "valley.json"), "w"))
    levels = []
    for lev in fm.levels:
        levels.append(dict(threshold=lev.threshold_km2, hand=np.round(np.nan_to_num(lev.hand, nan=-1), 4).tolist(),
                           cellReach=lev.cell_reach.tolist(), nReach=int(lev.n_reach),
                           L=lev.L.tolist(), S=lev.S.tolist(), W=lev.W.tolist(),
                           qPeak=lev.q_peak.tolist(), stagePeak=lev.stage_peak.tolist(),
                           y=lev.y.tolist(), Q=lev.Q.tolist()))
    json.dump(dict(d8=g.d8.astype(int).tolist(), area=np.round(g.area_km2, 6).tolist(),
                   slopeReach=g.slope_reach.tolist(), levels=levels,
                   depth=np.round(depth, 4).tolist()),
              open(os.path.join(FIX, "ch7_expected.json"), "w"))
    main = fm.levels[0]
    print(f"valley {ny}x{nx}: {int(g.river.sum())} river cells, {len(fm.levels)} levels, "
          f"{main.n_reach} reaches; flooded {(depth >= 0.01).sum() * dx * dx / 1e6:.2f} km²")


# ── the gorge experiment (HAND vs MRRpy's 2D) ────────────────────────────────
G_DX, G_NY, G_NX, G_SV, G_X0, G_ATOP = 30.0, 300, 90, 1e-3, 1350.0, 700.0


def inflow(t):
    t = np.asarray(t, dtype=float)
    return 60.0 + 840.0 * np.exp(-((t - 12 * 3600.0) / (5 * 3600.0)) ** 2)


def gorge_dem():
    r, c = np.mgrid[0:G_NY, 0:G_NX]
    y, x = (r + 0.5) * G_DX, (c + 0.5) * G_DX
    d = np.abs(x - G_X0)
    yy = (np.arange(G_NY) + 0.5) * G_DX
    B = (520.0 - 475.0 * np.clip(np.minimum((yy - 5700) / 300, (6900 - yy) / 300), 0, 1))[:, None]
    z = 1000.0 - G_SV * y + np.where(d < B, 0.005 * d, 0.005 * B + 0.22 * (d - B))
    z = z + np.clip((d - B) / 200, 0, 1) * smooth_noise(z.shape, 3.0, 6.0, 11)
    z = z + smooth_noise(z.shape, 1.2, 0.12, 12)
    z = np.where(np.abs(x - G_X0) < G_DX / 2, z - 0.8, z)
    return z


def export_gorge():
    z = np.round(gorge_dem() * 100) / 100
    c_r = int(G_X0 // G_DX)
    g = synth_grid(z, G_DX, 1.0, [(G_NY - 1, c_r)], extra_km2={(0, c_r): G_ATOP})
    times = np.arange(0.0, 36 * 3600.0 + 1, 1800.0)
    q_in = inflow(times)
    q_series = (q_in[:, None] * (g.area_km2[g.river] / G_ATOP)[None, :]).astype(np.float32)
    fm = flood(g, q_series.max(axis=0), 1.0, q_series=q_series, times=times)
    hand_max, _ = fm.depth_peak()

    bed = N.graded_river_bed(g.order, g.ds, g.dist, g.river, g.z_raw, g.slope_reach)
    z2 = np.where(g.river, bed, g.z_raw).reshape(z.shape)
    riv2 = g.river.reshape(z.shape)
    m = Flood2D(z2, np.where(riv2, 0.035, 0.06), G_DX, t0=-12 * 3600.0, threads=8)
    src = np.array([c_r - 1, c_r, c_r + 1])
    top = z2[G_NY - 1, c_r] + 20.0
    m.set_outflow([(G_NY - 1, c, "S", G_SV) for c in range(G_NX) if z2[G_NY - 1, c] <= top])
    m.set_sources(src, np.array([0.0]), np.full((1, 3), inflow(0.0) / 3))
    m.run_until(0.0)
    m.start_record(0.0)
    m.set_sources(src, times, np.repeat(q_in[:, None] / 3, 3, axis=1))
    frames2d, framesH = [], []
    for k, t in enumerate(times):
        if t > 0:
            m.run_until(t)
        frames2d.append(m.h.copy())
        d = np.zeros(g.n)
        for lev in fm.levels:
            s = lev.stage_series[k].astype(float)
            st = np.where(lev.cell_reach >= 0, s[np.maximum(lev.cell_reach, 0)], 0.0)
            d = np.maximum(d, np.where(lev.cell_reach >= 0, st - lev.hand, 0.0))
        framesH.append(d.reshape(z.shape))
    h2max = m.h_max.copy()
    hHmax = hand_max.reshape(z.shape)
    wet = (h2max >= 0.01) | (hHmax >= 0.01)
    cols = np.flatnonzero(wet.any(axis=0))
    c0, c1 = max(cols.min() - 4, 0), min(cols.max() + 5, G_NX)
    q = lambda a: np.clip(np.rint(np.asarray(a)[:, c0:c1] / 0.04), 0, 255)   # 4 cm steps
    zc = z[:, c0:c1]
    zmin = float(zc.min())
    json.dump(dict(ny=G_NY, nx=int(c1 - c0), dx=G_DX, col0=int(c0), riverCol=int(c_r - c0),
                   zmin=zmin, z_cm=b64(np.rint((zc - zmin) * 100), "<i4"),
                   bed2d_cm=b64(np.rint((z2[:, c_r] - zmin) * 100), "<i4"),
                   valleyGradient=G_SV, gorgeKm=[6.0, 6.6], timesH=(times / 3600).tolist(),
                   inflow=np.round(q_in, 1).tolist(), depthStepM=0.04,
                   frameTimesH=(times[::2] / 3600).tolist(),
                   hand=b64(np.stack([q(f) for f in framesH[::2]]), "u1"),
                   twoD=b64(np.stack([q(f) for f in frames2d[::2]]), "u1"),
                   handMax=b64(q(hHmax), "u1"), twoDMax=b64(q(h2max), "u1"),
                   floodedKm2=dict(hand=float((hHmax >= 0.01).sum() * G_DX ** 2 / 1e6),
                                   twoD=float((h2max >= 0.01).sum() * G_DX ** 2 / 1e6)),
                   massError=float(m.mass_error())),
              open(os.path.join(DATA, "gorge.json"), "w"))
    print(f"gorge: cols {c0}..{c1}, {len(times)} frames, flooded HAND "
          f"{(hHmax >= 0.01).sum() * G_DX ** 2 / 1e6:.2f} km², 2D {(h2max >= 0.01).sum() * G_DX ** 2 / 1e6:.2f} km²")


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(FIX, exist_ok=True)
    export_valley()
    export_gorge()
