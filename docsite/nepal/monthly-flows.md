# Monthly and low flows

Irrigation intakes, micro-hydro and small hydropower are designed on the
**flow that is usually there**, not on floods: the mean flow of each month, the
flow available in 80 % of years, the dry-season low flow and the release that
must stay in the river. The compendium's §4 collects the methods Nepali manuals
use for these. MRRpy-Nepal implements them as calculators. They need no physics
model and run in a second.

| Method | Gives | Needs |
|---|---|---|
| [MIP 1982](#mip) | 12 mean monthly flows | MIP region (1–7) and one or more dry-season flow measurements |
| [WECS/DHM 1990 monthly](#wecs-dhm-monthly) | 12 mean monthly flows | $A$, $A_{5000}$ and the mean monsoon precipitation |
| [MHSP 1997 monthly](#mhsp-monthly) | 12 mean monthly flows | $A$ and the mean monsoon precipitation |
| [Lower of WECS/DHM and MIP](#lower) | the design low-flow row | both of the above |
| [E-flow](#eflow) | the minimum release below an intake | any of the above |
| [80 % dependable flow](#dependable) | flow exceeded in 80 % of years, per month | a multi-year flow record (gauged or simulated) |
| [7Q10](#7q10) | the 7-day, 10-year low flow | a daily flow record |
| [Area ratio](#area-ratio-flows) | a donor record moved to the site | the donor record and both areas |

**MMP**, the mean monsoon precipitation, is the average June–September rainfall
over the catchment (mm), from DHM stations or isohyetal maps.

## MIP 1982 (Medium Irrigation Project) {#mip}

*Compendium §4.1. The standard method for irrigation intakes on ungauged
rivers.*

**The idea.** Within one hydrological region, the *shape* of the year's
hydrograph is about the same on every river; only its size differs. MIP gives
that shape as a **non-dimensional hydrograph**: each month's mean flow divided
by the April flow (April, the driest month, = 1). One flow measurement in the
dry season fixes the size.

| Region | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2.40 | 1.80 | 1.30 | 1.00 | 2.60 | 6.00 | 14.50 | 25.00 | 16.50 | 8.00 | 4.10 | 3.10 |
| 2 | 2.24 | 1.70 | 1.33 | 1.00 | 1.21 | 7.27 | 18.18 | 27.27 | 20.91 | 9.09 | 3.94 | 3.03 |
| 3 | 2.71 | 1.88 | 1.38 | 1.00 | 1.88 | 3.13 | 13.54 | 25.00 | 20.83 | 10.42 | 5.00 | 3.75 |
| 4 | 2.59 | 1.88 | 1.38 | 1.00 | 2.19 | 3.75 | 6.89 | 27.27 | 20.91 | 6.89 | 5.00 | 3.44 |
| 5 | 2.42 | 1.82 | 1.36 | 1.00 | 0.91 | 2.73 | 11.21 | 13.94 | 10.00 | 6.52 | 4.55 | 3.33 |
| 6 | 2.03 | 1.62 | 1.27 | 1.00 | 2.57 | 6.08 | 24.32 | 33.78 | 27.03 | 6.08 | 3.38 | 2.57 |
| 7 | 3.30 | 2.20 | 1.40 | 1.00 | 3.50 | 6.00 | 14.00 | 35.00 | 24.00 | 12.00 | 7.50 | 5.00 |

(Region from the MIP regions map; ratios from Baral and Shakya, WRPPF/DoI.)

**Step 1: the ratio on the measurement date.** The tabulated ratio $k_m$ holds
at the middle (the 15th) of month $m$. Between the 15ths it is interpolated
linearly, counting every month as 30 days:

$$
k(\text{date}) = \begin{cases}
k_m + (k_{m+1} - k_m)\,\dfrac{\text{day} - 15}{30} & \text{day} \ge 15\\[8pt]
k_{m-1} + (k_m - k_{m-1})\,\dfrac{\text{day} + 15}{30} & \text{day} < 15
\end{cases}
$$

In Region 4: 15 February → 1.88; 1 March → $1.88 + (1.38 - 1.88) \times 16/30
= 1.613$; 5 February → $2.59 + (1.88 - 2.59) \times 20/30 = 2.117$.

**Step 2: the April flow.** $Q_{Apr} = Q_{measured} / k(\text{date})$.

**Step 3: every month.** $Q_m = Q_{Apr}\,k_m$.

*Example (Region 4, 1.5 m³/s measured on 15 February):* $Q_{Apr} = 1.5/1.88 =
0.798$ m³/s.

| Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2.07 | 1.50 | 1.10 | 0.80 | 1.75 | 2.99 | 5.50 | 21.76 | 16.68 | 5.50 | 3.99 | 2.74 |

**Several measurements.** With more than one dry-season measurement, each gives
its own April flow, and the **lowest** is used. Shrestha et al. (2010) found
that scaling from the driest measurement matches the records much better than
scaling from April. Three measurements in Region 4 (15 Feb 1.5, 20 Mar 1.2,
10 Apr 1.0 m³/s) give April flows of 0.798, 0.911 and 0.940, and 0.798 is used.

**Rules.** The measurement must be a dry-season baseflow (November–April) and
not within a few days of rain; a measurement in another month is used but
carries a note. Measured flows must be above 0.

## WECS/DHM 1990 monthly (HYDEST) {#wecs-dhm-monthly}

*Compendium §4.3.* A regression for each month:

$$
Q_m = C\,A^{a_1}\,(A_{5000} + 1)^{a_2}\,\text{MMP}^{a_3}
$$

| Month | C | $a_1$ (A) | $a_2$ ($A_{5000}$+1) | $a_3$ (MMP) |
|---|---|---|---|---|
| Jan | 0.0142 | 0 | 0.9777 | 0 |
| Feb | 0.0122 | 0 | 0.9766 | 0 |
| Mar | 0.0100 | 0 | 0.9948 | 0 |
| Apr | 0.0080 | 0 | 1.0435 | 0 |
| May | 0.0084 | 0 | 1.0898 | 0 |
| Jun | 0.0069 | 0.9968 | 0 | 0.2610 |
| Jul | 0.0212 | 0 | 1.0093 | 0.2523 |
| Aug | 0.0255 | 0 | 0.9963 | 0.2620 |
| Sep | 0.0168 | 0 | 0.9894 | 0.2878 |
| Oct | 0.0097 | 0 | 0.9880 | 0.2508 |
| Nov | 0.0018 | 0.9605 | 0 | 0.3910 |
| Dec | 0.0015 | 0.9605 | 0 | 0.3607 |

January–May depend only on the area below 5,000 m; July–October add the monsoon rain; June,
November and December use the total area and the monsoon rain.

*Example (65 km², no snow, MMP = 1,500 mm):* January
$= 0.0142 \times 66^{0.9777} = 0.854$ m³/s; August $= 0.0255 \times 66^{0.9963}
\times 1500^{0.2620} = 11.26$ m³/s.

## MHSP 1997 monthly (NEA) {#mhsp-monthly}

*Compendium §4.4.*

$$
Q_m = C\,A^{a_1}\,\text{MMP}^{a_2}
$$

| Month | C | $a_1$ | $a_2$ | Month | C | $a_1$ | $a_2$ |
|---|---|---|---|---|---|---|---|
| Jan | 0.0312 | 0.8644 | 0 | Jul | 0.0164 | 0.9216 | 0.3534 |
| Feb | 0.0242 | 0.8752 | 0 | Aug | 0.0259 | 0.9095 | 0.3242 |
| Mar | 0.0205 | 0.8902 | 0 | Sep | 0.0221 | 0.8963 | 0.3217 |
| Apr | 0.0178 | 0.9558 | 0 | Oct | 0.0150 | 0.8772 | 0.2848 |
| May | 0.0119 | 0.9657 | 0 | Nov | 0.0079 | 0.8804 | 0.2707 |
| Jun | 0.0114 | 0.9466 | 0.2402 | Dec | 0.0054 | 0.8890 | 0.2580 |

(WECS/DHM and MHSP coefficients from Subedi et al. 2022.)

## Side by side, and the low-flow rule {#lower}

`monthly_flows` runs the chosen methods and adds two things:

* the row **Lower of WECS/DHM and MIP**, month by month, when both ran. For
  low-flow design Shrestha et al. (2010) advise taking the lower of the two;
* a **Mean** column (the mean of the 12 months).

*Example (65 km², Region 4, 1.5 m³/s on 15 February, MMP 1,500 mm), m³/s:*

| Method | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | Mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MIP 1982 | 2.07 | 1.50 | 1.10 | 0.80 | 1.75 | 2.99 | 5.50 | 21.76 | 16.68 | 5.50 | 3.99 | 2.74 | 5.53 |
| WECS/DHM 1990 | 0.85 | 0.73 | 0.65 | 0.63 | 0.81 | 2.98 | 9.21 | 11.26 | 8.70 | 3.81 | 1.73 | 1.16 | 3.54 |
| MHSP 1997 | 1.15 | 0.93 | 0.84 | 0.96 | 0.67 | 3.43 | 10.19 | 12.35 | 9.80 | 4.69 | 2.26 | 1.46 | 4.06 |
| Lower of WECS/DHM and MIP | 0.85 | 0.73 | 0.65 | 0.63 | 0.81 | 2.98 | 5.50 | 11.26 | 8.70 | 3.81 | 1.73 | 1.16 | 3.23 |

Here the regional regressions give less than half of what the MIP measurement
implies in the dry season. That difference is the reason for the rule, and also
a reason to measure the river more than once.

## Environmental flow {#eflow}

*Compendium §4.8.* The Hydropower Development Policy (2001) requires a release
below an intake of at least **10 % of the minimum mean monthly flow**:

$$
Q_{e} = 0.10 \times \min_m Q_m
$$

MRRpy-Nepal applies it to the *Lower of WECS/DHM and MIP* row when it exists,
otherwise to the first method's row. In the example: $0.10 \times 0.634$ (April)
$= 0.0634$ m³/s. It also returns 30 % of each month's flow, which the guidance
published with MIP 2016 rates as "satisfactory". Confirm which rule applies to
an irrigation intake; the 2001 rule was written for hydropower.

## 80 % dependable flow {#dependable}

*Compendium §4.7.* Irrigation design uses, for each month, the flow equalled or
exceeded in 80 % of years. From a record of several years (gauged, or simulated
with MRRpy), `dependable_flow` gives two estimates per month:

* **normal:** $Q_{80} = \max\!\left(\bar Q_m - z\,s_m,\ 0\right)$ with
  $z = \Phi^{-1}(0.8) = 0.8416$ and $\bar Q_m$, $s_m$ the mean and standard
  deviation ($n-1$) of that month's flow over the years (the compendium's
  formula);
* **empirical:** the 20 % quantile of the ranked years (Weibull plotting
  position), with no distribution assumed.

A daily series is first averaged to monthly means. A month needs at least 2
years. For example, a synthetic 15-year record with a mean August flow of 20.32
m³/s and a standard deviation of 0.85 m³/s gives $Q_{80}$ = 19.61 (normal) and
19.51 m³/s (empirical).

## 7Q10 low flow {#7q10}

*Compendium §4.9.* The lowest 7-day mean flow with a 10-year return period,
used for water-quality and minimum-flow checks:

1. $Q_7$: the 7-day moving average of the daily flows;
2. the lowest $Q_7$ of each calendar year;
3. a log-normal distribution fitted to those annual minima:

$$
\text{7Q10} = \exp\!\left(\overline{\ln Q_7} - 1.2816\,s_{\ln Q_7}\right),
$$

where $1.2816 = \Phi^{-1}(0.9)$ is the normal variate for a 1-in-10-year *low*
flow. At least 2 years are needed, and fewer than 10 carry a note. If the 7-day
flow falls to 0 in some year, the river dries up and 7Q10 is 0 (a log-normal
cannot hold zeros).

## Area ratio for flows {#area-ratio-flows}

*Compendium §4.5.* A donor gauge's record (a number, a monthly table or a whole
series) moved to the site in proportion to area, and optionally to rainfall:

$$
Q_{site} = Q_{donor}\,\frac{A_{site}}{A_{donor}}\left[\frac{P_{site}}{P_{donor}}\right]
$$

For mean and low flows the exponent is 1 (compare $n \approx 0.8$ for
[floods](frequency.md#area-ratio)).

## Running it

=== "Notebook form"

    The **Monthly and low flows** tab of `NepalForm()`: tick the methods, choose
    the MIP region, type the measurements (`2024-02-15 = 1.5`, one per line) and
    the mean monsoon rain, and press **Compute monthly flows**. The catchment
    comes from the **Site** tab.

=== "Command line"

    ```bash
    MRRpy nepal monthly --area 65 --mip-region 4 --measured 2024-02-15=1.5 \
        --mmp 1500 -o monthly.csv
    MRRpy nepal monthly --results results/ --mip-region 4 \
        --measured 2024-02-15=1.5 2024-03-20=1.2 --mmp 1500
    ```

=== "Python"

    ```python
    from MRRpy.nepal import CatchmentDescriptors, flows

    site = CatchmentDescriptors(area_km2=65)
    mf = flows.monthly_flows(site, mip_region=4, measurements=("2024-02-15", 1.5),
                             mmp_mm=1500)
    mf.table            # m³/s, one row per method, plus 'Lower of …' and 'Mean'
    mf.eflow            # minimum_release, month_of_minimum, satisfactory_by_month
    mf.notes

    flows.dependable_flow(daily_series)          # per month: mean, sd, q_normal, q_empirical
    flows.seven_q_ten(daily_series)              # (7Q10, notes)
    flows.area_ratio_flows(donor_monthly, 65, 180, p_site_mm=1500, p_donor_mm=1700)
    ```

Not included yet: the updated MIP 2016 (its 22-region tables are not
reproduced in the compendium), the WECS/DHM low-flow and flow-duration
regressions, and Khosla's method. See [what is not included](methods.md#not-included).

Next: [reading the results](results.md).
