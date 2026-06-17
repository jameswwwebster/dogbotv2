import asyncio
import discord
import json
import os
import re
import random
import subprocess
import time
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

COMMANDS_FILE          = "commands.json"
REMINDERS_FILE         = "reminders.json"
QUESTIONS_FILE         = "questions.json"
FEATURES_FILE          = "features.json"
PUSH_MESSAGES_FILE     = "push_messages.json"
PENDING_REMINDERS_FILE = "pending_reminders.json"
GIVEAWAYS_FILE         = "giveaways.json"
QUESTION_TRACKING_FILE = "question_tracking.json"

QUESTION_REACTION_WINDOW = 24 * 60 * 60  # seconds


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
        "eightball_enabled": False,
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


def save_questions(data):
    global _questions_cache, _questions_mtime
    with open(QUESTIONS_FILE, "w") as f:
        json.dump(data, f, indent=4)
    _questions_cache = data
    _questions_mtime = os.path.getmtime(QUESTIONS_FILE)


def load_question_tracking():
    if not os.path.exists(QUESTION_TRACKING_FILE):
        return {}
    with open(QUESTION_TRACKING_FILE, "r") as f:
        return json.load(f)


def save_question_tracking(data):
    with open(QUESTION_TRACKING_FILE, "w") as f:
        json.dump(data, f, indent=4)


def _cleanup_question_tracking():
    """Remove expired entries from the tracking file."""
    now_ts = time.time()
    tracking = load_question_tracking()
    cleaned = {mid: entry for mid, entry in tracking.items() if entry["expires_at"] > now_ts}
    if len(cleaned) != len(tracking):
        save_question_tracking(cleaned)


