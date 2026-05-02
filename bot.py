"""dogbotv2 entry point.

Loads cogs (custom prefix commands + RS3 slash commands), wires a
CommandNotFound suppressor so unknown `!foo` invocations don't spam
stderr, then connects to Discord.
"""

from __future__ import annotations

import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()


def make_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
        try:
            synced = await bot.sync_commands()  # py-cord 2.x: registers slash commands
            print(f"Synced slash commands ({len(synced) if synced else 'cached'} entries).")
        except Exception as e:  # noqa: BLE001 — log and keep going; bot still useful
            print(f"Slash command sync failed: {e}")

    @bot.event
    async def on_command_error(ctx: commands.Context, error: Exception):
        # `!foo` for a non-existent command is normal user noise — swallow it.
        if isinstance(error, commands.CommandNotFound):
            return
        # Surface anything else; preserves the prior debugging behaviour.
        raise error

    bot.load_extension("cogs.custom")
    bot.load_extension("cogs.rs3")
    return bot


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN not set.")
    bot = make_bot()
    bot.run(token)


if __name__ == "__main__":
    main()
