"""Discord activity leveling: XP from text + voice, level roles, leaderboard.

This system is intentionally separate from the in-game CS 1.6 rank/XP. Because
the XP here can decide a cash-prize contest, several anti-abuse guards are built
in (per-user text cooldown, minimum message length, voice presence/deafen
checks) and an admin /xp-audit view exposes message/voice counters next to XP so
outliers are easy to spot before paying out.
"""

import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, button

from utils.constants import (
    TEXT_XP_MIN, TEXT_XP_MAX, TEXT_XP_COOLDOWN, MIN_MESSAGE_LENGTH,
    VOICE_XP_PER_TICK, VOICE_TICK_SECONDS, VOICE_MIN_HUMANS,
    XP_EXCLUDED_CHANNELS, LEVELUP_CHANNEL_ID, LOGGING_CHANNEL_ID,
)
from utils.database import format_played_time
from utils.leveling import (
    level_progress, level_from_xp, progress_bar, is_max_level, DEFAULT_RANK_NAMES,
)

XP_PAGE_SIZE = 15
ARABIAN_COLOR = discord.Color.from_rgb(230, 145, 30)


def _short_name(name, limit=16):
    name = (name or "Unknown").strip()
    return name if len(name) <= limit else name[:limit - 1] + "…"


class XpTopView(View):
    """Paginated XP leaderboard, mirroring the /top view in cogs/cs.py."""

    def __init__(self, cog, guild, page, total, timeout=120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild = guild
        self.page = page
        self.total = total
        self._update_buttons()

    def _max_page(self):
        return max(1, -(-self.total // XP_PAGE_SIZE))  # ceil division

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self._max_page()

    async def _render(self, interaction):
        embed, self.total = await self.cog.build_xptop_embed(self.guild, self.page)
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


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id) -> monotonic timestamp of last text award. In
        # memory only: a restart simply lets everyone earn again immediately,
        # which is harmless.
        self._text_cooldowns = {}
        self.voice_loop.start()

    def cog_unload(self):
        self.voice_loop.cancel()

    @property
    def db(self):
        return self.bot.db_bot

    # ------------------------------------------------------------------ #
    # Earning XP — text
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if message.channel.id in XP_EXCLUDED_CHANNELS:
            return
        if len(message.content.strip()) < MIN_MESSAGE_LENGTH:
            return

        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        last = self._text_cooldowns.get(key, 0.0)
        if now - last < TEXT_XP_COOLDOWN:
            return
        self._text_cooldowns[key] = now

        amount = random.randint(TEXT_XP_MIN, TEXT_XP_MAX)
        old_level, new_level = await self.db.add_xp(
            message.guild.id, message.author.id, amount,
            messages=1, touch_award=True,
        )
        if new_level > old_level:
            await self._handle_levelup(message.author, new_level, message.channel)

    # ------------------------------------------------------------------ #
    # Earning XP — voice
    # ------------------------------------------------------------------ #
    @tasks.loop(seconds=VOICE_TICK_SECONDS)
    async def voice_loop(self):
        for guild in self.bot.guilds:
            afk = guild.afk_channel
            for vc in guild.voice_channels:
                if afk is not None and vc.id == afk.id:
                    continue
                humans = [m for m in vc.members if not m.bot]
                if len(humans) < VOICE_MIN_HUMANS:
                    continue  # can't farm XP sitting alone
                for member in humans:
                    voice = member.voice
                    # Deafened == not actually listening; treat as AFK.
                    if voice is None or voice.deaf or voice.self_deaf:
                        continue
                    old_level, new_level = await self.db.add_xp(
                        guild.id, member.id, VOICE_XP_PER_TICK,
                        voice_seconds=VOICE_TICK_SECONDS,
                    )
                    if new_level > old_level:
                        # No triggering text channel for voice; announce only if
                        # a dedicated level-up channel is configured.
                        await self._handle_levelup(member, new_level, None)

    @voice_loop.before_loop
    async def _before_voice_loop(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    # Level-up: roles + announcement
    # ------------------------------------------------------------------ #
    async def _handle_levelup(self, member, new_level, fallback_channel):
        role = await self._apply_level_roles(member, new_level)
        await self._announce_levelup(member, new_level, fallback_channel, role)

    async def _apply_level_roles(self, member, level):
        """Grant the highest configured tier the member qualifies for and strip
        the lower configured tiers. Returns the granted role (if any) for the
        announcement, or None."""
        tiers = await self.db.list_level_roles(member.guild.id)
        if not tiers:
            return None

        qualifying = [t for t in tiers if t["level"] <= level]
        target = max(qualifying, key=lambda t: t["level"]) if qualifying else None

        target_role = None
        to_add = None
        if target:
            target_role = member.guild.get_role(target["role_id"])
            if target_role and target_role not in member.roles:
                to_add = target_role

        to_remove = []
        for t in tiers:
            if target and t["level"] == target["level"]:
                continue
            role = member.guild.get_role(t["role_id"])
            if role and role in member.roles:
                to_remove.append(role)

        try:
            if to_add:
                await member.add_roles(to_add, reason=f"Reached level {level}")
            if to_remove:
                await member.remove_roles(*to_remove, reason="Level role update")
        except discord.Forbidden:
            await self._log(
                f"⚠️ Missing permission to manage level roles for "
                f"{member.mention}. Check that the bot has **Manage Roles** and "
                f"that its role is **above** the level roles."
            )
        except discord.HTTPException:
            pass
        return target_role if to_add else None

    async def _current_rank_role(self, guild, level):
        """The highest configured tier role the given level qualifies for, or
        None. Used for display on the rank card."""
        tiers = await self.db.list_level_roles(guild.id)
        qualifying = [t for t in tiers if t["level"] <= level]
        if not qualifying:
            return None
        target = max(qualifying, key=lambda t: t["level"])
        return guild.get_role(target["role_id"])

    async def _announce_levelup(self, member, new_level, fallback_channel, role):
        channel = None
        if LEVELUP_CHANNEL_ID:
            channel = member.guild.get_channel(LEVELUP_CHANNEL_ID)
        if channel is None:
            channel = fallback_channel
        if channel is None:
            return

        desc = f"🎉 {member.mention} just reached **Level {new_level}**!"
        if role is not None:
            desc += f"\nUnlocked the {role.mention} role."
        embed = discord.Embed(description=desc, color=ARABIAN_COLOR)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _log(self, text):
        if not LOGGING_CHANNEL_ID:
            return
        channel = self.bot.get_channel(LOGGING_CHANNEL_ID)
        if channel is not None:
            try:
                await channel.send(text)
            except discord.HTTPException:
                pass

    def _member_name(self, guild, user_id):
        member = guild.get_member(user_id)
        if member is not None:
            return member.display_name
        user = self.bot.get_user(user_id)
        return user.name if user is not None else f"User {user_id}"

    # ------------------------------------------------------------------ #
    # /level
    # ------------------------------------------------------------------ #
    @app_commands.command(name="level", description="Show your (or another member's) Discord level and XP")
    @app_commands.describe(member="Whose level to show (defaults to you)")
    async def level(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        member = member or interaction.user
        row = await self.db.get_member_xp(interaction.guild.id, member.id)
        if not row or not row["xp"]:
            await interaction.followup.send(
                f"**{member.display_name}** hasn't earned any XP yet.", ephemeral=True)
            return

        xp = row["xp"]
        lvl, into_level, needed = level_progress(xp)
        position = await self.db.get_xp_position(interaction.guild.id, xp)
        total = await self.db.get_xp_total_members(interaction.guild.id)
        rank_role = await self._current_rank_role(interaction.guild, lvl)

        embed = discord.Embed(
            title=f"📈 {member.display_name} — Level {lvl}",
            color=rank_role.color if rank_role else ARABIAN_COLOR,
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="🏅 Position", value=f"#{position} / {total:,}", inline=True)
        embed.add_field(name="🎮 Level", value=f"{lvl}", inline=True)
        embed.add_field(name="⭐ Total XP", value=f"{xp:,}", inline=True)
        if rank_role:
            embed.add_field(name="🎖️ Rank", value=rank_role.mention, inline=False)
        if is_max_level(lvl):
            embed.add_field(name="Progress", value="🏆 **Max rank reached!**", inline=False)
        else:
            bar = progress_bar(into_level, needed)
            embed.add_field(
                name=f"Progress to Level {lvl + 1}",
                value=f"`{bar}`\n{into_level:,} / {needed:,} XP",
                inline=False,
            )
        embed.add_field(name="💬 Messages", value=f"{row['messages']:,}", inline=True)
        embed.add_field(name="🔊 Voice", value=format_played_time(row["voice_seconds"]), inline=True)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------ #
    # /xptop
    # ------------------------------------------------------------------ #
    def _xptop_table(self, guild, rows, offset):
        header = "{:<4}{:<6}{:<9}{}\n".format("#", "Lvl", "XP", "Name")
        table = header + "-" * 38 + "\n"
        for i, r in enumerate(rows):
            table += "{:<4}{:<6}{:<9}{}\n".format(
                offset + i + 1, r["level"], f"{r['xp']:,}",
                _short_name(self._member_name(guild, r["user_id"]), 14),
            )
        if not rows:
            table += "No ranked members on this page.\n"
        return f"```\n{table}```"

    async def build_xptop_embed(self, guild, page):
        rows, total = await self.db.get_top_xp(guild.id, page)
        offset = (max(1, page) - 1) * XP_PAGE_SIZE
        max_page = max(1, -(-total // XP_PAGE_SIZE))
        embed = discord.Embed(
            title="🏆 Discord Activity Leaderboard",
            description=self._xptop_table(guild, rows, offset),
            color=ARABIAN_COLOR,
        )
        embed.set_footer(text=f"Page {page} / {max_page}  ·  {total:,} ranked members")
        return embed, total

    @app_commands.command(name="xptop", description="Discord activity XP leaderboard")
    async def xptop(self, interaction: discord.Interaction, page: int = 1):
        if page < 1:
            await interaction.response.send_message("Page number must be 1 or higher.", ephemeral=True)
            return
        await interaction.response.defer()
        embed, total = await self.build_xptop_embed(interaction.guild, page)
        view = XpTopView(self, interaction.guild, page, total)
        await interaction.followup.send(embed=embed, view=view)

    # ------------------------------------------------------------------ #
    # /levelrole  (admin) — configure which role is granted at which level
    # ------------------------------------------------------------------ #
    levelrole = app_commands.Group(
        name="levelrole",
        description="Configure which role members earn at each level",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @levelrole.command(name="set", description="Set/overwrite the role granted at a given level")
    @app_commands.describe(level="Level threshold (1+)", role="Role to grant at this level")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def levelrole_set(self, interaction: discord.Interaction, level: int, role: discord.Role):
        if level < 1:
            await interaction.response.send_message("Level must be 1 or higher.", ephemeral=True)
            return
        if role.is_default() or role.managed:
            await interaction.response.send_message(
                "That role can't be used as a level role (it's @everyone or bot-managed).",
                ephemeral=True)
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"I can't assign {role.mention} — it's above my highest role. "
                "Move my role above it in Server Settings → Roles.",
                ephemeral=True)
            return
        await self.db.set_level_role(interaction.guild.id, level, role.id)
        await interaction.response.send_message(
            f"✅ Members reaching **Level {level}** will now get {role.mention}.")

    @levelrole.command(name="remove", description="Remove the role tier at a given level")
    @app_commands.describe(level="Level threshold to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def levelrole_remove(self, interaction: discord.Interaction, level: int):
        deleted = await self.db.remove_level_role(interaction.guild.id, level)
        if deleted:
            await interaction.response.send_message(f"🗑️ Removed the role tier for **Level {level}**.")
        else:
            await interaction.response.send_message(
                f"No role tier is configured for Level {level}.", ephemeral=True)

    @levelrole.command(
        name="import",
        description="Bulk-map the default CS:GO ranks to roles of the same name",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def levelrole_import(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild
        # Case-insensitive name -> role lookup. If two roles share a name, the
        # first (higher) one wins, which is the sane default.
        by_name = {}
        for role in guild.roles:
            by_name.setdefault(role.name.strip().lower(), role)

        mapped, missing, too_high = [], [], []
        for level, name in sorted(DEFAULT_RANK_NAMES.items()):
            role = by_name.get(name.lower())
            if role is None:
                missing.append(f"L{level} · {name}")
                continue
            if role.is_default() or role.managed:
                missing.append(f"L{level} · {name} (unusable role)")
                continue
            await self.db.set_level_role(guild.id, level, role.id)
            mapped.append(f"L{level} → {role.mention}")
            if role >= guild.me.top_role:
                too_high.append(role.mention)

        embed = discord.Embed(
            title="📥 Level Role Import",
            color=ARABIAN_COLOR,
            description=(
                f"Matched **{len(mapped)}** of {len(DEFAULT_RANK_NAMES)} ranks "
                "by role name (case-insensitive)."
            ),
        )
        if mapped:
            embed.add_field(name="✅ Mapped", value="\n".join(mapped), inline=False)
        if missing:
            embed.add_field(
                name="❌ No matching role (create them, then re-run)",
                value="\n".join(missing), inline=False)
        if too_high:
            embed.add_field(
                name="⚠️ Above my top role — I can't assign these",
                value="Move my role above them in Server Settings → Roles:\n"
                      + ", ".join(too_high),
                inline=False)
        await interaction.followup.send(embed=embed)

    @levelrole.command(name="list", description="Show all configured level → role tiers")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def levelrole_list(self, interaction: discord.Interaction):
        tiers = await self.db.list_level_roles(interaction.guild.id)
        if not tiers:
            await interaction.response.send_message(
                "No level roles configured yet. Use `/levelrole set` to add some.",
                ephemeral=True)
            return
        lines = []
        for t in tiers:
            role = interaction.guild.get_role(t["role_id"])
            label = role.mention if role else f"⚠️ deleted role ({t['role_id']})"
            lines.append(f"**Level {t['level']}** → {label}")
        embed = discord.Embed(
            title="🎚️ Level Roles",
            description="\n".join(lines),
            color=ARABIAN_COLOR,
        )
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------ #
    # Admin XP management
    # ------------------------------------------------------------------ #
    @app_commands.command(name="xp-give", description="[Admin] Give XP to a member")
    @app_commands.describe(member="Member to award", amount="XP to add (use a negative number to subtract)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def xp_give(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount == 0:
            await interaction.response.send_message("Amount must be non-zero.", ephemeral=True)
            return
        if amount < 0:
            # Clamp so we never go below zero: read current, set the floor.
            row = await self.db.get_member_xp(interaction.guild.id, member.id)
            current = row["xp"] if row else 0
            await self.db.set_member_xp(
                interaction.guild.id, member.id, max(0, current + amount))
        else:
            await self.db.add_xp(interaction.guild.id, member.id, amount)
        await interaction.response.send_message(
            f"✅ Adjusted {member.mention}'s XP by **{amount:+,}**.")
        # Re-sync roles to the (possibly new) level either way.
        row = await self.db.get_member_xp(interaction.guild.id, member.id)
        if row:
            await self._apply_level_roles(member, level_from_xp(row["xp"]))

    @app_commands.command(name="xp-set", description="[Admin] Set a member's XP to an exact value")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def xp_set(self, interaction: discord.Interaction, member: discord.Member, xp: int):
        if xp < 0:
            await interaction.response.send_message("XP can't be negative.", ephemeral=True)
            return
        level = await self.db.set_member_xp(interaction.guild.id, member.id, xp)
        await self._apply_level_roles(member, level)
        await interaction.response.send_message(
            f"✅ Set {member.mention} to **{xp:,} XP** (Level {level}).")

    @app_commands.command(name="xp-reset", description="[Admin] Reset a member's XP to zero")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def xp_reset(self, interaction: discord.Interaction, member: discord.Member):
        await self.db.reset_member_xp(interaction.guild.id, member.id)
        # Strip every configured level role from them.
        await self._apply_level_roles(member, -1)
        await interaction.response.send_message(f"♻️ Reset {member.mention}'s XP to zero.")

    @app_commands.command(name="xp-audit", description="[Admin] Top members with XP vs. message/voice counters (spot farming)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def xp_audit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = await self.db.get_xp_audit(interaction.guild.id, limit=15)
        if not rows:
            await interaction.followup.send("No XP data yet.", ephemeral=True)
            return
        table = "{:<4}{:<8}{:<7}{:<7}{}\n".format("#", "XP", "Msgs", "Voice", "Name")
        table += "-" * 44 + "\n"
        for i, r in enumerate(rows, start=1):
            voice_min = (r["voice_seconds"] or 0) // 60
            table += "{:<4}{:<8}{:<7}{:<7}{}\n".format(
                i, f"{r['xp']:,}", r["messages"], f"{voice_min}m",
                _short_name(self._member_name(interaction.guild, r["user_id"]), 14),
            )
        embed = discord.Embed(
            title="🔍 XP Audit",
            description=f"```\n{table}```",
            color=discord.Color.red(),
        )
        embed.set_footer(text="Compare XP against messages/voice to spot farming before paying out.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    # Friendly errors for the admin-gated commands
    # ------------------------------------------------------------------ #
    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
            msg = "You need the **Manage Server** permission to use this command."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        raise error


async def setup(bot):
    await bot.add_cog(Leveling(bot))
