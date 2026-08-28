"""Tests for the live panel view. Needs a display, but no keyboard."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
except Exception as exc:                       # headless CI, no display
    raise unittest.SkipTest(f"no Tk display available: {exc}")

from mpkmacro import mpk_preset            # noqa: E402
from mpkmacro.device_view import DeviceView  # noqa: E402
from tests import fixtures                 # noqa: E402

PAD_CH = 0x90 | 9        # pads transmit on ch10
KEY_CH = 0x90 | 0        # keys on ch1


class DeviceViewCase(unittest.TestCase):
    def setUp(self):
        self.view = DeviceView(_root)
        self.view.set_preset(mpk_preset.parse(fixtures.PRESET_DAW))

    def tearDown(self):
        self.view.destroy()


class TestBankFollowing(DeviceViewCase):
    """BANK A/B only recolours its own button, so the bank must be inferred."""

    def test_starts_on_bank_a(self):
        self.assertEqual(self.view.bank.get(), "A")

    def test_bank_b_note_switches_the_view(self):
        self.view.handle_midi(PAD_CH, 44, 100)     # pad 1, bank B
        self.assertEqual(self.view.bank.get(), "B")

    def test_and_switches_back(self):
        self.view.handle_midi(PAD_CH, 44, 100)
        self.view.handle_midi(PAD_CH, 36, 100)     # pad 1, bank A
        self.assertEqual(self.view.bank.get(), "A")

    def test_label_matches_the_bank(self):
        self.view.handle_midi(PAD_CH, 44, 100)
        self.assertIn("Pad 1B", self.view.hit_lbl.get())
        self.view.handle_midi(PAD_CH, 36, 100)
        self.assertIn("Pad 1A", self.view.hit_lbl.get())

    def test_last_pad_of_each_bank(self):
        self.view.handle_midi(PAD_CH, 43, 100)     # pad 8, bank A
        self.assertEqual(self.view.bank.get(), "A")
        self.assertIn("Pad 8A", self.view.hit_lbl.get())
        self.view.handle_midi(PAD_CH, 51, 100)     # pad 8, bank B
        self.assertEqual(self.view.bank.get(), "B")
        self.assertIn("Pad 8B", self.view.hit_lbl.get())


class TestPadsVersusKeys(DeviceViewCase):
    """Pads and keys share note numbers; only the channel separates them."""

    def test_pad_channel_from_preset(self):
        self.assertEqual(self.view.pad_channel, 9)

    def test_note_36_on_pad_channel_is_a_pad(self):
        self.view.handle_midi(PAD_CH, 36, 100)
        self.assertTrue(self.view.hit_lbl.get().startswith("Pad"))

    def test_note_36_on_key_channel_is_a_key(self):
        self.view.handle_midi(KEY_CH, 36, 100)
        self.assertTrue(self.view.hit_lbl.get().startswith("Key"))

    def test_key_outside_range_rebases_the_keyboard(self):
        self.view.handle_midi(KEY_CH, 24, 100)
        self.assertLessEqual(self.view.key_base, 24)
        self.assertTrue(self.view.hit_lbl.get().startswith("Key"))


class TestControlRecognition(DeviceViewCase):
    def test_knob_by_cc_from_preset(self):
        self.view.handle_midi(0xB0, 24, 88)
        self.assertIn("Knob 1", self.view.hit_lbl.get())
        self.view.handle_midi(0xB0, 31, 10)
        self.assertIn("Knob 8", self.view.hit_lbl.get())

    def test_mod_wheel_is_cc1(self):
        self.view.handle_midi(0xB0, 1, 50)
        self.assertIn("Mod wheel", self.view.hit_lbl.get())

    def test_pitch_wheel(self):
        self.view.handle_midi(0xE0, 0, 100)
        self.assertIn("Pitch", self.view.hit_lbl.get())

    def test_unknown_cc_still_offers_a_macro(self):
        """Buttons send CCs we have no name for; they should stay usable."""
        self.view.handle_midi(0xB0, 82, 127)
        self.assertIn("82", self.view.hit_lbl.get())
        self.assertIsNotNone(self.view._hit)


class TestClickTargets(DeviceViewCase):
    def test_pad_click_uses_the_current_bank(self):
        trig, _ = self.view._trigger_for("pad", 0)
        self.assertEqual(trig["number"], 36)
        self.view.handle_midi(PAD_CH, 44, 100)      # flip to bank B
        trig, _ = self.view._trigger_for("pad", 0)
        self.assertEqual(trig["number"], 44)

    def test_knob_click_uses_preset_cc(self):
        trig, _ = self.view._trigger_for("knob", 2)
        self.assertEqual(trig, {"type": "cc", "channel": -1,
                                "number": 26, "value": None})

    def test_pitch_click(self):
        trig, _ = self.view._trigger_for("pitch", 0)
        self.assertEqual(trig["type"], "pitchbend")


if __name__ == "__main__":
    unittest.main(verbosity=2)
