# -*- coding: utf-8 -*-
"""
cli.py
======
``MRRpy nepal …`` — the Nepal commands of the MRRpy command line.

    MRRpy nepal methods
        Every method, agency preset and structure preset.

    MRRpy nepal estimate  SITE  [DESIGN]  [INPUTS]  [--physics]
        Flood estimates by the official methods (and the physics model).
        SITE:   --results FOLDER | -c run.yaml | --dem DEM --outlet LAT LON
                | --area KM2 [--area-below-3000 …] | --study study.yaml
        DESIGN: --agency KEY | --methods KEY …;  --structure KEY | --T 2 10 100
        INPUTS: --region, --C, --rain24 100=250 …, --rain-series FILE,
                --flood-series FILE, --donor-area KM2 --donor-floods 100=900 …

    MRRpy nepal frequency FILE [--T …] [--dist gumbel lp3 gev]
        Fit annual maxima (floods or daily rainfall) with confidence bands.

    MRRpy nepal monthly  [--mip-region R --measured DATE=Q …] [--mmp MM]  SITE
        Mean monthly flows: MIP 1982, WECS/DHM and MHSP, and the e-flow.

    MRRpy nepal design-storm --rain24 MM [-o FOLDER] [--results FOLDER]
        Write a design storm as rain-gauge CSVs for any MRRpy run.
"""

import os
import sys

from . import frequency as fq
from . import guidelines as gl
from .methods import FLOOD_METHODS, INPUTS, STATUS_TEXT, describe_methods, parse_table


def _pairs(items):
    """['100=250', '2: 120'] → {100.0: 250.0, 2.0: 120.0}."""
    return parse_table(" ".join(str(i) for i in items or ())) or {}


def _labelled(items):
    """['2021 flood mark=410'] → [('2021 flood mark', 410.0)]."""
    out = []
    for item in items or ():
        label, _sep, q = str(item).rpartition("=")
        if not label:
            raise ValueError(f"{item!r}: write an observed flood as LABEL=Q, e.g. '2021 flood=410'.")
        out.append((label.strip(), float(q)))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# Building a study from the arguments
# ═════════════════════════════════════════════════════════════════════════════
def _site(args):
    if getattr(args, "results", None):
        return {"results": args.results}
    if getattr(args, "config", None):
        return {"config": args.config}
    if getattr(args, "dem", None):
        if not args.outlet:
            raise ValueError("--dem needs --outlet LAT LON.")
        return {"dem": args.dem, "outlet": list(args.outlet), "folder": args.folder or "results"}
    if getattr(args, "area", None) is not None:
        numbers = {"area_km2": args.area}
        for arg, key in (("area_below_3000", "area_below_3000_km2"),
                         ("area_below_5000", "area_below_5000_km2"),
                         ("snow_area", "snow_area_km2"), ("length_km", "flow_length_km"),
                         ("slope", "flow_path_slope"), ("max_elevation", "max_elevation_m")):
            if getattr(args, arg, None) is not None:
                numbers[key] = getattr(args, arg)
        return {"numbers": numbers}
    raise ValueError("Say where the catchment is: --results FOLDER, -c run.yaml, --dem DEM "
                     "--outlet LAT LON, or --area KM2 (typed numbers).")


def _inputs(args):
    i = {}
    if args.region:
        i["mhsp_region"] = args.region
    if args.C is not None:
        i["runoff_coefficient"] = args.C
    if args.rain24:
        i["rain_24h"] = _pairs(args.rain24)
    if args.rain_series:
        i["rain_annual_max"] = args.rain_series
    if args.rain_dist:
        i["rain_distribution"] = args.rain_dist
    if args.rain_factor is not None:
        i["rain_fixed_day_factor"] = args.rain_factor
    if args.flood_series:
        i["flood_annual_max"] = args.flood_series
    if args.flood_dist:
        i["flood_distribution"] = args.flood_dist
    if args.donor_area is not None:
        i["donor_area_km2"] = args.donor_area
    if args.donor_floods:
        i["donor_floods"] = _pairs(args.donor_floods)
    if args.donor_series:
        i["donor_annual_max"] = args.donor_series
    if args.area_exponent is not None:
        i["area_ratio_exponent"] = args.area_exponent
    if args.dickens_c is not None:
        i["dickens_constant"] = args.dickens_c
    if args.ryves_c is not None:
        i["ryves_constant"] = args.ryves_c
    return i


