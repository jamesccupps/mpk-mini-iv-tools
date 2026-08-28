"""A drawing of the MPK mini IV that lights up as you play it.

The panel layout follows the real unit: pitch/mod wheels top left, 8 pads in
two rows of four (1-4 on the bottom row, 5-8 above), the display/encoder and
SHIFT / PLUGIN-DAW in the middle, 8 knobs in two rows of four on the right,
the button strip below, and 25 keys along the bottom.

Labels come from the preset actually loaded on the keyboard, and highlights
come from real incoming MIDI, so the thing that lights up is the thing you
touched.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import winmidi

# palette
BG = "#1d1f24"
PANEL = "#2b2e35"
EDGE = "#4a505c"
ACCENT = "#8a2530"
TEXT = "#ccd2db"
DIM = "#7d8695"
FAINT = "#5b6472"
KNOB = "#3b414b"
KNOB_HOT = "#4ea3ff"
PAD = "#33383f"
PAD_HOT = "#ff9f43"
BTN = "#343a43"
BTN_HOT = "#4ea3ff"
WHITE_KEY = "#e8eaee"
WHITE_HOT = "#4ea3ff"
BLACK_KEY = "#16181c"
BLACK_HOT = "#2d7fd6"
WHEEL = "#3b414b"
WHEEL_HOT = "#8e7bff"

CANVAS_W, CANVAS_H = 1000, 470
HOLD_MS = 260

BLACK_PCS = {1, 3, 6, 8, 10}
KEY_COUNT = 25

KNOB_ALT = ["DIVISION", "SWING", "MODE", "OCT", "LATCH", "SYNC", "GATE", "BPM"]
PAD_ALT_TOP = ["CHORDS", "CHORDS CONFIG", "SCALES", "SCALES CONFIG"]
PAD_ALT_BOT = ["", "PROG CHNG", "CC#", "NOTES"]

# (label, shift label) for the button strip. These are drawn for orientation;
# whatever they send is picked up live like any other control.
BTN_LEFT = [("OCT -", "PROG EDIT"), ("OCT +", "SAVE")]
BTN_MID = [("ARP", "CONFIG"), ("LATCH", "FULL LEVEL"), ("NOTE RPT", "CONFIG"),
           ("TAP TEMPO", "METRONOME"), ("BANK A/B", "")]
BTN_RIGHT = [("UNDO", "REDO"), ("LOOP", "GLOBAL"), ("STOP/PLAY", "CONTINUE"),
             ("REC", "QUANTIZE"), ("AUTO", "AUTOMATION")]


class DeviceView(ttk.Frame):
    def __init__(self, parent, on_pick=None, on_read=None):
        super().__init__(parent)
        self.on_pick = on_pick          # called with (trigger dict, label)
        self.on_read = on_read          # called when "Read from keyboard" hit
        self.preset = None
        self.pad_channel = 9            # globals byte 1 of the preset dump
        self.key_base = 48              # auto-corrects on the first key press
        self._timers = {}
        self._items = {}                # ("knob", 3) -> dict of canvas ids
        self._hit = None                # last touched control

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Read preset from keyboard",
                   command=self._read).pack(side="left")
        self.preset_lbl = tk.StringVar(value="Preset: not read yet")
        ttk.Label(bar, textvariable=self.preset_lbl).pack(side="left", padx=10)

        self.bank = tk.StringVar(value="A")
        ttk.Label(bar, text="Pad bank").pack(side="left", padx=(14, 4))
        bankbox = ttk.Combobox(bar, textvariable=self.bank, values=["A", "B"],
                               state="readonly", width=3)
        bankbox.pack(side="left")
        bankbox.bind("<<ComboboxSelected>>", lambda _e: self._relabel())

        self.canvas = tk.Canvas(self, width=CANVAS_W, height=CANVAS_H, bg=BG,
                                highlightthickness=0)
        # fixed height: the drawing has a fixed size, so letting it stretch
        # would just leave a black void under the keys
        self.canvas.pack(fill="x")
        self.canvas.bind("<Button-1>", self._click)

        foot = ttk.Frame(self)
        foot.pack(fill="x", pady=(6, 0))
        self.hit_lbl = tk.StringVar(
            value="Play something - the control you touch lights up.")
        ttk.Label(foot, textvariable=self.hit_lbl,
                  font=("Segoe UI", 10, "bold")).pack(side="left")
        self.pick_btn = ttk.Button(foot, text="Make a macro for this",
                                   command=self._pick, state="disabled")
        self.pick_btn.pack(side="right")

        self._draw()

    # -- drawing ------------------------------------------------------------

    def _draw(self):
        c = self.canvas
        c.create_rectangle(6, 6, CANVAS_W - 6, 300, fill=PANEL, outline=EDGE,
                           width=2)
        c.create_text(26, 22, text="AKAI", anchor="w", fill=TEXT,
                      font=("Segoe UI", 11, "bold"))
        c.create_text(26, 36, text="PROFESSIONAL", anchor="w", fill=FAINT,
                      font=("Segoe UI", 6))
        c.create_text(CANVAS_W - 20, 20,
                      text="click any control to build a macro for it",
                      anchor="e", fill=FAINT, font=("Segoe UI", 8))

        self._draw_wheels()
        self._draw_pads()
        self._draw_centre()
        self._draw_knobs()
        self._draw_buttons()

        self._draw_keys()

    def _draw_wheels(self):
        c = self.canvas
        for j, (name, kind) in enumerate((("PITCH", "pitch"), ("MOD", "mod"))):
            wx = 30 + j * 46
            c.create_rectangle(wx - 4, 46, wx + 36, 194, fill="#1a1c21",
                               outline=ACCENT)
            shape = c.create_rectangle(wx, 52, wx + 32, 188, fill=WHEEL,
                                       outline=EDGE, width=2)
            for gy in range(60, 185, 7):
                c.create_line(wx + 3, gy, wx + 29, gy, fill="#4d545f")
            label = c.create_text(wx + 16, 206, text=name, fill=TEXT,
                                  font=("Segoe UI", 7, "bold"))
            sub = c.create_text(wx + 16, 218, text="", fill=DIM,
                                font=("Segoe UI", 6))
            self._items[(kind, 0)] = {"shape": shape, "label": label,
                                      "sub": sub, "base": WHEEL,
                                      "hot": WHEEL_HOT}

    def _draw_pads(self):
        c = self.canvas
        pad_w, pad_h, gap = 96, 76, 10
        x0, y0 = 142, 46
        c.create_rectangle(x0 - 8, y0 - 8, x0 + 4 * pad_w + 3 * gap + 8,
                           y0 + 2 * pad_h + gap + 8, outline=ACCENT)
        for i in range(8):
            row, col = divmod(i, 4)          # row 0 = pads 1-4 = bottom row
            gx = x0 + col * (pad_w + gap)
            gy = y0 + (1 - row) * (pad_h + gap)
            shape = c.create_rectangle(gx, gy, gx + pad_w, gy + pad_h, fill=PAD,
                                       outline=EDGE, width=2)
            label = c.create_text(gx + pad_w / 2, gy + pad_h / 2 - 9,
                                  text=f"PAD {i + 1}", fill=TEXT,
                                  font=("Segoe UI", 10, "bold"))
            sub = c.create_text(gx + pad_w / 2, gy + pad_h / 2 + 10, text="--",
                                fill=DIM, font=("Segoe UI", 8))
            alt = PAD_ALT_TOP[col] if row == 1 else PAD_ALT_BOT[col]
            if alt:
                c.create_text(gx + pad_w / 2,
                              gy - 6 if row == 1 else gy + pad_h + 7,
                              text=alt, fill=FAINT, font=("Segoe UI", 6))
            self._items[("pad", i)] = {"shape": shape, "label": label,
                                       "sub": sub, "base": PAD, "hot": PAD_HOT}

    def _draw_centre(self):
        c = self.canvas
        cx = 600
        c.create_text(cx + 40, 26, text="MPK mini", fill=TEXT,
                      font=("Segoe UI", 12, "bold"))
        c.create_rectangle(cx, 40, cx + 116, 92, fill="#0e1116", outline=EDGE)
        self.screen_top = c.create_text(cx + 58, 52, text="-- no preset --",
                                        fill="#5fd0ff", font=("Consolas", 8))
        self.screen_mid = c.create_text(cx + 58, 70, text="", fill=TEXT,
                                        font=("Consolas", 8))
        c.create_oval(cx + 30, 100, cx + 86, 156, fill=KNOB, outline=ACCENT,
                      width=2)
        c.create_text(cx + 58, 168, text="< BANK >", fill=FAINT,
                      font=("Segoe UI", 6))
        for j, t in enumerate(("-", "+")):
            bx = cx + 8 + j * 58
            c.create_rectangle(bx, 176, bx + 50, 200, fill=BTN, outline=EDGE)
            c.create_text(bx + 25, 188, text=t, fill=TEXT,
                          font=("Segoe UI", 9, "bold"))
        for j, t in enumerate(("SHIFT", "PLUGIN/DAW")):
            bx = cx + 8 + j * 58
            c.create_rectangle(bx, 206, bx + 50, 232, fill=BTN, outline=EDGE)
            c.create_text(bx + 25, 219, text=t, fill=TEXT if j == 0 else "#d4707a",
                          font=("Segoe UI", 6, "bold"))
        c.create_text(cx + 58, 242, text="USER PRESETS", fill=FAINT,
                      font=("Segoe UI", 6))

    def _draw_knobs(self):
        c = self.canvas
        x0, y0 = 762, 84
        for i in range(8):
            row, col = divmod(i, 4)          # row 0 = knobs 1-4 = top row
            cx, cy, r = x0 + col * 62, y0 + row * 88, 24
            c.create_oval(cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3,
                          outline=ACCENT)
            ring = c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=KNOB,
                                 outline=EDGE, width=2)
            arc = c.create_arc(cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4,
                               start=225, extent=0, style="arc",
                               outline=KNOB_HOT, width=3)
            c.create_line(cx, cy, cx, cy - r + 6, fill=DIM, width=2)
            label = c.create_text(cx, cy + r + 11, text=f"K{i + 1}", fill=TEXT,
                                  font=("Segoe UI", 8, "bold"))
            sub = c.create_text(cx, cy + r + 23, text="CC --", fill=DIM,
                                font=("Segoe UI", 7))
            c.create_text(cx, cy + r + 34, text=KNOB_ALT[i], fill=FAINT,
                          font=("Segoe UI", 6))
            self._items[("knob", i)] = {"shape": ring, "arc": arc,
                                        "label": label, "sub": sub,
                                        "base": KNOB, "hot": KNOB_HOT}

    def _draw_buttons(self):
        c = self.canvas

        def strip(items, x, width):
            for j, (name, alt) in enumerate(items):
                bx = x + j * (width + 8)
                c.create_rectangle(bx, 246, bx + width, 274, fill=BTN,
                                   outline=EDGE)
                c.create_text(bx + width / 2, 257, text=name, fill=TEXT,
                              font=("Segoe UI", 7, "bold"))
                if alt:
                    c.create_text(bx + width / 2, 281, text=alt, fill=FAINT,
                                  font=("Segoe UI", 6))

        strip(BTN_LEFT, 26, 62)
        strip(BTN_MID, 176, 72)
        strip(BTN_RIGHT, 740, 42)

    def _draw_keys(self):
        c = self.canvas
        top, bot = 312, 456
        left, right = 20, CANVAS_W - 20
        whites = [i for i in range(KEY_COUNT)
                  if (self.key_base + i) % 12 not in BLACK_PCS]
        wide = (right - left) / max(1, len(whites))
        xs = {}
        wi = 0
        for i in range(KEY_COUNT):
            if (self.key_base + i) % 12 in BLACK_PCS:
                continue
            x = left + wi * wide
            xs[i] = x
            shape = c.create_rectangle(x, top, x + wide - 2, bot, fill=WHITE_KEY,
                                       outline="#9aa2ae")
            self._items[("key", i)] = {"shape": shape, "label": None,
                                       "sub": None, "base": WHITE_KEY,
                                       "hot": WHITE_HOT}
            wi += 1
        for i in range(KEY_COUNT):
            if (self.key_base + i) % 12 not in BLACK_PCS:
                continue
            prev = max((k for k in xs if k < i), default=None)
            if prev is None:
                continue
            x = xs[prev] + wide * 0.62
            shape = c.create_rectangle(x, top, x + wide * 0.62, top + 88,
                                       fill=BLACK_KEY, outline="#0a0c0e")
            self._items[("key", i)] = {"shape": shape, "label": None,
                                       "sub": None, "base": BLACK_KEY,
                                       "hot": BLACK_HOT}
        self._key_range_id = c.create_text(
            left + 4, top - 8,
            text=f"keys {winmidi.note_name(self.key_base)} - "
                 f"{winmidi.note_name(self.key_base + KEY_COUNT - 1)}"
                 "   (OCT -/+ shifts this)",
            anchor="w", fill=FAINT, font=("Segoe UI", 7))

    def _rebuild_keys(self):
        for i in range(KEY_COUNT):
            item = self._items.pop(("key", i), None)
            if item:
                self.canvas.delete(item["shape"])
        self.canvas.delete(self._key_range_id)
        self._draw_keys()

    # -- labels from the real preset ---------------------------------------

    def set_preset(self, preset):
        self.preset = preset
        if len(preset.globals_raw) > 1 and 0 <= preset.globals_raw[1] <= 15:
            self.pad_channel = preset.globals_raw[1]
        self.preset_lbl.set(
            f"Preset {preset.number}: {preset.name}   "
            f"(pads on ch {self.pad_channel + 1})"
        )
        self.canvas.itemconfig(self.screen_top,
                               text=f"{preset.number:02d} - {preset.name}"[:18])
        self.canvas.itemconfig(self.screen_mid, text=f"tempo {preset.tempo}")
        self._relabel()

    def _relabel(self):
        if not self.preset:
            return
        offset = 0 if self.bank.get() == "A" else 8
        for i in range(8):
            pad = self.preset.pads[i + offset]
            item = self._items[("pad", i)]
            self.canvas.itemconfig(item["label"],
                                   text=f"PAD {i + 1}{self.bank.get()}")
            self.canvas.itemconfig(
                item["sub"],
                text=f"{winmidi.note_name(pad['note'])} ({pad['note']})")
            item["note"] = pad["note"]
            item["cc"] = pad["cc"]
        for i in range(8):
            knob = self.preset.knobs[i]
            item = self._items[("knob", i)]
            name = knob["name"] or f"K{i + 1}"
            self.canvas.itemconfig(item["label"], text=name[:9])
            self.canvas.itemconfig(item["sub"], text=f"CC {knob['cc']}")
            item["cc"] = knob["cc"]

    def _read(self):
        if self.on_read:
            self.on_read()

    # -- live MIDI ----------------------------------------------------------

    def handle_midi(self, status, d1, d2):
        kind = status >> 4
        chan = status & 0x0F

        if kind == 0xE:
            self._flash(("pitch", 0),
                        f"Pitch wheel  {((d2 << 7) | d1) - 8192:+d}",
                        {"type": "pitchbend", "channel": chan,
                         "number": -1, "value": None})
            return
        if kind == 0xB:
            if d1 == 1:
                self._flash(("mod", 0), f"Mod wheel  CC1 = {d2}",
                            {"type": "cc", "channel": chan, "number": 1,
                             "value": None}, value=d2)
                return
            idx = self._knob_index(d1)
            trigger = {"type": "cc", "channel": chan, "number": d1, "value": None}
            if idx is not None:
                self._flash(("knob", idx), f"Knob {idx + 1}  CC{d1} = {d2}",
                            trigger, value=d2)
            else:
                # a button or something remapped -- still worth a macro
                self._note_hit(f"CC{d1} = {d2}  (a button, or a remapped control)",
                               trigger)
            return
        if kind == 0xC:
            self._note_hit(f"Program change {d1}",
                           {"type": "program", "channel": chan, "number": d1,
                            "value": None})
            return
        if kind == 0x9 and d2 > 0:
            idx = self._pad_index(d1, chan)
            if idx is not None:
                self._flash(("pad", idx),
                            f"Pad {idx + 1}{self.bank.get()}  "
                            f"{winmidi.note_name(d1)} ({d1})  vel {d2}",
                            {"type": "note_on", "channel": chan, "number": d1,
                             "value": None})
                return
            self._key_hit(d1, d2, chan)

    def _knob_index(self, cc):
        if self.preset:
            for i, k in enumerate(self.preset.knobs):
                if k["cc"] == cc:
                    return i
            return None
        return cc - 24 if 24 <= cc <= 31 else None   # factory default

    def _pad_index(self, note, chan):
        """Pads and keys can share note numbers, so the channel decides.

        The keyboard gives no MIDI indication of the selected bank -- pressing
        BANK A/B only recolours the button itself -- so the bank is inferred
        from which half of the pad table the note falls in, and the view
        follows along. Otherwise a bank B hit would light the right pad with
        the wrong label.
        """
        if chan != self.pad_channel:
            return None
        if self.preset:
            for i, pad in enumerate(self.preset.pads):
                if pad["note"] == note:
                    self._follow_bank("A" if i < 8 else "B")
                    return i % 8
            return None
        if 36 <= note <= 51:
            self._follow_bank("A" if note < 44 else "B")
            return (note - 36) % 8
        return None

    def _follow_bank(self, bank):
        if bank != self.bank.get():
            self.bank.set(bank)
            self._relabel()

    def _key_hit(self, note, vel, chan):
        if not (self.key_base <= note < self.key_base + KEY_COUNT):
            self.key_base = (note // 12) * 12
            self._rebuild_keys()
        idx = note - self.key_base
        if 0 <= idx < KEY_COUNT:
            self._flash(("key", idx),
                        f"Key {winmidi.note_name(note)} ({note})  vel {vel}",
                        {"type": "note_on", "channel": chan, "number": note,
                         "value": None})

    def _note_hit(self, text, trigger):
        self.hit_lbl.set(text)
        self._hit = trigger
        self.pick_btn.config(state="normal" if trigger else "disabled")

    def _flash(self, key, text, trigger, value=None):
        item = self._items.get(key)
        self._note_hit(text, trigger)
        if not item:
            return
        self.canvas.itemconfig(item["shape"], fill=item["hot"])
        if value is not None and "arc" in item:
            self.canvas.itemconfig(item["arc"], extent=-(value / 127.0) * 270)
        old = self._timers.pop(key, None)
        if old:
            self.after_cancel(old)
        self._timers[key] = self.after(
            HOLD_MS,
            lambda: self.canvas.itemconfig(item["shape"], fill=item["base"]),
        )

    # -- clicking -----------------------------------------------------------

    def _click(self, event):
        hits = self.canvas.find_overlapping(event.x, event.y, event.x, event.y)
        for key, item in self._items.items():
            if item["shape"] in hits:
                kind, idx = key
                trigger, text = self._trigger_for(kind, idx)
                if trigger:
                    self._note_hit(text, trigger)
                    self._pick()
                return

    def _trigger_for(self, kind, idx):
        if kind == "knob":
            cc = self._items[("knob", idx)].get("cc", 24 + idx)
            return ({"type": "cc", "channel": -1, "number": cc, "value": None},
                    f"Knob {idx + 1}  CC{cc}")
        if kind == "pad":
            note = self._items[("pad", idx)].get("note", 36 + idx)
            return ({"type": "note_on", "channel": -1, "number": note,
                     "value": None},
                    f"Pad {idx + 1}{self.bank.get()}  note {note}")
        if kind == "key":
            note = self.key_base + idx
            return ({"type": "note_on", "channel": -1, "number": note,
                     "value": None},
                    f"Key {winmidi.note_name(note)} ({note})")
        if kind == "mod":
            return ({"type": "cc", "channel": -1, "number": 1, "value": None},
                    "Mod wheel CC1")
        if kind == "pitch":
            return ({"type": "pitchbend", "channel": -1, "number": -1,
                     "value": None}, "Pitch wheel")
        return None, ""

    def _pick(self):
        if self._hit and self.on_pick:
            self.on_pick(self._hit, self.hit_lbl.get())
