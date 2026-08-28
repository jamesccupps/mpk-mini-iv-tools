"""MIDI input/output on Windows via winmm + ctypes.

No third-party packages. Works on any stock Python 3.8+ on Windows.
Handles short messages (notes/CC/PC) and SysEx in both directions -- SysEx is
what a hardware editor is built on, so it is first-class here.
"""
from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes

winmm = ctypes.WinDLL("winmm")

HMIDIIN = wintypes.HANDLE
HMIDIOUT = wintypes.HANDLE
DWORD_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

CALLBACK_FUNCTION = 0x00030000
MIM_DATA = 0x3C3
MIM_LONGDATA = 0x3C4
MMSYSERR_NOERROR = 0

SYSEX_BUFFERS = 4
SYSEX_BUFFER_SIZE = 8192


class MIDIINCAPS(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * 32),
        ("dwSupport", wintypes.DWORD),
    ]


class MIDIOUTCAPS(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * 32),
        ("wTechnology", wintypes.WORD),
        ("wVoices", wintypes.WORD),
        ("wNotes", wintypes.WORD),
        ("wChannelMask", wintypes.WORD),
        ("dwSupport", wintypes.DWORD),
    ]


class MIDIHDR(ctypes.Structure):
    pass


MIDIHDR._fields_ = [
    # Deliberately NOT c_char_p: ctypes would convert that back into a Python
    # bytes object truncated at the first NUL, and SysEx dumps are full of NULs.
    ("lpData", ctypes.POINTER(ctypes.c_char)),
    ("dwBufferLength", wintypes.DWORD),
    ("dwBytesRecorded", wintypes.DWORD),
    ("dwUser", DWORD_PTR),
    ("dwFlags", wintypes.DWORD),
    ("lpNext", ctypes.POINTER(MIDIHDR)),
    ("reserved", DWORD_PTR),
    ("dwOffset", wintypes.DWORD),
    ("dwReserved", DWORD_PTR * 8),
]

MidiInProc = ctypes.WINFUNCTYPE(
    None, HMIDIIN, wintypes.UINT, DWORD_PTR, DWORD_PTR, DWORD_PTR
)

winmm.midiInGetNumDevs.restype = wintypes.UINT
winmm.midiOutGetNumDevs.restype = wintypes.UINT
winmm.midiInOpen.argtypes = [
    ctypes.POINTER(HMIDIIN), wintypes.UINT, MidiInProc, DWORD_PTR, wintypes.DWORD
]
winmm.midiInOpen.restype = wintypes.UINT
winmm.midiOutOpen.argtypes = [
    ctypes.POINTER(HMIDIOUT), wintypes.UINT, DWORD_PTR, DWORD_PTR, wintypes.DWORD
]
winmm.midiOutOpen.restype = wintypes.UINT
winmm.midiOutShortMsg.argtypes = [HMIDIOUT, wintypes.DWORD]
winmm.midiOutShortMsg.restype = wintypes.UINT
winmm.midiInPrepareHeader.argtypes = [HMIDIIN, ctypes.POINTER(MIDIHDR), wintypes.UINT]
winmm.midiInUnprepareHeader.argtypes = [HMIDIIN, ctypes.POINTER(MIDIHDR), wintypes.UINT]
winmm.midiInAddBuffer.argtypes = [HMIDIIN, ctypes.POINTER(MIDIHDR), wintypes.UINT]
winmm.midiOutPrepareHeader.argtypes = [
    HMIDIOUT, ctypes.POINTER(MIDIHDR), wintypes.UINT
]
winmm.midiOutUnprepareHeader.argtypes = [
    HMIDIOUT, ctypes.POINTER(MIDIHDR), wintypes.UINT
]
winmm.midiOutLongMsg.argtypes = [HMIDIOUT, ctypes.POINTER(MIDIHDR), wintypes.UINT]


class MidiError(RuntimeError):
    pass


def _check(rc: int, what: str) -> None:
    if rc != MMSYSERR_NOERROR:
        buf = ctypes.create_unicode_buffer(256)
        try:
            winmm.midiInGetErrorTextW(rc, buf, 256)
        except Exception:
            pass
        raise MidiError(f"{what} failed (code {rc}) {buf.value}".strip())


def input_devices():
    names = []
    for i in range(winmm.midiInGetNumDevs()):
        caps = MIDIINCAPS()
        winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
        names.append(caps.szPname)
    return names


def output_devices():
    names = []
    for i in range(winmm.midiOutGetNumDevs()):
        caps = MIDIOUTCAPS()
        winmm.midiOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
        names.append(caps.szPname)
    return names


def base_device_name(name):
    """'MIDIOUT2 (MPK mini IV)' -> 'mpk mini iv'; 'MPK mini IV' -> 'mpk mini iv'.

    Windows wraps a multi-port device's extra ports in 'MIDIIN2 (...)' style
    names. Stripping that back to the hardware name lets us tell when an input
    and an output are the same physical box.
    """
    name = (name or "").strip()
    if "(" in name and name.endswith(")"):
        name = name[name.index("(") + 1:-1]
    return name.strip().lower()


def same_device(a, b):
    base_a, base_b = base_device_name(a), base_device_name(b)
    return bool(base_a) and base_a == base_b


def find_device(names, needle):
    """Index of the first device whose name contains needle (case-insensitive)."""
    needle = needle.lower()
    for i, n in enumerate(names):
        if needle in n.lower():
            return i
    return None