def _physics(args):
    p = {}
    if args.physics_T:
        p["return_periods"] = [float(t) for t in args.physics_T]
    for arg, key in (("cn", "curve_number"), ("pattern", "pattern"), ("duration", "duration_h"),
                     ("step", "step_min"), ("areal_reduction", "areal_reduction"),
                     ("climate_factor", "climate_factor"), ("model_config", "model_config"),
                     ("sim_hours", "sim_hours")):
        if getattr(args, arg, None) is not None:
            p[key] = getattr(args, arg)
    if args.no_snow_ramp:
        p["snow_ramp"] = False
    if args.physics:
        p["enabled"] = True            # kept in a saved study, so --study runs it again
    elif args.no_physics:
        p["enabled"] = False
    return p


def build_study(args):
    """The NepalStudy the arguments describe (a --study file, with flags on top)."""
    from .study import NepalStudy
    if args.study:
        base = NepalStudy.load(args.study)
        # flags win over the file; a new --agency / --structure replaces the file's lists
        methods = args.methods or (None if args.agency else base.methods)
        periods = args.T or (None if args.structure else base.return_periods)
        return NepalStudy(base.site, name=args.name or base.name,
                          agency=args.agency or base.agency,
                          structure=args.structure or base.structure,
                          methods=methods, return_periods=periods,
                          inputs={**base.inputs, **_inputs(args)},
                          physics={**base.physics, **_physics(args)},
                          output_dir=args.output_dir or base.output_dir,
                          observed_floods=_labelled(args.observed) or base.observed_floods)
    return NepalStudy(_site(args), name=args.name or "", agency=args.agency,
                      structure=args.structure, methods=args.methods, return_periods=args.T,
                      inputs=_inputs(args), physics=_physics(args), output_dir=args.output_dir,
                      observed_floods=_labelled(args.observed))


# ═════════════════════════════════════════════════════════════════════════════
# Commands
# ═════════════════════════════════════════════════════════════════════════════
def _cmd_methods(args):
    print(describe_methods())
    print(gl.describe_presets())
    print("Inputs (estimate flags in brackets):")
    flags = {"mhsp_region": "--region", "runoff_coefficient": "--C", "rain_24h": "--rain24",
             "rain_annual_max": "--rain-series", "rain_distribution": "--rain-dist",
             "rain_fixed_day_factor": "--rain-factor", "flood_annual_max": "--flood-series",
             "flood_distribution": "--flood-dist", "donor_area_km2": "--donor-area",
             "donor_floods": "--donor-floods", "donor_annual_max": "--donor-series",
             "area_ratio_exponent": "--area-exponent", "dickens_constant": "--dickens-c",
             "ryves_constant": "--ryves-c"}
    for key, i in INPUTS.items():
        print(f"  {i.label} [{flags[key]}]")
    return 0


def format_table(estimates):
    """The estimates as aligned text: values, ≈ interpolated, * extrapolated."""
    from .methods import _cell
    cols = estimates.columns
    name_w = max([len(r["name"]) for r in estimates.rows] + [6])
    stat_w = max([len(STATUS_TEXT.get(r["status"], r["status"])) for r in estimates.rows] + [6])
    head = f"{'Method':<{name_w}}  {'Status':<{stat_w}}  " + "  ".join(f"{c:>8}" for c in cols)
    lines = [head, "-" * len(head)]
    for r in estimates.rows:
        cells = [_cell(q, f) for q, f in zip(r["Q"], r["flags"])]
        lines.append(f"{r['name']:<{name_w}}  {STATUS_TEXT.get(r['status'], r['status']):<{stat_w}}  "
                     + "  ".join(f"{c:>8}" for c in cells))
    lines.append("(m³/s; ≈ interpolated, * extrapolated, – not available)")
    return "\n".join(lines)


def _cmd_estimate(args):
    study = build_study(args)
    if args.save_study:
        print(f"Study saved to {study.save(args.save_study)}")
    log = (lambda _s: None) if args.quiet else print
    result = study.run(log=log)                  # --physics / --no-physics live in the study
    print()
    print(result.descriptors.summary())
    for a in result.descriptors.assumptions():
        print(f"  assumed: {a}")
    if result.agency is not None:
        print(f"Methods: {result.agency.label}")
    if result.structure is not None:
        print(f"Design: {result.structure.describe()}")
    print()
    print(format_table(result.estimates))
    print()
    print("Official range (regional methods usable here):")
    for line in result.summary_lines()[1:]:
        print(line)
    notes = [(r["name"], r["notes"][0]) for r in result.estimates.rows
             if r["status"] in ("needs input", "outside") and r["notes"]]
    if notes:
        print("\nNeeds attention:")
        for name, n in notes:
            print(f"  - {name}: {n}")
    warnings = result.warnings()
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")
    if result.files:
        print("\nWritten:")
        for k, v in result.files.items():
            print(f"  {k:<10} {v}")
    elif study.folder is None:
        print("\n(Typed numbers: nothing saved. Add --output-dir DIR to save the table, chart "
              "and report.)")
    return 0


