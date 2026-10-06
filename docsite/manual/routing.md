# 5 Routing: method and time

Routing moves the runoff downhill, from cell to cell along the D8 flow
directions, until it leaves the model. This page covers **how** water moves (the
routing method), **for how long** the model runs and with **what time step**, and
the numerical safeguards. The other parts of the routing step are on their own
pages: [5.4 Ground roughness](roughness.md), [5.5 River channels](channels.md)
and [5.6 Water entering from upstream](inflows.md).

!!! info "Where to set it"
    Notebook form: step **5 Routing** (the method's own settings open under it)
    · Wizard: part **5 Routing and simulation time** · QGIS: tab **4 · Routing**,
    *Routing Scheme* and *Time Stepping* (safeguards under *Advanced numerics*).

Every method solves the same **water balance** for each cell: the change in
stored water equals rain-made runoff plus inflow from upstream cells minus
outflow,

$$
\frac{dV_i}{dt} = q_i\,A_{cell} + \sum_{j \to i} Q_j - Q_i ,
$$

and they differ in how they compute the outflow $Q_i$. All of them use
**Manning's equation**, the flow rate of water of depth $h$ over a surface of
roughness $n$ and slope $S$:

$$
Q = \frac{1}{n}\, A\, R^{2/3}\, S^{1/2}
$$

with $A$ the flow area and $R$ the hydraulic radius ($R \approx h$ for a wide
sheet of water; for river channels see [5.5](channels.md)). The water balance is
always closed: a run reports any lost or created water in
[`mass_balance.csv`](outputs.md#64-the-water-balance).

## 5.1 Routing method

| Method | `ROUTING_SCHEME` | Slope used | Good for | Speed |
|---|---|---|---|---|
| Kinematic wave | `kinematic` (0) | the ground slope | steep basins, quick looks | fast (CPU or GPU) |
| Diffusive wave, explicit | `diffusive` (1) | the water-surface slope | *deprecated*: use `diffusive_implicit` | slow on flat ground |
| Muskingum–Cunge | `muskingum` (2) | the ground slope, with matched diffusion | attenuation that doesn't depend on cell size | medium |
| Local inertial | `dynamic` (3) | the water surface, with inertia | *experimental, under development* | slow |
| Diffusive wave, implicit | `diffusive_implicit` (4) | the water-surface slope | backwater, flat valleys, lakes; any basin | fast, large steps (CPU only) |

**Kinematic wave** (`kinematic`). Outflow from Manning's equation with the
**ground slope**. Water can only go downhill and a cell can't feel what happens
downstream, so there is no backwater. It is the simplest and fastest method and
works well on steep terrain. On flat ground it can't pond water behind a
constriction, and a flood peak loses little height as it travels: in
[Example 3](../examples/routing-schemes.md) it gives the highest, earliest peak
of the three methods.

**Diffusive wave, explicit** (`diffusive`). Uses the **water-surface slope**
$S_w = S_0 + \theta\,(h_i - h_{down})/\Delta x$ instead of the ground slope, so a
deep pool downstream slows the flow (backwater), and peaks flatten as they
travel. `DIFFUSION_THETA` blends between kinematic (0) and full diffusion (1).
Because it is explicit, it needs tiny time steps on flat or ponded water. It is
**deprecated**: `diffusive_implicit` solves the same physics and is stable.

**Muskingum–Cunge** (`muskingum`). Treats each cell as a short river reach with
the classic Muskingum update,

$$
O_2 = C_0 I_2 + C_1 I_1 + C_2 O_1 + C_3 Q_L ,
$$

where $I$ is inflow, $O$ outflow and $Q_L$ the runoff entering the reach. The
coefficients come from the Courant number $C_r = c\,\Delta t/\Delta x$ and a
cell Péclet number $D_g = (3/5)\,h/(S_0 \Delta x)$, chosen (Cunge's method,
variable-parameter form of Ponce & Yevjevich) so the scheme's numerical
diffusion **equals** the physical diffusion of a flood wave. The peak's
attenuation therefore doesn't depend on the cell size. Like the kinematic wave it
has no backwater.

**Local inertial** (`dynamic`). Keeps the inertia term of the shallow-water
equations (LISFLOOD-FP; Bates et al. 2010, with de Almeida et al. 2012 flux
centering), so sharp surges such as dam breaks travel at the right speed.
**This method is still under development.** Its results may change, and it
isn't recommended for studies yet.

**Diffusive wave, implicit** (`diffusive_implicit`). The diffusive wave solved
**implicitly**, as HEC-RAS does for its 2D diffusion-wave equations. Each step
solves for the new water-surface elevations of all cells together:

$$
\frac{A_{store,i}}{\Delta t}\left(z_i^{n+1} - z_i^n\right)
= \sum_{j \to i} K_{j}\left(z_j^{n+1} - z_i^{n+1}\right) - K_i\left(z_i^{n+1} - z_{down}^{n+1}\right) + q_i A_{cell}
$$

with $z$ the water-surface elevation and $K$ a conductance from Manning's
equation, $K = A R^{2/3} / (n\,\Delta x \sqrt{|S_w|})$. Because D8 flow forms a tree,
this system is solved exactly in one sweep up and one down the tree, in time
proportional to the number of cells. The conductances depend on the new levels,
so each step is repeated (Picard iteration, `IMPLICIT_MAX_ITERS`) until the
levels change by less than `IMPLICIT_TOL`. The method is stable at any time step,
handles backwater and flat ground, and takes steps many times longer than the
explicit methods. It runs on the CPU only; with `BACKEND = gpu` it still runs, on
the CPU. The solver uses Numba when it is installed (`IMPLICIT_SOLVER`).

!!! tip "Which method?"
    Start with **`diffusive_implicit`** when backwater or flat ground matters,
    or when you want peaks that don't depend much on the time step. Use
    **`kinematic`** for steep basins, quick looks and the GPU. Use
    **`muskingum`** to compare. Because every method reads the same
    configuration, comparing them means changing one setting:
    [Example 3](../examples/routing-schemes.md).

<!-- settings: ROUTING_SCHEME DIFFUSION_THETA DYNAMIC_FLUX_THETA IMPLICIT_SOLVER IMPLICIT_NUM_THREADS IMPLICIT_THETA IMPLICIT_MAX_ITERS IMPLICIT_TOL IMPLICIT_RELAX IMPLICIT_SLOPE_FLOOR -->

## 5.2 Simulation time and time step

The run starts when the rain starts and lasts `TOTAL_SIMULATION_TIME_HOURS`. Make
it long enough for the flood to pass the outlet: the storm duration plus the
travel time through the basin, plus the recession you want to see. Results
(the hydrograph, gauges and maps) are recorded every `OUTPUT_INTERVAL_SECONDS`.

**Time step.** The model advances in steps of $\Delta t$ seconds.

- The **explicit** methods (`kinematic`, `diffusive`, `muskingum`, `dynamic`) are
  stable only if water doesn't cross more than about one cell per step: the
  **Courant condition**

  $$
  \Delta t \le C\,\frac{\Delta x}{c_{max}}
  $$

  with $c$ the speed of the flood wave ($c = \tfrac{5}{3}V$ for Manning flow) and
  $C$ = `CFL_TARGET`. With `ADAPTIVE_TIMESTEP` on (the default), MRRpy recomputes
  $\Delta t$ every step from the fastest wave in the grid, keeps it between
  `CFL_DT_MIN` and `CFL_DT_MAX`, and lets it grow by at most `CFL_DT_GROW` times
  per step. When the wave is too fast even for `CFL_DT_MIN`, the
  [flux limiter](#53-numerical-safeguards) keeps the step stable.
- The **implicit** method is stable at any step, so $\Delta t$ only controls
  accuracy. The adaptive step aims at a Courant number of `IMPLICIT_CFL_TARGET`
  (1–3 is typical: far longer steps than the explicit limit) and is capped at
  the output interval, not at `CFL_DT_MAX`. If a step would drain any cell
  more than `IMPLICIT_TOL` below empty, MRRpy throws that step away and
  repeats it at half the length, down to `CFL_DT_MIN`. Without this, the
  shortfall would be refilled with water that was never there. It mostly
  happens on the first wet step after a dry spell, because the step has grown
  to the output interval while nothing was flowing. The run summary reports
  how many steps were repeated.

With `ADAPTIVE_TIMESTEP` off, every step is `TIME_STEP_SECONDS` long; with it on,
`TIME_STEP_SECONDS` is only the first step.

<!-- settings: TOTAL_SIMULATION_TIME_HOURS OUTPUT_INTERVAL_SECONDS TIME_STEP_SECONDS ADAPTIVE_TIMESTEP CFL_TARGET IMPLICIT_CFL_TARGET CFL_DT_MAX CFL_DT_MIN CFL_DT_GROW -->

## 5.3 Numerical safeguards

These keep the model physical in awkward places. The defaults suit almost every
run.

- **`MIN_SLOPE`**. A perfectly flat cell has no slope, so Manning's equation
  would give no flow. Every cell gets at least this slope. It is also the
  smallest slope given to flats by the `carve_spread`
  [DEM conditioning](terrain.md#14-terrain-processing-advanced).
- **`MIN_DEPTH_M`**. Water thinner than this counts as dry and doesn't flow.
- **`MANNING_SLOPE_CAP`**. On near-vertical cliffs, Manning's equation gives
  unrealistic speeds (over 100 m/s). A cap such as 0.05–0.10 limits the slope used
  for flow speed. Off by default.
- **`FLUX_LIMITER`**. For the kinematic and explicit diffusive methods: a cell may
  never send out more water in one step than it holds,
  $Q\,\Delta t \le V$. It conserves water and is the explicit methods' safety net.
  Turn it off only with an adaptive time step.

<!-- settings: MIN_SLOPE MIN_DEPTH_M MANNING_SLOPE_CAP FLUX_LIMITER -->

## Try it

- [Example 3 – Compare routing methods](../examples/routing-schemes.md).
- [Example 8 – Route an inflow hydrograph](../examples/inflow-hydrograph.md).
