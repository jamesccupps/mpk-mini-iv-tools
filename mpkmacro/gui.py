"""Tkinter front end for MPK Macro Studio."""
from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import device_view, mpk_preset
from . import engine as eng
from . import winmidi

PAD_HINT = "Pads are usually notes 36-51. Hit one with the Monitor tab open to be sure."

ACTION_FIELDS = {
    "keys": [("keys", "Keys (e.g. ctrl+shift+s)", "space")],
    "text": [("text", "Text to type", "")],
    "run": [("path", "Program or file", ""), ("args", "Arguments (optional)", "")],
    "wait": [("ms", "Milliseconds", "100")],
    "chord": [
        ("notes", "Notes, comma separated (60,64,67)", "60,64,67"),
        ("velocity", "Velocity 1-127", "100"),
        ("length_ms", "Hold for (ms)", "300"),
        ("channel", "MIDI channel 0-15", "0"),
        ("strum_ms", "Strum delay (ms, 0 = block chord)", "0"),
    ],
    "cc": [
        ("cc", "CC number", "74"),
        ("value", "Value 0-127, or 'passthru' to follow the knob", "64"),
        ("channel", "MIDI channel 0-15", "0"),
        ("min", "Min (passthru only)", "0"),
        ("max", "Max (passthru only)", "127"),
    ],
    "note": [
        ("note", "Note number", "60"),
        ("velocity", "Velocity 1-127", "100"),
        ("length_ms", "Hold for (ms)", "250"),
        ("channel", "MIDI channel 0-15", "0"),
    ],
    "program": [
        ("program", "Program number 0-127", "0"),
        ("channel", "MIDI channel 0-15", "0"),
    ],
}
INT_FIELDS = {"ms", "velocity", "length_ms", "channel", "strum_ms", "cc",
              "min", "max", "note", "program"}

ACTION_HELP = {
    "keys": "Press a keyboard shortcut in whatever app has focus.",
    "text": "Type a block of text.",
    "run": "Launch a program, file or folder.",
    "wait": "Pause before the next action in this macro.",
    "chord": "Play a chord out of the MIDI Out port (needs a virtual port -> DAW).",
    "cc": "Send a CC. Set value to 'passthru' to make one knob drive many params.",
    "note": "Send a single note out of the MIDI Out port.",
    "program": "Send a program change out of the MIDI Out port.",
}


def _center(win, parent):
    win.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(0, x)}+{max(0, y)}")


# ---------------------------------------------------------------------------
# Action editor
# ---------------------------------------------------------------------------

