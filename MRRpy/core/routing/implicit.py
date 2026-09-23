# -*- coding: utf-8 -*-
"""
implicit.py — HEC-RAS-style semi-implicit diffusion-wave solver on the D8 tree.

The explicit diffusion wave (``hydraulics.diffusive_wave_discharge`` +
``router.run_time_loop``) is stable only under a CFL time step, so it collapses
``dt`` on flat/ponded water (celerity → 0) and on steep cells (celerity ∝ √S).
This module solves the same physics **implicitly**, which is unconditionally
stable — big time steps, no flat/steep ``dt`` collapse — the reason HEC-RAS's
2D Diffusion-Wave solver is fast.

Mathematics (HEC-RAS 6.2 diffusion-wave, per D8 face i→d)
--------------------------------------------------------
Momentum (friction slope = water-surface slope) gives the Manning face
discharge ``Q = (1/n) R^{2/3} A_xs √S_f`` with ``S_f = (z_i − z_d)/dist`` and
``z = bed + h`` (water-surface elevation, WSE).  Linearise it as a **face
conductance** evaluated at the previous Picard iterate (lagged conveyance):

    K_{i,d} = (1/n) R^{2/3} A_xs / (dist · √|S_f|)     →   Q_{i→d} = K_{i,d}·(z_i − z_d)

``K`` carries the ``|S_f|^{-1/2}`` singularity, but the flux ``K·ΔH ∝ |ΔH|^{1/2}``
stays finite as ``S_f→0``; we floor ``|S_f|`` by ``IMPLICIT_SLOPE_FLOOR``.

Backward-Euler (θ-method) finite-volume continuity, unknown = new WSE ``z^{n+1}``
(bed fixed → ``Δh = Δz``), storage footprint ``A_store`` and lateral source
``q`` [m/s] over the plan area ``A_cell``:

    (A_store,i/dt)(z_i^{n+1} − z_i^n) = θ·F_i^{n+1} + (1−θ)·F_i^n + q_i·A_cell + q_ext,i
    F_i = Σ_up K_{j,i}(z_j − z_i) − K_{i,d}(z_i − z_d) − K_bnd,i(z_i − bed_i)

Collecting the implicit terms yields a linear system **M z^{n+1} = b** whose
diagonal is ``A_store/dt + θ·Σ K`` and whose only off-diagonals are the
symmetric ``−θ·K`` face couplings.  Because D8 flow on a filled DEM is acyclic
with out-degree 1, the coupling graph is a **forest**, so ``M`` is a tree matrix
— SPD and strictly diagonally dominant (the ``A_store/dt`` term guarantees it).

Solve (exact, O(n))
-------------------
The existing topological order (upstream→downstream, ``s_rows``/``s_cols`` sorted
by flow accumulation) is a *perfect elimination ordering* for the tree
(``ds_idx[i] > i`` always) ⇒ **zero fill-in**.  Two sweeps:
  * forward eliminate each cell into its (single) downstream parent,
  * back-substitute from the outlet up to the leaves.
Both O(n).  This is the classic branched-channel double sweep of 1D river-network
solvers.  ``IMPLICIT_SOLVER`` picks the backend: a Numba-JIT double sweep when
available (near-C speed), else SciPy sparse ``splu`` with the natural (already
optimal) ordering — no new hard dependency.

Boundary cells (outlet / off-mask, ``ds_idx = −1``) keep the free-outflow
convention of the explicit scheme: a kinematic normal-depth outflow on the bed
slope, linearised as a conductance ``K_bnd`` to a ghost WSE at the bed.
"""

import os

import numpy as np

# ── Optional Numba fast path (never a hard dependency) ──────────────────────
try:
    from numba import njit, prange, set_num_threads, get_num_threads
    _NUMBA_OK = True
except Exception:                       # pragma: no cover - import guard
    _NUMBA_OK = False
    prange = range
    set_num_threads = get_num_threads = None

    def njit(*args, **kwargs):          # no-op decorator so the source still imports
        def _wrap(fn):
            return fn
        return _wrap(args[0]) if args and callable(args[0]) else _wrap


# ---------------------------------------------------------------------------
# Conveyance helper  C = (1/n) R^{2/3} A_xs   (overland wide sheet or confined channel)
# ---------------------------------------------------------------------------

