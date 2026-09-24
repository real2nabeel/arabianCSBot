"""Shared guards for server management."""
import re

import discord


def member_profile(user):
    """Named profile link remains readable even after a member leaves the guild."""
    name = getattr(user, "display_name", None) or getattr(user, "name", None) or "Member"
    name = discord.utils.escape_markdown(str(name).replace("\n", " "))
    name = name.replace("[", "\\[").replace("]", "\\]")
    return f"[{name}](https://discord.com/users/{user.id})"


def log_code_block(content):
    """Keep user text inside a closed code fence and Discord's field limit."""
    text = (content or "(No text content)").replace("`", "`\u200b")
    if len(text) > 1000:
        text = text[:985] + "\n… (truncated)"
    return f"```\n{text}\n```"


def message_log_embed(guild_id, channel_id, message_id, *, author=None,
                      author_id=None, deleted=False):
    """Compact message event card; deleted messages link to their channel."""
    author_id = author.id if author is not None else author_id
    channel_url = f"https://discord.com/channels/{guild_id}/{channel_id}"
    link = channel_url if deleted else f"{channel_url}/{message_id}"
    label = "Open channel" if deleted else "Jump to message"
    embed = discord.Embed(
        title="🗑️ Message deleted" if deleted else "✏️ Message edited",
        description=f"[↗ {label}]({link})",
        colour=discord.Colour.red() if deleted else discord.Colour.gold(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Author", value=f"<@{author_id}>" if author_id else "Unknown · not cached", inline=True)
    embed.add_field(name="Channel", value=f"<#{channel_id}>", inline=True)
    avatar = getattr(author, "display_avatar", None)
    if avatar is not None:
        embed.set_thumbnail(url=str(avatar.url))
    embed.set_footer(text="Server logs • Deleted" if deleted else "Server logs • Edited")
    return embed


def safe_auto_role(role, me):
    if role.is_default() or role.managed or role >= me.top_role:
        return False
    dangerous = {
        "administrator", "manage_guild", "manage_roles", "manage_channels",
        "kick_members", "ban_members", "moderate_members", "manage_messages",
        "manage_webhooks", "mention_everyone", "manage_threads",
    }
    return not any(getattr(role.permissions, name, False) for name in dangerous)


def welcome_text(template, member):
    values = {"mention": member.mention, "user": member.display_name,
              "server": member.guild.name, "count": str(member.guild.member_count)}
    return re.sub(r"\{(mention|user|server|count)\}",
                  lambda match: values[match.group(1)], template)[:2000]
