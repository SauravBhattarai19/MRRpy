# -*- coding: utf-8 -*-
"""
hydraulics.py — per-step flow kernels shared by both compute backends.

Manning velocity/discharge (sheet and confined rectangular channel),
the diffusive-wave (CASC2D/GSSHA-style water-surface-slope) discharge,
the volume flux limiter and the legacy uniform-rainfall array builder.
All array functions are backend-agnostic (NumPy or CuPy via the xp arg).
"""

import numpy as np




# ---------------------------------------------------------------------------
# 5.  Manning's equation (vectorised over all active cells)
# ---------------------------------------------------------------------------

def mannings_velocity(depth, slope, n):
    """
    V = (1/n) * depth^(2/3) * slope^(1/2)    [m/s]

    Parameters are 1-D arrays (one value per active cell).
    """
    return (1.0 / n) * (depth ** (2.0 / 3.0)) * (slope ** 0.5)


def cell_discharge(depth, velocity, cell_size):
    """
    Q = V * width * depth   [m³/s]
    Assumes wide rectangular cross-section → width ≈ cell_size.
    """
    return velocity * cell_size * depth


def mannings_discharge(depth, slope, n, width, chan_mask, cell_size, xp):
    """
    Kinematic Manning discharge with an optional CONFINED rectangular channel
    section on channel cells.

    Overland cells (``chan_mask`` False) use the wide-channel shortcut R ≈ depth
    and a flow width of ``cell_size`` — reproducing ``mannings_velocity`` followed
    by ``cell_discharge`` *bit-for-bit* (same arithmetic, same grouping).  Channel
    cells use a true rectangular cross-section of width ``B`` (≪ cell_size):

        A   = B · h                       (cross-section area)
        P   = B + 2·h                     (wetted perimeter)
        R   = A / P = B·h/(B+2h)          (hydraulic radius; < h when B is finite)
        Q   = (1/n) · R^(2/3) · √S · A    [m³/s]

    Confining the flow to ``B`` instead of spreading it across the whole DEM cell
    makes channel cells run deeper and faster (correct celerity / attenuation),
    which the wide-sheet ``R ≈ depth`` assumption cannot capture.

    Parameters
    ----------
    depth     : (n,) array – flow depth [m] (channel cells: depth over B·L footprint)
    slope     : (n,) array – friction slope [m/m]
    n         : scalar or (n,) array – Manning's n
    width     : (n,) array – flow width [m]: cell_size overland, B on channel cells
    chan_mask : (n,) bool array – True where the rectangular section applies
    cell_size : float – DEM cell size [m] (overland width)
    xp        : array module (numpy or cupy)

    Returns
    -------
    Q    : (n,) array [m³/s]  – Manning discharge (pre flux-limiter)
    A_xs : (n,) array [m²]    – flow cross-section area; celerity uses c = 5/3·Q/A_xs
    """
    # Overland (wide sheet): identical arithmetic to the original kinematic path.
    velocity   = (1.0 / n) * (depth ** (2.0 / 3.0)) * (slope ** 0.5)
    Q_overland = velocity * cell_size * depth
    A_overland = depth * cell_size

    # Channel (rectangular): true hydraulic radius R = A/P.
    A_chan = depth * width
    R_chan = A_chan / (width + 2.0 * depth)
    Q_chan = (1.0 / n) * (R_chan ** (2.0 / 3.0)) * (slope ** 0.5) * A_chan

    Q    = xp.where(chan_mask, Q_chan, Q_overland)
    A_xs = xp.where(chan_mask, A_chan, A_overland)
    return Q, A_xs


