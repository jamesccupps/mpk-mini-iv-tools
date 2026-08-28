"""Guided mapper: find out what every button and the encoder actually send.

The preset dump tells us what the pads and knobs are set to, but it says
nothing about the buttons. This walks you through them one at a time and
records what each one transmits, so the result is labelled rather than a wall
of undifferentiated MIDI.

    py -3 button_map.py                    # walk every control
    py -3 button_map.py --only ARP LATCH   # redo just these, keep the rest

Press the control it names, or press Enter to skip it. Ctrl+C to stop early.
Results print as a table and are written to button_map.json.

--only matches on any part of the label, case-insensitively, and merges into
an existing button_map.json rather than replacing it -- so a control you
fumbled can be redone on its own without repeating the whole run.

Read-only: it never transmits to the keyboard.
"""
from __future__ import annotations

import json
import sys
import time

from mpkmacro import winmidi

WAIT = 6.0          # seconds to wait for each control
SETTLE = 0.35       # keep collecting this long after the first message

# Panel order, left to right. Anything the DAW script swallows shows nothing --
# that is itself a useful result, so it gets recorded rather than skipped.
#
# The knobs and pads ARE included even though the preset dump already gives
# their assignments: the dump describes MIDI mode, and in DAW mode the control
# script can remap them or move them to another port. Comparing a DAW-mode run
# against a MIDI-mode run is the whole point.
CONTROLS = [
    # far left
    ("PITCH wheel", "move the pitch wheel"),
    ("MOD wheel", "move the mod wheel"),

    # pads -- spot checks, one per row per bank
    ("PAD 1 (bank A)", "pad 1, bottom-left"),
    ("PAD 5 (bank A)", "pad 5, top-left"),
    ("PAD 1 (bank B)", "BANK A/B, then pad 1 again"),

    # centre: display, encoder, bank, shift
    ("ENCODER turn right", "turn the encoder one click clockwise"),
    ("ENCODER turn left", "turn the encoder one click anticlockwise"),
    ("ENCODER press", "press the encoder in"),
    ("BANK -", "the BANK - button"),
    ("BANK +", "the BANK + button"),
    ("SHIFT", "SHIFT on its own"),
    ("PLUGIN/DAW", "the PLUGIN/DAW button"),

    # the eight knobs, top row then bottom row
    ("KNOB 1", "turn knob 1"),
    ("KNOB 2", "turn knob 2"),
    ("KNOB 3", "turn knob 3"),
    ("KNOB 4", "turn knob 4"),
    ("KNOB 5", "turn knob 5"),
    ("KNOB 6", "turn knob 6"),
    ("KNOB 7", "turn knob 7"),
    ("KNOB 8", "turn knob 8"),

    # button strip
    ("OCT -", "the OCT - button"),
    ("OCT +", "the OCT + button"),
    ("ARP", "the ARP button"),
    ("LATCH", "the LATCH button"),
    ("NOTE REPEAT", "the NOTE REPEAT button"),
    ("TAP TEMPO", "TAP TEMPO once"),
    ("BANK A/B", "the BANK A/B button"),
    ("UNDO", "the UNDO button"),
    ("LOOP", "the loop button"),
    ("STOP/PLAY", "the stop/play button"),
    ("REC", "the record button"),
    ("AUTOMATION", "the automation button"),

    # keybed
    ("KEY lowest", "the lowest white key"),
    ("KEY highest", "the highest white key"),
]


def describe(kind, payload):
    if kind == "sysex":
        return f"SysEx {len(payload)}B: {winmidi.hexdump(payload)}"
    return winmidi.describe(*payload)


def summarise(events):
    """Collapse a burst into something readable, keeping order."""
    seen, out = set(), []
    for port, text in events:
        key = (port, text.split("value")[0])
        if key not in seen:
            seen.add(key)
            out.append(f"[{port}] {text}")
    return out


def select_controls(argv):
    """Honour --only, matching loosely so exact punctuation is not needed."""
    if "--only" not in argv:
        return CONTROLS, False
    wanted = [a.lower() for a in argv[argv.index("--only") + 1:]
              if not a.startswith("--")]
    if not wanted:
        return CONTROLS, False
    chosen = [(label, prompt) for label, prompt in CONTROLS
              if any(w in label.lower() for w in wanted)]
    if not chosen:
        print(f"Nothing matched {wanted}. Known labels:")
        for label, _ in CONTROLS:
            print(f"  {label}")
        sys.exit(1)
    return chosen, True


def load_existing():
    try:
        with open("button_map.json", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def main(argv):
    controls, merging = select_controls(argv)
    results = load_existing() if merging else {}
    if merging:
        print(f"Redoing {len(controls)} control(s), keeping the other "
              f"{len(results)} already mapped.\n")

    names = winmidi.input_devices()
    idx = [i for i, n in enumerate(names) if "mpk mini" in n.lower()]
    if not idx:
        print("MPK mini IV not found. Is it plugged in?")
        return 1

    listeners = []
    for i in idx:
        mi = winmidi.MidiIn()
        try:
            mi.open(i)
            listeners.append((names[i], mi))
        except winmidi.MidiError as exc:
            print(f"  ! cannot open {names[i]}: {exc}")

    print(f"Listening on {len(listeners)} ports.\n")
    print("For each control: press it, or hit Enter to skip.")
    print("Tip: run this in DAW mode AND again in MIDI mode -- some buttons")
    print("are swallowed by the DAW script and only transmit in MIDI mode.\n")

    def drain():
        got = []
        for port, mi in listeners:
            while True:
                try:
                    kind, payload = mi.queue.get_nowait()
                except Exception:
                    break
                got.append((port, describe(kind, payload)))
        return got

    try:
        for label, prompt in controls:
            drain()                                    # clear anything stale
            try:
                input(f"  {label:<20} -> {prompt}, then Enter: ")
            except EOFError:
                print("\n(no console input available -- run this from a terminal)")
                break

            events = drain()
            deadline = time.time() + WAIT
            while not events and time.time() < deadline:
                time.sleep(0.01)
                events = drain()
            if events:
                stop = time.time() + SETTLE
                while time.time() < stop:
                    time.sleep(0.01)
                    events += drain()

            lines = summarise(events)
            results[label] = lines
            if lines:
                for line in lines[:4]:
                    print(f"      {line}")
                if len(lines) > 4:
                    print(f"      ... and {len(lines) - 4} more")
            else:
                print("      nothing (skipped, or the DAW script consumed it)")
            print()
    except KeyboardInterrupt:
        print("\nstopped early")
    finally:
        for _, mi in listeners:
            mi.close()

    print("=" * 62)
    print("BUTTON MAP")
    print("=" * 62)
    for label, lines in results.items():
        print(f"\n{label}")
        for line in lines or ["  (nothing)"]:
            print(f"  {line}")

    with open("button_map.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print("\nWritten to button_map.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
