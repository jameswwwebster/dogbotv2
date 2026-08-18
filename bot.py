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
REACTION_ROLES_FILE    = "reaction_roles.json"
BATTLE_PETS_FILE       = "battle_pets.json"

QUESTION_REACTION_WINDOW = 24 * 60 * 60  # seconds

BATTLE_PETS_EMOJIS = ["🐱", "🐶", "🐸"]
BATTLE_PETS_NAMES  = {"🐱": "Team Cat", "🐶": "Team Dog", "🐸": "Team Frog"}


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
        "booster_giveaway_enabled": False,
        "booster_giveaway_channel": 1536081045345149069,
        "trivia_event_enabled": False,
        "trivia_submit_channel": 1536070084005466243,
        "trivia_output_channel": 1536070221876428941,
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
    # Record when this question was last shown (used by the daily cooldown filter)
    data = load_questions()
    for q in data["questions"]:
        if q["question"] == entry["question"]:
            q["last_shown"] = time.time()
            save_questions(data)
            break


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
            if entry.get("booster_only"):
                body = (f"🎉 **BOOSTER GIVEAWAY** 🎉\n"
                        f"**Prize:** {entry['prize']}\n"
                        f"{winner_line}"
                        f"**Ends:** <t:{end_ts}:F> (<t:{end_ts}:R>)\n"
                        f"🚀 Server Boosters only! React with 🎉 to enter!")
            else:
                body = (f"🎉 **GIVEAWAY** 🎉\n"
                        f"**Prize:** {entry['prize']}\n"
                        f"{winner_line}"
                        f"**Ends:** <t:{end_ts}:F> (<t:{end_ts}:R>)\n"
                        f"React with 🎉 to enter!")
            msg = await channel.send(body)
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
    if entry.get("booster_only"):
        entrants = [u for u in entrants
                    if (channel.guild.get_member(u.id) or None) and
                       channel.guild.get_member(u.id).premium_since]
    if not entrants:
        await channel.send(f"🎉 The giveaway for **{entry['prize']}** ended with no eligible entries!")
    else:
        winners  = int(entry.get("winners", 1))
        picked   = random.sample(entrants, min(winners, len(entrants)))
        mentions = ", ".join(w.mention for w in picked)
        if len(picked) == 1:
            await channel.send(f"🎉 Congratulations {mentions}! You won **{entry['prize']}**!")
        else:
            await channel.send(f"🎉 Congratulations to our {len(picked)} winners: {mentions}! You won **{entry['prize']}**!")

    # Booster giveaway: immediately start the next cycle after drawing a winner
    if entry.get("booster_only") and load_features().get("booster_giveaway_enabled"):
        now_ts = datetime.now(timezone.utc).timestamp()
        already_active = any(g.get("booster_only") and g.get("end_at", 0) > now_ts
                             for g in load_giveaways())
        if not already_active:
            _start_booster_giveaway()

    _remove_giveaway_entry(entry)


_BOOSTER_MONTHS = [2, 4, 6, 8, 10, 12]


def _next_booster_date(after_ts=None):
    """Return the next Oct/Dec/Feb/Apr/Jun/Aug 1st noon UTC after the given timestamp (or now)."""
    if after_ts is None:
        after_ts = datetime.now(timezone.utc).timestamp()
    after_dt = datetime.fromtimestamp(after_ts, tz=timezone.utc)
    for year in (after_dt.year, after_dt.year + 1):
        for month in _BOOSTER_MONTHS:
            candidate = datetime(year, month, 1, 12, 0, 0, tzinfo=timezone.utc)
            if candidate.timestamp() > after_ts:
                return candidate.timestamp()
    return after_ts + 60 * 86400  # fallback (should never hit)


def _start_booster_giveaway():
    feats  = load_features()
    ch_id  = int(feats.get("booster_giveaway_channel", 1536081045345149069))
    end_at = _next_booster_date()
    entry  = {
        "channel_id": ch_id, "prize": "Bond",
        "end_at": end_at, "winners": 1,
        "message_id": None, "booster_only": True,
    }
    gs = load_giveaways()
    gs.append(entry)
    save_giveaways(gs)
    asyncio.create_task(_run_giveaway(entry))


