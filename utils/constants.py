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

# --- MySQL rank database -------------------------------------------------- #
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "db": os.getenv("DB_NAME", "rankTest"),
}
