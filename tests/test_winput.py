"""Tests for keystroke parsing. Windows only; no keys are actually sent."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform != "win32":
    raise unittest.SkipTest("winput is Windows only")

from mpkmacro import winput             # noqa: E402

VK_SHIFT, VK_CTRL, VK_ALT, VK_WIN = 0x10, 0x11, 0x12, 0x5B


class TestComboParsing(unittest.TestCase):
    def test_bare_named_key(self):
        mods, vk, literal = winput.parse_combo("space")
        self.assertEqual((mods, vk, literal), ([], 0x20, None))

    def test_single_modifier(self):
        mods, vk, _ = winput.parse_combo("ctrl+z")
        self.assertEqual(mods, [VK_CTRL])
        self.assertEqual(vk, ord("Z"))

    def test_two_modifiers_keep_order(self):
        mods, vk, _ = winput.parse_combo("ctrl+shift+s")
        self.assertEqual(mods, [VK_CTRL, VK_SHIFT])
        self.assertEqual(vk, ord("S"))

    def test_function_keys(self):
        self.assertEqual(winput.parse_combo("f1")[1], 0x70)
        self.assertEqual(winput.parse_combo("f5")[1], 0x74)
        self.assertEqual(winput.parse_combo("f12")[1], 0x7B)

    def test_alias_spellings(self):
        self.assertEqual(winput.parse_combo("enter")[1],
                         winput.parse_combo("return")[1])
        self.assertEqual(winput.parse_combo("esc")[1],
                         winput.parse_combo("escape")[1])
        self.assertEqual(winput.parse_combo("del")[1],
                         winput.parse_combo("delete")[1])

    def test_media_keys(self):
        self.assertEqual(winput.parse_combo("mediaplay")[1], 0xB3)
        self.assertEqual(winput.parse_combo("volumeup")[1], 0xAF)

    def test_win_modifier(self):
        mods, vk, _ = winput.parse_combo("win+d")
        self.assertEqual(mods, [VK_WIN])
        self.assertEqual(vk, ord("D"))

    def test_shifted_character_adds_shift_implicitly(self):
        """'?' needs shift on a US layout; the parser must supply it."""
        mods, _, _ = winput.parse_combo("?")
        self.assertIn(VK_SHIFT, mods)

    def test_shift_not_duplicated_when_given(self):
        mods, _, _ = winput.parse_combo("shift+a")
        self.assertEqual(mods.count(VK_SHIFT), 1)

    def test_whitespace_tolerated(self):
        mods, vk, _ = winput.parse_combo("  ctrl +  s  ")
        self.assertEqual(mods, [VK_CTRL])
        self.assertEqual(vk, ord("S"))

    def test_case_insensitive(self):
        self.assertEqual(winput.parse_combo("CTRL+Z")[1],
                         winput.parse_combo("ctrl+z")[1])

    def test_empty_is_harmless(self):
        self.assertEqual(winput.parse_combo(""), ([], None, None))

    def test_unknown_modifier_raises(self):
        with self.assertRaises(ValueError):
            winput.parse_combo("hyper+a")

    def test_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            winput.parse_combo("ctrl+nonsensekey")


class TestExtendedKeys(unittest.TestCase):
    """Extended keys need a flag or apps read them as their numpad twins."""

    def test_navigation_keys_are_extended(self):
        for name in ("left", "right", "up", "down", "home", "end",
                     "pageup", "pagedown", "insert", "delete"):
            with self.subTest(key=name):
                self.assertIn(winput.VK[name], winput.EXTENDED)

    def test_ordinary_letters_are_not_extended(self):
        self.assertNotIn(ord("A"), winput.EXTENDED)

    def test_numpad_digits_are_not_extended(self):
        for i in range(10):
            self.assertNotIn(winput.VK[f"num{i}"], winput.EXTENDED)


class TestUnicodeUnits(unittest.TestCase):
    """SendInput takes UTF-16 code units, so astral chars need surrogates."""

    def test_bmp_character_is_one_unit(self):
        self.assertEqual(winput._utf16_units("a"), (0x61,))

    def test_accented_character_is_one_unit(self):
        self.assertEqual(winput._utf16_units("é"), (0xE9,))

    def test_emoji_becomes_a_surrogate_pair(self):
        units = winput._utf16_units("🎹")
        self.assertEqual(len(units), 2)
        self.assertTrue(0xD800 <= units[0] <= 0xDBFF)
        self.assertTrue(0xDC00 <= units[1] <= 0xDFFF)


if __name__ == "__main__":
    unittest.main(verbosity=2)
