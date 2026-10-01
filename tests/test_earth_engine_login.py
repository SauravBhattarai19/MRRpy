# -*- coding: utf-8 -*-
"""
tests/test_earth_engine_login.py
================================
Signing in to Google Earth Engine (``MRRpy.connect_earth_engine``,
``MRRpy earth-engine-login``, the form's *Connect* button) and the map
picker that must work without Earth Engine.  A fake ``ee`` module stands in
for Earth Engine, so these tests never touch the network.

Run:  pytest tests/test_earth_engine_login.py -v
"""

import sys
import types

import pytest

import MRRpy
from MRRpy.cli.main import main as cli
from MRRpy.gee import auth


class FakeEE:
    """Records calls; behaves like a signed-in (or failing) Earth Engine."""

    def __init__(self, init_error=None, request_error=None):
        self.init_error, self.request_error = init_error, request_error
        self.calls = []
        fake = self

        class _Num:
            def __init__(self, v):
                pass

            def getInfo(self):
                fake.calls.append("getInfo")
                if fake.request_error:
                    raise fake.request_error
                return 1

        self.Number = _Num

    def Initialize(self, *args, **kw):
        self.calls.append(("Initialize", kw.get("project")))
        if self.init_error:
            raise self.init_error

    def Authenticate(self, **kw):
        self.calls.append(("Authenticate", kw))
        self.init_error = None                      # signing in fixes the credentials


