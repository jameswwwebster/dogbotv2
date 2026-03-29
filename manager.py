import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import subprocess

COMMANDS_FILE = os.path.join(os.path.dirname(__file__), "commands.json")
REMINDERS_FILE = os.path.join(os.path.dirname(__file__), "reminders.json")

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def load_commands():
    if not os.path.exists(COMMANDS_FILE):
        return {}
    with open(COMMANDS_FILE, "r") as f:
        return json.load(f)


def save_commands(cmds):
    with open(COMMANDS_FILE, "w") as f:
        json.dump(cmds, f, indent=4)


def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return []
    with open(REMINDERS_FILE, "r") as f:
        return json.load(f)


def save_reminders(reminders):
    with open(REMINDERS_FILE, "w") as f:
        json.dump(reminders, f, indent=4)


class ManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Discord Bot — Manager")
        self.resizable(False, False)
        self.configure(bg="#2b2d31")
        self._build_ui()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook", background="#2b2d31", borderwidth=0)
        style.configure("TNotebook.Tab", background="#1e1f22", foreground="white",
                        padding=[12, 6], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#5865f2")])

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        # --- Commands tab ---
        cmd_frame = tk.Frame(notebook, bg="#2b2d31")
        notebook.add(cmd_frame, text="Commands")
        self._build_commands_tab(cmd_frame)

        # --- Reminders tab ---
        rem_frame = tk.Frame(notebook, bg="#2b2d31")
        notebook.add(rem_frame, text="Reminders")
        self._build_reminders_tab(rem_frame)

        # --- Deploy button (shared) ---
        btn_opts = {"font": ("Segoe UI", 10, "bold"), "relief": "flat", "cursor": "hand2", "pady": 6}
        tk.Button(
            self, text="Save & Deploy to GitHub", bg="#3ba55d", fg="white",
            command=self.deploy, **btn_opts
        ).pack(fill="x", padx=12, pady=(0, 6))

        self.status = tk.Label(self, text="", bg="#2b2d31", fg="#b5bac1", font=("Segoe UI", 9))
        self.status.pack(pady=(0, 8))

    # ------------------------------------------------------------------ Commands tab

    def _build_commands_tab(self, parent):
        pad = {"padx": 10, "pady": 6}
        btn_opts = {"font": ("Segoe UI", 10, "bold"), "relief": "flat", "cursor": "hand2", "pady": 6}

        tk.Label(parent, text="Custom Commands", bg="#2b2d31", fg="white",
                 font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=3, pady=(12, 4))

        frame = tk.Frame(parent, bg="#2b2d31")
        frame.grid(row=1, column=0, columnspan=3, padx=12, pady=6)

        self.cmd_listbox = tk.Listbox(frame, width=50, height=10, bg="#1e1f22", fg="white",
                                      selectbackground="#5865f2", font=("Consolas", 11),
                                      activestyle="none", relief="flat")
        self.cmd_listbox.pack(side="left", fill="both")
        self.cmd_listbox.bind("<<ListboxSelect>>", self.on_cmd_select)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.cmd_listbox.yview)
        sb.pack(side="right", fill="y")
        self.cmd_listbox.config(yscrollcommand=sb.set)

        tk.Label(parent, text="!command", bg="#2b2d31", fg="#b5bac1",
                 font=("Segoe UI", 10)).grid(row=2, column=0, **pad, sticky="w")
        tk.Label(parent, text="Response", bg="#2b2d31", fg="#b5bac1",
                 font=("Segoe UI", 10)).grid(row=2, column=1, columnspan=2, **pad, sticky="w")

        self.cmd_var = tk.StringVar()
        self.resp_var = tk.StringVar()

        tk.Entry(parent, textvariable=self.cmd_var, width=16, bg="#1e1f22", fg="white",
                 insertbackground="white", relief="flat", font=("Consolas", 11)
                 ).grid(row=3, column=0, padx=(12, 4), pady=2, sticky="ew")
        tk.Entry(parent, textvariable=self.resp_var, width=34, bg="#1e1f22", fg="white",
                 insertbackground="white", relief="flat", font=("Consolas", 11)
                 ).grid(row=3, column=1, columnspan=2, padx=(4, 12), pady=2, sticky="ew")

        bf = tk.Frame(parent, bg="#2b2d31")
        bf.grid(row=4, column=0, columnspan=3, pady=10, padx=12, sticky="ew")

        tk.Button(bf, text="Add / Update", bg="#5865f2", fg="white",
                  command=self.add_or_update_cmd, **btn_opts).pack(side="left", expand=True, fill="x", padx=(0, 4))
        tk.Button(bf, text="Delete", bg="#ed4245", fg="white",
                  command=self.delete_cmd, **btn_opts).pack(side="left", expand=True, fill="x", padx=(4, 4))
        tk.Button(bf, text="Clear", bg="#4f545c", fg="white",
                  command=self.clear_cmd_fields, **btn_opts).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.refresh_cmd_list()

    # ------------------------------------------------------------------ Reminders tab

    def _build_reminders_tab(self, parent):
        btn_opts = {"font": ("Segoe UI", 10, "bold"), "relief": "flat", "cursor": "hand2", "pady": 6}

        tk.Label(parent, text="Scheduled Reminders", bg="#2b2d31", fg="white",
                 font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=4, pady=(12, 4))

        frame = tk.Frame(parent, bg="#2b2d31")
        frame.grid(row=1, column=0, columnspan=4, padx=12, pady=6)

        self.rem_listbox = tk.Listbox(frame, width=60, height=8, bg="#1e1f22", fg="white",
                                      selectbackground="#5865f2", font=("Consolas", 10),
                                      activestyle="none", relief="flat")
        self.rem_listbox.pack(side="left", fill="both")
        self.rem_listbox.bind("<<ListboxSelect>>", self.on_rem_select)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.rem_listbox.yview)
        sb.pack(side="right", fill="y")
        self.rem_listbox.config(yscrollcommand=sb.set)

        # Labels
        for col, text in enumerate(["Day", "Time (HH:MM)", "Channel ID", "Message"]):
            tk.Label(parent, text=text, bg="#2b2d31", fg="#b5bac1",
                     font=("Segoe UI", 10)).grid(row=2, column=col, padx=(12 if col == 0 else 4, 4), pady=4, sticky="w")

        self.rem_day_var = tk.StringVar(value="Wednesday")
        self.rem_time_var = tk.StringVar(value="12:00")
        self.rem_channel_var = tk.StringVar()
        self.rem_msg_var = tk.StringVar()

        ttk.Combobox(parent, textvariable=self.rem_day_var, values=DAYS, state="readonly",
                     width=11, font=("Segoe UI", 10)
                     ).grid(row=3, column=0, padx=(12, 4), pady=2, sticky="ew")

        tk.Entry(parent, textvariable=self.rem_time_var, width=10, bg="#1e1f22", fg="white",
                 insertbackground="white", relief="flat", font=("Consolas", 11)
                 ).grid(row=3, column=1, padx=4, pady=2, sticky="ew")

        tk.Entry(parent, textvariable=self.rem_channel_var, width=20, bg="#1e1f22", fg="white",
                 insertbackground="white", relief="flat", font=("Consolas", 11)
                 ).grid(row=3, column=2, padx=4, pady=2, sticky="ew")

        tk.Entry(parent, textvariable=self.rem_msg_var, width=30, bg="#1e1f22", fg="white",
                 insertbackground="white", relief="flat", font=("Consolas", 11)
                 ).grid(row=3, column=3, padx=(4, 12), pady=2, sticky="ew")

        bf = tk.Frame(parent, bg="#2b2d31")
        bf.grid(row=4, column=0, columnspan=4, pady=10, padx=12, sticky="ew")

        tk.Button(bf, text="Add / Update", bg="#5865f2", fg="white",
                  command=self.add_or_update_reminder, **btn_opts).pack(side="left", expand=True, fill="x", padx=(0, 4))
        tk.Button(bf, text="Delete", bg="#ed4245", fg="white",
                  command=self.delete_reminder, **btn_opts).pack(side="left", expand=True, fill="x", padx=(4, 4))
        tk.Button(bf, text="Clear", bg="#4f545c", fg="white",
                  command=self.clear_rem_fields, **btn_opts).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.refresh_rem_list()

    # ------------------------------------------------------------------ Commands logic

    def refresh_cmd_list(self):
        self.cmd_listbox.delete(0, "end")
        cmds = load_commands()
        for cmd, resp in cmds.items():
            self.cmd_listbox.insert("end", f"!{cmd:<20} {resp}")
        self._cmds_cache = cmds

    def on_cmd_select(self, _=None):
        sel = self.cmd_listbox.curselection()
        if not sel:
            return
        cmd = list(self._cmds_cache.keys())[sel[0]]
        self.cmd_var.set(cmd)
        self.resp_var.set(self._cmds_cache[cmd])

    def add_or_update_cmd(self):
        cmd = self.cmd_var.get().strip().lstrip("!").lower()
        resp = self.resp_var.get().strip()
        if not cmd or not resp:
            messagebox.showwarning("Missing input", "Fill in both the command and the response.")
            return
        cmds = load_commands()
        cmds[cmd] = resp
        save_commands(cmds)
        self.refresh_cmd_list()
        self.clear_cmd_fields()
        self.set_status(f'Saved "!{cmd}"')

    def delete_cmd(self):
        cmd = self.cmd_var.get().strip().lstrip("!").lower()
        if not cmd:
            messagebox.showwarning("No selection", "Select a command first.")
            return
        cmds = load_commands()
        if cmd not in cmds:
            messagebox.showwarning("Not found", f'Command "!{cmd}" does not exist.')
            return
        if not messagebox.askyesno("Confirm", f'Delete "!{cmd}"?'):
            return
        del cmds[cmd]
        save_commands(cmds)
        self.refresh_cmd_list()
        self.clear_cmd_fields()
        self.set_status(f'Deleted "!{cmd}"')

    def clear_cmd_fields(self):
        self.cmd_var.set("")
        self.resp_var.set("")
        self.cmd_listbox.selection_clear(0, "end")

    # ------------------------------------------------------------------ Reminders logic

    def refresh_rem_list(self):
        self.rem_listbox.delete(0, "end")
        self._reminders_cache = load_reminders()
        for r in self._reminders_cache:
            day = DAYS[r["day"]]
            self.rem_listbox.insert("end", f"{day:<12} {r['time']}  #{r['channel_id']}  {r['message']}")

    def on_rem_select(self, _=None):
        sel = self.rem_listbox.curselection()
        if not sel:
            return
        r = self._reminders_cache[sel[0]]
        self.rem_day_var.set(DAYS[r["day"]])
        self.rem_time_var.set(r["time"])
        self.rem_channel_var.set(str(r["channel_id"]))
        self.rem_msg_var.set(r["message"])

    def add_or_update_reminder(self):
        day_name = self.rem_day_var.get()
        time_str = self.rem_time_var.get().strip()
        channel = self.rem_channel_var.get().strip()
        msg = self.rem_msg_var.get().strip()

        if not all([day_name, time_str, channel, msg]):
            messagebox.showwarning("Missing input", "Fill in all fields.")
            return

        try:
            h, m = map(int, time_str.split(":"))
            assert 0 <= h <= 23 and 0 <= m <= 59
        except Exception:
            messagebox.showwarning("Invalid time", "Use HH:MM format, e.g. 12:00")
            return

        try:
            channel_id = int(channel)
        except ValueError:
            messagebox.showwarning("Invalid channel ID", "Channel ID must be a number.")
            return

        day_idx = DAYS.index(day_name)
        reminders = load_reminders()

        # Check if selected item to update
        sel = self.rem_listbox.curselection()
        new_entry = {"day": day_idx, "time": time_str, "channel_id": channel_id, "message": msg}
        if sel:
            reminders[sel[0]] = new_entry
        else:
            reminders.append(new_entry)

        save_reminders(reminders)
        self.refresh_rem_list()
        self.clear_rem_fields()
        self.set_status(f"Saved reminder for {day_name} at {time_str}")

    def delete_reminder(self):
        sel = self.rem_listbox.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a reminder first.")
            return
        if not messagebox.askyesno("Confirm", "Delete this reminder?"):
            return
        reminders = load_reminders()
        reminders.pop(sel[0])
        save_reminders(reminders)
        self.refresh_rem_list()
        self.clear_rem_fields()
        self.set_status("Reminder deleted.")

    def clear_rem_fields(self):
        self.rem_day_var.set("Wednesday")
        self.rem_time_var.set("12:00")
        self.rem_channel_var.set("")
        self.rem_msg_var.set("")
        self.rem_listbox.selection_clear(0, "end")

    # ------------------------------------------------------------------ Deploy

    def deploy(self):
        repo_dir = os.path.dirname(os.path.realpath(__file__))
        try:
            result = subprocess.run(
                ["git", "add", "."], cwd=repo_dir,
                capture_output=True, text=True
            )
            if result.returncode != 0:
                messagebox.showerror("Deploy failed", f"git add failed in:\n{repo_dir}\n\n{result.stderr}")
                return
            result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir)
            if result.returncode == 0:
                self.set_status("No changes to deploy.")
                return
            subprocess.run(["git", "commit", "-m", "Update bot data"], cwd=repo_dir, check=True)
            subprocess.run(["git", "push"], cwd=repo_dir, check=True)
            self.set_status("Deployed! Railway will redeploy automatically.")
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Deploy failed", str(e))

    def set_status(self, msg):
        self.status.config(text=msg)
        self.after(4000, lambda: self.status.config(text=""))


if __name__ == "__main__":
    app = ManagerApp()
    app.mainloop()