def _conveyance(h_flow, width, chan_mask, n, cell_size):
    """
    Manning conveyance ``C = (1/n) R^{2/3} A_xs`` [m³/s per √(m/m)] per cell.

    Overland (``chan_mask`` False): wide sheet, ``R ≈ h``, width = ``cell_size``
    → ``C = (1/n) h^{5/3} cell_size`` — the same arithmetic as the explicit
    diffusive overland kernel.  Channel cells use the confined rectangular
    section ``A = B·h``, ``P = B + 2h``, ``R = A/P``.
    """
    A_over = h_flow * cell_size
    C_over = (1.0 / n) * (h_flow ** (2.0 / 3.0)) * A_over

    A_chan = h_flow * width
    R_chan = A_chan / (width + 2.0 * h_flow)
    C_chan = (1.0 / n) * (R_chan ** (2.0 / 3.0)) * A_chan
    return np.where(chan_mask, C_chan, C_over)


# ---------------------------------------------------------------------------
# Tree linear solvers  (M z = b,  M tree-structured SPD)
# ---------------------------------------------------------------------------

@njit(cache=True)
def _sweep_solve(diag, off, parent, is_root, rhs):
    """
    Exact O(n) direct solve of a tree-structured SPD system.

    ``diag[i]``     : M_ii
    ``off[i]``      : M_{i,parent[i]} = M_{parent[i],i}  (0 for roots)
    ``parent[i]``   : downstream position (must satisfy parent[i] > i; -1 for roots)
    ``is_root[i]``  : True where the cell has no downstream (outlet / off-mask)
    ``rhs[i]``      : b_i

    Cells are in topological order (``parent[i] > i``), a perfect elimination
    ordering, so forward elimination (leaves→root) then back-substitution
    (root→leaves) has zero fill-in.  ``diag``/``rhs`` are copied by the caller;
    this routine mutates them.
    """
    n = diag.shape[0]
    z = np.empty(n, dtype=diag.dtype)

    # Forward elimination: fold each cell into its (single) downstream parent.
    for i in range(n):
        if not is_root[i]:
            p = parent[i]
            inv = 1.0 / diag[i]
            diag[p] -= off[i] * off[i] * inv
            rhs[p] -= off[i] * rhs[i] * inv

    # Back-substitution: parent (higher index) solved before its children.
    for i in range(n - 1, -1, -1):
        if is_root[i]:
            z[i] = rhs[i] / diag[i]
        else:
            z[i] = (rhs[i] - off[i] * z[parent[i]]) / diag[i]
    return z


def _splu_solve(diag, off, parent, is_root, rhs):
    """
    SciPy sparse fallback: assemble M as CSC and factor with SuperLU using the
    NATURAL ordering (our topological order is already a perfect elimination
    order for the tree → near-zero fill).  Dependency-free (SciPy is required).
    """
    from scipy.sparse import csc_matrix
    from scipy.sparse.linalg import splu

    n = diag.shape[0]
    child = np.nonzero(~is_root)[0]
    par = parent[child]
    # Diagonal + the two symmetric off-diagonal entries per child→parent face.
    rows = np.concatenate([np.arange(n), child, par])
    cols = np.concatenate([np.arange(n), par, child])
    data = np.concatenate([diag, off[child], off[child]])
    M = csc_matrix((data, (rows, cols)), shape=(n, n))
    return splu(M, permc_spec="NATURAL").solve(rhs)


# ---------------------------------------------------------------------------
# Parallel (multi-core) assembly — the per-Picard-iteration bottleneck
# ---------------------------------------------------------------------------
# Benchmarked on the 768K-cell Gandaki basin grid: the tree SWEEP is ~7ms
# (inherently sequential along the topological chain — cannot be parallelised
# without restructuring into level sets), but building the conductances +
# M/rhs (K_int, K_bnd, diag, rhs, off) from the current WSE iterate is ~35ms —
# 5x the sweep cost — and is embarrassingly parallel: every cell's own
# conductance is independent, and the only cross-cell step (each parent's
# incident-K sum from its children, ``np.add.at`` in the pure-NumPy path) is a
# per-parent REDUCTION that can be computed race-free with a precomputed CSR
# reverse-adjacency (``child_off``/``child_idx``) instead of a scatter — each
# parallel worker owns exactly one parent's accumulation.  On a many-core
# machine this collapses the dominant cost of each Picard iteration.

