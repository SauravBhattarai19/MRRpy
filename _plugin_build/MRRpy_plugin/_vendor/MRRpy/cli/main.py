# -*- coding: utf-8 -*-
"""
main.py
=======
The ``MRRpy`` command-line interface.

Commands
--------
    MRRpy run -c config.yaml [--stages process_dem routing]
        Run the pipeline with the given config file (YAML, JSON or a legacy
        flat python settings module).

    MRRpy wizard [-o run.yaml] [--edit run.yaml] [--advanced]
        Build (or edit) a config file by answering questions — only the
        questions that matter for your earlier answers are asked.

    MRRpy init-config [-o config.yaml] [--short] [--interactive]
        Write a commented template config file: every parameter at its
        default with a plain-language explanation (--short: only the main
        ones; --interactive: run the wizard instead).

    MRRpy earth-engine-login [--project ID] [--check] [--force]
        Sign in to Google Earth Engine once per computer and check that the
        project works (needed only for Earth Engine options).

    MRRpy explain NAME | WORDS… [--all]
        Explain one setting (choices, default, when it applies), search the
        settings by keyword, or list them all.

    MRRpy validate -c config.yaml
        Load the config file and run the pre-flight sanity checks without
        starting a simulation.

    MRRpy list-options
        Print every fixed-choice option with its integer codes (each option
        accepts the string or the code, e.g. PRECIP_METHOD: uniform ≡ 0).

    MRRpy list-dems
        Print every DEM dataset MRRpy can download (dataset id, resolution,
        coverage, and which need no account) — set DEM_SOURCE to one of
        these keys.

    MRRpy demo [FOLDER] [--real]
        Run a small sample basin from start to finish; nothing to prepare.

    MRRpy doctor [--offline]
        Check this computer: packages, GPU, Earth Engine sign-in, internet.

    MRRpy ensemble -c config.yaml [--model M] [--members N …] [--workers N]
        Run every member of an Open-Meteo ensemble forecast and write the
        range of floods they give.

Global flags: ``MRRpy --version``; ``MRRpy --debug <command> …`` shows the full
Python traceback on an error.  ``MRRpy run`` takes ``--quiet`` and ``--no-log``.
"""

import argparse
import os
import sys

from ..config import Config
from ..pipeline import run_pipeline, DEFAULT_STAGES, _STAGE_PROGRESS


def _cmd_run(args):
    cfg = Config.from_file(args.config)
    if args.output_dir:
        cfg.OUTPUT_DIR = args.output_dir
        cfg.update_output_paths()
    if args.backend:
        cfg.BACKEND = args.backend
    cfg.validate()
    out = run_pipeline(cfg, stages=args.stages, quiet=args.quiet,
                       log_file=not args.no_log)
    if args.quiet:
        print(out.summary())
    return 130 if out.cancelled else 0


def _cmd_init_config(args):
    if args.interactive:
        return _wizard(output=args.output)
    from ..interactive.render import save_yaml
    if os.path.splitext(args.output)[1].lower() == ".json":
        path = Config().save(args.output)            # JSON can't hold comments
    else:
        path = save_yaml(Config(), args.output, full=not args.short,
                         source="MRRpy init-config")
    print(f"Template config written to: {path}")
    print("Edit at least DEM_PATH, OUTPUT_POINT, TARGET_CRS_EPSG and OUTPUT_DIR, then:")
    print(f"  MRRpy validate -c {path}")
    print(f"  MRRpy run -c {path}")
    print("Prefer answering questions?  MRRpy wizard")
    return 0


def _wizard(output=None, edit=None, ask_all=False, write_all=False, brief=False,
            start=None):
    from ..interactive.wizard import run_wizard
    cfg = run_wizard(config=edit, output=output, ask_all=ask_all, write_all=write_all,
                     starting_point=start, offer_run=True, show_help=not brief)
    return 0 if cfg is not None else 1


def _cmd_wizard(args):
    return _wizard(output=args.output, edit=args.edit, ask_all=args.advanced,
                   write_all=args.write_all, brief=args.brief, start=args.start)


def _cmd_ee_login(args):
    from ..gee.auth import connect
    ok = connect(project=args.project, sign_in=not args.check, force=args.force,
                 auth_mode=args.auth_mode)
    return 0 if ok else 1


def _cmd_explain(args):
    from ..interactive.render import explain, list_settings
    if args.all or not args.query:
        print(list_settings())
        print("Details on one setting:  MRRpy explain <NAME>   "
              "Search:  MRRpy explain <word>")
        return 0
    text = explain(" ".join(args.query))
    print(text)
    return 0 if not text.startswith("No setting") else 1