async def _reattach_or_start_booster_giveaway():
    feats   = load_features()
    ch_id   = int(feats.get("booster_giveaway_channel", 1536081045345149069))
    channel = bot.get_channel(ch_id)
    if not channel:
        print(f"[BoosterGiveaway] Channel {ch_id} not found.")
        return
    now_ts = datetime.now(timezone.utc).timestamp()
    # Scan channel history for an active bot-posted booster giveaway
    async for m in channel.history(limit=50):
        if m.author != bot.user or "BOOSTER GIVEAWAY" not in m.content:
            continue
        match = re.search(r'<t:(\d+):F>', m.content)
        if not match:
            continue
        end_at = float(match.group(1))
        if end_at <= now_ts:
            continue  # already expired
        # Found one — reattach
        entry = {"channel_id": ch_id, "prize": "Bond", "end_at": end_at,
                 "winners": 1, "message_id": m.id, "booster_only": True}
        gs = load_giveaways()
        if not any(g.get("booster_only") and g.get("message_id") == m.id for g in gs):
            gs.append(entry)
            save_giveaways(gs)
        asyncio.create_task(_run_giveaway(entry))
        print(f"[BoosterGiveaway] Reattached to existing message (ID: {m.id}).")
        return
    # Nothing active — post immediately (end date aligns to next scheduled date)
    print("[BoosterGiveaway] No active giveaway found — posting new one.")
    _start_booster_giveaway()


def load_reaction_roles():
    defaults = {"message_id": 969585509561172028, "channel_id": 969324314983804948,
                "info_message_id": None, "roles": {}}
    if not os.path.exists(REACTION_ROLES_FILE):
        return defaults
    with open(REACTION_ROLES_FILE, "r") as f:
        data = json.load(f)
    for k, v in defaults.items():
        data.setdefault(k, v)
    # Migrate old plain-string format {"emote": "role"} → {"emote": {"role": "role", "name": "role"}}
    for emote, val in data["roles"].items():
        if isinstance(val, str):
            data["roles"][emote] = {"role": val, "name": val}
    return data


def _rr_role_name(entry):
    return entry["role"] if isinstance(entry, dict) else entry


def _rr_display_name(entry):
    return entry.get("name", entry["role"]) if isinstance(entry, dict) else entry


def save_reaction_roles(data):
    with open(REACTION_ROLES_FILE, "w") as f:
        json.dump(data, f, indent=4)


def load_battle_pets():
    if not os.path.exists(BATTLE_PETS_FILE):
        return None
    with open(BATTLE_PETS_FILE) as f:
        data = json.load(f)
    return data if data else None


def save_battle_pets(entry):
    with open(BATTLE_PETS_FILE, "w") as f:
        json.dump(entry or {}, f, indent=4)


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


