# -*- coding: utf-8 -*-
"""
MRRpy.interactive
=================
Build a configuration without typing it by hand.

* ``run_wizard()``   — question-and-answer in any terminal or notebook
                       (``MRRpy wizard`` on the command line).  No extra installs.
* ``ConfigForm()``   — a form with tabs for Jupyter (needs ``ipywidgets``:
                       ``pip install MRRpy[notebook]``).
* ``explain(name)``  — plain-language help on any setting, or a search.
* ``render_yaml``, ``to_python``, ``describe_run`` — readable views of a Config.

Every front-end reads the same parameter catalogue (``MRRpy.config_schema``),
so they offer exactly the same settings, choices and checks.
"""

from .render import (describe_run, explain, list_settings, render_yaml, save_yaml,
                     to_python)
from .wizard import Wizard, run_wizard

__all__ = ["ConfigForm", "Wizard", "run_wizard", "explain", "list_settings",
           "describe_run", "render_yaml", "save_yaml", "to_python"]


def __getattr__(name):
    # ConfigForm needs ipywidgets; import it only when asked for.
    if name == "ConfigForm":
        from .form import ConfigForm
        return ConfigForm
    raise AttributeError(f"module 'MRRpy.interactive' has no attribute {name!r}")
