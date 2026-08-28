"""Print the MPK mini IV's identity: firmware version and serial number.

Decoded from the MIDI universal identity reply, which for this unit looks like

    F0 7E 7F 06 02 47 5D 00 19 00 <v1 v2 v3 v4> 00 00 00 <serial ASCII> 00 F7

Read-only.

    py -3 device_info.py
"""
from __future__ import annotations

import sys
import time

from mpkmacro import mpk_preset, winmidi


def decode_identity(msg):
    m = list(msg)
    if len(m) < 12 or m[0] != 0xF0 or m[1] != 0x7E or m[3:5] != [0x06, 0x02]:
        raise ValueError("not a universal identity reply")
    manufacturer = m[5]
    family = m[6] | (m[7] << 7)
    model = m[8] | (m[9] << 7)
    version = m[10:14]
    tail = bytes(m[14:-1])
    serial = "".join(chr(b) for b in tail if 32 <= b < 127)
    return {
        "manufacturer": manufacturer,
        "family": family,
        "model": model,
        "version_bytes": version,
        "serial": serial,
    }


def main():
    ins, outs = winmidi.input_devices(), winmidi.output_devices()
    ii = winmidi.find_device(ins, "MPK mini")
    oi = winmidi.find_device(outs, "MPK mini")
    if ii is None or oi is None:
        print("MPK mini IV not found. Is it plugged in?")
        return 1

    midi_in, midi_out = winmidi.MidiIn(), winmidi.MidiOut()
    midi_in.open(ii)
    midi_out.open(oi)
    try:
        midi_out.send_sysex(mpk_preset.identity_request())
        time.sleep(0.4)
        reply = None
        while True:
            try:
                kind, payload = midi_in.queue.get_nowait()
            except Exception:
                break
            if kind == "sysex":
                reply = payload
    finally:
        midi_in.close()
        midi_out.close()

    if reply is None:
        print("No identity reply.")
        return 1

    print("raw:", winmidi.hexdump(reply), "\n")
    info = decode_identity(reply)
    v = info["version_bytes"]
    print(f"  manufacturer   0x{info['manufacturer']:02X} "
          f"({'Akai' if info['manufacturer'] == 0x47 else 'unknown'})")
    print(f"  family         {info['family']} (0x{info['family']:02X})")
    print(f"  model          {info['model']}  <- key count")
    print(f"  version bytes  {' '.join(f'{b:02X}' for b in v)}")
    print(f"  reads as       {v[0]}.{v[1]}{v[2]}  or  {v[0]}.{v[1]}.{v[2]}")
    print(f"  serial         {info['serial']}")
    print("\nCheck this against the number the keyboard itself shows under its")
    print("global/settings menu -- that display is the authority.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