def _cmd_frequency(args):
    values = fq.read_series(args.file, column=args.column)
    T = args.T or [2, 5, 10, 20, 50, 100, 200, 500]
    print(f"{values.size} annual maxima from {args.file} (min {values.min():.4g}, "
          f"max {values.max():.4g}, mean {values.mean():.4g})\n")
    for dist in args.dist or fq.DISTRIBUTIONS:
        try:
            fit = fq.fit_annual_maxima(values, T, dist, ci=args.ci, n_boot=args.boot)
        except ValueError as exc:
            print(f"{fq.DISTRIBUTION_LABELS[fq._distribution(dist)]}: {exc}\n")
            continue
        pct = int(round(args.ci * 100))
        print(f"{fit.label}  ({', '.join(f'{k} {v:.4g}' for k, v in fit.params.items())})")
        print(f"  {'T (years)':>10}  {'value':>10}  {f'{pct} % band':>21}")
        for t, q, lo, hi in zip(fit.T, fit.quantiles, fit.lower, fit.upper):
            print(f"  {fq._tkey(t):>10}  {q:>10.4g}  {lo:>10.4g} – {hi:<10.4g}")
        for w in fit.warnings:
            print(f"  note: {w}")
        print()
    return 0


def _descriptors_for(args):
    from .descriptors import CatchmentDescriptors, measure_catchment
    if args.results or args.config:
        return measure_catchment(args.results or args.config)
    if args.area is not None:
        return CatchmentDescriptors(area_km2=args.area, area_below_5000_km2=args.area_below_5000)
    return None


def _cmd_monthly(args):
    from .flows import MONTHLY_METHODS, monthly_flows
    measurements = [(d, q) for d, q in _date_pairs(args.measured)]
    desc = _descriptors_for(args)
    methods = args.methods or list(MONTHLY_METHODS)
    mf = monthly_flows(desc, methods, mip_region=args.mip_region, measurements=measurements,
                       mmp_mm=args.mmp)
    if not len(mf.table):
        print("No method could run:")
    else:
        print(mf.table.round(3).to_string())
    for n in mf.notes:
        print(f"  - {n}")
    if args.output and len(mf.table):
        print(f"Written: {mf.to_csv(args.output)}")
    return 0 if len(mf.table) else 1


def _date_pairs(items):
    out = []
    for item in items or ():
        d, _sep, q = str(item).partition("=")
        if not q:
            raise ValueError(f"{item!r}: write a measurement as DATE=Q, e.g. 2024-02-15=1.5.")
        out.append((d.strip(), float(q)))
    return out


def _cmd_design_storm(args):
    from . import design_storm as ds
    depth = ds.design_depth(args.rain24, args.areal_reduction, args.climate_factor)
    hyeto = ds.design_hyetograph(depth, args.duration, args.step, args.pattern)
    x, y, where = 0.0, 0.0, "(0, 0) — with one gauge its position does not matter"
    if args.results:
        from .descriptors import measure_catchment
        d = measure_catchment(args.results)
        x, y = d.outlet_xy
        where = f"the catchment outlet ({d.crs})"
    folder = args.output or "design_storm"
    hyeto_csv = os.path.join(folder, "hyetograph.csv")
    gauge, rain = ds.write_storm_files(hyeto, folder, x, y, sim_hours=args.sim_hours,
                                       name=f"design storm {depth:.0f} mm")
    hyeto.to_csv(hyeto_csv, index=False)
    peak = hyeto["intensity_mm_h"].max()
    print(f"Design storm: {hyeto['rain_mm'].sum():.1f} mm in {args.duration:g} h "
          f"(R24 {args.rain24:g} mm × {args.areal_reduction:g} × {args.climate_factor:g}), "
          f"{args.pattern}, peak {peak:.1f} mm/h; gauge at {where}.")
    print(f"Written: {hyeto_csv}\n         {gauge}\n         {rain}")
    print("Use it in any MRRpy run:  PRECIP_METHOD: thiessen, PRECIP_GAUGE_FILE: "
          f"{gauge}, PRECIP_TIMESERIES_FILE: {rain}")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# Parser
