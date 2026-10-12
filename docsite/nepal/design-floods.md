# Design floods with the physics model

The official formulas give one number per return period, from the catchment
area. The physics model gives the whole flood (peak, timing and volume) from the
rain, the soil, the slopes and the river network of *this* catchment. For small
Chure and Terai streams that is exactly what the national formulas lack
(compendium §6). MRRpy-Nepal builds the physics model's design flood from the
same rainfall rules Nepali practice uses, so the two can be compared fairly.

For each return period $T$ it does this:

1. take the T-year 24-hour design rainfall $R_{24}$ and apply the optional factors;
2. spread it in time as a **design storm** (Mononobe curve, alternating blocks);
3. write the storm as a one-gauge rain file that MRRpy reads with [[PRECIP_METHOD]] `thiessen`;
4. run MRRpy's runoff and routing on the delineated DEM;
5. read back the peak, the time of the peak, the volume and the runoff ratio, and
   place the peak against the official range.

## 1. The design rainfall {#design-rainfall}

$R_{24}$ is given exactly as for the Rational method: typed `T: mm` pairs, or a
station's annual maxima fitted with Gumbel, LP-III or GEV (with the optional
daily-to-24-hour factor). See [the design rainfall](rainfall-methods.md#design-rainfall).
Two optional factors then multiply it:

$$
R^{*}_{24} = R_{24} \times \text{ARF} \times \text{CF}
$$

| Factor | Default | Allowed | Use |
|---|---|---|---|
| ARF, areal reduction | 1 | $0 < \text{ARF} \le 1$ | point rainfall → catchment average, for large catchments |
| CF, climate factor | 1 | $\text{CF} > 0$ | e.g. 1.10 for +10 %: the ToR's climate delta factors |

## 2. The design storm {#storm}

### The Mononobe depth–duration curve

The Rational method takes its intensity from the
[Mononobe formula](rainfall-methods.md#mononobe). Integrated over a duration
$t$ (hours), that intensity gives the depth falling in the most intense $t$
hours:

$$
I(t) = \frac{R^{*}_{24}}{24}\left(\frac{24}{t}\right)^{2/3}
\quad\Longrightarrow\quad
D(t) = I(t)\,t = R^{*}_{24}\left(\frac{t}{24}\right)^{1/3}
$$

For $R^{*}_{24}$ = 250 mm: $D(1\,\text{h})$ = 86.7 mm, $D(3\,\text{h})$ = 125 mm,
$D(6\,\text{h})$ = 157.5 mm, $D(24\,\text{h})$ = 250 mm.

### Alternating blocks

The storm of duration $t_d$ is cut into $n = t_d/\Delta t$ blocks of length
$\Delta t$ (default 24 h and 15 min, so 96 blocks; $\Delta t$ must divide $t_d$):

1. **Cumulative depths** $D(\Delta t), D(2\Delta t), \dots, D(n\Delta t)$ from the
   Mononobe curve.
2. **Block depths** are their differences: $d_1 = D(\Delta t)$,
   $d_k = D(k\Delta t) - D((k-1)\Delta t)$. The curve is concave, so
   $d_1 > d_2 > \dots > d_n$.
3. **Arrange them** from a peak position outwards. The largest block goes at
   index $\min(\lfloor 0.5\,n \rfloor, n-1)$ (the middle; `peak_fraction` moves
   it, 0 = start, 1 = end). The next largest goes to its right, the next to its
   left, and so on, alternating; if one side is full, the rest go to the other.

Because the blocks are nested around the peak, **every duration inside the
storm carries its Mononobe depth**: the most intense hour holds $D(1)$, the most
intense three hours $D(3)$, the whole storm $D(t_d)$. One storm therefore suits
a catchment of any response time. The time of concentration does not have to
be known in advance, as it does for the Rational method.

*Example: 250 mm in 24 hours, 1-hour blocks.* The largest block, $D(1)$ = 86.67
mm, falls in hour 12–13. The second, $D(2) - D(1)$ = 22.53 mm, goes in hour
13–14, the third, $D(3) - D(2)$ = 15.80 mm, in hour 11–12, and so on:

| Hour | … | 9–10 | 10–11 | 11–12 | **12–13** | 13–14 | 14–15 | 15–16 | … |
|---|---|---|---|---|---|---|---|---|---|
| Rain (mm) | … | 8.30 | 10.62 | 15.80 | **86.67** | 22.53 | 12.58 | 9.29 | … |

Hours 11–14 hold $15.80 + 86.67 + 22.53 = 125.0$ mm $= D(3)$, and the 24 blocks
add up to 250 mm.

*Shorter storms.* A storm of $t_d < 24$ h holds the Mononobe depth for its
length, $D(t_d)$, not the whole $R_{24}$. A 3-hour storm of the same rainfall
holds 125 mm; in 30-minute blocks it is 7.37, 8.43, 12.54, **68.79**, 17.88 and
9.98 mm.

*Uniform pattern.* `pattern="uniform"` spreads $D(t_d)$ evenly over the storm.
It is offered for comparison; it lacks the intense burst, so it gives much lower
peaks (see [the results below](#how-the-choices-change-the-flood)).

### The rain files {#storm-files}

The storm is written as the two CSV files MRRpy already reads with
[[PRECIP_METHOD]] `thiessen`, with one gauge at the catchment outlet, so the
physics model needs no new rain option:

* `design_storm_gauge.csv`: `gauge_id, name, easting_m, northing_m` (gauge
  `G01`, in the model's map projection);
* `design_storm_rain.csv`: `time_s, G01`, where each value is the depth (mm)
  that fell in the interval ending at that row.

MRRpy turns each row into a rate (depth ÷ interval) and interpolates the rates
linearly in time. So each block is written as the depth at the block's **end**
time, with a zero row before the first and after the last block. The area under
the interpolated rate is then exactly the storm depth, and the storm is shifted
by half a block. A final zero row at the end of the run keeps the rain file as
long as the simulation. A 2-hour storm in 30-minute blocks, for a 6-hour run:

```text
time_s,G01
0.0,0.0
1800.0,9.98
3600.0,12.54
5400.0,68.79
7200.0,17.88
9000.0,0.0
21600.0,0.0
```

`MRRpy nepal design-storm --rain24 250` and the QGIS tool *4. Nepal design
storm* write these files (and `hyetograph.csv`) for any run of your own.

## 3. The model {#model}

By default (offline, no extra data) the design storm runs through this model,
built by `nepal_design_config`:

| Part | Setting |
|---|---|
| Runoff | SCS curve number, one value for the catchment (default 75), normal wetness (AMC II): [[RUNOFF_SOURCE]] `scs_cn` |
| Routing | kinematic wave: [[ROUTING_SCHEME]] `kinematic` |
| Channels | sized by the official 2-year flood at every cell: [[CHANNEL_QBF_M3S]] `wecs_nepal` |
| High ground | rain share 1 below 3,000 m, falling to 0 at 5,000 m: [[RAIN_SNOW_ELEV_LOW]] / [[RAIN_SNOW_ELEV_HIGH]] |

### SCS curve number {#scs-cn}

The SCS (NRCS) curve-number method splits the cumulative rain $P$ (mm) that has
fallen on a cell since the start of the storm into losses and **effective
rain** $P_e$ (mm), the part that runs off:

$$
S = \frac{25400}{CN} - 254, \qquad I_a = 0.2\,S, \qquad
P_e = \begin{cases} \dfrac{(P - I_a)^2}{P - I_a + S} & P > I_a\\[4pt] 0 & P \le I_a \end{cases}
$$

$S$ is the maximum retention of the soil (mm) and $I_a$ the initial abstraction,
the rain held before any runoff starts (interception, depressions, first
infiltration). The curve number $CN$ runs from about 30 (very permeable soil
under forest) to 98 (paved). MRRpy applies the formula to each cell's cumulative
rain at every time step and routes the increase in $P_e$ over the step as
runoff. The method describes one event (it does not recover between storms),
which is exactly what a design storm is.

| CN | $S$ (mm) | $I_a$ (mm) | $P_e$ for $P$ = 250 mm | Share that runs off |
|---|---|---|---|---|
| 60 | 169.3 | 33.9 | 121.2 mm | 48 % |
| 75 | 84.7 | 16.9 | 171.0 mm | 68 % |
| 80 | 63.5 | 12.7 | 187.2 mm | 75 % |
| 90 | 28.2 | 5.6 | 219.1 mm | 88 % |

The curve number is for normal antecedent wetness (AMC II), which is what the
default model uses. In your own model, [[RUNOFF_CN_AMC]] can convert it to dry
(AMC I, $CN/(2.281 - 0.01281\,CN)$) or wet conditions (AMC III,
$CN/(0.427 + 0.00573\,CN)$); CN 75 becomes 56.8 and 87.5. The initial
abstraction ratio 0.2 is [[RUNOFF_SCS_Ia_FACTOR]].

### Less rain on high ground {#snow-ramp}

The official $A_{3000}$ rule says ground above 3,000 m gives little flood runoff:
less monsoon rain falls there, and above about 5,000 m it falls as snow. The
physics model applies the same idea cell by cell. The rain reaching a cell at
elevation $z$ is multiplied by

$$
f(z) = \min\!\left(1, \max\!\left(0, \frac{z_{high} - z}{z_{high} - z_{low}}\right)\right),
\qquad z_{low} = 3000\ \text{m},\ z_{high} = 5000\ \text{m},
$$

so the share is 1 below 3,000 m, 0.5 at 4,000 m and 0 above 5,000 m. Untick
*Less rain above 3,000 m* (CLI `--no-snow-ramp`, study `snow_ramp: false`) to
switch it off. A model configuration that already sets its own
[[RAIN_SNOW_ELEV_LOW]] / [[RAIN_SNOW_ELEV_HIGH]] keeps them.

### Channels sized by the official 2-year flood {#channels}

Every river cell gets a channel that carries the bankfull flow, about the
2-year flood. The `wecs_nepal` preset evaluates the WECS/DHM 2-year formula at
every cell, with that cell's own drainage area below 3,000 m:

$$
Q_{bf} = 1.8767\,(A_{3000,\,cell} + 1)^{0.8783},
$$

and channel width and depth follow from $Q_{bf}$ (see
[river channels](../manual/channels.md)). In the small test basin the channels
carry 1.9–2.1 m³/s, and the outlet channel is 10.3 m wide and 0.12 m deep.

### Your own model

For a model of your own (Green–Ampt with soils from Earth Engine, another
routing scheme, roughness by land cover), give a config file: *Model settings
file* in the form, `--model-config run.yaml`, study `physics: {model_config:
run.yaml}`, or a config file as the site. MRRpy-Nepal replaces only its
rainfall (the storm files, [[PRECIP_METHOD]], the simulation length) and the
output file names. Everything else is your model.

## 4. Which return periods, and for how long {#runs}

**Return periods simulated.** One run per return period:

1. the ones you list (*Return periods to simulate*, `--physics-T 50 100`,
   study `physics: {return_periods: [50, 100]}`);
2. otherwise the structure's design return period(s): 100 years for a bridge,
   25 for a culvert, 50 and 100 for a weir;
3. otherwise 100 years if the table has it, else its largest return period.

A return period with no design rainfall (outside a typed table) is skipped, and
the notes say so.

**Length of each run.** The storm, plus time for the flood to pass the outlet:

$$
t_{sim} = t_d + \min\!\left(\max\!\left(6,\ 4\,t_c\right),\ 120\right)\ \text{h}
$$

with $t_c$ the [Kirpich time of concentration](rainfall-methods.md#kirpich) in
hours, or $t_{sim} = t_d + 24$ h when $L$ or $S$ is unknown. For the 65 km²
catchment ($t_c$ = 2.69 h) a 24-hour storm runs for 34.8 h. For the small test
basin ($t_c$ = 7 min) a 3-hour storm runs for 9 h. Set *Simulation length*
(`--sim-hours`) to override it.

## 5. The result {#result}

For each return period the physics flood is read from the run's
`hydrograph.csv` and the mass balance:

| Value | How it is computed |
|---|---|
| Peak (m³/s) | the largest outlet discharge `Q_m3s` |
| Time to peak (h) | the time of that largest discharge, from the start of the storm |
| Volume (m³) | $\int Q\,dt$ over the run (trapezoidal rule) |
| Runoff ratio | effective runoff ÷ gross rain over the catchment, from the mass balance |
| Storm (mm) | the total depth of the storm applied, after the factors and the Mononobe depth for its length |

The peak becomes the `physics` row of the table, and the report says whether it
lies inside, above or below the [official range](results.md#official-range),
and its ratio to the official median.

### How the choices change the flood

Four runs on the small synthetic basin of MRRpy's test suite (0.108 km², 100-year
$R_{24}$ = 250 mm, a 3-hour storm in 15-minute blocks), with the official range
of WECS/DHM and DHM 2004 at 4.17–15.8 m³/s:

| Run | Storm | Peak | Time to peak | Volume | Runoff ratio |
|---|---|---|---|---|---|
| CN 80, centre-peaked | 125 mm | 3.187 m³/s | 2.0 h | 7,740 m³ | 0.57 |
| CN 80, climate factor 1.1 | 138 mm | 3.755 m³/s (+18 %) | 2.0 h | 8,920 m³ | 0.60 |
| CN 70, centre-peaked | 125 mm | 1.934 m³/s (−39 %) | 2.0 h | 5,410 m³ | 0.40 |
| CN 80, uniform storm | 125 mm | 1.051 m³/s (−67 %) | 3.0 h | 7,740 m³ | 0.57 |

What they show:

* **+10 % rain gives +18 % peak.** The SCS losses are almost fixed, so extra rain
  runs off nearly in full. Climate factors therefore matter more for floods than
  for rainfall.
* **The curve number is the most uncertain input.** Ten points of CN change the
  peak by 40 %. Choose it from soil and land cover, and check it against a gauge
  or flood marks when you can.
* **The time pattern matters as much as the depth.** The same 125 mm spread
  evenly gives a third of the peak. The centre-peaked storm keeps the Mononobe
  intensity for every duration, which is why it is the default.

The report line of the first run:

```text
T = 100 years: 125 mm in 3 h (R24 250 mm) → peak 3.187 m³/s at 2.0 h,
volume 0.00774 Mm³, runoff ratio 0.57. It is below the official range
(4.169–15.77 m³/s), 0.3196× the official median.
```

Each run writes to `<results>/nepal/design_T<T>/`: `hyetograph.csv`, the
storm's gauge files, `hydrograph.csv`, and `gauges.csv` and maps when
[[ROUTING_GAUGES]] or [[SAVE_FIELDS]] are set, so the 100-year flood can be
mapped with [`export_peak_maps`](../reference/api.md#plotting). All runs append
to `<results>/nepal/mass_balance_design.csv`. The results folder's own
`hydrograph.csv` and `gauges.csv` are left as they were.

!!! tip "When the physics flood is outside the official range"
    That is not wrong in itself: the national formulas were fitted mostly to
    large mountain rivers. Check the inputs first: the design rainfall, the curve
    number (or soil parameters), the storm pattern and the roughness. Then compare
    with any gauge nearby (frequency analysis) or surveyed flood marks
    (`observed_floods`). Calibrating the model to a gauge or to flood marks is
    planned (see `NEPAL_PLAN.md`).

## Setting it up

=== "Notebook form"

    In the **Methods** tab tick **MRRpy physics model**. Its branch shows the
    curve number, the return periods to simulate, the storm pattern, duration
    and time step, the climate and areal-reduction factors, *Less rain above
    3,000 m* and an optional model settings file. The physics model needs a DEM
    site (a results folder, a config file or a DEM and an outlet).

=== "Command line"

    ```bash
    MRRpy nepal estimate --results results/ --agency dor_bridge --structure bridge \
        --rain24 2=120 100=250 --physics --cn 80 --climate-factor 1.1

    MRRpy nepal design-storm --rain24 250 --duration 6 --step 30 \
        --results results/ -o storm/          # just the storm files
    ```

=== "Study file"

    ```yaml
    site:
      results: results/
    agency: dor_bridge
    structure: bridge
    inputs:
      rain_24h: {2: 120, 100: 250}
    physics:
      enabled: true
      curve_number: 80
      climate_factor: 1.1
      duration_h: 24
      step_min: 15
    ```

=== "Python"

    ```python
    from MRRpy.nepal import NepalStudy
    from MRRpy.nepal.physics import nepal_design_config, run_design_floods
    from MRRpy.nepal.design_storm import design_hyetograph

    study = NepalStudy.from_results("results/", agency="dor_bridge", structure="bridge",
                                    inputs={"rain_24h": {2: 120, 100: 250}},
                                    physics={"curve_number": 80, "climate_factor": 1.1})
    result = study.run()
    result.physics[100.0].summary()

    # the same, one level down
    cfg = nepal_design_config("results/", curve_number=80)
    floods = run_design_floods(cfg, {100: 250.0}, climate_factor=1.1)
    design_hyetograph(250, duration_h=24, step_min=60)      # the storm as a table
    ```

## Bankfull presets for any MRRpy run {#bankfull-presets}

Three Nepal presets of [[CHANNEL_QBF_M3S]] evaluate an official 2-year flood at
every cell. They work in any MRRpy run, not only in MRRpy-Nepal:

| Preset | Formula | From |
|---|---|---|
| `wecs_nepal` | $1.8767\,(A_{3000}+1)^{0.8783}$ | WECS/DHM 1990 $Q_2$ |
| `dhm2004_nepal` | $2.29\,A_{3000}^{0.86}$ | DHM 2004 $Q_2$ |
| `specific_q_nepal` | $4.2\,A^{0.70}$ | WECS 2019 specific discharge, $q_2 = 4.2\,A^{-0.30}$ (fitted above 12 km²) |

```yaml
CHANNEL_QBF_M3S: dhm2004_nepal
```

Next: [monthly and low flows](monthly-flows.md).