class ActionDialog(tk.Toplevel):
    def __init__(self, parent, action=None):
        super().__init__(parent)
        self.title("Action")
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self._vars = {}

        action = action or {"do": "keys", "keys": "space"}
        self.kind = tk.StringVar(value=action.get("do", "keys"))
        self._action = dict(action)

        top = ttk.Frame(self, padding=12)
        top.pack(fill="both", expand=True)

        ttk.Label(top, text="Do what?").grid(row=0, column=0, sticky="w")
        combo = ttk.Combobox(top, textvariable=self.kind, values=eng.ACTION_TYPES,
                             state="readonly", width=18)
        combo.grid(row=0, column=1, sticky="w", pady=(0, 4))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._rebuild())

        self.help = ttk.Label(top, text="", wraplength=380, foreground="#555")
        self.help.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.fields = ttk.Frame(top)
        self.fields.grid(row=2, column=0, columnspan=3, sticky="ew")

        btns = ttk.Frame(top)
        btns.grid(row=3, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="OK", command=self._ok).pack(side="right", padx=6)

        self._rebuild()
        _center(self, parent)
        self.grab_set()
        self.wait_window(self)

    def _rebuild(self):
        for child in self.fields.winfo_children():
            child.destroy()
        self._vars.clear()
        kind = self.kind.get()
        self.help.config(text=ACTION_HELP.get(kind, ""))
        for row, (key, label, default) in enumerate(ACTION_FIELDS.get(kind, [])):
            ttk.Label(self.fields, text=label).grid(
                row=row, column=0, sticky="w", pady=2
            )
            var = tk.StringVar(value=str(self._action.get(key, default)))
            self._vars[key] = var
            entry = ttk.Entry(self.fields, textvariable=var, width=34)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
            if key == "path":
                ttk.Button(
                    self.fields, text="...", width=3,
                    command=lambda v=var: self._browse(v),
                ).grid(row=row, column=2, padx=(4, 0))
        self.fields.columnconfigure(1, weight=1)

    def _browse(self, var):
        path = filedialog.askopenfilename(parent=self, title="Choose a program")
        if path:
            var.set(path)

    def _ok(self):
        action = {"do": self.kind.get()}
        for key, var in self._vars.items():
            raw = var.get().strip()
            if key == "notes":
                try:
                    action[key] = [int(p) for p in raw.replace(" ", "").split(",") if p]
                except ValueError:
                    messagebox.showerror("Bad notes", "Use numbers like 60,64,67",
                                         parent=self)
                    return
            elif key == "value" and raw.lower() == "passthru":
                action[key] = "passthru"
            elif key in INT_FIELDS or key == "value":
                try:
                    action[key] = int(raw or 0)
                except ValueError:
                    messagebox.showerror("Bad number", f"{key} must be a number",
                                         parent=self)
                    return
            else:
                action[key] = raw
        self.result = action
        self.destroy()


# ---------------------------------------------------------------------------
# Mapping editor
# ---------------------------------------------------------------------------

