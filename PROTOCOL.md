# Akai MPK mini IV: SysEx protocol notes

What is known about the MPK mini IV's SysEx protocol, what is not, and how each
claim was established. Akai doesn't publish it, and its "MPK mini Editor" for
Windows doesn't support this model.

All of this comes from **one unit**, probed from Windows through `winmm`. The
identity reply's version bytes are `01 04 01 00`, recorded here as firmware
1.41. A different firmware may differ anywhere.

## How to read this document

Each finding carries one of four tags:

| Tag | Meaning |
|---|---|
| **both** | The bytes were captured *and* the behaviour was seen on hardware |
| **wire** | The bytes were captured verbatim (they are in [`tests/fixtures.py`](tests/fixtures.py)), but the meaning is not independently confirmed |
| **live** | Observed on hardware, but no byte capture is kept in the repo |
| **neither** | An inference: from other MPK models, from one coincidence, or from naming. Treat it as a hypothesis |

A byte's *value* can be wire-known while its *meaning* is only inferred. The
tables tag the meaning.

Open questions live in the [unknowns register](#unknowns-register) at the end.
Each one has a test that would settle it.

---

## Safety rules (learned on this unit)

1. **Never send a guessed opcode.** An early probe swept an invented opcode,
   `0x60`, and changed device state. What exactly changed was not recorded (U15).
2. **A preset dump request is not side-effect free.** Sweeping slots 0–13 left
   the unit on the last slot read, with that preset's pad assignments and
   colours, and knocked it out of DAW mode (U2).
3. **Recovery:** SHIFT + PLUGIN/DAW → USER PRESETS → turn the encoder to the
   preset → press the encoder.
4. **The store opcode is untested** (U14). A wrong guess could overwrite a slot.

The tools in this repo send only the universal identity request and opcode
`0x66`.

---

## USB ports

| Fact | Tag |
|---|---|
| Windows sees **4 MIDI inputs and 5 MIDI outputs**: `MPK mini IV`, then `MIDIINn (MPK mini IV)` / `MIDIOUTn (MPK mini IV)` | live |
| Port 1 carries keys, pads, knobs and wheels in MIDI mode | live |
| Ableton Live's bundled `MPK_mini_IV` script claims **port 2** (Live renames it `MPK_mini_IV Input/Output`) | live |
| The first output Windows lists with `MPK mini` in its name answers preset dump and identity requests | live |
| What ports 3 and 4 carry, and which other outputs answer SysEx | unknown (U17) |
| DAW mode doesn't sustain itself. The unit boots into it and drops back to MIDI within about a second unless the host script keeps talking | live |

`port_scout.py` watches every input at once, to map the ports.

---

## Universal identity

```
request   F0 7E 7F 06 01 F7
reply     F0 7E 7F 06 02 47 5D 00 19 00 01 04 01 00 00 00 00 00 <serial ASCII> 00 F7
```

| Bytes | Value | Meaning | Tag |
|---|---|---|---|
| 5 | `47` | Manufacturer: Akai | wire (standard MIDI ID) |
| 6–7 | `5D 00` | Family `0x5D`, the product ID used in every Akai-framed message below | both |
| 8–9 | `19 00` | Model `25`, which matches the key count | neither |
| 10–13 | `01 04 01 00` | Firmware version, read as 1.41. Whether the unit's display says 1.41 or 1.4.1 isn't recorded | neither (U18) |
| 14.. | ASCII | Unit serial number, then `00` | wire |

The serial is zeroed in the fixture. **Zero it in any capture you publish.**

`0x5D` fits Akai's MPK mini numbering: mk2 is `0x26` and mk3 is `0x49`.

---

## Akai message envelope

```
F0 47 <dev> 5D <opcode> <lenMSB> <lenLSB> <payload...> F7
```

| Field | Meaning | Tag |
|---|---|---|
| `<dev>` | Device ID. The unit sends `00`. Requests with either `00` or `7F` are answered | live (both IDs answered); wire (`00` in replies) |
| `<lenMSB> <lenLSB>` | Payload length, 14 bits over two 7-bit bytes: `(MSB << 7) \| LSB` | wire (holds for every captured frame) |

`mpk_preset.parse_frame()` unwraps any frame of this shape and checks the
declared length.

## Opcodes

| Opcode | Direction | Payload | Meaning | Tag |
|---|---|---|---|---|
| `0x66` | PC → unit | 1 byte: slot | Preset dump request. Same opcode as the mk2/mk3 | live (the unit replies with `0x67`) |
| `0x67` | unit → PC | 276 bytes | Preset dump. Layout below | both |
| `0x2A` | unit → PC | 1 byte: mode | Pad mode changed. `00` = Notes, `02` = CC#. Other values unseen (U11) | both. Right after `00` the pads sent Note On on ch10; while `02`, they sent CC 34/35 |
| `0x19` | unit → PC | 0 or 17 bytes | Sent on connect. 17-byte form starts `02`, then zeros. Meaning unknown (U13) | wire |
| `0x2A` | PC → unit | — | Whether *sending* it sets the pad mode is **untested**. Don't assume it does (U12) | neither |
| `0x64` | PC → unit | — | Store, on the mk2/mk3. **Untested here** (U14) | neither |
| `0x60` | PC → unit | — | Not a known opcode. Sending it changed device state (U15) | live |

Captured frames (all in `tests/fixtures.py`):

```
F0 47 00 5D 2A 00 01 00 F7         pad mode -> Notes
F0 47 00 5D 2A 00 01 02 F7         pad mode -> CC#
F0 47 00 5D 19 00 00 F7            status, short
F0 47 00 5D 19 00 11 02 00 .. 00 F7  status, 17 bytes
F0 47 00 5D 67 02 14 <276 bytes> F7  preset dump (slot 0 request), 284 bytes total
```

---

## Preset dump request

```
F0 47 00 5D 66 00 01 <slot> F7
```

| Slot | Contents | Tag |
|---|---|---|
| `0` | Returned a preset named `DAW` (this is the fixture). **Reported byte-identical to slot 1.** Either it is the "current buffer" (the mk2/mk3 convention) or it is an alias for slot 1. Unresolved (U1) | wire (reply); live (identical to slot 1) |
| `1` | `DAW` preset | live |
| `2` | Unknown (U4) | — |
| `3`–`13` | USER 1–USER 11, inferred because a 0–13 sweep ended on USER11 | neither |

**The request appears to load the slot it asks for** (U2). This tool's "Read
preset" button and `dump_presets.py` both ask for slot 0 only, for that reason.
Until U1 is settled, that may still leave the unit on slot 1.

## Preset dump payload (276 bytes)

Offsets are from the start of the payload, after `<lenLSB>`.

| Offset | Size | Contents | Tag for the meaning |
|---|---|---|---|
| 0 | 1 | `00` in the slot-0 reply. Assumed to be the preset number, but see U3 | neither |
| 1 | 16 | Name, ASCII, NUL-padded (`DAW`) | wire |
| 17 | 13 | Global settings. See the next table | mixed |
| 30 | 80 | 16 pad records, 5 bytes each. Pads 1–8 are bank A, 9–16 are bank B | wire |
| 110 | 160 | 8 knob records, 20 bytes each | wire |
| 270 | 6 | Tail: `00 00 01 00 01 00` | unknown (U10) |

### Global settings (offset 17, 13 bytes)

Factory `DAW` preset: `00 09 00 78 03 02 00 00 01 00 7F 00 01`

| Index | Value | Meaning | Tag |
|---|---|---|---|
| 1 | `09` | Pad MIDI channel, 0-based (ch10). The Device view relies on this | neither. It matches pads transmitting on ch10, but was never varied (U5) |
| 3 | `78` | Tempo, 120 BPM | neither (U6) |
| 0, 2, 4–12 | as above | Unknown | U7 |

### Pad record (5 bytes)

| Byte | Factory values | Meaning | Tag |
|---|---|---|---|
| 0 | 36–51 | Note | both. Pads sent notes 36+ on ch10 |
| 1 | 32–47 | CC number (used in CC# pad mode) | both. In CC# mode, pads sent CC 34/35 |
| 2 | 0–15 | Program change number | wire |
| 3–4 | `05 21` on every pad | Unknown. Possibly pad colour, because loading a slot changed the colours | U8 |

### Knob record (20 bytes)

| Byte | Factory values | Meaning | Tag |
|---|---|---|---|
| 0 | 24–31 | CC number | both. The knobs send CC 24–31 |
| 1 | `00` | Minimum | wire |
| 2 | `7F` | Maximum | wire |
| 3 | `01` (`00` also seen on some preset) | Mode, possibly absolute vs relative | neither (U9) |
| 4–19 | `KNOB1`…`KNOB8` | Name, ASCII, NUL-padded | wire |

---

## Unknowns register

Each item says what is open and the cheapest test that would settle it. Unless
an item says otherwise, start from a known preset and keep a `--raw` dump of it,
so every change can be diffed and put back.

| ID | Open question | Falsification test |
|---|---|---|
| U1 | Is slot 0 the current buffer, or an alias for slot 1? | Load USER 5 by hand. Request slot 0 *only*. Compare the reply with a separate slot-1 read, and note what the display shows afterwards |
| U2 | Does a dump request always load the slot? Seen once, during a 0–13 sweep | Load USER 5. Request slot 3 once. Check the display. Repeat with slot 0 |
| U3 | Is payload byte 0 the slot number? The slot-0 reply reads `00`, but slot 1 was reported identical | Request slots 1 and 5 and diff byte 0 |
| U4 | What is slot 2? | Request slot 2 and read the name |
| U5 | Is globals[1] the pad MIDI channel? | Change the pad channel in PROG EDIT, save to a scratch user slot, and read it back |
| U6 | Is globals[3] the tempo? | Set the BPM to 97 (`0x61`) and read back |
| U7 | What are the remaining globals bytes? | Change one global setting at a time, read, diff |
| U8 | What are pad bytes 3–4 (`05 21`)? | Change one pad's colour (or other per-pad setting), read, diff |
| U9 | What are the knob mode byte's values? | Set knob 1 to relative, read, diff |
| U10 | What are the tail bytes? | Diff dumps of several user presets |
| U11 | Which pad-mode values exist beyond `00`/`02`? `01` is probably Prog Change, going by the pad legend order PROG CHNG / CC# / NOTES | Switch the pads to PROG CHNG with the SysEx Lab open |
| U12 | Does sending `0x2A` set the pad mode? | Only after U11 is settled, and only with the recovery steps to hand. Send `F0 47 00 5D 2A 00 01 02 F7` and see if the pads switch to CC# |
| U13 | What does the 17-byte `0x19` status mean? | Capture it in DAW mode and in MIDI mode, after preset changes, and diff |
| U14 | Is `0x64` the store opcode, and what does it expect? | On a scratch user slot whose dump you have saved: send that same dump back with `0x64`, then read it back. Only after that, change one byte |
| U15 | What did `0x60` change? | Not worth repeating without a reason. If you do, dump every slot first |
| U16 | What do the buttons send (ARP, LATCH, NOTE RPT, TAP TEMPO, UNDO, LOOP, transport, encoder) in MIDI mode vs DAW mode? | Run `button_map.py` once in each mode, with the DAW closed for the MIDI-mode run |
| U17 | What do ports 3–4 carry, and which outputs answer SysEx? | `port_scout.py` for inputs. For outputs, send the identity request to each one |
| U18 | Does `01 04 01 00` read as 1.41 or 1.4.1? | Compare with the version the unit's global menu shows |

## Adding a finding

1. Capture it. The app's **SysEx Lab** shows every frame, decoded where
   possible, and can save the log. `dump_presets.py --raw` prints a dump as hex.
2. Zero any serial number.
3. Add the frame to `tests/fixtures.py`, with a comment saying what was done on
   the hardware and the firmware version.
4. Write a test that the parser reads it the way you claim.
5. Update the tables here, change the tag, and strike the item from the register.
