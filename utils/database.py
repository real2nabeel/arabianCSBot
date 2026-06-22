"""Async MySQL data access layer for the Arabian CS 1.6 rank database.

All queries run against the ``rank_system`` and ``weapon_kills`` tables through
an aiomysql connection pool so the Discord event loop is never blocked.
"""

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
    async def resolve_player(self, name):
        """Resolve a search string to a single player.

        Returns ``(player_key, nick, mode)`` where mode is:
          * ``0``  -> unambiguous match (player_key + nick set)
          * ``1``  -> ambiguous; ``nick`` is a list of candidate nicknames
          * ``-1`` -> no match at all
        """
        rows = await self.fetch_all(
            "SELECT `Player`, `Nick` FROM rank_system "
            "WHERE `Nick` LIKE %s ORDER BY `XP` DESC LIMIT 25",
            (f"%{name}%",),
        )
        if not rows:
            return None, None, -1

        if len(rows) == 1:
            return rows[0]["Player"], rows[0]["Nick"], 0

        exact = [r for r in rows if r["Nick"] == name]
        if len(exact) == 1:
            return exact[0]["Player"], exact[0]["Nick"], 0

        return None, [r["Nick"] for r in rows], 1

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