def local_inertial_update(Q_inertia, Q_fric, A_xs, R, S, n, dt, xp, g=9.81):
    """
    One local-inertial (LISFLOOD-FP) momentum update per face, with de Almeida &
    Bates (2013) flux centering for stability.

    Keeps the local acceleration term ∂Q/∂t, but omits advective momentum.
    This is NOT the full shallow-water system and does not preserve general
    dam-break shocks. Flux centering introduces numerical diffusion. ``Q_inertia`` is the
    *centered* previous flux q* = θ·q_i + (1−θ)/2·(q_up + q_down) — the de Almeida
    stabilisation that suppresses the checkerboard oscillation the original Bates
    (θ=1) scheme suffers.  Friction is semi-implicit on the own-face flux ``Q_fric``,
    which also caps velocity physically (high |Q| grows the denominator):

        Q_{t+dt} = (q* + g·A·dt·S) / (1 + g·dt·n²·|q_i| / (A·R^{4/3}))

    S is the (signed) water-surface slope, POSITIVE downhill (caller's convention
    S = (WSE_i − WSE_ds)/Δx), so the pressure term ACCELERATES downstream flow.  A is
    the flow area, R the hydraulic radius over the flow-depth-above-the-higher-bed.
    Mass is conserved by the caller's volume ledger (Q·dt scattered downstream).
    """
    num = Q_inertia + g * A_xs * dt * S
    den = 1.0 + g * dt * (n * n) * xp.abs(Q_fric) \
        / xp.maximum(A_xs * R ** (4.0 / 3.0), 1e-30)
    return num / den


def diffusive_wave_discharge(depth, dem, dist, slope_bnd, n, ds_safe, valid_ds,
                             theta, cell_size, xp, min_depth, width, chan_mask,
                             slope_regularization=1e-6):
    """Downstream-only D8 diffusion-wave discharge with a regularized flat limit.

    Interior slope is (1-theta)*S_bnd + theta*((z_i-z_j)+(h_i-h_j))/L.
    Thus theta=1 uses the true stage gradient, including flat/adverse bed steps;
    theta=0 recovers kinematic Manning. Boundary links retain free normal outflow.
    Conveyance uses the blended own/higher-bed depth and rectangular hydraulic
    radius on channel cells. Dry conveyance is zero (min_depth is retained only
    for signature compatibility).

    On interior diffusive links sqrt(S) is replaced by
    S/sqrt(max(S, slope_regularization)), S=max(S_w, 0). This is continuous,
    exactly zero at level water, and matches Manning above the threshold. It
    changes the small-gradient constitutive law, so check epsilon sensitivity.
    Backflow is still suppressed: this is a directed network, not a 2-D solver.

    Returns (Q [m3/s], flow area [m2], nonnegative slope). The caller must use
    diffusive_inverse_timestep AND a conservative donor-volume limiter.
    """
    depth_ds = depth[ds_safe]
    dem_ds   = dem[ds_safe]

    # Difference bed and depth separately: adding small depths to large elevations
    # first loses the head difference especially with float32 DEMs.
    dz = dem - dem_ds
    S_w = (1.0 - theta) * slope_bnd + theta * (dz + depth - depth_ds) / dist
    # Free-outflow cells (no downstream) fall back to the kinematic bed slope.
    S_eff = xp.where(valid_ds, S_w, slope_bnd)
    S_eff = xp.maximum(S_eff, 0.0)                       # adverse gradient → no discharge

    # Conveyance depth: blend own depth (kinematic) with flow-depth-over-the-higher-bed
    # (LISFLOOD-FP diffusion-wave convention) by the SAME θ as the slope, so the two terms
    # stay a coherent pair — θ=0 → own depth + bed slope = kinematic exactly; θ=1 → higher-
    # bed depth + water-surface slope = full diffusion wave.  In the normal downhill case
    # the higher-bed depth already equals the upstream cell's own depth.
    h_higher = xp.maximum(depth, depth_ds - dz) - xp.maximum(-dz, 0.0)
    h_flow   = (1.0 - theta) * depth + theta * h_higher
    h_flow   = xp.where(valid_ds, h_flow, depth)          # free-outflow cells: own depth
    h_flow   = xp.maximum(h_flow, 0.0)  # dry cells have zero conveyance

    # Continuous linearization close to zero slope; unlike max(S, eps) this
    # produces exactly zero flux at level water. Above eps Manning is unchanged.
    # Only interior diffusive links are regularized (theta=0 stays kinematic).
    root_s = xp.sqrt(S_eff)
    if theta > 0 and slope_regularization > 0:
        root_s = xp.where(valid_ds, S_eff / xp.sqrt(
            xp.maximum(S_eff, slope_regularization)), root_s)

    # Conveyance discharge.  Overland (chan_mask False): wide sheet R≈h_flow,
    # width=cell_size — identical arithmetic to the original diffusive path.
    # Channel: confined rectangular section, true hydraulic radius R=A/P.
    Q_overland = (1.0 / n) * (h_flow ** (5.0 / 3.0)) * root_s * cell_size
    A_overland = h_flow * cell_size

    A_chan = h_flow * width
    R_chan = A_chan / (width + 2.0 * h_flow)
    Q_chan = (1.0 / n) * (R_chan ** (2.0 / 3.0)) * root_s * A_chan

    Q    = xp.where(chan_mask, Q_chan, Q_overland)
    A_xs = xp.where(chan_mask, A_chan, A_overland)
    # A_xs exposed so callers use the correct celerity denominator (c=5/3·Q/A_xs);
    # S_eff exposed for diagnostics.
    return Q, A_xs, S_eff


