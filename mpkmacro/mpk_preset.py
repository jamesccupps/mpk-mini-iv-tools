"""MPK mini IV preset SysEx format.

Worked out by probing a real MPK mini IV. Confirmed so far:

    request  F0 47 <dev> 5D 66 00 01 <preset> F7
    reply    F0 47 <dev> 5D 67 <lenMSB> <lenLSB> <payload> F7

<dev> is 0x00 or 0x7F (both answer). 0x5D is the MPK mini IV product ID -- it
comes straight out of the universal identity reply (F0 7E 7F 06 02 47 5D 00 ...).
Length is 14 bits split over two 7-bit bytes: (MSB << 7) | LSB, and for this
model it is 276, giving a 284-byte message.

Payload layout (offsets are relative to the start of the payload):

    0        preset number
    1..16    name, 16 bytes ASCII, NUL padded
    17..29   13 bytes of global settings (partially identified)
    30..109  16 pad records, 5 bytes each
    110..269 8 knob records, 20 bytes each
    270..275 6 byte tail

Fields still marked unknown are left as raw numbers rather than guessed at.
"""
from __future__ import annotations

import json

PRODUCT_ID = 0x5D
OP_REQUEST = 0x66
OP_DUMP = 0x67

NAME_LEN = 16
GLOBAL_LEN = 13
PAD_COUNT = 16
PAD_REC = 5
KNOB_COUNT = 8
KNOB_REC = 20
TAIL_LEN = 6
PAYLOAD_LEN = 1 + NAME_LEN + GLOBAL_LEN + PAD_COUNT * PAD_REC + KNOB_COUNT * KNOB_REC + TAIL_LEN


def request(preset=0, dev=0x00):
    """Bytes that ask the keyboard for a preset. 0 = current, 1..13 = slots."""
    return [0xF0, 0x47, dev, PRODUCT_ID, OP_REQUEST, 0x00, 0x01, preset, 0xF7]


def identity_request():
    return [0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]


def _text(data):
    return bytes(data).split(b"\x00")[0].decode("ascii", "replace")


class Preset:
    def __init__(self, payload):
        self.raw = list(payload)
        p = self.raw
        self.number = p[0]
        self.name = _text(p[1:1 + NAME_LEN])

        g = p[1 + NAME_LEN:1 + NAME_LEN + GLOBAL_LEN]
        self.globals_raw = list(g)
        # Byte 3 of this block reads 0x78 (120) on a factory preset, which is
        # almost certainly the arpeggiator/sequencer tempo. The rest are not
        # identified yet, so they are kept verbatim and written back unchanged.
        self.tempo = g[3] if len(g) > 3 else None

        off = 1 + NAME_LEN + GLOBAL_LEN
        self.pads = []
        for i in range(PAD_COUNT):
            rec = p[off + i * PAD_REC: off + (i + 1) * PAD_REC]
            self.pads.append({
                "pad": i + 1,
                "bank": "A" if i < 8 else "B",
                "note": rec[0],
                "cc": rec[1],
                "program": rec[2],
                "unknown": rec[3:],
            })

        off += PAD_COUNT * PAD_REC
        self.knobs = []
        for i in range(KNOB_COUNT):
            rec = p[off + i * KNOB_REC: off + (i + 1) * KNOB_REC]
            self.knobs.append({
                "knob": i + 1,
                "cc": rec[0],
                "min": rec[1],
                "max": rec[2],
                "mode": rec[3],          # 0/1 seen; absolute vs relative
                "name": _text(rec[4:20]),
            })

        off += KNOB_COUNT * KNOB_REC
        self.tail = list(p[off:off + TAIL_LEN])

    def to_dict(self):
        return {
            "number": self.number,
            "name": self.name,
            "tempo": self.tempo,
            "globals_raw": self.globals_raw,
            "pads": self.pads,
            "knobs": self.knobs,
            "tail": self.tail,
        }

    def report(self):
        lines = [
            f"Preset {self.number}: {self.name!r}",
            f"  tempo?            {self.tempo}",
            f"  globals (raw)     {' '.join(f'{b:02X}' for b in self.globals_raw)}",
            "  Pads:",
        ]
        for pad in self.pads:
            lines.append(
                f"    Pad {pad['pad']:>2} (bank {pad['bank']})  "
                f"note {pad['note']:>3}  CC {pad['cc']:>3}  PC {pad['program']:>3}"
            )
        lines.append("  Knobs:")
        for k in self.knobs:
            lines.append(
                f"    Knob {k['knob']}  CC {k['cc']:>3}  "
                f"range {k['min']}-{k['max']}  mode {k['mode']}  name {k['name']!r}"
            )
        lines.append(f"  tail              {' '.join(f'{b:02X}' for b in self.tail)}")
        return "\n".join(lines)


def parse(message):
    """Parse a full F0..F7 dump reply. Returns a Preset, or raises ValueError."""
    m = list(message)
    if len(m) < 9 or m[0] != 0xF0 or m[-1] != 0xF7:
        raise ValueError("not a complete SysEx message")
    if m[1] != 0x47:
        raise ValueError(f"not an Akai message (manufacturer 0x{m[1]:02X})")
    if m[3] != PRODUCT_ID:
        raise ValueError(f"not an MPK mini IV (product 0x{m[3]:02X})")
    if m[4] != OP_DUMP:
        raise ValueError(f"not a preset dump (opcode 0x{m[4]:02X})")
    declared = (m[5] << 7) | m[6]
    payload = m[7:-1]
    if declared != len(payload):
        raise ValueError(
            f"length mismatch: header says {declared}, got {len(payload)}"
        )
    if len(payload) != PAYLOAD_LEN:
        raise ValueError(
            f"unexpected payload size {len(payload)}, expected {PAYLOAD_LEN}"
        )
    return Preset(payload)


def to_json(preset):
    return json.dumps(preset.to_dict(), indent=2)
