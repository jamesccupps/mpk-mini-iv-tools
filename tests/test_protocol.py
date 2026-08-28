"""Tests for the MPK mini IV SysEx protocol. No hardware needed."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpkmacro import mpk_preset          # noqa: E402
from tests import fixtures               # noqa: E402


class TestFrame(unittest.TestCase):
    """The F0 47 <dev> 5D <op> <lenMSB> <lenLSB> <payload> F7 envelope."""

    def test_unwraps_preset_dump(self):
        frame = mpk_preset.parse_frame(fixtures.PRESET_DAW)
        self.assertEqual(frame.dev, 0x00)
        self.assertEqual(frame.opcode, mpk_preset.OP_DUMP)
        self.assertEqual(len(frame.payload), mpk_preset.PAYLOAD_LEN)

    def test_length_is_14_bits_over_two_bytes(self):
        # 0x02 0x14 -> (2 << 7) | 0x14 == 276
        self.assertEqual(len(fixtures.PRESET_DAW), 284)
        frame = mpk_preset.parse_frame(fixtures.PRESET_DAW)
        self.assertEqual(len(frame.payload), 276)

    def test_same_envelope_for_short_messages(self):
        for msg, op, size in (
            (fixtures.PAD_MODE_NOTES, mpk_preset.OP_PAD_MODE, 1),
            (fixtures.STATUS_SHORT, mpk_preset.OP_STATUS, 0),
            (fixtures.STATUS_LONG, mpk_preset.OP_STATUS, 17),
        ):
            with self.subTest(opcode=op):
                frame = mpk_preset.parse_frame(msg)
                self.assertEqual(frame.opcode, op)
                self.assertEqual(len(frame.payload), size)

    def test_rejects_truncated(self):
        with self.assertRaises(ValueError):
            mpk_preset.parse_frame([0xF0, 0x47, 0x00])

    def test_rejects_other_manufacturer(self):
        with self.assertRaises(ValueError):
            mpk_preset.parse_frame([0xF0, 0x43, 0x00, 0x5D, 0x67, 0, 0, 0xF7])

    def test_rejects_other_product(self):
        with self.assertRaises(ValueError):
            mpk_preset.parse_frame([0xF0, 0x47, 0x00, 0x49, 0x67, 0, 0, 0xF7])

    def test_rejects_length_mismatch(self):
        bad = [0xF0, 0x47, 0x00, 0x5D, 0x2A, 0x00, 0x09, 0x00, 0xF7]
        with self.assertRaises(ValueError):
            mpk_preset.parse_frame(bad)


class TestPreset(unittest.TestCase):
    def setUp(self):
        self.preset = mpk_preset.parse(fixtures.PRESET_DAW)

    def test_name_and_slot(self):
        self.assertEqual(self.preset.name, "DAW")
        self.assertEqual(self.preset.number, 0)

    def test_sixteen_pads_two_banks(self):
        self.assertEqual(len(self.preset.pads), 16)
        self.assertEqual([p["bank"] for p in self.preset.pads],
                         ["A"] * 8 + ["B"] * 8)

    def test_pad_notes_are_36_to_51(self):
        self.assertEqual([p["note"] for p in self.preset.pads],
                         list(range(36, 52)))

    def test_pad_ccs_are_32_to_47(self):
        self.assertEqual([p["cc"] for p in self.preset.pads],
                         list(range(32, 48)))

    def test_pad_program_changes_are_0_to_15(self):
        self.assertEqual([p["program"] for p in self.preset.pads],
                         list(range(16)))

    def test_eight_knobs_cc_24_to_31(self):
        self.assertEqual(len(self.preset.knobs), 8)
        self.assertEqual([k["cc"] for k in self.preset.knobs],
                         list(range(24, 32)))

    def test_knob_names_and_ranges(self):
        for i, knob in enumerate(self.preset.knobs, start=1):
            with self.subTest(knob=i):
                self.assertEqual(knob["name"], f"KNOB{i}")
                self.assertEqual((knob["min"], knob["max"]), (0, 127))

    def test_tempo_byte(self):
        self.assertEqual(self.preset.tempo, 120)

    def test_pad_channel_byte(self):
        # globals[1] is 9 -> MIDI channel 10, which matched the hardware:
        # pads transmitted on ch10 while keys used ch1.
        self.assertEqual(self.preset.globals_raw[1], 9)

    def test_round_trips_to_dict(self):
        d = self.preset.to_dict()
        self.assertEqual(d["name"], "DAW")
        self.assertEqual(len(d["pads"]), 16)
        self.assertEqual(len(d["knobs"]), 8)

    def test_report_is_readable(self):
        text = self.preset.report()
        self.assertIn("DAW", text)
        self.assertIn("KNOB1", text)

    def test_rejects_wrong_opcode(self):
        with self.assertRaises(ValueError):
            mpk_preset.parse(fixtures.PAD_MODE_NOTES)


class TestRequests(unittest.TestCase):
    def test_request_bytes(self):
        self.assertEqual(mpk_preset.request(3),
                         [0xF0, 0x47, 0x00, 0x5D, 0x66, 0x00, 0x01, 0x03, 0xF7])

    def test_request_honours_device_id(self):
        self.assertEqual(mpk_preset.request(0, dev=0x7F)[2], 0x7F)

    def test_identity_request_is_universal(self):
        self.assertEqual(mpk_preset.identity_request(),
                         [0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])


class TestDecodeMessage(unittest.TestCase):
    def test_decodes_preset_dump(self):
        out = mpk_preset.decode_message(fixtures.PRESET_DAW)
        self.assertIn("Preset dump", out)
        self.assertIn("DAW", out)

    def test_decodes_pad_modes(self):
        self.assertIn("Notes",
                      mpk_preset.decode_message(fixtures.PAD_MODE_NOTES))
        self.assertIn("CC#", mpk_preset.decode_message(fixtures.PAD_MODE_CC))

    def test_decodes_status(self):
        self.assertIn("Status",
                      mpk_preset.decode_message(fixtures.STATUS_SHORT))

    def test_decodes_identity_with_firmware(self):
        out = mpk_preset.decode_message(fixtures.IDENTITY)
        self.assertIn("1.41", out)
        self.assertIn("25 keys", out)

    def test_decodes_a_request(self):
        self.assertIn("request",
                      mpk_preset.decode_message(mpk_preset.request(5)))

    def test_returns_none_for_foreign_sysex(self):
        self.assertIsNone(
            mpk_preset.decode_message([0xF0, 0x43, 0x10, 0x4C, 0xF7]))

    def test_unknown_opcode_is_reported_not_crashed(self):
        msg = [0xF0, 0x47, 0x00, 0x5D, 0x77, 0x00, 0x01, 0x01, 0xF7]
        self.assertIn("Unknown opcode", mpk_preset.decode_message(msg))


if __name__ == "__main__":
    unittest.main(verbosity=2)