def diffusive_inverse_timestep(Q, A, slope, n, width, chan_mask, cell_size,
                               dist, store_area, ds_safe, valid_ds, theta,
                               slope_regularization, xp):
    """Conservative explicit rate bound [1/s] on the actual D8 storage graph.

    Each interior edge contributes its head conductance to BOTH incident cells;
    all tributaries are summed, including when the receiver is a narrow channel.
    The edge rate uses twice the tangent head conductance: the Manning secant
    above epsilon, and twice the linear conductance at/below epsilon. The latter
    factor is essential: a positivity-only bound allows alternating modes to
    flip sign on gently descending, nearly level water at CFL_TARGET > 0.5.
    On a uniform chain this bounds c/dx + 4D_tangent/dx². At zero slope the
    finite linearized conductance remains active even though Q=0.
    This is a local sufficient safeguard, not an accuracy or global TVD proof.
    """
    from ...utils.gpu_utils import scatter_add
    B = xp.where(chan_mask, width, cell_size)
    h = A / B
    R = xp.where(chan_mask, A / (B + 2*h), h)
    K = A * R**(2./3.) / n
    # 5/3 is an upper bound for rectangular Manning's logarithmic derivative.
    adv = (5./3.) * Q / xp.maximum(h, 1e-30)
    flat_factor = xp.where(slope <= slope_regularization, 2.0, 1.0)
    conductance = xp.where(valid_ds, flat_factor * theta * K /
        (dist * xp.sqrt(xp.maximum(slope, slope_regularization))), 0.)
    incident = adv + conductance
    incoming = xp.zeros_like(incident)
    # The extra conveyance term covers the blended higher-bed depth when theta<1.
    scatter_add(incoming, ds_safe[valid_ds],
                (conductance + theta * adv)[valid_ds])
    return (incident + incoming) / store_area


