# Gauges: frequency analysis, donor gauges and flood marks

Where floods have been measured, the record is the best evidence there is.
MRRpy-Nepal uses it in three ways:

* **frequency analysis** of a gauge at the site (`frequency`);
* the **catchment area ratio**, which moves the floods of a nearby gauge to the
  site (`area_ratio`);
* **flood marks**, which give the peak of one past flood (the slope–area
  method).

The same frequency analysis fits the station rainfall record that feeds the
[Rational method and the physics model](rainfall-methods.md#rainfall-series).

## The annual maximum series

Frequency analysis needs **one value per year**: the largest instantaneous peak
flow (or the largest daily rainfall) of each year. From a DHM daily or
instantaneous record:

```python
from MRRpy.nepal import frequency

peaks = frequency.annual_maxima(daily_series)                 # calendar years
peaks = frequency.annual_maxima(daily_series, start_month=4)  # years starting in April
values = frequency.read_series("peaks.csv")                   # a CSV of annual maxima
```

`read_series` takes a single column of numbers, or a table with a year column
and a value column (the last numeric column, or the one named with `column=`).
Blank years are dropped.

**How much data.** Fewer than **10** years and the fit is refused. Fewer than
**20** years and the result carries a note ("about 20 or more are needed for a
dependable fit", as the compendium says). A return period more than **twice the
record length** is flagged *extrapolated*: 20 years of data say little about the
100-year flood.

### Plotting positions

To compare a fitted curve with the data, each observed flood gets an empirical
return period from its rank $m$ (1 = largest) among $n$ years, by the
**Weibull** formula:

$$
T_m = \frac{n + 1}{m}
$$

For the 20-year example below, the largest flood (820 m³/s) plots at 21 years,
the second (720) at 10.5 years and the third (700) at 7 years.
`frequency.plotting_positions(values)` returns these points.

### The example series

The worked examples use this series of 20 annual maximum floods (m³/s). It is
an **example series, not real data**:

```text
410 380 655 520 300 720 450 390 610 505 470 820 360 540 430 600 495 380 700 455
```

Mean $\bar x$ = 509.5 m³/s, standard deviation $s$ = 136.90 m³/s.

## Gumbel (EV1) by the method of moments {#gumbel}

The Gumbel or Extreme Value type I distribution is the classical model for
annual maxima:

$$
F(x) = \exp\!\left[-\exp\!\left(-\frac{x - u}{\alpha}\right)\right]
$$

Its mean is $u + 0.5772\,\alpha$ and its standard deviation $\pi\alpha/\sqrt6$.
Setting these equal to the sample mean $\bar x$ and standard deviation $s$ (with
$n-1$), and solving $F(x_T) = 1 - 1/T$, gives the **frequency-factor** form of
the compendium (§3.11):

$$
x_T = \bar x + K_T\,s, \qquad
K_T = -\frac{\sqrt 6}{\pi}\left[0.5772 + \ln\!\left(\ln\frac{T}{T-1}\right)\right]
$$

| T | 2 | 10 | 50 | 100 |
|---|---|---|---|---|
| $K_T$ | −0.1643 | 1.3046 | 2.5923 | 3.1367 |
| $x_T = 509.5 + K_T \times 136.90$ (m³/s) | 487.0 | 688.1 | 864.4 | 938.9 |

$K_T$ does not depend on the data, so the Gumbel curve has a fixed shape
(skewness 1.14); only its position and spread are fitted.

## Log-Pearson type III {#lp3}

*Named in the DoLIDAR manual.* Fit a Pearson type III distribution to the
logarithms $y = \log_{10} x$:

$$
\log_{10} x_T = \bar y + K_T(g)\,s_y
$$

with $\bar y$ and $s_y$ the mean and standard deviation ($n-1$) of the logs, and
$g$ their **station skew**, corrected for sample-size bias:

$$
g = \frac{n \sum (y_i - \bar y)^3}{(n-1)(n-2)\,s_y^3}
$$

$K_T(g)$ is the exact quantile of the standardised Pearson III distribution with
skew $g$ (`scipy.stats.pearson3`), so no frequency-factor table is needed. For
$g = 0$ it equals the normal variate $S_T$, and LP-III reduces to the log-normal
distribution.

*Example:* $\bar y$ = 2.6928, $s_y$ = 0.11392, $g$ = 0.1901.

| T | 2 | 10 | 50 | 100 |
|---|---|---|---|---|
| $K_T(g)$ | −0.0317 | 1.3002 | 2.1542 | 2.4651 |
| $x_T$ (m³/s) | 488.9 | 693.3 | 867.4 | 941.1 |

Every value must be above 0 (logarithms). MRRpy-Nepal uses the station skew
alone; regional-skew weighting and low-outlier tests (as in the US Bulletin 17)
are not applied.

## GEV by L-moments {#gev}

The Generalised Extreme Value distribution adds a **shape** parameter $k$ to
Gumbel, so the tail can be heavier ($k < 0$) or bounded ($k > 0$). It is fitted
by **L-moments** (Hosking 1990), which are less affected by one or two extreme
values than ordinary moments.

**1. Probability-weighted moments** of the sorted sample $x_{(1)} \le \dots \le
x_{(n)}$:

$$
b_0 = \bar x, \quad
b_1 = \frac1n \sum_{j=1}^{n} \frac{j-1}{n-1}\,x_{(j)}, \quad
b_2 = \frac1n \sum_{j=1}^{n} \frac{(j-1)(j-2)}{(n-1)(n-2)}\,x_{(j)}
$$

**2. L-moments** and the L-skewness $\tau_3$:

$$
\lambda_1 = b_0, \quad \lambda_2 = 2b_1 - b_0, \quad
\lambda_3 = 6b_2 - 6b_1 + b_0, \quad \tau_3 = \lambda_3/\lambda_2
$$

**3. Parameters** by Hosking's approximation for the shape:

$$
c = \frac{2}{3 + \tau_3} - \frac{\ln 2}{\ln 3}, \qquad
k = 7.8590\,c + 2.9554\,c^2,
$$

$$
\alpha = \frac{\lambda_2\,k}{(1 - 2^{-k})\,\Gamma(1 + k)}, \qquad
\xi = \lambda_1 - \frac{\alpha\,(1 - \Gamma(1 + k))}{k}
$$

**4. Quantile:**

$$
x_T = \xi + \frac{\alpha}{k}\left[1 - \left(-\ln F\right)^{k}\right], \qquad F = 1 - \frac1T
$$

When $|k| < 10^{-6}$ the Gumbel limit is used: $\alpha = \lambda_2/\ln 2$,
$\xi = \lambda_1 - 0.5772\,\alpha$ and $x_T = \xi - \alpha\ln(-\ln F)$. Hosking's
approximation is accurate for $-0.5 < \tau_3 < 0.5$; outside that range the fit
carries a note. The sign convention is Hosking's ($k > 0$ bounds the upper tail),
the same as SciPy's `genextreme` shape $c$.

*Example:* $b_0$ = 509.5, $b_1$ = 293.96, $b_2$ = 211.36, so $\lambda_2$ = 78.42
and $\tau_3$ = 0.1770. Then $c$ = −0.001397, $k$ = −0.01097 (a slightly heavy
tail, close to Gumbel), $\alpha$ = 111.99 and $\xi$ = 443.63.

| T | 2 | 10 | 50 | 100 |
|---|---|---|---|---|
| $x_T$ (m³/s) | 484.8 | 698.8 | 890.1 | 972.0 |

## Confidence bands by the bootstrap {#bootstrap}

The DoWRI pilot ToR asks for confidence bounds, and with 20 years of data they
are wide. MRRpy-Nepal computes them by the **bootstrap**:

1. draw $n$ years at random *with replacement* from the record;
2. fit the same distribution to that resample and compute its $x_T$;
3. repeat 1,000 times;
4. the 5th and 95th percentiles of the 1,000 values of $x_T$ form the **90 %
   band** (change it with `ci=`; CLI `--ci`).

The resampling uses a fixed seed (20241012), so a result can be reproduced
exactly. A resample that cannot be fitted (for example every value equal) is
skipped.

| Distribution | Q2 | Q10 | Q50 | Q100 |
|---|---|---|---|---|
| Gumbel | 487.0 (440–540) | 688.1 (600–758) | 864.4 (730–964) | \*938.9 (783–1051) |
| LP-III | 488.9 (439–550) | 693.3 (601–768) | 867.4 (718–973) | \*941.1 (760–1069) |
| GEV | 484.8 (434–553) | 698.8 (600–770) | 890.1 (719–986) | \*972.0 (752–1116) |

\* 100 years is more than twice the 20-year record.

The three distributions agree within 4 % here, but each 100-year value has a
band of about ±15 %. The choice of distribution matters less than the length of
the record.

### Choosing a distribution

```bash
MRRpy nepal frequency peaks.csv --T 2 10 50 100
```

prints all three fits side by side with their bands and notes
(`frequency.compare_distributions` in Python). Practical guidance:

* Gumbel and LP-III are the methods the DoLIDAR manual names; GEV by L-moments
  is the modern choice and is robust to a single outlier;
* plot the fitted curves over the [plotting positions](#plotting-positions) and
  prefer the one that follows the largest floods;
* if the fits disagree strongly, the record is probably too short. Say so,
  rather than picking the highest or the lowest;
* for a design, report the band as well as the central value.

## Frequency analysis in a study — `frequency`

*Compendium §3.11. Used by every agency when data exist.*

Give the site's annual maxima (input `flood_annual_max`, CLI `--flood-series
peaks.csv`) and the distribution (`flood_distribution`, default Gumbel; CLI
`--flood-dist`). The `frequency` row then holds $x_T$ for every return period,
with its band (drawn on the chart), *extrapolated* flags for $T > 2n$, and notes
saying which distribution was fitted to how many years. Frequency analysis is
not one of the regional formulas, so it is compared with the official range but
never part of it.

## Catchment area ratio — `area_ratio` {#area-ratio}

*Compendium §3.12. Used by DoED and consultants.* A gauge on a similar nearby
river (the **donor**) is moved to the site:

$$
Q_{site,T} = Q_{donor,T}\left(\frac{A_{site}}{A_{donor}}\right)^{n}
$$

**The exponent $n$.** Flood per km² falls as catchments grow, so floods grow
less than in proportion to area and $n < 1$. The compendium gives 0.5–0.85 for
floods (0.75–0.85 for mountain streams). MRRpy-Nepal uses **0.8** by default
(input `area_ratio_exponent`, CLI `--area-exponent`). For mean flows $n = 1$; see
[monthly flows](monthly-flows.md#area-ratio-flows).

**The donor floods** are given one of two ways:

* typed `T: m³/s` pairs (`donor_floods`, CLI `--donor-floods 2=900 100=4200`).
  Only return periods you typed get a value (no interpolation); others are
  flagged *no donor flood for this T*;
* the donor's annual maxima (`donor_annual_max`, CLI `--donor-series`), fitted
  with the flood distribution. The bootstrap band is scaled by the same factor.

**Validity.** *Use with caution* when the site is less than half or more than
twice the donor's area: area transfers are usually trusted only within about a
factor of 2, and the donor must be shown to be hydrologically similar (same
region, similar elevation range, rainfall and geology).

*Example (compendium):* Kankai at Mainachuli (1,148 km²) moved to the Ratuwa
bridge (430 km²). The area ratio is 430/1148 = 0.375. With $n$ = 0.8 the factor is
$0.375^{0.8} = 0.456$; with $n$ = 1 it would be 0.375. If the donor's floods were
900 and 4,200 m³/s (illustrative values), the site gets 410.3 and 1,915 m³/s.
The ratio is below 0.5, so the row is *use with caution*.

## Flood marks: the slope–area method {#flood-marks}

*Compendium §3.13.* After a big flood, the high-water marks on the banks give
the water surface. Survey a cross-section and the water-surface slope, and
Manning's equation gives the peak:

$$
Q = \frac1n\,A\,R^{2/3}\,S^{1/2}, \qquad R = \frac{A}{P}
$$

with $A$ the flow area (m²), $P$ the wetted perimeter (m), $R$ the hydraulic
radius (m), $S$ the water-surface slope (m/m) and $n$ Manning's roughness.

*Example:* $A$ = 120 m², $P$ = 48 m (so $R$ = 2.5 m), $S$ = 0.004, $n$ = 0.035 →
$Q = (1/0.035) \times 120 \times 2.5^{2/3} \times 0.004^{1/2} = 399.4$ m³/s.

```python
from MRRpy.nepal import slope_area_discharge
slope_area_discharge(area_m2=120, perimeter_m=48, slope=0.004, n=0.035)   # 399.4
```

The return period of a marked flood is unknown, so it is not a row of the
table. Give it as an **observed flood** instead (study `observed_floods=[("2021
flood marks", 400)]`, CLI `--observed "2021 marks=400"`, form: *Observed
floods*). It is drawn as a horizontal reference line on the chart and listed in
the report. A design flood well below a flood that has already happened needs
explaining.

## In code

```python
from MRRpy.nepal import frequency

fit = frequency.fit_annual_maxima(values, [2, 10, 50, 100], "gev")   # 90 % band
fit.quantiles, fit.lower, fit.upper, fit.params, fit.warnings
fit.to_frame()                                    # T, value, lower_90, upper_90
frequency.compare_distributions(values, [2, 10, 100])
frequency.gumbel_frequency_factor([2, 100])        # array([-0.1643,  3.1367])
```

Next: [design floods with the physics model](design-floods.md).
