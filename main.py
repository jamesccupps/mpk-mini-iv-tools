"""Entry point for MPK Macro Studio."""
import sys

if sys.platform != "win32":
    raise SystemExit("MPK Macro Studio is Windows only (it uses winmm and SendInput).")

from mpkmacro.gui import main

if __name__ == "__main__":
    main()