@pytest.fixture
def fake_ee(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)                     # no stray key.json
    for var in ("GOOGLE_APPLICATION_CREDENTIALS", "GEE_SERVICE_ACCOUNT_KEY", "GEE_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    ee = FakeEE()
    monkeypatch.setattr(auth, "ee", ee, raising=False)
    monkeypatch.setattr(auth, "GEE_AVAILABLE", True)
    monkeypatch.setattr(auth, "_saved_sign_in", lambda: True)
    return ee


# ── Plain-language errors ────────────────────────────────────────────────────
@pytest.mark.parametrize("error, words", [
    ("Please authorize access to your Earth Engine account", "not signed in"),
    ("invalid_grant: Token has been expired or revoked.", "not signed in"),
    ("Project 'projects/xyz' not found or deleted.", "can't be used with Earth Engine"),
    ("Caller does not have required permission to use project xyz", "registered"),
    ("Connection reset by peer", "Could not connect"),
])
def test_errors_are_explained(error, words):
    assert words in auth.explain_error(Exception(error), "xyz")


def test_missing_project_is_explained():
    msg = auth.explain_error(Exception("no project found. Call with project="), None)
    assert "project ID" in msg and "ee-yourname" in msg


# ── status() never prompts ───────────────────────────────────────────────────
def test_status_connected(fake_ee):
    ok, msg = auth.status("ee-me")
    assert ok and "Connected" in msg and "ee-me" in msg
    assert ("Initialize", "ee-me") in fake_ee.calls and "getInfo" in fake_ee.calls
    assert not any(c[0] == "Authenticate" for c in fake_ee.calls if isinstance(c, tuple))


def test_status_not_signed_in(fake_ee, monkeypatch):
    monkeypatch.setattr(auth, "_saved_sign_in", lambda: False)
    ok, msg = auth.status("ee-me")
    assert not ok and "not signed in" in msg and "connect_earth_engine('ee-me')" in msg
    assert fake_ee.calls == []


def test_status_bad_project(fake_ee):
    fake_ee.request_error = Exception("Project 'projects/nope' not found or deleted.")
    ok, msg = auth.status("nope")
    assert not ok and "'nope'" in msg and "register" in msg


def test_status_without_earthengine_api(monkeypatch):
    monkeypatch.setattr(auth, "GEE_AVAILABLE", False)
    ok, msg = auth.status("x")
    assert not ok and 'pip install "MRRpy[gee]"' in msg


# ── connect() signs in only when needed ──────────────────────────────────────
def _authenticated(ee):
    return [c for c in ee.calls if isinstance(c, tuple) and c[0] == "Authenticate"]


def test_connect_uses_the_saved_sign_in(fake_ee, capsys):
    assert MRRpy.connect_earth_engine("ee-me") is True
    assert not _authenticated(fake_ee)
    assert "Connected" in capsys.readouterr().out


def test_connect_signs_in_when_never_signed_in(fake_ee, monkeypatch, capsys):
    state = {"saved": False}
    monkeypatch.setattr(auth, "_saved_sign_in", lambda: state["saved"])
    real = fake_ee.Authenticate

    def sign_in(**kw):
        state["saved"] = True
        real(**kw)

    fake_ee.Authenticate = sign_in
    assert auth.connect("ee-me", auth_mode="notebook") is True
    assert _authenticated(fake_ee)[0][1]["auth_mode"] == "notebook"
    out = capsys.readouterr().out
    assert "follow the link" in out and "Connected" in out


def test_connect_does_not_sign_in_for_a_project_problem(fake_ee, capsys):
    fake_ee.request_error = Exception("Project 'projects/nope' not found or deleted.")
    assert auth.connect("nope") is False
    assert not _authenticated(fake_ee)
    assert "register" in capsys.readouterr().out


def test_connect_check_only_and_force(fake_ee, monkeypatch):
    monkeypatch.setattr(auth, "_saved_sign_in", lambda: False)
    assert auth.connect("ee-me", sign_in=False, quiet=True) is False
    assert not _authenticated(fake_ee)
    monkeypatch.setattr(auth, "_saved_sign_in", lambda: True)
    assert auth.connect("ee-me", force=True, quiet=True) is True
    assert _authenticated(fake_ee)[0][1]["force"] is True


def test_connect_reports_a_failed_sign_in(fake_ee, monkeypatch, capsys):
    monkeypatch.setattr(auth, "_saved_sign_in", lambda: False)

    def refuse(**kw):
        raise Exception("invalid_grant: bad code")

    fake_ee.Authenticate = refuse
    assert auth.connect("ee-me") is False
    assert "not signed in" in capsys.readouterr().out


# ── Command line ─────────────────────────────────────────────────────────────
def test_cli_earth_engine_login(monkeypatch):
    seen = []
    monkeypatch.setattr(auth, "connect", lambda **kw: seen.append(kw) or kw["sign_in"])
    assert cli(["earth-engine-login", "--project", "ee-me"]) == 0
    assert seen[-1] == dict(project="ee-me", sign_in=True, force=False, auth_mode=None)
    assert cli(["earth-engine-login", "--check"]) == 1
    assert seen[-1]["sign_in"] is False
    assert cli(["earth-engine-login", "--force", "--auth-mode", "notebook"]) == 0
    assert seen[-1]["force"] and seen[-1]["auth_mode"] == "notebook"


def test_wizard_review_shows_the_sign_in_command(tiny_basin, tmp_path):
    from MRRpy.interactive.wizard import run_wizard
    from _interactive_helpers import Script
    dem, _pt = tiny_basin
    s = Script({"Elevation model (DEM) file": dem, "Google Earth Engine project": "ee-me",
                "Storm start (UTC)": "2024-09-27 00:00",
                "Save the configuration as": str(tmp_path / "r.yaml")})
    run_wizard(starting_point="satellite_event", input_fn=s, print_fn=s.out)
    assert "MRRpy earth-engine-login --project ee-me" in s.text


# ── The form's Connect button ────────────────────────────────────────────────
def test_form_connect_button(monkeypatch):
    pytest.importorskip("ipywidgets")
    from MRRpy.interactive.form import ConfigForm
    asked = []
    monkeypatch.setattr(auth, "status",
                        lambda project: asked.append(project) or (False, "not signed in yet"))
    f = ConfigForm(map=False)
    f.fields["PRECIP_METHOD"].group.value = "imerg"
    box, note, field = f.gee_boxes["rain"]
    assert "Connect" in note.value
    field.text.value = "ee-me"
    button, result = f.connect_btns["rain"]
    button.click()
    assert asked == ["ee-me"] and f.ee_connected is False
    assert "Problem: not signed in yet" in result.value and 'role="alert"' in result.value
    assert "not signed in yet" in f.connect_btns["terrain"][1].value      # every box updated
    monkeypatch.setattr(auth, "status", lambda project: (True, "Connected (ee-me)."))
    button.click()
    assert f.ee_connected is True and "Problem" not in result.value


# ── Map picker: drawing needs no Earth Engine ────────────────────────────────
def test_pick_bounds_map_needs_no_earth_engine(monkeypatch):
    pytest.importorskip("ipyleaflet")
    monkeypatch.setitem(sys.modules, "geemap", None)          # importing it would fail
    monkeypatch.setitem(sys.modules, "ee", types.ModuleType("ee"))   # an uninitialised ee
    from MRRpy.utils.notebook_map import get_drawn_bounds, pick_bounds_map
    m = pick_bounds_map(center=(27.7, 85.3), zoom=8, ee_initialize=True)
    with pytest.raises(RuntimeError, match="No shape has been drawn"):
        get_drawn_bounds(m)
    rect = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [
        [[85.0, 27.0], [85.0, 28.0], [86.0, 28.0], [86.0, 27.0], [85.0, 27.0]]]}}
    draw = m.draw_control
    draw._draw_callbacks(draw, action="created", geo_json=rect)
    assert get_drawn_bounds(m) == (85.0, 27.0, 86.0, 28.0)
    draw._draw_callbacks(draw, action="deleted", geo_json=rect)
    with pytest.raises(RuntimeError):
        get_drawn_bounds(m)