def _push_reaction_roles_to_github():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("[ReactionRoles] GITHUB_TOKEN not set — skipping push.")
        return False
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        if not remote.startswith("https://"):
            return False
        authed = remote.replace("https://", f"https://{token}@")
        subprocess.run(["git", "config", "user.email", "dogbot@railway.app"], check=True)
        subprocess.run(["git", "config", "user.name",  "DogBot"],             check=True)
        subprocess.run(["git", "pull", "--rebase", authed, "master"], capture_output=True)
        subprocess.run(["git", "add", REACTION_ROLES_FILE], check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return True
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(["git", "commit", "-m", f"Reaction roles update — {ts}"], check=True)
        subprocess.run(["git", "push", authed, "master"], check=True)
        print("[ReactionRoles] Pushed to GitHub.")
        return True
    except Exception as e:
        print(f"[ReactionRoles] Push failed: {e}")
        return False


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


def _parse_deadline(text):
    """Parse '7d', '2h30m', '1d12h', or 'YYYY-MM-DD HH:MM' into a UTC timestamp."""
    now = datetime.now(timezone.utc).timestamp()
    m = re.fullmatch(r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?', text.strip(), re.IGNORECASE)
    if m and any(m.group(i) for i in (1, 2, 3)):
        delta = (int(m.group(1) or 0) * 86400 +
                 int(m.group(2) or 0) * 3600 +
                 int(m.group(3) or 0) * 60)
        if delta > 0:
            return now + delta
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(text.strip(), fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
    return None


_BP_PRIZE_PER = 10  # M per participant

def _battle_pets_body(end_ts, pool_m, total):
    s = "s" if total != 1 else ""
    prize_line = f"**Prize Pool:** {pool_m}M  ({total} participant{s} × {_BP_PRIZE_PER}M)"
    return (
        "⚔️ **BATTLE OF THE PETS** ⚔️\n"
        f"**Ends:** <t:{end_ts}:F> (<t:{end_ts}:R>)\n"
        f"{prize_line}\n\n"
        "Pick your camp by reacting below!\n"
        "🐱 — Team Cat\n"
        "🐶 — Team Dog\n"
        "🐸 — Team Frog\n\n"
        "_One camp only — reacting with a different emoji removes your previous choice._"
    )


_bp_update_tasks = {}  # message_id -> asyncio.Task


async def _update_battle_pets_pool(msg_id, channel_id):
    bp = load_battle_pets()
    if not bp or bp.get("message_id") != msg_id:
        return
    channel = bot.get_channel(channel_id)
    if not channel:
        return
    try:
        msg = await channel.fetch_message(msg_id)
    except (discord.NotFound, discord.HTTPException):
        return
    all_users = set()
    for emoji in BATTLE_PETS_EMOJIS:
        rxn = discord.utils.get(msg.reactions, emoji=emoji)
        if rxn:
            async for u in rxn.users():
                if not u.bot:
                    all_users.add(u.id)
    total   = len(all_users)
    pool_m  = total * _BP_PRIZE_PER
    end_ts  = int(bp["end_at"])
    try:
        await msg.edit(content=_battle_pets_body(end_ts, pool_m, total))
    except discord.HTTPException as e:
        print(f"[BattlePets] Prize pool update failed: {e}")


async def _debounced_bp_update(msg_id, channel_id):
    await asyncio.sleep(3)
    await _update_battle_pets_pool(msg_id, channel_id)
    _bp_update_tasks.pop(msg_id, None)


def _schedule_bp_pool_update(msg_id, channel_id):
    existing = _bp_update_tasks.get(msg_id)
    if existing and not existing.done():
        existing.cancel()
    _bp_update_tasks[msg_id] = asyncio.create_task(_debounced_bp_update(msg_id, channel_id))


async def _run_battle_pets(entry):
    channel = bot.get_channel(entry["channel_id"])
    if not channel:
        print(f"[BattlePets] Channel {entry['channel_id']} not found.")
        save_battle_pets(None)
        return

    now_ts = datetime.now(timezone.utc).timestamp()

    if not entry.get("message_id"):
        if entry["end_at"] <= now_ts:
            print("[BattlePets] Entry already expired before posting — clearing.")
            save_battle_pets(None)
            return
        end_ts = int(entry["end_at"])
        msg = await channel.send(_battle_pets_body(end_ts, 0, 0))
        for emoji in BATTLE_PETS_EMOJIS:
            await msg.add_reaction(emoji)
        entry["message_id"] = msg.id
        save_battle_pets(entry)

    delay = entry["end_at"] - datetime.now(timezone.utc).timestamp()
    if delay > 0:
        await asyncio.sleep(delay)

    try:
        msg = await channel.fetch_message(entry["message_id"])
    except (discord.NotFound, discord.HTTPException):
        save_battle_pets(None)
        return

    camps = {}
    for emoji in BATTLE_PETS_EMOJIS:
        reaction = discord.utils.get(msg.reactions, emoji=emoji)
        camps[emoji] = [u async for u in reaction.users() if not u.bot] if reaction else []

    all_participants = {u.id for camp in camps.values() for u in camp}
    total   = len(all_participants)
    pool_m  = total * _BP_PRIZE_PER

    winner_emoji = random.choice(BATTLE_PETS_EMOJIS)
    winners = camps[winner_emoji]

    lines = [
        "⚔️ **BATTLE OF THE PETS — RESULTS** ⚔️",
        f"The fates have chosen... **{winner_emoji} {BATTLE_PETS_NAMES[winner_emoji]}**!",
        "",
    ]
    if winners:
        mentions  = " ".join(w.mention for w in winners)
        team_word = BATTLE_PETS_NAMES[winner_emoji].split()[1]
        n = len(winners)
        per_m = pool_m / n
        per_str = f"{int(per_m)}M" if per_m == int(per_m) else f"~{per_m:.1f}M"
        lines.append(f"🎉 Congratulations to all Team {team_word} members: {mentions}")
        lines.append(f"💰 Prize: **{pool_m}M ÷ {n} = {per_str} each**")
    else:
        lines.append(
            f"Nobody joined {BATTLE_PETS_NAMES[winner_emoji]}... "
            f"{winner_emoji} wins with an empty camp — incredible!"
        )
    lines += [
        "",
        "**Final standings:**",
    ]
    for emoji in BATTLE_PETS_EMOJIS:
        marker = " 🏆" if emoji == winner_emoji else ""
        lines.append(f"{emoji} {BATTLE_PETS_NAMES[emoji]}: {len(camps[emoji])}{marker}")
    lines += ["", f"**Total prize pool: {pool_m}M** ({total} participant{'s' if total != 1 else ''} × {_BP_PRIZE_PER}M)"]

    await channel.send("\n".join(lines))
    save_battle_pets(None)


async def _reattach_battle_pets():
    bp = load_battle_pets()
    if not bp:
        return
    now_ts = datetime.now(timezone.utc).timestamp()
    if bp["end_at"] <= now_ts:
        print("[BattlePets] Stored battle already expired — clearing.")
        save_battle_pets(None)
        return
    # If message_id is unknown, scan channel history to avoid a duplicate post
    if not bp.get("message_id"):
        channel = bot.get_channel(bp["channel_id"])
        if channel:
            async for m in channel.history(limit=50):
                if m.author != bot.user or "BATTLE OF THE PETS" not in m.content:
                    continue
                match = re.search(r'<t:(\d+):F>', m.content)
                if match and abs(float(match.group(1)) - bp["end_at"]) < 60:
                    bp["message_id"] = m.id
                    save_battle_pets(bp)
                    print(f"[BattlePets] Found existing message in history (ID: {m.id}).")
                    break
    asyncio.create_task(_run_battle_pets(bp))
    # Refresh the prize pool display in case participants reacted during downtime
    if bp.get("message_id"):
        _schedule_bp_pool_update(bp["message_id"], bp["channel_id"])
    print(f"[BattlePets] Reattached (message_id={bp.get('message_id')}).")


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
                    cutoff = time.time() - 180 * 86400
                    eligible = [q for q in questions if not q.get("last_shown") or q["last_shown"] < cutoff]
                    q = random.choice(eligible if eligible else questions)
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


async def _sync_roles_message():
    rr = load_reaction_roles()
    channel = bot.get_channel(rr["channel_id"])
    if not channel:
        print("[ReactionRoles] Channel not found for sync.")
        return

    def channel_mention(name):
        ch = discord.utils.get(channel.guild.channels, name=name)
        if not ch:
            ch = next((c for c in channel.guild.channels if name in c.name), None)
        return ch.mention if ch else f"#{name}"

    lines = [
        f"Please react to the appropriate emoji to activate notifications for when that activity is being hosted in "
        f"{channel_mention('pvm-signup')} or {channel_mention('pvm-chat')}\n"
    ]
    for emote, entry in rr["roles"].items():
        role_name    = _rr_role_name(entry)
        display_name = _rr_display_name(entry)
        guild_role   = discord.utils.get(channel.guild.roles, name=role_name)
        role_mention = guild_role.mention if guild_role else f"@{role_name}"
        lines.append(f"{emote} - {role_mention} - {display_name}")
    content = "\n".join(lines)
    no_ping = discord.AllowedMentions(roles=False)

    # Try the saved message ID first
    info_id = rr.get("info_message_id")
    if info_id:
        try:
            msg = await channel.fetch_message(info_id)
            await msg.edit(content=content, allowed_mentions=no_ping)
            print("[ReactionRoles] Info message updated.")
            return
        except discord.NotFound:
            rr["info_message_id"] = None
        except Exception as e:
            print(f"[ReactionRoles] Could not edit info message: {e}")
            return

    # Scan history for an existing bot message to reuse (avoids duplicate posts on redeploy)
    async for m in channel.history(limit=50):
        if m.author == bot.user and "react to the appropriate emoji" in m.content:
            await m.edit(content=content, allowed_mentions=no_ping)
            rr["info_message_id"] = m.id
            save_reaction_roles(rr)
            await asyncio.get_event_loop().run_in_executor(None, _push_reaction_roles_to_github)
            print(f"[ReactionRoles] Reattached to existing message (ID: {m.id}).")
            return

    # Nothing found — send once and save the ID
    msg = await channel.send(content, allowed_mentions=no_ping)
    rr["info_message_id"] = msg.id
    save_reaction_roles(rr)
    await asyncio.get_event_loop().run_in_executor(None, _push_reaction_roles_to_github)
    print(f"[ReactionRoles] New info message sent (ID: {msg.id}).")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    if not check_reminders.is_running():
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

    # Booster giveaway: reattach to existing message or post a new one
    if load_features().get("booster_giveaway_enabled"):
        await _reattach_or_start_booster_giveaway()

    # Battle of the Pets: reattach if one is stored
    await _reattach_battle_pets()

    # Sync the roles info message and add emotes
    await _sync_roles_message()
    rr = load_reaction_roles()
    if rr.get("message_id") and rr.get("channel_id") and rr["roles"]:
        rr_channel = bot.get_channel(rr["channel_id"])
        if rr_channel:
            try:
                rr_msg = await rr_channel.fetch_message(rr["message_id"])
                for emote in rr["roles"]:
                    try:
                        await rr_msg.add_reaction(emote)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[ReactionRoles] Could not fetch message: {e}")

    # Send and clear any queued push messages
    pending = load_push_messages()
    if pending:
        now_ts = datetime.now(timezone.utc).timestamp()
        save_push_messages([])  # clear immediately so redeploys never resend
        for entry in pending:
            # Skip messages queued more than 10 minutes ago (stale from a previous deploy)
            if entry.get("queued_at") and now_ts - entry["queued_at"] > 600:
                continue
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

    # Trivia event: collect Q: / A: submissions
    _feats = load_features()
    if (_feats.get("trivia_event_enabled") and
            message.channel.id == int(_feats.get("trivia_submit_channel", 0))):
        content = message.content.strip()
        lines   = content.splitlines()
        q_line  = next((l for l in lines if l.strip().lower().startswith("q:")), None)
        a_line  = next((l for l in lines if l.strip().lower().startswith("a:")), None)
        # Also handle single-line format: "Q: question A: answer"
        question = answer = None
        if q_line and a_line:
            question = q_line.split(":", 1)[1].strip()
            answer   = a_line.split(":", 1)[1].strip()
        else:
            m = re.search(r'(?i)q:\s*(.+?)\s+a:\s*(.+)', content)
            if m:
                question = m.group(1).strip()
                answer   = m.group(2).strip()
        try:
            await message.delete()
        except discord.NotFound:
            return  # another instance already handled this message
        except discord.Forbidden:
            print(f"[Trivia] Missing Manage Messages permission in channel {message.channel.id}")
        if question and answer:
            try:
                await message.author.send("Your question has been successfully submitted!")
            except discord.Forbidden:
                pass
            out_ch = bot.get_channel(int(_feats.get("trivia_output_channel", 0)))
            if out_ch:
                msg = await out_ch.send(f"❓ **{question}**\n||{answer}||\n*Submitted by {message.author.mention}*")
                await msg.add_reaction("👍")
                await msg.add_reaction("⭐")
            else:
                print(f"[Trivia] Output channel {_feats.get('trivia_output_channel')} not found.")
        else:
            try:
                await message.author.send(
                    "❌ Invalid format — please use:\n```\nQ: your question\nA: your answer\n```")
            except discord.Forbidden:
                pass
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

    # Question score tracking
    tracking = load_question_tracking()
    entry = tracking.get(str(payload.message_id))
    if entry and time.time() <= entry["expires_at"]:
        emoji = str(payload.emoji)
        if emoji == "✅":
            _update_question_score(entry["question"], correct_delta=1)
        elif emoji == "❌":
            _update_question_score(entry["question"], incorrect_delta=1)

    # Reaction roles
    rr = load_reaction_roles()
    if payload.message_id == rr.get("message_id"):
        emoji_str = str(payload.emoji)
        rr_entry  = rr["roles"].get(emoji_str)
        role_name = _rr_role_name(rr_entry) if rr_entry else None
        print(f"[ReactionRoles] ADD emoji={emoji_str!r} role_name={role_name!r}")
        if not role_name:
            print(f"[ReactionRoles] No mapping for that emoji. Known: {list(rr['roles'].keys())}")
            return
        guild = bot.get_guild(payload.guild_id)
        if not guild:
            print(f"[ReactionRoles] Guild {payload.guild_id} not found in cache.")
            return
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            available = [r.name for r in guild.roles]
            print(f"[ReactionRoles] Role '{role_name}' not found. Available: {available}")
            return
        try:
            member = await guild.fetch_member(payload.user_id)
        except Exception as e:
            print(f"[ReactionRoles] Could not fetch member {payload.user_id}: {e}")
            return
        try:
            await member.add_roles(role)
            print(f"[ReactionRoles] Added '{role_name}' to {member.display_name}.")
            display = _rr_display_name(rr_entry) if rr_entry else role_name
            try:
                await member.send(f"✅ You've been given the **{role_name}** role! You'll get pinged when **{display}** is being hosted.")
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            print(f"[ReactionRoles] Forbidden adding '{role_name}' — check bot role hierarchy.")
            ch = bot.get_channel(rr.get("channel_id"))
            if ch:
                await ch.send(f"⚠️ Can't assign **{role_name}** — move DogBot's role above it in Server Settings → Roles.", delete_after=30)

    # Battle of the Pets — enforce single-camp: remove other pet reactions if user switches
    bp = load_battle_pets()
    if bp and payload.message_id == bp.get("message_id"):
        emoji_str = str(payload.emoji)
        if emoji_str in BATTLE_PETS_EMOJIS:
            guild   = bot.get_guild(payload.guild_id)
            channel = bot.get_channel(payload.channel_id)
            if guild and channel:
                try:
                    member = await guild.fetch_member(payload.user_id)
                    msg    = await channel.fetch_message(payload.message_id)
                    for other in BATTLE_PETS_EMOJIS:
                        if other == emoji_str:
                            continue
                        rxn = discord.utils.get(msg.reactions, emoji=other)
                        if rxn:
                            users = [u async for u in rxn.users()]
                            if any(u.id == payload.user_id for u in users):
                                await msg.remove_reaction(other, member)
                                print(f"[BattlePets] Removed {other} from {member.display_name} (switched to {emoji_str}).")
                except Exception as e:
                    print(f"[BattlePets] Single-camp enforcement error: {e}")
            # Update the prize pool display (debounced so rapid reactions only cause one edit)
            _schedule_bp_pool_update(payload.message_id, payload.channel_id)


@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id:
        return

    # Question score tracking
    tracking = load_question_tracking()
    entry = tracking.get(str(payload.message_id))
    if entry and time.time() <= entry["expires_at"]:
        emoji = str(payload.emoji)
        if emoji == "✅":
            _update_question_score(entry["question"], correct_delta=-1)
        elif emoji == "❌":
            _update_question_score(entry["question"], incorrect_delta=-1)

    # Reaction roles
    rr = load_reaction_roles()
    if payload.message_id == rr.get("message_id"):
        rr_entry  = rr["roles"].get(str(payload.emoji))
        role_name = _rr_role_name(rr_entry) if rr_entry else None
        if role_name:
            guild = bot.get_guild(payload.guild_id)
            if guild:
                role = discord.utils.get(guild.roles, name=role_name)
                try:
                    member = await guild.fetch_member(payload.user_id)
                except Exception:
                    member = None
                if role and member:
                    await member.remove_roles(role)
                    display = _rr_display_name(rr_entry) if rr_entry else role_name
                    try:
                        await member.send(f"❌ The **{role_name}** role has been removed. You'll no longer get pinged for **{display}**.")
                    except discord.Forbidden:
                        pass

    # Battle of the Pets — update prize pool when someone leaves a camp
    bp = load_battle_pets()
    if bp and payload.message_id == bp.get("message_id"):
        if str(payload.emoji) in BATTLE_PETS_EMOJIS:
            _schedule_bp_pool_update(payload.message_id, payload.channel_id)


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
    fun.append("`!newquestion` — Random question from the last 30 added ❓")
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

    if has_mod_role(ctx.author):
        lines.append("\n**🎭 Reaction Roles (mod only):**")
        lines.append("`!addreaction <emote> <role> <boss name>` — Add a reaction role mapping")

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


@bot.command(name="newquestion")
async def newquestion_cmd(ctx):
    questions = load_questions().get("questions", [])
    if not questions:
        await ctx.send("No questions available yet.")
        return
    pool = questions[-30:] if len(questions) >= 30 else questions
    await _post_question(ctx.channel, random.choice(pool))


@bot.command(name="triviadebug")
async def triviadebug_cmd(ctx):
    if not has_mod_role(ctx.author):
        return
    feats = load_features()
    enabled  = feats.get("trivia_event_enabled", False)
    sub_id   = int(feats.get("trivia_submit_channel", 0))
    out_id   = int(feats.get("trivia_output_channel", 0))
    sub_ch   = bot.get_channel(sub_id)
    out_ch   = bot.get_channel(out_id)
    bot_mem  = ctx.guild.get_member(bot.user.id)
    sub_perms = sub_ch.permissions_for(bot_mem) if sub_ch and bot_mem else None
    out_perms = out_ch.permissions_for(bot_mem) if out_ch and bot_mem else None
    lines = ["**🎯 Trivia Event Debug**"]
    lines.append(f"Enabled: {'✅' if enabled else '❌ OFF — toggle in manager Preset Events tab'}")
    lines.append(f"Submit channel: {sub_ch.mention if sub_ch else f'❌ `{sub_id}` not found'}")
    if sub_perms:
        lines.append(f"  • Read messages: {'✅' if sub_perms.read_messages else '❌'}")
        lines.append(f"  • Manage messages (delete): {'✅' if sub_perms.manage_messages else '❌'}")
    lines.append(f"Output channel: {out_ch.mention if out_ch else f'❌ `{out_id}` not found'}")
    if out_perms:
        lines.append(f"  • Send messages: {'✅' if out_perms.send_messages else '❌'}")
    await ctx.send("\n".join(lines))


@bot.command(name="rrdebug")
async def rrdebug_cmd(ctx):
    if not has_mod_role(ctx.author):
        return
    rr = load_reaction_roles()
    guild = ctx.guild
    bot_member = guild.get_member(bot.user.id)
    bot_top_role = bot_member.top_role if bot_member else None
    has_manage = ctx.channel.permissions_for(bot_member).manage_roles if bot_member else False

    lines = ["**🔍 Reaction Roles Debug**"]
    lines.append(f"Watching message ID: `{rr.get('message_id')}`")
    lines.append(f"Channel ID: `{rr.get('channel_id')}`")
    lines.append(f"Bot has Manage Roles: {'✅' if has_manage else '❌ MISSING'}")
    lines.append(f"Bot top role: `{bot_top_role}` (position {bot_top_role.position if bot_top_role else '?'})")
    lines.append("")
    lines.append("**Role mappings (✅ = found & bot can assign):**")
    for emote, entry in rr["roles"].items():
        role_name = _rr_role_name(entry)
        guild_role = discord.utils.get(guild.roles, name=role_name)
        if not guild_role:
            status = "❌ NOT FOUND"
        elif bot_top_role and guild_role.position >= bot_top_role.position:
            status = f"⚠️ found but bot role too low (pos {guild_role.position} ≥ {bot_top_role.position})"
        else:
            status = "✅"
        lines.append(f"{emote} → `{role_name}` {status}")
    await ctx.send("\n".join(lines))


_addreaction_seen = {}  # message_id -> timestamp, deduplicates across overlapping instances

@bot.command(name="addreaction")
async def addreaction_cmd(ctx, emote: str = None, role_name: str = None, *, boss_name: str = None):
    if not has_mod_role(ctx.author):
        return
    if time.time() - _addreaction_seen.get(ctx.message.id, 0) < 5:
        return  # already handled by another instance
    _addreaction_seen[ctx.message.id] = time.time()
    if not emote or not role_name or not boss_name:
        await ctx.send("Usage: `!addreaction <emote> <role name> <boss name>`\nExample: `!addreaction <:Solak:123> Solak Solak`")
        return
    data = load_reaction_roles()
    data["roles"][emote] = {"role": role_name, "name": boss_name}
    save_reaction_roles(data)
    # Add the reaction to the message immediately
    channel = bot.get_channel(data["channel_id"])
    if channel:
        try:
            msg = await channel.fetch_message(data["message_id"])
            await msg.add_reaction(emote)
        except Exception:
            pass
    await ctx.send(f"✅ Reaction role added: {emote} → **{role_name}** ({boss_name})")
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, _push_reaction_roles_to_github)
    if not ok:
        await ctx.send("⚠️ Could not sync to GitHub — update the manager manually.")


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


@bot.command(name="battlepets")
async def battlepets_cmd(ctx, subcommand: str = None, *, args: str = None):
    if not has_mod_role(ctx.author):
        return
    if subcommand and subcommand.lower() == "start":
        if not args:
            await ctx.send(
                "Usage: `!battlepets start <duration or date>`\n"
                "Examples: `!battlepets start 7d` · `!battlepets start 2h30m` · `!battlepets start 2026-09-01 18:00`"
            )
            return
        end_at = _parse_deadline(args)
        if not end_at or end_at <= datetime.now(timezone.utc).timestamp():
            await ctx.send("❌ Invalid deadline. Try `7d`, `2h30m`, or `2026-09-01 18:00`.")
            return
        if load_battle_pets():
            await ctx.send("❌ A Battle of the Pets is already active. Cancel it first with `!battlepets cancel`.")
            return
        entry = {"channel_id": ctx.channel.id, "end_at": end_at, "message_id": None}
        save_battle_pets(entry)
        asyncio.create_task(_run_battle_pets(entry))
        await ctx.send(f"⚔️ Battle of the Pets started! Ends <t:{int(end_at)}:R>.")
    elif subcommand and subcommand.lower() == "cancel":
        bp = load_battle_pets()
        if not bp:
            await ctx.send("❌ No active Battle of the Pets.")
            return
        if bp.get("message_id") and bp.get("channel_id"):
            try:
                ch = bot.get_channel(bp["channel_id"])
                if ch:
                    msg = await ch.fetch_message(bp["message_id"])
                    await msg.delete()
            except Exception:
                pass
        save_battle_pets(None)
        await ctx.send("⚔️ Battle of the Pets cancelled.")
    else:
        bp = load_battle_pets()
        if bp:
            end_ts = int(bp["end_at"])
            await ctx.send(
                f"⚔️ **Battle of the Pets** is active — ends <t:{end_ts}:R>.\n"
                "Use `!battlepets cancel` to cancel it."
            )
        else:
            await ctx.send(
                "⚔️ **Battle of the Pets** commands (mod only):\n"
                "`!battlepets start <duration>` — start (e.g. `7d`, `2h30m`, `2026-09-01 18:00`)\n"
                "`!battlepets cancel` — cancel the active battle"
            )


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
