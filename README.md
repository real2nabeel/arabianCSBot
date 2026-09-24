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
│   └── server_management.py # Event logs, welcomes, automatic roles
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

### Running with Docker

**Prerequisites:** Docker with Compose v2.

```bash
# 1. Configure your environment
cp .env.example .env
#    then edit .env — note DB_HOST must not be 127.0.0.1 inside a container:
#    use host.docker.internal for a MySQL on the host machine.

# 2. Build and start
docker compose up -d --build

# 3. Follow the logs
docker compose logs -f bot
```

Rebuild after code changes with `docker compose up -d --build`; stop with
`docker compose down`.

The compose file also ships an **optional MySQL service** for local
development, disabled by default:

```bash
docker compose --profile local-db up -d
```

With it running, set `DB_HOST=mysql` in `.env`. The bot's own schema
(`DB_NAME_BOT`) is created automatically on startup; the game ranking schemas
must be imported yourself, for example:

```bash
docker compose exec -T mysql mysql -uroot -p"$DB_PASSWORD" rankTest < ddls.sql
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

## Server management

### Live dashboard and activity alerts

Set `DASHBOARD_CHANNEL_ID` to a text channel for the live server card. The bot
creates one message, stores its ID in the bot database, and updates it every
60 seconds. It displays the DD2 server's map, total players/capacity, a console
connect command, and the community website. Failed queries show an unreachable state with no stale map or
player count. If the message is deleted, it creates a replacement. The bot pins
the card when it has Manage Messages; otherwise staff can pin it manually.

Members opt into the alert role through Discord's Channels & Roles menu. Set
`ACTIVITY_ALERT_ROLE_ID` and `ACTIVITY_ALERT_CHANNEL_ID` as before. The bot no
longer assigns subscription roles or posts buttons. On upgrade it deletes its
saved old subscription panel from the currently configured alert/dashboard
channels and clears the panel ID. If that panel lives in a previous channel,
staff must remove it manually. Keep the role out of `AUTO_ROLE_IDS`.

A second message in `DASHBOARD_CHANNEL_ID` shows the season's top 50 as one
Components V2 media card, with the title and timestamp only in the image: two columns
of 25, with the top three highlighted. There are no buttons
or pages. Members can open the image to enlarge it. Rankings come from the live
ranking database, following the existing ranking order. Every
`LEADERBOARD_REFRESH_SECONDS` (default 300), the bot checks the data and replaces
the attachment on that same message only when the displayed standings change.
It recovers the message ID after restarts and replaces a deleted message.
The timestamp records when the displayed standings were last rendered.

The bot creates a small `server_leaderboard` table automatically in `DB_NAME_BOT`
to save that message ID; it does not store ranking snapshots. Rendering runs in
a worker thread. Query/render/upload failures preserve the previous board and
are retried at the next interval. Docker installs Pillow, Arabic text shaping
dependencies, and DejaVu fonts; local Windows runs use Arial. The dashboard
channel additionally needs **Attach Files**. Existing `/top` pagination is unchanged.

The default alert conditions are:

- At least **15 reported humans** for **120 seconds** before an alert.
- After alerting, fewer than **4 humans** for **300 seconds** to re-arm.
- At least **7,200 seconds (2 hours)** between alerts.
- Bot counts are subtracted from the total reported by A2S_INFO. Missing or
  inconsistent counts are unknown and cannot qualify or re-arm an alert.
- Polls occur every **30 seconds**. Failed queries and long sampling gaps reset
  the continuous-condition timers. Conditions are checked at sample times.

The dashboard uses total occupancy, while alerts use humans only. These are
server-reported counts; plugins that spoof population can make them inaccurate.
No rules query or extra game plugin is needed.

Armed/disarmed state and the last alert time are persisted in `server_monitor`,
keyed by Discord guild and game-server address. On restart, the two-minute and
five-minute observation windows start fresh so downtime never counts as proof
of sustained population. The bot reserves an alert in the database before
sending it to avoid duplicate pings on restart. If sending fails or the process
crashes at that point, that cycle may be skipped and the cooldown still applies.
Run one bot instance. A crash between creating a dashboard/leaderboard message and
saving its ID can leave an orphan message that staff should remove manually.

The bot needs View Channel, Send Messages, Embed Links, and Read Message History
in the configured text channels. Manage Roles is no longer needed for activity
alerts (it is still needed for automatic member/level roles).
For a non-mentionable alert role, grant **Mention @everyone, @here, and All Roles**
to the bot in the alert channel only. Each alert explicitly permits mentions of
only the configured role. Alternatively, a mentionable role works, but other
members may then be able to ping it too. Dashboard/leaderboard messages never ping.

All thresholds and intervals are configurable in `.env.example`. Blank channel
IDs disable the corresponding feature. `GUILD_ID` is required and all configured
channels must belong to that guild. Deploy changes with:

```bash
docker compose up -d --build --force-recreate bot
```

### Event logs, welcomes, and automatic roles

The bot also provides server event logs, welcome messages, and automatic member
roles. Use Discord's built-in tools for moderation. Settings are read from `.env` on startup; copy the
server-management section from `.env.example` and restart the Python process after editing.
For Docker, recreate the container to load changed environment variables; a plain
`docker compose restart` retains the container's old environment. Deploy code
and configuration changes together with `docker compose up -d --build --force-recreate bot`.
No ProBot settings, messages, or XP are imported automatically.

| Setting | Purpose |
| --- | --- |
| `SERVER_LOG_CHANNEL_ID` | Private staff channel for server events; blank disables event logging |
| `MOD_LOG_CHANNEL_ID` | Optional separate channel for ban/unban events; blank uses the server log channel |
| `LOG_EXCLUDED_CHANNELS` | Comma-separated channel or category IDs to exclude from message logs, including child threads |
| `WELCOME_CHANNEL_ID` | Welcome channel; blank disables welcomes |
| `WELCOME_MESSAGE` | Text with `{mention}`, `{user}`, `{server}`, and `{count}` placeholders; maximum output is 2,000 characters |
| `AUTO_ROLE_IDS` | Comma-separated roles for new human members; blank disables assignment |

Server logs cover joins/leaves, nickname/member-role/timeout changes,
message edits/deletions/bulk deletions, bans/unbans, and channel/role creation,
updates, and deletion. Role-position-only changes are ignored. Member event logs
use named profile links so departed members remain readable. Log messages never ping members or roles. Both configured
log channels are excluded from message logging. Content of uncached deleted
messages, and the previous content of uncached edited messages, is unavailable;
the bot records the event IDs instead. Bulk deletions produce a count/ID summary.
These are live event logs, not a message archive or a replay of events missed
while the bot was offline. External changes do not guess the responsible staff
member. Ban/unban and timeout events are still logged when staff use Discord's
built-in moderation tools; the bot does not issue punishments or maintain cases.

Welcomes are plain text and can mention only the joining member. Automatic
roles skip bots, managed roles, `@everyone`, staff-capability roles, and roles at
or above the bot. Assignment waits for membership screening to finish. Roles
are assigned on join or a live screening-completion event, not retroactively
to existing members. A restart does not backfill joins/screening missed offline.

Enable **Server Members Intent** and **Message Content Intent** in the Discord
Developer Portal (the bot already requests both). Give the bot View Channel,
Send Messages, and Embed Links in log channels, plus View Channel and Send
Messages in the welcome channel. Automatic roles require Manage Roles with
the bot's highest role above each assigned role. Keep log channels
restricted to staff because they can contain deleted message content.

Before removing ProBot, configure these IDs and verify a welcome, screened
role assignment, and message edit/delete logging in your server. Avoid duplicate welcomes/roles by disabling those ProBot modules
when the replacements are enabled. Local tests do not validate live permissions.

Run offline tests with `.venv/Scripts/python.exe -m unittest discover -s tests`.

If message logs never appear, check `docker compose logs --tail=100 bot` after
recreating the container. Check that the bot can view the source channel and has
View Channel, Send Messages, and Embed Links permissions in the log channel.
Test using a human member's message in a normal channel the bot can view; the
log channels themselves are excluded. Setting names use plain underscores,
for example `SERVER_LOG_CHANNEL_ID`, without Markdown backslashes.

Message edit/delete logs show author mentions, channel mentions, and distinct
code blocks for message content (long content is marked as truncated). Edits
include a jump-to-message link; deletions link to the channel because the deleted
message is no longer accessible. Author avatars are shown when cached. Mentions
in logs do not send notifications.
