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

COMMANDS_FILE          = "commands.json"
REMINDERS_FILE         = "reminders.json"
QUESTIONS_FILE         = "questions.json"
FEATURES_FILE          = "features.json"
PUSH_MESSAGES_FILE     = "push_messages.json"
PENDING_REMINDERS_FILE = "pending_reminders.json"
GIVEAWAYS_FILE         = "giveaways.json"


def load_custom_commands():
    if not os.path.exists(COMMANDS_FILE):
        return {}
    with open(COMMANDS_FILE, "r") as f:
        data = json.load(f)
    # Migrate old plain-string format → {"response": ..., "mod_only": false}
    return {cmd: (val if isinstance(val, dict) else {"response": val, "mod_only": False})
            for cmd, val in data.items()}


def load_features():
    defaults = {
        "gmt_offset": 0, "rng_enabled": False,
        "daily_question_enabled": False,
        "daily_question_time": "10:00",
        "daily_question_channel": 472851820448972800,
    }
    if not os.path.exists(FEATURES_FILE):
        return defaults
    with open(FEATURES_FILE, "r") as f:
        data = json.load(f)
    for k, v in defaults.items():
        data.setdefault(k, v)
    return data


_questions_cache = None
_questions_mtime = 0.0


def load_questions():
    global _questions_cache, _questions_mtime
    if not os.path.exists(QUESTIONS_FILE):
        return {"command": "", "questions": []}
    mtime = os.path.getmtime(QUESTIONS_FILE)
    if _questions_cache is None or mtime != _questions_mtime:
        with open(QUESTIONS_FILE, "r") as f:
            _questions_cache = json.load(f)
        _questions_mtime = mtime
    return _questions_cache


def load_pending_reminders():
    if not os.path.exists(PENDING_REMINDERS_FILE):
        return []
    with open(PENDING_REMINDERS_FILE, "r") as f:
        return json.load(f)


