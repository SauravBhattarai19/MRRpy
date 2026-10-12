# Rainfall: the Rational method and the design rainfall

The regional formulas know only the catchment area. Rainfall-based methods
start from the rain that falls on *this* catchment and work out how much of it
becomes the flood. MRRpy-Nepal has two of them:

* the **Rational method**, the standard formula for small catchments in Nepal;
* the **MRRpy physics model**, which runs a design storm through runoff and
  routing on the DEM ([design floods](design-floods.md)).

Both need the same input: the **T-year 24-hour design rainfall** $R_{24}$. This
page explains the Rational method and how $R_{24}$ is worked out.

## The Rational method — `rational` {#rational}

*Compendium §3.8. Used by DoLIDAR, DoR (culverts), DoWRI (small schemes) and
municipalities.*

$$
\boxed{\;Q_T = \frac{C\,I_T\,A}{3.6}\;}
$$

| Symbol | Meaning | Unit |
|---|---|---|
| $Q_T$ | peak flood of return period $T$ | m³/s |
| $C$ | runoff coefficient: the share of the rain that runs off (0–1) | – |
| $I_T$ | rainfall intensity of return period $T$ for a duration equal to the time of concentration | mm/h |
| $A$ | catchment area | km² |
| 3.6 | unit conversion: 1 mm/h on 1 km² is $10^{-3}\,\text{m} \times 10^{6}\,\text{m}^2 / 3600\,\text{s} = 1/3.6$ m³/s | |

**The idea.** Rain of constant intensity falls on the whole catchment. The flow
at the outlet grows until water from the most distant point arrives, after the
**time of concentration** $t_c$. From then on the whole catchment contributes, and
the flow levels off at $C\,I\,A$. Shorter bursts of rain are more intense but do
not let the whole catchment contribute; longer ones are less intense. The worst
case is rain lasting exactly $t_c$, so $I$ is the intensity for a duration
$t_c$. The method also assumes that the $T$-year rain makes the $T$-year flood.

### Time of concentration: Kirpich {#kirpich}

$$
t_c = 0.0195\,L^{0.77}\,S^{-0.385} \quad \text{[minutes]}
$$

with $L$ the length of the longest flow path in **metres** and $S$ its average
slope (m/m), both [measured from the DEM](catchment.md). Longer and flatter
catchments take longer to concentrate.

### Intensity: Mononobe {#mononobe}

Nepal has few intensity–duration–frequency (IDF) curves, but DHM publishes the
24-hour rainfall. The Mononobe formula turns the 24-hour depth into an intensity
for any shorter duration $t$ (hours):

$$
I_t = \frac{R_{24}}{24}\left(\frac{24}{t}\right)^{2/3} \quad \text{[mm/h]}
$$

At $t = 24$ h it gives the 24-hour average $R_{24}/24$. Shorter durations are
more intense: one hour is $24^{2/3} = 8.32$ times the 24-hour average. The depth
that falls in the most intense $t$ hours is

$$
D(t) = I_t\,t = R_{24}\left(\frac{t}{24}\right)^{1/3},
$$

