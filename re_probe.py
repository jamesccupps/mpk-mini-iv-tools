"""Probe an MPK mini IV for SysEx responses.

Read-only reconnaissance: it sends standard *query* messages and prints
whatever the device answers, so we can work out the protocol a PC editor
would need to speak. It never sends a write/store command.

Usage:  py -3 re_probe.py
"""
from __future__ import annotations

import sys
import time

from mpkmacro import winmidi

DEVICE_HINT = "MPK mini"


def hexs(data):
    return " ".join(f"{b:02X}" for b in data)


def ascii_of(data):
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def build_probes():
    """(label, bytes) pairs -- all of them are queries, none store anything."""
    probes = [
        ("Universal Identity Request", [0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]),
    ]
    # Akai's MPK mini family uses F0 47 <devID> <productID> 66 00 01 <preset> F7
    # to request a preset dump. 0x26=mk2, 0x49=mk3. The identity reply told us
    # the mini IV's product ID is 0x5D, so try that shape in its known variants.
    pid = 0x5D
    for dev in (0x00, 0x7F):
        probes.append(
            (f"Akai dump request dev=0x{dev:02X} pid=0x{pid:02X} preset 0 (RAM)",
             [0xF0, 0x47, dev, pid, 0x66, 0x00, 0x01, 0x00, 0xF7])
        )
        probes.append(
            (f"Akai dump request dev=0x{dev:02X} pid=0x{pid:02X} preset 1",
             [0xF0, 0x47, dev, pid, 0x66, 0x00, 0x01, 0x01, 0xF7])
        )
    # NOTE: this script deliberately sends ONLY the dump-request opcode (0x66),
    # which is the documented read used by every MPK mini editor. An earlier
    # version also swept a guessed opcode (0x60); guessing opcodes at hardware
    # can change device state, so don't add speculative ones here. Test unknown
    # opcodes only when you are prepared to reset the device.
    return probes


def main():
    ins = winmidi.input_devices()
    outs = winmidi.output_devices()
    print("MIDI inputs :", ins)
    print("MIDI outputs:", outs)
    print()

    in_idx = [i for i, n in enumerate(ins) if DEVICE_HINT.lower() in n.lower()]
    out_idx = [i for i, n in enumerate(outs) if DEVICE_HINT.lower() in n.lower()]
    if not in_idx or not out_idx:
        print(f"No device matching {DEVICE_HINT!r}. Is it plugged in?")
        return 1

    # Listen on every one of the device's input ports at once.
    listeners = []
    for i in in_idx:
        mi = winmidi.MidiIn()
        try:
            mi.open(i)
            listeners.append((ins[i], mi))
        except winmidi.MidiError as exc:
            print(f"  ! could not open input {ins[i]}: {exc}")
    print(f"Listening on {len(listeners)} input port(s)\n")

    def drain(tag):
        got = False
        for name, mi in listeners:
            while True:
                try:
                    kind, payload = mi.queue.get_nowait()
                except Exception:
                    break
                got = True
                if kind == "sysex":
                    print(f"  <== [{name}] SYSEX ({len(payload)} bytes)")
                    print(f"      {hexs(payload)}")
                    print(f"      ascii: {ascii_of(payload)}")
                else:
                    print(f"  <== [{name}] {winmidi.describe(*payload)}")
        if not got:
            print(f"  (no reply to {tag})")

    for oi in out_idx:
        mo = winmidi.MidiOut()
        try:
            mo.open(oi)
        except winmidi.MidiError as exc:
            print(f"! could not open output {outs[oi]}: {exc}")
            continue
        print(f"=== sending on output: {outs[oi]} ===")
        for label, msg in build_probes():
            print(f"  ==> {label}: {hexs(msg)}")
            mo.send_sysex(msg)
            time.sleep(0.35)
            drain(label)
        mo.close()
        print()

    for _, mi in listeners:
        mi.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