class MappingDialog(tk.Toplevel):
    def __init__(self, parent, app, mapping=None):
        super().__init__(parent)
        self.title("Macro")
        self.transient(parent)
        self.app = app
        self.result = None
        mapping = mapping or eng.default_mapping()
        self.mapping = {
            "id": mapping.get("id", eng.new_id()),
            "name": mapping.get("name", "New macro"),
            "enabled": mapping.get("enabled", True),
            "block": mapping.get("block", True),
            "trigger": dict(mapping.get("trigger", {})),
            "actions": [dict(a) for a in mapping.get("actions", [])],
        }

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="Name").grid(row=0, column=0, sticky="w")
        self.name = tk.StringVar(value=self.mapping["name"])
        ttk.Entry(root, textvariable=self.name, width=40).grid(
            row=0, column=1, columnspan=3, sticky="ew", pady=2
        )

        self.enabled = tk.BooleanVar(value=self.mapping["enabled"])
        self.block = tk.BooleanVar(value=self.mapping["block"])
        ttk.Checkbutton(root, text="Enabled", variable=self.enabled).grid(
            row=1, column=1, sticky="w"
        )
        ttk.Checkbutton(
            root, text="Swallow this message (don't pass it to the DAW)",
            variable=self.block,
        ).grid(row=1, column=2, columnspan=2, sticky="w")

        trig = ttk.LabelFrame(root, text="When this comes in", padding=10)
        trig.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 6))

        t = self.mapping["trigger"]
        self.t_type = tk.StringVar(value=t.get("type", "note_on"))
        self.t_chan = tk.StringVar(value=self._chan_label(t.get("channel", -1)))
        self.t_num = tk.StringVar(value=str(t.get("number", 36)))
        self.t_val = tk.StringVar(
            value="" if t.get("value") in (None, "", -1) else str(t.get("value"))
        )

        ttk.Label(trig, text="Type").grid(row=0, column=0, sticky="w")
        ttk.Combobox(trig, textvariable=self.t_type, values=eng.TRIGGER_TYPES,
                     state="readonly", width=12).grid(row=0, column=1, padx=4)
        ttk.Label(trig, text="Channel").grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Combobox(trig, textvariable=self.t_chan, state="readonly", width=6,
                     values=["Any"] + [str(i) for i in range(1, 17)]).grid(
            row=0, column=3, padx=4
        )
        ttk.Label(trig, text="Note / CC #").grid(row=1, column=0, sticky="w",
                                                 pady=(6, 0))
        ttk.Entry(trig, textvariable=self.t_num, width=8).grid(
            row=1, column=1, sticky="w", padx=4, pady=(6, 0)
        )
        ttk.Label(trig, text="Only if value =").grid(row=1, column=2, sticky="w",
                                                     padx=(10, 0), pady=(6, 0))
        ttk.Entry(trig, textvariable=self.t_val, width=8).grid(
            row=1, column=3, sticky="w", padx=4, pady=(6, 0)
        )
        self.learn_btn = ttk.Button(trig, text="MIDI Learn", command=self._learn)
        self.learn_btn.grid(row=0, column=4, rowspan=2, padx=(14, 0))
        ttk.Label(trig, text=PAD_HINT, foreground="#666").grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(8, 0)
        )

        acts = ttk.LabelFrame(root, text="Do this", padding=10)
        acts.grid(row=3, column=0, columnspan=4, sticky="nsew")
        self.actions = tk.Listbox(acts, height=7, activestyle="none")
        self.actions.grid(row=0, column=0, sticky="nsew")
        self.actions.bind("<Double-Button-1>", lambda _e: self._edit_action())
        bar = ttk.Frame(acts)
        bar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        for label, cmd in (
            ("Add", self._add_action), ("Edit", self._edit_action),
            ("Remove", self._remove_action), ("Up", lambda: self._move(-1)),
            ("Down", lambda: self._move(1)),
        ):
            ttk.Button(bar, text=label, width=8, command=cmd).pack(pady=2)
        acts.columnconfigure(0, weight=1)
        acts.rowconfigure(0, weight=1)

        btns = ttk.Frame(root)
        btns.grid(row=4, column=0, columnspan=4, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=self._ok).pack(side="right", padx=6)

        root.columnconfigure(1, weight=1)
        root.rowconfigure(3, weight=1)
        self._refresh_actions()
        _center(self, parent)
        self.grab_set()

    @staticmethod
    def _chan_label(ch):
        return "Any" if ch in (-1, None) else str(ch + 1)

    def _learn(self):
        if not self.app.engine.midi_in.is_open:
            messagebox.showwarning("Not connected",
                                   "Connect to the keyboard first.", parent=self)
            return
        self.learn_btn.config(text="Hit a pad/key...")
        self.app.start_learn(self._learned)

    def _learned(self, status, d1, d2):
        kind = eng._kind_of(status, d2) or "note_on"
        self.t_type.set(kind)
        self.t_chan.set(str((status & 0x0F) + 1))
        self.t_num.set(str(d1))
        self.learn_btn.config(text="MIDI Learn")

    def _refresh_actions(self):
        self.actions.delete(0, "end")
        for a in self.mapping["actions"]:
            self.actions.insert("end", "   " + eng.describe_actions([a]))

    def _sel(self):
        sel = self.actions.curselection()
        return sel[0] if sel else None

    def _add_action(self):
        dlg = ActionDialog(self, None)
        if dlg.result:
            self.mapping["actions"].append(dlg.result)
            self._refresh_actions()

    def _edit_action(self):
        i = self._sel()
        if i is None:
            return
        dlg = ActionDialog(self, self.mapping["actions"][i])
        if dlg.result:
            self.mapping["actions"][i] = dlg.result
            self._refresh_actions()

    def _remove_action(self):
        i = self._sel()
        if i is not None:
            del self.mapping["actions"][i]
            self._refresh_actions()

    def _move(self, delta):
        i = self._sel()
        if i is None:
            return
        j = i + delta
        acts = self.mapping["actions"]
        if 0 <= j < len(acts):
            acts[i], acts[j] = acts[j], acts[i]
            self._refresh_actions()
            self.actions.selection_set(j)

    def _ok(self):
        try:
            number = int(self.t_num.get())
        except ValueError:
            number = -1
        chan = self.t_chan.get()
        raw_val = self.t_val.get().strip()
        self.mapping.update({
            "name": self.name.get().strip() or "Untitled",
            "enabled": self.enabled.get(),
            "block": self.block.get(),
            "trigger": {
                "type": self.t_type.get(),
                "channel": -1 if chan == "Any" else int(chan) - 1,
                "number": number,
                "value": int(raw_val) if raw_val.isdigit() else None,
            },
        })
        self.result = self.mapping
        self.destroy()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MPK Macro Studio")
        self.geometry("1060x680")
        self.minsize(1000, 640)

        self.ui_queue = queue.SimpleQueue()
        self.engine = eng.Engine(log=self._log_threadsafe)
        self.engine.monitor_callback = self._monitor_threadsafe
        self.engine.sysex_callback = self._sysex_threadsafe
        self.settings = eng.load_settings()
        self.monitor_paused = tk.BooleanVar(value=False)

        self._build_toolbar()
        self._build_tabs()
        self._build_status()

        self.profiles = eng.load_profiles()
        if not self.profiles:
            prof = eng.Profile({"name": "My Macros", "match_app": "", "mappings": []})
            prof.save(eng.PROFILE_DIR / "My Macros.json")
            self.profiles = [prof]
        self.engine.set_profiles(self.profiles)
        self._refresh_profiles()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(40, self._drain_ui)
        self._auto_connect()

    # -- layout -------------------------------------------------------------

    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")

        ttk.Label(bar, text="Keyboard").pack(side="left")
        self.in_var = tk.StringVar()
        self.in_combo = ttk.Combobox(bar, textvariable=self.in_var, width=26,
                                     state="readonly")
        self.in_combo.pack(side="left", padx=(6, 12))
        self.in_combo.bind("<<ComboboxSelected>>",
                           lambda _e: self._refresh_devices())

        ttk.Label(bar, text="Send MIDI to").pack(side="left")
        self.out_var = tk.StringVar()
        self.out_combo = ttk.Combobox(bar, textvariable=self.out_var, width=26,
                                      state="readonly")
        self.out_combo.pack(side="left", padx=(6, 12))

        ttk.Button(bar, text="Refresh", command=self._refresh_devices).pack(side="left")
        self.connect_btn = ttk.Button(bar, text="Connect", command=self._toggle)
        self.connect_btn.pack(side="left", padx=6)

        self.armed = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Macros armed", variable=self.armed,
                        command=self._sync_flags).pack(side="left", padx=(14, 0))

        self.thru_var = tk.StringVar(value=eng.PASSTHRU_UNMAPPED)
        ttk.Label(bar, text="Pass through").pack(side="left", padx=(14, 4))
        ttk.Combobox(bar, textvariable=self.thru_var, width=10, state="readonly",
                     values=[eng.PASSTHRU_OFF, eng.PASSTHRU_UNMAPPED,
                             eng.PASSTHRU_ALL]).pack(side="left")
        self.thru_var.trace_add("write", lambda *_: self._sync_flags())

        self._refresh_devices()

    def _build_tabs(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # --- device ---
        devtab = ttk.Frame(nb, padding=8)
        nb.add(devtab, text="Device")
        self.device = device_view.DeviceView(
            devtab, on_pick=self._macro_for, on_read=self._read_preset
        )
        self.device.pack(fill="both", expand=True)

        # --- macros ---
        macros = ttk.Frame(nb, padding=10)
        nb.add(macros, text="Macros")

        top = ttk.Frame(macros)
        top.pack(fill="x")
        ttk.Label(top, text="Profile").pack(side="left")
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(top, textvariable=self.profile_var,
                                          state="readonly", width=24)
        self.profile_combo.pack(side="left", padx=6)
        self.profile_combo.bind("<<ComboboxSelected>>",
                                lambda _e: self._select_profile())
        ttk.Button(top, text="New", command=self._new_profile).pack(side="left")
        ttk.Button(top, text="Delete", command=self._delete_profile).pack(
            side="left", padx=4)

        ttk.Label(top, text="Auto-switch when app is").pack(side="left", padx=(18, 4))
        self.app_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.app_var, width=22).pack(side="left")
        ttk.Button(top, text="Use focused app",
                   command=self._grab_app).pack(side="left", padx=4)
        ttk.Button(top, text="Save", command=self._save_profile).pack(side="left")

        cols = ("name", "trigger", "actions")
        self.tree = ttk.Treeview(macros, columns=cols, show="headings", height=14)
        for col, text, width in (("name", "Macro", 200),
                                 ("trigger", "Trigger", 250),
                                 ("actions", "Does", 420)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(10, 6))
        self.tree.bind("<Double-Button-1>", lambda _e: self._edit_mapping())

        row = ttk.Frame(macros)
        row.pack(fill="x")
        for label, cmd in (("Add macro", self._add_mapping),
                           ("Edit", self._edit_mapping),
                           ("Duplicate", self._dup_mapping),
                           ("Enable / disable", self._toggle_mapping),
                           ("Delete", self._del_mapping)):
            ttk.Button(row, text=label, command=cmd).pack(side="left", padx=(0, 6))

        # --- monitor ---
        mon = ttk.Frame(nb, padding=10)
        nb.add(mon, text="MIDI Monitor")
        ttk.Label(
            mon,
            text="Everything the keyboard sends. Use this to find out what a pad, "
                 "key or knob actually is.",
        ).pack(anchor="w")
        self.monitor = tk.Text(mon, height=20, font=("Consolas", 10), wrap="none")
        self.monitor.pack(fill="both", expand=True, pady=8)
        mrow = ttk.Frame(mon)
        mrow.pack(fill="x")
        ttk.Checkbutton(mrow, text="Pause", variable=self.monitor_paused).pack(
            side="left")
        ttk.Button(mrow, text="Clear",
                   command=lambda: self.monitor.delete("1.0", "end")).pack(
            side="left", padx=6)

        # --- sysex ---
        sx = ttk.Frame(nb, padding=10)
        nb.add(sx, text="SysEx Lab")
        ttk.Label(
            sx,
            text="Talk to the keyboard directly. Product ID 0x5D = MPK mini IV.\n"
                 "Read a preset:  F0 47 00 5D 66 00 01 <preset 00-0D> F7",
            justify="left",
        ).pack(anchor="w")
        erow = ttk.Frame(sx)
        erow.pack(fill="x", pady=8)
        self.sysex_var = tk.StringVar(value="F0 47 00 5D 66 00 01 00 F7")
        ttk.Entry(erow, textvariable=self.sysex_var, font=("Consolas", 10)).pack(
            side="left", fill="x", expand=True)
        ttk.Button(erow, text="Send", command=self._send_sysex).pack(
            side="left", padx=6)
        ttk.Button(erow, text="Identity", command=self._identity).pack(side="left")
        self.sysex_log = tk.Text(sx, height=18, font=("Consolas", 9), wrap="word")
        self.sysex_log.pack(fill="both", expand=True)
        ttk.Button(sx, text="Save log to file", command=self._save_sysex).pack(
            anchor="w", pady=(6, 0))

        # --- help ---
        helptab = ttk.Frame(nb, padding=14)
        nb.add(helptab, text="Help")
        txt = tk.Text(helptab, wrap="word", font=("Segoe UI", 10), relief="flat")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", HELP_TEXT)
        txt.config(state="disabled")

    def _build_status(self):
        self.status = tk.StringVar(value="Ready")
        bar = ttk.Frame(self, padding=(10, 4))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.status, foreground="#333").pack(side="left")

    # -- devices ------------------------------------------------------------

    def _refresh_devices(self):
        self.inputs = winmidi.input_devices()
        self.outputs = winmidi.output_devices()
        self.in_combo["values"] = self.inputs
        # The keyboard's own outputs are deliberately absent from this list:
        # sending its MIDI back to it is a feedback loop. SysEx still reaches
        # it through the engine's dedicated device port.
        self.out_combo["values"] = ["(none)"] + [
            n for n in self.outputs
            if not winmidi.same_device(n, self.in_var.get())
        ]
        if winmidi.same_device(self.out_var.get(), self.in_var.get()):
            self.out_var.set("(none)")
        if not self.in_var.get():
            idx = winmidi.find_device(self.inputs, "MPK mini")
            if idx is not None:
                self.in_var.set(self.inputs[idx])
            elif self.inputs:
                self.in_var.set(self.inputs[0])
        if not self.out_var.get():
            idx = winmidi.find_device(self.outputs, "loopMIDI")
            self.out_var.set(self.outputs[idx] if idx is not None else "(none)")

    def _auto_connect(self):
        saved_in = self.settings.get("input")
        if saved_in in self.inputs:
            self.in_var.set(saved_in)
        saved_out = self.settings.get("output")
        if saved_out in self.outputs:
            self.out_var.set(saved_out)
        if self.in_var.get():
            self._toggle()

    def _toggle(self):
        if self.engine.midi_in.is_open:
            self.engine.stop()
            self.connect_btn.config(text="Connect")
            self.status.set("Disconnected")
            return
        name = self.in_var.get()
        if name not in self.inputs:
            messagebox.showwarning("No keyboard", "Pick a MIDI input first.")
            return
        out_name = self.out_var.get()
        out_idx = self.outputs.index(out_name) if out_name in self.outputs else None
        try:
            self.engine.start(self.inputs.index(name), out_idx, out_idx)
        except winmidi.MidiError as exc:
            messagebox.showerror("Could not open MIDI", str(exc))
            return
        self._sync_flags()
        self.connect_btn.config(text="Disconnect")
        eng.save_settings({"input": name, "output": out_name})
        # Deliberately does NOT auto-request a preset dump. Connecting should
        # never send anything to the keyboard -- use "Read preset from
        # keyboard" on the Device tab when you actually want it.

    def _sync_flags(self):
        self.engine.armed = self.armed.get()
        self.engine.passthrough = self.thru_var.get()

    # -- profiles -----------------------------------------------------------

    def _refresh_profiles(self):
        names = [p.name for p in self.profiles]
        self.profile_combo["values"] = names
        if self.engine.active_profile and self.engine.active_profile.name in names:
            self.profile_var.set(self.engine.active_profile.name)
        elif names:
            self.profile_var.set(names[0])
        self._select_profile()

    def _current_profile(self):
        name = self.profile_var.get()
        for p in self.profiles:
            if p.name == name:
                return p
        return self.profiles[0] if self.profiles else None

    def _select_profile(self):
        prof = self._current_profile()
        if not prof:
            return
        self.engine.active_profile = prof
        self.app_var.set(prof.match_app)
        self._refresh_tree()

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        prof = self._current_profile()
        if not prof:
            return
        for m in prof.mappings:
            mark = "" if m.get("enabled", True) else "  (off)"
            self.tree.insert("", "end", iid=m["id"], values=(
                m.get("name", "") + mark,
                eng.describe_trigger(m.get("trigger", {})),
                eng.describe_actions(m.get("actions", [])),
            ))

    def _new_profile(self):
        dlg = tk.Toplevel(self)
        dlg.title("New profile")
        dlg.transient(self)
        var = tk.StringVar(value="New profile")
        ttk.Label(dlg, text="Name", padding=10).pack()
        ttk.Entry(dlg, textvariable=var, width=30).pack(padx=12)

        def ok():
            name = var.get().strip() or "New profile"
            prof = eng.Profile({"name": name, "match_app": "", "mappings": []})
            prof.save(eng.PROFILE_DIR / f"{name}.json")
            self.profiles.append(prof)
            self.engine.set_profiles(self.profiles, prof)
            self.profile_var.set(name)
            self._refresh_profiles()
            dlg.destroy()

        ttk.Button(dlg, text="Create", command=ok).pack(pady=10)
        _center(dlg, self)
        dlg.grab_set()

    def _delete_profile(self):
        prof = self._current_profile()
        if not prof or len(self.profiles) == 1:
            messagebox.showinfo("Keep one", "You need at least one profile.")
            return
        if not messagebox.askyesno("Delete profile", f"Delete '{prof.name}'?"):
            return
        if prof.path and Path(prof.path).exists():
            Path(prof.path).unlink()
        self.profiles.remove(prof)
        self.engine.set_profiles(self.profiles, self.profiles[0])
        self._refresh_profiles()

    def _grab_app(self):
        from . import winput
        self.after(1500, lambda: self.app_var.set(winput.foreground_exe()))
        self.status.set("Click your DAW within 1.5 seconds...")

    def _save_profile(self):
        prof = self._current_profile()
        if not prof:
            return
        prof.match_app = self.app_var.get().strip()
        prof.save(prof.path or (eng.PROFILE_DIR / f"{prof.name}.json"))
        self.status.set(f"Saved {prof.name}")

    # -- mappings -----------------------------------------------------------

    def _selected_mapping(self):
        sel = self.tree.selection()
        if not sel:
            return None
        prof = self._current_profile()
        for m in prof.mappings:
            if m["id"] == sel[0]:
                return m
        return None

    def _add_mapping(self):
        dlg = MappingDialog(self, self)
        self.wait_window(dlg)
        if dlg.result:
            self._current_profile().mappings.append(dlg.result)
            self._save_profile()
            self._refresh_tree()

    def _edit_mapping(self):
        m = self._selected_mapping()
        if not m:
            return
        dlg = MappingDialog(self, self, m)
        self.wait_window(dlg)
        if dlg.result:
            prof = self._current_profile()
            for i, existing in enumerate(prof.mappings):
                if existing["id"] == dlg.result["id"]:
                    prof.mappings[i] = dlg.result
                    break
            self._save_profile()
            self._refresh_tree()

    def _dup_mapping(self):
        m = self._selected_mapping()
        if not m:
            return
        copy = {**m, "id": eng.new_id(), "name": m.get("name", "") + " copy"}
        self._current_profile().mappings.append(copy)
        self._save_profile()
        self._refresh_tree()

    def _toggle_mapping(self):
        m = self._selected_mapping()
        if not m:
            return
        m["enabled"] = not m.get("enabled", True)
        self._save_profile()
        self._refresh_tree()

    def _del_mapping(self):
        m = self._selected_mapping()
        if not m:
            return
        prof = self._current_profile()
        prof.mappings = [x for x in prof.mappings if x["id"] != m["id"]]
        self._save_profile()
        self._refresh_tree()

    # -- learn / sysex ------------------------------------------------------

    def start_learn(self, callback):
        def wrapped(status, d1, d2):
            self.ui_queue.put(("learn", (callback, status, d1, d2)))
        self.engine.learn_callback = wrapped

    def _read_preset(self):
        """Ask the keyboard for the preset it currently has loaded."""
        if not self.engine.device_out.is_open:
            messagebox.showwarning(
                "Keyboard not connected",
                "Press Connect first so the app can talk to the keyboard.")
            return
        self.engine.device_out.send_sysex(mpk_preset.request(0))
        self.status.set("Asked the keyboard for its current preset...")

    def _macro_for(self, trigger, label):
        """Called when a control is clicked on the device picture."""
        mapping = eng.default_mapping()
        mapping["trigger"] = dict(trigger)
        mapping["name"] = label
        dlg = MappingDialog(self, self, mapping)
        self.wait_window(dlg)
        if dlg.result:
            self._current_profile().mappings.append(dlg.result)
            self._save_profile()
            self._refresh_tree()

    def _send_sysex(self):
        if not self.engine.device_out.is_open:
            messagebox.showwarning(
                "Keyboard not connected", "Press Connect first.")
            return
        try:
            data = [int(b, 16) for b in self.sysex_var.get().split()]
        except ValueError:
            messagebox.showerror("Bad hex", "Use hex bytes like: F0 47 00 5D ... F7")
            return
        self.engine.device_out.send_sysex(data)
        self._append_sysex(f"==> {winmidi.hexdump(data)}\n")

    def _identity(self):
        self.sysex_var.set("F0 7E 7F 06 01 F7")
        self._send_sysex()

    def _save_sysex(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            title="Save SysEx log")
        if path:
            Path(path).write_text(self.sysex_log.get("1.0", "end"), encoding="utf-8")
            self.status.set(f"Saved {path}")

    def _append_sysex(self, text):
        self.sysex_log.insert("end", text)
        self.sysex_log.see("end")

    # -- thread marshalling -------------------------------------------------

    def _log_threadsafe(self, msg, kind="info"):
        self.ui_queue.put(("log", (msg, kind)))

    def _monitor_threadsafe(self, status, d1, d2):
        self.ui_queue.put(("midi", (status, d1, d2)))

    def _sysex_threadsafe(self, data):
        self.ui_queue.put(("sysex", data))

    def _drain_ui(self):
        for _ in range(200):
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                msg, _level = payload
                self.status.set(msg.strip().splitlines()[-1][:160])
            elif kind == "midi":
                self.device.handle_midi(*payload)
                if not self.monitor_paused.get():
                    self.monitor.insert("end", winmidi.describe(*payload) + "\n")
                    if float(self.monitor.index("end")) > 500:
                        self.monitor.delete("1.0", "100.0")
                    self.monitor.see("end")
            elif kind == "sysex":
                self._append_sysex(
                    f"<== {len(payload)} bytes\n    {winmidi.hexdump(payload)}\n")
                try:
                    preset = mpk_preset.parse(payload)
                except ValueError:
                    pass
                else:
                    self.device.set_preset(preset)
                    self.status.set(
                        f"Read preset {preset.number}: {preset.name}")
            elif kind == "learn":
                cb, status, d1, d2 = payload
                cb(status, d1, d2)
        self.after(40, self._drain_ui)

    def _on_close(self):
        try:
            self.engine.stop()
        finally:
            self.destroy()


