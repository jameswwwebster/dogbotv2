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

COMMANDS_FILE = "commands.json"
REMINDERS_FILE = "reminders.json"
QUESTIONS_FILE = "questions.json"
FEATURES_FILE  = "features.json"


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


def resolve_emojis(text, guild):
    """Replace :emojiname: with the proper <:name:id> Discord syntax."""
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
    """Replace @Name with proper role/member mention syntax."""
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


@tasks.loop(minutes=1)
async def check_reminders():
    features = load_features()
    offset = features.get("gmt_offset", 0)
    now = datetime.now(timezone.utc) + timedelta(hours=offset)
    for reminder in load_reminders():
        h, m = map(int, reminder["time"].split(":"))
        if now.weekday() == reminder["day"] and now.hour == h and now.minute == m:
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


@bot.command(name="help")
async def help_command(ctx):
    custom_cmds = load_custom_commands()
    if not custom_cmds:
        await ctx.send("No custom commands yet.")
        return
    lines = [f"`!{cmd}` — {resp}" for cmd, resp in custom_cmds.items()]
    await ctx.send("**Available commands:**\n" + "\n".join(lines))


bot.run(os.getenv("DISCORD_TOKEN"))
