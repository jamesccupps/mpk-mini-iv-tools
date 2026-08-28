"""Tests for macro matching, knob scaling and the feedback-loop guard."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpkmacro import engine as eng      # noqa: E402
from mpkmacro import winmidi            # noqa: E402

NOTE_ON, NOTE_OFF, CC = 0x90, 0x80, 0xB0


def mapping(**trigger):
    base = {"type": "note_on", "channel": -1, "number": 36, "value": None}
    base.update(trigger)
    return {"enabled": True, "trigger": base}


class TestTriggerMatching(unittest.TestCase):
    def test_matches_its_note(self):
        self.assertTrue(eng.matches(mapping(), NOTE_ON, 36, 100))

    def test_ignores_other_notes(self):
        self.assertFalse(eng.matches(mapping(), NOTE_ON, 37, 100))

    def test_note_on_velocity_zero_is_a_note_off(self):
        """The usual running-status trick: 0x9n with velocity 0 means off."""
        self.assertFalse(eng.matches(mapping(), NOTE_ON, 36, 0))
        self.assertTrue(
            eng.matches(mapping(type="note_off"), NOTE_ON, 36, 0))

    def test_explicit_note_off(self):
        self.assertTrue(eng.matches(mapping(type="note_off"), NOTE_OFF, 36, 0))

    def test_channel_any_matches_all(self):
        for ch in range(16):
            with self.subTest(channel=ch):
                self.assertTrue(eng.matches(mapping(), NOTE_ON | ch, 36, 100))

    def test_specific_channel_is_exclusive(self):
        m = mapping(channel=9)          # ch10, where the pads live
        self.assertTrue(eng.matches(m, NOTE_ON | 9, 36, 100))
        self.assertFalse(eng.matches(m, NOTE_ON | 0, 36, 100))

    def test_cc_value_filter(self):
        m = mapping(type="cc", number=24, value=127)
        self.assertTrue(eng.matches(m, CC, 24, 127))
        self.assertFalse(eng.matches(m, CC, 24, 64))

    def test_cc_without_value_filter_takes_any(self):
        m = mapping(type="cc", number=24)
        for v in (0, 64, 127):
            with self.subTest(value=v):
                self.assertTrue(eng.matches(m, CC, 24, v))

    def test_wildcard_number(self):
        self.assertTrue(eng.matches(mapping(number=-1), NOTE_ON, 99, 100))

    def test_disabled_never_matches(self):
        m = mapping()
        m["enabled"] = False
        self.assertFalse(eng.matches(m, NOTE_ON, 36, 100))

    def test_pitchbend_ignores_number(self):
        m = mapping(type="pitchbend", number=-1)
        self.assertTrue(eng.matches(m, 0xE0, 0, 64))


class TestKnobScaling(unittest.TestCase):
    def test_full_range_passes_through(self):
        for v in (0, 64, 127):
            with self.subTest(value=v):
                self.assertEqual(
                    eng.Engine._scale(v, {"min": 0, "max": 127}), v)

    def test_limited_range(self):
        self.assertEqual(eng.Engine._scale(127, {"min": 0, "max": 80}), 80)
        self.assertEqual(eng.Engine._scale(0, {"min": 0, "max": 80}), 0)

    def test_offset_range(self):
        self.assertEqual(eng.Engine._scale(0, {"min": 20, "max": 100}), 20)
        self.assertEqual(eng.Engine._scale(127, {"min": 20, "max": 100}), 100)

    def test_invert(self):
        opts = {"min": 0, "max": 127, "invert": True}
        self.assertEqual(eng.Engine._scale(0, opts), 127)
        self.assertEqual(eng.Engine._scale(127, opts), 0)

    def test_always_within_midi_range(self):
        for v in range(0, 128, 7):
            out = eng.Engine._scale(v, {"min": 0, "max": 127})
            self.assertGreaterEqual(out, 0)
            self.assertLessEqual(out, 127)


class TestFeedbackLoopGuard(unittest.TestCase):
    """Routing a keyboard's MIDI back to itself floods the port. See README."""

    def test_plain_names_match(self):
        self.assertTrue(winmidi.same_device("MPK mini IV", "MPK mini IV"))

    def test_windows_port_wrappers_are_stripped(self):
        self.assertTrue(
            winmidi.same_device("MIDIOUT2 (MPK mini IV)", "MPK mini IV"))
        self.assertTrue(
            winmidi.same_device("MIDIIN3 (MPK mini IV)", "MPK mini IV"))

    def test_two_wrapped_ports_of_one_device_match(self):
        self.assertTrue(winmidi.same_device("MIDIOUT5 (MPK mini IV)",
                                            "MIDIIN2 (MPK mini IV)"))

    def test_different_devices_do_not_match(self):
        self.assertFalse(winmidi.same_device("loopMIDI Port", "MPK mini IV"))
        self.assertFalse(
            winmidi.same_device("Microsoft GS Wavetable Synth", "MPK mini IV"))

    def test_empty_never_matches(self):
        self.assertFalse(winmidi.same_device("", ""))
        self.assertFalse(winmidi.same_device("", "MPK mini IV"))

    def test_case_insensitive(self):
        self.assertTrue(winmidi.same_device("mpk MINI iv", "MPK mini IV"))


class TestDescriptions(unittest.TestCase):
    def test_trigger_description_names_the_note(self):
        text = eng.describe_trigger(
            {"type": "note_on", "channel": -1, "number": 36})
        self.assertIn("36", text)

    def test_action_description(self):
        self.assertIn(
            "ctrl+z", eng.describe_actions([{"do": "keys", "keys": "ctrl+z"}]))

    def test_chord_description_uses_note_names(self):
        text = eng.describe_actions([{"do": "chord", "notes": [60, 64, 67]}])
        self.assertIn("C4", text)

    def test_passthru_cc_is_labelled_as_knob(self):
        text = eng.describe_actions(
            [{"do": "cc", "cc": 74, "value": "passthru"}])
        self.assertIn("knob", text)


class TestProfiles(unittest.TestCase):
    def test_blank_match_app_never_matches(self):
        p = eng.Profile({"name": "x", "match_app": "", "mappings": []})
        self.assertFalse(p.matches_app("Ableton Live 12 Lite.exe"))

    def test_matches_any_in_comma_list(self):
        p = eng.Profile({"name": "x", "mappings": [],
                         "match_app": "Ableton Live 12 Lite.exe, FL64.exe"})
        self.assertTrue(p.matches_app("FL64.exe"))
        self.assertTrue(p.matches_app("ableton live 12 lite.exe"))
        self.assertFalse(p.matches_app("notepad.exe"))

    def test_default_mapping_is_valid(self):
        m = eng.default_mapping()
        self.assertTrue(eng.matches(m, NOTE_ON, m["trigger"]["number"], 100))

    def test_new_ids_are_unique(self):
        self.assertEqual(len({eng.new_id() for _ in range(500)}), 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