def save_pending_reminders(data):
    with open(PENDING_REMINDERS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def load_giveaways():
    if not os.path.exists(GIVEAWAYS_FILE):
        return []
    with open(GIVEAWAYS_FILE, "r") as f:
        return json.load(f)


def save_giveaways(data):
    with open(GIVEAWAYS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def _update_giveaway_entry(entry):
    giveaways = load_giveaways()
    for i, g in enumerate(giveaways):
        if g["channel_id"] == entry["channel_id"] and g["end_at"] == entry["end_at"]:
            giveaways[i] = entry
            break
    save_giveaways(giveaways)


def _remove_giveaway_entry(entry):
    save_giveaways([g for g in load_giveaways()
                    if not (g["channel_id"] == entry["channel_id"]
                            and g["end_at"] == entry["end_at"])])


async def _run_giveaway(entry):
    channel = bot.get_channel(entry["channel_id"])
    if not channel:
        print(f"[Giveaway] Channel {entry['channel_id']} not found.")
        _remove_giveaway_entry(entry)
        return

    now_ts = datetime.now(timezone.utc).timestamp()

    if not entry.get("message_id"):
        # If the giveaway already expired before the bot could post it, silently drop it
        if entry["end_at"] <= now_ts:
            print(f"[Giveaway] Skipping already-expired giveaway: {entry['prize']}")
            _remove_giveaway_entry(entry)
            return
        end_ts = int(entry["end_at"])
        # Search channel history for an existing message in case of a redeploy mid-giveaway
        existing = None
        async for m in channel.history(limit=50):
            if m.author == bot.user and f"<t:{end_ts}:" in m.content and entry["prize"] in m.content:
                existing = m
                break
        if existing:
            print(f"[Giveaway] Reattached to existing message for: {entry['prize']}")
            entry["message_id"] = existing.id
            _update_giveaway_entry(entry)
        else:
            msg = await channel.send(
                f"🎉 **GIVEAWAY** 🎉\n"
                f"**Prize:** {entry['prize']}\n"
                f"**Ends:** <t:{end_ts}:F> (<t:{end_ts}:R>)\n"
                f"React with 🎉 to enter!"
            )
            await msg.add_reaction("🎉")
            entry["message_id"] = msg.id
            _update_giveaway_entry(entry)

    delay = entry["end_at"] - datetime.now(timezone.utc).timestamp()
    if delay > 0:
        await asyncio.sleep(delay)

    try:
        msg = await channel.fetch_message(entry["message_id"])
    except (discord.NotFound, discord.HTTPException):
        _remove_giveaway_entry(entry)
        return

    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    entrants = [u async for u in reaction.users() if not u.bot] if reaction else []
    if not entrants:
        await channel.send(f"🎉 The giveaway for **{entry['prize']}** ended with no entries!")
    else:
        winner = random.choice(entrants)
        await channel.send(f"🎉 Congratulations {winner.mention}! You won **{entry['prize']}**!")

    _remove_giveaway_entry(entry)


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


def has_mod_role(member):
    mod_role = load_features().get("mod_role", "").strip().lower()
    if not mod_role:
        return True  # no restriction set
    return any(role.name.lower() == mod_role for role in member.roles)


def resolve_text(text, guild):
    text = resolve_emojis(text, guild)
    text = resolve_mentions(text, guild)
    return text


_active_reminders = {}  # user_id -> count of active !remindme timers

REMINDME_MAX = 3  # max concurrent reminders per user


async def _fire_reminder(user_id, channel_id, message, delay_seconds):
    """Sleep then send a reminder, then clean up the pending file and counter."""
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    channel = bot.get_channel(channel_id)
    if channel:
        user = bot.get_user(user_id)
        mention = user.mention if user else f"<@{user_id}>"
        await channel.send(f"⏰ {mention} {message}")
    # Remove this entry from the persistent file
    pending = load_pending_reminders()
    pending = [r for r in pending
               if not (r["user_id"] == user_id and r["message"] == message)]
    save_pending_reminders(pending)
    # Decrement counter
    if _active_reminders.get(user_id, 0) > 0:
        _active_reminders[user_id] -= 1


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

    # Daily question auto-post
    if features.get("daily_question_enabled"):
        try:
            dq_h, dq_m = map(int, features.get("daily_question_time", "10:00").split(":"))
        except Exception:
            dq_h, dq_m = 10, 0
        if now.hour == dq_h and now.minute == dq_m and "daily_q" not in _reminders_sent:
            _reminders_sent["daily_q"] = True
            channel = bot.get_channel(int(features.get("daily_question_channel", 472851820448972800)))
            if channel:
                questions = load_questions().get("questions", [])
                if questions:
                    q = random.choice(questions)
                    await channel.send(f"❓ **{q['question']}**\n||{q['answer']}||")

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

    # Restore any !remindme timers that survived a redeploy
    now_ts = datetime.now(timezone.utc).timestamp()
    surviving = []
    for entry in load_pending_reminders():
        remaining = entry["fire_at"] - now_ts
        if remaining <= 0:
            # Already overdue — fire immediately
            asyncio.create_task(_fire_reminder(
                entry["user_id"], entry["channel_id"], entry["message"], 0))
        else:
            _active_reminders[entry["user_id"]] = (
                _active_reminders.get(entry["user_id"], 0) + 1)
            asyncio.create_task(_fire_reminder(
                entry["user_id"], entry["channel_id"], entry["message"], remaining))
            surviving.append(entry)
    if surviving:
        print(f"[Reminders] Restored {len(surviving)} pending !remindme timer(s).")

    # Start any queued giveaways
    for entry in load_giveaways():
        asyncio.create_task(_run_giveaway(entry))

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
            entry = custom_cmds[trigger]
            if entry.get("mod_only") and not has_mod_role(message.author):
                return
            text = resolve_text(entry["response"], message.guild)
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


_GROUP_BOSSES = [
    "Amascut, the Devourer",
    "The Ambassador",
    "The Barrows: Rise of the Six",
    "Black Stone Dragon",
    "Kalphite King",
    "Nakatra, Devourer Eternal",
    "Nex",
    "Nex: Angel of Death",
    "Seiryu, the Azure Serpent",
    "Solak, Guardian of the Grove",
    "Vorago",
    "Zamorak, Lord of Chaos",
]


@bot.command(name="pickgroupboss")
async def pickgroupboss_cmd(ctx):
    if not load_features().get("pickgroupboss_enabled"):
        return
    boss = random.choice(_GROUP_BOSSES)
    await ctx.send(f"⚔️ Tonight's group boss: **{boss}**!")


_FLIRTS = [
    # ── Bad / Funny ────────────────────────────────────────────────────────────
    "{sender} tried to flirt with {target}, it failed horribly.",
    "{sender} tried to flirt with {target}, nice try but a bit pathetic.",
    "{sender} tried to flirt with {target}, they got friendzoned instantly.",
    "{sender} tried to flirt with {target}, even the bot felt second-hand embarrassment.",
    "{sender} tried to flirt with {target}, and somehow made it weird.",
    "{sender} tried to flirt with {target}, the silence was deafening.",
    "{sender} tried to flirt with {target}, they've been blocked.",
    "{sender} tried to flirt with {target}, please never do that again.",
    "{sender} tried to flirt with {target}, their parents would be disappointed.",
    "{sender} tried to flirt with {target}, but {target} already has a duo partner.",
    # ── Smooth / Funny ─────────────────────────────────────────────────────────
    "{sender} slid into {target}'s DMs like a pro.",
    "{sender} shot their shot with {target}, respect the confidence.",
    "{sender} asked {target} to Netflix and chill. Bold move.",
    # ── RuneScape Themed ───────────────────────────────────────────────────────
    "{sender} tried to flirt with {target}, but got a 'not interested' faster than a Jad pray flick.",
    "{sender} tried to flirt with {target}, they have 99 Strength but 1 Charisma.",
    '{sender} tried to flirt with {target}. "Are you a daily? Because I\'d do you every day."',
    '{sender} tried to flirt with {target}. "Want to duo Solak sometime? 👀"',
    '{sender} tried to flirt with {target}. "I\'d spend all my bank on you and still think it was worth it."',
    '{sender} tried to flirt with {target}. "You\'re rarer than a Hazelmere\'s signet ring drop."',
    '{sender} tried to flirt with {target}. "Are you a loot beam? Because you light up my world."',
    '{sender} tried to flirt with {target}. "I\'d give up my max cape for you."',
    '{sender} tried to flirt with {target}. "You must be a Trim comp cape, because you\'re the whole package."',
    '{sender} tried to flirt with {target}. "I\'d camp Nex for a week just to impress you."',
    '{sender} tried to flirt with {target}. "Are you a bank preset? Because I\'d save you."',
    '{sender} tried to flirt with {target}. "I\'d put you on my friends list any day."',
    '{sender} tried to flirt with {target}. "You\'re the only boss I\'d skip a reaper task for."',
    '{sender} tried to flirt with {target}. "I\'d use my last deathtouched dart on you. That\'s love."',
    '{sender} tried to flirt with {target}. "You\'re not just a 10/10, you\'re a 120/120."',
    '{sender} tried to flirt with {target}. "I\'d follow you into the Wilderness without insurance."',
    '{sender} tried to flirt with {target}. "Are you a boss pet? Because the odds of finding someone like you are astronomical."',
    '{sender} tried to flirt with {target}. "You\'re the only grind I actually enjoy."',
    '{sender} tried to flirt with {target}. "I\'d logout at Lumbridge just to walk you home."',
    '{sender} tried to flirt with {target}. "Are you a Slayer task? Because I\'d cancel everyone else for you."',
    '{sender} tried to flirt with {target}. "You\'re the only thing I\'d AFK for hours."',
    '{sender} tried to flirt with {target}. "I\'d trade my entire bank for one date with you."',
    '{sender} tried to flirt with {target}. "You hit harder than a Raksha shadow pool."',
    '{sender} tried to flirt with {target}. "Are you Vorago? Because you\'re out of my league but I keep trying anyway."',
    '{sender} tried to flirt with {target}. "I\'d do 1000 Telos kills just to get your attention."',
    '{sender} tried to flirt with {target}. "You\'re better than any drop I\'ve ever gotten."',
    '{sender} tried to flirt with {target}. "I\'d turn off my loot beam so nobody else notices you."',
    '{sender} tried to flirt with {target}. "You must be a Zamorak solo, because you\'re worth every wipe."',
    '{sender} tried to flirt with {target}. "I\'ve got 99 Farming but I still couldn\'t grow anything as beautiful as you."',
    '{sender} tried to flirt with {target}. "Are you the GE? Because everyone wants a piece of you."',
    '{sender} tried to flirt with {target}. "I\'d walk from Lumbridge to Prif just to see you online."',
    '{sender} tried to flirt with {target}. "You\'re the reason I log in every day."',
    '{sender} tried to flirt with {target}. "I\'d lend you my best gear with no timer."',
]


@bot.command(name="flirt")
async def flirt_cmd(ctx, target: discord.Member = None):
    if not load_features().get("flirt_enabled"):
        return
    if not target:
        await ctx.send("Usage: `!flirt @user`")
        return
    flirt = random.choice(_FLIRTS)
    await ctx.send(flirt.format(sender=ctx.author.mention, target=target.mention))


@bot.command(name="hug")
async def hug_cmd(ctx, target: discord.Member = None):
    if not load_features().get("hug_enabled"):
        return
    if not target:
        await ctx.send("Mention someone to hug! e.g. `!hug @user`")
        return
    await ctx.send(f"{ctx.author.mention} hugs {target.mention}! 🤗")


@bot.command(name="spank")
async def spank_cmd(ctx, target: discord.Member = None):
    if not load_features().get("spank_enabled"):
        return
    if not target:
        await ctx.send("Mention someone to spank! e.g. `!spank @user`")
        return
    await ctx.send(f"🥵🥵 {ctx.author.mention} spanks {target.mention}! 🥵🥵")


@bot.command(name="rerollgiveaway")
async def rerollgiveaway_cmd(ctx, message_id: int = None):
    if not has_mod_role(ctx.author):
        await ctx.send("You need the moderator role to use this command.")
        return
    if not message_id:
        await ctx.send("Usage: `!rerollgiveaway <message_id>`")
        return
    try:
        msg = await ctx.channel.fetch_message(message_id)
    except discord.NotFound:
        await ctx.send("❌ Message not found in this channel.")
        return
    except discord.HTTPException:
        await ctx.send("❌ Failed to fetch the message.")
        return
    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    entrants = [u async for u in reaction.users() if not u.bot] if reaction else []
    if not entrants:
        await ctx.send("🎉 No valid entries found on that message.")
        return
    # Extract prize from the original giveaway message
    prize = None
    for line in msg.content.splitlines():
        if line.startswith("**Prize:**"):
            prize = line.replace("**Prize:**", "").strip()
            break
    winner = random.choice(entrants)
    prize_text = f" You won **{prize}**!" if prize else ""
    await ctx.send(f"🎉 Reroll! Congratulations {winner.mention}!{prize_text}")


@bot.command(name="clear")
async def clear_cmd(ctx, amount: int = None):
    if not load_features().get("clear_enabled"):
        return
    if not has_mod_role(ctx.author):
        await ctx.send("You need the moderator role to use this command.")
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
    if not has_mod_role(ctx.author):
        await ctx.send("You need the moderator role to use this command.")
        return
    if not minutes or not reminder:
        await ctx.send("Usage: `!remindme <minutes> <message>`")
        return
    if minutes < 1 or minutes > 1440:
        await ctx.send("Minutes must be between 1 and 1440.")
        return
    uid = ctx.author.id
    if _active_reminders.get(uid, 0) >= REMINDME_MAX:
        await ctx.send(f"You already have {REMINDME_MAX} active reminders. Wait for one to fire.")
        return
    _active_reminders[uid] = _active_reminders.get(uid, 0) + 1
    fire_at = datetime.now(timezone.utc).timestamp() + minutes * 60
    pending = load_pending_reminders()
    pending.append({"user_id": uid, "channel_id": ctx.channel.id,
                    "message": reminder, "fire_at": fire_at})
    save_pending_reminders(pending)
    s = "s" if minutes != 1 else ""
    await ctx.send(f"⏰ Got it! I'll remind you in {minutes} minute{s}.")
    asyncio.create_task(_fire_reminder(uid, ctx.channel.id, reminder, minutes * 60))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument — check the command usage with `!commands`.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("User not found. Make sure you @mention them.")
    elif isinstance(error, commands.CommandInvokeError):
        await ctx.send(f"Something went wrong: {error.original}")


bot.run(os.getenv("DISCORD_TOKEN"))
