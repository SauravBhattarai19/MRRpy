# -*- coding: utf-8 -*-
"""
rating.py — synthetic rating curves (stage ↔ discharge) for HAND reaches.

Stage y is measured above the bank (the DEM surface at the river cell; the
model's channel bed lies its bankfull depth D below it).  For reach r:

    Q(y) = √S · [ K_slot(D + y)  +  (1/L) · Σ_{HAND_i < y} a_i · (y − HAND_i)^(5/3) / n_i ]

* K_slot is the model's own sub-grid channel (``hydraulics.compound_conveyance``
  with the floodplain width set to zero): slot of width W, walls up to the bank,
  channel n.
* The sum is the floodplain in strip (divided-channel) form: every cell that
  drains to the reach and lies below the water conveys a sheet of width a_i/L
  and depth y − HAND_i with its own Manning's n.  a_i is the cell's plan area
  minus the part the channel itself occupies.

With only the river cells in the sum this is exactly the model's compound
section (slot + one-cell floodplain); HAND adds the land beside the river.
"""

import numpy as np

from ..routing.hydraulics import compound_conveyance

try:
    from numba import njit as _njit
except Exception:                                 # pragma: no cover
    def _njit(*a, **k):
        return (lambda f: f) if not (a and callable(a[0])) else a[0]

DY_FINE = 0.05        # [m] stage step up to Y_FINE_MAX
Y_FINE_MAX = 10.0     # [m]
DY_COARSE = 0.2       # [m] stage step above that
Y_CAP = 100.0         # [m] highest stage tabulated


def stage_grid(y_max):
    """Stages above bank [m]: 5 cm steps to 10 m, then 20 cm steps to y_max."""
    y = np.arange(0.0, min(y_max, Y_FINE_MAX) + 1e-9, DY_FINE)
    if y_max > Y_FINE_MAX + 1e-9:
        y = np.concatenate([y, np.arange(Y_FINE_MAX + DY_COARSE, y_max + 1e-9, DY_COARSE)])
    return y


@_njit(cache=True)
def _first_above(y, h):
    """Index of the first stage strictly above h (len(y) if none)."""
    lo, hi = 0, y.shape[0]
    while lo < hi:
        mid = (lo + hi) // 2
        if y[mid] > h:
            hi = mid
        else:
            lo = mid + 1
    return lo


@_njit(cache=True)
def _floodplain_area(cr, hand, is_drain, w_cell, dist, cell_area, cell_size, n_reach):
    """Plan area of each cell left for floodplain flow.  River cells lose the
    channel footprint min(W·dist, cell area); a channel wider than the cell
    (fine grids) also takes the rest of its width from the reach's lowest
    cells.  Cells must be sorted by (reach, HAND)."""
    m = cr.shape[0]
    a = np.full(m, cell_area)
    left = np.zeros(n_reach)
    for i in range(m):
        if is_drain[i] and cr[i] >= 0:
            fp = w_cell[i] * dist[i]
            if fp > cell_area:
                fp = cell_area
            a[i] = cell_area - fp
            extra = (w_cell[i] - cell_size) * dist[i]
            if extra > 0.0:
                left[cr[i]] += extra
    for i in range(m):
        r = cr[i]
        if r < 0 or is_drain[i] or left[r] <= 0.0:
            continue
        take = a[i] if a[i] < left[r] else left[r]
        a[i] -= take
        left[r] -= take
    return a


@_njit(cache=True)
def _floodplain_tables(cr, hand, a_fp, n_fp, cell_area, y, n_reach):
    K = y.shape[0]
    F = np.zeros((n_reach, K))
    A = np.zeros((n_reach, K))
    for i in range(cr.shape[0]):
        r = cr[i]
        h = hand[i]
        if r < 0 or not (h < y[K - 1]):          # also skips NaN
            continue
        if h < 0.0:
            h = 0.0
        w = a_fp[i] / n_fp[i]
        for k in range(_first_above(y, h), K):
            F[r, k] += w * (y[k] - h) ** (5.0 / 3.0)
            A[r, k] += cell_area
    return F, A


