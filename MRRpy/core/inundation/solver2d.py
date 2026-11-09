# -*- coding: utf-8 -*-
"""
solver2d.py — 2D flood flow on a raster (local-inertial shallow water).

The local-inertial equations of Bates et al. (2010, J. Hydrol. 387, 33–45),
explicit, on a regular grid.  For every cell face

    q_new = (q − g h_f Δt ∂η/∂x) / (1 + g Δt n² |q| / h_f^(7/3))

q: discharge per unit width [m²/s]; η = z + h the water level; h_f the depth
of water able to cross the face (higher water level minus higher ground);
n: Manning's n (mean of the two cells).  Continuity: ∂h/∂t = −∇·q + sources.

* Time step Δt = α Δx / √(g h_max) (α = 0.5), never longer than dt_max.  In 2D
  the scheme's checkerboard mode is only just stable at α ≈ 0.707; at the usual
  α = 0.7 a 15 m-deep fast river (the Pearl at Jackson) blew up into metre-high
  sloshing once the run was stopped every 10 minutes to save maps, while
  α = 0.5 gave the uninterrupted α = 0.7 answer to 1e-6 m
  (TestCases/flood_zoom_us/runs/pearl_alpha).
* Plain q (θ = 1).  The q-centring of de Almeida et al. (2012) averages each
  face with its neighbours in the same direction; in a river one cell wide
  that zig-zags between x- and y-faces those are mostly dry walls, which made
  a steady river twice as deep (TestCases/flood_zoom_nakhu).
* A cell never gives more water than it holds: its outgoing fluxes are scaled
  down when they would (exact mass balance, depth ≥ 0).
* |q| is capped at Froude number fr_max where the water at the face is at
  least fr_hmin deep (local-inertial is a subcritical model; the cap keeps
  deep, steep flow stable and leaves thin wetting fronts free).
* Sources: Q(t) [m³/s] added to listed cells, linear in time between records.
* Outflow cells on the box edge drain at normal depth over a given slope;
  every other edge is a wall.

The whole time loop runs compiled (numba), rows in parallel; along the way it
keeps per cell the deepest water and its time, the fastest flow, the first
time deeper than ``h_wet`` and the time spent deeper than it.

Arrays are (ny, nx), row 0 at the top (north).  qx is (ny, nx+1): positive
toward +x (east); qy is (ny+1, nx): positive toward +row (south).
"""

import math

import numpy as np

try:
    import numba
    from numba import njit, prange
except Exception:                                 # pragma: no cover
    numba = None

G = 9.81


def _need_numba():
    if numba is None:
        raise ImportError("The 2D flood simulation needs numba (pip install numba).")


