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
# Both have identical table structures (rank_system + weapon_kills), so the
# same query layer is reused, just pointed at a different database name.
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
