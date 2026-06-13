import a2s
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, button

from utils.constants import SERVER_ADDRESS
from utils.database import WEAPON_COLUMNS, WEAPON_LOOKUP, TOP_PAGE_SIZE, format_played_time

ARABIAN_ICON = (
    "https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
    "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
    "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&"
)
ARABIAN_COLOR = discord.Color.from_rgb(230, 145, 30)


def _valid_url(url):
    return isinstance(url, str) and url.startswith(("http://", "https://"))


def _short_name(name, limit=16):
    """Cap a player name so a leaderboard row never overflows the embed
    width (which would wrap the line and break the table layout)."""
    name = (name or "Unknown").strip()
    return name if len(name) <= limit else name[:limit - 1] + "…"


def _avatar_url(avatar):
    """Resolve the stored avatar value to a usable image URL.

    The DB stores Steam's 40-char SHA-1 avatar hash (or, rarely, a full URL).
    """
    if not avatar:
        return None
    if _valid_url(avatar):
        return avatar
    avatar = avatar.strip().lower()
    if len(avatar) == 40 and all(c in "0123456789abcdef" for c in avatar):
        return f"https://avatars.steamstatic.com/{avatar}_full.jpg"
    return None


class TopView(View):
    """Paginated leaderboard view. Buttons enable/disable based on the
    current page and total player count."""

    def __init__(self, cog, page, total, timeout=120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.page = page
        self.total = total
        self._update_buttons()

    def _max_page(self):
        return max(1, -(-self.total // TOP_PAGE_SIZE))  # ceil division

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self._max_page()

    async def _render(self, interaction: discord.Interaction):
        embed, self.total = await self.cog.build_top_embed(self.page)
        self._update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @button(label="Previous", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, _):
        if self.page > 1:
            self.page -= 1
        await self._render(interaction)

    @button(label="Next", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _):
        if self.page < self._max_page():
            self.page += 1
        await self._render(interaction)


class CsLogic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------------ #
    # /rankstats
    # ------------------------------------------------------------------ #
    @app_commands.command(name="rankstats", description="Get stats for a player")
    @app_commands.describe(player_name="Exact in-game nickname (case-sensitive)")
    async def rankstats(self, interaction: discord.Interaction, player_name: str):
        await interaction.response.defer()
        p = await self._resolve_player_or_report(interaction, player_name)
        if p is None:
            return

        online = p["Online"]
        embed = discord.Embed(
            title=f"{p['Name']} — Player Stats",
            color=discord.Color.green() if online else ARABIAN_COLOR,
            url=p["Profile"] if _valid_url(p["Profile"]) else None,
        )
        avatar = _avatar_url(p["Avatar"])
        if avatar:
            embed.set_thumbnail(url=avatar)

        # Row 1 — identity
        embed.add_field(name="🏅 Rank", value=f"**{p['Rank Placement']}** · {p['Rank']}", inline=True)
        embed.add_field(name="⭐ XP", value=f"{p['XP']:,}", inline=True)
        embed.add_field(name="🎮 Level", value=f"{p['Level']}", inline=True)

        # Row 2 — combat core
        embed.add_field(name="🎯 K/D Ratio", value=f"{p['K/D Ratio']}", inline=True)
        embed.add_field(name="💀 Kills", value=f"{p['Kills']:,}", inline=True)
        embed.add_field(name="☠️ Deaths", value=f"{p['Deaths']:,}", inline=True)

        # Row 3 — accuracy
        embed.add_field(name="🩸 Headshots", value=f"{p['Headshots']:,} ({p['Headshot %']}%)", inline=True)
        embed.add_field(name="🤝 Assists", value=f"{p['Assists']:,}", inline=True)
        embed.add_field(name="💥 Damage", value=f"{p['Damage']:,}", inline=True)

        # Row 4 — output
        embed.add_field(name="🔫 Shots", value=f"{p['Shots']:,}", inline=True)
        embed.add_field(name="✅ Hits", value=f"{p['Hits']:,}", inline=True)
        embed.add_field(name="🏆 MVP", value=f"{p['Most Valuable Player']:,}", inline=True)

        # Row 5 — objectives
        embed.add_field(name="💣 Planted", value=f"{p['C4 Planted']:,}", inline=True)
        embed.add_field(name="💥 Exploded", value=f"{p['C4 Exploded']:,}", inline=True)
        embed.add_field(name="🛡️ Defused", value=f"{p['C4 Defused']:,}", inline=True)

        # Top weapons (monospace, ASCII weapon names so alignment is safe)
        if p["Top Weapons"]:
            lines = "\n".join(
                "{:<11}{:>8,}".format(list(w.keys())[0], list(w.values())[0])
                for w in p["Top Weapons"]
            )
            embed.add_field(name="🔝 Top Weapons", value=f"```\n{lines}\n```", inline=False)

        # Activity
        embed.add_field(name="⏱️ Played Time", value=p["Played Time"], inline=True)
        embed.add_field(name="🥇 Rounds Won", value=f"{p['Rounds Won']:,}", inline=True)
        embed.add_field(name="​", value="​", inline=True)  # row filler
        embed.add_field(name="📅 First Login", value=p["First Login"], inline=True)
        embed.add_field(name="📅 Last Login", value=p["Last Login"], inline=True)
        embed.add_field(name="​", value="​", inline=True)  # row filler

        embed.set_footer(text="🟢 Online now" if online else "⚫ Offline")
        await interaction.followup.send(embed=embed)

    @staticmethod
    def _ambiguous_embed(player_names, query=None):
        title = "🔎 Multiple players matched"
        if query:
            title += f" “{query}”"
        embed = discord.Embed(
            title=title,
            description="Please re-enter a more precise name (case-sensitive):",
            color=discord.Color.red(),
        )
        embed.add_field(name="Did you mean…", value="`" + "`, `".join(str(n) for n in player_names) + "`")
        return embed

    async def _resolve_player_or_report(self, interaction, name):
        """Resolve a player name, or send a not-found / suggestions reply and
        return ``None``. Used by commands that need an exact single match."""
        data, mode = await self.db.get_player_info(name)
        if mode == -1 or not data:
            await interaction.followup.send(
                f"Player **{name}** could not be found. Make sure you enter a real player name.",
                ephemeral=True,
            )
            return None
        if mode == 1:
            await interaction.followup.send(embed=self._ambiguous_embed(data, name), ephemeral=True)
            return None
        return data

    # ------------------------------------------------------------------ #
    # /ip
    # ------------------------------------------------------------------ #
    @app_commands.command(name="ip", description="Returns an Embed of the Arabian IP")
    async def ip(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = discord.Embed(
            title="Welcome to Arabian Servers!",
            description="Have fun and enjoy your stay! 🎮",
            color=ARABIAN_COLOR,
            url="https://arabian-servers.com",
        )
        embed.set_author(name="JOIN US!", icon_url=ARABIAN_ICON)
        embed.set_thumbnail(url=ARABIAN_ICON)

        embed.add_field(name="🔥 Server IP", value="`151.80.47.182:27015`", inline=True)
        embed.add_field(name="📅 Running Since", value="2013", inline=True)

        try:
            info = await a2s.ainfo(SERVER_ADDRESS)
            embed.add_field(name="🎯 Current Players",
                            value=f"{info.player_count}/{info.max_players}", inline=True)
        except Exception:
            embed.add_field(name="🎯 Current Players", value="Server unreachable", inline=True)

        embed.add_field(name="🌍 Website",
                        value="[arabian-servers.com](https://arabian-servers.com)", inline=False)

        embed.set_footer(text="Arabian Servers for CS 1.6 since 2013 🕹️", icon_url=ARABIAN_ICON)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------ #
    # /top
    # ------------------------------------------------------------------ #
    def _leaderboard_table(self, players):
        # Name is placed last: player names can contain right-to-left or
        # non-monospace characters (e.g. Arabic) that would otherwise break
        # the alignment of every column after them.
        header = "{:<5}{:<8}{:<9}{:<8}{:<7}{:<11}{}\n".format(
            "#", "K-D", "XP", "Kills", "HS", "Skill", "Name")
        table = header + "-" * 56 + "\n"
        for row in players:
            table += "{:<5}{:<8}{:<9}{:<8}{:<7}{:<11}{}\n".format(
                row["Rank"], row["Diff"], row["XP"], row["Kills"], row["Headshots"],
                row["Skills"], _short_name(row["Name"]),
            )
        if not players:
            table += "No players on this page.\n"
        return f"```\n{table}```"

    async def build_top_embed(self, page: int):
        players, total = await self.db.get_top_players(page)
        max_page = max(1, -(-total // TOP_PAGE_SIZE))
        embed = discord.Embed(
            title="🏆 Leaderboard — Top Players",
            description=self._leaderboard_table(players),
            color=ARABIAN_COLOR,
        )
        embed.set_footer(text=f"Page {page} / {max_page}  ·  {total:,} ranked players  ·  sorted by frag difference (K-D)")
        return embed, total

    @app_commands.command(name="top", description="Displays the current leaderboard")
    async def top(self, interaction: discord.Interaction, page: int = 1):
        if page < 1:
            await interaction.response.send_message("Page number must be 1 or higher.", ephemeral=True)
            return

        await interaction.response.defer()
        embed, total = await self.build_top_embed(page)
        view = TopView(self, page, total)
        await interaction.followup.send(embed=embed, view=view)

    # ------------------------------------------------------------------ #
    # /online
    # ------------------------------------------------------------------ #
    @app_commands.command(name="online", description="Lists players currently online")
    async def online(self, interaction: discord.Interaction):
        await interaction.response.defer()
        players = await self.db.get_online_players()

        if not players:
            embed = discord.Embed(
                title="🟢 Online Players",
                description="No registered players are online right now.",
                color=ARABIAN_COLOR,
            )
            await interaction.followup.send(embed=embed)
            return

        table = "{:<4}{:<15}{:<9}{:<7}{}\n".format("#", "Rank", "XP", "K/D", "Name")
        table += "-" * 48 + "\n"
        for i, p in enumerate(players, start=1):
            kd = round((p["Kills"] or 0) / (p["Deaths"] or 1), 2)
            table += "{:<4}{:<15}{:<9}{:<7}{}\n".format(
                i, (p["Rank Name"] or "")[:13], p["XP"] or 0, kd, _short_name(p["Nick"]))

        embed = discord.Embed(
            title="🟢 Online Players",
            description=f"```\n{table}```",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"{len(players)} player(s) online")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------ #
    # /weaponstats
    # ------------------------------------------------------------------ #
    @app_commands.command(name="weaponstats", description="Full weapon kill breakdown for a player")
    async def weaponstats(self, interaction: discord.Interaction, player_name: str):
        await interaction.response.defer()
        data, mode = await self.db.get_weapon_breakdown(player_name)

        if mode == -1 or not data:
            await interaction.followup.send(f"No weapon data found for **{player_name}**.", ephemeral=True)
            return
        if mode == 1:
            await interaction.followup.send(embed=self._ambiguous_embed(data, player_name), ephemeral=True)
            return

        table = "{:<12}{:<8}{:<7}{}\n".format("Weapon", "Kills", "HS", "HS%")
        table += "-" * 33 + "\n"
        for w in data["weapons"]:
            hsp = round(w["hs"] / w["kills"] * 100, 1) if w["kills"] else 0.0
            table += "{:<12}{:<8}{:<7}{}\n".format(w["weapon"], w["kills"], w["hs"], f"{hsp}%")
        if not data["weapons"]:
            table += "No kills recorded.\n"

        embed = discord.Embed(
            title=f"🔫 {data['Name']} — Weapon Breakdown",
            description=f"```\n{table}```",
            color=ARABIAN_COLOR,
        )
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------ #
    # /compare
    # ------------------------------------------------------------------ #
    @staticmethod
    def _compare_block(d):
        return (
            f"🏅 {d['Rank Placement']} · {d['Rank']}\n"
            f"⭐ {d['XP']:,} XP\n"
            f"🎯 {d['K/D Ratio']} K/D\n"
            f"💀 {d['Kills']:,} / {d['Deaths']:,}\n"
            f"🩸 {d['Headshots']:,} ({d['Headshot %']}%)\n"
            f"💥 {d['Damage']:,} dmg\n"
            f"🏆 {d['Most Valuable Player']:,} MVP\n"
            f"⏱️ {d['Played Time']}"
        )

    @app_commands.command(name="compare", description="Compare two players head-to-head")
    async def compare(self, interaction: discord.Interaction, player_one: str, player_two: str):
        await interaction.response.defer()

        data_one = await self._resolve_player_or_report(interaction, player_one)
        if data_one is None:
            return
        data_two = await self._resolve_player_or_report(interaction, player_two)
        if data_two is None:
            return

        # Highlight who leads on XP in the title.
        leader = data_one if data_one["XP"] >= data_two["XP"] else data_two
        embed = discord.Embed(
            title=f"⚔️ {data_one['Name']}  vs  {data_two['Name']}",
            description=f"👑 Higher XP: **{leader['Name']}**",
            color=discord.Color.purple(),
        )
        embed.add_field(name=f"🔵 {data_one['Name']}", value=self._compare_block(data_one), inline=True)
        embed.add_field(name=f"🔴 {data_two['Name']}", value=self._compare_block(data_two), inline=True)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------ #
    # /topweapon
    # ------------------------------------------------------------------ #
    @app_commands.command(name="topweapon", description="Leaderboard of top killers with a specific weapon")
    @app_commands.describe(weapon="e.g. AK47, M4A1, AWP, Deagle, Knife...")
    async def topweapon(self, interaction: discord.Interaction, weapon: str):
        await interaction.response.defer()
        column = WEAPON_LOOKUP.get(weapon.strip().lower())
        if column is None:
            await interaction.followup.send(
                "Unknown weapon. Valid options:\n`" + "`, `".join(WEAPON_COLUMNS) + "`",
                ephemeral=True)
            return

        rows = await self.db.get_top_weapon(column)
        if not rows:
            await interaction.followup.send(f"No kills recorded with **{column}** yet.")
            return

        table = "{:<4}{:<9}{}\n".format("#", "Kills", "Name")
        table += "-" * 36 + "\n"
        for i, r in enumerate(rows, start=1):
            table += "{:<4}{:<9}{}\n".format(i, r["kills"], _short_name(r["Nick"]))

        embed = discord.Embed(
            title=f"🔝 Top {column} Killers",
            description=f"```\n{table}```",
            color=ARABIAN_COLOR,
        )
        await interaction.followup.send(embed=embed)

    @topweapon.autocomplete("weapon")
    async def weapon_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()
        matches = [w for w in WEAPON_COLUMNS if current in w.lower()][:25]
        return [app_commands.Choice(name=w, value=w) for w in matches]

    # ------------------------------------------------------------------ #
    # /serverstats
    # ------------------------------------------------------------------ #
    @app_commands.command(name="serverstats", description="Aggregate stats across all registered players")
    async def serverstats(self, interaction: discord.Interaction):
        await interaction.response.defer()
        s = await self.db.get_server_stats()
        if not s:
            await interaction.followup.send("No data available.", ephemeral=True)
            return

        kills = s["kills"] or 0
        deaths = s["deaths"] or 0
        kd = round(kills / deaths, 2) if deaths else float(kills)

        embed = discord.Embed(title="📊 Arabian Servers — Global Stats", color=discord.Color.gold())
        embed.set_thumbnail(url=ARABIAN_ICON)

        embed.add_field(name="👥 Registered Players", value=f"{s['total_players']:,}", inline=True)
        embed.add_field(name="🟢 Online Now", value=f"{s['online']:,}", inline=True)
        embed.add_field(name="⏱️ Combined Playtime", value=format_played_time(s["playtime"]), inline=True)

        embed.add_field(name="💀 Total Kills", value=f"{kills:,}", inline=True)
        embed.add_field(name="☠️ Total Deaths", value=f"{deaths:,}", inline=True)
        embed.add_field(name="🎯 Global K/D", value=f"{kd}", inline=True)

        embed.add_field(name="🩸 Total Headshots", value=f"{s['headshots'] or 0:,}", inline=True)
        embed.add_field(name="💣 C4 Planted", value=f"{s['planted'] or 0:,}", inline=True)
        embed.add_field(name="🛡️ C4 Defused", value=f"{s['defused'] or 0:,}", inline=True)

        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(CsLogic(bot))
