# All formulas at a glance

Every formula MRRpy-Nepal computes, on one page, with a link to the page that
explains it step by step: what the symbols mean, where the formula comes from,
a worked example, its range of validity, and the caveats of the compendium
*Nepal Flood Estimation Methods* (section numbers §). Units: $Q$ in m³/s, areas
in km², rainfall in mm, $T$ in years.

## Flood peaks

| Key | Method (§) | Formula | Needs | Explained in |
|---|---|---|---|---|
| `wecs_dhm` | WECS/DHM 1990, HYDEST (§3.1) | $Q_2 = 1.8767(A_{3000}+1)^{0.8783}$, $Q_{100} = 14.63(A_{3000}+1)^{0.7342}$, other $T$ log-normal | $A_{3000}$ | [regional formulas](regional-formulas.md#wecs-dhm) |
| `wecs_dhm_daily` | WECS/DHM 1990 daily flood (§3.1) | $Q_2 = 0.8154(A_{3000}+1)^{0.9527}$, $Q_{100} = 4.144(A_{3000}+1)^{0.8448}$ | $A_{3000}$ | [regional formulas](regional-formulas.md#wecs-dhm) |
| `dhm_2004` | DHM 2004, Sharma & Adhikari (§3.2) | $Q_2 = 2.29A_{3000}^{0.86}$, $Q_{100} = 20.7A_{3000}^{0.72}$, other $T$ log-normal | $A_{3000}$ | [regional formulas](regional-formulas.md#dhm-2004) |
| `mhsp_1997` | MHSP 1997, NEA (§3.3) | $Q_T = k_T A^{b_T}$ by region, $T$ = 5, 20, 50, 100 | $A$, region | [regional formulas](regional-formulas.md#mhsp) |
| `modified_dickens` | Modified Dickens (§3.5) | $Q_T = C_T A^{3/4}$, $C_T = 2.342\log(0.6T)\log(1185/p) + 4$, $p = 100(a+6)/(A+a)$ | $A$, snow $a$ | [regional formulas](regional-formulas.md#modified-dickens) |
| `specific_discharge` | Specific discharge, WECS 2019 (§3.15) | $Q_T = q_T A$; $q_2 = 4.2A^{-0.30}$, $q_{25} = 30.8A^{-0.44}$, $q_{50} = 43.3A^{-0.46}$, $q_{100} = 61.4A^{-0.49}$ | $A$ | [regional formulas](regional-formulas.md#specific-discharge) |
| `rational` | Rational method (§3.8) | $Q = CIA/3.6$; $t_c = 0.0195L^{0.77}S^{-0.385}$ min; $I = (R_{24}/24)(24/t_c)^{2/3}$ | $A$, $L$, $S$, $C$, $R_{24}$ | [rainfall methods](rainfall-methods.md#rational) |
| `physics` | MRRpy physics model (§3.19) | design storm $D(t) = R_{24}(t/24)^{1/3}$ in alternating blocks → SCS-CN runoff → kinematic routing on the DEM | DEM, $R_{24}$ | [design floods](design-floods.md) |
| `frequency` | Frequency analysis (§3.11) | Gumbel $x_T = \bar x + K_T s$; LP-III; GEV by L-moments; bootstrap band | annual maxima at the site | [frequency analysis](frequency.md) |
| `area_ratio` | Catchment area ratio (§3.12) | $Q_{site} = Q_{donor}(A_{site}/A_{donor})^n$, $n$ = 0.8 | donor area and floods | [frequency analysis](frequency.md#area-ratio) |
| `dickens` | Dickens, comparison only (§3.4) | $Q = C_D A^{3/4}$, $C_D$ = 11.4 | $A$ | [regional formulas](regional-formulas.md#comparison) |
| `ryves` | Ryves, comparison only (§3.14) | $Q = C_R A^{2/3}$, $C_R$ = 10.2 | $A$ | [regional formulas](regional-formulas.md#comparison) |
| `inglis` | Inglis, comparison only (§3.14) | $Q = 124A/\sqrt{A + 10.4}$ | $A$ | [regional formulas](regional-formulas.md#comparison) |
| — | Slope–area method, flood marks (§3.13) | $Q = \frac1n A R^{2/3} S^{1/2}$, $R = A/P$ | surveyed section | [frequency analysis](frequency.md#flood-marks) |

## Shared pieces

| What | Formula | Explained in |
|---|---|---|
| Standard normal variate | $S_T = \Phi^{-1}(1 - 1/T)$; $S_{100} = 2.3263$ | [regional formulas](regional-formulas.md#normal-variate) |
| Log-normal interpolation (WECS/DHM, DHM 2004) | $\ln Q_T = \ln Q_2 + S_T \ln(Q_{100}/Q_2)/S_{100}$ | [regional formulas](regional-formulas.md#lognormal) |
| Interpolating tabulated methods (MHSP, specific discharge) | $\ln Q$ linear in $S_T$ between tabulated $T$; nothing outside | [regional formulas](regional-formulas.md#tabulated) |
| Gumbel reduced variate (typed rainfall) | $y_T = -\ln(-\ln(1 - 1/T))$; $R_{24}$ linear in $y_T$ | [rainfall methods](rainfall-methods.md#typed-rainfall) |
| Daily-to-24-hour factor | $R_{24} = 1.13 \times$ fixed-day maximum (WMO), optional | [rainfall methods](rainfall-methods.md#rainfall-series) |
| Design depth | $R^{*}_{24} = R_{24} \times \text{ARF} \times \text{CF}$ | [design floods](design-floods.md#design-rainfall) |
| SCS curve number | $S = 25400/CN - 254$, $I_a = 0.2S$, $P_e = (P - I_a)^2/(P - I_a + S)$ | [design floods](design-floods.md#scs-cn) |
| Rain share on high ground | $f(z) = \text{clip}((5000 - z)/2000, 0, 1)$ | [design floods](design-floods.md#snow-ramp) |
| Bankfull channel presets | $Q_{bf}$ = the WECS/DHM, DHM 2004 or specific-discharge 2-year flood at every cell | [design floods](design-floods.md#bankfull-presets) |
| Length of a physics run | $t_d + \min(\max(6, 4t_c), 120)$ h | [design floods](design-floods.md#runs) |
| Plotting position | $T_m = (n+1)/m$ (Weibull) | [frequency analysis](frequency.md#plotting-positions) |
| Catchment numbers | $A$, $A_{3000}$, $A_{5000}$, snow, $L$, $S = \Delta z/L$, $S_{10\text{–}85}$, $L_c$ from the DEM | [catchment numbers](catchment.md) |

## Monthly and low flows

| Method (§) | Formula | Explained in |
|---|---|---|
| MIP 1982 (§4.1) | $Q_m = (Q_{meas}/k(\text{date}))\,k_m$; 7 regions; lowest implied April flow | [monthly flows](monthly-flows.md#mip) |
| WECS/DHM 1990 monthly (§4.3) | $Q_m = C A^{a_1}(A_{5000}+1)^{a_2}\text{MMP}^{a_3}$ | [monthly flows](monthly-flows.md#wecs-dhm-monthly) |
| MHSP 1997 monthly (§4.4) | $Q_m = C A^{a_1}\text{MMP}^{a_2}$ | [monthly flows](monthly-flows.md#mhsp-monthly) |
| Low-flow rule | the lower of WECS/DHM and MIP each month (Shrestha et al. 2010) | [monthly flows](monthly-flows.md#lower) |
| E-flow (§4.8) | $\ge 0.10 \min_m Q_m$ (Hydropower Development Policy 2001) | [monthly flows](monthly-flows.md#eflow) |
| 80 % dependable flow (§4.7) | $\bar Q_m - 0.8416\,s_m$, and the empirical 20 % quantile | [monthly flows](monthly-flows.md#dependable) |
| 7Q10 (§4.9) | $\exp(\overline{\ln Q_7} - 1.2816\,s_{\ln Q_7})$ | [monthly flows](monthly-flows.md#7q10) |
| Area ratio for flows (§4.5) | $Q_{site} = Q_{donor}(A_{site}/A_{donor})(P_{site}/P_{donor})$ | [monthly flows](monthly-flows.md#area-ratio-flows) |

## Where the coefficients come from

Every coefficient is the one printed in the compendium. Where it says a value
still has to be checked against the original report, the method's notes say so
too (`FloodMethod.source`; the *Notes by method* in the report):

* WECS/DHM 1990: some papers print the $Q_2$ exponent as 0.8737 or leave out the
  "+1"; the 1990 report is the reference;
* DHM 2004: confirm whether the mean basin elevation enters the formula;
* MHSP 1997 (floods and monthly) and the specific-discharge method: as
  reproduced in Subedi et al. (2022);
* Modified Dickens: the form of Subedi et al. (2022) and the MBMAN lecture note;
* MIP 1982: Baral and Shakya, WRPPF/DoI.

## What is not in MRRpy-Nepal (yet) {#not-included}

| Method | Why |
|---|---|
| B.D. Richards (§3.6) | the compendium gives only part of it (no $t_c$ relation or intensity reduction; the areal factor is printed two ways); to be added from the DoR hydrology guideline |
| PCJ 1996 / 2024 (§3.7) | its coefficient tables are not reproduced; to be added from Jha's papers |
| Tahal index flood (§3.10) | the Narayani growth factors are not reproduced; regional L-moment growth curves are planned instead |
| Updated MIP 2016 (§4.2) | the 22-region ratio tables are not reproduced |
| WECS/DHM low flows and FDC (§4.3) | coefficients not reproduced |
| Fuller (§3.14), envelope curves (§3.16) | no usable coefficients or Nepal curve |
| WECS 1982 (§3.20) | superseded and unverified ("do not use for design") |
| Khosla (§4.6) | ignores storage and baseflow; MRRpy simulates continuously instead |
| Snyder / SCS unit hydrographs (§3.9) | MRRpy routes the hydrograph physically; SCS-CN losses are a runoff option |
| GLOF / LDOF (§3.18) | outside this package's scope; MRRpy can route a given outburst hydrograph ([[ROUTING_INFLOW_BC]]) |

A method is added only when its formula and coefficients can be taken from the
compendium in full; a formula given only in part is left out rather than
guessed. The roadmap (regional frequency analysis with L-moments, calibration
of the physics model to gauges and flood marks, satellite rainfall frequency,
climate factors from CMIP6) is in `NEPAL_PLAN.md` at the root of the
repository.