if numba is not None:
    @njit(cache=True, parallel=True)
    def _fluxes(z, h, n, qx, qy, qxn, qyn, dt, dx, h_dry, fr_max, fr_hmin):
        ny, nx = h.shape
        for r in prange(ny):               # x-faces between (r, c-1) and (r, c)
            for c in range(1, nx):
                zl = z[r, c - 1]
                zr = z[r, c]
                el = zl + h[r, c - 1]
                er = zr + h[r, c]
                hf = max(el, er) - max(zl, zr)
                if hf <= h_dry:
                    qxn[r, c] = 0.0
                    continue
                q0 = qx[r, c]
                nf = 0.5 * (n[r, c - 1] + n[r, c])
                q = (q0 - G * hf * dt * (er - el) / dx) / (
                    1.0 + G * dt * nf * nf * abs(q0) / hf ** (7.0 / 3.0))
                if hf >= fr_hmin:
                    qmax = fr_max * hf * math.sqrt(G * hf)
                    if q > qmax:
                        q = qmax
                    elif q < -qmax:
                        q = -qmax
                qxn[r, c] = q
        for r in prange(1, ny):            # y-faces between (r-1, c) and (r, c)
            for c in range(nx):
                zu = z[r - 1, c]
                zd = z[r, c]
                eu = zu + h[r - 1, c]
                ed = zd + h[r, c]
                hf = max(eu, ed) - max(zu, zd)
                if hf <= h_dry:
                    qyn[r, c] = 0.0
                    continue
                q0 = qy[r, c]
                nf = 0.5 * (n[r - 1, c] + n[r, c])
                q = (q0 - G * hf * dt * (ed - eu) / dx) / (
                    1.0 + G * dt * nf * nf * abs(q0) / hf ** (7.0 / 3.0))
                if hf >= fr_hmin:
                    qmax = fr_max * hf * math.sqrt(G * hf)
                    if q > qmax:
                        q = qmax
                    elif q < -qmax:
                        q = -qmax
                qyn[r, c] = q

    @njit(cache=True)
    def _edges(h, n, qxn, qyn, out_r, out_c, out_side, out_slope, h_dry):
        """Walls everywhere on the box edge except the outflow cells, which
        drain at normal depth through their edge face."""
        ny, nx = h.shape
        for r in range(ny):
            qxn[r, 0] = 0.0
            qxn[r, nx] = 0.0
        for c in range(nx):
            qyn[0, c] = 0.0
            qyn[ny, c] = 0.0
        for k in range(out_r.shape[0]):
            r = out_r[k]
            c = out_c[k]
            hh = h[r, c]
            q = 0.0
            if hh > h_dry:
                q = hh ** (5.0 / 3.0) * math.sqrt(out_slope[k]) / n[r, c]
            s = out_side[k]                # 0 north, 1 south, 2 west, 3 east
            if s == 0:
                qyn[0, c] = -q
            elif s == 1:
                qyn[ny, c] = q
            elif s == 2:
                qxn[r, 0] = -q
            else:
                qxn[r, nx] = q

    @njit(cache=True, parallel=True)
    def _update(h, qxn, qyn, f, rowmax, dt, dx, t_new, h_wet, h_max, t_max, v_max,
                first_wet, wet_time):
        """Scale fluxes so no cell gives more than it holds, update the depth,
        keep the per-cell records.  Returns the volume that left through the
        edge faces."""
        ny, nx = h.shape
        for r in prange(ny):
            for c in range(nx):
                out = (max(qxn[r, c + 1], 0.0) + max(-qxn[r, c], 0.0)
                       + max(qyn[r + 1, c], 0.0) + max(-qyn[r, c], 0.0)) * dt * dx
                fr = 1.0
                if out > 0.0:
                    vol = h[r, c] * dx * dx
                    if out > vol:
                        fr = vol / out
                f[r, c] = fr
        for r in prange(ny):
            for c in range(nx + 1):
                q = qxn[r, c]
                if q > 0.0 and c > 0:
                    qxn[r, c] = q * f[r, c - 1]
                elif q < 0.0 and c < nx:
                    qxn[r, c] = q * f[r, c]
        for r in prange(ny + 1):
            for c in range(nx):
                q = qyn[r, c]
                if q > 0.0 and r > 0:
                    qyn[r, c] = q * f[r - 1, c]
                elif q < 0.0 and r < ny:
                    qyn[r, c] = q * f[r, c]
        a = dt / dx
        for r in prange(ny):
            m = 0.0
            for c in range(nx):
                hn = h[r, c] + a * (qxn[r, c] - qxn[r, c + 1] + qyn[r, c] - qyn[r + 1, c])
                if hn < 0.0:                   # round-off only
                    hn = 0.0
                h[r, c] = hn
                if hn > m:
                    m = hn
                if hn > h_max[r, c]:
                    h_max[r, c] = hn
                    t_max[r, c] = t_new
                if hn >= h_wet:
                    if not (first_wet[r, c] == first_wet[r, c]):     # still NaN
                        first_wet[r, c] = t_new
                    wet_time[r, c] += dt
                    ux = 0.5 * (qxn[r, c] + qxn[r, c + 1])
                    uy = 0.5 * (qyn[r, c] + qyn[r + 1, c])
                    v = math.sqrt(ux * ux + uy * uy) / hn
                    if v > v_max[r, c]:
                        v_max[r, c] = v
            rowmax[r] = m
        v_out = 0.0
        for r in range(ny):
            v_out += max(-qxn[r, 0], 0.0) + max(qxn[r, nx], 0.0)
        for c in range(nx):
            v_out += max(-qyn[0, c], 0.0) + max(qyn[ny, c], 0.0)
        return v_out * dt * dx

    @njit(cache=True)
    def _sources(h, src_r, src_c, src_t, src_q, t_mid, dt, dx):
        """Add the source flows at t_mid (linear between records); returns the
        volume added."""
        k_n = src_r.shape[0]
        if k_n == 0:
            return 0.0
        T = src_t.shape[0]
        i = 0
        w = 0.0
        if T > 1:
            if t_mid >= src_t[T - 1]:
                i = T - 2
                w = 1.0
            elif t_mid > src_t[0]:
                lo, hi = 0, T - 1                 # src_t[lo] <= t_mid < src_t[hi]
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if src_t[mid] <= t_mid:
                        lo = mid
                    else:
                        hi = mid
                i = lo
                w = (t_mid - src_t[lo]) / (src_t[hi] - src_t[lo])
        v = 0.0
        for k in range(k_n):
            q = src_q[i, k] if T == 1 else (1.0 - w) * src_q[i, k] + w * src_q[i + 1, k]
            if q > 0.0:
                h[src_r[k], src_c[k]] += q * dt / (dx * dx)
                v += q * dt
        return v

    @njit(cache=True)
    def _advance(z, n, h, qx, qy, qxn, qyn, f, rowmax, t, t_end, dx, alpha, h_dry, fr_max,
                 fr_hmin, dt_max, out_r, out_c, out_side, out_slope, src_r, src_c, src_t, src_q,
                 h_wet, h_max, t_max, v_max, first_wet, wet_time, acc):
        """Step from t to t_end.  acc: [volume in, volume out, steps, deepest
        water now, shortest step].  Returns the new time."""
        hmax = acc[3]
        swapped = False
        while t < t_end - 1e-9:
            dt = dt_max
            if hmax > h_dry:
                dt = min(dt_max, alpha * dx / math.sqrt(G * hmax))
            if t + dt > t_end:
                dt = t_end - t
            _fluxes(z, h, n, qx, qy, qxn, qyn, dt, dx, h_dry, fr_max, fr_hmin)
            _edges(h, n, qxn, qyn, out_r, out_c, out_side, out_slope, h_dry)
            t_new = t + dt
            acc[1] += _update(h, qxn, qyn, f, rowmax, dt, dx, t_new, h_wet, h_max, t_max, v_max,
                              first_wet, wet_time)
            acc[0] += _sources(h, src_r, src_c, src_t, src_q, t + 0.5 * dt, dt, dx)
            hmax = rowmax.max()
            for k in range(src_r.shape[0]):
                if h[src_r[k], src_c[k]] > hmax:
                    hmax = h[src_r[k], src_c[k]]
            qx, qxn = qxn, qx
            qy, qyn = qyn, qy
            swapped = not swapped
            t = t_new
            acc[2] += 1.0
            if dt < acc[4]:
                acc[4] = dt
        if swapped:                            # the caller's qx, qy hold the newest fluxes
            qxn[:, :] = qx
            qyn[:, :] = qy
        acc[3] = hmax
        return t