def _cmd_validate(args):
    cfg = Config.from_file(args.config)
    try:
        cfg.validate()
    except ValueError as exc:
        print(exc)
        return 1
    print("Config OK.")
    from ..interactive.render import describe_run
    for line in describe_run(cfg):
        print(f"  - {line}")
    return 0


def _cmd_demo(args):
    from ..sample import demo
    out = demo(args.folder, real=args.real, quiet=not args.verbose)
    return 0 if out.hydrograph is not None else 1


def _cmd_doctor(args):
    from ..doctor import report
    return 0 if report(online=not args.offline) else 1


def _cmd_ensemble(args):
    from ..batch import run_ensemble
    cfg = Config.from_file(args.config)
    if args.output_dir:
        cfg.OUTPUT_DIR = args.output_dir
    if args.model:
        cfg.OPENMETEO_MODEL = args.model
    res = run_ensemble(cfg, members=args.members, workers=args.workers)
    try:
        import matplotlib
        matplotlib.use("Agg", force=False)
        from ..plotting import plot_ensemble
        fig, _ax = plot_ensemble(res)
        png = os.path.join(res["output_dir"], "ensemble_hydrograph.png")
        fig.savefig(png, dpi=120, bbox_inches="tight")
        print(f"Figure: {png}")
    except Exception as exc:              # noqa: BLE001 — the runs themselves succeeded
        print(f"(The figure could not be drawn: {exc})")
    return 0


def _cmd_list_options(args):
    from ..core.routing.qbf import describe_presets
    print(Config.describe_options())
    print("\nCHANNEL_QBF_M3S — bankfull flow: None/'auto' (global estimate), a number "
          "[m³/s], a formula, or a preset:")
    print(describe_presets())
    return 0


