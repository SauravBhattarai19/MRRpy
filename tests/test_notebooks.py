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
             for n in ("configure_and_run.ipynb", "pick_dem_bounds.ipynb", "flood_maps_2d.ipynb",
                       "quickstart_demo.ipynb")]


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


def test_quickstart_notebook_runs_offline(tmp_path):
    """The first-run notebook, without its last section (a real DEM download)."""
    pytest.importorskip("ipykernel")
    nbclient = pytest.importorskip("nbclient")
    nb = nbformat.read(os.path.join(ROOT, "notebooks", "quickstart_demo.ipynb"), as_version=4)
    stop = next(i for i, c in enumerate(nb.cells) if c.source.startswith("## 5."))
    nb.cells = nb.cells[:stop]
    client = nbclient.NotebookClient(nb, timeout=600, kernel_name="python3",
                                     resources={"metadata": {"path": str(tmp_path)}})
    client.execute()
    text = "".join(o.get("text", "") for c in nb.cells if c.cell_type == "code"
                   for o in c.get("outputs", []))
    assert "Peak flow at the outlet" in text and "water balance closes" in text
    assert (tmp_path / "mrrpy_demo" / "curve_numbers" / "summary.csv").exists()
