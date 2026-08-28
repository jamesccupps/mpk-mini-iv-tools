"""Mapping model and the runtime that turns MIDI into actions."""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import winmidi, winput

APP_DIR = Path(__file__).resolve().parent.parent
PROFILE_DIR = APP_DIR / "profiles"
SETTINGS_PATH = APP_DIR / "settings.json"

NOTE_ON, NOTE_OFF, CC, PC, PITCH, CHAN_AT = 0x9, 0x8, 0xB, 0xC, 0xE, 0xD

TRIGGER_TYPES = ["note_on", "note_off", "cc", "program", "pitchbend", "aftertouch"]
ACTION_TYPES = ["keys", "text", "run", "wait", "chord", "cc", "note", "program"]

PASSTHRU_OFF, PASSTHRU_UNMAPPED, PASSTHRU_ALL = "off", "unmapped", "all"


def new_id():
    return uuid.uuid4().hex[:8]


def default_mapping():
    return {
        "id": new_id(),
        "name": "New macro",
        "enabled": True,
        "block": True,
        "trigger": {"type": "note_on", "channel": -1, "number": 36, "value": None},
        "actions": [{"do": "keys", "keys": "space"}],
    }


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

class Profile:
    def __init__(self, data=None, path=None):
        data = data or {}
        self.path = path
        self.name = data.get("name", "Untitled")
        self.match_app = data.get("match_app", "")
        self.mappings = data.get("mappings", [])

    def to_dict(self):
        return {
            "name": self.name,
            "match_app": self.match_app,
            "mappings": self.mappings,
        }

    def save(self, path=None):
        self.path = Path(path or self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.to_dict(), indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path):
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data, path)

    def matches_app(self, exe):
        """match_app is a comma separated list of exe names; blank = always."""
        if not self.match_app.strip():
            return False
        wanted = [w.strip().lower() for w in self.match_app.split(",") if w.strip()]
        return exe.lower() in wanted


def load_profiles():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profiles = []
    for path in sorted(PROFILE_DIR.glob("*.json")):
        try:
            profiles.append(Profile.load(path))
        except Exception:
            pass
    return profiles


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _kind_of(status, d2):
    kind = status >> 4
    if kind == NOTE_ON and d2 == 0:
        return "note_off"
    return {
        NOTE_ON: "note_on", NOTE_OFF: "note_off", CC: "cc",
        PC: "program", PITCH: "pitchbend", CHAN_AT: "aftertouch",
    }.get(kind)


def matches(mapping, status, d1, d2):
    if not mapping.get("enabled", True):
        return False
    trig = mapping.get("trigger", {})
    if trig.get("type") != _kind_of(status, d2):
        return False
    channel = trig.get("channel", -1)
    if channel not in (-1, None, status & 0x0F):
        return False
    number = trig.get("number")
    # Pitchbend and aftertouch have no meaningful "number" to match on.
    if trig.get("type") not in ("pitchbend", "aftertouch"):
        if number not in (None, -1, d1):
            return False
    want = trig.get("value")
    if want not in (None, "", -1) and int(want) != d2:
        return False
    return True


def describe_trigger(trig):
    t = trig.get("type", "?")
    ch = trig.get("channel", -1)
    ch_txt = "any ch" if ch in (-1, None) else f"ch{ch + 1}"
    num = trig.get("number")
    if t in ("note_on", "note_off"):
        body = "any note" if num in (None, -1) else f"{winmidi.note_name(num)} ({num})"
    elif t == "cc":
        body = "any CC" if num in (None, -1) else f"CC#{num}"
    elif t == "program":
        body = "any" if num in (None, -1) else f"PC#{num}"
    else:
        body = ""
    val = trig.get("value")
    val_txt = f" = {val}" if val not in (None, "", -1) else ""
    label = {"note_on": "Note", "note_off": "Note off", "cc": "Knob/CC",
             "program": "Program", "pitchbend": "Pitchbend",
             "aftertouch": "Aftertouch"}.get(t, t)
    return f"{label}  {body}{val_txt}  [{ch_txt}]".replace("  ", " ").strip()


