# -*- coding: utf-8 -*-
"""
config_bridge.py
================
Re-export of the core configuration object (``MRRpy.config.Config``), made
importable first via :func:`ensure_core`, so the Python API, the CLI and the
plugin all share one definition.
"""

from . import ensure_core

ensure_core()

from MRRpy.config import Config  # noqa: E402,F401

__all__ = ["Config"]
