# -*- coding: utf-8 -*-
"""
runlog.py
=========
What a run prints, where it goes, and how a run is stopped.

The model reports with plain ``print``.  While a run is going, :func:`capture`
sends those lines to up to three places at once:

* the screen (all of it, or only warnings with ``quiet=True``),
* a log file (``{OUTPUT_DIR}/run.log``),
* a callback, one line at a time (the QGIS plugin's log panel, the notebook form).

``sys.stdout`` is replaced by a small proxy for the duration, but the proxy
only redirects text printed *by the run that asked for it* (tracked with a
context variable): other threads, and anything printed outside a run, pass
straight through.  Two runs in two threads therefore keep separate logs,
which a plain ``sys.stdout`` swap cannot do.

:class:`RunCancelled` is raised inside the time loop when the caller's
``is_cancelled()`` turns true, so a long routing run stops within one step.
"""

import contextlib
import contextvars
import sys
import threading

#: Lines carrying one of these tags are shown even in quiet mode.
IMPORTANT = ("[WARN", "[ERROR", "[NOTE", "[DEPRECATED", "[CFL WARNING", "[INFO] Run cancelled")


class RunCancelled(Exception):
    """The caller asked the run to stop (``is_cancelled()`` returned True)."""


_sink = contextvars.ContextVar("mrrpy_run_sink", default=None)
_lock = threading.Lock()
_active = 0            # captures in progress (any thread)


class _Sink:
    """Where one run's text goes."""

    def __init__(self, stream, on_line, log_file, quiet):
        self.stream = stream            # the screen (may be None, e.g. QGIS on Windows)
        self.on_line = on_line
        self.log_file = log_file
        self.quiet = quiet
        self._buf = ""

    def write(self, text):
        text = str(text)
        if self.log_file is not None:
            try:
                self.log_file.write(text)
            except (OSError, ValueError):
                self.log_file = None
        if self.on_line is None and not self.quiet:
            self._screen(text)
        if self.on_line is not None or self.quiet:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._line(line)
        return len(text)

    def _line(self, line):
        if self.on_line is not None:
            self.on_line(line)
        elif any(tag in line for tag in IMPORTANT):       # quiet: warnings only
            self._screen(line + "\n")

    def _screen(self, text):
        if self.stream is not None:
            try:
                self.stream.write(text)
            except (OSError, ValueError):
                pass

    def close(self):
        if self._buf:
            self._line(self._buf)
            self._buf = ""
        if self.log_file is not None:
            try:
                self.log_file.flush()
            except (OSError, ValueError):
                pass


class _Proxy:
    """Stands in for sys.stdout: a run's text goes to its sink, the rest passes."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        sink = _sink.get()
        if sink is not None:
            return sink.write(text)
        if self._stream is None:
            return len(text)
        return self._stream.write(text)

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except (OSError, ValueError):
                pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


@contextlib.contextmanager
def capture(on_line=None, log_path=None, quiet=False):
    """
    Route everything printed inside the ``with`` block (by this thread / task).

    on_line  : callable(str) — gets each finished line; the screen then gets
               nothing (the caller shows the lines itself).
    log_path : file to append the text to (None: no file).
    quiet    : without *on_line*, show only warnings on the screen.
    """
    global _active
    log_file = None
    if log_path:
        try:
            log_file = open(log_path, "a", encoding="utf-8")
        except OSError:
            log_file = None
    with _lock:
        if not isinstance(sys.stdout, _Proxy):
            sys.stdout = _Proxy(sys.stdout)
        proxy = sys.stdout
        _active += 1
    outer = _sink.get()
    stream = outer if outer is not None else proxy._stream
    sink = _Sink(stream, on_line, log_file, quiet)
    token = _sink.set(sink)
    try:
        yield sink
    finally:
        _sink.reset(token)
        sink.close()
        if log_file is not None:
            log_file.close()
        with _lock:
            _active -= 1
            if _active == 0 and sys.stdout is proxy:
                sys.stdout = proxy._stream


def check_cancelled(is_cancelled):
    """Raise RunCancelled when the caller's *is_cancelled* (may be None) says so."""
    if is_cancelled is not None and is_cancelled():
        raise RunCancelled()


def eta_text(done_fraction, elapsed_s):
    """'about 3 min left' from the share of the run done and the time it took."""
    if done_fraction <= 0 or done_fraction >= 1:
        return ""
    left = elapsed_s * (1.0 - done_fraction) / done_fraction
    if left < 90:
        return f"about {max(1, round(left))} s left"
    if left < 5400:
        return f"about {round(left / 60)} min left"
    return f"about {left / 3600:.1f} h left"
