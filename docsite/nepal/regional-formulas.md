# Official regional flood formulas

The regional formulas are regressions fitted to the floods recorded at DHM
gauges. They give the peak flood of a return period $T$ from the catchment alone,
with no rainfall, soil or slope, so they work for any site where a DEM or a map
is available. They are the backbone of most Nepali design reports. This page
explains each formula used by MRRpy-Nepal: what it means, how it is computed,
where it is valid, and what the compendium *Nepal Flood Estimation Methods* warns
about. Section numbers (§) refer to the compendium.

Units throughout: $Q$ in m³/s, areas in km², $T$ in years.

The **worked example** on this page is the compendium's 65 km² snow-free Chure
catchment ($A = A_{3000} = 65$ km², no snow). MRRpy-Nepal reproduces each of its
numbers in `tests/test_nepal_methods.py`.

## Return period and the standard normal variate {#normal-variate}

A flood with return period $T$ is exceeded in any one year with probability
$1/T$. The 100-year flood has a 1 % chance each year, and about a 26 % chance of
being exceeded at least once in 30 years ($1 - 0.99^{30}$).

The formulas below need the **standard normal variate** $S_T$: how many
standard deviations above the mean a normal distribution has to go before only
$1/T$ of it lies above:

$$
S_T = \Phi^{-1}\!\left(1 - \frac{1}{T}\right)
$$

where $\Phi^{-1}$ is the inverse of the standard normal distribution.
MRRpy-Nepal computes it exactly (`MRRpy.nepal.methods.normal_variate`), so
$S_{100} = 2.3263$ (the compendium rounds to 2.326):

| $T$ (years) | 2 | 5 | 10 | 20 | 25 | 50 | 100 | 200 | 500 |
|---|---|---|---|---|---|---|---|---|---|
| $S_T$ | 0 | 0.8416 | 1.2816 | 1.6449 | 1.7507 | 2.0537 | 2.3263 | 2.5758 | 2.8782 |

### The log-normal interpolation of WECS/DHM {#lognormal}

WECS/DHM 1990 and DHM 2004 publish only two formulas, one for the 2-year flood
and one for the 100-year flood. Other return periods come from assuming that the
logarithm of the annual flood is normally distributed with mean $\mu$ and
standard deviation $\sigma$:

$$
\ln Q_T = \mu + S_T\,\sigma .
$$

At $T = 2$, $S_2 = 0$, so $\mu = \ln Q_2$. At $T = 100$,
$\ln Q_{100} = \ln Q_2 + S_{100}\,\sigma$, so $\sigma = \ln(Q_{100}/Q_2)/S_{100}$.
Putting both back gives the interpolation formula printed in the compendium:

$$
\boxed{\;\ln Q_T = \ln Q_2 + S_T\,\frac{\ln(Q_{100}/Q_2)}{S_{100}}\;}
$$

On a chart of $\ln Q$ against $S_T$ this is a straight line through $Q_2$ and
$Q_{100}$. Beyond 100 years the line is extended past the data the formulas were
fitted to, so those values are flagged **extrapolated** (shown with `*` in the
tables).

### Interpolating a tabulated method {#tabulated}

MHSP 1997 and the specific-discharge method give a separate formula for only a
few return periods (MHSP: 5, 20, 50, 100 years; specific discharge: 2, 25, 50,
100 years). MRRpy-Nepal then:

* uses the method's own formula at a tabulated $T$;
* **interpolates** between the two neighbouring tabulated return periods
  $T_1 < T < T_2$, with $\ln Q$ linear in $S_T$ (the same log-normal idea as
  above):

    $$
    \ln Q_T = \ln Q_{T_1} + \frac{S_T - S_{T_1}}{S_{T_2} - S_{T_1}}\,
    \left(\ln Q_{T_2} - \ln Q_{T_1}\right)
    $$

    These values are flagged **interpolated** (shown with `≈`);
* gives **no value** outside the tabulated span (for example MHSP at 2 or 200
  years). The method's notes say which return periods it tabulates.

*Example (MHSP Western, 10 years, 65 km²):* $Q_5 = 74.94$ and $Q_{20} = 114.79$
m³/s. The weight is $(1.2816 - 0.8416)/(1.6449 - 0.8416) = 0.5477$, so
$\ln Q_{10} = 4.3167 + 0.5477 \times (4.7431 - 4.3167) = 4.5502$ and
$Q_{10} \approx 94.65$ m³/s.

## WECS/DHM 1990 (HYDEST) — `wecs_dhm` {#wecs-dhm}

*Compendium §3.1. Used by DoWRI, DoED, DoR, DHM, AEPC and consultants. The most
widely used method in Nepal.*

