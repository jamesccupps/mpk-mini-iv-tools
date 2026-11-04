"""Tests for the winmm layer's buffer handling. Windows only; no keyboard."""
import ctypes
import os
import queue
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform != "win32":
    raise unittest.SkipTest("winmidi is Windows only")

from mpkmacro import winmidi            # noqa: E402

SYNTH = "Microsoft GS Wavetable Synth"


def header_with(data):
    buf = ctypes.create_string_buffer(bytes(data), winmidi.SYSEX_BUFFER_SIZE)
    hdr = winmidi.MIDIHDR()
    hdr.lpData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    hdr.dwBufferLength = winmidi.SYSEX_BUFFER_SIZE
    hdr.dwBytesRecorded = len(data)
    return buf, hdr


class TestRefillLoop(unittest.TestCase):
    """The refill thread is handed raw addresses by the winmm callback."""

    def run_loop(self, midi_in, *addresses):
        refill = queue.SimpleQueue()
        midi_in._running = True
        worker = threading.Thread(target=midi_in._refill_loop, args=(refill,))
        worker.start()
        for addr in addresses:
            refill.put(addr)
        time.sleep(0.05)
        refill.put(None)
        worker.join(timeout=2)
        midi_in._running = False
        self.assertFalse(worker.is_alive())
        out = []
        while True:
            try:
                out.append(midi_in.queue.get_nowait())
            except queue.Empty:
                return out

    def test_own_header_is_copied_out(self):
        mi = winmidi.MidiIn()
        sysex = [0xF0, 0x47, 0x00, 0x5D, 0x19, 0x00, 0x00, 0xF7]
        buf, hdr = header_with(sysex)
        mi._headers[ctypes.addressof(hdr)] = hdr
        self.assertEqual(self.run_loop(mi, ctypes.addressof(hdr)),
                         [("sysex", tuple(sysex))])
        self.assertEqual(hdr.dwBytesRecorded, 0)      # reset for reuse

    def test_unknown_address_is_never_dereferenced(self):
        """A previous session's header address -- freed memory -- must be
        skipped, not cast to a MIDIHDR and read."""
        mi = winmidi.MidiIn()
        buf, hdr = header_with([0xF0, 0xF7])
        stale = ctypes.addressof(hdr)
        del buf, hdr                                  # gone, like after close()
        self.assertEqual(self.run_loop(mi, stale, 0xDEADBEEF), [])


@unittest.skipUnless(SYNTH in winmidi.output_devices(),
                     f"needs the {SYNTH} output")
class TestSysexSend(unittest.TestCase):
    """Sends a universal identity request to Windows' built-in synth, which
    ignores it. Never targets a hardware port."""

    def test_returns_only_once_the_driver_is_done(self):
        out = winmidi.MidiOut()
        out.open(winmidi.output_devices().index(SYNTH))
        try:
            started = time.monotonic()
            out.send_sysex([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])
            self.assertLess(time.monotonic() - started,
                            winmidi.SYSEX_SEND_TIMEOUT)
        finally:
            out.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