def normal_depth(Q_ref, slope, n, width, chan_mask, xp, iters=3):
    """
    Manning normal depth, matching the conveyance convention of ``mannings_discharge``.

    Given a reference discharge ``Q_ref`` [m³/s], solve Manning's equation for the
    flow depth ``h`` [m].  Overland cells (``chan_mask`` False) use the wide-sheet
    shortcut ``R ≈ h`` (``width = cell_size``), giving the exact closed form

        h = (n·Q/(B·√S))^(3/5)  ,   A_xs = B·h

    Confined channel cells (``chan_mask`` True, ``width = B ≪ cell_size``) use the
    true rectangular hydraulic radius ``R = A/P`` (``A = B·h``, ``P = B + 2h``),
    refined from the wide-sheet guess by a few Newton iterations — the same split
    ``mannings_discharge`` makes between overland and channel cells.

    Used by the Muskingum–Cunge scheme to obtain the reference flow area (hence
    celerity ``c = 5/3·Q_ref/A_xs``) from a rating rather than from a stored volume.

    Parameters
    ----------
    Q_ref     : (n,) array – reference discharge [m³/s] (negatives floored to 0)
    slope     : (n,) array – bed slope [m/m] (already floored at MIN_SLOPE)
    n         : scalar or (n,) array – Manning's n
    width     : (n,) array – section width B [m] (cell_size overland, B on channels)
    chan_mask : (n,) bool array – True where the rectangular R=A/P section applies
    xp        : array module (numpy or cupy)
    iters     : int – Newton iterations for channel cells (3 is ample)

    Returns
    -------
    h    : (n,) array [m]  – normal (flow) depth
    A_xs : (n,) array [m²] – flow cross-section area B·h  (celerity denominator)
    """
    sqrtS = xp.sqrt(slope)
    Qpos  = xp.maximum(Q_ref, 0.0)
    # Wide-sheet closed form (R ≈ h) — exact overland, Newton seed for channels.
    h   = (n * Qpos / (width * sqrtS + 1e-30)) ** 0.6
    ref = chan_mask & (Qpos > 1e-12)        # only refine wet channel cells
    for _ in range(iters):
        A  = width * h
        P  = width + 2.0 * h
        Qp = (1.0 / n) * sqrtS * A ** (5.0 / 3.0) / P ** (2.0 / 3.0)
        dQ = ((1.0 / n) * sqrtS * A ** (2.0 / 3.0) * P ** (-5.0 / 3.0)
              * ((5.0 / 3.0) * width * P - (4.0 / 3.0) * A))
        step = xp.where(ref, (Qp - Qpos) / xp.maximum(dQ, 1e-30), 0.0)
        h    = xp.maximum(h - step, 0.0)
    A_xs = width * h
    return h, A_xs


def mannings_celerity(Q, A, width, chan_mask, xp):
    """dQ/dA for Manning at fixed slope (rectangular channel or wide sheet).

    For a rectangle the factor multiplying Q/A decreases from 5/3 to 1 as
    depth/width increases; 5/3 is exact only for the wide-sheet approximation.
    """
    h = A / width
    exponent = xp.where(chan_mask, 1. + (2./3.) * width / (width + 2*h), 5./3.)
    return exponent * Q / xp.maximum(A, 1e-30)


