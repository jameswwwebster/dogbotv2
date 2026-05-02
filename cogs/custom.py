"""Existing data-driven custom commands from `commands.json` (e.g. !dog, !cat).
Kept as prefix-style commands so the existing tkinter manager.py workflow
keeps working: edit JSON, redeploy, commands update.
"""

from __future__ import annotations

import json
import os

import discord
from discord.ext import commands

COMMANDS_FILE = "commands.json"


def load_custom_commands() -> dict:
    if not os.path.exists(COMMANDS_FILE):
        return {}
    with open(COMMANDS_FILE, "r") as f:
        return json.load(f)


class CustomCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return
        if not message.content.startswith("!"):
            return
        trigger = message.content[1:].lower().strip()
        # The static `!help` command below takes priority over any commands.json entry.
        if trigger == "help":
            return
        custom_cmds = load_custom_commands()
        if trigger in custom_cmds:
            await message.channel.send(custom_cmds[trigger])

    @commands.command(name="help")
    async def help_command(self, ctx: commands.Context):
        """List the dynamic commands.json entries (the !-prefix ones)."""
        custom_cmds = load_custom_commands()
        if not custom_cmds:
            await ctx.send("No custom commands yet. Use `/help` for slash commands.")
            return
        lines = [f"`!{cmd}` — {resp}" for cmd, resp in custom_cmds.items()]
        await ctx.send("**Prefix commands:**\n" + "\n".join(lines) + "\n\nUse `/help` to see slash commands.")


def setup(bot: commands.Bot):
    bot.add_cog(CustomCommands(bot))
