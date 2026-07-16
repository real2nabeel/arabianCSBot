<h1 align="center">Arabian Servers CS 1.6 Discord Bot</h1>

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
the community instant access to their stats inside Discord. This includes ranks, K/D,
weapon breakdowns, comparisons between players and leaderboards
through Discord **slash commands**.

## Features

- **slash commands** covering individual stats, weapon analytics, player
  comparisons and global server metrics.
- **Fully asynchronous I/O** database access runs on an `aiomysql`
  connection pool and game-server queries use async A2S, so the event loop is
  never blocked under load.
- **Paginated leaderboards** via interactive Discord button components, with
  page-aware navigation controls.
- **Fuzzy player resolution** partial names resolve to a single player when
  unambiguous, or prompt the user to disambiguate.
- **Live game-server integration** real-time player counts pulled directly
  from the CS 1.6 server over the A2S protocol.
- **Modular cog architecture** with centralized error logging to a Discord
  channel.

## Commands

Every ranking command comes in two flavours: the plain command reads the
**live** ranking, and the `-history` variant reads the
**historical** ranking.

| Command | Description |
| --- | --- |
| `/rankstats <player>` · `/rankstats-history <player>` | Detailed stats card: rank, K/D, headshots, accuracy, C4, top weapons, playtime |
| `/top [page]` · `/top-history [page]` | Paginated XP leaderboard with interactive navigation |
| `/online` | Players currently in the match live from the game server (name, current-match frags, time connected) |
| `/weaponstats <player>` · `/weaponstats-history <player>` | Per-weapon kill and headshot breakdown |
| `/compare <p1> <p2>` · `/compare-history <p1> <p2>` | Side-by-side head-to-head comparison |
| `/topweapon <weapon>` · `/topweapon-history <weapon>` | Top killers with a specific weapon (with autocomplete) |
| `/serverstats` · `/serverstats-history` | Aggregate metrics across all registered players |
| `/ip` | Server address and live player count |

## Tech Stack

- **Python 3.12**
- **[discord.py](https://discordpy.readthedocs.io/) 2.4** slash commands, UI components, cogs
- **[aiomysql](https://aiomysql.readthedocs.io/)** asynchronous MySQL access with connection pooling
- **[python-a2s](https://github.com/Yepoleb/python-a2s)** Source/GoldSrc server queries
- **[python-dotenv](https://github.com/theskumar/python-dotenv)** environment-based configuration

## Architecture

```
bot.py                 # Entry point lifecycle, cog loading, command sync
├── cogs/
│   ├── cs.py           # Stats, leaderboards & server commands
│   ├── events.py       # Centralized command-error logging
│   └── moderation.py   # Moderation utilities
├── utils/
│   ├── constants.py    # Environment-driven configuration
│   ├── database.py     # Async data-access layer (aiomysql pool)
│   └── utils.py        # Shared helpers
└── legacy/
    └── scraper.py      # Original v1 web-scraping data source (inactive)
```

The bot opens its database pool and loads all cogs in `setup_hook`, then closes
the pool gracefully on shutdown. The data-access layer (`utils/database.py`)
fully encapsulates SQL, exposing intent-revealing methods (`get_player_info`,
`get_top_players`, `get_weapon_breakdown`, …) to the command layer.

## Data Sources

The bot is designed around two independent ways of reading player statistics:

- **MySQL rank database (primary).** Stats are read directly from the game's through a fully asynchronous,
  connection-pooled data layer (`utils/database.py`). Because it talks to the
  database directly, it exposes the complete dataset and powers the richer
  commands such as `/weaponstats`, `/compare`, and `/serverstats`.

- **Web scraping ([`legacy/scraper.py`](legacy/scraper.py)).** A
  `requests` + `BeautifulSoup` module that parses player stats from the public
  rank webpage. It serves as an alternative source useful when only the public
  page is reachable and demonstrates HTML parsing and resilient data
  extraction. Enabling it requires the optional dependencies noted in
  `requirements.txt`.

Keeping the data access behind a clear interface lets the bot stay decoupled
from any single source.

## Getting Started

**Prerequisites:** Python 3.12+, a MySQL database containing the player data, and a Discord bot token.

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
