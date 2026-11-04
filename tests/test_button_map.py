"""Tests for the guided mapper's burst summary. No keyboard needed."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform != "win32":
    raise unittest.SkipTest("button_map imports winmm")

import button_map                       # noqa: E402

PORT = "MPK mini IV"


def short(status, d1, d2):
    return (PORT, "short", (status, d1, d2))


def bend(value):
    raw = value + 8192
    return short(0xE0, raw & 0x7F, raw >> 7)


class TestSummarise(unittest.TestCase):
    def test_a_wheel_sweep_is_one_line(self):
        """Pitchbend lines have no 'value' word; they used to stay unmerged
        (457 lines for a single wheel move in the old button_map.json)."""
        lines = button_map.summarise([bend(v) for v in range(21, 1115, 3)])
        self.assertEqual(len(lines), 1)
        self.assertIn("x365", lines[0])
        self.assertIn("range 21..1113", lines[0])

    def test_knob_turn_is_one_line_per_cc(self):
        events = [short(0xB0, 24, v) for v in range(0, 128, 8)]
        events += [short(0xB0, 25, 64)]
        lines = button_map.summarise(events)
        self.assertEqual(len(lines), 2)
        self.assertIn("range 0..120", lines[0])
        self.assertNotIn("x", lines[1].split("value")[1])   # single message

    def test_note_on_and_off_are_separate(self):
        lines = button_map.summarise([short(0x99, 36, 100), short(0x99, 36, 0),
                                      short(0x89, 36, 0)])
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith(f"[{PORT}] Note On"))
        self.assertIn("x2", lines[1])        # vel-0 note on counts as off

    def test_ports_are_kept_apart(self):
        a = short(0xB0, 24, 1)
        b = ("MIDIIN2 (MPK mini IV)", "short", (0xB0, 24, 1))
        self.assertEqual(len(button_map.summarise([a, b])), 2)

    def test_sysex_kept_verbatim(self):
        msg = (0xF0, 0x47, 0x00, 0x5D, 0x2A, 0x00, 0x01, 0x02, 0xF7)
        lines = button_map.summarise([(PORT, "sysex", msg)] * 2)
        self.assertEqual(len(lines), 1)
        self.assertIn("2A 00 01 02", lines[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
