import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

COMMANDS_FILE = os.path.join(os.path.dirname(__file__), "commands.json")
REMINDERS_FILE = os.path.join(os.path.dirname(__file__), "reminders.json")
QUESTIONS_FILE = os.path.join(os.path.dirname(__file__), "questions.json")
FEATURES_FILE  = os.path.join(os.path.dirname(__file__), "features.json")

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


# ── I/O helpers ───────────────────────────────────────────────────────────────

def load_commands():
    if not os.path.exists(COMMANDS_FILE):
        return {}
    with open(COMMANDS_FILE, "r") as f:
        return json.load(f)

def save_commands(d):
    with open(COMMANDS_FILE, "w") as f:
        json.dump(d, f, indent=4)

def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return []
    with open(REMINDERS_FILE, "r") as f:
        return json.load(f)

def save_reminders(d):
    with open(REMINDERS_FILE, "w") as f:
        json.dump(d, f, indent=4)

def load_questions():
    if not os.path.exists(QUESTIONS_FILE):
        return {"command": "", "questions": []}
    with open(QUESTIONS_FILE, "r") as f:
        return json.load(f)

def save_questions(d):
    with open(QUESTIONS_FILE, "w") as f:
        json.dump(d, f, indent=4)

def load_features():
    defaults = {"gmt_offset": 0, "rng_enabled": False, "webhook_url": ""}
    if not os.path.exists(FEATURES_FILE):
        return defaults
    with open(FEATURES_FILE, "r") as f:
        data = json.load(f)
    for k, v in defaults.items():
        data.setdefault(k, v)
    return data

def save_features(d):
    with open(FEATURES_FILE, "w") as f:
        json.dump(d, f, indent=4)


# ── Widget helpers ─────────────────────────────────────────────────────────────

def label(parent, text, large=False, dim=False, **kw):
    return tk.Label(parent, text=text, bg=BG, fg=FG_DIM if dim else FG,
                    font=("Segoe UI", 13 if large else 10, "bold" if large else "normal"), **kw)

def entry(parent, var, **kw):
    return tk.Entry(parent, textvariable=var, bg=BG_INPUT, fg=FG,
                    insertbackground=FG, relief="flat", font=("Consolas", 11), **kw)

def btn(parent, text, color, cmd, **kw):
    return tk.Button(parent, text=text, bg=color, fg=FG, font=("Segoe UI", 10, "bold"),
                     relief="flat", cursor="hand2", pady=6, command=cmd, **kw)

