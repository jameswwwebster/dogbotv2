import asyncio
import discord
import json
import os
import re
import random
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

COMMANDS_FILE      = "commands.json"
REMINDERS_FILE     = "reminders.json"
QUESTIONS_FILE     = "questions.json"
FEATURES_FILE      = "features.json"
PUSH_MESSAGES_FILE = "push_messages.json"


def load_custom_commands():
    if not os.path.exists(COMMANDS_FILE):
        return {}
    with open(COMMANDS_FILE, "r") as f:
        return json.load(f)


def load_features():
    defaults = {"gmt_offset": 0, "rng_enabled": False}
    if not os.path.exists(FEATURES_FILE):
        return defaults
    with open(FEATURES_FILE, "r") as f:
        data = json.load(f)
    for k, v in defaults.items():
        data.setdefault(k, v)
    return data


def load_questions():
    if not os.path.exists(QUESTIONS_FILE):
        return {"command": "", "questions": []}
    with open(QUESTIONS_FILE, "r") as f:
        return json.load(f)


def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return []
    with open(REMINDERS_FILE, "r") as f:
        return json.load(f)


def load_push_messages():
    if not os.path.exists(PUSH_MESSAGES_FILE):
        return []
    with open(PUSH_MESSAGES_FILE, "r") as f:
        return json.load(f)


def save_push_messages(data):
    with open(PUSH_MESSAGES_FILE, "w") as f:
        json.dump(data, f, indent=4)


def resolve_emojis(text, guild):
    if guild is None:
        return text

    def replace_emoji(match):
        name = match.group(1)
        for emoji in guild.emojis:
            if emoji.name.lower() == name.lower():
                return str(emoji)
        return match.group(0)

    return re.sub(r':([a-zA-Z0-9_]+):', replace_emoji, text)


def resolve_mentions(text, guild):
    if guild is None:
        return text

    def replace_mention(match):
        name = match.group(1).lower()
        for role in guild.roles:
            if role.name.lower() == name:
                return role.mention
        for member in guild.members:
            if member.name.lower() == name or member.display_name.lower() == name:
                return member.mention
        return match.group(0)

    return re.sub(r'@([^\s<>@#&!]+)', replace_mention, text)


def resolve_text(text, guild):
    text = resolve_emojis(text, guild)
    text = resolve_mentions(text, guild)
    return text


_reminders_sent = {}  # tracks which reminders fired this minute to avoid duplicates

@tasks.loop(seconds=30)
async def check_reminders():
    global _reminders_sent
    features = load_features()
    offset = features.get("gmt_offset", 0)
    now = datetime.now(timezone.utc) + timedelta(hours=offset)

    # Reset sent log at the start of each new minute
    current_minute = (now.weekday(), now.hour, now.minute)
    if _reminders_sent.get("_minute") != current_minute:
        _reminders_sent = {"_minute": current_minute}

    for i, reminder in enumerate(load_reminders()):
        h, m = map(int, reminder["time"].split(":"))
        if now.weekday() == reminder["day"] and now.hour == h and now.minute == m:
            if i in _reminders_sent:
                continue  # already sent this minute
            _reminders_sent[i] = True
            channel = bot.get_channel(reminder["channel_id"])
            if channel:
                text = resolve_text(reminder["message"], channel.guild)
                await channel.send(text, allowed_mentions=discord.AllowedMentions(roles=True, everyone=True, users=True))
            else:
                print(f"[Reminders] Channel {reminder['channel_id']} not found.")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    check_reminders.start()

    # Send and clear any queued push messages
    pending = load_push_messages()
    if pending:
        for entry in pending:
            channel = bot.get_channel(entry["channel_id"])
            if channel:
                text = resolve_text(entry["message"], channel.guild)
                await channel.send(text, allowed_mentions=discord.AllowedMentions(roles=True, everyone=True, users=True))
            else:
                print(f"[Push] Channel {entry['channel_id']} not found.")
        save_push_messages([])


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.content.startswith("!"):
        trigger = message.content[1:].lower().strip()
        features = load_features()

        # RNG command
        if features.get("rng_enabled") and trigger == "rng":
            number = random.randint(1, 100)
            await message.channel.send(f"DogBot rolled a {number}!")
            return

        # Question command
        q_data = load_questions()
        q_cmd = q_data.get("command", "").lower().lstrip("!")
        if q_cmd and trigger == q_cmd:
            questions = q_data.get("questions", [])
            if not questions:
                await message.channel.send("No questions available yet.")
                return
            entry = random.choice(questions)
            msg = f"Question: {entry['question']} -> Answer ||{entry['answer']}||"
            await message.channel.send(msg)
            return

        # Custom commands
        custom_cmds = load_custom_commands()
        if trigger in custom_cmds:
            text = resolve_text(custom_cmds[trigger], message.guild)
            await message.channel.send(text, allowed_mentions=discord.AllowedMentions(roles=True, everyone=True, users=True))
            return

    await bot.process_commands(message)


