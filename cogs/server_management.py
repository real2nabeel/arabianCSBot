"""Server event logs, welcome messages, and screening-aware automatic roles."""
import logging

import discord
from discord.ext import commands

from utils.constants import (
    GUILD_ID, SERVER_LOG_CHANNEL_ID, MOD_LOG_CHANNEL_ID, LOG_EXCLUDED_CHANNELS,
    WELCOME_CHANNEL_ID, WELCOME_MESSAGE, AUTO_ROLE_IDS,
)
from utils.server_management import safe_auto_role, welcome_text

logger = logging.getLogger(__name__)


class ServerManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def enabled_guild(self, guild):
        return guild is not None and (not GUILD_ID or guild.id == GUILD_ID)

    def ignored_channel(self, guild, channel_id):
        channel = guild.get_channel_or_thread(channel_id)
        excluded = LOG_EXCLUDED_CHANNELS | {SERVER_LOG_CHANNEL_ID, MOD_LOG_CHANNEL_ID}
        return (channel_id in excluded
                or getattr(channel, "parent_id", None) in excluded
                or getattr(channel, "category_id", None) in excluded)

    async def send_log(self, guild, title, description, *, moderation=False):
        if not self.enabled_guild(guild):
            return
        channel_id = MOD_LOG_CHANNEL_ID if moderation else SERVER_LOG_CHANNEL_ID
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            logger.warning("Log channel %s is not available in guild %s", channel_id, guild.id)
            return
        embed = discord.Embed(title=title[:256], description=description[:4096],
                              colour=discord.Colour.blurple(), timestamp=discord.utils.utcnow())
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logger.exception("Could not send %s to log channel %s", title, channel_id)

    async def apply_auto_roles(self, member):
        if not self.enabled_guild(member.guild) or member.bot or member.pending:
            return
        me = member.guild.me
        for role_id in sorted(AUTO_ROLE_IDS):
            role = member.guild.get_role(role_id)
            if role in member.roles:
                continue
            if role is None or me is None or not safe_auto_role(role, me):
                logger.warning("Skipping unavailable/unsafe automatic role %s", role_id)
                continue
            try:
                await member.add_roles(role, reason="Automatic member role after screening")
            except discord.HTTPException:
                logger.exception("Failed automatic role %s for member %s", role_id, member.id)
                await self.send_log(member.guild, "Automatic role failed",
                                    f"Member: {member.id}\nRole: {role_id}\nCheck Manage Roles and role hierarchy.")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not self.enabled_guild(member.guild):
            return
        await self.send_log(member.guild, "Member joined",
                            f"{member} ({member.id})\nAccount created: {member.created_at:%Y-%m-%d %H:%M UTC}")
        await self.apply_auto_roles(member)
        if member.bot or not WELCOME_CHANNEL_ID:
            return
        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
        if channel is None:
            logger.warning("Welcome channel %s is unavailable", WELCOME_CHANNEL_ID)
            return
        content = welcome_text(WELCOME_MESSAGE, member)
        if not content.strip():
            return
        try:
            await channel.send(content, allowed_mentions=discord.AllowedMentions(
                users=[member], roles=False, everyone=False, replied_user=False,
            ))
        except discord.HTTPException:
            logger.exception("Could not welcome member %s", member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.send_log(member.guild, "Member left", f"{member} ({member.id})")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if not self.enabled_guild(after.guild):
            return
        if before.pending and not after.pending:
            await self.apply_auto_roles(after)
        changes = []
        if before.nick != after.nick:
            changes.append(f"Nickname: {before.nick or '(none)'} → {after.nick or '(none)'}")
        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        if added:
            changes.append("Roles added: " + ", ".join(f"{r.name} ({r.id})" for r in added))
        if removed:
            changes.append("Roles removed: " + ", ".join(f"{r.name} ({r.id})" for r in removed))
        if before.timed_out_until != after.timed_out_until:
            changes.append(f"Timeout: {after.timed_out_until or 'removed'}")
        if changes:
            await self.send_log(after.guild, "Member updated", f"{after} ({after.id})\n" + "\n".join(changes))

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.send_log(guild, "Member banned", f"{user} ({user.id})", moderation=True)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.send_log(guild, "Member unbanned", f"{user} ({user.id})", moderation=True)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        if not self.enabled_guild(guild) or self.ignored_channel(guild, payload.channel_id):
            return
        message = payload.cached_message
        if message is not None and message.author.bot:
            return
        description = f"Channel: <#{payload.channel_id}>\nMessage ID: {payload.message_id}"
        if message:
            description += f"\nAuthor: {message.author} ({message.author.id})\n{message.content[:2500] or '(no text)'}"
            if message.attachments:
                description += "\nAttachments: " + ", ".join(a.filename for a in message.attachments)[:500]
        else:
            description += "\nContent and author unavailable (message was not cached)."
        await self.send_log(guild, "Message deleted", description)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        if not self.enabled_guild(guild) or self.ignored_channel(guild, payload.channel_id):
            return
        await self.send_log(guild, "Messages bulk deleted",
                            f"Channel: <#{payload.channel_id}>\nCount: {len(payload.message_ids)}\n"
                            "IDs (up to 100): " + ", ".join(str(i) for i in sorted(payload.message_ids)[:100]))

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if "content" not in payload.data:
            return  # Ignore embed previews and other non-content updates.
        guild = self.bot.get_guild(payload.guild_id)
        if not self.enabled_guild(guild) or self.ignored_channel(guild, payload.channel_id):
            return
        before = payload.cached_message
        if before and (before.author.bot or before.content == payload.data["content"]):
            return
        if payload.data.get("author", {}).get("bot"):
            return
        old = before.content if before else "Unavailable (message was not cached)"
        author = str(before.author.id) if before else payload.data.get("author", {}).get("id", "Unknown")
        await self.send_log(guild, "Message edited",
                            f"Channel: <#{payload.channel_id}>\nMessage ID: {payload.message_id}\nAuthor: {author}\n"
                            f"Before:\n{old[:1500]}\nAfter:\n{payload.data['content'][:1500]}")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if not self.ignored_channel(channel.guild, channel.id):
            await self.send_log(channel.guild, "Channel created", f"{channel.name} ({channel.id})")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if not self.ignored_channel(channel.guild, channel.id):
            await self.send_log(channel.guild, "Channel deleted", f"{channel.name} ({channel.id})")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if self.ignored_channel(after.guild, after.id):
            return
        changes = []
        for attr in ("name", "topic", "category_id", "slowmode_delay", "nsfw", "bitrate", "user_limit"):
            if getattr(before, attr, None) != getattr(after, attr, None):
                changes.append(f"{attr}: {getattr(before, attr, None)} → {getattr(after, attr, None)}")
        if before.overwrites != after.overwrites:
            changes.append("Channel permission overrides changed.")
        if changes:
            await self.send_log(after.guild, "Channel updated", f"{after.name} ({after.id})\n" + "\n".join(changes))

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.send_log(role.guild, "Role created", f"{role.name} ({role.id})")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.send_log(role.guild, "Role deleted", f"{role.name} ({role.id})")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = []
        for attr in ("name", "colour", "hoist", "mentionable", "position"):
            if getattr(before, attr) != getattr(after, attr):
                changes.append(f"{attr}: {getattr(before, attr)} → {getattr(after, attr)}")
        if before.permissions != after.permissions:
            changes.append(f"Permissions: {before.permissions.value} → {after.permissions.value}")
        if changes:
            await self.send_log(after.guild, "Role updated", f"{after.name} ({after.id})\n" + "\n".join(changes))


async def setup(bot):
    await bot.add_cog(ServerManagement(bot))
