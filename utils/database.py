"""Async MySQL data access layer for the Arabian CS 1.6 rank database.

All queries run against the ``rank_system`` and ``weapon_kills`` tables through
an aiomysql connection pool so the Discord event loop is never blocked.
"""

import difflib
import re

import aiomysql

from utils.constants import DB_CONFIG_LIVE
from utils.leveling import level_from_xp

# Weapon "kill" columns in the weapon_kills table. In the history schema
# (rankTest) each weapon also has a headshot column of the same name suffixed
# with " HS"; the live schema (liverank) has no headshot columns at all.
WEAPON_COLUMNS = [
    "Knife", "Glock18", "USP", "P228", "Deagle", "Fiveseven", "Elite",
    "M3", "XM1014", "TMP", "MAC10", "MP5 Navy", "UMP45", "P90", "M249",
    "Galil", "Famas", "AK47", "M4A1", "SG552", "AUG", "Scout", "AWP",
    "G3SG1", "SG550", "HE Grenade",
]

# Case-insensitive lookup so users can type "ak47" / "awp" etc.
WEAPON_LOOKUP = {w.lower(): w for w in WEAPON_COLUMNS}

TOP_PAGE_SIZE = 15

# Player search tuning. SEARCH_LIMIT also caps the autocomplete list (Discord
# allows at most 25 choices), SUGGESTION_LIMIT the "did you mean" embed.
SEARCH_LIMIT = 25
SUGGESTION_LIMIT = 10

# A fuzzy candidate is accepted outright only when it is both a strong match
# and clearly better than the runner-up, so a typo resolves but a genuinely
# ambiguous query still asks.
FUZZY_ACCEPT = 0.8
FUZZY_ACCEPT_GAP = 0.1
FUZZY_LONE_ACCEPT = 0.6
FUZZY_SUGGEST = 0.4

# LIKE wildcards in user input must be escaped or a "%" matches every player.
# Backslash is MySQL's default LIKE escape character.
_LIKE_ESCAPES = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


def escape_like(text):
    r"""Escape LIKE wildcards so `%`, `_` and `\` are matched literally."""
    return (text or "").translate(_LIKE_ESCAPES)


def normalize_nick(text):
    r"""Fold a nickname to its bare letters/digits, lowercased.

    Player nicks are full of clan tags and decoration (``[AR]*Nabeel*``,
    ``n a b e e l``); normalizing both sides lets someone type just the name.
    ``\W`` is Unicode-aware, so Arabic nicks survive this untouched.
    """
    return re.sub(r"[\W_]+", "", (text or "").lower(), flags=re.UNICODE)


def nick_tokens(text):
    """The normalized words of a nick: ``"[AR]*Nabeel*"`` -> ``["ar", "nabeel"]``.

    Matching per token is what lets someone type the bare name of a player who
    wears a clan tag, without that losing to a longer nick that merely starts
    with the same letters.
    """
    return [t for t in re.split(r"[\W_]+", (text or "").lower(), flags=re.UNICODE) if t]


def subsequence_pattern(text):
    """LIKE pattern matching nicks containing these characters *in order*.

    Used only after a plain substring search finds nothing: it is a cheap,
    typo-tolerant last resort ("nbeel" -> ``%n%b%e%e%l%``).
    """
    chars = [escape_like(c) for c in (text or "") if not c.isspace()]
    return "%" + "%".join(chars) + "%" if chars else "%"


def similarity(query, nick):
    """0..1 closeness of a nick to a search string, compared on normalized
    forms so decoration doesn't count against the match."""
    q, n = normalize_nick(query), normalize_nick(nick)
    if not q or not n:
        return 0.0
    score = difflib.SequenceMatcher(None, q, n).ratio()
    if n.startswith(q):
        score = max(score, 0.85)
    elif q in n:
        score = max(score, 0.75)
    return score


def rank_by_similarity(name, rows):
    """Sort candidate rows by closeness to ``name`` (XP breaks ties).

    Returns a list of ``(score, row)``, best first.
    """
    scored = [(similarity(name, row["Nick"]), row) for row in rows]
    scored.sort(key=lambda item: (-item[0], -(item[1].get("XP") or 0)))
    return scored