@bot.command(name="commands")
async def commands_list(ctx):
    features  = load_features()
    custom    = load_custom_commands()
    q_data    = load_questions()
    lines     = ["**Bot Commands**"]

    if custom:
        lines.append("\n**Custom:**")
        for cmd, resp in custom.items():
            short = resp[:60] + "…" if len(resp) > 60 else resp
            lines.append(f"`!{cmd}` — {short}")

    fun = []
    if features.get("rng_enabled"):
        fun.append("`!rng` — Rolls a random number between 1–100")
    if features.get("hug_enabled"):
        fun.append("`!hug @user` — Give someone a hug")
    if q_data.get("command"):
        fun.append(f"`!{q_data['command']}` — Random trivia question with spoiler answer")
    if fun:
        lines.append("\n**Fun:**")
        lines.extend(fun)

    util = []
    if features.get("clear_enabled"):
        util.append("`!clear <amount>` — Delete the last X messages (max 100)")
    if features.get("remindme_enabled"):
        util.append("`!remindme <minutes> <message>` — Get a personal reminder")
    if util:
        lines.append("\n**Utility:**")
        lines.extend(util)

    await ctx.send("\n".join(lines))


@bot.command(name="hug")
async def hug_cmd(ctx, target: discord.Member = None):
    if not load_features().get("hug_enabled"):
        return
    if not target:
        await ctx.send("Mention someone to hug! e.g. `!hug @user`")
        return
    await ctx.send(f"{ctx.author.mention} hugs {target.mention}! 🤗")


@bot.command(name="clear")
async def clear_cmd(ctx, amount: int = None):
    if not load_features().get("clear_enabled"):
        return
    if not amount or amount < 1:
        await ctx.send("Usage: `!clear <amount>`")
        return
    if amount > 100:
        await ctx.send("Maximum is 100 messages at a time.")
        return
    if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
        await ctx.send("I don't have permission to delete messages in this channel.")
        return
    await ctx.message.delete()
    deleted = await ctx.channel.purge(limit=amount)
    msg = await ctx.send(f"Deleted {len(deleted)} message(s).")
    await asyncio.sleep(3)
    await msg.delete()


@bot.command(name="remindme")
async def remindme_cmd(ctx, minutes: int = None, *, reminder: str = None):
    if not load_features().get("remindme_enabled"):
        return
    if not minutes or not reminder:
        await ctx.send("Usage: `!remindme <minutes> <message>`")
        return
    if minutes < 1 or minutes > 1440:
        await ctx.send("Minutes must be between 1 and 1440.")
        return
    s = "s" if minutes != 1 else ""
    await ctx.send(f"⏰ Got it! I'll remind you in {minutes} minute{s}.")
    await asyncio.sleep(minutes * 60)
    await ctx.send(f"⏰ {ctx.author.mention} {reminder}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument — check the command usage with `!commands`.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("User not found. Make sure you @mention them.")
    elif isinstance(error, commands.CommandInvokeError):
        await ctx.send(f"Something went wrong: {error.original}")


bot.run(os.getenv("DISCORD_TOKEN"))
