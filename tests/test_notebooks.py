# -*- coding: utf-8 -*-
"""
tests/test_notebooks.py
=======================
The example notebooks in notebooks/ stay valid, and the configuration
notebook runs from top to bottom in a real Jupyter kernel.

Run:  pytest tests/test_notebooks.py -v
"""

import ast
import os
import shutil

import pytest

nbformat = pytest.importorskip("nbformat")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The notebooks MRRpy ships (not users' own copies or scratch notebooks there).
NOTEBOOKS = [os.path.join(ROOT, "notebooks", n)
             for n in ("configure_and_run.ipynb", "pick_dem_bounds.ipynb")]


@pytest.mark.parametrize("path", NOTEBOOKS, ids=os.path.basename)
def test_notebook_is_valid_and_clean(path):
    nb = nbformat.read(path, as_version=4)
    nbformat.validate(nb)
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        source = "\n".join(line for line in cell.source.splitlines()
                           if not line.lstrip().startswith(("%", "!")))
        ast.parse(source)                                  # every code cell is valid Python
        assert not cell.get("outputs"), "commit notebooks without outputs"


def test_configuration_notebook_runs(tmp_path):
    pytest.importorskip("ipywidgets")
    pytest.importorskip("ipykernel")
    nbclient = pytest.importorskip("nbclient")
    src = os.path.join(ROOT, "notebooks", "configure_and_run.ipynb")
    work = tmp_path / "work"
    work.mkdir()
    shutil.copy(src, work)
    nb = nbformat.read(str(work / "configure_and_run.ipynb"), as_version=4)
    client = nbclient.NotebookClient(nb, timeout=300, kernel_name="python3",
                                     resources={"metadata": {"path": str(work)}})
    client.execute()
    text = "".join(o.get("text", "") for c in nb.cells if c.cell_type == "code"
                   for o in c.get("outputs", []))
    assert "Fix these before running" in text              # no DEM yet → told what to do
    assert "cfg = Config(" in text                         # the Python view
    assert "CHANNEL_QBF_M3S — Bankfull flow" in text       # explain()
    assert (work / "my_run.yaml").exists()
    widget_outputs = [o for c in nb.cells for o in c.get("outputs", [])
                      if "application/vnd.jupyter.widget-view+json" in o.get("data", {})]
    assert widget_outputs, "the form did not display as a widget"