# Leaderboard ranking criteria, most significant first. Each entry is
# (sql_expression, python_value_getter, "better"_operator). All numeric keys
# rank higher-is-better (">"); the final Nick tiebreak is alphabetical ("<")
# to make the ordering fully deterministic.
RANK_KEYS = [
    ("(COALESCE(`Kills`, 0) - COALESCE(`Deaths`, 0))",
     lambda p: (p["Kills"] or 0) - (p["Deaths"] or 0), ">"),   # frag difference
    ("COALESCE(`Assists`, 0)", lambda p: p["Assists"] or 0, ">"),
    ("COALESCE(`Headshots`, 0)", lambda p: p["Headshots"] or 0, ">"),
    ("COALESCE(`MVP`, 0)", lambda p: p["MVP"] or 0, ">"),
    ("COALESCE(`Rounds Won`, 0)", lambda p: p["Rounds Won"] or 0, ">"),
    ("COALESCE(`Planted`, 0)", lambda p: p["Planted"] or 0, ">"),
    ("COALESCE(`Exploded`, 0)", lambda p: p["Exploded"] or 0, ">"),
    ("COALESCE(`Defused`, 0)", lambda p: p["Defused"] or 0, ">"),
    ("COALESCE(`XP`, 0)", lambda p: p["XP"] or 0, ">"),
    ("`Nick`", lambda p: p["Nick"], "<"),
]

# ORDER BY clause matching RANK_KEYS (">" -> DESC, "<" -> ASC).
LEADERBOARD_ORDER = ", ".join(
    f"{expr} {'DESC' if op == '>' else 'ASC'}" for expr, _, op in RANK_KEYS
)


def _placement_where(player):
    """Build a WHERE clause (and params) matching every player ranked strictly
    above ``player`` under RANK_KEYS, so COUNT(*) + 1 yields their position."""
    values = [getter(player) for _, getter, _ in RANK_KEYS]
    terms, params = [], []
    for i, (expr, _, op) in enumerate(RANK_KEYS):
        conditions = []
        for j in range(i):  # tie on every more-significant key
            conditions.append(f"{RANK_KEYS[j][0]} = %s")
            params.append(values[j])
        conditions.append(f"{expr} {op} %s")  # and beat this one
        params.append(values[i])
        terms.append("(" + " AND ".join(conditions) + ")")
    return " OR ".join(terms), params


def format_played_time(seconds):
    """Format a played-time value (stored in seconds) as ``Dd Hh Mm``."""
    if not seconds:
        return "0h 0m"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def kd_ratio(kills, deaths):
    kills = kills or 0
    deaths = deaths or 0
    if deaths == 0:
        return float(kills)
    return round(kills / deaths, 2)


def hs_percentage(headshots, kills):
    headshots = headshots or 0
    kills = kills or 0
    if kills == 0:
        return 0.0
    return round(headshots / kills * 100, 1)