def _build_children_csr(parent, valid, n):
    """
    One-time (per-grid) CSR reverse-adjacency of the D8 tree: for each parent
    index p, ``child_idx[child_off[p]:child_off[p+1]]`` lists the cells whose
    downstream neighbour is p.  Lets the parallel kernel replace the scatter
    ``np.add.at(diag, parent, tK)`` with a race-free per-parent gather.
    """
    counts = np.zeros(n, dtype=np.int64)
    for i in range(n):
        if valid[i]:
            counts[parent[i]] += 1
    child_off = np.zeros(n + 1, dtype=np.int64)
    child_off[1:] = np.cumsum(counts)
    cursor = child_off[:-1].copy()
    child_idx = np.empty(int(child_off[-1]), dtype=np.int64)
    for i in range(n):
        if valid[i]:
            p = parent[i]
            child_idx[cursor[p]] = i
            cursor[p] += 1
    return child_off, child_idx


@njit(parallel=True, cache=True)
def _assemble_parallel(z, z0, dem, dist, slope_bed, sqrt_Sbed, n_arr, width,
                       chan_mask, cell_size, A_over_dt, q, theta, eps_h,
                       slope_floor, relax, first_iter, parent, ds, valid, root,
                       child_off, child_idx, K_int_prev, K_bnd_prev):
    """
    Fused, multi-core replacement for one Picard iteration's conductance +
    M/rhs assembly (see module docstring for the underlying equations).
    Mirrors the pure-NumPy path in ``ImplicitDiffusiveSolver.solve_step``
    term-for-term; kept in lock-step with it deliberately (verified against
    it in the test suite) rather than sharing code, since a single fused
    kernel is what makes the parallel loop worthwhile.

    Returns (diag, off, rhs, K_int, K_bnd) — off/K_int/K_bnd are 0 on cells
    without a valid downstream neighbour (outlet / off-mask), matching the
    NumPy path's ``xp.where(valid, ...)`` masking.
    """
    n = z.shape[0]
    K_int  = np.empty(n)
    K_bnd  = np.empty(n)
    diag   = np.empty(n)
    rhs    = np.empty(n)
    off    = np.zeros(n)
    f_int  = np.zeros(n)   # child->parent flux at z0 (theta<1 only)
    Fn_own = np.zeros(n)   # this cell's own explicit-fraction term (theta<1 only)

    # ── Pass 1: per-cell own conductances + M/rhs own-terms (parallel) ──────
    for i in prange(n):
        di = ds[i]
        zi = z[i]
        z_ds = z[di]
        dz = zi - z_ds
        adz = dz if dz >= 0.0 else -dz
        Sf = adz / dist[i]
        if Sf < slope_floor:
            Sf = slope_floor
        wse_hi = zi if zi > z_ds else z_ds
        bed_hi = dem[i] if dem[i] > dem[di] else dem[di]
        h_hb = wse_hi - bed_hi
        h_flow = h_hb if h_hb > eps_h else eps_h

        if chan_mask[i]:
            A = h_flow * width[i]
            R = A / (width[i] + 2.0 * h_flow)
            C = (1.0 / n_arr[i]) * R ** (2.0 / 3.0) * A
        else:
            A = h_flow * cell_size
            C = (1.0 / n_arr[i]) * h_flow ** (2.0 / 3.0) * A
        k_new = (C / (dist[i] * np.sqrt(Sf))) if valid[i] else 0.0

        h_own = zi - dem[i]
        if h_own < eps_h:
            h_own = eps_h
        if chan_mask[i]:
            A2 = h_own * width[i]
            R2 = A2 / (width[i] + 2.0 * h_own)
            C2 = (1.0 / n_arr[i]) * R2 ** (2.0 / 3.0) * A2
        else:
            A2 = h_own * cell_size
            C2 = (1.0 / n_arr[i]) * h_own ** (2.0 / 3.0) * A2
        Q_kin = C2 * sqrt_Sbed[i]
        kb_new = (Q_kin / h_own) if root[i] else 0.0

        if first_iter:
            ki, kb = k_new, kb_new
        else:
            ki = relax * k_new + (1.0 - relax) * K_int_prev[i]
            kb = relax * kb_new + (1.0 - relax) * K_bnd_prev[i]
        K_int[i] = ki
        K_bnd[i] = kb

        tk = theta * ki if valid[i] else 0.0
        off[i] = -tk
        diag[i] = A_over_dt[i] + tk + theta * kb
        rhs[i]  = A_over_dt[i] * z0[i] + q[i] + theta * kb * dem[i]

        if theta < 1.0:
            dz0 = z0[i] - z0[di]
            fi = ki * dz0 if valid[i] else 0.0
            f_int[i] = fi
            Fn_own[i] = -fi - kb * (z0[i] - dem[i])

    # ── Pass 2: per-parent reduction over children (parallel, race-free) ────
    # Every cell (leaf or not) needs its own Fn_own term; the children loop is
    # simply empty for leaves (child_off[p] == child_off[p+1]), contributing 0.
    for p in prange(n):
        s0, s1 = child_off[p], child_off[p + 1]
        acc_diag = 0.0
        for k in range(s0, s1):
            acc_diag += theta * K_int[child_idx[k]]
        diag[p] += acc_diag
        if theta < 1.0:
            acc_f = 0.0
            for k in range(s0, s1):
                acc_f += f_int[child_idx[k]]
            rhs[p] += (1.0 - theta) * (Fn_own[p] + acc_f)

    return diag, off, rhs, K_int, K_bnd