HELP_TEXT = """MPK Macro Studio - turn your MPK mini IV into a macro controller.

WHAT THIS DOES
  Your MPK mini IV already edits itself (SHIFT + PROG EDIT on the keyboard) for
  notes, CCs and channels. What it cannot do is press keys on your computer.
  That is what this adds: any pad, key or knob can fire a keyboard shortcut,
  type text, launch a program, or play a chord.

GETTING STARTED
  1. Pick your keyboard under "Keyboard" and press Connect.
  2. Open the MIDI Monitor tab and hit a pad. Note the number it shows.
  3. Go to Macros, press "Add macro", then "MIDI Learn" and hit that pad again.
  4. Add an action, e.g. keys = "space" for play/stop. Save.
  5. Focus your DAW and hit the pad.

PASSING NOTES THROUGH TO A DAW
  Macros that "swallow" a message stop it reaching the DAW. If you want the
  keyboard to still play notes while macros work, install loopMIDI (free),
  create a port, choose it under "Send MIDI to", and point your DAW at that
  port instead of the MPK directly. Chord and CC actions also need this.

MACRO KNOBS
  Add a CC trigger on a knob, then several CC actions with value = passthru.
  One knob now moves several parameters at once, each with its own min/max.

PROFILES
  One profile per app. Put the exe name in "Auto-switch when app is"
  (e.g. Ableton Live 12 Suite.exe) and the profile follows your focus.

KEY NAMES
  ctrl alt shift win, plus f1-f24, space, enter, tab, esc, backspace, delete,
  insert, home, end, pageup, pagedown, left, right, up, down, num0-num9,
  mediaplay, medianext, mediaprev, volumeup, volumedown, volumemute.
  Combine with +, e.g.  ctrl+shift+s
"""


def main():
    app = App()
    app.mainloop()
