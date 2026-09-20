# SPDX-License-Identifier: GPL-3.0-or-later
"""A scan that runs where you can see it.

A scan was a blocking GET. On the rig it takes about fifty seconds -- almost
all of it one line, ``Building Heroic metadata cache``, walking fourteen
thousand files under ``%APPDATA%`` -- and for that whole time the interface
returned nothing at all: no window change, no spinner, no text. The maintainer, having
deleted two entries and pressed Rescan: "Scan runs with no visible indicator,
we need some sort of indicator it is running." He was about to report the two
entries as undetected when they came back.

So the scan runs on a thread and the page that asked for it comes back
immediately. What it is doing is not invented for the page -- the importers
have always said it, to a log nobody reads -- so this listens to
``core.utils.log`` while the scan runs and keeps the last of it.

**One at a time.** Two scans over the same libraries would take twice as long,
interleave their log lines, and stage the same changes twice. Asking for a scan
while one is running joins the one that is running.
"""

import collections
import threading
import time
from typing import Callable, Dict, List, Optional

# Enough to see what happened, not so much that a runaway importer fills
# memory. The page only ever shows the last line; the rest is for the report.
LINES = 200


class ScanJob:
    """The scan that is running, if one is. There is at most one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lines: collections.deque = collections.deque(maxlen=LINES)
        self._running = False
        self._started = 0.0
        self._finished = 0.0
        self._error = ""
        self._staged = 0
        self._run = 0

    # --- what the page asks -------------------------------------------------

    def running(self) -> bool:
        with self._lock:
            return self._running

    def status(self) -> Dict:
        """Everything the scanning page needs, in one read."""
        with self._lock:
            elapsed = ((self._finished or time.monotonic()) - self._started
                       if self._started else 0.0)
            return {
                "running": self._running,
                "run": self._run,
                "elapsed": round(elapsed, 1),
                "latest": self._lines[-1] if self._lines else "",
                "lines": list(self._lines),
                "error": self._error,
                "staged": self._staged,
                "ran": bool(self._started),
            }

    # --- running one --------------------------------------------------------

    def start(self, work: Callable[[], int],
              on_error: Optional[Callable[[str], None]] = None) -> bool:
        """Begin a scan on a thread. False if one was already running.

        *work* does the scan and returns how many changes it staged. It runs
        off the request thread, so it must not touch the handler.
        """
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._run += 1
            self._started = time.monotonic()
            self._finished = 0.0
            self._error = ""
            self._staged = 0
            self._lines.clear()

        thread = threading.Thread(target=self._work, args=(work, on_error),
                                  name="sunshine-apps-ui-scan", daemon=True)
        thread.start()
        return True

    def _note(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    def _work(self, work: Callable[[], int],
              on_error: Optional[Callable[[str], None]]) -> None:
        from .core import utils

        utils.watch(self._note)
        error, staged = "", 0
        try:
            staged = int(work() or 0)
        except Exception as e:                  # noqa: BLE001 - reported, not raised
            # Raising here would kill the thread with nobody to catch it and
            # leave the page spinning for ever. The page says what went wrong.
            error = str(e) or e.__class__.__name__
            if on_error is not None:
                try:
                    on_error(error)
                except Exception:               # noqa: BLE001
                    pass
        finally:
            utils.unwatch(self._note)
            with self._lock:
                self._running = False
                self._finished = time.monotonic()
                self._error = error
                self._staged = staged


# One server, one scan. Held here rather than on the handler, which is built
# fresh for every request.
job = ScanJob()
