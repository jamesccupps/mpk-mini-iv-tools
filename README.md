# MPK Macro Studio

Turns an **Akai MPK mini IV** into a macro controller for Windows, and talks to
the keyboard's own preset memory over SysEx.

Pure standard-library Python — no `pip install`, no dependencies.

```bash
"MPK Macro Studio.bat"
```

**Requirements:** Windows, Python 3.8+. Nothing else. It uses `winmm` and
`SendInput` through `ctypes`, and Tkinter for the UI.

> [!WARNING]
> The SysEx tools here talk to real hardware over a protocol that was
> reverse-engineered, not documented. Two behaviours to know before you run
> anything:
>
> - **Requesting a preset appears to make the keyboard load it.** Sweeping every
>   slot leaves the unit on the last one read, with different pad assignments
>   and colours. Recovery is SHIFT + PLUGIN/DAW → encoder → your preset.
> - **Never send a guessed opcode.** An early version of `re_probe.py` swept an
>   invented opcode and changed device state. Everything here now sends only
>   opcodes confirmed against hardware.
>
> Nothing here writes to the keyboard's memory, and SysEx cannot damage the
> device — but it can change settings you then have to put back.

Unofficial and unaffiliated with Akai Professional or inMusic. Findings come
from probing one MPK mini IV (firmware 1.41). Use at your own risk.

## Why this exists

The mini IV edits itself. Hold **SHIFT + PROG EDIT** on the keyboard and you can
change any pad's note, any knob's CC, MIDI channels, ranges and curves, then
save to one of 11 user preset slots. Akai's old "MPK mini Editor" for Windows
does **not** support this model, and it doesn't need to.

What the keyboard cannot do is press keys on your computer. That is what this
adds — plus a way to read its presets from the PC.

## What it does

**Device tab — a live picture of the keyboard.** Pads, knobs, wheels, keys and
the button strip, laid out like the real panel. Touch anything and it lights up,
with the exact note or CC it just sent shown underneath. Every label is read off
the preset that is *actually loaded* on your unit, so pad and knob numbers are
never a guess. Click any control to build a macro for it.

Pads and keys can share note numbers, so the view uses the pad MIDI channel from
the preset (channel 10 on the factory presets) to tell them apart. The keyboard
drawing re-bases itself automatically when you use OCT − / OCT +.

**Macros.** Any pad, key or knob can fire:

| Action | What it does |
|---|---|
| `keys` | A keyboard shortcut in the focused app (`ctrl+shift+s`) |
| `text` | Types a block of text |
| `run` | Launches a program or file |
| `wait` | Pauses between steps |
| `chord` | Plays a chord out a MIDI port, with optional strum |
| `cc` | Sends a CC — set value to `passthru` for **macro knobs** |
| `note` / `program` | Single note or program change |

Chain several actions into one macro; they run in order.

**Profiles** switch automatically by focused app — put `Ableton Live 12
Suite.exe` in the auto-switch box and that profile follows your focus.

**MIDI Monitor** shows exactly what the keyboard sends, so you never have to
guess a pad number.

**SysEx Lab** sends raw SysEx and shows replies — this is where the protocol
below was worked out.

## Setup

1. Run `MPK Macro Studio.bat`. It finds the keyboard and reads its preset.
2. On the **Device** tab, press the pad or turn the knob you want to use — it
   lights up so you know you've got the right one.
3. Click it, add an action, Save.
4. Focus your DAW and hit the pad.

The included profile has six example macros. They ship **disabled** so nothing
surprises you — tick "Enable / disable" on the ones you want.

### Playing notes *and* running macros at once

A macro that swallows its message stops it reaching the DAW, and `chord`/`cc`
actions need somewhere to send notes. Both are solved by a virtual MIDI cable:

1. Install **loopMIDI** (free, Tobias Erichsen) and create a port.
2. Set **Send MIDI to** = that port.
3. Point your DAW at the loopMIDI port instead of the MPK directly.

Without it, macros still work fine — keystrokes need no MIDI routing at all.

## Ableton Live setup (Live 12, Windows)

Live ships an `MPK_mini_IV` control surface script, so nothing needs
installing. On the keyboard, DAW mode is not self-sustaining: the device boots
into it and drops back to MIDI within about a second unless Live keeps talking
to it. **DAW for a second, then MIDI** therefore means the handshake started
and the return path failed — almost always the Control Surface *Output*.

Settings → **Tempo & MIDI**:

| Setting | Value |
|---|---|
| Control Surface 1 | MPK mini IV |
| Input | the port Live renames **`MPK_mini_IV Input`** |
| Output | the port Live renames **`MPK_mini_IV Output`** |

Live renames whichever port the script has claimed, which is how you identify
the DAW port — it is port 2, not port 1. Watch out: the keyboard exposes
**five MIDI outputs but only four inputs**, so the output list is offset from
the input list and the Output dropdown is easy to set one row off.

Input Ports table:

| Port | Track | Sync | Remote | MPE |
|---|---|---|---|---|
| MPK mini IV | on | – | – | – |
| MPK_mini_IV Input (port 2) | on | on | – | – |
| MPK mini IV (Port 3) | **off** | – | – | – |
| MPK mini IV (Port 4) | **off** | – | – | – |

Ports 3 and 4 must be off or the Studio Instrument Collection plugin
misbehaves. Leave **Remote off** — the script does the mapping, and Remote on
top of it double-maps. Leave **MPE off**.

If the hardware still will not sit in DAW mode, load the DAW preset by hand:
**SHIFT + PLUGIN/DAW** → USER PRESETS → encoder to **DAW** → press the encoder.
DAW is preset slot 1.

