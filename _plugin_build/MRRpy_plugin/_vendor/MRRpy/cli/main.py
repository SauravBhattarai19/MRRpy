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
        Print every DEM dataset MRRpy can auto-download from Google Earth
        Engine (dataset id, resolution, coverage) — set DEM_SOURCE to one of
        these keys.
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
    run_pipeline(cfg, stages=args.stages)
    return 0


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
    except (FileNotFoundError, ValueError, AttributeError, ImportError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