$$
Q_2 = 1.8767\,(A_{3000} + 1)^{0.8783}, \qquad
Q_{100} = 14.63\,(A_{3000} + 1)^{0.7342}
$$

and any other $T$ by the [log-normal interpolation](#lognormal).

**What the variables mean.** $A_{3000}$ is the catchment area below 3,000 m
([measured from the DEM](catchment.md)). Above about 3,000 m monsoon rain falls
off and snow takes over, so the high ground adds little to floods; the
regression therefore leaves it out. The "+1" keeps the formula finite for a
catchment that lies wholly above 3,000 m. The exponent on $Q_{100}$ is smaller
than the one on $Q_2$: a big rare flood grows more slowly with area than a common
one, because large catchments rarely receive intense rain over their whole area
at once.

**Step by step (65 km²):**

1. $A_{3000} + 1 = 66$.
2. $Q_2 = 1.8767 \times 66^{0.8783} = 74.39$ m³/s.
3. $Q_{100} = 14.63 \times 66^{0.7342} = 317.07$ m³/s.
4. $\sigma = \ln(317.07/74.39)/2.3263 = 0.6232$.
5. $Q_{50} = \exp(\ln 74.39 + 2.0537 \times 0.6232) = 267.5$ m³/s.

| T | 2 | 5 | 10 | 20 | 50 | 100 | 200 | 500 |
|---|---|---|---|---|---|---|---|---|
| $Q$ (m³/s) | 74.39 | 125.7 | 165.3 | 207.4 | 267.5 | 317.1 | \*370.4 | \*447.2 |

**Daily floods — `wecs_dhm_daily`.** The same report gives the daily *mean*
flood, used for diversion and hydropower studies:

$$
Q_{2,\text{daily}} = 0.8154\,(A_{3000}+1)^{0.9527}, \qquad
Q_{100,\text{daily}} = 4.144\,(A_{3000}+1)^{0.8448}.
$$

For 65 km² this gives 44.14 m³/s (2 years) and 142.8 m³/s (100 years). A daily
mean is not an instantaneous peak, so this row is never part of the
[official range](results.md#official-range).

**Validity.** *Use with caution* below 100 km². The AEPC micro-hydro design aids
call WECS/DHM reliable only above 100 km² and not in the Siwalik or Terai, while
Subedi et al. (2022) describe it as suited to catchments of 100 km² or less, so
the 1990 report should be checked. Also *use with caution* for a Chure/Terai
stream (river class III), where $A_{3000} = A$ and the formula uses area only.

**Source note.** Some papers print the $Q_2$ exponent as 0.8737 or leave out the
"+1". The WECS/DHM 1990 report is the reference.

## DHM 2004 (Sharma & Adhikari) — `dhm_2004` {#dhm-2004}

*Compendium §3.2. Used by DHM, DoLIDAR (small irrigation), DoED and
consultants.*

$$
Q_2 = 2.29\,A_{3000}^{0.86}, \qquad Q_{100} = 20.7\,A_{3000}^{0.72},
$$

interpolated to other $T$ [the same way](#lognormal). It has the same
structure as WECS/DHM, with new coefficients and no "+1".

**Step by step (65 km²):** $Q_2 = 2.29 \times 65^{0.86} = 82.97$ m³/s;
$Q_{100} = 20.7 \times 65^{0.72} = 418.09$ m³/s.

| T | 2 | 5 | 10 | 20 | 50 | 100 | 200 | 500 |
|---|---|---|---|---|---|---|---|---|
| $Q$ (m³/s) | 82.97 | 149.0 | 202.2 | 260.3 | 345.9 | 418.1 | \*497.3 | \*613.6 |

At 100 years it is about 32 % above WECS/DHM for this catchment, which is
typical: DHM 2004 usually gives the higher floods.

**Validity.** *Outside its range* when $A_{3000} = 0$ (the whole catchment above
3,000 m): with no "+1" the formula gives zero. *Use with caution* for a
Chure/Terai stream, for the same reason as WECS/DHM.

**Source note.** Confirm in the DHM publication whether the mean basin elevation
enters the formula.

## MHSP 1997 (NEA) — `mhsp_1997` {#mhsp}

*Compendium §3.3. Medium Hydropower Study Project; used by NEA, DoED and
hydropower consultants.*

A power law of the **total** area, with separate constants for three regions of
Nepal and four return periods:

$$
Q_T = k_T\,A^{\,b_T}
$$

| T | Western $k$ | Western $b$ | Central $k$ | Central $b$ | Eastern $k$ | Eastern $b$ |
|---|---|---|---|---|---|---|
| 5 | 2.0409 | 0.8632 | 1.6762 | 0.9660 | 7.4008 | 0.7862 |
| 20 | 3.2895 | 0.8510 | 3.2303 | 0.9281 | 13.0848 | 0.7535 |
| 50 | 4.2570 | 0.8444 | 4.6090 | 0.9071 | 17.6058 | 0.7380 |
| 100 | 5.2225 | 0.8352 | 5.9865 | 0.8888 | 21.5181 | 0.7281 |

You choose the region (input `mhsp_region`, CLI `--region`). The compendium notes
that the far west (for example Kailali) probably uses the Western pair. Return
periods between 5 and 100 years are [interpolated](#tabulated); outside that span
MHSP gives nothing.

**Worked example (65 km²):**

| Region | Q5 | Q10 | Q20 | Q50 | Q100 |
|---|---|---|---|---|---|
| Western | 74.94 | ≈94.66 | 114.8 | 144.5 | 170.6 |
| Central | 94.54 | ≈124.2 | 155.5 | 203.3 | 244.6 |
| Eastern | 197.1 | ≈249.9 | 304.0 | 383.3 | 449.6 |

**Validity.** *Use with caution* below 100 km² or for a Chure/Terai stream. The
method was developed for medium hydropower sites on hill and mountain rivers, and
for small catchments it gives much lower values than WECS/DHM (compare the
Western 170.6 with WECS/DHM's 317.1 m³/s above).

**Source note.** Coefficients as reproduced in Subedi et al. (2022); confirm
against the MHSP 1997 report.

## Modified Dickens — `modified_dickens` {#modified-dickens}

*Compendium §3.5. Used by DoWRI, DoR, DWIDM and consultants, often as a check.*

The original Dickens formula $Q = C\,A^{3/4}$ (below) has one constant and no
return period. The modified form ties the constant to the return period and to
the share of snow in the catchment:

$$
Q_T = C_T\,A^{3/4}, \qquad
C_T = 2.342\,\log_{10}(0.6\,T)\,\log_{10}\!\frac{1185}{p} + 4, \qquad
p = \frac{100\,(a + 6)}{A + a}
$$

**What the variables mean.** $a$ is the permanent-snow area (km²), taken as the
area at or above 5,000 m. $p$ is a percentage that grows with the share of snow;
the "+6" is part of the published formula. A larger $p$ (more snow) gives a
smaller $\log(1185/p)$ and so a smaller $C_T$: snow-fed catchments produce less
flood per km². $C_T$ grows with $\log(0.6T)$, so the 2-year constant is about 4.4.

**Step by step (65 km², no snow):**

1. $p = 100 \times (0 + 6)/(65 + 0) = 9.231$.
2. $\log_{10}(1185/9.231) = \log_{10} 128.4 = 2.1085$.
3. $C_{100} = 2.342 \times \log_{10}(60) \times 2.1085 + 4 = 2.342 \times 1.7782
   \times 2.1085 + 4 = 12.78$.
4. $A^{3/4} = 65^{0.75} = 22.89$, so $Q_{100} = 12.78 \times 22.89 = 292.6$ m³/s.

| T | 2 | 5 | 10 | 20 | 50 | 100 | 200 | 500 |
|---|---|---|---|---|---|---|---|---|
| $C_T$ | 4.391 | 6.356 | 7.843 | 9.329 | 11.29 | 12.78 | 14.27 | 16.23 |
| $Q$ (m³/s) | 100.5 | 145.5 | 179.5 | 213.6 | 258.5 | 292.6 | 326.6 | 371.6 |

The formula has a return period built in, so nothing is flagged as extrapolated.
Like any other method, though, values far beyond the data behind it are
uncertain.

**Validity.** *Outside its range* when $p \ge 1185$, because then
$\log(1185/p) \le 0$. For a snow-free catchment that means $A$ below about
0.5 km². *Use with caution* for a snow-free catchment under 100 km², where the
"+6" dominates $p$ and so the result.

**Source note.** The form follows Subedi et al. (2022) and the MBMAN lecture note
(the two logarithms multiply; the denominator is $A + a$). Some sources write
$A$ instead; `modified_dickens(area, T, snow, denominator="A")` gives that
variant in Python, but the registry uses $A + a$.

## Specific discharge (WECS 2019) — `specific_discharge` {#specific-discharge}

*Compendium §3.15. WECS Flood Control and Management Manual (2019); river
training and flood-management studies.*

The flood per square kilometre, $q_T$ (m³/s/km²), falls with area. Four power
laws fitted to 51 DHM stations with data to 1996:

$$
q_2 = 4.2\,A^{-0.30}, \quad q_{25} = 30.8\,A^{-0.44}, \quad
q_{50} = 43.3\,A^{-0.46}, \quad q_{100} = 61.4\,A^{-0.49}, \qquad
Q_T = q_T\,A
$$

so, for example, $Q_2 = 4.2\,A^{0.70}$. Other return periods between 2 and
100 years are [interpolated](#tabulated).

**Worked example (65 km²):** $q_{100} = 61.4 \times 65^{-0.49} = 7.940$
m³/s/km², so $Q_{100} = 7.940 \times 65 = 516.1$ m³/s.

| T | 2 | 5 | 10 | 20 | 25 | 50 | 100 |
|---|---|---|---|---|---|---|---|
| $q_T$ (m³/s/km²) | 1.200 | | | | 4.908 | 6.347 | 7.940 |
| $Q$ (m³/s) | 78.03 | ≈153.6 | ≈218.7 | ≈293.0 | 319.0 | 412.5 | 516.1 |

**Validity.** *Outside its range* below 12 km², because smaller stations were
left out of the analysis.

## Comparison only: Dickens, Ryves, Inglis {#comparison}

*Compendium §3.4 and §3.14.* These formulas were fitted to Indian regions long
before the Nepali gauge network existed. They give a single "maximum flood" with no return
period, so the same value appears in every column of the table. They are shown
because older reports and DoR screening checks still quote them. They are
**never** part of the official range, and their status is *comparison only*.

| Method | Formula | Constant (input) | 65 km² |
|---|---|---|---|
| Dickens (1865) — `dickens` | $Q = C_D\,A^{3/4}$ | $C_D$ = 11.4 by default: 6 North Indian plains, 11–14 North Indian hills, 14–28 Central India (`dickens_constant`) | 261.0 |
| Ryves — `ryves` | $Q = C_R\,A^{2/3}$ | $C_R$ = 10.2 by default: 6.8 near the coast, 8.5 at 80–240 km, 10.2 near hills (`ryves_constant`) | 164.9 |
| Inglis — `inglis` | $Q = \dfrac{124\,A}{\sqrt{A + 10.4}}$ | none | 928.2 |

For the 65 km² example they span 165–928 m³/s, a factor of 5.6, which is why
they are not used for design.

## All regional methods side by side (65 km²) {#side-by-side}

| Method | Status | Q2 | Q5 | Q10 | Q20 | Q50 | Q100 |
|---|---|---|---|---|---|---|---|
| WECS/DHM 1990 | use with caution | 74.39 | 125.7 | 165.3 | 207.4 | 267.5 | 317.1 |
| DHM 2004 | ok* | 82.97 | 149.0 | 202.2 | 260.3 | 345.9 | 418.1 |
| MHSP 1997 (Western) | use with caution | – | 74.94 | ≈94.66 | 114.8 | 144.5 | 170.6 |
| Modified Dickens | use with caution | 100.5 | 145.5 | 179.5 | 213.6 | 258.5 | 292.6 |
| Specific discharge | ok | 78.03 | ≈153.6 | ≈218.7 | ≈293.0 | 412.5 | 516.1 |
| WECS/DHM daily (not a peak) | ok | 44.14 | 67.49 | 84.27 | 101.2 | 124.4 | 142.8 |

\* When the highest elevation is given and is below 1,500 m (a Chure stream), DHM
2004 also gets *use with caution* (the other rows already have it or no check).

At 100 years the usable peak methods range from 170.6 to 516.1 m³/s, a factor of
3. This is the main finding of the compendium's §6: for small Chure catchments
the national formulas disagree, and none of them knows the catchment's rainfall,
slope or soil. That is why MRRpy-Nepal sets the
[Rational method](rainfall-methods.md) and the
[physics model](design-floods.md) next to them, and why it reports the
[range and its spread](results.md#official-range) rather than one number.

## In code

```python
from MRRpy.nepal import methods as m

m.wecs_dhm_1990(65, [2, 50, 100])            # array([ 74.39, 267.5, 317.07])
m.dhm_2004(65, [2, 100])
Q, flags = m.mhsp_1997(65, [5, 10, 100], "western")   # flags: '', 'interpolated', ''
Q, C, p = m.modified_dickens(65, [2, 100], snow_km2=0)
Q, flags = m.specific_discharge(65, [2, 25, 100])
m.normal_variate([2, 100])                   # array([0.    , 2.3263])
```

The pure functions above take numbers. `estimate_floods` runs any selection
of methods for one catchment and adds the status, flags and notes. See
[reading the results](results.md).
