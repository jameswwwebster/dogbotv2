"""RS3-specific slash commands: /stats, /profile, /price, /next."""

from __future__ import annotations

from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands

from rs3 import api, resets
from rs3.formatting import commas, humanise_gp, rank_or_dash


# Keep one shared session per cog instance so repeated calls reuse the
# connection pool. Created lazily on first use.
class _SessionHolder:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class RS3(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._sessions = _SessionHolder()

    def cog_unload(self):
        # py-cord schedules sync cog_unload; close the session asynchronously.
        if self._sessions._session and not self._sessions._session.closed:
            self.bot.loop.create_task(self._sessions.close())

    # ------------------------------------------------------------------
    # /stats
    # ------------------------------------------------------------------
    @discord.slash_command(name="stats", description="Look up an RS3 player's hiscores.")
    async def stats(self, ctx: discord.ApplicationContext, player: str):
        await ctx.defer()
        try:
            session = await self._sessions.get()
            profile = await api.fetch_hiscores(session, player)
        except api.ApiError as e:
            await ctx.followup.send(f"❌ {e}", ephemeral=True)
            return

        await ctx.followup.send(embed=self._stats_embed(profile))

    @staticmethod
    def _stats_embed(profile: api.HiscoresProfile) -> discord.Embed:
        overall = profile.overall
        embed = discord.Embed(
            title=f"Hiscores — {profile.username}",
            colour=discord.Colour.gold(),
            url=f"https://secure.runescape.com/m=hiscore/compare?user1={profile.username}",
        )
        embed.add_field(
            name="Overall",
            value=f"**Total level:** {commas(overall.level)}\n"
                  f"**XP:** {commas(overall.xp)}\n"
                  f"**Rank:** {rank_or_dash(overall.rank)}",
            inline=False,
        )
        # Skills in two columns for compact layout
        cols = [[], []]
        for i, s in enumerate(profile.skills[1:], start=0):
            cols[i % 2].append(f"`{s.level:3d}` {s.name}")
        embed.add_field(name="​", value="\n".join(cols[0]) or "—", inline=True)
        embed.add_field(name="​", value="\n".join(cols[1]) or "—", inline=True)
        return embed

    # ------------------------------------------------------------------
    # /profile
    # ------------------------------------------------------------------
    @discord.slash_command(name="profile", description="RS3 player profile (hiscores + RuneMetrics activity).")
    async def profile(self, ctx: discord.ApplicationContext, player: str):
        await ctx.defer()
        session = await self._sessions.get()

        hiscores: api.HiscoresProfile | None = None
        rm: api.RuneMetricsProfile | None = None
        errors: list[str] = []

        try:
            hiscores = await api.fetch_hiscores(session, player)
        except api.ApiError as e:
            errors.append(f"Hiscores: {e}")

        try:
            rm = await api.fetch_runemetrics(session, player, activities=10)
        except api.ApiError as e:
            errors.append(f"RuneMetrics: {e}")

        if not hiscores and not rm:
            await ctx.followup.send("❌ " + "\n".join(errors), ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Profile — {player}",
            colour=discord.Colour.dark_gold(),
        )
        if rm:
            embed.add_field(
                name="Summary",
                value=(
                    f"**Combat:** {rm.combat_level or '—'}\n"
                    f"**Total skill:** {commas(rm.total_skill)}\n"
                    f"**Total XP:** {commas(rm.total_xp)}\n"
                    f"**Quests:** {rm.quests_complete or 0} done / "
                    f"{rm.quests_started or 0} in progress / "
                    f"{rm.quests_not_started or 0} to start"
                ),
                inline=False,
            )
        elif hiscores:
            o = hiscores.overall
            embed.add_field(
                name="Summary (hiscores fallback — RuneMetrics unavailable)",
                value=f"**Total level:** {commas(o.level)}\n**Total XP:** {commas(o.xp)}",
                inline=False,
            )
        if rm and rm.activities:
            recent = "\n".join(
                f"• `{a.date}` — {a.text}" for a in rm.activities[:8]
            )
            embed.add_field(name="Recent activity", value=recent[:1024], inline=False)
        if errors and (hiscores or rm):
            embed.set_footer(text="Partial data — " + " | ".join(errors))

        await ctx.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /price
    # ------------------------------------------------------------------
    @discord.slash_command(name="price", description="Look up the current GE price for an item.")
    async def price(self, ctx: discord.ApplicationContext, item: str):
        await ctx.defer()
        session = await self._sessions.get()
        try:
            item_id = await api.search_ge_item(session, item)
            if item_id is None:
                await ctx.followup.send(f"❌ Couldn't find a GE item matching '{item}'.", ephemeral=True)
                return
            ge = await api.fetch_ge_item(session, item_id)
        except api.ApiError as e:
            await ctx.followup.send(f"❌ {e}", ephemeral=True)
            return

        embed = discord.Embed(
            title=ge.name,
            description=ge.description,
            colour=discord.Colour.green() if ge.day30_trend == "positive" else
                    discord.Colour.red() if ge.day30_trend == "negative" else
                    discord.Colour.greyple(),
            url=f"https://secure.runescape.com/m=itemdb_rs/{ge.name.replace(' ', '+')}/viewitem?obj={ge.id}",
        )
        if ge.icon_url:
            embed.set_thumbnail(url=ge.icon_url)
        embed.add_field(name="Current",       value=f"{ge.current_price_text} gp", inline=True)
        embed.add_field(name="Today's change", value=str(ge.today_change),         inline=True)
        embed.add_field(name="30-day trend",   value=ge.day30_trend,                inline=True)
        embed.set_footer(text=("Members" if ge.members else "Free-to-play") + f" · id {ge.id}")
        await ctx.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /next
    # ------------------------------------------------------------------
    @discord.slash_command(name="next", description="When does the next RS3 reset / event fire?")
    async def next_reset(
        self,
        ctx: discord.ApplicationContext,
        event: discord.Option(  # type: ignore[name-defined]
            str,
            "Optional — limit to one event",
            choices=[r.key for r in resets.RESETS],
            required=False,
            default=None,
        ),
    ):
        now = datetime.now(timezone.utc)
        rows = [resets.get(event)] if event else resets.RESETS
        rows = [r for r in rows if r is not None]

        embed = discord.Embed(
            title="Upcoming RS3 resets" if not event else f"Next: {rows[0].name}",
            colour=discord.Colour.blurple(),
            timestamp=now,
        )
        for r in rows:
            nxt = resets.next_occurrence(r, now)
            until = resets.format_timedelta(nxt - now)
            ts = int(nxt.timestamp())
            embed.add_field(
                name=r.name,
                value=f"In **{until}** — <t:{ts}:F>\n_{r.description}_",
                inline=False,
            )
        embed.set_footer(text="All times in UTC; <t:…:F> renders in your local zone.")
        await ctx.respond(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(RS3(bot))
