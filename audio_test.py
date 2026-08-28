"""Play a test tone through each Windows audio output in turn.

Bypasses Ableton and ASIO entirely -- this is the raw Windows audio path, so
whichever device you actually hear identifies the hardware your speakers are
on. Point ASIO4ALL at that same device.

    py -3 audio_test.py            # tone through every device in turn
    py -3 audio_test.py --list     # just list them
    py -3 audio_test.py --device 3 # only device 3
"""
from __future__ import annotations

import ctypes
import math
import struct
import sys
import time
from ctypes import wintypes

winmm = ctypes.WinDLL("winmm")

SAMPLE_RATE = 44100
SECONDS = 1.2
FREQ = 440.0
AMPLITUDE = 0.25          # keep it civil
WAVE_FORMAT_PCM = 1
WAVE_MAPPER = 0xFFFFFFFF


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [
    # POINTER(c_char), not c_char_p: ctypes would truncate the buffer at the
    # first NUL byte, and PCM audio is full of them.
    ("lpData", ctypes.POINTER(ctypes.c_char)),
    ("dwBufferLength", wintypes.DWORD),
    ("dwBytesRecorded", wintypes.DWORD),
    ("dwUser", ctypes.c_void_p),
    ("dwFlags", wintypes.DWORD),
    ("dwLoops", wintypes.DWORD),
    ("lpNext", ctypes.POINTER(WAVEHDR)),
    ("reserved", ctypes.c_void_p),
]


class WAVEOUTCAPS(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * 32),
        ("dwFormats", wintypes.DWORD),
        ("wChannels", wintypes.WORD),
        ("wReserved1", wintypes.WORD),
        ("dwSupport", wintypes.DWORD),
    ]


def devices():
    out = []
    for i in range(winmm.waveOutGetNumDevs()):
        caps = WAVEOUTCAPS()
        if winmm.waveOutGetDevCapsW(i, ctypes.byref(caps),
                                    ctypes.sizeof(caps)) == 0:
            out.append((i, caps.szPname))
    return out


def tone_bytes():
    frames = int(SAMPLE_RATE * SECONDS)
    data = bytearray()
    for n in range(frames):
        # short fade in/out so it doesn't click
        env = min(1.0, n / 2000.0, (frames - n) / 2000.0)
        v = int(32767 * AMPLITUDE * env * math.sin(2 * math.pi * FREQ * n / SAMPLE_RATE))
        data += struct.pack("<hh", v, v)      # stereo
    return bytes(data)


def play(device_id, pcm):
    fmt = WAVEFORMATEX(
        wFormatTag=WAVE_FORMAT_PCM, nChannels=2, nSamplesPerSec=SAMPLE_RATE,
        nAvgBytesPerSec=SAMPLE_RATE * 4, nBlockAlign=4, wBitsPerSample=16,
        cbSize=0,
    )
    hwo = ctypes.c_void_p()
    rc = winmm.waveOutOpen(ctypes.byref(hwo), device_id, ctypes.byref(fmt),
                           0, 0, 0)
    if rc != 0:
        return f"could not open (code {rc} -- another app may hold it)"

    buf = ctypes.create_string_buffer(pcm, len(pcm))
    hdr = WAVEHDR()
    hdr.lpData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    hdr.dwBufferLength = len(pcm)
    hdr.dwFlags = 0
    winmm.waveOutPrepareHeader(hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.waveOutWrite(hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
    time.sleep(SECONDS + 0.25)
    winmm.waveOutUnprepareHeader(hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.waveOutClose(hwo)
    return "played"


def main(argv):
    devs = devices()
    if not devs:
        print("No audio output devices found.")
        return 1

    if "--list" in argv:
        for i, name in devs:
            print(f"  [{i}] {name}")
        return 0

    only = None
    if "--device" in argv:
        only = int(argv[argv.index("--device") + 1])

    pcm = tone_bytes()
    print("Playing a 440 Hz tone through each output.")
    print("Note which number you HEAR.\n")
    for i, name in devs:
        if only is not None and i != only:
            continue
        print(f"  [{i}] {name} ... ", end="", flush=True)
        print(play(i, pcm), flush=True)
        time.sleep(0.3)
    print("\nWhichever number you heard is the device your speakers are on.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