### Audio latency

If playing feels laggy, check **Preferences → Audio → Overall Latency** before
changing anything else. Live's MME/DirectX fallback defaults to a **4096 sample**
output buffer, which is ~93 ms. Dragging that to 1024 gives ~23 ms and 512 gives
~12 ms, with no driver change and nothing to install. Step back up one if you
hear crackling.

ASIO4ALL can go lower, but note that Realtek exposes several endpoints. Enabling
"Realtek(R) Audio" as a whole can drive the *wrong* jack and produce total
silence while Live's meters still move. Use the gear icon → Advanced Options and
enable the specific output your speakers are plugged into. `audio_test.py` plays
a tone through every Windows output in turn so you can identify which is which:

```bash
py -3 audio_test.py --list     # list outputs
py -3 audio_test.py            # tone through each in turn
```

Silence with meters moving has two usual causes: no active stereo pair under
**Output Config**, or ASIO holding a device another app (Discord, Chrome, Steam)
already owns.

## The MPK mini IV SysEx protocol

Reverse-engineered from a real unit; every field below is confirmed against
hardware unless marked otherwise.

The universal identity request `F0 7E 7F 06 01 F7` returns:

```
F0 7E 7F 06 02 47 5D 00 19 00 01 04 01 00 00 00 00 00 <serial ASCII> 00 F7
            ^^ ^^
            |  product ID 0x5D = MPK mini IV
            Akai
```

That `5D` is the key — it slots into Akai's existing MPK mini scheme
(`0x26` = mk2, `0x49` = mk3):

```
request   F0 47 <dev> 5D 66 00 01 <preset> F7
reply     F0 47 <dev> 5D 67 <lenMSB> <lenLSB> <payload> F7
```

`<dev>` may be `00` or `7F`; both answer. `<preset>` is `0` for the current
buffer and `1`–`13` for the slots. Length is 14 bits over two 7-bit bytes,
`(MSB << 7) | LSB` = **276**, giving a 284-byte message.

Payload layout:

| Offset | Size | Contents |
|---|---|---|
| 0 | 1 | Preset number |
| 1 | 16 | Name, ASCII, NUL padded |
| 17 | 13 | Global settings — byte 3 is `0x78` (120), almost certainly tempo; rest not yet identified |
| 30 | 80 | 16 pad records, 5 bytes each |
| 110 | 160 | 8 knob records, 20 bytes each |
| 270 | 6 | Tail, `00 00 01 00 01 00` on factory presets |

Pad record (5 bytes): `note`, `cc`, `program`, then 2 bytes not yet identified.
Knob record (20 bytes): `cc`, `min`, `max`, `mode`, then a 16-byte ASCII name.

Factory defaults read back as pads = notes 36–51 / CC 32–47 / PC 0–15, and
knobs = CC 24–31 named `KNOB1`–`KNOB8`.

### Messages the keyboard sends unprompted

Captured live while operating the hardware:

| Message | Meaning |
|---|---|
| `F0 47 00 5D 2A 00 01 <mode> F7` | pad mode changed. `00` = Notes, `02` = CC#. Confirmed: right after mode `00` the pads began sending `Note On` on ch10, and while in `02` they sent CC 34/35 (pads use CC 32-47). |
| `F0 47 00 5D 19 00 00 F7` | status, emitted on connect |
| `F0 47 00 5D 19 00 11 02 ...` | longer status, emitted on connect |

Whether sending `0x2A` *to* the device sets the pad mode is **untested**. Don't
assume it does — see the warning below.

### Danger: requesting a preset appears to load it

Observed on hardware: sweeping slots 0-13 with the dump-request opcode left the
unit sitting on the last slot read, with that preset's pad assignments and pad
colours, and knocked it out of DAW mode. Recovery is
**SHIFT + PLUGIN/DAW -> encoder to DAW -> press encoder**.

So reads are not as side-effect-free as the opcode name suggests. `dump_presets.py`
therefore reads only the current preset unless you pass `--all`.

Two rules learned the hard way:

- **Never send a guessed opcode to hardware.** An earlier version of
  `re_probe.py` swept an invented `0x60`; that has been removed.
- **Connecting should never transmit.** The app no longer auto-requests a
  preset dump when it opens.

### Tools

```bash
py -3 dump_presets.py          # all 14 presets, plain English
py -3 dump_presets.py --json   # machine readable
py -3 dump_presets.py --raw    # hex
py -3 re_probe.py              # protocol reconnaissance
```

Both are **read-only**. Nothing here writes to the keyboard.

### Not done yet: writing presets back

Reading is solved. Writing needs the store opcode, which on the mk2/mk3 is
`0x64` — untested here, because a wrong guess overwrites a preset slot. Test it
on a slot you don't care about, and read it back to confirm.

## Layout

```
main.py                 launcher
MPK Macro Studio.bat    double-click this
dump_presets.py         read presets from the keyboard
re_probe.py             SysEx reconnaissance
profiles/*.json         your macros, one file per profile
settings.json           last used ports
mpkmacro/
  winmidi.py            MIDI in/out + SysEx via winmm
  winput.py             SendInput keystrokes, foreground app
  engine.py             matching and action execution
  gui.py                Tkinter UI
  device_view.py        the live panel drawing
  mpk_preset.py         preset format
```

## Notes

- Windows only — it uses `winmm` and `SendInput` directly.
- Keystrokes go to whatever window has focus, exactly as if typed.
- MIDI callbacks do the minimum on the system thread and hand off to a worker,
  which is why SysEx dumps arrive intact.