# ---------------------------------------------------------------------------
# Solver object (built once per run; holds the static grid arrays)
# ---------------------------------------------------------------------------

class ImplicitDiffusiveSolver:
    """
    Semi-implicit diffusion-wave step on the D8 tree.  Constructed once from
    ``grid_data``; ``solve_step`` advances one time step (Picard-iterated).

    Runs entirely in NumPy on the CPU (implicit solves are linear-algebra /
    core bound, not throughput bound — see the module docstring and the
    ``diffusive_implicit`` → CPU rule in ``router.initialise_grid``).
    """

    def __init__(self, cfg, grid_data):
        _to_np = lambda a: np.asarray(a.get() if hasattr(a, "get") else a)
        self.dem        = _to_np(grid_data["dem_1d"]).astype(np.float64)
        self.dist       = _to_np(grid_data["dist_1d"]).astype(np.float64)
        self.slope_bed  = _to_np(grid_data["slope_1d"]).astype(np.float64)
        self.n          = _to_np(grid_data["n_1d"]).astype(np.float64)
        self.width      = _to_np(grid_data["width_1d"]).astype(np.float64)
        self.store_area = _to_np(grid_data["store_area_1d"]).astype(np.float64)
        self.chan_mask  = _to_np(grid_data["chan_mask_1d"]).astype(bool)
        self.cell_size  = float(grid_data["cell_size"])
        self.cell_area  = float(grid_data["cell_area"])

        ds_idx          = _to_np(grid_data["ds_idx"]).astype(np.int64)
        self.parent     = ds_idx
        self.is_root    = ds_idx < 0
        self.valid_ds   = ds_idx >= 0
        self.ds_safe    = np.where(self.valid_ds, ds_idx, 0)
        self.n_cells    = int(grid_data["n_cells"])
        self.sqrt_Sbed  = np.sqrt(np.maximum(self.slope_bed, 0.0))

        # Tunables (all defaulted in Config so existing configs are unchanged).
        self.max_iters   = int(getattr(cfg, "IMPLICIT_MAX_ITERS", 4))
        self.tol         = float(getattr(cfg, "IMPLICIT_TOL", 1e-4))
        self.slope_floor = float(getattr(cfg, "IMPLICIT_SLOPE_FLOOR", 1e-8))
        self.theta       = float(getattr(cfg, "IMPLICIT_THETA", 1.0))
        self.relax       = float(getattr(cfg, "IMPLICIT_RELAX", 0.7))
        self.min_depth   = float(getattr(cfg, "MIN_DEPTH_M", 1e-6))

        solver = str(getattr(cfg, "IMPLICIT_SOLVER", "auto")).lower()
        if solver == "auto":
            solver = "numba" if _NUMBA_OK else "splu"
        if solver == "numba" and not _NUMBA_OK:
            print("  [WARN] IMPLICIT_SOLVER='numba' but numba is unavailable — "
                  "falling back to SciPy sparse (splu).")
            solver = "splu"
        self.solver_name = solver

        # Multi-core assembly (see module docstring): the per-Picard-iteration
        # conductance + M/rhs build is embarrassingly parallel and dominates
        # the sweep's own cost ~5:1, so use it whenever Numba is available,
        # independent of which linear solve backend (numba sweep / splu) is
        # chosen.  child_off/child_idx replace the scatter-add with a
        # race-free per-parent gather (see ``_build_children_csr``).
        self.parallel_assembly = _NUMBA_OK
        if self.parallel_assembly:
            self.child_off, self.child_idx = _build_children_csr(
                self.parent, self.valid_ds, self.n_cells)

            # This kernel is memory-bandwidth-bound, not compute-bound (each
            # cell does ~20 FLOPs against ~10 array reads + a few writes) —
            # benchmarked on a 768K-cell grid (192-core machine): throughput
            # improves up to ~32-64 threads then DEGRADES using more (192
            # threads was slower than 8, from cross-core/NUMA memory-
            # controller contention).  "Use every core" is the wrong default
            # for this kernel, so cap it rather than let Numba grab all of
            # them.  IMPLICIT_NUM_THREADS overrides the cap explicitly.
            _requested = getattr(cfg, "IMPLICIT_NUM_THREADS", None)
            _ncpu = os.cpu_count() or 32
            n_threads = int(_requested) if _requested else min(32, _ncpu)
            set_num_threads(max(1, min(n_threads, _ncpu)))

        # Warm up the Numba JIT once so it doesn't tax the first time step.
        if _NUMBA_OK:
            _sweep_solve(np.ones(1), np.zeros(1), np.array([-1]),
                         np.array([True]), np.zeros(1))
        if self.parallel_assembly:
            _assemble_parallel(
                np.ones(1), np.ones(1), np.zeros(1), np.ones(1), np.ones(1),
                np.ones(1), np.array([0.03]), np.ones(1), np.array([False]),
                90.0, np.ones(1), np.zeros(1), self.theta, self.min_depth,
                self.slope_floor, self.relax, True, np.array([-1]),
                np.array([0]), np.array([False]), np.array([True]),
                np.array([0, 0], dtype=np.int64), np.empty(0, dtype=np.int64),
                np.zeros(1), np.zeros(1))

    # -- one time step -------------------------------------------------------

    def solve_step(self, volume, source_rate, bc_rate, dt):
        """
        Advance one implicit diffusion-wave step.

        Parameters
        ----------
        volume      : (n,) float64 – stored volume at step start [m³]
        source_rate : (n,) float64 – effective lateral runoff [m/s] over ``cell_area``
        bc_rate     : (n,) float64 or None – external point inflow [m³/s]
        dt          : float – time step [s]

        Returns
        -------
        volume_new : (n,) float64 [m³]  – updated storage (mass-consistent)
        q_out_face : (n,) float64 [m³/s]– outflow leaving each cell downstream
                     (interior: K·ΔH to parent; boundary: free outflow) — used
                     for the hydrograph, celerity and boundary mass accounting
        n_iters    : int   – Picard iterations taken
        residual   : float – final max|Δz| [m]
        """
        dem, dist, n = self.dem, self.dist, self.n
        width, chan  = self.width, self.chan_mask
        store, csize = self.store_area, self.cell_size
        parent, ds   = self.parent, self.ds_safe
        valid, root  = self.valid_ds, self.is_root
        theta        = self.theta
        eps_h        = self.min_depth

        # Start-of-step WSE.  Volume is NOT floored at 0 here: the continuity
        # ledger is signed so mass closes to machine precision even when the
        # Picard iteration is imperfect (a cell may briefly over-drain by a hair,
        # recovered as upstream water arrives).  Conveyance depths below are
        # floored separately, so the negative excursion never enters a Manning
        # power.
        z0 = dem + volume / store                            # start-of-step WSE
        z  = z0.copy()                                       # Picard iterate

        A_over_dt = store / dt
        # Lateral inflow (source over plan area + external point inflow) [m³/s].
        q = source_rate * self.cell_area
        if bc_rate is not None:
            q = q + bc_rate

        K_int  = np.zeros(self.n_cells)     # downstream-face conductance [m²/s]
        K_bnd  = np.zeros(self.n_cells)     # free-outflow conductance    [m²/s]
        _first = True
        n_iters, residual = 0, 0.0

        for it in range(self.max_iters):
            n_iters = it + 1

            if self.parallel_assembly:
                # Multi-core fused kernel: conductances + M/rhs in one pass
                # (see module docstring — this is the ~5x-of-sweep-cost step).
                diag, off, rhs, K_int, K_bnd = _assemble_parallel(
                    z, z0, dem, dist, self.slope_bed, self.sqrt_Sbed, n, width,
                    chan, csize, A_over_dt, q, theta, eps_h, self.slope_floor,
                    self.relax, _first, parent, ds, valid, root,
                    self.child_off, self.child_idx, K_int, K_bnd)
                _first = False
            else:
                # ── Face conductance K_{i,d} from the current iterate (lagged) ──
                z_ds  = z[ds]
                dem_ds = dem[ds]
                dz    = z - z_ds
                Sf    = np.maximum(np.abs(dz) / dist, self.slope_floor)
                # Conveyance uses the flow depth over the HIGHER bed (wet/dry safe).
                h_hb  = np.maximum(z, z_ds) - np.maximum(dem, dem_ds)
                h_flow = np.maximum(h_hb, eps_h)
                C     = _conveyance(h_flow, width, chan, n, csize)
                K_int_new = np.where(valid, C / (dist * np.sqrt(Sf)), 0.0)

                # ── Free-outflow conductance for boundary cells (kinematic) ─────
                h_own = np.maximum(z - dem, eps_h)
                C_own = _conveyance(h_own, width, chan, n, csize)
                Q_kin = C_own * self.sqrt_Sbed                   # normal-depth outflow
                K_bnd_new = np.where(root, Q_kin / h_own, 0.0)

                # Under-relax the conductance between iterates: the diffusion-wave
                # ``|∇H|^{-1/2}`` term makes raw lagged K swing (and diverge) at large
                # Courant numbers; blending with the previous iterate's K damps that so
                # the Picard loop converges for big steps.  relax=1.0 → no relaxation.
                if _first or self.relax >= 1.0:
                    K_int, K_bnd, _first = K_int_new, K_bnd_new, False
                else:
                    w = self.relax
                    K_int = w * K_int_new + (1.0 - w) * K_int
                    K_bnd = w * K_bnd_new + (1.0 - w) * K_bnd

                # ── Assemble M (tree) and RHS ───────────────────────────────────
                diag = A_over_dt.copy()
                rhs  = A_over_dt * z0 + q
                off  = np.zeros(self.n_cells)

                # Implicit interior faces: symmetric −θK coupling child↔parent.
                tK = theta * K_int
                off[valid] = -tK[valid]
                diag[valid] += tK[valid]                         # child's own face
                np.add.at(diag, parent[valid], tK[valid])        # parent's incident face

                # Implicit boundary (free-outflow) term.
                diag += theta * K_bnd
                rhs  += theta * K_bnd * dem

                # Explicit fraction (θ<1): net flux at the start-of-step WSE z0.
                if theta < 1.0:
                    dz0   = z0 - z0[ds]
                    f_int = np.where(valid, K_int * dz0, 0.0)    # child→parent flux
                    Fn    = -f_int - K_bnd * (z0 - dem)
                    np.add.at(Fn, parent[valid], f_int[valid])
                    rhs += (1.0 - theta) * Fn

            # ── Solve the tree system ───────────────────────────────────────
            if self.solver_name == "splu":
                z_new = _splu_solve(diag, off, parent, root, rhs)
            else:
                z_new = _sweep_solve(diag.copy(), off, parent, root, rhs.copy())

            residual = float(np.max(np.abs(z_new - z))) if self.n_cells else 0.0
            z = z_new
            if residual < self.tol:
                break

        # ── Storage and diagnostic fluxes from the solved WSE ───────────────
        # Signed ledger (no clamp): with the interior fluxes cancelling pairwise,
        # ΔV = (lateral in − boundary out)·dt EXACTLY, so the router's mass budget
        # closes to machine precision independent of Picard convergence.  Physical
        # positivity (z ≥ bed, Q ≥ 0) comes from converging the iteration (moderate
        # Courant + enough iters), not from clamps that would leak mass.
        volume_new = (z - dem) * store
        q_out_face = np.where(valid, K_int * (z - z[ds]), K_bnd * (z - dem))
        return volume_new, q_out_face, n_iters, residual
