# Ableton Live with the MPK mini IV (Live 12, Windows)

Setup notes that came out of getting this keyboard working with Live. They
aren't needed to use MPK Macro Studio, but they explain most "it half works"
problems.

## Control surface

Live ships an `MPK_mini_IV` control surface script, so nothing needs
installing. On the keyboard, DAW mode doesn't sustain itself: the device boots
into it and drops back to MIDI within about a second unless Live keeps talking
to it. So **DAW for a second, then MIDI** means the handshake started and the
return path failed. That is almost always the Control Surface *Output*.

Settings → **Tempo & MIDI**:

| Setting | Value |
|---|---|
| Control Surface 1 | MPK mini IV |
| Input | the port Live renames **`MPK_mini_IV Input`** |
| Output | the port Live renames **`MPK_mini_IV Output`** |

Live renames whichever port the script has claimed, which is how you identify
the DAW port. It is port 2, not port 1. Watch out: the keyboard exposes **five
MIDI outputs but only four inputs**. The output list is offset from the input
list, so the Output dropdown is easy to set one row off.

Input Ports table:

| Port | Track | Sync | Remote | MPE |
|---|---|---|---|---|
| MPK mini IV | on | – | – | – |
| MPK_mini_IV Input (port 2) | on | on | – | – |
| MPK mini IV (Port 3) | **off** | – | – | – |
| MPK mini IV (Port 4) | **off** | – | – | – |

Ports 3 and 4 must be off, or the Studio Instrument Collection plugin
misbehaves. Leave **Remote off**: the script does the mapping, and Remote on top
of it double-maps. Leave **MPE off**.

If the hardware still won't stay in DAW mode, load the DAW preset by hand:
**SHIFT + PLUGIN/DAW** → USER PRESETS → encoder to **DAW** → press the encoder.

## Capture MIDI

Live 12 removed Capture MIDI's keyboard shortcut. `Ctrl+Shift+C` is now "Copy
Time", so a macro that sends it fires the wrong command. MIDI-map the Capture
button instead:
1. Enable **Remote** on the keyboard's input port.
2. Press **Ctrl+M** and click the Capture button.
3. Press a pad, then press **Ctrl+M** again.

## Audio latency

If playing feels laggy, check **Preferences → Audio → Overall Latency** before
changing anything else. Live's MME/DirectX fallback defaults to a **4096-sample**
output buffer, which is about 93 ms. Setting it to 1024 gives about 23 ms, and
512 about 12 ms, with no driver change and nothing to install. Step back up one
if you hear crackling.

ASIO4ALL can go lower, but Realtek exposes several endpoints. Enabling
"Realtek(R) Audio" as a whole can drive the *wrong* jack, giving total silence
while Live's meters still move. Use the gear icon → Advanced Options and enable
the specific output your speakers are plugged into. `audio_test.py` plays a tone
through every Windows output in turn, so you can tell which is which:

```bash
py -3 audio_test.py --list     # list outputs
py -3 audio_test.py            # tone through each in turn
```

Silence with the meters moving usually has one of two causes. Either there is
no active stereo pair under **Output Config**, or ASIO is trying to use a device
another app (Discord, Chrome, Steam) already owns.