def muskingum_cunge_step(I2, I1, O1, Q_L, c, A_xs, width, slope, dist, dt, xp,
                         Q_ref=None):
    """
    One variable-parameter Muskingum–Cunge (Ponce–Yevjevich) update per cell.

    Each D8 cell is treated as a reach of length ``dist``.  The outflow at the new
    time is

        O₂ = C0·I₂ + C1·I₁ + C2·O₁ + C3·Q_L          (C0 + C1 + C2 = 1)

    The Cunge coefficients match numerical diffusion to the hydraulic diffusivity
    D = Q/(2·B·S₀) in a linearized derivation. This is not a grid-independence
    guarantee for the nonlinear implementation:

        Cr = c·dt/dist                     (Courant number, c = dQ/dA)
        Dg = Q_ref/(B·S₀·c·dist)           (diffusion number; = 1 − 2X)
        C0 = (−1 + Cr + Dg)/denom ,  C1 = (1 + Cr − Dg)/denom
        C2 = ( 1 − Cr + Dg)/denom ,  C3 = (2·Cr)/denom ,  denom = 1 + Cr + Dg

    Q_ref supplied by the router uses the exact rectangular rating derivative.
    Omitting it retains the historical wide-sheet Dg expression for API compatibility.

    Nonnegative homogeneous coefficients require |1-Dg| <= Cr <= 1+Dg.
    Either C0 or C1 (or C2) can be negative outside this region. The O2>=0
    floor and a closed signed volume ledger do NOT establish positive storage,
    monotonicity, physical admissibility, or validity for dam-break shocks.

    Parameters
    ----------
    I2, I1 : (n,) arrays – inflow rate this / previous step [m³/s]
    O1     : (n,) array  – outflow rate previous step [m³/s]
    Q_L    : (n,) array  – lateral inflow rate (effective runoff) [m³/s]
    c      : (n,) array  – kinematic celerity dQ/dA [m/s]
    A_xs   : (n,) array  – reference flow area [m²]
    width  : (n,) array  – section width B [m]
    slope  : (n,) array  – bed slope [m/m]
    dist   : (n,) array  – reach length Δx [m]
    dt     : float       – time step [s]
    xp     : array module (numpy or cupy)

    Returns
    -------
    O2       : (n,) array [m³/s] – outflow this step (floored at 0)
    neg_frac : 0-d array         – fraction of cells whose raw O₂ was negative
                                   (floored) — a resolution diagnostic
    """
    Cr    = c * dt / dist
    h_eff = A_xs / xp.maximum(width, 1e-30)
    Dg    = (0.6 * h_eff / (slope * dist) if Q_ref is None else
             Q_ref / xp.maximum(width * slope * c * dist, 1e-30))
    denom = 1.0 + Cr + Dg
    C0 = (-1.0 + Cr + Dg) / denom
    C1 = ( 1.0 + Cr - Dg) / denom
    C2 = ( 1.0 - Cr + Dg) / denom
    C3 = ( 2.0 * Cr)       / denom
    O2 = C0 * I2 + C1 * I1 + C2 * O1 + C3 * Q_L
    neg      = O2 < 0.0
    neg_frac = neg.sum() / xp.maximum(O2.size, 1)
    O2 = xp.maximum(O2, 0.0)
    return O2, neg_frac


def flux_limiter(Q_out, volume, dt):
    """
    Donor-volume positivity limiter (not a stability or accuracy guarantee).

    Caps Q_out so that a cell can never drain more water than it currently
    stores in a single time step:

        Q_out_limited = min(Q_out, volume / dt)

    This preserves nonnegative storage when the same limited transfer enters
    the receiving cell. Frequent clipping distorts propagation; it does not
    enforce a diffusion stability bound or demonstrate physical accuracy.

    Parameters
    ----------
    Q_out  : 1-D float array  – Manning's discharge [m³/s] for each cell
    volume : 1-D float array  – current stored volume [m³] for each cell
    dt     : float            – time step [s]

    Returns
    -------
    Q_out_limited : 1-D float array  [m³/s]
    """
    return np.minimum(Q_out, np.maximum(volume, 0.0) / dt)


# ---------------------------------------------------------------------------
# 6.  Rainfall array builder
# ---------------------------------------------------------------------------

def build_rainfall_array(shape, intensity_mm_hr, duration_hours, dt_seconds, t_seconds):
    """
    Return a 2-D rainfall array (m/s) for the current simulation time.

    For a spatially uniform event:
        - intensity_mm_hr converted to m/s = intensity / (1000 * 3600)
        - Applied only while t_seconds < duration_hours * 3600

    The function signature accepts `shape` so it can later be replaced by a
    spatially variable (e.g., radar) array without changing the router logic.

    Parameters
    ----------
    shape           : (nrows, ncols) of the grid
    intensity_mm_hr : uniform rainfall rate [mm/hr]
    duration_hours  : rainfall duration [hr]
    dt_seconds      : time step [s]  (unused here; kept for API consistency)
    t_seconds       : current simulation time [s]

    Returns
    -------
    rain_ms : 2-D float64 array  (m/s)
    """
    rain_ms_value = (intensity_mm_hr / (1000.0 * 3600.0)
                     if t_seconds < duration_hours * 3600.0
                     else 0.0)
    return np.full(shape, rain_ms_value, dtype=np.float64)
