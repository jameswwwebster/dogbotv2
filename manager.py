import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta

COMMANDS_FILE      = os.path.join(os.path.dirname(__file__), "commands.json")
REMINDERS_FILE     = os.path.join(os.path.dirname(__file__), "reminders.json")
QUESTIONS_FILE     = os.path.join(os.path.dirname(__file__), "questions.json")
FEATURES_FILE      = os.path.join(os.path.dirname(__file__), "features.json")
PUSH_MESSAGES_FILE = os.path.join(os.path.dirname(__file__), "push_messages.json")
GIVEAWAYS_FILE     = os.path.join(os.path.dirname(__file__), "giveaways.json")

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

BG       = "#2b2d31"
BG_CARD  = "#313338"
BG_INPUT = "#1e1f22"
FG       = "white"
FG_DIM   = "#b5bac1"
ACCENT   = "#5865f2"
RED      = "#ed4245"
GREY     = "#4f545c"
GREEN    = "#3ba55d"
GOLD     = "#f0b232"


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_commands():
    if not os.path.exists(COMMANDS_FILE): return {}
    with open(COMMANDS_FILE) as f: data = json.load(f)
    # Migrate old plain-string format {"cmd": "response"} → {"cmd": {"response": ..., "mod_only": false}}
    return {cmd: (val if isinstance(val, dict) else {"response": val, "mod_only": False})
            for cmd, val in data.items()}

def save_commands(d):
    with open(COMMANDS_FILE, "w") as f: json.dump(d, f, indent=4)

def load_reminders():
    if not os.path.exists(REMINDERS_FILE): return []
    with open(REMINDERS_FILE) as f: return json.load(f)

def save_reminders(d):
    with open(REMINDERS_FILE, "w") as f: json.dump(d, f, indent=4)

def load_questions():
    if not os.path.exists(QUESTIONS_FILE): return {"command": "", "questions": []}
    with open(QUESTIONS_FILE) as f: return json.load(f)

def save_questions(d):
    with open(QUESTIONS_FILE, "w") as f: json.dump(d, f, indent=4)

def load_features():
    defaults = {"gmt_offset": 0, "rng_enabled": False}
    if not os.path.exists(FEATURES_FILE): return defaults
    with open(FEATURES_FILE) as f: data = json.load(f)
    for k, v in defaults.items(): data.setdefault(k, v)
    return data

def save_features(d):
    with open(FEATURES_FILE, "w") as f: json.dump(d, f, indent=4)

def load_push_messages():
    if not os.path.exists(PUSH_MESSAGES_FILE): return []
    with open(PUSH_MESSAGES_FILE) as f: return json.load(f)

def save_push_messages(d):
    with open(PUSH_MESSAGES_FILE, "w") as f: json.dump(d, f, indent=4)

def load_giveaways():
    if not os.path.exists(GIVEAWAYS_FILE): return []
    with open(GIVEAWAYS_FILE) as f: return json.load(f)

def save_giveaways(d):
    with open(GIVEAWAYS_FILE, "w") as f: json.dump(d, f, indent=4)


# ── Widget helpers ─────────────────────────────────────────────────────────────

def lbl(parent, text, large=False, dim=False, **kw):
    return tk.Label(parent, text=text, bg=BG,
                    fg=FG_DIM if dim else FG,
                    font=("Segoe UI", 13 if large else 10,
                          "bold" if large else "normal"),
                    anchor="center", **kw)

def inp(parent, var, **kw):
    return tk.Entry(parent, textvariable=var, bg=BG_INPUT, fg=FG,
                    insertbackground=FG, relief="flat",
                    font=("Consolas", 11), **kw)

def btn(parent, text, color, cmd, **kw):
    return tk.Button(parent, text=text, bg=color, fg=FG,
                     font=("Segoe UI", 10, "bold"), relief="flat",
                     cursor="hand2", pady=6, command=cmd, **kw)

def scrolled_lb(parent, width, height):
    f  = tk.Frame(parent, bg=BG)
    lb = tk.Listbox(f, width=width, height=height,
                    bg=BG_INPUT, fg=FG, selectbackground=ACCENT,
                    font=("Consolas", 11), activestyle="none", relief="flat")
    sb = ttk.Scrollbar(f, orient="vertical", command=lb.yview)
    lb.config(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return f, lb

def section(parent, title, subtitle=None):
    """Centered section header with optional subtitle."""
    lbl(parent, title, large=True).pack(fill="x", pady=(12, 2))
    if subtitle:
        lbl(parent, subtitle, dim=True).pack(fill="x", pady=(0, 8))

def field_row(parent, labels, weights):
    """Returns a frame configured as a centered field row."""
    row = tk.Frame(parent, bg=BG)
    row.pack(padx=20, pady=(6, 2), fill="x")
    for i, w in enumerate(weights):
        row.columnconfigure(i, weight=w)
    for i, text in enumerate(labels):
        tk.Label(row, text=text, bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 10), anchor="center"
                 ).grid(row=0, column=i, pady=(0, 2), sticky="ew")
    return row