class Flood2D:
    """
    A raster flood model.  z, n: (ny, nx) ground [m] and Manning's n; dx the
    cell size [m]; t0 the start time [s].  Cells outside the area to simulate
    should be high walls in z.
    """

    def __init__(self, z, n, dx, t0=0.0, alpha=0.5, h_dry=1e-3, fr_max=1.5, fr_hmin=0.1,
                 dt_max=10.0, h_wet=0.1, h0=None, threads=None):
        _need_numba()
        self.z = np.ascontiguousarray(z, dtype=np.float64)
        self.n = np.ascontiguousarray(n, dtype=np.float64)
        self.dx = float(dx)
        ny, nx = self.z.shape
        self.h = np.zeros((ny, nx)) if h0 is None else np.array(h0, dtype=np.float64)
        self.qx = np.zeros((ny, nx + 1))
        self.qy = np.zeros((ny + 1, nx))
        self._qxn = np.zeros((ny, nx + 1))
        self._qyn = np.zeros((ny + 1, nx))
        self._f = np.ones((ny, nx))
        self._rowmax = np.zeros(ny)
        self.alpha, self.h_dry, self.h_wet = float(alpha), float(h_dry), float(h_wet)
        self.fr_max, self.fr_hmin, self.dt_max = float(fr_max), float(fr_hmin), float(dt_max)
        self.t = float(t0)
        self.v0 = self.volume()
        # [volume in, volume out, steps, deepest water now, shortest step]
        self._acc = np.array([0.0, 0.0, 0.0, float(self.h.max()), np.inf])
        # rows run in parallel; a few dozen threads saturate a grid of 10^5–10^6 cells
        self.threads = max(1, min(numba.config.NUMBA_NUM_THREADS,
                                  int(threads) if threads else max(1, min(32, z.size // 4000))))
        self.reset_records()
        self.set_outflow([])
        self.set_sources(np.zeros(0, np.int64), np.array([0.0]), np.zeros((1, 0)))

    # ── boundary conditions ────────────────────────────────────────────────
    def set_outflow(self, cells):
        """cells: list of (row, col, side, slope); side 'N', 'S', 'W' or 'E'."""
        sides = {"N": 0, "S": 1, "W": 2, "E": 3}
        self.out_r = np.array([c[0] for c in cells], dtype=np.int64)
        self.out_c = np.array([c[1] for c in cells], dtype=np.int64)
        self.out_side = np.array([sides[c[2]] for c in cells], dtype=np.int64)
        self.out_slope = np.array([max(float(c[3]), 1e-5) for c in cells], dtype=np.float64)

    def set_sources(self, flat_idx, times, q):
        """Point sources: flat cell indices (k,), times (T,) [s], q (T, k) [m³/s]."""
        idx = np.asarray(flat_idx, dtype=np.int64)
        nx = self.z.shape[1]
        self.src_r, self.src_c = idx // nx, idx % nx
        self.src_t = np.ascontiguousarray(times, dtype=np.float64)
        self.src_q = np.ascontiguousarray(np.asarray(q, dtype=np.float64).reshape(len(self.src_t),
                                                                                   idx.size))

    def reset_records(self):
        """Start the per-cell records (deepest water, …) afresh."""
        shape = self.z.shape
        self.h_max = self.h.copy()
        self.t_max = np.where(self.h > 0, self.t, np.nan)
        self.v_max = np.zeros(shape)
        self.first_wet = np.where(self.h >= self.h_wet, self.t, np.nan)
        self.wet_time = np.zeros(shape)

    def start_record(self, t):
        """After a spin-up: set the clock to t [s], keep the water, and start the
        records and the water balance afresh."""
        self.t = float(t)
        self.v0 = self.volume()
        self._acc[0] = self._acc[1] = 0.0
        self.reset_records()

    # ── time stepping ──────────────────────────────────────────────────────
    def run_until(self, t_end):
        """Advance to t_end [s]."""
        if t_end <= self.t:
            return
        import warnings
        before = numba.get_num_threads()
        numba.set_num_threads(self.threads)
        try:
            with warnings.catch_warnings():        # numba probing an old TBB: harmless
                warnings.filterwarnings("ignore", message=".*TBB.*")
                self.t = _advance(self.z, self.n, self.h, self.qx, self.qy, self._qxn,
                                  self._qyn, self._f, self._rowmax, self.t, float(t_end), self.dx,
                                  self.alpha, self.h_dry, self.fr_max, self.fr_hmin, self.dt_max,
                                  self.out_r, self.out_c, self.out_side, self.out_slope,
                                  self.src_r, self.src_c, self.src_t, self.src_q, self.h_wet,
                                  self.h_max, self.t_max, self.v_max, self.first_wet,
                                  self.wet_time, self._acc)
        finally:
            numba.set_num_threads(before)

    # ── diagnostics ────────────────────────────────────────────────────────
    @property
    def v_in(self):
        return float(self._acc[0])

    @property
    def v_out(self):
        return float(self._acc[1])

    @property
    def steps(self):
        return int(self._acc[2])

    @property
    def dt_min(self):
        return float(self._acc[4])

    def volume(self):
        return float(self.h.sum()) * self.dx ** 2

    def mass_error(self):
        """(storage change − (inflow − outflow)) / inflow."""
        d = (self.volume() - self.v0) - (self.v_in - self.v_out)
        return d / max(self.v_in, 1e-12)

    def source_rate(self, t):
        """Source flows (k,) [m³/s] at time t."""
        if not self.src_r.size:
            return np.zeros(0)
        return np.array([np.interp(t, self.src_t, self.src_q[:, k]) for k in range(self.src_r.size)])

    def speed(self):
        """Cell-centre speed |q|/h [m/s] now (0 where shallower than 1 cm)."""
        ux = 0.5 * (self.qx[:, :-1] + self.qx[:, 1:])
        uy = 0.5 * (self.qy[:-1, :] + self.qy[1:, :])
        return np.where(self.h > 0.01, np.hypot(ux, uy) / np.maximum(self.h, 0.01), 0.0)
