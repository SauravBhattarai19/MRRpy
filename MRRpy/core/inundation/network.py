# -*- coding: utf-8 -*-
"""
network.py — D8 river-network helpers for HAND flood mapping.

Every function works on flat arrays that describe a D8 tree, so the same code
runs on the routing grid and on a finer flood-map grid:

  ds     (n,) int64  downstream cell index, -1 where water leaves the domain
  order  (n,) int64  cell indices ordered downstream-first (every cell comes
                     after the cell it drains to)

The routing grid supplies ``order = arange(n)[::-1]`` (the router's topological
order is upstream-first, ``ds_idx[i] > i``); a pyflwdir grid supplies
``order = flw.idxs_seq`` with ``ds = flw.idxs_ds`` (a pit, ds == self, → -1).
"""

import heapq

import numpy as np

from ..routing.terrain import D8_MOVE

try:
    from numba import njit as _njit
except Exception:                                 # pragma: no cover
    def _njit(*a, **k):
        return (lambda f: f) if not (a and callable(a[0])) else a[0]


# ── Nearest drain and height above it ────────────────────────────────────────
@_njit(cache=True)
def _nearest_drain(order, ds, is_drain):
    drain_of = np.full(ds.shape[0], -1, dtype=np.int64)
    for k in range(order.shape[0]):               # outlets first
        i = order[k]
        if is_drain[i]:
            drain_of[i] = i
        else:
            d = ds[i]
            if d >= 0:
                drain_of[i] = drain_of[d]
    return drain_of


def nearest_drain(order, ds, is_drain):
    """Index of the first river (drain) cell downstream of each cell, following
    the D8 flow path (the cell itself when it is a river cell); -1 where the
    path leaves the domain before reaching a river."""
    return _nearest_drain(np.asarray(order, dtype=np.int64), np.asarray(ds, dtype=np.int64),
                          np.asarray(is_drain, dtype=np.bool_))


def height_above_drain(z, drain_of):
    """HAND [m]: elevation above the nearest drain cell, NaN where there is none."""
    z = np.asarray(z, dtype=np.float64)
    ok = drain_of >= 0
    return np.where(ok, z - z[np.where(ok, drain_of, 0)], np.nan)


@_njit(cache=True)
def _bed_profile(order, ds, is_drain, z):
    bed = z.copy()
    for k in range(order.shape[0] - 1, -1, -1):  # headwaters first
        i = order[k]
        if is_drain[i]:
            d = ds[i]
            if d >= 0 and is_drain[d] and bed[i] < bed[d]:
                bed[d] = bed[i]
    return bed


def river_bed_profile(order, ds, is_drain, z):
    """River-cell elevations made non-increasing downstream by lowering only
    ("thalweg conditioning"): every river cell is at most as high as any river
    cell upstream of it, so bridges and DEM dams across a river disappear.
    Other cells keep *z*."""
    return _bed_profile(np.asarray(order, dtype=np.int64), np.asarray(ds, dtype=np.int64),
                        np.asarray(is_drain, dtype=np.bool_), np.asarray(z, dtype=np.float64))