def _cmd_list_dems(args):
    from ..gee.dem_catalog import describe_dems
    print(describe_dems())
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="MRRpy",
        description="MRRpy — distributed hydrological + hydrodynamic model "
                    "(VSA-OPM; Pradhan & Ogden 2010).",
    )
    from .. import __version__
    parser.add_argument("--version", action="version", version=f"MRRpy {__version__}")
    parser.add_argument("--debug", action="store_true",
                        help="on an error, show the full Python traceback")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run the pipeline from a config file")
    p_run.add_argument("-c", "--config", required=True,
                       help="config file (.yaml, .json or legacy .py)")
    p_run.add_argument("--stages", nargs="+", default=list(DEFAULT_STAGES),
                       choices=sorted(_STAGE_PROGRESS),
                       help=f"pipeline stages to run (default: {' '.join(DEFAULT_STAGES)})")
    p_run.add_argument("--output-dir", default=None,
                       help="override OUTPUT_DIR from the config file")
    p_run.add_argument("--backend", default=None, choices=("cpu", "gpu"),
                       help="override the compute backend")
    p_run.add_argument("-q", "--quiet", action="store_true",
                       help="print only warnings and a closing summary (the full "
                            "report still goes to run.log in the results folder)")
    p_run.add_argument("--no-log", action="store_true",
                       help="do not write run.log in the results folder")
    p_run.set_defaults(func=_cmd_run)

    p_wiz = sub.add_parser(
        "wizard", help="build or edit a config file by answering questions",
        description="Build a config file by answering questions.  Press Enter to keep "
                    "the value in [brackets]; type ? for help, back, done or quit.")
    p_wiz.add_argument("-o", "--output", default=None,
                       help="file to save (.yaml or .json; asked at the end, default run.yaml)")
    p_wiz.add_argument("--edit", metavar="FILE", default=None,
                       help="start from an existing config file and change it")
    p_wiz.add_argument("--advanced", action="store_true",
                       help="ask the advanced questions too, without asking first")
    p_wiz.add_argument("--write-all", action="store_true",
                       help="save every setting (a long reference file), not only "
                            "the ones that matter for your choices")
    p_wiz.add_argument("--brief", action="store_true",
                       help="don't print the explanation above each question")
    from ..config_schema import STARTING_POINT_BY_KEY
    p_wiz.add_argument("--start", choices=list(STARTING_POINT_BY_KEY), default=None,
                       help="skip the first question by choosing a starting point")
    p_wiz.set_defaults(func=_cmd_wizard)

    p_init = sub.add_parser("init-config", help="write a commented template config file")
    p_init.add_argument("-o", "--output", default="config.yaml",
                        help="destination file (.yaml or .json; default: config.yaml)")
    p_init.add_argument("--short", action="store_true",
                        help="only the main settings (the rest keep their defaults)")
    p_init.add_argument("--full", dest="short", action="store_false",
                        help="every setting, explained (the default)")
    p_init.add_argument("-i", "--interactive", action="store_true",
                        help="build the file by answering questions (same as 'MRRpy wizard')")
    p_init.set_defaults(func=_cmd_init_config)

    p_ee = sub.add_parser(
        "earth-engine-login", help="sign in to Google Earth Engine and check the connection",
        description="Connect to Google Earth Engine: uses this computer's saved sign-in, or "
                    "signs in once (a link to open and a code to paste back; works over SSH).")
    p_ee.add_argument("--project", default=None,
                      help="your Earth Engine (Google Cloud) project ID, e.g. ee-yourname "
                           "(default: the GEE_PROJECT environment variable)")
    p_ee.add_argument("--check", action="store_true",
                      help="only check the connection; never start a sign-in")
    p_ee.add_argument("--force", action="store_true",
                      help="sign in again, e.g. with another Google account")
    p_ee.add_argument("--auth-mode", default=None,
                      choices=("notebook", "localhost", "gcloud", "colab"),
                      help="how to sign in (default: Earth Engine chooses)")
    p_ee.set_defaults(func=_cmd_ee_login)

    p_exp = sub.add_parser("explain", help="explain a setting, or search the settings")
    p_exp.add_argument("query", nargs="*",
                       help="a setting name (e.g. ROUTING_SCHEME) or words to search for")
    p_exp.add_argument("--all", action="store_true", help="list every setting")
    p_exp.set_defaults(func=_cmd_explain)

    p_val = sub.add_parser("validate", help="check a config file without running")
    p_val.add_argument("-c", "--config", required=True,
                       help="config file (.yaml, .json or legacy .py)")
    p_val.set_defaults(func=_cmd_validate)

    p_demo = sub.add_parser(
        "demo", help="run a small sample basin from start to finish (nothing to prepare)",
        description="Run the sample basin: a made-up valley by default (offline), or a real "
                    "basin near Kathmandu with --real (downloads a DEM, no account).")
    p_demo.add_argument("folder", nargs="?", default="mrrpy_demo",
                        help="where to put the demo (default: mrrpy_demo)")
    p_demo.add_argument("--real", action="store_true",
                        help="a real basin with a downloaded 90 m DEM (needs internet)")
    p_demo.add_argument("-v", "--verbose", action="store_true",
                        help="print the full report of the run")
    p_demo.set_defaults(func=_cmd_demo)

    p_doc = sub.add_parser(
        "doctor", help="check this computer: packages, GPU, Earth Engine, internet",
        description="Check what MRRpy needs on this computer. Nothing is installed or changed.")
    p_doc.add_argument("--offline", action="store_true",
                       help="skip the checks that need the internet")
    p_doc.set_defaults(func=_cmd_doctor)

    p_ens = sub.add_parser(
        "ensemble", help="run every member of an Open-Meteo ensemble forecast",
        description="Run each member of an ensemble forecast and write the range of floods "
                    "they give (ensemble_hydrograph.csv and .png). The config must use "
                    "Open-Meteo rain (PRECIP_METHOD openmeteo_thiessen or openmeteo_idw).")
    p_ens.add_argument("-c", "--config", required=True,
                       help="config file (.yaml, .json or legacy .py)")
    p_ens.add_argument("--model", default=None,
                       help="ensemble model, e.g. gfs_seamless (31 members), ecmwf_ifs025 "
                            "(51), icon_seamless (40); default: OPENMETEO_MODEL of the file")
    p_ens.add_argument("--members", nargs="+", type=int, default=None,
                       help="member numbers to run (default: all; 0 is the control run)")
    p_ens.add_argument("--workers", type=int, default=1,
                       help="how many members to run at the same time (default 1)")
    p_ens.add_argument("--output-dir", default=None,
                       help="override OUTPUT_DIR from the config file")
    p_ens.set_defaults(func=_cmd_ensemble)

    p_opts = sub.add_parser("list-options",
                            help="list fixed-choice options and their integer codes")
    p_opts.set_defaults(func=_cmd_list_options)

    p_dems = sub.add_parser("list-dems",
                            help="list DEM datasets available via Google Earth Engine")
    p_dems.set_defaults(func=_cmd_list_dems)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n[INFO] Stopped.", file=sys.stderr)
        return 130
    except Exception as exc:              # noqa: BLE001 — one plain line, not a traceback
        if args.debug:
            raise
        expected = (FileNotFoundError, ValueError, AttributeError, ImportError, RuntimeError)
        what = str(exc) if isinstance(exc, expected) else f"{type(exc).__name__}: {exc}"
        print(f"[ERROR] {what}", file=sys.stderr)
        if not isinstance(exc, (FileNotFoundError, ValueError)):
            print("        For the full details, run the same command with --debug "
                  "right after 'MRRpy', e.g.  MRRpy --debug run -c run.yaml",
                  file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
