"""Shared guards for server management."""
import re


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
