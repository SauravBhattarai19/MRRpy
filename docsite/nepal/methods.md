# Methods and formulas

Every method MRRpy-Nepal computes, with its formula, what it needs, its range
and the caveats the compendium *Nepal Flood Estimation Methods* attaches to it.
Section numbers (§) refer to the compendium. $Q$ is in m³/s, areas in km².

The catchment numbers come from the DEM ([measured
automatically](#catchment-numbers)) or are typed in. The worked values below are
the compendium's 65 km² snow-free Chure catchment; MRRpy-Nepal reproduces each of
them in its tests.

## The official regional formulas

### WECS/DHM 1990 (HYDEST) — `wecs_dhm` (§3.1)

The national regression on the area below 3,000 m, $A_{3000}$:

$$
Q_2 = 1.8767\,(A_{3000}+1)^{0.8783}, \qquad Q_{100} = 14.63\,(A_{3000}+1)^{0.7342},
$$

$$
\ln Q_T = \ln Q_2 + S_T\,\frac{\ln(Q_{100}/Q_2)}{2.326},
$$

where $S_T$ is the standard normal variate (0 for 2 years, 0.842 for 5, 1.282 for
10, 1.645 for 20, 2.054 for 50, 2.326 for 100, 2.576 for 200, 2.878 for 500).
Daily mean floods (`wecs_dhm_daily`) use $0.8154\,(A_{3000}+1)^{0.9527}$ and
$4.144\,(A_{3000}+1)^{0.8448}$ — not peaks, so they stay out of the official range.

*Example:* $Q_2$ = 74.4, $Q_{100}$ = 317.1, $Q_{50}$ = 267.6 m³/s.
*Used by:* DoWRI, DoED, DoR, DHM, AEPC, consultants.
*Caution flag:* below 100 km² (the AEPC design aids call it reliable only above
100 km² and not in the Siwalik or Terai; Subedi et al. 2022 say the opposite), and
for a Chure/Terai stream, where $A_{3000} = A$ makes it area-only.
*Source note:* some papers print the $Q_2$ exponent as 0.8737 or drop the "+1";
the 1990 report is the reference.

### DHM 2004 (Sharma & Adhikari) — `dhm_2004` (§3.2)

$$
Q_2 = 2.29\,A_{3000}^{0.86}, \qquad Q_{100} = 20.7\,A_{3000}^{0.72},
$$

interpolated like WECS/DHM. *Example:* $Q_2$ = 83.0, $Q_{100}$ = 418.1, $Q_{50}$ =
346.0 m³/s — about 32 % above WECS/DHM at 100 years. *Used by:* DHM, DoLIDAR,
DoED, consultants. *Outside its range* when the whole catchment lies above 3,000 m
(it has no "+1"). *Source note:* confirm whether mean basin elevation enters the
formula.

### MHSP 1997 (NEA) — `mhsp_1997` (§3.3)

$Q_T = k\,A^b$, with $k$ and $b$ by region and return period:

| T | Western k | Western b | Central k | Central b | Eastern k | Eastern b |
|---|---|---|---|---|---|---|
| 5 | 2.0409 | 0.8632 | 1.6762 | 0.9660 | 7.4008 | 0.7862 |
| 20 | 3.2895 | 0.8510 | 3.2303 | 0.9281 | 13.0848 | 0.7535 |
| 50 | 4.2570 | 0.8444 | 4.6090 | 0.9071 | 17.6058 | 0.7380 |
| 100 | 5.2225 | 0.8352 | 5.9865 | 0.8888 | 21.5181 | 0.7281 |

Other return periods between 5 and 100 years are interpolated (≈) on the normal
variate; outside that span MHSP gives nothing. You choose the region; the
compendium notes the far west (e.g. Kailali) probably uses the Western pair.
*Example (Western, 100 years):* 170.6 m³/s. *Caution flag:* below 100 km² or for a
Chure/Terai stream — developed for medium hydropower sites, it gives much lower
values for small catchments. *Source note:* coefficients as reproduced in Subedi
et al. (2022); confirm against the MHSP 1997 report.

### Modified Dickens — `modified_dickens` (§3.5)

$$
Q_T = C_T\,A^{3/4}, \qquad C_T = 2.342\,\log(0.6T)\,\log\frac{1185}{p} + 4,
\qquad p = \frac{100\,(a+6)}{A+a},
$$

with $a$ the permanent-snow area, taken as the area at or above 5,000 m (measured
from the DEM). *Example:* $p$ = 9.23, $C_{100}$ = 12.78, $Q_{100}$ = 292.6, $Q_2$ =
100.5, $Q_{50}$ = 258.5 m³/s. *Used by:* DoWRI, DoR, DWIDM, consultants (often as
a check). *Caution flag:* small snow-free catchments, where the "+6" in $p$
dominates. *Outside its range* when $p \ge 1185$ (catchments under about 0.5 km²).

### Specific discharge, WECS 2019 — `specific_discharge` (§3.15)

$Q_T = q_T\,A$ with $q_2 = 4.2\,A^{-0.30}$, $q_{25} = 30.8\,A^{-0.44}$,
$q_{50} = 43.3\,A^{-0.46}$, $q_{100} = 61.4\,A^{-0.49}$ (51 DHM stations, data to
1996). Interpolated between 2 and 100 years. *Example:* $q_{100}$ = 7.94 m³/s/km²,
$Q_{100}$ = 516, $Q_2$ = 78 m³/s. *Outside its range* below 12 km² (smaller
stations were excluded).

## Rainfall-based methods

### Rational method — `rational` (§3.8)

$$
Q = \frac{C\,I\,A}{3.6}, \qquad t_c = 0.0195\,L^{0.77}\,S^{-0.385}\ \text{min (Kirpich)},
\qquad I = \frac{R_{24}}{24}\left(\frac{24}{t_c}\right)^{2/3}\ \text{(Mononobe)},
$$

with $L$ the longest flow path (m) and $S$ its slope, both measured from the DEM,
$R_{24}$ the T-year 24-hour rainfall (mm) and $C$ the runoff coefficient (about
0.3 forest, 0.5 agriculture, 0.25 barren, 0.85 built-up; DoLIDAR suggests
0.2–0.4). *Example:* $L$ = 15 km, $S$ = 0.015 → $t_c$ = 161 min; $R_{24}$ = 250 mm →
$I$ = 44.8 mm/h; $C$ = 0.45 → $Q$ = 364.1 m³/s. *Caution flag:* above 12 km² (many
manuals). *Outside its range:* above 50 km² (WECS 2019).

The design rainfall is either typed (`2: 120, 100: 250`; return periods in between
are interpolated on a Gumbel scale) or fitted to a DHM station's annual maximum
daily rainfall (see [frequency analysis](#frequency-analysis)). DHM records are
once-a-day readings; the optional daily-to-24-hour factor (WMO practice: 1.13)
turns fixed-day maxima into true 24-hour maxima.

### The MRRpy physics model — `physics` (§3.19)

The design storm runs through MRRpy's runoff and routing on the DEM — see
[design floods with the physics model](design-floods.md).

## Gauge-based methods

### Frequency analysis — `frequency` (§3.11)

Fitted to the annual maximum floods at the site:

* **Gumbel** by moments: $X_T = \bar{x} + K_T\,s$, with
  $K_T = -\frac{\sqrt{6}}{\pi}\left[0.5772 + \ln\ln\frac{T}{T-1}\right]$;
* **Log-Pearson III** on $\log_{10}$ of the data, with the station skew;
* **GEV** by L-moments (Hosking 1990).

Each comes with a 90 % bootstrap confidence band (the ToR asks for confidence
bounds). At least 10 years are needed; under 20 years the result carries a note,
and so does any return period beyond twice the record. `MRRpy nepal frequency
peaks.csv` compares the three side by side.

### Catchment area ratio — `area_ratio` (§3.12)

$Q_{site} = Q_{donor}\,(A_{site}/A_{donor})^n$ with $n$ about 0.5–0.85 for floods
(default 0.8). The donor's floods are typed or fitted to its annual maxima.
*Caution flag:* when the areas differ by more than a factor of 2 — the donor must
be shown to be hydrologically similar. *Example:* Kankai at Mainachuli (1,148 km²)
to the Ratuwa bridge (430 km²): linear ratio 0.375; with $n$ = 0.8, 0.456.

### Flood marks — the slope–area method (§3.13)

`MRRpy.nepal.slope_area_discharge(area_m2, perimeter_m, slope, n)` gives the peak
of a surveyed flood, $Q = \frac{1}{n} A R^{2/3} S^{1/2}$. Its return period is
unknown, so a study shows it as a reference line on the chart (`observed_floods`).

## Comparison only

`dickens` ($Q = C_D A^{3/4}$, default $C_D$ = 11.4), `ryves` ($Q = C_R A^{2/3}$,
default $C_R$ = 10.2) and `inglis` ($Q = 124A/\sqrt{A+10.4}$) were fitted to Indian
regions and have no return period. They appear in older reports and in DoR
screening checks; for the 65 km² example they span 165–928 m³/s, which is why they
are never part of the official range.

## Monthly and low flows

Calculators from the irrigation and hydropower manuals (§4), in `MRRpy nepal
monthly`, the form's last tab and `MRRpy.nepal.flows`:

* **MIP 1982** — 7 regions; one dry-season measurement (November–April) fixes the
  scale of the region's non-dimensional hydrograph (flow ÷ April flow). The ratio
  is interpolated between the 15ths of the months. With several measurements the
  lowest implied April flow is used (Shrestha et al. 2010). *Example:* Region 4,
  1.5 m³/s on 15 February → April 0.80, August 21.76 m³/s.
* **WECS/DHM 1990 monthly** — $Q = C\,A^{a_1}(A_{5000}+1)^{a_2}\,MMP^{a_3}$, with
  the monthly coefficients of the compendium and the mean monsoon precipitation
  $MMP$ (mm).
* **MHSP 1997 monthly** — $Q = C\,A^{a_1}\,MMP^{a_2}$.
* **Low-flow rule** — for low-flow design take the lower of WECS/DHM and MIP for
  each month (Shrestha et al. 2010); shown as its own row.
* **E-flow** — at least 10 % of the minimum mean monthly flow (Hydropower
  Development Policy 2001); confirm the rule that applies to irrigation intakes.
* **80 % dependable flow**, **7Q10** (log-normal) and the catchment area ratio for a
  donor record: `dependable_flow`, `seven_q_ten`, `area_ratio_flows`.

## Catchment numbers

`MRRpy.nepal.measure_catchment(results_folder)` reads the rasters of the
`process_dem` stage:

| Number | How it is measured |
|---|---|
| A, A₃₀₀₀, A₅₀₀₀ | cells of the watershed (all, below 3,000 m, below 5,000 m) × cell area |
| Permanent snow | cells at or above 5,000 m |
| L | the longest D8 flow path to the outlet |
| S | its fall over its length, H/L (S10–85 is reported too) |
| Lc | distance along L to the point nearest the catchment centroid |
| River class | I snow-fed (area above 5,000 m), III Chure/Terai (highest point below about 1,500 m), II otherwise — approximate, used only for warnings |

Typed numbers work as well; left empty, the area below 3,000 m and 5,000 m is
the whole area (as for a Terai/Chure catchment) and the snow area is 0, and the
report says so.

## What is not in MRRpy-Nepal (yet)

| Method | Why |
|---|---|
| B.D. Richards (§3.6) | the compendium gives only part of it (no t_c relation or intensity reduction; the areal factor is printed two ways) — to add from the DoR hydrology guideline |
| PCJ 1996 / 2024 (§3.7) | its coefficient tables are not reproduced — to add from Jha's papers |
| Tahal index flood (§3.10) | the Narayani growth factors are not reproduced; regional L-moment growth curves are planned instead |
| Updated MIP 2016 (§4.2) | the 22-region ratio tables are not reproduced |
| WECS/DHM low flows and FDC (§4.3) | coefficients not reproduced |
| Fuller (§3.14), envelope curves (§3.16) | no usable coefficients or Nepal curve |
| WECS 1982 (§3.20) | superseded and unverified ("do not use for design") |
| Khosla (§4.6) | ignores storage and baseflow; MRRpy simulates continuously instead |
| Snyder / SCS unit hydrographs (§3.9) | MRRpy routes the hydrograph physically; SCS-CN losses are a runoff option |
| GLOF / LDOF (§3.18) | outside this package's scope; MRRpy can route a given outburst hydrograph ([[ROUTING_INFLOW_BC]]) |

The roadmap (regional frequency analysis with L-moments, calibration of the
physics model to gauges and flood marks, satellite rainfall frequency, climate
factors from CMIP6) is in `NEPAL_PLAN.md` at the root of the repository.
