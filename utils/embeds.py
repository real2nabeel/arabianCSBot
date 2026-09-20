"""Shared presentation for community, game, and staff cards."""
import discord

BRAND_COLOR = discord.Colour.from_rgb(230, 145, 30)


def make_embed(*, section="Community", **kwargs):
    kwargs.setdefault("color", BRAND_COLOR)
    kwargs.setdefault("timestamp", discord.utils.utcnow())
    if kwargs.get("title"):
        kwargs["title"] = kwargs["title"][:256]
    embed = discord.Embed(**kwargs)
    embed.set_author(name=f"Arabian Servers • {section}")
    embed.set_footer(text="Arabian Servers • CS 1.6 community")
    return embed


def event_embed(title, description):
    """Turn event details into readable, bounded fields with semantic colors."""
    if any(word in title.lower() for word in ("failed", "deleted", "banned")) and "unbanned" not in title.lower():
        icon, colour = "🔴", discord.Colour.red()
    elif any(word in title.lower() for word in ("joined", "created", "unbanned")):
        icon, colour = "🟢", discord.Colour.green()
    else:
        icon, colour = "🟠", BRAND_COLOR
    lines = description.splitlines()
    embed = make_embed(section="Server logs", title=f"{icon} {title}",
                       description=(lines[0] if lines else "")[:1000], color=colour)
    fields = []
    for line in lines[1:]:
        label, separator, value = line.partition(": ")
        if separator:
            fields.append([label, value])
        elif fields:
            fields[-1][1] += "\n" + line
        else:
            fields.append(["Details", line])
    for label, value in fields[:10]:
        if len(value) > 450:
            value = value[:435] + "\n… (truncated)"
        embed.add_field(name=label[:256], value=value or "—", inline=False)
    embed.set_footer(text="Server logs")
    return embed


def permission_changes(before, after):
    old = dict(before)
    changes = [f"{'✅' if enabled else '➖'} {name.replace('_', ' ').title()}"
               for name, enabled in after if old.get(name) != enabled]
    return "\n".join(changes) or "No permission changes"