# ── Reaches ──────────────────────────────────────────────────────────────────
@_njit(cache=True)
def _segment(order, ds, is_drain, dist, max_len):
    n = ds.shape[0]
    n_don = np.zeros(n, dtype=np.int64)
    donor = np.full(n, -1, dtype=np.int64)
    for i in range(n):
        if is_drain[i]:
            d = ds[i]
            if d >= 0 and is_drain[d]:
                n_don[d] += 1
                donor[d] = i
    # Pass 1, upstream-first: link (source/confluence → next confluence) and
    # the distance from the link head to each cell's upstream face.
    link = np.full(n, -1, dtype=np.int64)
    start = np.zeros(n)
    link_len = np.zeros(n)                       # indexed by link id
    n_link = 0
    for k in range(order.shape[0] - 1, -1, -1):
        i = order[k]
        if not is_drain[i]:
            continue
        if n_don[i] == 1:
            j = donor[i]
            link[i] = link[j]
            start[i] = start[j] + dist[j]
        else:
            link[i] = n_link
            n_link += 1
        end = start[i] + dist[i]
        if end > link_len[link[i]]:
            link_len[link[i]] = end
    # Each link is cut into equal pieces no longer than max_len.
    n_piece = np.ones(n_link, dtype=np.int64)
    offset = np.zeros(n_link, dtype=np.int64)
    tot = 0
    for l in range(n_link):
        if max_len > 0:
            n_piece[l] = max(1, int(np.ceil(link_len[l] / max_len - 1e-9)))
        offset[l] = tot
        tot += n_piece[l]
    reach = np.full(n, -1, dtype=np.int64)
    r_len = np.zeros(tot)
    r_out = np.full(tot, -1, dtype=np.int64)
    r_out_pos = np.full(tot, -1.0)
    for i in range(n):
        if not is_drain[i]:
            continue
        l = link[i]
        piece_len = link_len[l] / n_piece[l]
        p = int((start[i] + 0.5 * dist[i]) / piece_len) if piece_len > 0 else 0
        if p > n_piece[l] - 1:
            p = n_piece[l] - 1
        r = offset[l] + p
        reach[i] = r
        r_len[r] += dist[i]
        if start[i] > r_out_pos[r]:              # most downstream cell = reach outlet
            r_out_pos[r] = start[i]
            r_out[r] = i
    return reach, r_len, r_out


def segment_reaches(order, ds, is_drain, dist, max_len_m):
    """
    Split the river cells into reaches: links run from a source or a confluence
    (a river cell with two or more river donors) to the next confluence or the
    domain edge, and every link is cut into ``ceil(L / max_len_m)`` pieces of
    equal length (so no short leftover pieces).

    Returns (reach_of (n,) int64 with -1 off the rivers, length (R,) [m],
    outlet (R,) most downstream cell of each reach).
    """
    return _segment(np.asarray(order, dtype=np.int64), np.asarray(ds, dtype=np.int64),
                    np.asarray(is_drain, dtype=np.bool_), np.asarray(dist, dtype=np.float64),
                    float(max_len_m))


def level_thresholds(a_channel_km2, a_max_km2):
    """Drainage-area thresholds [km²] of the HAND levels: the river network,
    then main stems ×10, ×100, … while still below half the largest river."""
    out = [float(a_channel_km2)]
    a = float(a_channel_km2) * 10.0
    while a < 0.5 * float(a_max_km2):
        out.append(a)
        a *= 10.0
    return out


# ── Flow directions by least-cost search ─────────────────────────────────────
_DR = np.array([-1, -1, 0, 1, 1, 1, 0, -1], dtype=np.int64)       # N NE E SE S SW W NW
_DC = np.array([0, 1, 1, 1, 0, -1, -1, -1], dtype=np.int64)
_TOWARD = np.array([4, 8, 16, 32, 64, 128, 1, 2], dtype=np.uint8)  # code from the neighbour back


@_njit(cache=True)
def _least_cost_d8(z, valid, nrows, ncols, DR, DC, TOWARD):
    n = nrows * ncols
    d8 = np.zeros(n, dtype=np.uint8)
    done = np.zeros(n, dtype=np.bool_)
    heap = [(0.0, np.int64(0), np.int64(0))]
    heap.pop()
    seq = np.int64(0)
    for i in range(n):                            # outlets: the edge and next to no-data
        if not valid[i]:
            continue
        r, c = i // ncols, i % ncols
        edge = r == 0 or c == 0 or r == nrows - 1 or c == ncols - 1
        if not edge:
            for k in range(8):
                if not valid[(r + DR[k]) * ncols + c + DC[k]]:
                    edge = True
                    break
        if edge:
            done[i] = True
            heapq.heappush(heap, (z[i], seq, np.int64(i)))
            seq += 1
    while len(heap):
        _zc, _s, i = heapq.heappop(heap)
        r, c = i // ncols, i % ncols
        for k in range(8):
            rn, cn = r + DR[k], c + DC[k]
            if rn < 0 or rn >= nrows or cn < 0 or cn >= ncols:
                continue
            j = rn * ncols + cn
            if valid[j] and not done[j]:
                done[j] = True
                d8[j] = TOWARD[k]
                heapq.heappush(heap, (z[j], seq, np.int64(j)))
                seq += 1
    return d8