# ── App ────────────────────────────────────────────────────────────────────────

class ManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🐾 DogBot — Dashboard")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._build_ui()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_CARD, foreground=FG,
                        padding=[12, 6], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        for name, builder in [
            ("💬 Commands",     self._build_commands_tab),
            ("⏰ Reminders",    self._build_reminders_tab),
            ("❓ Questions",    self._build_questions_tab),
            ("📢 Push Message", self._build_push_tab),
            ("🎮 Fun Features", self._build_features_tab),
            ("🎉 Giveaway",     self._build_giveaway_tab),
            ("🔧 Utility",      self._build_utility_tab),
        ]:
            f = tk.Frame(nb, bg=BG)
            nb.add(f, text=name)
            builder(f)

        btn(self, "Save & Deploy to GitHub", GREEN, self.deploy).pack(
            fill="x", padx=12, pady=(0, 6))
        self._status = tk.Label(self, text="", bg=BG, fg=FG_DIM, font=("Segoe UI", 9))
        self._status.pack(pady=(0, 8))

    # ── Commands ──────────────────────────────────────────────────────────────

    def _build_commands_tab(self, p):
        section(p, "Custom Commands", "Add a command and the bot's response.")

        lf, self._cmd_lb = scrolled_lb(p, 52, 9)
        lf.pack(padx=20, fill="x")
        self._cmd_lb.bind("<<ListboxSelect>>", self._on_cmd_sel)

        row = field_row(p, ["!command", "Response"], [1, 3])
        self._cmd_var  = tk.StringVar()
        self._resp_var = tk.StringVar()
        inp(row, self._cmd_var ).grid(row=1, column=0, padx=(0, 4), sticky="ew")
        inp(row, self._resp_var).grid(row=1, column=1, padx=(4, 0), sticky="ew")

        mf = tk.Frame(p, bg=BG)
        mf.pack(padx=20, pady=(4, 0), fill="x")
        self._mod_only_var = tk.BooleanVar()
        tk.Checkbutton(mf, text="Mod only", variable=self._mod_only_var,
                       bg=BG, fg=FG_DIM, selectcolor=BG_INPUT,
                       activebackground=BG, font=("Segoe UI", 9)
                       ).pack(side="left")

        bf = tk.Frame(p, bg=BG)
        bf.pack(padx=20, pady=(4, 8), fill="x")
        btn(bf, "Add / Update", ACCENT, self._add_cmd ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        btn(bf, "Delete",       RED,   self._del_cmd ).pack(side="left", expand=True, fill="x", padx=(4, 4))
        btn(bf, "Clear",        GREY,  self._clear_cmd).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self._refresh_cmds()

    def _refresh_cmds(self):
        self._cmd_lb.delete(0, "end")
        self.__cmds = load_commands()
        for cmd, entry in self.__cmds.items():
            tag = "[mod]" if entry.get("mod_only") else "[pub]"
            self._cmd_lb.insert("end", f"!{cmd:<18} {tag}  {entry['response']}")

    def _on_cmd_sel(self, _=None):
        sel = self._cmd_lb.curselection()
        if not sel: return
        cmd   = list(self.__cmds.keys())[sel[0]]
        entry = self.__cmds[cmd]
        self._cmd_var.set(cmd)
        self._resp_var.set(entry["response"])
        self._mod_only_var.set(entry.get("mod_only", False))

    def _add_cmd(self):
        cmd  = self._cmd_var.get().strip().lstrip("!").lower()
        resp = self._resp_var.get().strip()
        if not cmd or not resp:
            messagebox.showwarning("Missing input", "Fill in both fields.")
            return
        d = load_commands()
        d[cmd] = {"response": resp, "mod_only": self._mod_only_var.get()}
        save_commands(d)
        self._refresh_cmds(); self._clear_cmd()
        self.set_status(f'Saved "!{cmd}"')

    def _del_cmd(self):
        cmd = self._cmd_var.get().strip().lstrip("!").lower()
        if not cmd:
            messagebox.showwarning("No selection", "Select a command first."); return
        d = load_commands()
        if cmd not in d:
            messagebox.showwarning("Not found", f'"!{cmd}" does not exist.'); return
        if not messagebox.askyesno("Confirm", f'Delete "!{cmd}"?'): return
        del d[cmd]; save_commands(d)
        self._refresh_cmds(); self._clear_cmd()
        self.set_status(f'Deleted "!{cmd}"')

    def _clear_cmd(self):
        self._cmd_var.set(""); self._resp_var.set("")
        self._mod_only_var.set(False)
        self._cmd_lb.selection_clear(0, "end")

    # ── Reminders ─────────────────────────────────────────────────────────────

    def _build_reminders_tab(self, p):
        section(p, "Scheduled Reminders", "Enter times in your local timezone.")

        # Clock row
        cr = tk.Frame(p, bg=BG)
        cr.pack(pady=(0, 8))

        self._clock_lbl = tk.Label(cr, text="", bg=BG, fg=GOLD,
                                   font=("Segoe UI", 11, "bold"))
        self._clock_lbl.pack(side="left", padx=(0, 16))

        tk.Label(cr, text="Offset:", bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 10)).pack(side="left")

        self._offset_var = tk.StringVar(value=str(load_features().get("gmt_offset", 0)))
        cb = ttk.Combobox(cr, textvariable=self._offset_var,
                          values=["0", "1", "2"], width=4, state="readonly",
                          font=("Segoe UI", 10))
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", self._save_offset)

        tk.Label(cr, text="(0 = GMT   1 = CET/BST   2 = CEST)", bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))
        self._tick()

        lf, self._rem_lb = scrolled_lb(p, 58, 7)
        lf.pack(padx=20, fill="x")
        self._rem_lb.bind("<<ListboxSelect>>", self._on_rem_sel)

        row = field_row(p, ["Day", "Time (HH:MM)", "Channel ID", "Message"], [1, 1, 2, 3])
        self._rem_day  = tk.StringVar(value="Wednesday")
        self._rem_time = tk.StringVar(value="12:00")
        self._rem_ch   = tk.StringVar()
        self._rem_msg  = tk.StringVar()

        ttk.Combobox(row, textvariable=self._rem_day, values=DAYS,
                     state="readonly", font=("Segoe UI", 10)
                     ).grid(row=1, column=0, padx=2, sticky="ew")
        inp(row, self._rem_time).grid(row=1, column=1, padx=2, sticky="ew")
        inp(row, self._rem_ch  ).grid(row=1, column=2, padx=2, sticky="ew")
        inp(row, self._rem_msg ).grid(row=1, column=3, padx=2, sticky="ew")

        bf = tk.Frame(p, bg=BG)
        bf.pack(padx=20, pady=8, fill="x")
        btn(bf, "Add / Update", ACCENT, self._add_rem ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        btn(bf, "Delete",       RED,   self._del_rem ).pack(side="left", expand=True, fill="x", padx=(4, 4))
        btn(bf, "Clear",        GREY,  self._clear_rem).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self._refresh_rems()

    def _tick(self):
        try:    offset = int(self._offset_var.get())
        except: offset = 0
        now  = datetime.now(timezone.utc) + timedelta(hours=offset)
        sign = f"+{offset}" if offset >= 0 else str(offset)
        self._clock_lbl.config(text=f"🕐  {now.strftime('%H:%M:%S')}  UTC{sign}")
        self.after(1000, self._tick)

    def _save_offset(self, *_):
        try:    offset = int(self._offset_var.get())
        except: return
        d = load_features(); d["gmt_offset"] = offset; save_features(d)

    def _refresh_rems(self):
        self._rem_lb.delete(0, "end")
        self.__rems = load_reminders()
        for r in self.__rems:
            self._rem_lb.insert("end",
                f"{DAYS[r['day']]:<12} {r['time']}  #{r['channel_id']}  {r['message']}")

    def _on_rem_sel(self, _=None):
        sel = self._rem_lb.curselection()
        if not sel: return
        r = self.__rems[sel[0]]
        self._rem_day.set(DAYS[r["day"]]); self._rem_time.set(r["time"])
        self._rem_ch.set(str(r["channel_id"])); self._rem_msg.set(r["message"])

    def _add_rem(self):
        day = self._rem_day.get(); time = self._rem_time.get().strip()
        ch  = self._rem_ch.get().strip(); msg = self._rem_msg.get().strip()
        if not all([day, time, ch, msg]):
            messagebox.showwarning("Missing input", "Fill in all fields."); return
        try:
            h, m = map(int, time.split(":")); assert 0 <= h <= 23 and 0 <= m <= 59
        except:
            messagebox.showwarning("Invalid time", "Use HH:MM format."); return
        try:    ch_id = int(ch)
        except: messagebox.showwarning("Invalid channel", "Must be a number."); return
        rems = load_reminders()
        entry = {"day": DAYS.index(day), "time": time, "channel_id": ch_id, "message": msg}
        sel = self._rem_lb.curselection()
        if sel: rems[sel[0]] = entry
        else:   rems.append(entry)
        save_reminders(rems); self._refresh_rems(); self._clear_rem()
        self.set_status(f"Saved reminder for {day} at {time}")

    def _del_rem(self):
        sel = self._rem_lb.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a reminder first."); return
        if not messagebox.askyesno("Confirm", "Delete this reminder?"): return
        rems = load_reminders(); rems.pop(sel[0]); save_reminders(rems)
        self._refresh_rems(); self._clear_rem()
        self.set_status("Reminder deleted.")

    def _clear_rem(self):
        self._rem_day.set("Wednesday"); self._rem_time.set("12:00")
        self._rem_ch.set(""); self._rem_msg.set("")
        self._rem_lb.selection_clear(0, "end")

    # ── Questions ─────────────────────────────────────────────────────────────

    def _build_questions_tab(self, p):
        section(p, "Daily Questions", "Picks a random question each time the command is used.")

        lbl(p, "Command (without !)", dim=True).pack(fill="x", padx=20)
        self._q_cmd_var = tk.StringVar()
        self._q_cmd_var.trace_add("write", self._save_q_cmd)
        inp(p, self._q_cmd_var).pack(padx=20, pady=(2, 8), fill="x")

        lf, self._q_lb = scrolled_lb(p, 55, 5)
        lf.pack(padx=20, fill="x")
        self._q_lb.bind("<<ListboxSelect>>", self._on_q_sel)

        row = field_row(p, ["Question", "Answer (spoiler)"], [3, 2])
        self._q_text   = tk.StringVar()
        self._q_answer = tk.StringVar()
        inp(row, self._q_text  ).grid(row=1, column=0, padx=(0, 4), sticky="ew")
        inp(row, self._q_answer).grid(row=1, column=1, padx=(4, 0), sticky="ew")

        bf = tk.Frame(p, bg=BG)
        bf.pack(padx=20, pady=8, fill="x")
        btn(bf, "Add / Update", ACCENT, self._add_q ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        btn(bf, "Delete",       RED,   self._del_q ).pack(side="left", expand=True, fill="x", padx=(4, 4))
        btn(bf, "Clear",        GREY,  self._clear_q).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self._refresh_qs()

        # ── Auto-post ─────────────────────────────────────────────────────────
        tk.Frame(p, bg=GREY, height=1).pack(fill="x", padx=20, pady=(4, 8))

        feats = load_features()
        self._dq_enabled_var = tk.BooleanVar(value=feats.get("daily_question_enabled", False))
        self._dq_time_var    = tk.StringVar(value=feats.get("daily_question_time", "10:00"))
        self._dq_ch_var      = tk.StringVar(value=str(feats.get("daily_question_channel", 472851820448972800)))
        self._dq_time_var.trace_add("write", self._save_daily_q)
        self._dq_ch_var.trace_add("write",   self._save_daily_q)

        card = tk.Frame(p, bg=BG_CARD)
        card.pack(padx=20, fill="x")

        info = tk.Frame(card, bg=BG_CARD)
        info.pack(side="left", padx=12, pady=8, fill="x", expand=True)
        tk.Label(info, text="Auto-post a random question daily", bg=BG_CARD, fg=FG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")

        row = tk.Frame(info, bg=BG_CARD)
        row.pack(anchor="w", pady=(4, 0))
        tk.Label(row, text="Time:", bg=BG_CARD, fg=FG_DIM, font=("Segoe UI", 9)).pack(side="left")
        inp(row, self._dq_time_var, width=6).pack(side="left", padx=(4, 14))
        tk.Label(row, text="Channel:", bg=BG_CARD, fg=FG_DIM, font=("Segoe UI", 9)).pack(side="left")
        inp(row, self._dq_ch_var, width=19).pack(side="left", padx=(4, 6))
        tk.Button(row, text="General Chat", bg=BG_INPUT, fg=FG_DIM,
                  font=("Segoe UI", 9), relief="flat", cursor="hand2",
                  command=lambda: self._dq_ch_var.set("472851820448972800")
                  ).pack(side="left")

        tk.Checkbutton(card, variable=self._dq_enabled_var, bg=BG_CARD,
                       activebackground=BG_CARD, command=self._save_daily_q
                       ).pack(side="right", padx=12)

    def _save_daily_q(self, *_):
        d = load_features()
        d["daily_question_enabled"] = self._dq_enabled_var.get()
        try:
            h, m = map(int, self._dq_time_var.get().strip().split(":"))
            assert 0 <= h <= 23 and 0 <= m <= 59
            d["daily_question_time"] = self._dq_time_var.get().strip()
        except Exception:
            pass
        try:
            d["daily_question_channel"] = int(self._dq_ch_var.get().strip())
        except ValueError:
            pass
        save_features(d)
        self.set_status("Saved. Deploy to apply.")

    def _save_q_cmd(self, *_):
        d = load_questions(); d["command"] = self._q_cmd_var.get().strip().lstrip("!")
        save_questions(d)

    def _refresh_qs(self):
        self._q_lb.delete(0, "end")
        d = load_questions()
        if d.get("command"): self._q_cmd_var.set(d["command"])
        self.__qs = d.get("questions", [])
        for q in self.__qs:
            self._q_lb.insert("end", f"{q['question']}  ||{q['answer']}||")

    def _on_q_sel(self, _=None):
        sel = self._q_lb.curselection()
        if not sel: return
        q = self.__qs[sel[0]]
        self._q_text.set(q["question"]); self._q_answer.set(q["answer"])

    def _add_q(self):
        q = self._q_text.get().strip(); a = self._q_answer.get().strip()
        if not q or not a:
            messagebox.showwarning("Missing input", "Fill in both fields."); return
        d = load_questions(); item = {"question": q, "answer": a}
        sel = self._q_lb.curselection()
        if sel: d["questions"][sel[0]] = item
        else:   d["questions"].append(item)
        save_questions(d); self._refresh_qs(); self._clear_q()
        self.set_status("Question saved.")

    def _del_q(self):
        sel = self._q_lb.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a question first."); return
        if not messagebox.askyesno("Confirm", "Delete this question?"): return
        d = load_questions(); d["questions"].pop(sel[0]); save_questions(d)
        self._refresh_qs(); self._clear_q()
        self.set_status("Question deleted.")

    def _clear_q(self):
        self._q_text.set(""); self._q_answer.set("")
        self._q_lb.selection_clear(0, "end")

    # ── Push Message ──────────────────────────────────────────────────────────

    def _build_push_tab(self, p):
        section(p, "Push Message",
                "Queues a one-time message sent by the bot on next deploy.")

        lbl(p, "Channel ID", dim=True).pack(fill="x", padx=20)
        self._push_ch = tk.StringVar()
        inp(p, self._push_ch).pack(padx=20, pady=(2, 6), fill="x")

        # Presets
        presets = [
            ("General Chat",   "472851820448972800"),
            ("Announcements",  "478724610330722305"),
        ]
        pf = tk.Frame(p, bg=BG)
        pf.pack(padx=20, pady=(0, 10), fill="x")
        for name, ch_id in presets:
            tk.Button(pf, text=name, bg=BG_CARD, fg=FG_DIM,
                      font=("Segoe UI", 9), relief="flat", cursor="hand2",
                      command=lambda c=ch_id: self._push_ch.set(c)
                      ).pack(side="left", padx=(0, 6))

        lbl(p, "Message  (supports @mentions and :emojis:)", dim=True).pack(fill="x", padx=20)
        self._push_text = tk.Text(p, height=7, bg=BG_INPUT, fg=FG,
                                  insertbackground=FG, relief="flat",
                                  font=("Consolas", 11), wrap="word")
        self._push_text.pack(padx=20, pady=(2, 10), fill="x")

        # Show any already queued messages
        self._push_queue_lbl = tk.Label(p, text="", bg=BG, fg=FG_DIM,
                                        font=("Segoe UI", 9))
        self._push_queue_lbl.pack(fill="x", padx=20)
        self._refresh_push_label()

        bf = tk.Frame(p, bg=BG)
        bf.pack(padx=20, pady=8, fill="x")
        btn(bf, "Queue & Deploy", ACCENT, self._queue_push).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        btn(bf, "Clear Queue", RED, self._clear_push_queue).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

    def _refresh_push_label(self):
        msgs = load_push_messages()
        if msgs:
            self._push_queue_lbl.config(text=f"{len(msgs)} message(s) queued for next deploy.")
        else:
            self._push_queue_lbl.config(text="No messages queued.")

    def _queue_push(self):
        ch  = self._push_ch.get().strip()
        msg = self._push_text.get("1.0", "end-1c").strip()
        if not ch:
            messagebox.showwarning("Missing channel", "Enter a channel ID."); return
        if not msg:
            messagebox.showwarning("Missing message", "Enter a message."); return
        try:    ch_id = int(ch)
        except: messagebox.showwarning("Invalid channel", "Channel ID must be a number."); return

        msgs = load_push_messages()
        msgs.append({"channel_id": ch_id, "message": msg})
        save_push_messages(msgs)
        self._push_text.delete("1.0", "end")
        self._refresh_push_label()
        self.set_status("Queued. Deploying...")
        self.deploy(clear_push_after=True)

    def _clear_push_queue(self):
        if not messagebox.askyesno("Confirm", "Clear all queued messages?"): return
        save_push_messages([])
        self._refresh_push_label()
        self.set_status("Queue cleared.")

    # ── Fun Features ──────────────────────────────────────────────────────────

    def _build_features_tab(self, p):
        section(p, "Fun Features", "Toggle extra bot commands. Deploy to apply.")

        feats = load_features()
        self._rng_var            = tk.BooleanVar(value=feats.get("rng_enabled",            False))
        self._hug_var            = tk.BooleanVar(value=feats.get("hug_enabled",            False))
        self._spank_var          = tk.BooleanVar(value=feats.get("spank_enabled",          False))
        self._pickgroupboss_var  = tk.BooleanVar(value=feats.get("pickgroupboss_enabled",  False))

        for var, title, desc in [
            (self._rng_var,   "!RNG",
             'Picks a random number 1–100.\nResponds: "DogBot rolled a X!"'),
            (self._hug_var,   "!hug @user",
             "Give someone a hug.\nResponds: \"[sender] hugs [target]! 🤗\""),
            (self._spank_var, "!spank @user",
             "Give someone a spank. 🥵🥵\nResponds: \"[sender] spanks [target]!\""),
            (self._pickgroupboss_var, "!pickgroupboss",
             "Picks a random group boss to do together.\nResponds: \"⚔️ Tonight's group boss: [boss]!\""),
        ]:
            card = tk.Frame(p, bg=BG_CARD)
            card.pack(padx=20, pady=4, fill="x")
            info = tk.Frame(card, bg=BG_CARD)
            info.pack(side="left", padx=12, pady=10, fill="x", expand=True)
            tk.Label(info, text=title, bg=BG_CARD, fg=FG,
                     font=("Segoe UI", 11, "bold")).pack(anchor="center")
            tk.Label(info, text=desc, bg=BG_CARD, fg=FG_DIM, font=("Segoe UI", 9),
                     anchor="center", justify="center").pack(anchor="center")
            tk.Checkbutton(card, variable=var, bg=BG_CARD,
                           activebackground=BG_CARD, command=self._save_features
                           ).pack(side="right", padx=12)

        btn(p, "Save & Deploy", GREEN, self.deploy).pack(padx=20, pady=16, fill="x")

    def _save_features(self):
        d = load_features()
        d["rng_enabled"]           = self._rng_var.get()
        d["hug_enabled"]           = self._hug_var.get()
        d["spank_enabled"]         = self._spank_var.get()
        d["pickgroupboss_enabled"] = self._pickgroupboss_var.get()
        save_features(d)
        self.set_status("Saved. Deploy to apply.")

    # ── Giveaway ──────────────────────────────────────────────────────────────

    _GW_PRESETS = {
        472851820448972800: "General Chat",
        478724610330722305: "Announcements",
    }

    def _build_giveaway_tab(self, p):
        section(p, "Giveaway", "Schedule a giveaway — the bot posts the message and picks a winner.")

        # Live clock (shares the GMT offset from Reminders tab)
        self._gw_clock_lbl = tk.Label(p, text="", bg=BG, fg=GOLD,
                                      font=("Segoe UI", 11, "bold"))
        self._gw_clock_lbl.pack(pady=(0, 6))
        self._giveaway_tick()

        # Active / queued giveaways list
        lf, self._gw_lb = scrolled_lb(p, 58, 4)
        lf.pack(padx=20, fill="x")

        btn(p, "Delete Selected", RED, self._del_giveaway).pack(
            padx=20, pady=(4, 10), fill="x")

        # ── New giveaway form ──
        tk.Frame(p, bg=GREY, height=1).pack(fill="x", padx=20, pady=(0, 8))

        # Channel ID
        lbl(p, "Channel ID", dim=True).pack(fill="x", padx=20)
        self._gw_ch = tk.StringVar()
        inp(p, self._gw_ch).pack(padx=20, pady=(2, 4), fill="x")

        pf = tk.Frame(p, bg=BG)
        pf.pack(padx=20, pady=(0, 8), fill="x")
        for name, ch_id in [("General Chat",  "472851820448972800"),
                             ("Announcements", "478724610330722305")]:
            tk.Button(pf, text=name, bg=BG_CARD, fg=FG_DIM,
                      font=("Segoe UI", 9), relief="flat", cursor="hand2",
                      command=lambda c=ch_id: self._gw_ch.set(c)
                      ).pack(side="left", padx=(0, 6))

        # Prize
        lbl(p, "Prize", dim=True).pack(fill="x", padx=20)
        self._gw_prize = tk.StringVar()
        inp(p, self._gw_prize).pack(padx=20, pady=(2, 8), fill="x")

        # End date & time
        lbl(p, "End date & time (your local time)", dim=True).pack(fill="x", padx=20)
        dt_frame = tk.Frame(p, bg=BG)
        dt_frame.pack(padx=20, pady=(2, 10), fill="x")

        now_local = datetime.now(timezone.utc) + timedelta(hours=self._get_gw_offset())
        years = [str(now_local.year), str(now_local.year + 1)]

        self._gw_day   = tk.StringVar(value=f"{now_local.day:02d}")
        self._gw_month = tk.StringVar(value=f"{now_local.month:02d}")
        self._gw_year  = tk.StringVar(value=str(now_local.year))
        self._gw_time  = tk.StringVar(value="12:00")

        for label_text, var, values, w in [
            ("Day",   self._gw_day,   [f"{i:02d}" for i in range(1, 32)], 4),
            ("Month", self._gw_month, [f"{i:02d}" for i in range(1, 13)], 4),
            ("Year",  self._gw_year,  years,                               6),
        ]:
            col = tk.Frame(dt_frame, bg=BG)
            col.pack(side="left", padx=(0, 8))
            tk.Label(col, text=label_text, bg=BG, fg=FG_DIM,
                     font=("Segoe UI", 9), anchor="center").pack(fill="x")
            ttk.Combobox(col, textvariable=var, values=values,
                         width=w, state="readonly", font=("Segoe UI", 10)).pack()

        tk.Label(dt_frame, text="", bg=BG, width=2).pack(side="left")

        time_col = tk.Frame(dt_frame, bg=BG)
        time_col.pack(side="left")
        tk.Label(time_col, text="Time (HH:MM)", bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9), anchor="center").pack(fill="x")
        inp(time_col, self._gw_time, width=7).pack()

        btn(p, "Queue & Deploy", ACCENT, self._queue_giveaway).pack(
            padx=20, pady=(0, 6), fill="x")

        self._refresh_gw_list()

    def _get_gw_offset(self):
        try:
            return int(self._offset_var.get())
        except Exception:
            return load_features().get("gmt_offset", 0)

    def _giveaway_tick(self):
        offset = self._get_gw_offset()
        now    = datetime.now(timezone.utc) + timedelta(hours=offset)
        sign   = f"+{offset}" if offset >= 0 else str(offset)
        self._gw_clock_lbl.config(text=f"🕐  {now.strftime('%H:%M:%S')}  UTC{sign}")
        self.after(1000, self._giveaway_tick)

    def _refresh_gw_list(self):
        self._gw_lb.delete(0, "end")
        self.__gws = load_giveaways()
        offset = self._get_gw_offset()
        sign   = f"+{offset}" if offset >= 0 else str(offset)
        for g in self.__gws:
            ch_name = self._GW_PRESETS.get(g["channel_id"], str(g["channel_id"]))
            end_dt  = datetime.fromtimestamp(g["end_at"], tz=timezone.utc) + timedelta(hours=offset)
            status  = "active" if g.get("message_id") else "queued"
            self._gw_lb.insert("end",
                f"[{status}]  {ch_name:<16}  {g['prize']:<28}  "
                f"{end_dt.strftime('%d %b %Y %H:%M')} UTC{sign}"
            )

    def _queue_giveaway(self):
        ch       = self._gw_ch.get().strip()
        prize    = self._gw_prize.get().strip()
        time_str = self._gw_time.get().strip()
        if not ch:
            messagebox.showwarning("Missing channel", "Enter a channel ID."); return
        if not prize:
            messagebox.showwarning("Missing prize", "Enter a prize."); return
        try:
            ch_id = int(ch)
        except ValueError:
            messagebox.showwarning("Invalid channel", "Channel ID must be a number."); return
        try:
            h, m = map(int, time_str.split(":"))
            assert 0 <= h <= 23 and 0 <= m <= 59
        except Exception:
            messagebox.showwarning("Invalid time", "Use HH:MM format."); return
        try:
            offset    = self._get_gw_offset()
            end_local = datetime(
                int(self._gw_year.get()), int(self._gw_month.get()), int(self._gw_day.get()),
                h, m, tzinfo=timezone(timedelta(hours=offset))
            )
            end_at = end_local.timestamp()
        except ValueError as e:
            messagebox.showwarning("Invalid date", str(e)); return
        if end_at <= datetime.now(timezone.utc).timestamp():
            messagebox.showwarning("Invalid time", "End time must be in the future."); return
        gs = load_giveaways()
        gs.append({"channel_id": ch_id, "prize": prize, "end_at": end_at, "message_id": None})
        save_giveaways(gs)
        self.set_status("Giveaway queued. Deploying...")
        self.deploy()
        # Clear locally so the next deploy (e.g. a push message) doesn't re-trigger this giveaway
        save_giveaways([])
        self._refresh_gw_list()

    def _del_giveaway(self):
        sel = self._gw_lb.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a giveaway first."); return
        g = self.__gws[sel[0]]
        label = g["prize"]
        if not messagebox.askyesno("Confirm", f'Delete giveaway "{label}"?'): return
        gs = load_giveaways()
        gs = [x for x in gs if not (x["channel_id"] == g["channel_id"]
                                     and x["end_at"] == g["end_at"])]
        save_giveaways(gs)
        self._refresh_gw_list()
        self.set_status(f'Deleted "{label}".')

    # ── Utility ───────────────────────────────────────────────────────────────

    def _build_utility_tab(self, p):
        section(p, "Utility", "Helper and moderation commands. Deploy to apply.")

        feats = load_features()
        self._clear_var    = tk.BooleanVar(value=feats.get("clear_enabled",    False))
        self._remindme_var = tk.BooleanVar(value=feats.get("remindme_enabled", False))

        lbl(p, "Moderator role name (leave blank to allow everyone)", dim=True).pack(fill="x", padx=20)
        self._mod_role_var = tk.StringVar(value=feats.get("mod_role", ""))
        self._mod_role_var.trace_add("write", self._save_mod_role)
        inp(p, self._mod_role_var).pack(padx=20, pady=(2, 10), fill="x")

        for var, title, desc in [
            (self._clear_var,
             "!clear <amount>",
             "Deletes the last X messages (max 100).\nRequires 'Manage Messages' permission."),
            (self._remindme_var,
             "!remindme <minutes> <message>",
             "Sets a personal reminder.\nThe bot pings you after the given number of minutes."),
        ]:
            card = tk.Frame(p, bg=BG_CARD)
            card.pack(padx=20, pady=4, fill="x")
            info = tk.Frame(card, bg=BG_CARD)
            info.pack(side="left", padx=12, pady=10, fill="x", expand=True)
            tk.Label(info, text=title, bg=BG_CARD, fg=FG,
                     font=("Segoe UI", 11, "bold")).pack(anchor="center")
            tk.Label(info, text=desc, bg=BG_CARD, fg=FG_DIM, font=("Segoe UI", 9),
                     anchor="center", justify="center").pack(anchor="center")
            tk.Checkbutton(card, variable=var, bg=BG_CARD,
                           activebackground=BG_CARD, command=self._save_utility
                           ).pack(side="right", padx=12)

        btn(p, "Save & Deploy", GREEN, self.deploy).pack(padx=20, pady=16, fill="x")

    def _save_utility(self):
        d = load_features()
        d["clear_enabled"]    = self._clear_var.get()
        d["remindme_enabled"] = self._remindme_var.get()
        save_features(d)
        self.set_status("Saved. Deploy to apply.")

    def _save_mod_role(self, *_):
        d = load_features()
        d["mod_role"] = self._mod_role_var.get().strip()
        save_features(d)

    # ── Deploy ────────────────────────────────────────────────────────────────

    def deploy(self, clear_push_after=False):
        repo = os.path.dirname(os.path.realpath(__file__))
        try:
            r = subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, text=True)
            if r.returncode != 0:
                messagebox.showerror("Deploy failed", r.stderr); return
            if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode == 0:
                self.set_status("No changes to deploy."); return
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            subprocess.run(["git", "commit", "-m", f"Bot update — {timestamp}"], cwd=repo, check=True)
            subprocess.run(["git", "push"], cwd=repo, check=True)
            if clear_push_after:
                save_push_messages([])
                self._refresh_push_label()
            self.set_status("Deployed! Railway will redeploy automatically.")
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Deploy failed", str(e))

    def set_status(self, msg):
        self._status.config(text=msg)
        self.after(4000, lambda: self._status.config(text=""))


if __name__ == "__main__":
    app = ManagerApp()
    app.mainloop()
