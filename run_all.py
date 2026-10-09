"""Run one bot.py process per Discord server inside a single worker.

The main server (SERVER_ID=rs) uses DISCORD_TOKEN and, optionally, GUILD_ID.
Each extra server is enabled by setting DISCORD_TOKEN_<NAME>, with an optional
GUILD_ID_<NAME>. For example DISCORD_TOKEN_OSRS + GUILD_ID_OSRS starts a
process with SERVER_ID=osrs, which reads the *_osrs.json files.

If a bot process exits it is restarted on its own (with backoff), so one
server's problem doesn't take the others down.
"""
import os
import signal
import subprocess
import sys
import time

_DIR = os.path.dirname(os.path.realpath(__file__))
BOT_SCRIPT = os.path.join(_DIR, "bot.py")
MAX_BACKOFF = 300  # seconds


def discover_servers():
    servers = {}
    if os.getenv("DISCORD_TOKEN"):
        servers["rs"] = {
            "DISCORD_TOKEN": os.environ["DISCORD_TOKEN"],
            "GUILD_ID": os.getenv("GUILD_ID", "0"),
        }
    for key, value in os.environ.items():
        if key.startswith("DISCORD_TOKEN_") and value:
            name = key[len("DISCORD_TOKEN_"):]
            servers[name.lower()] = {
                "DISCORD_TOKEN": value,
                "GUILD_ID": os.getenv(f"GUILD_ID_{name}", "0"),
            }
    return servers


def start(server_id, cfg):
    env = dict(os.environ, SERVER_ID=server_id, **cfg)
    print(f"[launcher] Starting bot for '{server_id}'", flush=True)
    return subprocess.Popen([sys.executable, BOT_SCRIPT], env=env, cwd=_DIR)


def main():
    servers = discover_servers()
    if not servers:
        sys.exit("[launcher] No DISCORD_TOKEN or DISCORD_TOKEN_<NAME> set.")

    procs, backoff, restart_at = {}, {}, {}
    for sid, cfg in servers.items():
        procs[sid] = start(sid, cfg)
        backoff[sid] = 5
        restart_at[sid] = time.time()

    stopping = False

    def shutdown(signum, _frame):
        nonlocal stopping
        stopping = True
        for p in procs.values():
            if p and p.poll() is None:
                p.send_signal(signum)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while not stopping:
        now = time.time()
        for sid, p in procs.items():
            if p is not None and p.poll() is not None:
                print(f"[launcher] '{sid}' exited with code {p.returncode}; "
                      f"restarting in {backoff[sid]}s", flush=True)
                procs[sid] = None
                restart_at[sid] = now + backoff[sid]
                backoff[sid] = min(backoff[sid] * 2, MAX_BACKOFF)
            elif p is None and now >= restart_at[sid]:
                procs[sid] = start(sid, servers[sid])
                restart_at[sid] = now
            elif p is not None and now - restart_at[sid] > 600:
                backoff[sid] = 5  # stayed up 10 minutes: reset backoff
        time.sleep(1)

    for p in procs.values():
        if p:
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