which the [design storm](design-floods.md#storm) of the physics model also uses.
The Rational method evaluates $I_t$ at $t = t_c/60$.

### Runoff coefficient

$C$ carries all the losses (infiltration, interception, depression storage) in
one number, and it dominates the answer: doubling $C$ doubles $Q$. Typical
values (compendium §3.8, after Subedi et al. 2022), also in
`MRRpy.nepal.methods.RUNOFF_COEFFICIENTS`:

| Land cover | C |
|---|---|
| Forest | 0.3 |
| Barren land | 0.25 |
| Agriculture | 0.5 |
| Built-up | 0.85 |

The DoLIDAR manual suggests 0.2–0.4 for small irrigation catchments. For a
catchment with several land covers, the usual practice is the area-weighted
mean $C = \sum_i C_i A_i / A$; MRRpy-Nepal takes the single value you give. It
must be in (0, 1].

### Worked examples

**65 km² Chure catchment** ($L$ = 15 km, $S$ = 0.015, $C$ = 0.45,
$R_{100}$ = 250 mm):

1. $t_c = 0.0195 \times 15000^{0.77} \times 0.015^{-0.385} = 0.0195 \times 1642.8
   \times 5.0374 = 161.4$ min $= 2.690$ h.
2. $I = (250/24) \times (24/2.690)^{2/3} = 10.417 \times 4.302 = 44.81$ mm/h.
3. $Q_{100} = 0.45 \times 44.81 \times 65 / 3.6 = 364.1$ m³/s.

The catchment is larger than 50 km², so the result is *outside its range* (see
below). It is kept in the table for comparison but left out of every official
range.

**8 km² culvert catchment** ($L$ = 4 km, $S$ = 0.04, $C$ = 0.4, $R_{24}$ =
120 mm for 2 years and 205 mm for 25 years):

1. $t_c = 0.0195 \times 4000^{0.77} \times 0.04^{-0.385} = 39.98$ min $= 0.666$ h.
2. $(24/0.666)^{2/3} = 10.91$, so $I_2 = 5.0 \times 10.91 = 54.53$ mm/h and
   $I_{25} = 8.542 \times 10.91 = 93.16$ mm/h.
3. $Q_2 = 0.4 \times 54.53 \times 8 / 3.6 = 48.47$ m³/s and $Q_{25} = 82.81$ m³/s.

### Validity

| Catchment area | Status | Why |
|---|---|---|
| up to 12 km² | ok | the size most manuals allow |
| 12–50 km² | *use with caution* | many design manuals use it only up to about 12 km² |
| above 50 km² | *outside its range* | the WECS Flood Control and Management Manual (2019) allows it only up to 50 km² |

Beyond a few tens of km² the assumptions fail: rain is not uniform over the
catchment, storage in the channels flattens the peak, and $t_c$ is hard to
define.

The notes of the Rational row always state $t_c$, $L$, $S$, $C$ and where
$R_{24}$ came from, so a reviewer can check every step.

## The design rainfall $R_{24}$ {#design-rainfall}

$R_{24}$ is the depth of rain in 24 hours with return period $T$, at the site.
Give it in one of two ways.

### 1. Typed values (`rain_24h`) {#typed-rainfall}

From a DHM station report, an IDF study or a rainfall atlas, as
`return period: mm` pairs:

```text
2: 120, 50: 230, 100: 250        (or 2=120 50=230 100=250)
```

Return periods you did not type, but which fall between two that you did, are
**interpolated linearly in the Gumbel reduced variate**

$$
y_T = -\ln\!\left(-\ln\!\left(1 - \frac{1}{T}\right)\right),
\qquad
R_T = R_{T_1} + \frac{y_T - y_{T_1}}{y_{T_2} - y_{T_1}}\,\left(R_{T_2} - R_{T_1}\right).
$$

Annual maximum rainfall is usually close to a Gumbel distribution, and on a
Gumbel scale the rainfall is a straight line in $y_T$. This interpolation is
therefore what a frequency plot would give. Outside the typed range nothing is
invented: the rainfall methods give no value there, with the flag *no rainfall
for this T*.

| T | 2 | 5 | 10 | 20 | 25 | 50 | 100 | 200 |
|---|---|---|---|---|---|---|---|---|
| $y_T$ | 0.3665 | 1.4999 | 2.2504 | 2.9702 | 3.1985 | 3.9019 | 4.6001 | 5.2958 |
| $R_{24}$ (mm) | 120 | ≈155.3 | ≈178.6 | ≈201.0 | ≈208.1 | 230 | 250 | – |

For example, at 10 years: $120 + (2.2504 - 0.3665)/(3.9019 - 0.3665) \times
(230 - 120) = 120 + 0.5329 \times 110 = 178.6$ mm.

### 2. A station record (`rain_annual_max`) {#rainfall-series}

One value per year: the largest daily rainfall of each year at a DHM station
near the site (a list, or a CSV file). MRRpy-Nepal fits a distribution to it
(Gumbel by default; `rain_distribution` can be `gumbel`, `lp3` or `gev`; see
[frequency analysis](frequency.md)) and reads off $R_{24}$ for every return
period. At least 10 years are needed, and fewer than 20 years carry a note.

**The daily-to-24-hour factor** (`rain_fixed_day_factor`). DHM stations are read
once a day, so the record holds rain in fixed *calendar* days. A storm that
straddles the reading time is split between two days, and the largest
fixed-day value is smaller than the largest rain in any 24 consecutive hours.
WMO practice multiplies fixed-day maxima by **1.13**. The factor is applied to
every value before the fit. The default is 1 (no correction).

*Example:* 20 years of station maxima (mean 119.95 mm; an example series, not
real data), Gumbel fit: $R_{24}$ = 116.0, 151.2, 182.1 and 195.1 mm for 2, 10,
50 and 100 years. With the factor 1.13: 131.1, 170.9, 205.8 and 220.5 mm.

### Factors on the design rainfall (physics model only)

The physics model can also scale $R_{24}$ by an **areal reduction factor** (point
rainfall → catchment average, for large catchments) and a **climate factor**
(for example 1.10 for +10 % under a climate scenario). See
[design floods](design-floods.md#design-rainfall).

## Inputs and where to give them

| Input | Notebook form / QGIS | Command line | Python (`inputs=`) |
|---|---|---|---|
| Runoff coefficient | under *Rational method* | `--C 0.45` | `runoff_coefficient` |
| Typed $R_{24}$ | *24-hour design rainfall* | `--rain24 2=120 100=250` | `rain_24h={2: 120, 100: 250}` |
| Station record | *Annual maximum daily rainfall* | `--rain-series rain.csv` | `rain_annual_max=[...]` or a CSV path |
| Its distribution | (choice) | `--rain-dist gev` | `rain_distribution="gev"` |
| Daily-to-24-hour factor | (advanced) | `--rain-factor 1.13` | `rain_fixed_day_factor=1.13` |

`L` and `S` come from the DEM, or from `--length-km` and `--slope` (form: the
*Site* tab) for typed numbers.

```python
from MRRpy.nepal import methods as m

tc = m.kirpich_tc_minutes(15_000, 0.015)          # 161.4 min
I = m.mononobe_intensity(250, tc / 60)            # 44.81 mm/h
m.rational_peak(0.45, I, 65)                      # 364.1 m³/s

r24, flags, notes, fit = m.design_rainfall({"rain_24h": {2: 120, 50: 230, 100: 250}},
                                           [2, 10, 100])
```

Next: [frequency analysis and donor gauges](frequency.md).
