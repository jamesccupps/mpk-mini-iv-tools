"""Read presets out of the MPK mini IV and print them in plain English.

WARNING -- requesting a slot appears to make the keyboard LOAD it. Sweeping
every slot therefore leaves the unit sitting on the last one read (USER11),
with that preset's pad assignments and pad colours. This was observed on real
hardware. So by default this reads only the current preset; pass --all to
sweep every slot, and reload the preset you want afterwards with
SHIFT + PLUGIN/DAW -> USER PRESETS.

It still only ever sends the dump-*request* opcode; it never writes.

    py -3 dump_presets.py            # current preset only
    py -3 dump_presets.py --all      # every slot (changes what is loaded)
    py -3 dump_presets.py --json     # machine readable
    py -3 dump_presets.py --raw      # hex, for protocol work
"""
from __future__ import annotations

import json
import sys
import time

from mpkmacro import mpk_preset, winmidi


def main(argv):
    as_json = "--json" in argv
    as_raw = "--raw" in argv
    slots = range(0, 14) if "--all" in argv else [0]
    if "--all" in argv and not as_json:
        print("NOTE: sweeping all slots leaves the keyboard on the last one.\n"
              "      Reload your preset afterwards: SHIFT + PLUGIN/DAW.\n")

    ins, outs = winmidi.input_devices(), winmidi.output_devices()
    in_i = winmidi.find_device(ins, "MPK mini")
    out_i = winmidi.find_device(outs, "MPK mini")
    if in_i is None or out_i is None:
        print("MPK mini IV not found. Is it plugged in?")
        return 1

    midi_in, midi_out = winmidi.MidiIn(), winmidi.MidiOut()
    midi_in.open(in_i)
    midi_out.open(out_i)
    if not as_json:
        print(f"Talking to {ins[in_i]}\n")

    results = []
    try:
        for slot in slots:
            midi_out.send_sysex(mpk_preset.request(slot))
            time.sleep(0.25)
            reply = None
            while True:
                try:
                    kind, payload = midi_in.queue.get_nowait()
                except Exception:
                    break
                if kind == "sysex":
                    reply = payload
            if reply is None:
                if not as_json:
                    print(f"Preset {slot}: no reply")
                continue
            if as_raw:
                print(f"Preset {slot}: {winmidi.hexdump(reply)}\n")
                continue
            try:
                preset = mpk_preset.parse(reply)
            except ValueError as exc:
                print(f"Preset {slot}: could not parse ({exc})")
                print(f"  {winmidi.hexdump(reply)}")
                continue
            if as_json:
                results.append(preset.to_dict())
            else:
                print(preset.report())
                print()
    finally:
        midi_in.close()
        midi_out.close()

    if as_json:
        print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