def describe_actions(actions):
    out = []
    for a in actions:
        do = a.get("do")
        if do == "keys":
            out.append(a.get("keys", ""))
        elif do == "text":
            txt = a.get("text", "")
            out.append(f'type "{txt[:18]}{"..." if len(txt) > 18 else ""}"')
        elif do == "run":
            out.append(f"run {os.path.basename(a.get('path', ''))}")
        elif do == "wait":
            out.append(f"wait {a.get('ms', 0)}ms")
        elif do == "chord":
            notes = a.get("notes", [])
            out.append("chord " + "-".join(winmidi.note_name(n) for n in notes))
        elif do == "cc":
            v = a.get("value", 0)
            out.append(f"CC#{a.get('cc', 0)}={'knob' if v == 'passthru' else v}")
        elif do == "note":
            out.append(f"note {winmidi.note_name(a.get('note', 60))}")
        elif do == "program":
            out.append(f"PC#{a.get('program', 0)}")
        else:
            out.append(str(do))
    return "  >  ".join(out)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class Engine:
    """Reads MIDI, runs matching macros, optionally forwards to a virtual port."""

    def __init__(self, log=None):
        self.log = log or (lambda msg, kind="info": None)
        self.midi_in = winmidi.MidiIn()
        self.midi_out = winmidi.MidiOut()     # for chord/CC macros -> DAW
        self.thru_out = winmidi.MidiOut()     # for passthrough      -> DAW
        self.device_out = winmidi.MidiOut()   # SysEx -> the keyboard itself
        self.profiles = []
        self.active_profile = None
        self.armed = True
        self.passthrough = PASSTHRU_UNMAPPED
        self.auto_switch = True
        self.learn_callback = None
        self.monitor_callback = None
        self.sysex_callback = None
        self._running = False
        self._threads = []
        self._current_exe = ""
        self._held = {}

    # -- lifecycle ----------------------------------------------------------

    def start(self, in_index, out_index=None, thru_index=None):
        self.stop()
        self.midi_in.open(in_index)

        # Routing MIDI back to the keyboard it came from creates a feedback
        # loop: the device echoes it, we forward it again, and the port floods
        # at tens of thousands of messages a second. Refuse outright.
        if out_index is not None:
            out_names = winmidi.output_devices()
            candidate = out_names[out_index] if out_index < len(out_names) else ""
            if winmidi.same_device(candidate, self.midi_in.device_name):
                self.log(
                    f"'{candidate}' is the keyboard itself - routing MIDI back "
                    "to it would cause a feedback loop, so it has been ignored. "
                    "Use a loopMIDI port for passthrough and chords.",
                    "warn",
                )
                out_index = None
                thru_index = None

        if out_index is not None:
            try:
                self.midi_out.open(out_index)
            except winmidi.MidiError as exc:
                self.log(f"MIDI out unavailable: {exc}", "warn")
        if thru_index is not None:
            if thru_index == out_index and self.midi_out.is_open:
                self.thru_out = self.midi_out
            else:
                try:
                    self.thru_out.open(thru_index)
                except winmidi.MidiError as exc:
                    self.log(f"Passthrough port unavailable: {exc}", "warn")
        # A separate handle on the keyboard's own output, so SysEx still reaches
        # it when the macro/passthrough output is pointed at a virtual port.
        dev_idx = winmidi.find_device(winmidi.output_devices(), "MPK mini")
        if dev_idx is not None:
            if dev_idx == out_index and self.midi_out.is_open:
                self.device_out = self.midi_out
            else:
                try:
                    self.device_out.open(dev_idx)
                except winmidi.MidiError as exc:
                    self.log(f"Cannot talk to the keyboard directly: {exc}", "warn")

        self._running = True
        self._threads = [
            threading.Thread(target=self._pump, daemon=True),
            threading.Thread(target=self._watch_foreground, daemon=True),
        ]
        for t in self._threads:
            t.start()
        self.log(f"Listening on {self.midi_in.device_name}", "good")

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=1.0)
        self._threads = []
        self.midi_in.close()
        if self.thru_out is not self.midi_out:
            self.thru_out.close()
        if self.device_out is not self.midi_out:
            self.device_out.close()
        self.midi_out.close()

    # -- main loop ----------------------------------------------------------

    def _pump(self):
        import queue as _q
        while self._running:
            try:
                kind, payload = self.midi_in.queue.get(timeout=0.2)
            except _q.Empty:
                continue
            try:
                if kind == "sysex":
                    if self.sysex_callback:
                        self.sysex_callback(payload)
                else:
                    self._handle(*payload)
            except Exception:
                self.log(traceback.format_exc(limit=3), "error")

    def _handle(self, status, d1, d2):
        if self.monitor_callback:
            self.monitor_callback(status, d1, d2)

        if self.learn_callback:
            cb, self.learn_callback = self.learn_callback, None
            cb(status, d1, d2)
            return

        fired = False
        if self.armed and self.active_profile:
            for mapping in self.active_profile.mappings:
                if matches(mapping, status, d1, d2):
                    fired = True
                    self.log(f"-> {mapping.get('name', 'macro')}", "fire")
                    threading.Thread(
                        target=self._run_actions,
                        args=(mapping.get("actions", []), d2),
                        daemon=True,
                    ).start()
                    if mapping.get("block", True):
                        break

        if self.passthrough == PASSTHRU_ALL or (
            self.passthrough == PASSTHRU_UNMAPPED and not fired
        ):
            self.thru_out.send(status, d1, d2)

    # -- actions ------------------------------------------------------------

    def _run_actions(self, actions, incoming_value):
        for action in actions:
            try:
                self._run_one(action, incoming_value)
            except Exception as exc:
                self.log(f"action failed ({action.get('do')}): {exc}", "error")

    def _run_one(self, action, incoming_value):
        do = action.get("do")
        if do == "keys":
            winput.send_combo(action.get("keys", ""))
        elif do == "text":
            winput.type_text(action.get("text", ""))
        elif do == "run":
            winput.run_program(action.get("path", ""), action.get("args", ""))
        elif do == "wait":
            time.sleep(max(0, int(action.get("ms", 0))) / 1000.0)
        elif do == "chord":
            self._play_chord(action)
        elif do == "note":
            self._play_chord({
                "notes": [int(action.get("note", 60))],
                "velocity": action.get("velocity", 100),
                "length_ms": action.get("length_ms", 250),
                "channel": action.get("channel", 0),
            })
        elif do == "cc":
            value = action.get("value", 0)
            if value == "passthru":
                value = self._scale(incoming_value, action)
            ch = int(action.get("channel", 0)) & 0x0F
            self.midi_out.send(0xB0 | ch, int(action.get("cc", 1)), int(value) & 0x7F)
        elif do == "program":
            ch = int(action.get("channel", 0)) & 0x0F
            self.midi_out.send(0xC0 | ch, int(action.get("program", 0)))

    @staticmethod
    def _scale(value, action):
        """Map an incoming 0-127 knob value into the action's own range."""
        lo = int(action.get("min", 0))
        hi = int(action.get("max", 127))
        if action.get("invert"):
            value = 127 - value
        return max(0, min(127, lo + (hi - lo) * value // 127))

    def _play_chord(self, action):
        notes = [int(n) for n in action.get("notes", [])]
        if not notes:
            return
        ch = int(action.get("channel", 0)) & 0x0F
        vel = int(action.get("velocity", 100))
        strum = max(0, int(action.get("strum_ms", 0))) / 1000.0
        length = max(1, int(action.get("length_ms", 250))) / 1000.0
        for note in notes:
            self.midi_out.send(0x90 | ch, note, vel)
            if strum:
                time.sleep(strum)
        time.sleep(length)
        for note in notes:
            self.midi_out.send(0x80 | ch, note, 0)

    # -- profile switching --------------------------------------------------

    def set_profiles(self, profiles, active=None):
        self.profiles = profiles
        if active is not None:
            self.active_profile = active
        elif profiles and self.active_profile not in profiles:
            self.active_profile = profiles[0]

    def _watch_foreground(self):
        while self._running:
            if self.auto_switch and self.profiles:
                exe = winput.foreground_exe()
                if exe and exe != self._current_exe:
                    self._current_exe = exe
                    for prof in self.profiles:
                        if prof.matches_app(exe) and prof is not self.active_profile:
                            self.active_profile = prof
                            self.log(f"Profile -> {prof.name} ({exe})", "good")
                            break
            time.sleep(0.4)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def load_settings():
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(data):
    try:
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass
