# dogbotv2

A small Discord bot for an RS3 community.

## Commands

### Slash commands (RS3)

| Command | Description |
|---|---|
| `/stats player:<name>` | Hiscores lookup — total level, XP, rank, and per-skill levels. |
| `/profile player:<name>` | Combined RuneMetrics + hiscores summary plus the player's recent activity feed. |
| `/price item:<name>` | Current Grand Exchange price, today's change, and 30-day trend for an item. |
| `/next [event]` | Next RS3 reset / event time. With no argument, lists every reset; pass `event:` to limit it. |

### Prefix commands (legacy)

The `!commands.json` system still works — edit that file (the existing tkinter
`manager.py` GUI is a convenient way) and redeploy. `!help` lists what's
defined there.

## Configuration

Environment variables:

| Var | Required | Notes |
|---|---|---|
| `DISCORD_TOKEN` | yes | Bot token from the Discord Developer Portal. |
| `GITHUB_TOKEN` | no  | Legacy — only used by removed scoring features; safe to omit. |

## Running locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
echo "DISCORD_TOKEN=…" > .env
python bot.py
```

## Tests

```bash
python -m unittest discover tests
```

Pure-Python tests for the RS3 parsers and reset arithmetic — no network
required.

## Deploying

The repo is set up for any of: Render (Background Worker, Docker
runtime), Fly.io (Dockerfile), Heroku-likes (Procfile), or anything that
honours `nixpacks.toml`.
