<h1 align="center">Arabian Servers — CS 1.6 Discord Bot</h1>

<p align="center">
  A Discord bot that surfaces live player statistics and leaderboards for the
  <b>Arabian Counter-Strike 1.6</b> community, serving stats directly from the
  game's MySQL rank database.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="discord.py" src="https://img.shields.io/badge/discord.py-2.4-5865F2?logo=discord&logoColor=white">
  <img alt="MySQL" src="https://img.shields.io/badge/MySQL-aiomysql-4479A1?logo=mysql&logoColor=white">
  <img alt="Async" src="https://img.shields.io/badge/I%2FO-fully%20async-success">
</p>

---

## Overview

Arabian Servers has run Counter-Strike 1.6 servers since 2013. This bot gives
the community instant access to their stats inside Discord — ranks, K/D,
weapon breakdowns, head-to-head comparisons and server-wide leaderboards —
through modern Discord **slash commands**.

Player data is read straight from the live rank database (`rank_system` and
`weapon_kills`), so stats are always current with no scraping, caching layer,
or manual updates.

## Features

- **8 slash commands** covering individual stats, weapon analytics, player
  comparisons and global server metrics.
- **Fully asynchronous I/O** — database access runs on an `aiomysql`
  connection pool and game-server queries use async A2S, so the event loop is
  never blocked under load.
- **Paginated leaderboards** via interactive Discord button components, with
  page-aware navigation controls.
- **Fuzzy player resolution** — partial names resolve to a single player when
  unambiguous, or prompt the user to disambiguate.
- **Live game-server integration** — real-time player counts pulled directly
  from the CS 1.6 server over the A2S protocol.
- **Modular cog architecture** with centralized error logging to a Discord
  channel.
- **Secrets-free codebase** — all configuration (tokens, DB credentials) is
  loaded from the environment.

## Commands

| Command | Description |
| --- | --- |
| `/rankstats <player>` | Detailed stats card: rank, K/D, headshots, accuracy, C4, top weapons, playtime |
| `/top [page]` | Paginated XP leaderboard with interactive navigation |
| `/online` | Players currently connected to the server |
| `/weaponstats <player>` | Per-weapon kill and headshot breakdown |
| `/compare <p1> <p2>` | Side-by-side head-to-head comparison |
| `/topweapon <weapon>` | Top killers with a specific weapon (with autocomplete) |
| `/serverstats` | Aggregate metrics across all registered players |
| `/ip` | Server address and live player count |

## Tech Stack

- **Python 3.12**
- **[discord.py](https://discordpy.readthedocs.io/) 2.4** — slash commands, UI components, cogs
- **[aiomysql](https://aiomysql.readthedocs.io/)** — asynchronous MySQL access with connection pooling
- **[python-a2s](https://github.com/Yepoleb/python-a2s)** — Source/GoldSrc server queries
- **[python-dotenv](https://github.com/theskumar/python-dotenv)** — environment-based configuration

## Architecture

```
bot.py                 # Entry point — lifecycle, cog loading, command sync
├── cogs/
│   ├── cs.py           # Stats, leaderboards & server commands
│   ├── events.py       # Centralized command-error logging
│   └── moderation.py   # Moderation utilities
└── utils/
    ├── constants.py    # Environment-driven configuration
    ├── database.py     # Async data-access layer (aiomysql pool)
    └── utils.py        # Shared helpers
```

The bot opens its database pool and loads all cogs in `setup_hook`, then closes
the pool gracefully on shutdown. The data-access layer (`utils/database.py`)
fully encapsulates SQL, exposing intent-revealing methods (`get_player_info`,
`get_top_players`, `get_weapon_breakdown`, …) to the command layer.

## Getting Started

**Prerequisites:** Python 3.12+, a MySQL database containing the `rank_system`
and `weapon_kills` tables, and a Discord bot token.

```bash
# 1. Install dependencies (a virtual environment is recommended)
pip install -r requirements.txt

# 2. Configure your environment
cp .env.example .env
#    then edit .env with your Discord token and MySQL credentials

# 3. Run the bot
python bot.py
```

### Configuration

All settings are provided through environment variables (see `.env.example`):

| Variable | Description |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token |
| `LOGGING_CHANNEL_ID` | Channel ID for error logs |
| `SERVER_IP` / `SERVER_PORT` | CS 1.6 game server address (for live player count) |
| `DB_HOST` / `DB_PORT` | MySQL host and port |
| `DB_USER` / `DB_PASSWORD` | MySQL credentials |
| `DB_NAME` | Rank database name |
