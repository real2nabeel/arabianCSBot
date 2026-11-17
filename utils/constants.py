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

# Server management. Zero/empty channel IDs disable the corresponding feature.
SERVER_LOG_CHANNEL_ID = _int_env("SERVER_LOG_CHANNEL_ID")
MOD_LOG_CHANNEL_ID = _int_env("MOD_LOG_CHANNEL_ID", SERVER_LOG_CHANNEL_ID)
LOG_EXCLUDED_CHANNELS = _id_list_env("LOG_EXCLUDED_CHANNELS")
WELCOME_CHANNEL_ID = _int_env("WELCOME_CHANNEL_ID")
WELCOME_MESSAGE = os.getenv(
    "WELCOME_MESSAGE", "Welcome {mention} to {server}! Please read the server rules."
)
AUTO_ROLE_IDS = _id_list_env("AUTO_ROLE_IDS")

# Dashboard and opt-in activity alerts; blank IDs disable each feature.
DASHBOARD_CHANNEL_ID = _int_env("DASHBOARD_CHANNEL_ID")
ACTIVITY_ALERT_CHANNEL_ID = _int_env("ACTIVITY_ALERT_CHANNEL_ID")
ACTIVITY_ALERT_ROLE_ID = _int_env("ACTIVITY_ALERT_ROLE_ID")
SERVER_POLL_SECONDS = _int_env("SERVER_POLL_SECONDS", 30)
DASHBOARD_REFRESH_SECONDS = _int_env("DASHBOARD_REFRESH_SECONDS", 60)
LEADERBOARD_REFRESH_SECONDS = _int_env("LEADERBOARD_REFRESH_SECONDS", 300)
ACTIVITY_HUMAN_THRESHOLD = _int_env("ACTIVITY_HUMAN_THRESHOLD", 15)
ACTIVITY_SUSTAIN_SECONDS = _int_env("ACTIVITY_SUSTAIN_SECONDS", 120)
ACTIVITY_REARM_BELOW = _int_env("ACTIVITY_REARM_BELOW", 4)
ACTIVITY_REARM_SECONDS = _int_env("ACTIVITY_REARM_SECONDS", 300)
ACTIVITY_COOLDOWN_SECONDS = _int_env("ACTIVITY_COOLDOWN_SECONDS", 7200)

# Server activity graph and admin activity table. Player counts are sampled on
# every SERVER_POLL_SECONDS poll; admins are players in the live rank table
# whose AMX Mod X access flags contain ADMIN_FLAG ("c" = kick, the usual admin
# marker). Times and day boundaries use ACTIVITY_UTC_OFFSET (hours).
STAFF_ACTIVITY_CHANNEL_ID = _int_env("STAFF_ACTIVITY_CHANNEL_ID")
ADMIN_FLAG = os.getenv("ADMIN_FLAG", "c").strip() or "c"
ACTIVITY_REFRESH_SECONDS = _int_env("ACTIVITY_REFRESH_SECONDS", 600)
ACTIVITY_HISTORY_DAYS = _int_env("ACTIVITY_HISTORY_DAYS", 30)
ACTIVITY_UTC_OFFSET = _int_env("ACTIVITY_UTC_OFFSET", 3)

# --- Highlight clips (cogs/clips.py) ---------------------------------------- #
# The host-side job (clips/nightly.py) writes finished clips into CLIPS_DIR (mounted into the container); each
# is posted to CLIPS_REVIEW_CHANNEL_ID. A 👍 from a member with one of CLIPS_APPROVER_ROLE_IDS (or Administrator)
# approves it, ❌ rejects it. Approved clips are posted to CLIPS_PLATFORMS, at most CLIPS_POSTS_PER_DAY per
# platform, CLIPS_POST_GAP_MINUTES apart, between CLIPS_POST_HOURS (server time, ACTIVITY_UTC_OFFSET).
# A blank channel turns the whole feature off.
CLIPS_DIR = os.getenv("CLIPS_DIR", "/clips")
CLIPS_REVIEW_CHANNEL_ID = _int_env("CLIPS_REVIEW_CHANNEL_ID")
CLIPS_APPROVER_ROLE_IDS = _id_list_env("CLIPS_APPROVER_ROLE_IDS")
CLIPS_PLATFORMS = [p.strip().lower() for p in os.getenv("CLIPS_PLATFORMS", "facebook,instagram").split(",") if p.strip()]
CLIPS_POSTS_PER_DAY = _int_env("CLIPS_POSTS_PER_DAY", 2)
CLIPS_POST_GAP_MINUTES = _int_env("CLIPS_POST_GAP_MINUTES", 240)
CLIPS_POST_HOURS = os.getenv("CLIPS_POST_HOURS", "12-23").strip()
CLIPS_CHECK_MINUTES = _int_env("CLIPS_CHECK_MINUTES", 10)
CLIPS_CAPTION = os.getenv(
    "CLIPS_CAPTION", "🔥 {player} – {summary} on {map}\n🎮 Play with us: connect {server}\n\n{hashtags}"
).replace("\n", "\n")
CLIPS_HASHTAGS = os.getenv(
    "CLIPS_HASHTAGS",
    "#CounterStrike #CS16 #CounterStrike16 #dust2 #FPS #Gaming #ArabGamers #ArabianServers #كاونتر_سترايك",
).strip()
CLIPS_SERVER_ADDRESS = os.getenv("CLIPS_SERVER_ADDRESS", "").strip() or f"{SERVER_ADDRESS[0]}:{SERVER_ADDRESS[1]}"

# Platform credentials. Meta: a never-expiring system-user token with the Page and Instagram account assigned.
META_TOKEN = os.getenv("META_TOKEN", "").strip()
META_PAGE_ID = os.getenv("META_PAGE_ID", "").strip()
META_IG_ID = os.getenv("META_IG_ID", "").strip()
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v23.0").strip()
# YouTube and TikTok keep refreshable tokens in JSON files (mounted read-write so refreshed tokens are saved).
YOUTUBE_TOKEN_FILE = os.getenv("YOUTUBE_TOKEN_FILE", "/clips-secrets/youtube_token.json")
YOUTUBE_PRIVACY = os.getenv("YOUTUBE_PRIVACY", "private").strip()   # an unaudited Google app can only post private
TIKTOK_TOKEN_FILE = os.getenv("TIKTOK_TOKEN_FILE", "/clips-secrets/tiktok_token.json")
TIKTOK_CLIENT_FILE = os.getenv("TIKTOK_CLIENT_FILE", "/clips-secrets/tiktok_client")
TIKTOK_MODE = os.getenv("TIKTOK_MODE", "inbox").strip()            # inbox = to the app's drafts; direct needs an audit