def scrolled_listbox(parent, width, height):
    f = tk.Frame(parent, bg=BG)
    lb = tk.Listbox(f, width=width, height=height, bg=BG_INPUT, fg=FG,
                    selectbackground=ACCENT, font=("Consolas", 11),
                    activestyle="none", relief="flat")
    sb = ttk.Scrollbar(f, orient="vertical", command=lb.yview)
    lb.config(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return f, lb


# ── App ────────────────────────────────────────────────────────────────────────

class ManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Discord Bot — Manager")
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
            ("Commands",     self._build_commands_tab),
            ("Reminders",    self._build_reminders_tab),
            ("Questions",    self._build_questions_tab),
            ("Push Message", self._build_push_tab),
            ("Fun Features", self._build_features_tab),
        ]:
            f = tk.Frame(nb, bg=BG)
            nb.add(f, text=name)
            builder(f)

        btn(self, "Save & Deploy to GitHub", GREEN, self.deploy).pack(
            fill="x", padx=12, pady=(0, 6))

        self.status_lbl = tk.Label(self, text="", bg=BG, fg=FG_DIM, font=("Segoe UI", 9))
        self.status_lbl.pack(pady=(0, 8))

    # ── Commands ──────────────────────────────────────────────────────────────

    def _build_commands_tab(self, p):
        label(p, "Custom Commands", large=True).pack(pady=(12, 2))
        label(p, "Add a command and the response the bot will give.", dim=True).pack(pady=(0, 8))

        lf, self.cmd_lb = scrolled_listbox(p, 52, 10)
        lf.pack(padx=12, fill="x")
        self.cmd_lb.bind("<<ListboxSelect>>", self._on_cmd_select)

        row = tk.Frame(p, bg=BG)
        row.pack(padx=12, pady=(8, 4), fill="x")
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=3)

        label(row, "!command", dim=True).grid(row=0, column=0, pady=(0, 2))
        label(row, "Response", dim=True).grid(row=0, column=1, pady=(0, 2))

        self.cmd_var  = tk.StringVar()
        self.resp_var = tk.StringVar()
        entry(row, self.cmd_var).grid( row=1, column=0, padx=(0, 4), sticky="ew")
        entry(row, self.resp_var).grid(row=1, column=1, padx=(4, 0), sticky="ew")

        bf = tk.Frame(p, bg=BG)
        bf.pack(padx=12, pady=8, fill="x")
        btn(bf, "Add / Update", ACCENT, self._add_cmd).pack(side="left", expand=True, fill="x", padx=(0, 4))
        btn(bf, "Delete",       RED,   self._del_cmd).pack(side="left", expand=True, fill="x", padx=(4, 4))
        btn(bf, "Clear",        GREY,  self._clear_cmd).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self._refresh_cmds()

    def _refresh_cmds(self):
        self.cmd_lb.delete(0, "end")
        self._cmds = load_commands()
        for cmd, resp in self._cmds.items():
            self.cmd_lb.insert("end", f"!{cmd:<18} {resp}")

    def _on_cmd_select(self, _=None):
        sel = self.cmd_lb.curselection()
        if not sel:
            return
        cmd = list(self._cmds.keys())[sel[0]]
        self.cmd_var.set(cmd)
        self.resp_var.set(self._cmds[cmd])

    def _add_cmd(self):
        cmd  = self.cmd_var.get().strip().lstrip("!").lower()
        resp = self.resp_var.get().strip()
        if not cmd or not resp:
            messagebox.showwarning("Missing input", "Fill in both fields.")
            return
        d = load_commands()
        d[cmd] = resp
        save_commands(d)
        self._refresh_cmds()
        self._clear_cmd()
        self.set_status(f'Saved "!{cmd}"')

    def _del_cmd(self):
        cmd = self.cmd_var.get().strip().lstrip("!").lower()
        if not cmd:
            messagebox.showwarning("No selection", "Select a command first.")
            return
        d = load_commands()
        if cmd not in d:
            messagebox.showwarning("Not found", f'"!{cmd}" does not exist.')
            return
        if not messagebox.askyesno("Confirm", f'Delete "!{cmd}"?'):
            return
        del d[cmd]
        save_commands(d)
        self._refresh_cmds()
        self._clear_cmd()
        self.set_status(f'Deleted "!{cmd}"')

    def _clear_cmd(self):
        self.cmd_var.set("")
        self.resp_var.set("")
        self.cmd_lb.selection_clear(0, "end")

    # ── Reminders ─────────────────────────────────────────────────────────────

    def _build_reminders_tab(self, p):
        label(p, "Scheduled Reminders", large=True).pack(pady=(12, 2))
        label(p, "Times are in your local timezone based on the offset below.", dim=True).pack(pady=(0, 6))

        # Clock + offset row
        clock_row = tk.Frame(p, bg=BG)
        clock_row.pack(pady=(0, 8))

        self._clock_lbl = tk.Label(clock_row, text="", bg=BG, fg=GOLD,
                                   font=("Segoe UI", 11, "bold"))
        self._clock_lbl.pack(side="left", padx=(0, 16))

        tk.Label(clock_row, text="Offset:", bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 10)).pack(side="left")

        feats = load_features()
        self._offset_var = tk.StringVar(value=str(feats.get("gmt_offset", 0)))
        offset_cb = ttk.Combobox(clock_row, textvariable=self._offset_var,
                                 values=["0", "1", "2"], width=4, state="readonly",
                                 font=("Segoe UI", 10))
        offset_cb.pack(side="left", padx=4)
        offset_cb.bind("<<ComboboxSelected>>", self._save_offset)

        tk.Label(clock_row, text="(0=GMT  1=CET/BST  2=CEST)", bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))

        self._tick_clock()

        # Listbox
        lf, self.rem_lb = scrolled_listbox(p, 58, 7)
        lf.pack(padx=12, fill="x")
        self.rem_lb.bind("<<ListboxSelect>>", self._on_rem_select)

        # Fields
        fields = tk.Frame(p, bg=BG)
        fields.pack(padx=12, pady=(8, 4), fill="x")
        for i, w in enumerate([1, 1, 2, 3]):
            fields.columnconfigure(i, weight=w)

        for col, txt in enumerate(["Day", "Time (HH:MM)", "Channel ID", "Message"]):
            label(fields, txt, dim=True).grid(row=0, column=col, pady=(0, 2))

        self.rem_day_var  = tk.StringVar(value="Wednesday")
        self.rem_time_var = tk.StringVar(value="12:00")
        self.rem_ch_var   = tk.StringVar()
        self.rem_msg_var  = tk.StringVar()

        ttk.Combobox(fields, textvariable=self.rem_day_var, values=DAYS,
                     state="readonly", font=("Segoe UI", 10)
                     ).grid(row=1, column=0, padx=2, sticky="ew")
        entry(fields, self.rem_time_var).grid(row=1, column=1, padx=2, sticky="ew")
        entry(fields, self.rem_ch_var  ).grid(row=1, column=2, padx=2, sticky="ew")
        entry(fields, self.rem_msg_var ).grid(row=1, column=3, padx=2, sticky="ew")

        bf = tk.Frame(p, bg=BG)
        bf.pack(padx=12, pady=8, fill="x")
        btn(bf, "Add / Update", ACCENT, self._add_rem ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        btn(bf, "Delete",       RED,   self._del_rem ).pack(side="left", expand=True, fill="x", padx=(4, 4))
        btn(bf, "Clear",        GREY,  self._clear_rem).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self._refresh_rems()

    def _tick_clock(self):
        try:
            offset = int(self._offset_var.get())
        except (ValueError, AttributeError):
            offset = 0
        now = datetime.now(timezone.utc) + timedelta(hours=offset)
        sign = f"+{offset}" if offset >= 0 else str(offset)
        self._clock_lbl.config(text=f"🕐  {now.strftime('%H:%M:%S')}  (UTC{sign})")
        self.after(1000, self._tick_clock)

    def _save_offset(self, *_):
        try:
            offset = int(self._offset_var.get())
        except ValueError:
            return
        d = load_features()
        d["gmt_offset"] = offset
        save_features(d)

    def _refresh_rems(self):
        self.rem_lb.delete(0, "end")
        self._rems = load_reminders()
        for r in self._rems:
            self.rem_lb.insert("end",
                f"{DAYS[r['day']]:<12} {r['time']}  #{r['channel_id']}  {r['message']}")

    def _on_rem_select(self, _=None):
        sel = self.rem_lb.curselection()
        if not sel:
            return
        r = self._rems[sel[0]]
        self.rem_day_var.set(DAYS[r["day"]])
        self.rem_time_var.set(r["time"])
        self.rem_ch_var.set(str(r["channel_id"]))
        self.rem_msg_var.set(r["message"])

    def _add_rem(self):
        day  = self.rem_day_var.get()
        time = self.rem_time_var.get().strip()
        ch   = self.rem_ch_var.get().strip()
        msg  = self.rem_msg_var.get().strip()
        if not all([day, time, ch, msg]):
            messagebox.showwarning("Missing input", "Fill in all fields.")
            return
        try:
            h, m = map(int, time.split(":"))
            assert 0 <= h <= 23 and 0 <= m <= 59
        except Exception:
            messagebox.showwarning("Invalid time", "Use HH:MM format.")
            return
        try:
            ch_id = int(ch)
        except ValueError:
            messagebox.showwarning("Invalid channel", "Channel ID must be a number.")
            return
        rems = load_reminders()
        entry_data = {"day": DAYS.index(day), "time": time, "channel_id": ch_id, "message": msg}
        sel = self.rem_lb.curselection()
        if sel:
            rems[sel[0]] = entry_data
        else:
            rems.append(entry_data)
        save_reminders(rems)
        self._refresh_rems()
        self._clear_rem()
        self.set_status(f"Saved reminder for {day} at {time}")

    def _del_rem(self):
        sel = self.rem_lb.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a reminder first.")
            return
        if not messagebox.askyesno("Confirm", "Delete this reminder?"):
            return
        rems = load_reminders()
        rems.pop(sel[0])
        save_reminders(rems)
        self._refresh_rems()
        self._clear_rem()
        self.set_status("Reminder deleted.")

    def _clear_rem(self):
        self.rem_day_var.set("Wednesday")
        self.rem_time_var.set("12:00")
        self.rem_ch_var.set("")
        self.rem_msg_var.set("")
        self.rem_lb.selection_clear(0, "end")

    # ── Questions ─────────────────────────────────────────────────────────────

    def _build_questions_tab(self, p):
        label(p, "Daily Questions", large=True).pack(pady=(12, 2))
        label(p, "Picks a random question each time the command is used.", dim=True).pack(pady=(0, 8))

        label(p, "Command (without !)", dim=True).pack()
        self.q_cmd_var = tk.StringVar()
        self.q_cmd_var.trace_add("write", self._save_q_cmd)
        entry(p, self.q_cmd_var).pack(padx=12, pady=(2, 8), fill="x")

        lf, self.q_lb = scrolled_listbox(p, 55, 7)
        lf.pack(padx=12, fill="x")
        self.q_lb.bind("<<ListboxSelect>>", self._on_q_select)

        row = tk.Frame(p, bg=BG)
        row.pack(padx=12, pady=(8, 4), fill="x")
        row.columnconfigure(0, weight=3)
        row.columnconfigure(1, weight=2)

        label(row, "Question", dim=True).grid(row=0, column=0, pady=(0, 2))
        label(row, "Answer (spoiler)", dim=True).grid(row=0, column=1, pady=(0, 2))

        self.q_text_var   = tk.StringVar()
        self.q_answer_var = tk.StringVar()
        entry(row, self.q_text_var  ).grid(row=1, column=0, padx=(0, 4), sticky="ew")
        entry(row, self.q_answer_var).grid(row=1, column=1, padx=(4, 0), sticky="ew")

        bf = tk.Frame(p, bg=BG)
        bf.pack(padx=12, pady=8, fill="x")
        btn(bf, "Add / Update", ACCENT, self._add_q ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        btn(bf, "Delete",       RED,   self._del_q ).pack(side="left", expand=True, fill="x", padx=(4, 4))
        btn(bf, "Clear",        GREY,  self._clear_q).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self._refresh_qs()

    def _save_q_cmd(self, *_):
        cmd = self.q_cmd_var.get().strip().lstrip("!")
        d = load_questions()
        d["command"] = cmd
        save_questions(d)

    def _refresh_qs(self):
        self.q_lb.delete(0, "end")
        d = load_questions()
        if d.get("command"):
            self.q_cmd_var.set(d["command"])
        self._qs = d.get("questions", [])
        for q in self._qs:
            self.q_lb.insert("end", f"{q['question']}  ||{q['answer']}||")

    def _on_q_select(self, _=None):
        sel = self.q_lb.curselection()
        if not sel:
            return
        q = self._qs[sel[0]]
        self.q_text_var.set(q["question"])
        self.q_answer_var.set(q["answer"])

    def _add_q(self):
        q = self.q_text_var.get().strip()
        a = self.q_answer_var.get().strip()
        if not q or not a:
            messagebox.showwarning("Missing input", "Fill in both fields.")
            return
        d = load_questions()
        item = {"question": q, "answer": a}
        sel = self.q_lb.curselection()
        if sel:
            d["questions"][sel[0]] = item
        else:
            d["questions"].append(item)
        save_questions(d)
        self._refresh_qs()
        self._clear_q()
        self.set_status("Question saved.")

    def _del_q(self):
        sel = self.q_lb.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a question first.")
            return
        if not messagebox.askyesno("Confirm", "Delete this question?"):
            return
        d = load_questions()
        d["questions"].pop(sel[0])
        save_questions(d)
        self._refresh_qs()
        self._clear_q()
        self.set_status("Question deleted.")

    def _clear_q(self):
        self.q_text_var.set("")
        self.q_answer_var.set("")
        self.q_lb.selection_clear(0, "end")

    # ── Push Message ──────────────────────────────────────────────────────────

    def _build_push_tab(self, p):
        label(p, "Push Message", large=True).pack(pady=(12, 2))
        label(p, "Send a one-time message instantly via a Discord webhook.", dim=True).pack(pady=(0, 12))

        label(p, "Webhook URL", dim=True).pack()
        self._webhook_var = tk.StringVar(value=load_features().get("webhook_url", ""))
        self._webhook_var.trace_add("write", self._save_webhook)
        entry(p, self._webhook_var).pack(padx=12, pady=(2, 12), fill="x")

        label(p, "Message", dim=True).pack()
        self._push_text = tk.Text(p, height=7, bg=BG_INPUT, fg=FG,
                                  insertbackground=FG, relief="flat",
                                  font=("Consolas", 11), wrap="word")
        self._push_text.pack(padx=12, pady=(2, 12), fill="x")

        btn(p, "Send", ACCENT, self._send_push).pack(padx=12, fill="x")

        label(p, "To create a webhook: Discord channel settings → Integrations → Webhooks",
              dim=True).pack(pady=(10, 0))

    def _save_webhook(self, *_):
        d = load_features()
        d["webhook_url"] = self._webhook_var.get().strip()
        save_features(d)

    def _send_push(self):
        url = self._webhook_var.get().strip()
        msg = self._push_text.get("1.0", "end-1c").strip()
        if not url:
            messagebox.showwarning("No webhook", "Enter a webhook URL first.")
            return
        if not msg:
            messagebox.showwarning("No message", "Enter a message.")
            return
        payload = json.dumps({"content": msg}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status in (200, 204):
                    self._push_text.delete("1.0", "end")
                    self.set_status("Message sent!")
                else:
                    messagebox.showerror("Failed", f"Discord returned {resp.status}")
        except urllib.error.HTTPError as e:
            messagebox.showerror("HTTP Error", f"{e.code}: {e.reason}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── Fun Features ──────────────────────────────────────────────────────────

    def _build_features_tab(self, p):
        label(p, "Fun Features", large=True).pack(pady=(12, 2))
        label(p, "Toggle extra bot commands. Deploy after changing.", dim=True).pack(pady=(0, 12))

        feats = load_features()
        self._rng_var = tk.BooleanVar(value=feats.get("rng_enabled", False))

        card = tk.Frame(p, bg=BG_CARD)
        card.pack(padx=12, fill="x")

        info = tk.Frame(card, bg=BG_CARD)
        info.pack(side="left", padx=12, pady=10, fill="x", expand=True)
        tk.Label(info, text="!RNG", bg=BG_CARD, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(info, text="Picks a random number between 1–100.\nResponds: DogBot rolled a X!",
                 bg=BG_CARD, fg=FG_DIM, font=("Segoe UI", 9)).pack(anchor="w")

        tk.Checkbutton(card, variable=self._rng_var, bg=BG_CARD,
                       activebackground=BG_CARD, command=self._save_features
                       ).pack(side="right", padx=12)

        btn(p, "Save & Deploy", GREEN, self.deploy).pack(padx=12, pady=16, fill="x")

    def _save_features(self):
        d = load_features()
        d["rng_enabled"] = self._rng_var.get()
        save_features(d)
        self.set_status("Saved. Deploy to apply.")

    # ── Deploy ────────────────────────────────────────────────────────────────

    def deploy(self):
        repo = os.path.dirname(os.path.realpath(__file__))
        try:
            r = subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, text=True)
            if r.returncode != 0:
                messagebox.showerror("Deploy failed", r.stderr)
                return
            if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode == 0:
                self.set_status("No changes to deploy.")
                return
            subprocess.run(["git", "commit", "-m", "Update bot data"], cwd=repo, check=True)
            subprocess.run(["git", "push"], cwd=repo, check=True)
            self.set_status("Deployed! Railway will redeploy automatically.")
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Deploy failed", str(e))

    def set_status(self, msg):
        self.status_lbl.config(text=msg)
        self.after(4000, lambda: self.status_lbl.config(text=""))


if __name__ == "__main__":
    app = ManagerApp()
    app.mainloop()