async def _post_question(channel, entry):
    """Post a question, add reactions, and register it for score tracking."""
    msg = await channel.send(f"❓ **{entry['question']}**\n||{entry['answer']}||")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    tracking = load_question_tracking()
    tracking[str(msg.id)] = {
        "question": entry["question"],
        "expires_at": time.time() + QUESTION_REACTION_WINDOW,
    }
    save_question_tracking(tracking)


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
        end_ts  = int(entry["end_at"])
        winners = int(entry.get("winners", 1))
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
            winner_line = f"**Winners:** {winners}\n" if winners > 1 else ""
            msg = await channel.send(
                f"🎉 **GIVEAWAY** 🎉\n"
                f"**Prize:** {entry['prize']}\n"
                f"{winner_line}"
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
        winners  = int(entry.get("winners", 1))
        picked   = random.sample(entrants, min(winners, len(entrants)))
        mentions = ", ".join(w.mention for w in picked)
        if len(picked) == 1:
            await channel.send(f"🎉 Congratulations {mentions}! You won **{entry['prize']}**!")
        else:
            await channel.send(f"🎉 Congratulations to our {len(picked)} winners: {mentions}! You won **{entry['prize']}**!")

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


_scores_dirty     = False
_last_score_push  = 0.0
SCORE_PUSH_INTERVAL = 3600  # push at most once per hour


def _push_scores_to_github():
    global _scores_dirty, _last_score_push
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("[Scores] GITHUB_TOKEN not set — skipping score push.")
        return
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        if not remote.startswith("https://"):
            print("[Scores] Remote is not HTTPS — skipping score push.")
            return
        authed = remote.replace("https://", f"https://{token}@")
        subprocess.run(["git", "config", "user.email", "dogbot@railway.app"], check=True)
        subprocess.run(["git", "config", "user.name",  "DogBot"],             check=True)
        subprocess.run(["git", "pull", "--rebase", authed, "master"],
                       capture_output=True)
        subprocess.run(["git", "add", QUESTIONS_FILE], check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            print("[Scores] No score changes to push.")
            _scores_dirty = False
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(["git", "commit", "-m", f"Score update — {ts}"], check=True)
        subprocess.run(["git", "push", authed, "master"],                check=True)
        _scores_dirty    = False
        _last_score_push = time.time()
        print("[Scores] Score updates pushed to GitHub.")
    except Exception as e:
        print(f"[Scores] Push failed: {e}")


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
                    await _post_question(channel, q)

    # Hourly score push back to GitHub
    if _scores_dirty and time.time() - _last_score_push > SCORE_PUSH_INTERVAL:
        await asyncio.get_event_loop().run_in_executor(None, _push_scores_to_github)

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
    _cleanup_question_tracking()

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
                if entry.get("is_question"):
                    # Extract question/answer from the formatted message and use _post_question
                    # so reactions are added and score tracking is registered
                    q_data = load_questions()
                    text   = resolve_text(entry["message"], channel.guild)
                    # Find matching question object for tracking
                    q_obj  = next((q for q in q_data.get("questions", [])
                                   if q["question"] in text), None)
                    if q_obj:
                        await _post_question(channel, q_obj)
                    else:
                        await channel.send(text, allowed_mentions=discord.AllowedMentions(roles=True, everyone=True, users=True))
                else:
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
            await _post_question(message.channel, entry)
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


def _update_question_score(question_text, correct_delta=0, incorrect_delta=0):
    global _scores_dirty
    data = load_questions()
    for q in data.get("questions", []):
        if q["question"] == question_text:
            q["correct"]   = max(0, q.get("correct",   0) + correct_delta)
            q["incorrect"] = max(0, q.get("incorrect", 0) + incorrect_delta)
            save_questions(data)
            _scores_dirty = True
            break


@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    tracking = load_question_tracking()
    entry = tracking.get(str(payload.message_id))
    if not entry or time.time() > entry["expires_at"]:
        return
    emoji = str(payload.emoji)
    if emoji == "✅":
        _update_question_score(entry["question"], correct_delta=1)
    elif emoji == "❌":
        _update_question_score(entry["question"], incorrect_delta=1)


@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id:
        return
    tracking = load_question_tracking()
    entry = tracking.get(str(payload.message_id))
    if not entry or time.time() > entry["expires_at"]:
        return
    emoji = str(payload.emoji)
    if emoji == "✅":
        _update_question_score(entry["question"], correct_delta=-1)
    elif emoji == "❌":
        _update_question_score(entry["question"], incorrect_delta=-1)


@bot.command(name="commands")
async def commands_list(ctx):
    features = load_features()
    custom   = load_custom_commands()
    q_data   = load_questions()
    lines    = ["**🐾 DogBot Commands**"]

    # Custom commands
    if custom:
        lines.append("\n**📝 Custom:**")
        for cmd, entry in custom.items():
            tag = " `[mod]`" if entry.get("mod_only") else ""
            lines.append(f"`!{cmd}`{tag}")

    # Fun commands
    fun = []
    if features.get("rng_enabled"):
        fun.append("`!rng` — Random number 1–100")
    if features.get("hug_enabled"):
        fun.append("`!hug @user` — Give someone a hug 🤗")
    if features.get("spank_enabled"):
        fun.append("`!spank @user` — Give someone a spank 🥵")
    if features.get("flirt_enabled"):
        fun.append("`!flirt @user` — Send a random flirt 💘")
    if features.get("kill_enabled"):
        fun.append("`!kill @user` — Attempt to kill someone ☠️")
    if features.get("rps_enabled"):
        fun.append("`!rps <rock/paper/scissors>` — Play against DogBot 🪨📄✂️")
    if features.get("pickgroupboss_enabled"):
        fun.append("`!pickgroupboss` — Pick a random group boss ⚔️")
    if features.get("eightball_enabled"):
        fun.append("`!8ball <question>` — DogBot answers your question 🎱")
    if q_data.get("command"):
        fun.append(f"`!{q_data['command']}` — Random RS trivia question ❓")
    if fun:
        lines.append("\n**🎮 Fun:**")
        lines.extend(fun)

    # Utility commands
    util = []
    if features.get("clear_enabled"):
        util.append("`!clear <amount>` — Delete last X messages (mod only)")
    if features.get("remindme_enabled"):
        util.append("`!remindme <minutes> <message>` — Set a personal reminder ⏰")
    if util:
        lines.append("\n**🔧 Utility:**")
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


@bot.command(name="kill")
async def kill_cmd(ctx, target: discord.Member = None):
    if not load_features().get("kill_enabled"):
        return
    if not target:
        await ctx.send("Usage: `!kill @user`")
        return
    outcome = random.choice([
        f"{ctx.author.mention} tried to kill {target.mention} but killed themselves instead.",
        f"{ctx.author.mention} tried to kill {target.mention} and succeeded, but at what cost?",
        f"{ctx.author.mention} tried to kill {target.mention}. Finally, we got rid of them!",
    ])
    await ctx.send(outcome)


_RPS_EMOJI  = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
_RPS_BEATS  = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
_RPS_ALIAS  = {"r": "rock", "p": "paper", "s": "scissors",
               "stone": "rock", "paper": "paper", "scissor": "scissors"}


@bot.command(name="rps")
async def rps_cmd(ctx, choice: str = None):
    if not load_features().get("rps_enabled"):
        return
    if not choice:
        await ctx.send("Usage: `!rps <rock / paper / scissors>`")
        return
    player = _RPS_ALIAS.get(choice.lower(), choice.lower())
    if player not in _RPS_EMOJI:
        await ctx.send("Choose **rock**, **paper**, or **scissors**.")
        return
    bot_pick = random.choice(["rock", "paper", "scissors"])
    pe, be   = _RPS_EMOJI[player], _RPS_EMOJI[bot_pick]
    if player == bot_pick:
        result = "It's a tie! 🤝"
    elif _RPS_BEATS[player] == bot_pick:
        result = f"{ctx.author.display_name} wins! 🎉"
    else:
        result = "DogBot wins! 🤖"
    await ctx.send(
        f"{pe} **{ctx.author.display_name}** used **{player}** — "
        f"{be} **DogBot** used **{bot_pick}**. {result}"
    )


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


_8BALL_INTROS = [
    "DogBot thinks about your question and answers with",
    "DogBot gazes into the void and concludes",
    "DogBot consults the ancient scrolls and declares",
    "DogBot ponders deeply and has decided",
    "DogBot has thought long and hard, and the answer is",
    "DogBot shakes its head and says",
    "DogBot closes its eyes and whispers",
    "DogBot has spoken:",
    "After much deliberation, DogBot announces",
    "DogBot stares into your soul and responds",
]

_8BALL_ANSWERS = [
    # ── Yes (~50) ──────────────────────────────────────────────────────────────
    "Yes!", "Absolutely!", "Without a doubt.", "Signs point to yes.",
    "It is certain.", "You may rely on it.", "Most likely.", "Outlook good.",
    "100% yes.", "Obviously.", "Of course!", "Definitely!", "Affirmative.",
    "Yep.", "For sure!", "No doubt about it.", "The stars align — yes.",
    "All signs point to yes.", "Undoubtedly.", "A resounding yes!",
    "Positively!", "Confirmed.", "You bet!", "Indeed!", "Oh yeah!", "Totally!",
    "Very likely.", "Almost certainly.", "Big yes energy.", "That's a yes, chief.",
    "The vibes say yes.", "The universe agrees.", "My sources say yes.",
    "Bold of you to ask — yes.", "Fo sho.", "Yessir!", "In every way, yes.",
    "The odds are in your favor.", "I'd bet on yes.", "That's a big yes.",
    "Yeah, no doubt.", "Concentrate and ask again… just kidding, yes.",
    "Certified yes.", "The 8-ball smiles upon you.", "Strongly yes.",
    "Trust the process — yes.", "Bet.", "Aye.", "Heck yes.", "You already know it's yes.",
    # ── No (~45) ───────────────────────────────────────────────────────────────
    "No.", "Absolutely not.", "Don't count on it.", "My reply is no.",
    "My sources say no.", "Outlook not so good.", "Very doubtful.", "Nope.",
    "Nah.", "Not a chance.", "Definitely not.", "No way.", "Not likely.",
    "Hard no.", "Negative.", "Forget about it.", "I wouldn't count on it.",
    "Looks bleak.", "The stars say no.", "Not in this lifetime.", "Doubt it.",
    "That would be a no.", "The universe disagrees.", "Not today.",
    "DogBot weeps — no.", "No, and that's final.", "Signs point to no.",
    "Regrettably, no.", "Unfortunately not.", "Not even close.",
    "Don't hold your breath.", "Nah fam.", "No chance.",
    "My senses say no.", "Negative, ghost rider.", "The vibes say no.",
    "Not happening.", "Slim to none.", "I see darkness — no.", "Certified no.",
    "DogBot laughs at you — no.", "Nada.", "Not in your favor.",
    "Doubt it heavily.", "Yikes, no.",
    # ── Uncertain (~5) ────────────────────────────────────────────────────────
    "Ask again later.", "Cannot predict now.", "Better not tell you now.",
    "Reply hazy, try again.", "DogBot is undecided.",
]


@bot.command(name="8ball")
async def eightball_cmd(ctx, *, question: str = None):
    if not load_features().get("eightball_enabled"):
        return
    if not question:
        await ctx.send("Usage: `!8ball <your question>`")
        return
    intro = random.choice(_8BALL_INTROS)
    answer = random.choice(_8BALL_ANSWERS)
    await ctx.send(f'🎱 {intro} **"{answer}"**')


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


@bot.slash_command(name="webster", description="Behold the goblin.")
async def webster(ctx: discord.ApplicationContext):
    embed = discord.Embed(title="Webster", colour=discord.Colour.dark_green())
    embed.set_image(url="https://oldschool.runescape.wiki/images/Goblin.png")
    await ctx.respond(embed=embed)


bot.run(os.getenv("DISCORD_TOKEN"))

# deploy test: trivial no-op change to verify Render auto-deploy on push to master (2026-06-17)
