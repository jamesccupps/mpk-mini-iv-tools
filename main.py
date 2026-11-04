"""Entry point for MPK Macro Studio."""
import logging
import platform
import sys

if sys.platform != "win32":
    raise SystemExit("MPK Macro Studio is Windows only (it uses winmm and SendInput).")

from mpkmacro import __version__, applog
from mpkmacro.gui import main

if __name__ == "__main__":
    applog.setup()
    logging.getLogger("mpkmacro").info(
        "MPK Macro Studio %s, Python %s", __version__, platform.python_version())
    main()
