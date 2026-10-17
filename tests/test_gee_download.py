# -*- coding: utf-8 -*-
"""
tests/test_gee_download.py
==========================
Earth Engine files are fetched with ``MRRpy.gee._http.fetch``: a connection
that stalls must end in a clear error, not hang the run (``urlretrieve`` has no
timeout and hung runs forever), and a good download must arrive whole.
No Earth Engine or internet needed: a local server stands in.

Run:  pytest tests/test_gee_download.py -v
"""

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from MRRpy.gee._http import fetch


def test_stalled_connection_ends_in_an_error(tmp_path):
    """The server accepts the connection and never answers."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    held = []
    stop = threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(srv.accept()[0])            # keep it open, say nothing
            except OSError:
                pass
    th = threading.Thread(target=accept, daemon=True)
    th.start()
    url = f"http://127.0.0.1:{srv.getsockname()[1]}/tile.tif"
    t0 = time.perf_counter()
    try:
        with pytest.raises(RuntimeError, match="failed 2 times"):
            fetch(url, str(tmp_path / "tile.tif"), stall_s=0.5, tries=2, wait_s=0.0,
                  log=lambda m: None)
    finally:
        stop.set()
        th.join()
        for c in held:
            c.close()
        srv.close()
    assert time.perf_counter() - t0 < 10.0
    assert len(held) == 2                                  # it tried again once


def test_good_download_arrives_whole(tmp_path):
    body = bytes(range(256)) * 4000

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    th = threading.Thread(target=httpd.handle_request, daemon=True)
    th.start()
    out = tmp_path / "tile.tif"
    fetch(f"http://127.0.0.1:{httpd.server_address[1]}/tile.tif", str(out), stall_s=5.0)
    th.join()
    httpd.server_close()
    assert out.read_bytes() == body
