"""Log file setup.

The app is normally launched with pythonw, where stderr goes nowhere. Without
a file, any failure -- a profile that won't parse, a port that won't open, an
exception in a button handler -- would leave no trace at all.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent / "mpk-macro-studio.log"
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(level=logging.INFO, path=LOG_PATH):
    root = logging.getLogger()
    if root.handlers:
        return
    fmt = logging.Formatter(FORMAT)
    try:
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=512_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError as exc:
        # A read-only install folder shouldn't stop the app; say so on stderr
        # if there is one.
        if sys.stderr:
            print(f"cannot write {path}: {exc}", file=sys.stderr)
    if sys.stderr:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    root.setLevel(level)