class MidiIn:
    """Opens a MIDI input and pushes messages onto a queue.

    The winmm callback runs on a system thread and must stay tiny, so it only
    unpacks bytes (short messages) or notes which SysEx buffer filled up. A
    worker thread does the copying and re-arms the buffer -- calling back into
    winmm from the callback itself can deadlock.
    """

    def __init__(self):
        self.handle = HMIDIIN()
        self.queue = queue.SimpleQueue()
        self._cb = MidiInProc(self._callback)  # must stay referenced
        self._headers = []
        self._buffers = []
        self._refill = queue.SimpleQueue()
        self._refill_thread = None
        self._running = False
        self.is_open = False
        self.device_name = ""

    def open(self, index, sysex=True):
        self.close()
        _check(
            winmm.midiInOpen(
                ctypes.byref(self.handle), index, self._cb, 0, CALLBACK_FUNCTION
            ),
            "midiInOpen",
        )
        if sysex:
            self._running = True
            self._refill_thread = threading.Thread(
                target=self._refill_loop, daemon=True
            )
            self._refill_thread.start()
            for _ in range(SYSEX_BUFFERS):
                self._add_buffer()
        _check(winmm.midiInStart(self.handle), "midiInStart")
        self.is_open = True
        devs = input_devices()
        self.device_name = devs[index] if index < len(devs) else f"device {index}"

    def _add_buffer(self):
        buf = ctypes.create_string_buffer(SYSEX_BUFFER_SIZE)
        hdr = MIDIHDR()
        hdr.lpData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
        hdr.dwBufferLength = SYSEX_BUFFER_SIZE
        hdr.dwFlags = 0
        self._buffers.append(buf)
        self._headers.append(hdr)
        winmm.midiInPrepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
        winmm.midiInAddBuffer(self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr))

    def _callback(self, _h, msg, _inst, p1, _p2):
        if msg == MIM_DATA:
            self.queue.put(("short", (p1 & 0xFF, (p1 >> 8) & 0x7F, (p1 >> 16) & 0x7F)))
        elif msg == MIM_LONGDATA:
            self._refill.put(int(p1))

    def _refill_loop(self):
        while self._running:
            try:
                ptr = self._refill.get(timeout=0.25)
            except queue.Empty:
                continue
            if ptr is None:
                break
            hdr = ctypes.cast(ptr, ctypes.POINTER(MIDIHDR)).contents
            n = hdr.dwBytesRecorded
            if n:
                data = bytes(hdr.lpData[:n])
                self.queue.put(("sysex", tuple(data)))
            if self._running:
                hdr.dwBytesRecorded = 0
                winmm.midiInAddBuffer(
                    self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr)
                )

    def close(self):
        if not self.is_open:
            return
        self._running = False
        self._refill.put(None)
        winmm.midiInStop(self.handle)
        winmm.midiInReset(self.handle)
        for hdr in self._headers:
            winmm.midiInUnprepareHeader(
                self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr)
            )
        self._headers.clear()
        self._buffers.clear()
        winmm.midiInClose(self.handle)
        self.is_open = False
        self.device_name = ""


class MidiOut:
    def __init__(self):
        self.handle = HMIDIOUT()
        self.is_open = False
        self.device_name = ""

    def open(self, index):
        self.close()
        _check(
            winmm.midiOutOpen(ctypes.byref(self.handle), index, 0, 0, 0), "midiOutOpen"
        )
        self.is_open = True
        devs = output_devices()
        self.device_name = devs[index] if index < len(devs) else f"device {index}"

    def send(self, status, data1=0, data2=0):
        if not self.is_open:
            return
        packed = (status & 0xFF) | ((data1 & 0x7F) << 8) | ((data2 & 0x7F) << 16)
        winmm.midiOutShortMsg(self.handle, packed)

    def send_sysex(self, data):
        """data: iterable of ints, with or without the F0 / F7 wrapper."""
        if not self.is_open:
            return
        payload = list(data)
        if not payload:
            return
        if payload[0] != 0xF0:
            payload.insert(0, 0xF0)
        if payload[-1] != 0xF7:
            payload.append(0xF7)
        raw = bytes(payload)
        buf = ctypes.create_string_buffer(raw, len(raw))
        hdr = MIDIHDR()
        hdr.lpData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
        hdr.dwBufferLength = len(raw)
        hdr.dwBytesRecorded = len(raw)
        hdr.dwFlags = 0
        winmm.midiOutPrepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
        winmm.midiOutLongMsg(self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
        winmm.midiOutUnprepareHeader(self.handle, ctypes.byref(hdr), ctypes.sizeof(hdr))

    def close(self):
        if self.is_open:
            winmm.midiOutReset(self.handle)
            winmm.midiOutClose(self.handle)
            self.is_open = False
            self.device_name = ""


# ---- message helpers -------------------------------------------------------

NOTE_OFF, NOTE_ON, POLY_AT, CC, PC, CHAN_AT, PITCH = 0x8, 0x9, 0xA, 0xB, 0xC, 0xD, 0xE
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(note):
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


def hexdump(data):
    return " ".join(f"{b:02X}" for b in data)


def describe(status, d1, d2):
    kind, ch = status >> 4, (status & 0x0F) + 1
    if kind == NOTE_ON and d2 > 0:
        return f"Note On   ch{ch:<3} {note_name(d1)} ({d1})   vel {d2}"
    if kind == NOTE_OFF or (kind == NOTE_ON and d2 == 0):
        return f"Note Off  ch{ch:<3} {note_name(d1)} ({d1})"
    if kind == CC:
        return f"CC        ch{ch:<3} #{d1}   value {d2}"
    if kind == PC:
        return f"Program   ch{ch:<3} #{d1}"
    if kind == PITCH:
        return f"Pitchbend ch{ch:<3} {((d2 << 7) | d1) - 8192:+d}"
    if kind == CHAN_AT:
        return f"Aftertch  ch{ch:<3} {d1}"
    if kind == POLY_AT:
        return f"PolyAT    ch{ch:<3} {note_name(d1)}   {d2}"
    return f"Raw       {status:02X} {d1} {d2}"