class Database:
    """Thin async wrapper around an aiomysql connection pool."""

    def __init__(self, config=None):
        # Each instance targets one schema (live or historical). Defaults to
        # the live config so existing single-DB callers keep working.
        self.config = config or DB_CONFIG_LIVE
        self.pool = None

    async def ensure_database_exists(self):
        """Create this instance's schema if it is missing.

        ``create_pool`` connects to a named database and fails if it does not
        exist, so this runs first (on a connection with no default db) to make
        first-time setup of the bot's own schema painless.
        """
        cfg = {k: v for k, v in self.config.items() if k != "db"}
        conn = await aiomysql.connect(autocommit=True, charset="utf8mb4", **cfg)
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.config['db']}` "
                    "CHARACTER SET utf8mb4"
                )
        finally:
            conn.close()

    async def connect(self):
        self.pool = await aiomysql.create_pool(
            autocommit=True,
            minsize=1,
            maxsize=5,
            charset="utf8mb4",
            **self.config,
        )

    async def ensure_server_monitor_schema(self):
        await self.execute(
            "CREATE TABLE IF NOT EXISTS server_monitor ("
            "guild_id BIGINT UNSIGNED NOT NULL, server_key VARCHAR(255) NOT NULL, "
            "dashboard_id BIGINT UNSIGNED NULL, panel_id BIGINT UNSIGNED NULL, "
            "armed BOOLEAN NOT NULL DEFAULT 1, last_alert DOUBLE NOT NULL DEFAULT 0, "
            "PRIMARY KEY (guild_id, server_key)) CHARACTER SET utf8mb4"
        )

    async def get_server_monitor(self, guild_id, server_key):
        await self.execute(
            "INSERT IGNORE INTO server_monitor (guild_id, server_key) VALUES (%s, %s)",
            (guild_id, server_key),
        )
        return await self.fetch_one(
            "SELECT * FROM server_monitor WHERE guild_id=%s AND server_key=%s",
            (guild_id, server_key),
        )

    async def set_monitor_message(self, guild_id, server_key, field, message_id):
        if field not in {"dashboard_id", "panel_id"}:
            raise ValueError("Invalid monitor message field")
        await self.execute(
            f"UPDATE server_monitor SET {field}=%s WHERE guild_id=%s AND server_key=%s",
            (message_id, guild_id, server_key),
        )

    async def rearm_server_alert(self, guild_id, server_key):
        await self.execute(
            "UPDATE server_monitor SET armed=1 WHERE guild_id=%s AND server_key=%s",
            (guild_id, server_key),
        )

    async def claim_server_alert(self, guild_id, server_key, now, cooldown):
        # Reserve before sending so a restart/uncertain Discord response cannot
        # produce a second ping. A failed send may consume this alert cycle.
        return await self.execute(
            "UPDATE server_monitor SET armed=0, last_alert=%s "
            "WHERE guild_id=%s AND server_key=%s AND armed=1 "
            "AND (last_alert=0 OR last_alert<=%s)",
            (now, guild_id, server_key, now - cooldown),
        ) == 1

    async def close(self):
        if self.pool is not None:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None

    async def fetch_all(self, query, args=None):
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, args)
                return await cur.fetchall()

    async def fetch_one(self, query, args=None):
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, args)
                return await cur.fetchone()

    async def execute(self, query, args=None):
        """Run a write/DDL statement and return the affected row count."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, args)
                return cur.rowcount

    # ------------------------------------------------------------------ #
    # Player resolution
    # ------------------------------------------------------------------ #
    async def _search_rows(self, name, limit=SEARCH_LIMIT):
        """Candidate rows for ``name``, best match first.

        Returns ``(rows, fuzzy)``. The first pass is a substring search ordered
        by match quality (exact nick, then prefix, then anywhere) and XP, so the
        row the user meant is never pushed off the end of the LIMIT by a more
        active player who merely contains the string. Only when that finds
        nothing do we fall back to the typo-tolerant subsequence scan, flagged
        by ``fuzzy`` so the caller scores those results before trusting them.
        """
        pattern = escape_like(name)
        rows = await self.fetch_all(
            "SELECT `Player`, `Nick`, COALESCE(`XP`, 0) AS `XP`, "
            "  CASE WHEN `Nick` = %s THEN 0 "
            "       WHEN `Nick` LIKE %s THEN 1 "
            "       ELSE 2 END AS `match_rank` "
            "FROM rank_system WHERE `Nick` LIKE %s "
            "ORDER BY `match_rank` ASC, `XP` DESC LIMIT %s",
            (name, f"{pattern}%", f"%{pattern}%", limit),
        )
        if rows:
            return rows, False

        rows = await self.fetch_all(
            "SELECT `Player`, `Nick`, COALESCE(`XP`, 0) AS `XP` "
            "FROM rank_system WHERE `Nick` LIKE %s ORDER BY `XP` DESC LIMIT %s",
            (subsequence_pattern(name), limit * 2),
        )
        return rows, True

    async def resolve_player(self, name):
        """Resolve a search string to a single player.

        Matching is deliberately forgiving — partial names, any casing, missing
        clan tags or decoration, and small typos all resolve — because players
        are picked out of chat by nickname, not copied character-for-character.

        Returns ``(player_key, nick, mode)`` where mode is:
          * ``0``  -> unambiguous match (player_key + nick set)
          * ``1``  -> ambiguous; ``nick`` is a list of candidate nicknames
          * ``-1`` -> no match at all
        """
        name = (name or "").strip()
        if not name:
            return None, None, -1

        rows, fuzzy = await self._search_rows(name)
        if not rows:
            return None, None, -1

        if not fuzzy:
            # Rows are ordered best-match-then-XP, so the first hit of each pass
            # is the most active player that qualifies. Several players really
            # can share a nick, so an exact match resolves to the top-ranked one
            # instead of being ambiguous forever.
            for candidates in (
                [r for r in rows if (r["Nick"] or "").lower() == name.lower()],
                [r for r in rows if normalize_nick(r["Nick"]) == normalize_nick(name)],
            ):
                if candidates:
                    return candidates[0]["Player"], candidates[0]["Nick"], 0

            if len(rows) == 1:
                return rows[0]["Player"], rows[0]["Nick"], 0

            # Then one word of the nick, whole or as a prefix — but only when a
            # single player qualifies, otherwise the query is genuinely between
            # two players and they should get to choose.
            query = normalize_nick(name)
            for match in (lambda token: token == query, lambda token: token.startswith(query)):
                narrowed = [r for r in rows if any(map(match, nick_tokens(r["Nick"])))]
                if len(narrowed) == 1:
                    return narrowed[0]["Player"], narrowed[0]["Nick"], 0

            return None, [r["Nick"] for r in rows[:SUGGESTION_LIMIT]], 1

        # Fuzzy fallback: nothing contained the string, so only accept a
        # candidate that stands clearly apart from the rest.
        scored = rank_by_similarity(name, rows)
        best_score, best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if best_score >= FUZZY_ACCEPT and best_score - runner_up >= FUZZY_ACCEPT_GAP:
            return best["Player"], best["Nick"], 0

        close = [(score, row) for score, row in scored[:SUGGESTION_LIMIT]
                 if score >= FUZZY_SUGGEST]
        if not close:
            return None, None, -1
        if len(close) == 1 and close[0][0] >= FUZZY_LONE_ACCEPT:
            return close[0][1]["Player"], close[0][1]["Nick"], 0
        return None, [row["Nick"] for _, row in close], 1

    async def search_players(self, query, limit=SEARCH_LIMIT):
        """Nickname suggestions for slash-command autocomplete, best first.

        An empty query offers the leaderboard's top players so the dropdown is
        never blank before the user types.
        """
        query = (query or "").strip()
        if not query:
            rows = await self.fetch_all(
                "SELECT `Nick` FROM rank_system "
                "WHERE `Nick` IS NOT NULL AND `Nick` <> '' "
                f"ORDER BY {LEADERBOARD_ORDER} LIMIT %s",
                (limit,),
            )
        else:
            rows, fuzzy = await self._search_rows(query, limit)
            if fuzzy:
                rows = [row for score, row in rank_by_similarity(query, rows)
                        if score >= FUZZY_SUGGEST]

        # Distinct nicks only: players sharing a nick would render as identical
        # (and unpickable) duplicate choices.
        seen, names = set(), []
        for row in rows:
            nick = (row["Nick"] or "").strip()
            if nick and nick.lower() not in seen:
                seen.add(nick.lower())
                names.append(nick)
        return names[:limit]

    # ------------------------------------------------------------------ #
    # Player stats (/rankstats)
    # ------------------------------------------------------------------ #
    async def get_player_info(self, name):
        """Return ``(data, mode)`` mirroring the old scraping interface."""
        player_key, nick, mode = await self.resolve_player(name)
        if mode == -1:
            return None, -1
        if mode == 1:
            return nick, 1

        p = await self.fetch_one(
            "SELECT * FROM rank_system WHERE `Player` = %s LIMIT 1",
            (player_key,),
        )
        if not p:
            return None, -1

        where, params = _placement_where(p)
        placement = await self.fetch_one(
            f"SELECT COUNT(*) + 1 AS pos FROM rank_system WHERE {where}",
            params,
        )
        pos = placement["pos"] if placement else "?"

        top_weapons = await self.get_top_weapons(player_key, limit=5)

        return {
            "Name": p["Nick"],
            "Rank": p["Rank Name"],
            "Rank Placement": f"#{pos}",
            "XP": p["XP"] or 0,
            "Level": p["Level"] or 0,
            "K/D Ratio": kd_ratio(p["Kills"], p["Deaths"]),
            "Kills": p["Kills"] or 0,
            "Deaths": p["Deaths"] or 0,
            "Assists": p["Assists"] or 0,
            "Headshots": p["Headshots"] or 0,
            "Headshot %": hs_percentage(p["Headshots"], p["Kills"]),
            "Shots": p["Shots"] or 0,
            "Hits": p["Hits"] or 0,
            "Damage": p["Damage"] or 0,
            "C4 Planted": p["Planted"] or 0,
            "C4 Exploded": p["Exploded"] or 0,
            "C4 Defused": p["Defused"] or 0,
            "Most Valuable Player": p["MVP"] or 0,
            "Rounds Won": p["Rounds Won"] or 0,
            "Top Weapons": top_weapons,
            "Played Time": format_played_time(p["Played Time"]),
            "First Login": p["First Login"] or "N/A",
            "Last Login": p["Last Login"] or "N/A",
            "Skill": p["Skill"],
            "Online": bool(p["Online"]),
            "Avatar": p.get("Avatar") or None,
            "Profile": p.get("Profile") or None,
        }, 0

    async def get_top_weapons(self, player_key, limit=5):
        row = await self.fetch_one(
            "SELECT * FROM weapon_kills WHERE `Player` = %s LIMIT 1",
            (player_key,),
        )
        if not row:
            return []
        kills = {w: row[w] for w in WEAPON_COLUMNS if row.get(w)}
        top = sorted(kills.items(), key=lambda item: item[1], reverse=True)[:limit]
        return [{weapon: count} for weapon, count in top]

    # ------------------------------------------------------------------ #
    # Leaderboard (/top)
    # ------------------------------------------------------------------ #
    async def get_top_players(self, page=1, per_page=TOP_PAGE_SIZE):
        page = max(1, page)
        offset = (page - 1) * per_page

        total_row = await self.fetch_one("SELECT COUNT(*) AS c FROM rank_system")
        total = total_row["c"] if total_row else 0

        rows = await self.fetch_all(
            "SELECT `Nick`, `Kills`, `Deaths`, `Headshots` "
            f"FROM rank_system ORDER BY {LEADERBOARD_ORDER} LIMIT %s OFFSET %s",
            (per_page, offset),
        )

        players = []
        for i, row in enumerate(rows):
            players.append({
                "Rank": offset + i + 1,
                "Name": row["Nick"] or "Unknown",
                "Kills": row["Kills"] or 0,
                "Deaths": row["Deaths"] or 0,
                "Headshots": row["Headshots"] or 0,
            })

        return players, total

    # ------------------------------------------------------------------ #
    # Weapon breakdown (/weaponstats)
    # ------------------------------------------------------------------ #
    async def get_weapon_breakdown(self, name):
        player_key, nick, mode = await self.resolve_player(name)
        if mode != 0:
            return nick, mode

        row = await self.fetch_one(
            "SELECT * FROM weapon_kills WHERE `Player` = %s LIMIT 1",
            (player_key,),
        )
        if not row:
            return None, -1

        # Live (liverank) weapon_kills has no "<Weapon> HS" columns at all; only
        # the history schema (rankTest) does. Detect their presence so callers
        # can hide the headshot columns when there is no data behind them.
        has_hs = any(f"{w} HS" in row for w in WEAPON_COLUMNS)

        weapons = []
        for weapon in WEAPON_COLUMNS:
            kills = row.get(weapon) or 0
            hs = row.get(f"{weapon} HS") or 0
            if kills:
                weapons.append({"weapon": weapon, "kills": kills, "hs": hs})
        weapons.sort(key=lambda w: w["kills"], reverse=True)
        return {"Name": nick, "weapons": weapons, "has_hs": has_hs}, 0

    # ------------------------------------------------------------------ #
    # Top killers with a specific weapon (/topweapon)
    # ------------------------------------------------------------------ #
    async def get_top_weapon(self, weapon, limit=TOP_PAGE_SIZE):
        # weapon is validated against WEAPON_COLUMNS by the caller, so it is
        # safe to interpolate as a backticked column name.
        #
        # The Nick is pulled from rank_system rather than weapon_kills: the live
        # (liverank) weapon_kills table has no Nick column, so we join on Player
        # to get it. This works against both schemas.
        rows = await self.fetch_all(
            f"SELECT r.`Nick` AS `Nick`, w.`{weapon}` AS kills "
            f"FROM weapon_kills w "
            f"JOIN rank_system r ON r.`Player` = w.`Player` "
            f"WHERE w.`{weapon}` > 0 ORDER BY w.`{weapon}` DESC LIMIT %s",
            (limit,),
        )
        return rows

    # ------------------------------------------------------------------ #
    # Server-wide aggregates (/serverstats)
    # ------------------------------------------------------------------ #
    async def get_server_stats(self):
        return await self.fetch_one(
            "SELECT "
            "  COUNT(*) AS total_players, "
            "  COALESCE(SUM(`Kills`), 0) AS kills, "
            "  COALESCE(SUM(`Deaths`), 0) AS deaths, "
            "  COALESCE(SUM(`Headshots`), 0) AS headshots, "
            "  COALESCE(SUM(`Played Time`), 0) AS playtime, "
            "  COALESCE(SUM(`Planted`), 0) AS planted, "
            "  COALESCE(SUM(`Defused`), 0) AS defused, "
            "  COALESCE(SUM(`Online`), 0) AS online "
            "FROM rank_system"
        )

    # ------------------------------------------------------------------ #
    # Discord activity leveling (separate from the in-game rank system).
    #
    # These methods run against the bot's own schema (DB_CONFIG_BOT), not the
    # game ranking schemas. They power the /level, /xptop, /levelrole and admin
    # XP commands in cogs/leveling.py.
    # ------------------------------------------------------------------ #
    XP_PAGE_SIZE = TOP_PAGE_SIZE

    async def ensure_leveling_schema(self):
        """Create the leveling tables if they do not exist. Safe to call on
        every startup."""
        await self.execute(
            "CREATE TABLE IF NOT EXISTS discord_xp ("
            "  guild_id BIGINT UNSIGNED NOT NULL,"
            "  user_id BIGINT UNSIGNED NOT NULL,"
            "  xp BIGINT UNSIGNED NOT NULL DEFAULT 0,"
            "  level INT UNSIGNED NOT NULL DEFAULT 0,"
            "  messages BIGINT UNSIGNED NOT NULL DEFAULT 0,"
            "  voice_seconds BIGINT UNSIGNED NOT NULL DEFAULT 0,"
            "  last_award DATETIME NULL,"
            "  PRIMARY KEY (guild_id, user_id),"
            "  KEY idx_guild_xp (guild_id, xp)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        await self.execute(
            "CREATE TABLE IF NOT EXISTS level_roles ("
            "  guild_id BIGINT UNSIGNED NOT NULL,"
            "  level INT UNSIGNED NOT NULL,"
            "  role_id BIGINT UNSIGNED NOT NULL,"
            "  PRIMARY KEY (guild_id, level)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )

    async def add_xp(self, guild_id, user_id, amount, *,
                     messages=0, voice_seconds=0, touch_award=False):
        """Add ``amount`` XP (and optional message/voice counters) to a member.

        Returns ``(old_level, new_level)`` so the caller can detect a level-up.
        ``touch_award`` updates ``last_award`` (used for the text cooldown).
        """
        row = await self.fetch_one(
            "SELECT xp FROM discord_xp WHERE guild_id = %s AND user_id = %s",
            (guild_id, user_id),
        )
        old_xp = row["xp"] if row else 0
        new_xp = old_xp + amount
        old_level = level_from_xp(old_xp)
        new_level = level_from_xp(new_xp)
        award = ", last_award = UTC_TIMESTAMP()" if touch_award else ""
        await self.execute(
            "INSERT INTO discord_xp "
            "  (guild_id, user_id, xp, level, messages, voice_seconds, last_award) "
            f"VALUES (%s, %s, %s, %s, %s, %s, {'UTC_TIMESTAMP()' if touch_award else 'NULL'}) "
            "ON DUPLICATE KEY UPDATE "
            "  xp = xp + VALUES(xp), level = %s, "
            "  messages = messages + VALUES(messages), "
            f"  voice_seconds = voice_seconds + VALUES(voice_seconds){award}",
            (guild_id, user_id, amount, new_level, messages, voice_seconds, new_level),
        )
        return old_level, new_level

    async def get_member_xp(self, guild_id, user_id):
        return await self.fetch_one(
            "SELECT xp, level, messages, voice_seconds FROM discord_xp "
            "WHERE guild_id = %s AND user_id = %s",
            (guild_id, user_id),
        )

    async def get_xp_position(self, guild_id, xp):
        """1-based leaderboard position for a given XP total."""
        row = await self.fetch_one(
            "SELECT COUNT(*) + 1 AS pos FROM discord_xp "
            "WHERE guild_id = %s AND xp > %s",
            (guild_id, xp),
        )
        return row["pos"] if row else 1

    async def get_xp_total_members(self, guild_id):
        row = await self.fetch_one(
            "SELECT COUNT(*) AS c FROM discord_xp WHERE guild_id = %s AND xp > 0",
            (guild_id,),
        )
        return row["c"] if row else 0

    async def get_top_xp(self, guild_id, page=1, per_page=None):
        per_page = per_page or self.XP_PAGE_SIZE
        page = max(1, page)
        offset = (page - 1) * per_page
        total = await self.get_xp_total_members(guild_id)
        rows = await self.fetch_all(
            "SELECT user_id, xp, level, messages, voice_seconds FROM discord_xp "
            "WHERE guild_id = %s AND xp > 0 "
            "ORDER BY xp DESC, user_id ASC LIMIT %s OFFSET %s",
            (guild_id, per_page, offset),
        )
        return rows, total

    async def set_member_xp(self, guild_id, user_id, xp):
        """Set a member's XP to an absolute value (admin override)."""
        xp = max(0, int(xp))
        level = level_from_xp(xp)
        await self.execute(
            "INSERT INTO discord_xp (guild_id, user_id, xp, level) "
            "VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE xp = VALUES(xp), level = VALUES(level)",
            (guild_id, user_id, xp, level),
        )
        return level

    async def reset_member_xp(self, guild_id, user_id):
        """Remove a member's XP row entirely. Returns rows deleted."""
        return await self.execute(
            "DELETE FROM discord_xp WHERE guild_id = %s AND user_id = %s",
            (guild_id, user_id),
        )

    async def get_xp_audit(self, guild_id, limit=15):
        """Top members by XP with their message/voice counters, so an admin can
        eyeball farming before paying out the contest prize."""
        return await self.fetch_all(
            "SELECT user_id, xp, level, messages, voice_seconds FROM discord_xp "
            "WHERE guild_id = %s AND xp > 0 ORDER BY xp DESC LIMIT %s",
            (guild_id, limit),
        )

    # --- level <-> role configuration --------------------------------- #
    async def set_level_role(self, guild_id, level, role_id):
        await self.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) "
            "VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE role_id = VALUES(role_id)",
            (guild_id, level, role_id),
        )

    async def remove_level_role(self, guild_id, level):
        return await self.execute(
            "DELETE FROM level_roles WHERE guild_id = %s AND level = %s",
            (guild_id, level),
        )

    async def list_level_roles(self, guild_id):
        """All configured tiers for a guild, ordered by level ascending."""
        return await self.fetch_all(
            "SELECT level, role_id FROM level_roles WHERE guild_id = %s "
            "ORDER BY level ASC",
            (guild_id,),
        )
