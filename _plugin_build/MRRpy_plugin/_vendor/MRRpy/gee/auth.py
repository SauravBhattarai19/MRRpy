# -*- coding: utf-8 -*-
"""
auth.py — Google Earth Engine authentication.

Single authentication entry point shared by every GEE-backed download
(serves_gee, imerg_gee).  Credential resolution order:
  1. GOOGLE_APPLICATION_CREDENTIALS service-account file (or a key.json
     found next to this package, at the package root, or in the CWD)
  2. GEE_SERVICE_ACCOUNT_KEY inline JSON
  3. Earth Engine default credentials, then the interactive flow.
"""

import json
import logging
import os

try:
    import ee
    GEE_AVAILABLE = True
except ImportError:
    GEE_AVAILABLE = False

logger = logging.getLogger(__name__)


def authenticate(project=None, interactive=True):
    """Initialize GEE with the best available credentials.

    ``interactive=False`` never opens the browser sign-in flow (for optional,
    best-effort lookups that must not block a headless run)."""
    proj = project or os.environ.get('GEE_PROJECT')
    init_kw = {'project': proj} if proj else {}

    sa_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if not sa_path:
        # Non-interactive shells (conda run, HPC) don't source ~/.bashrc, so the
        # env var may be absent.  Fall back to a key.json next to this module,
        # at the package root, or in the current working directory.
        _here = os.path.dirname(os.path.abspath(__file__))
        for _candidate in (os.path.join(_here, 'key.json'),
                           os.path.join(os.path.dirname(_here), 'key.json'),
                           os.path.join(os.getcwd(), 'key.json')):
            if os.path.isfile(_candidate):
                sa_path = _candidate
                break
    if sa_path and os.path.isfile(sa_path):
        try:
            credentials = ee.ServiceAccountCredentials(None, sa_path)
            ee.Initialize(credentials, **init_kw)
            logger.info("GEE authenticated via GOOGLE_APPLICATION_CREDENTIALS")
            return True
        except Exception as exc:
            logger.warning("Service account auth failed: %s", exc)

    sa_json = os.environ.get('GEE_SERVICE_ACCOUNT_KEY')
    if sa_json:
        try:
            key_data = json.loads(sa_json)
            credentials = ee.ServiceAccountCredentials(
                key_data['client_email'], key_data=sa_json
            )
            ee.Initialize(credentials, **init_kw)
            logger.info("GEE authenticated via GEE_SERVICE_ACCOUNT_KEY")
            return True
        except Exception as exc:
            logger.warning("Inline service account auth failed: %s", exc)

    try:
        ee.Initialize(**init_kw)
        logger.info("GEE authenticated via default credentials")
        return True
    except Exception:
        if not interactive:
            logger.warning("GEE default credentials unavailable (non-interactive)")
            return False
        try:
            ee.Authenticate()
            ee.Initialize(**init_kw)
            logger.info("GEE authenticated via interactive flow")
            return True
        except Exception as exc:
            logger.warning("GEE authentication failed: %s", exc)
            return False


# ═════════════════════════════════════════════════════════════════════════════
# User-facing: check the connection, and sign in once
# ═════════════════════════════════════════════════════════════════════════════
_REGISTER_URL = "https://code.earthengine.google.com/register"
_NO_GEE = 'Earth Engine support is not installed. Install it with: pip install "MRRpy[gee]"'


def _saved_sign_in():
    """True when this computer has a saved Earth Engine sign-in (or a service key)."""
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GEE_SERVICE_ACCOUNT_KEY"):
        return True
    _here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(_here, "key.json"),
                 os.path.join(os.path.dirname(_here), "key.json"),
                 os.path.join(os.getcwd(), "key.json")):
        if os.path.isfile(path):
            return True
    try:
        from ee import oauth
        return os.path.isfile(oauth.get_credentials_path())
    except Exception:   # noqa: BLE001
        return False


