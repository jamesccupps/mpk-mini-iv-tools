"""Tests for dialog lifecycles. Needs a display, but no keyboard.

Uses a stand-in for the main window rather than App(), because App()
auto-connects to whatever MIDI input it finds and would grab a real keyboard.
"""
import os
import queue
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.geometry("200x100+-3000+-3000")   # mapped (grab needs it), off-screen
    _root.update()
except Exception as exc:                       # headless CI, no display
    raise unittest.SkipTest(f"no Tk display available: {exc}")

from mpkmacro import engine as eng            # noqa: E402
from mpkmacro import gui                      # noqa: E402

NOTE_ON = 0x90


class FakeApp:
    """Just the parts of gui.App that MappingDialog talks to."""
    start_learn = gui.App.start_learn
    cancel_learn = gui.App.cancel_learn

    def __init__(self):
        self.engine = eng.Engine()
        self.engine.midi_in.is_open = True        # pretend we're connected
        self.ui_queue = queue.SimpleQueue()

    def deliver(self):
        """What App._drain_ui does with a queued learn."""
        kind, (cb, status, d1, d2) = self.ui_queue.get_nowait()
        cb(status, d1, d2)


class TestMidiLearn(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.dlg = gui.MappingDialog(_root, self.app)
        self.dlg.update()

    def tearDown(self):
        if self.dlg.winfo_exists():
            self.dlg.destroy()

    def hit(self, note):
        """The engine receiving a pad hit while a learn is armed."""
        self.app.engine._handle(NOTE_ON, note, 100)

    def test_learn_fills_the_trigger(self):
        self.dlg._learn()
        self.hit(40)
        self.app.deliver()
        self.assertEqual(self.dlg.t_num.get(), "40")
        self.assertIsNone(self.app.engine.learn_callback)

    def test_closing_the_dialog_disarms_learn(self):
        """Left armed, the next pad hit was swallowed -- no macro fired, no
        passthrough -- and handed to a destroyed dialog."""
        self.dlg._learn()
        self.dlg.destroy()
        self.assertIsNone(self.app.engine.learn_callback)

    def test_a_hit_queued_before_close_is_dropped_quietly(self):
        self.dlg._learn()
        self.hit(40)                    # captured, waiting in the UI queue
        self.dlg.destroy()
        self.app.deliver()              # must not raise TclError

    def test_closing_without_learning_leaves_others_alone(self):
        other = object()
        self.app.engine.learn_callback = other
        self.dlg.destroy()
        self.assertIs(self.app.engine.learn_callback, other)


if __name__ == "__main__":
    unittest.main(verbosity=2)