# ═════════════════════════════════════════════════════════════════════════════
def _site_args(p, numbers=True):
    g = p.add_argument_group("catchment (choose one)")
    g.add_argument("--results", metavar="FOLDER",
                   help="results folder of an MRRpy run (process_dem done)")
    g.add_argument("-c", "--config", metavar="FILE",
                   help="an MRRpy config file (its OUTPUT_DIR; delineated if needed)")
    if numbers:
        g.add_argument("--area", type=float, metavar="KM2", help="typed catchment area (km²)")
        g.add_argument("--area-below-5000", type=float, metavar="KM2",
                       help="typed area below 5,000 m (km²)")
    return g


def add_parser(sub):
    """Add the ``nepal`` command (with its sub-commands) to the main CLI."""
    p = sub.add_parser(
        "nepal", help="Nepal: official flood methods, design storms and monthly flows",
        description="MRRpy-Nepal: the official Nepali flood-estimation methods next to the "
                    "physics model.  Start with 'MRRpy nepal methods'.")
    nsub = p.add_subparsers(dest="nepal_command", required=True)

    m = nsub.add_parser("methods", help="list the methods, agency and structure presets")
    m.set_defaults(func=_cmd_methods)

    e = nsub.add_parser(
        "estimate", help="flood estimates by the official methods (and the physics model)",
        description="Flood estimates for one catchment by the methods you choose (or the ones "
                    "an agency's manual names), side by side, with the official range.")
    g = _site_args(e, numbers=False)
    g.add_argument("--dem", metavar="FILE", help="a DEM file (delineated with --outlet)")
    g.add_argument("--outlet", nargs=2, type=float, metavar=("LAT", "LON"),
                   help="the outlet of the --dem catchment")
    g.add_argument("--folder", metavar="DIR", help="where to delineate a --dem site (default results)")
    g.add_argument("--area", type=float, metavar="KM2", help="typed catchment area (km²)")
    g.add_argument("--area-below-3000", type=float, metavar="KM2")
    g.add_argument("--area-below-5000", type=float, metavar="KM2")
    g.add_argument("--snow-area", type=float, metavar="KM2", help="permanent snow (km²)")
    g.add_argument("--length-km", type=float, metavar="KM", help="longest flow path L (km)")
    g.add_argument("--slope", type=float, metavar="M/M", help="slope of L (m/m)")
    g.add_argument("--max-elevation", type=float, metavar="M", help="highest point (m)")
    g.add_argument("--study", metavar="FILE", help="a saved study (YAML); other flags override it")
    d = e.add_argument_group("design")
    d.add_argument("--agency", choices=list(gl.AGENCIES), help="tick the methods this manual names")
    d.add_argument("--methods", nargs="+", choices=list(FLOOD_METHODS), metavar="KEY",
                   help="methods to run (overrides --agency): " + ", ".join(FLOOD_METHODS))
    d.add_argument("--structure", choices=list(gl.STRUCTURES),
                   help="tick this structure's design return periods")
    d.add_argument("--T", nargs="+", type=float, metavar="YEARS",
                   help="return periods (overrides --structure; default 2 5 10 20 50 100 200 500)")
    d.add_argument("--name", help="site name for the tables and report")
    i = e.add_argument_group("method inputs")
    i.add_argument("--region", choices=("western", "central", "eastern"), help="MHSP region")
    i.add_argument("--C", type=float, help="runoff coefficient for the Rational method")
    i.add_argument("--rain24", nargs="+", metavar="T=MM",
                   help="24-hour design rainfall, e.g. 2=120 100=250")
    i.add_argument("--rain-series", metavar="FILE", help="CSV of annual maximum daily rainfall")
    i.add_argument("--rain-dist", choices=fq.DISTRIBUTIONS)
    i.add_argument("--rain-factor", type=float, help="daily → 24-hour factor (e.g. 1.13)")
    i.add_argument("--flood-series", metavar="FILE", help="CSV of annual maximum floods at the site")
    i.add_argument("--flood-dist", choices=fq.DISTRIBUTIONS)
    i.add_argument("--donor-area", type=float, metavar="KM2", help="donor gauge catchment area")
    i.add_argument("--donor-floods", nargs="+", metavar="T=Q", help="donor design floods")
    i.add_argument("--donor-series", metavar="FILE", help="CSV of donor annual maximum floods")
    i.add_argument("--area-exponent", type=float, help="area-ratio exponent n (default 0.8)")
    i.add_argument("--dickens-c", type=float, help="Dickens constant (default 11.4)")
    i.add_argument("--ryves-c", type=float, help="Ryves constant (default 10.2)")
    i.add_argument("--observed", nargs="+", metavar="LABEL=Q",
                   help="observed floods for the chart, e.g. '2021 flood mark=410'")
    ph = e.add_argument_group("physics model")
    ph.add_argument("--physics", action="store_true", help="also run the MRRpy physics model")
    ph.add_argument("--no-physics", action="store_true", help="skip the physics model")
    ph.add_argument("--physics-T", nargs="+", type=float, metavar="YEARS",
                    help="return periods to simulate (default: the design return period)")
    ph.add_argument("--cn", type=float, help="SCS curve number of the default model (default 75)")
    ph.add_argument("--pattern", choices=("center", "uniform"), help="storm time pattern")
    ph.add_argument("--duration", type=float, metavar="HOURS", help="storm duration (default 24)")
    ph.add_argument("--step", type=float, metavar="MIN", help="storm time step (default 15)")
    ph.add_argument("--areal-reduction", type=float, help="areal reduction factor on R24")
    ph.add_argument("--climate-factor", type=float, help="climate factor on R24, e.g. 1.1")
    ph.add_argument("--no-snow-ramp", action="store_true",
                    help="do not reduce the rain above 3,000 m")
    ph.add_argument("--model-config", metavar="FILE",
                    help="use this config's runoff and routing instead of the default model")
    ph.add_argument("--sim-hours", type=float, help="simulation length (h)")
    o = e.add_argument_group("output")
    o.add_argument("-o", "--output-dir", metavar="DIR",
                   help="where to write (default <results>/nepal)")
    o.add_argument("--save-study", metavar="FILE", help="also save these settings as a study YAML")
    o.add_argument("-q", "--quiet", action="store_true", help="hide the model's progress lines")
    e.set_defaults(func=_cmd_estimate)

    f = nsub.add_parser("frequency", help="fit annual maxima (Gumbel, LP-III, GEV)")
    f.add_argument("file", help="CSV of annual maxima (a value column, optionally a year column)")
    f.add_argument("--column", help="the column to use (default: the last numeric one)")
    f.add_argument("--T", nargs="+", type=float, metavar="YEARS")
    f.add_argument("--dist", nargs="+", choices=fq.DISTRIBUTIONS)
    f.add_argument("--ci", type=float, default=0.90, help="confidence band (default 0.90)")
    f.add_argument("--boot", type=int, default=1000, help="bootstrap resamples (default 1000)")
    f.set_defaults(func=_cmd_frequency)

    mo = nsub.add_parser("monthly", help="mean monthly flows: MIP 1982, WECS/DHM, MHSP; e-flow")
    _site_args(mo)
    mo.add_argument("--methods", nargs="+", choices=("mip_1982", "wecs_dhm", "mhsp_1997"))
    mo.add_argument("--mip-region", type=int, choices=range(1, 8), metavar="1-7",
                    help="MIP 1982 region")
    mo.add_argument("--measured", nargs="+", metavar="DATE=Q",
                    help="dry-season flow measurement(s), e.g. 2024-02-15=1.5")
    mo.add_argument("--mmp", type=float, metavar="MM", help="mean monsoon (Jun–Sep) precipitation")
    mo.add_argument("-o", "--output", metavar="CSV", help="write the table to this CSV")
    mo.set_defaults(func=_cmd_monthly)

    s = nsub.add_parser("design-storm", help="write a design storm as rain-gauge CSVs")
    s.add_argument("--rain24", type=float, required=True, metavar="MM",
                   help="the T-year 24-hour design rainfall")
    s.add_argument("--duration", type=float, default=24.0, metavar="HOURS")
    s.add_argument("--step", type=float, default=15.0, metavar="MIN")
    s.add_argument("--pattern", choices=("center", "uniform"), default="center")
    s.add_argument("--areal-reduction", type=float, default=1.0)
    s.add_argument("--climate-factor", type=float, default=1.0)
    s.add_argument("--sim-hours", type=float, help="pad the rain file with zeros to this length")
    s.add_argument("--results", metavar="FOLDER",
                   help="results folder: put the gauge at its outlet (map projection)")
    s.add_argument("-o", "--output", metavar="FOLDER", help="folder to write (default design_storm)")
    s.set_defaults(func=_cmd_design_storm)
    return p


def main(argv=None):                                   # pragma: no cover - convenience
    from ..cli.main import main as mrrpy_main
    return mrrpy_main(["nepal"] + list(argv if argv is not None else sys.argv[1:]))
