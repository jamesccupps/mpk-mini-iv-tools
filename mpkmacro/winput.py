"""Synthetic keyboard input and foreground-app detection (Win32, ctypes)."""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = wintypes.SHORT

# Named keys -> virtual key codes.
VK = {
    "backspace": 0x08, "tab": 0x09, "clear": 0x0C, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22, "end": 0x23,
    "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C, "apps": 0x5D,
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
    "numlock": 0x90, "scrolllock": 0x91,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "medianext": 0xB0, "mediaprev": 0xB1, "mediastop": 0xB2, "mediaplay": 0xB3,
}
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i

# Keys that live on the extended part of the keyboard and need the flag set,
# otherwise apps read them as their numpad twins.
EXTENDED = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E,
    0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3,
}
MODIFIERS = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
             "win": 0x5B, "cmd": 0x5B, "meta": 0x5B}


def _key_event(vk, up):
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _char_events(text):
    """Type any unicode text without caring about the keyboard layout."""
    events = []
    for ch in text:
        for code in _utf16_units(ch):
            for up in (False, True):
                inp = INPUT(type=INPUT_KEYBOARD)
                inp.ki = KEYBDINPUT(
                    wVk=0, wScan=code,
                    dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0),
                    time=0, dwExtraInfo=0,
                )
                events.append(inp)
    return events


def _utf16_units(ch):
    """SendInput takes UTF-16 code units, so astral chars need surrogates."""
    cp = ord(ch)
    if cp <= 0xFFFF:
        return (cp,)
    cp -= 0x10000
    return (0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF))


def _send(events):
    if not events:
        return
    arr = (INPUT * len(events))(*events)
    user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))


def parse_combo(combo):
    """'ctrl+shift+s' -> ([VK_CONTROL, VK_SHIFT], VK_S, None).

    The third item is a literal character, used when the key cannot be reached
    through the current keyboard layout and has to be injected as unicode.
    """
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        return [], None, None
    mods, key = parts[:-1], parts[-1]
    mod_vks, unknown = [], []
    for m in mods:
        if m in MODIFIERS:
            mod_vks.append(MODIFIERS[m])
        else:
            unknown.append(m)
    if unknown:
        raise ValueError(f"unknown modifier(s): {', '.join(unknown)}")
    if key in VK:
        return mod_vks, VK[key], None
    if len(key) == 1:
        scan = user32.VkKeyScanW(key)
        if scan != -1:
            vk = scan & 0xFF
            if (scan >> 8) & 1 and 0x10 not in mod_vks:
                mod_vks.append(0x10)  # the character itself needs shift
            return mod_vks, vk, None
        return mod_vks, None, key
    raise ValueError(f"unknown key: {key}")


def send_combo(combo):
    mods, vk, literal = parse_combo(combo)
    events = [_key_event(m, False) for m in mods]
    if vk is not None:
        events += [_key_event(vk, False), _key_event(vk, True)]
    elif literal:
        events += _char_events(literal)
    events += [_key_event(m, True) for m in reversed(mods)]
    _send(events)


def type_text(text):
    _send(_char_events(text))


def run_program(path, args=""):
    path = os.path.expandvars(path.strip())
    if args:
        subprocess.Popen(f'"{path}" {args}', shell=True)
    else:
        os.startfile(path)


# ---- foreground application ------------------------------------------------

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
user32.GetForegroundWindow.restype = wintypes.HWND
kernel32.OpenProcess.restype = wintypes.HANDLE


def foreground_exe():
    """Filename of the executable owning the focused window ('' on failure)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""
