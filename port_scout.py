"""Work out what each of the MPK mini IV's four USB MIDI ports carries.

The keyboard presents four ports over USB-C. Akai's setup guides name them
("DAW Port", etc.) but Windows only shows them as MPK mini IV, MIDIIN2,
MIDIIN3, MIDIIN4 -- so the fastest way to know which is which is to watch all
four at once and play with the controls.

    py -3 port_scout.py

Then, in order: play a key, hit a pad, turn a knob, press PLUGIN/DAW, and
press the transport buttons. Ctrl+C when done for a summary.
"""
from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict

from mpkmacro import winmidi

KINDS = {0x8: "note off", 0x9: "note on", 0xA: "poly AT", 0xB: "CC",
         0xC: "program", 0xD: "aftertouch", 0xE: "pitchbend"}


def main():
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

    print(f"Watching {len(listeners)} ports. Now try, one at a time:")
    print("  1. play a key      2. hit a pad       3. turn a knob")
    print("  4. press PLUGIN/DAW    5. press the transport buttons")
    print("  6. move pitch / mod wheels")
    print("\nCtrl+C to stop and see the summary.\n")

    seen = defaultdict(Counter)
    try:
        while True:
            quiet = True
            for name, mi in listeners:
                while True:
                    try:
                        kind, payload = mi.queue.get_nowait()
                    except Exception:
                        break
                    quiet = False
                    if kind == "sysex":
                        print(f"[{name}]  SysEx, {len(payload)} bytes")
                        seen[name]["sysex"] += 1
                        continue
                    status, d1, d2 = payload
                    label = KINDS.get(status >> 4, f"0x{status:02X}")
                    ch = (status & 0x0F) + 1
                    print(f"[{name}]  {label:<10} ch{ch:<3} "
                          f"{winmidi.describe(status, d1, d2)}")
                    seen[name][f"{label} ch{ch}"] += 1
            if quiet:
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        for _, mi in listeners:
            mi.close()

    print("\n" + "=" * 60)
    print("SUMMARY -- what each port carried")
    print("=" * 60)
    for name, _ in listeners:
        counts = seen.get(name)
        if not counts:
            print(f"\n{name}\n  (nothing)")
            continue
        print(f"\n{name}")
        for what, n in counts.most_common():
            print(f"  {what:<24} x{n}")
    print("\nThe port carrying your keys/pads is the one to use for playing.")
    print("A port that only wakes up for transport buttons is the DAW port.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
