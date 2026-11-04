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

    # Locally, profiles/ holds the user's own macros, which they are free to
    # enable. Only a clean checkout (CI) shows what actually ships.
    @unittest.skipUnless(os.environ.get("CI"), "checks a clean checkout only")
    def test_shipped_profiles_fire_nothing(self):
        """A fresh install must not press keys until the user opts in."""
        shipped = sorted(eng.PROFILE_DIR.glob("*.json"))
        self.assertTrue(shipped)
        for path in shipped:
            for m in eng.Profile.load(path).mappings:
                with self.subTest(profile=path.name, macro=m.get("name")):
                    self.assertFalse(m.get("enabled", True))


class TestTriggerFields(unittest.TestCase):
    """What the macro editor accepts in its Note/CC # and value boxes."""

    def parse(self, number, value="", kind="note_on"):
        return eng.parse_trigger_fields(kind, number, value)

    def test_plain_numbers(self):
        self.assertEqual(self.parse("36", "127"), (36, 127))

    def test_blank_is_the_wildcard(self):
        self.assertEqual(self.parse("", ""), (-1, None))
        self.assertEqual(self.parse("any", " "), (-1, None))
        self.assertEqual(self.parse("-1", "-1"), (-1, None))

    def test_typo_is_refused_not_widened(self):
        """'3a' used to save as "any note" and fire on every key."""
        for bad in ("3a", "C3", "36.0", "x"):
            with self.subTest(text=bad):
                with self.assertRaises(ValueError):
                    self.parse(bad)
        with self.assertRaises(ValueError):
            self.parse("36", "loud")

    def test_out_of_midi_range_is_refused(self):
        for bad in ("128", "200", "-5"):
            with self.subTest(text=bad):
                with self.assertRaises(ValueError):
                    self.parse(bad)

    def test_pitchbend_has_no_number(self):
        self.assertEqual(self.parse("64", kind="pitchbend"), (-1, None))

    def test_result_matches_like_the_editor_meant(self):
        number, value = self.parse("37")
        m = {"enabled": True, "trigger": {"type": "note_on", "channel": -1,
                                          "number": number, "value": value}}
        self.assertTrue(eng.matches(m, NOTE_ON, 37, 90))
        self.assertFalse(eng.matches(m, NOTE_ON, 38, 90))


class TestProfileNames(unittest.TestCase):
    """A profile name becomes a filename, so it has to be a safe one."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def error(self, name, existing=("My Macros",)):
        return eng.profile_name_error(name, list(existing), self.dir)

    def test_ordinary_names_are_fine(self):
        for ok in ("Ableton", "FL Studio 21", "Photoshop (brushes)", "v1.2"):
            with self.subTest(name=ok):
                self.assertIsNone(self.error(ok))

    def test_duplicate_is_refused_case_insensitively(self):
        """Used to overwrite the existing profile's file with an empty one."""
        self.assertIsNotNone(self.error("My Macros"))
        self.assertIsNotNone(self.error("my macros"))

    def test_existing_file_is_refused(self):
        """A file that failed to load is still somebody's macros."""
        with open(os.path.join(self.dir, "Broken.json"), "w") as fh:
            fh.write("{not json")
        self.assertIsNotNone(self.error("Broken"))

    def test_path_characters_are_refused(self):
        for bad in ("a/b", "a\\b", "..\\..\\x", "x:y", "what?", "a*", 'q"'):
            with self.subTest(name=bad):
                self.assertIsNotNone(self.error(bad))

    def test_reserved_and_blank_are_refused(self):
        for bad in ("", "   ", "CON", "nul", "com1", "LPT9.txt", "trailing.",
                    " padded"):
            with self.subTest(name=bad):
                self.assertIsNotNone(self.error(bad))


class TestProfileLoading(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self._real_dir = eng.PROFILE_DIR
        eng.PROFILE_DIR = eng.Path(self.tmp.name)
        profile("Good").save(eng.PROFILE_DIR / "Good.json")
        (eng.PROFILE_DIR / "Broken.json").write_text('{"name": "x",,}')

    def tearDown(self):
        eng.PROFILE_DIR = self._real_dir
        self.tmp.cleanup()

    def test_a_broken_file_is_reported_not_swallowed(self):
        errors = []
        with self.assertLogs("mpkmacro.engine", "ERROR"):
            profiles = eng.load_profiles(errors)
        self.assertEqual([p.name for p in profiles], ["Good"])
        self.assertEqual([name for name, _ in errors], ["Broken.json"])

    def test_the_broken_file_is_left_alone(self):
        with self.assertLogs("mpkmacro.engine", "ERROR"):
            eng.load_profiles()
        self.assertEqual((eng.PROFILE_DIR / "Broken.json").read_text(),
                         '{"name": "x",,}')


def profile(name, match_app=""):
    return eng.Profile({"name": name, "match_app": match_app, "mappings": []})


class TestProfileSwitching(unittest.TestCase):
    """App-bound profiles are live only while their app has focus."""

    LIVE = "Ableton Live 12 Lite.exe"

    def setUp(self):
        # "Ableton" sorts first on disk -- it must still not start live.
        self.daw = profile("Ableton Looper", self.LIVE)
        self.mine = profile("My Macros")
        self.other = profile("Other global")
        self.engine = eng.Engine()
        self.engine.set_profiles([self.daw, self.mine, self.other])
        self._real = eng.winput.foreground_process
        self.focus = (1234, "chrome.exe")
        eng.winput.foreground_process = lambda: self.focus

    def tearDown(self):
        eng.winput.foreground_process = self._real

    def focus_on(self, exe, pid=1234):
        self.focus = (pid, exe)
        self.engine.update_active()
        return self.engine.active_profile

    def test_starts_on_a_global_profile_not_the_first_file(self):
        self.assertIs(self.engine.active_profile, self.mine)

    def test_app_profile_goes_live_with_its_app(self):
        self.assertIs(self.focus_on(self.LIVE), self.daw)

    def test_and_stops_when_focus_leaves(self):
        self.focus_on(self.LIVE)
        self.assertIs(self.focus_on("chrome.exe"), self.mine)

    def test_fallback_follows_the_users_pick(self):
        self.engine.set_fallback(self.other)
        self.focus_on(self.LIVE)
        self.assertIs(self.focus_on("notepad.exe"), self.other)

    def test_app_profile_cannot_become_the_fallback(self):
        self.engine.set_fallback(self.daw)
        self.assertIs(self.focus_on("chrome.exe"), self.mine)

    def test_own_window_does_not_switch(self):
        """Clicking into the app to edit must not swap the profile."""
        self.focus_on(self.LIVE)
        self.assertIs(self.focus_on("python.exe", pid=os.getpid()), self.daw)

    def test_no_global_profile_means_nothing_live(self):
        self.engine.set_profiles([self.daw])
        self.assertIsNone(self.focus_on("chrome.exe"))
        self.assertIs(self.focus_on(self.LIVE), self.daw)

    def test_giving_the_fallback_an_app_retires_it(self):
        self.mine.match_app = "notepad.exe"
        self.engine.set_profiles(self.engine.profiles)
        self.assertIs(self.focus_on("chrome.exe"), self.other)

    def test_callback_reports_changes(self):
        seen = []
        self.engine.profile_callback = seen.append
        self.focus_on(self.LIVE)
        self.focus_on(self.LIVE)                    # no change, no call
        self.focus_on("chrome.exe")
        self.assertEqual(seen, [self.daw, self.mine])


if __name__ == "__main__":
    unittest.main(verbosity=2)