def least_cost_d8(dem, valid):
    """
    D8 flow directions (pysheds/pyflwdir codes, 0 = outlet) by least-cost
    search (Metz, Mitasova & Harmon 2011; GRASS r.watershed): starting from the
    edge, cells are reached lowest first, each draining to the neighbour it was
    reached from.  Flow stays in the real channels and crosses a bridge or a
    DEM dam at its lowest point, instead of filling the valley floor behind it
    into a flat that D8 would cross in straight lines.
    """
    dem = np.asarray(dem, dtype=np.float64)
    nrows, ncols = dem.shape
    d8 = _least_cost_d8(np.where(valid, dem, np.inf).ravel(), np.asarray(valid).ravel(),
                        nrows, ncols, _DR, _DC, _TOWARD)
    return d8.reshape(dem.shape)


# ── Building a network from a D8 raster ──────────────────────────────────────
def downstream_from_d8(d8, valid, cell_size):
    """
    Flat downstream index and flow-path length of every cell of a D8 raster
    (pysheds/pyflwdir codes, ``terrain.D8_MOVE``).  ``ds = -1`` where the
    direction is a pit, points off the raster, or into an invalid cell.
    Returns (ds (H·W,) int64, dist (H·W,) float64).
    """
    d8 = np.asarray(d8)
    nrows, ncols = d8.shape
    rr, cc = np.indices(d8.shape)
    rn = np.full(d8.shape, -1, dtype=np.int64)
    cn = np.full(d8.shape, -1, dtype=np.int64)
    dist = np.zeros(d8.shape, dtype=np.float64)
    for code, (dr, dc) in D8_MOVE.items():
        m = d8 == code
        rn[m] = rr[m] + dr
        cn[m] = cc[m] + dc
        dist[m] = cell_size * (np.sqrt(2.0) if dr and dc else 1.0)
    inside = (rn >= 0) & (rn < nrows) & (cn >= 0) & (cn < ncols)
    ds = np.where(inside, rn * ncols + cn, -1).ravel()
    ok = valid.ravel() & (ds >= 0)
    ok[ok] = valid.ravel()[ds[ok]]
    ds = np.where(ok, ds, -1)
    return ds, np.where(ds >= 0, dist.ravel(), float(cell_size))


@_njit(cache=True)
def _bfs_order(ds):
    n = ds.shape[0]
    n_up = np.zeros(n + 1, dtype=np.int64)
    for i in range(n):
        if ds[i] >= 0:
            n_up[ds[i] + 1] += 1
    for i in range(n):
        n_up[i + 1] += n_up[i]
    up = np.empty(n_up[n], dtype=np.int64)
    fill = n_up[:-1].copy()
    for i in range(n):
        d = ds[i]
        if d >= 0:
            up[fill[d]] = i
            fill[d] += 1
    order = np.empty(n, dtype=np.int64)
    head = 0
    for i in range(n):
        if ds[i] < 0:
            order[head] = i
            head += 1
    k = 0
    while k < head:
        i = order[k]
        for j in range(n_up[i], n_up[i + 1]):
            order[head] = up[j]
            head += 1
        k += 1
    return order[:head]


def downstream_first_order(ds):
    """Cells ordered downstream-first (breadth-first from the cells whose
    water leaves the domain).  Cells caught in a loop are left out."""
    return _bfs_order(np.asarray(ds, dtype=np.int64))


def upstream_area(order, ds, cell_area_km2, extra_km2=None):
    """Drainage area [km²] of every cell (its own area plus everything draining
    to it), with optional extra area injected at chosen cells (rivers entering
    from outside the domain)."""
    acc = np.full(ds.shape[0], float(cell_area_km2)) if np.isscalar(cell_area_km2) \
        else np.array(cell_area_km2, dtype=np.float64)
    if extra_km2 is not None:
        acc = acc + extra_km2
    return _accumulate(np.asarray(order, dtype=np.int64), np.asarray(ds, dtype=np.int64), acc)


@_njit(cache=True)
def _accumulate(order, ds, acc):
    for k in range(order.shape[0] - 1, -1, -1):  # headwaters first
        i = order[k]
        d = ds[i]
        if d >= 0:
            acc[d] += acc[i]
    return acc
