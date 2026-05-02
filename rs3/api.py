"""HTTP clients for RS3 public APIs.

All functions return parsed Python data structures and raise `ApiError`
on transport / parsing failures so cog code can present a friendly
message without sprinkling try/except everywhere.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import aiohttp


# Order matches the Jagex Hiscores Lite CSV column order. Update if Jagex
# adds new skills (rare event).
HISCORES_SKILLS = [
    "Overall",
    "Attack", "Defence", "Strength", "Constitution", "Ranged", "Prayer",
    "Magic", "Cooking", "Woodcutting", "Fletching", "Fishing", "Firemaking",
    "Crafting", "Smithing", "Mining", "Herblore", "Agility", "Thieving",
    "Slayer", "Farming", "Runecrafting", "Hunter", "Construction",
    "Summoning", "Dungeoneering", "Divination", "Invention", "Archaeology",
    "Necromancy",
]


class ApiError(Exception):
    """Wraps any failure (HTTP status, network, malformed body)."""


@dataclass(frozen=True)
class SkillEntry:
    name: str
    rank: int           # -1 if unranked
    level: int
    xp: int


@dataclass(frozen=True)
class HiscoresProfile:
    username: str
    skills: list[SkillEntry]

    def by_name(self, name: str) -> Optional[SkillEntry]:
        for s in self.skills:
            if s.name.lower() == name.lower():
                return s
        return None

    @property
    def overall(self) -> SkillEntry:
        return self.skills[0]


HISCORES_URL = "https://secure.runescape.com/m=hiscore/index_lite.ws"
RUNEMETRICS_PROFILE_URL = "https://apps.runescape.com/runemetrics/profile/profile"
GE_DETAIL_URL = "https://secure.runescape.com/m=itemdb_rs/api/catalogue/detail.json"
GE_SEARCH_URL = "https://secure.runescape.com/m=itemdb_rs/api/catalogue/items.json"
GE_GRAPH_URL_TEMPLATE = "https://secure.runescape.com/m=itemdb_rs/api/graph/{item_id}.json"

USER_AGENT = "dogbotv2 (+https://github.com/collectordog/dogbotv2)"


async def _get(session: aiohttp.ClientSession, url: str, **kwargs) -> aiohttp.ClientResponse:
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)
    try:
        return await session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10), **kwargs)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise ApiError(f"Network error contacting {url}: {e}") from e


# ---------------------------------------------------------------------------
# Hiscores
# ---------------------------------------------------------------------------

def parse_hiscores_csv(text: str, username: str) -> HiscoresProfile:
    """Parse the Lite hiscores CSV. Each line is `rank,level,xp`."""
    rows = [r for r in text.strip().splitlines() if r.strip()]
    if len(rows) < len(HISCORES_SKILLS):
        # Some accounts may be missing later skills (e.g., haven't unlocked
        # Necromancy yet for very stale lookups). Pad with "unranked" rows.
        rows += ["-1,1,0"] * (len(HISCORES_SKILLS) - len(rows))

    skills: list[SkillEntry] = []
    for name, raw in zip(HISCORES_SKILLS, rows[: len(HISCORES_SKILLS)]):
        try:
            rank, level, xp = (int(x) for x in raw.split(",", 2))
        except ValueError as e:
            raise ApiError(f"Malformed hiscores row '{raw}': {e}") from e
        skills.append(SkillEntry(name=name, rank=rank, level=level, xp=xp))
    return HiscoresProfile(username=username, skills=skills)


async def fetch_hiscores(session: aiohttp.ClientSession, username: str) -> HiscoresProfile:
    resp = await _get(session, HISCORES_URL, params={"player": username})
    if resp.status == 404:
        raise ApiError(f"Player '{username}' not found on the RS3 hiscores.")
    if resp.status != 200:
        raise ApiError(f"Hiscores returned HTTP {resp.status}.")
    text = await resp.text()
    return parse_hiscores_csv(text, username=username)


# ---------------------------------------------------------------------------
# RuneMetrics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecentActivity:
    date: str        # original 'DD-MMM-YYYY HH:MM' from RuneMetrics
    text: str
    details: str


@dataclass(frozen=True)
class RuneMetricsProfile:
    username: str
    combat_level: Optional[int]
    total_skill: Optional[int]
    total_xp: Optional[int]
    quests_complete: Optional[int]
    quests_started: Optional[int]
    quests_not_started: Optional[int]
    activities: list[RecentActivity]


async def fetch_runemetrics(session: aiohttp.ClientSession, username: str, activities: int = 20) -> RuneMetricsProfile:
    resp = await _get(session, RUNEMETRICS_PROFILE_URL, params={"user": username, "activities": str(activities)})
    if resp.status != 200:
        raise ApiError(f"RuneMetrics returned HTTP {resp.status}.")
    data = await resp.json(content_type=None)
    if "error" in data:
        # 'NO_PROFILE' or 'PROFILE_PRIVATE'
        raise ApiError({
            "NO_PROFILE": f"No RuneMetrics profile for '{username}'.",
            "PROFILE_PRIVATE": f"'{username}' has set their RuneMetrics profile to private.",
            "NOT_A_MEMBER": f"'{username}' is not a member.",
        }.get(data["error"], f"RuneMetrics error: {data['error']}"))

    return RuneMetricsProfile(
        username=data.get("name", username),
        combat_level=data.get("combatlevel"),
        total_skill=data.get("totalskill"),
        total_xp=data.get("totalxp"),
        quests_complete=data.get("questscomplete"),
        quests_started=data.get("questsstarted"),
        quests_not_started=data.get("questsnotstarted"),
        activities=[
            RecentActivity(date=a.get("date", ""), text=a.get("text", ""), details=a.get("details", ""))
            for a in (data.get("activities") or [])
        ],
    )


# ---------------------------------------------------------------------------
# GE prices
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeItem:
    id: int
    name: str
    description: str
    icon_url: str
    members: bool
    current_price: int       # in gp; we normalise the API's 'k/m/b' suffixes
    current_price_text: str  # the API's pretty form, e.g. '1.5m'
    today_change: str        # e.g. '+150' or '-1.2%'
    day30_trend: str         # e.g. 'positive' / 'negative' / 'neutral'


def _parse_price(raw) -> int:
    """RS3 GE returns either an int or a 'k/m/b'-suffixed string. Normalise."""
    if isinstance(raw, int):
        return raw
    s = str(raw).replace(",", "").replace(" ", "").lower()
    if not s:
        return 0
    mult = 1
    if s.endswith("k"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("b"):
        mult, s = 1_000_000_000, s[:-1]
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return 0


async def search_ge_item(session: aiohttp.ClientSession, query: str) -> Optional[int]:
    """Find an item ID by name. Searches alphabetically through the API's
    paginated catalogue. Returns the first exact (case-insensitive) match,
    or the first prefix match if no exact one. None if nothing found."""
    if not query:
        return None
    first = query.strip()[0].lower()
    if not first.isalpha():
        # The API only paginates alphabetic prefixes; fall back to plain
        # category=1 (members) which covers almost everything searchable.
        return None

    exact_target = query.strip().lower()
    prefix_match: Optional[int] = None

    # Pages are 12 items each; iterate until we get an empty page or hit a match.
    for page in range(1, 100):
        resp = await _get(session, GE_SEARCH_URL, params={
            "category": "1",
            "alpha": first,
            "page": str(page),
        })
        if resp.status != 200:
            break
        body = await resp.json(content_type=None)
        items = body.get("items") or []
        if not items:
            break
        for item in items:
            name_lc = item.get("name", "").lower()
            if name_lc == exact_target:
                return int(item["id"])
            if prefix_match is None and name_lc.startswith(exact_target):
                prefix_match = int(item["id"])
    return prefix_match


async def fetch_ge_item(session: aiohttp.ClientSession, item_id: int) -> GeItem:
    resp = await _get(session, GE_DETAIL_URL, params={"item": str(item_id)})
    if resp.status != 200:
        raise ApiError(f"GE detail returned HTTP {resp.status}.")
    body = await resp.json(content_type=None)
    item = body.get("item")
    if not item:
        raise ApiError(f"No GE item with id {item_id}.")
    return GeItem(
        id=int(item["id"]),
        name=item.get("name", "Unknown"),
        description=item.get("description", ""),
        icon_url=item.get("icon_large") or item.get("icon", ""),
        members=item.get("members", "false") == "true",
        current_price=_parse_price(item.get("current", {}).get("price", 0)),
        current_price_text=str(item.get("current", {}).get("price", "0")),
        today_change=str(item.get("today", {}).get("price", "0")),
        day30_trend=str(item.get("day30", {}).get("trend", "neutral")),
    )