def floodplain_area(cell_reach, hand, is_drain, w_cell, dist, cell_area, cell_size, n_reach):
    """See ``_floodplain_area``; any cell order (sorted internally)."""
    srt = np.lexsort((np.nan_to_num(hand, nan=np.inf), cell_reach))
    a = np.empty(len(cell_reach))
    a[srt] = _floodplain_area(
        np.asarray(cell_reach, dtype=np.int64)[srt], np.asarray(hand, dtype=np.float64)[srt],
        np.asarray(is_drain, dtype=np.bool_)[srt], np.asarray(w_cell, dtype=np.float64)[srt],
        np.asarray(dist, dtype=np.float64)[srt], float(cell_area), float(cell_size), int(n_reach))
    return a


def rating_curves(cell_reach, hand, a_fp, n_fp, cell_area, L, S, W, D, n_ch, y):
    """
    Synthetic rating curves for R reaches at the stages y (ascending, y[0] = 0).

    cell_reach (m,)  reach of the nearest drain of each cell (-1 = none)
    hand       (m,)  height above that drain [m]
    a_fp       (m,)  plan area left for floodplain flow [m²] (``floodplain_area``)
    n_fp       (m,)  floodplain Manning's n of each cell
    L, S, W, D, n_ch (R,)  reach length [m], slope, channel width [m],
                     bankfull depth [m] (0 = no channel below the DEM), channel n

    Returns (Q (R, K) [m³/s], flooded_area (R, K) [m²] of land below the water).
    """
    R = len(L)
    F, A = _floodplain_tables(np.asarray(cell_reach, dtype=np.int64),
                              np.asarray(hand, dtype=np.float64),
                              np.asarray(a_fp, dtype=np.float64),
                              np.asarray(n_fp, dtype=np.float64),
                              float(cell_area), np.asarray(y, dtype=np.float64), R)
    W = np.asarray(W, dtype=np.float64)[:, None]
    D = np.asarray(D, dtype=np.float64)[:, None]
    h = D + np.asarray(y, dtype=np.float64)[None, :]
    k_slot, _a = compound_conveyance(h, np.asarray(n_ch, dtype=np.float64)[:, None], W,
                                     np.ones(h.shape, dtype=bool), D, W, np)
    k_fp = F / np.maximum(np.asarray(L, dtype=np.float64), 1e-9)[:, None]
    Q = np.sqrt(np.asarray(S, dtype=np.float64))[:, None] * (k_slot + k_fp)
    return Q, A


def rating_curves_fitting(q_needed, *args, y_max=Y_FINE_MAX):
    """``rating_curves`` on a stage grid that doubles (to Y_CAP) until every
    reach's needed discharge fits.  Returns (y, Q, flooded_area)."""
    q_needed = np.asarray(q_needed, dtype=np.float64)
    while True:
        y = stage_grid(y_max)
        Q, A = rating_curves(*args, y)
        if y_max >= Y_CAP or not np.any(q_needed > Q[:, -1]):
            return y, Q, A
        y_max = min(2.0 * y_max, Y_CAP)


@_njit(cache=True)
def _stage_rows(Q, y, q):
    T, R = q.shape
    K = y.shape[0]
    out = np.zeros((T, R))
    clipped = np.zeros(R, dtype=np.bool_)
    for r in range(R):
        for t in range(T):
            v = q[t, r]
            if not (v > Q[r, 0]):                 # in-bank (or NaN)
                continue
            if v >= Q[r, K - 1]:
                out[t, r] = y[K - 1]
                clipped[r] = True
                continue
            lo, hi = 0, K - 1                     # Q[r, lo] < v <= Q[r, hi]
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if Q[r, mid] < v:
                    lo = mid
                else:
                    hi = mid
            dq = Q[r, hi] - Q[r, lo]
            out[t, r] = y[lo] + (y[hi] - y[lo]) * ((v - Q[r, lo]) / dq if dq > 0 else 1.0)
    return out, clipped


def stage_from_discharge(Q, y, q):
    """
    Stage above bank [m] for discharge q: (R,) or (T, R).  At or below the
    bankfull flow Q[:, 0] the stage is 0 (water stays in the channel).  Above
    the table's top the stage is held at y[-1] and the reach is flagged.

    Returns (stage like q, clipped (R,) bool).
    """
    q = np.asarray(q, dtype=np.float64)
    two_d = q.ndim == 2
    out, clipped = _stage_rows(np.asarray(Q, dtype=np.float64), np.asarray(y, dtype=np.float64),
                               q if two_d else q[None, :])
    return (out if two_d else out[0]), clipped
