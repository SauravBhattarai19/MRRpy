# -*- coding: utf-8 -*-
"""
_http.py — downloading an Earth Engine file without hanging.

``urllib.request.urlretrieve`` has no timeout: one connection that stalls (the
request sent, nothing ever coming back) hangs the whole run with no message.
``fetch`` drops a connection that sends nothing for *stall_s* seconds and tries
again; a slow but moving download is never cut.
"""

import shutil
import time
import urllib.error
import urllib.request


def fetch(url, output_path, stall_s=300.0, tries=3, wait_s=5.0, log=print):
    """Download *url* to *output_path*; RuntimeError after *tries* failures,
    waiting *wait_s* × attempt between them."""
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=stall_s) as resp, open(output_path, "wb") as f:
                shutil.copyfileobj(resp, f)
            return output_path
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            if k == tries - 1:
                raise RuntimeError(f"the Earth Engine download failed {tries} times "
                                   f"(last: {exc})") from exc
            log(f"  [WARN] Earth Engine download stalled or failed ({exc}); trying again …")
            time.sleep(wait_s * (k + 1))
