"""Real SysEx captured from an MPK mini IV (firmware 1.41).

These are verbatim hardware responses, not hand-written examples, so the tests
below exercise the parser against what the device genuinely sends.
"""

def _bytes(hexstr):
    return [int(b, 16) for b in hexstr.split()]


# Reply to a dump request for slot 0. 284 bytes.
PRESET_DAW = _bytes("""
F0 47 00 5D 67 02 14 00 44 41 57 00 00 00 00 00 00 00 00 00 00 00 00 00 00
09 00 78 03 02 00 00 01 00 7F 00 01
24 20 00 05 21 25 21 01 05 21 26 22 02 05 21 27 23 03 05 21
28 24 04 05 21 29 25 05 05 21 2A 26 06 05 21 2B 27 07 05 21
2C 28 08 05 21 2D 29 09 05 21 2E 2A 0A 05 21 2F 2B 0B 05 21
30 2C 0C 05 21 31 2D 0D 05 21 32 2E 0E 05 21 33 2F 0F 05 21
18 00 7F 01 4B 4E 4F 42 31 00 00 00 00 00 00 00 00 00 00 00
19 00 7F 01 4B 4E 4F 42 32 00 00 00 00 00 00 00 00 00 00 00
1A 00 7F 01 4B 4E 4F 42 33 00 00 00 00 00 00 00 00 00 00 00
1B 00 7F 01 4B 4E 4F 42 34 00 00 00 00 00 00 00 00 00 00 00
1C 00 7F 01 4B 4E 4F 42 35 00 00 00 00 00 00 00 00 00 00 00
1D 00 7F 01 4B 4E 4F 42 36 00 00 00 00 00 00 00 00 00 00 00
1E 00 7F 01 4B 4E 4F 42 37 00 00 00 00 00 00 00 00 00 00 00
1F 00 7F 01 4B 4E 4F 42 38 00 00 00 00 00 00 00 00 00 00 00
00 00 01 00 01 00 F7
""")

# Universal identity reply. The trailing ASCII is the unit's serial number,
# zeroed here so nobody publishes theirs by accident.
IDENTITY = _bytes("""
F0 7E 7F 06 02 47 5D 00 19 00 01 04 01 00 00 00 00 00
30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 00 F7
""")

# Emitted by the keyboard when the pad mode changed, captured live.
PAD_MODE_NOTES = _bytes("F0 47 00 5D 2A 00 01 00 F7")
PAD_MODE_CC = _bytes("F0 47 00 5D 2A 00 01 02 F7")

# Emitted on connect.
STATUS_SHORT = _bytes("F0 47 00 5D 19 00 00 F7")
STATUS_LONG = _bytes(
    "F0 47 00 5D 19 00 11 02 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 F7"
)
