"""Configuration loaded from environment variables (.env file).

Copy ``.env.example`` to ``.env`` and fill in the values. Nothing secret
should ever be committed to the repository.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _int_env(name, default=0):
    """Read an int env var, tolerating empty/blank values."""
    value = os.getenv(name, "")
    return int(value) if value.strip() else default

# --- Discord -------------------------------------------------------------- #
TOKEN = os.getenv("DISCORD_TOKEN")
LOGGING_CHANNEL_ID = _int_env("LOGGING_CHANNEL_ID")

# The single Discord server this bot is allowed to operate in. Commands are
# synced only to this guild, and the bot leaves any other server it joins.
GUILD_ID = _int_env("GUILD_ID")

# --- CS 1.6 game server (used by a2s for the /ip player count) ------------ #
SERVER_ADDRESS = (
    os.getenv("SERVER_IP", "151.80.47.182"),
    int(os.getenv("SERVER_PORT", "27015")),
)

# --- MySQL rank databases ------------------------------------------------- #
# Two schemas live on the same MySQL server, sharing host/credentials:
#   * the LIVE ranking   (current season)  -> DB_NAME_LIVE   (default "liverank")
#   * the HISTORICAL rank (all-time/legacy) -> DB_NAME        (default "rankTest")
# The rank_system tables are structurally identical, so the same query layer is
# reused, just pointed at a different database name. The weapon_kills tables
# differ: rankTest (history) has a Nick column and per-weapon "<Weapon> HS"
# headshot columns; liverank (live) has neither. The query layer accounts for
# this (see Database.get_top_weapon / get_weapon_breakdown).
_DB_BASE = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
}

DB_CONFIG_LIVE = {**_DB_BASE, "db": os.getenv("DB_NAME_LIVE", "liverank")}
DB_CONFIG_HISTORY = {**_DB_BASE, "db": os.getenv("DB_NAME", "rankTest")}

# Backwards-compatible default (live) for any single-DB callers.
DB_CONFIG = DB_CONFIG_LIVE

# --- Discord activity leveling -------------------------------------------- #
# A standalone XP/level system driven by Discord activity (text + voice). It is
# completely separate from the in-game CS 1.6 rank/XP. The bot's leveling tables
# (discord_xp, level_roles) live in their own schema by default so bot state is
# never mixed into the game ranking data; point it elsewhere with DB_NAME_BOT.
DB_CONFIG_BOT = {**_DB_BASE, "db": os.getenv("DB_NAME_BOT", "arabianbot")}

# Text XP: a random amount in [min, max] per qualifying message, granted at most
# once per TEXT_XP_COOLDOWN seconds per user. Messages shorter than
# MIN_MESSAGE_LENGTH (after stripping) earn nothing — the main anti-spam guard.
TEXT_XP_MIN = _int_env("TEXT_XP_MIN", 15)
TEXT_XP_MAX = _int_env("TEXT_XP_MAX", 25)
TEXT_XP_COOLDOWN = _int_env("TEXT_XP_COOLDOWN", 60)
MIN_MESSAGE_LENGTH = _int_env("MIN_MESSAGE_LENGTH", 3)

# Voice XP: granted every VOICE_TICK_SECONDS to each qualifying member. A member
# qualifies only if they are not deafened AND there are at least
# VOICE_MIN_HUMANS non-bot members in the channel (so you cannot farm by sitting
# alone). The AFK channel is always excluded.
VOICE_XP_PER_TICK = _int_env("VOICE_XP_PER_TICK", 10)
VOICE_TICK_SECONDS = _int_env("VOICE_TICK_SECONDS", 60)
VOICE_MIN_HUMANS = _int_env("VOICE_MIN_HUMANS", 2)

# Channel IDs (comma-separated) where text messages earn no XP.
def _id_list_env(name):
    raw = os.getenv(name, "")
    return {int(part) for part in raw.replace(",", " ").split() if part.strip().isdigit()}

XP_EXCLUDED_CHANNELS = _id_list_env("XP_EXCLUDED_CHANNELS")

# Channel to announce level-ups in. If 0/unset, the bot replies in the channel
# where the message that triggered the level-up was sent (and stays silent for
# voice level-ups).
LEVELUP_CHANNEL_ID = _int_env("LEVELUP_CHANNEL_ID")