def explain_error(exc, project=None):
    """A plain-language explanation of an Earth Engine connection error."""
    text = str(exc)
    low = text.lower()
    short = text.strip().splitlines()[0][:300] if text.strip() else type(exc).__name__
    login = (f"MRRpy.connect_earth_engine({project!r})" if project
             else "MRRpy.connect_earth_engine('your-project')")
    if any(k in low for k in ("authorize", "credential", "authenticate", "sign in",
                              "invalid_grant", "refresh token", "token has been expired")):
        return ("This computer is not signed in to Earth Engine (or the saved sign-in "
                f"expired). Sign in once: run {login} in a notebook cell, or "
                "`MRRpy earth-engine-login` in a terminal. It shows a link to sign in "
                "with your Google account.")
    if "project" in low and any(k in low for k in ("no project", "not found", "missing",
                                                   "must be", "required")) and not project:
        return ("Earth Engine needs a Google Cloud project ID, e.g. 'ee-yourname'. Find yours "
                "at https://code.earthengine.google.com (the person icon, top right) or "
                "https://console.cloud.google.com.")
    if any(k in low for k in ("permission", "not registered", "403", "denied", "not found",
                              "does not exist", "has not been used", "disabled")):
        return (f"Signed in, but the project {project!r} can't be used with Earth Engine: "
                f"{short}  Check the project ID, and that the project is registered for "
                f"Earth Engine ({_REGISTER_URL}).")
    return f"Could not connect to Earth Engine: {short}"


def status(project=None):
    """
    (connected, message): can Earth Engine be used right now with *project*?

    Never opens a sign-in prompt, so it is safe in buttons and scripts.  It
    makes one tiny request to confirm the sign-in and the project really work.
    """
    if not GEE_AVAILABLE:
        return False, _NO_GEE
    proj = project or os.environ.get("GEE_PROJECT")
    if not _saved_sign_in():
        return False, explain_error(Exception("not signed in: no credentials"), proj)
    try:
        if not authenticate(proj, interactive=False):
            ee.Initialize(**({"project": proj} if proj else {}))   # re-raise the reason
        ee.Number(1).getInfo()
    except Exception as exc:   # noqa: BLE001 — ee raises many types
        return False, explain_error(exc, proj)
    where = f"project {proj}" if proj else "your default project"
    return True, f"Connected to Google Earth Engine ({where})."


def connect(project=None, sign_in=True, force=False, auth_mode=None, quiet=False):
    """
    Connect to Google Earth Engine, signing in first if this computer has no
    saved sign-in.  Returns True when Earth Engine is ready to use.

        import MRRpy
        MRRpy.connect_earth_engine("ee-yourname")

    The sign-in shows a link: open it, sign in with the Google account that
    has Earth Engine access, and paste the code it gives you back here.  It is
    saved, so you only do this once per computer.  Works in Jupyter, in a
    terminal and over SSH.  ``force=True`` signs in again (e.g. with another
    account); ``auth_mode`` is passed to ``ee.Authenticate`` ('notebook',
    'localhost', 'gcloud', 'colab').
    """
    say = (lambda *_a: None) if quiet else print
    if not GEE_AVAILABLE:
        say(_NO_GEE)
        return False
    proj = project or os.environ.get("GEE_PROJECT")
    if not proj:
        say("Tip: give your Earth Engine project ID, e.g. "
            "MRRpy.connect_earth_engine('ee-yourname').")
    if not force:
        ok, message = status(proj)
        if ok or not sign_in:
            say(message)
            return ok
        if _saved_sign_in() and "not signed in" not in message:
            say(message)                     # signed in, but e.g. the project is wrong
            return False
    say("Signing in to Google Earth Engine — follow the link below, then paste the code.")
    try:
        ee.Authenticate(force=True if force else False,
                        **({"auth_mode": auth_mode} if auth_mode else {}))
    except Exception as exc:   # noqa: BLE001
        say(explain_error(exc, proj))
        return False
    ok, message = status(proj)
    say(message)
    return ok
