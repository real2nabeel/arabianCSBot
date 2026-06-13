"""Async MySQL data access layer for the Arabian CS 1.6 rank database.

Replaces the old web-scraping layer (``player_stats.py``). All queries run
against the ``rank_system`` and ``weapon_kills`` tables through an aiomysql
connection pool so the Discord event loop is never blocked.
"""

import aiomysql

from utils.constants import DB_CONFIG

# Weapon "kill" columns in the weapon_kills table (the headshot columns are
# these same names suffixed with " HS").
WEAPON_COLUMNS = [
    "Knife", "Glock18", "USP", "P228", "Deagle", "Fiveseven", "Elite",
    "M3", "XM1014", "TMP", "MAC10", "MP5 Navy", "UMP45", "P90", "M249",
    "Galil", "Famas", "AK47", "M4A1", "SG552", "AUG", "Scout", "AWP",
    "G3SG1", "SG550", "HE Grenade",
]

# Case-insensitive lookup so users can type "ak47" / "awp" etc.
WEAPON_LOOKUP = {w.lower(): w for w in WEAPON_COLUMNS}

TOP_PAGE_SIZE = 15


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

    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await aiomysql.create_pool(
            autocommit=True,
            minsize=1,
            maxsize=5,
            charset="utf8mb4",
            **DB_CONFIG,
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

        placement = await self.fetch_one(
            "SELECT COUNT(*) + 1 AS pos FROM rank_system WHERE `XP` > %s",
            (p["XP"] or 0,),
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
            "SELECT `Nick`, `XP`, `Kills`, `Headshots`, `Skill`, `Skill Range` "
            "FROM rank_system ORDER BY `XP` DESC LIMIT %s OFFSET %s",
            (per_page, offset),
        )

        players = []
        for i, row in enumerate(rows):
            skill = (row["Skill"] or "").strip()
            skill_range = row["Skill Range"]
            skill_display = f"{skill} {skill_range}".strip() if skill else str(skill_range or "")
            players.append({
                "Rank": offset + i + 1,
                "XP": row["XP"] or 0,
                "Name": row["Nick"] or "Unknown",
                "Kills": row["Kills"] or 0,
                "Headshots": row["Headshots"] or 0,
                "Headshot Percentages": f"{hs_percentage(row['Headshots'], row['Kills'])}%",
                "Skills": skill_display,
            })

        return players, total

    # ------------------------------------------------------------------ #
    # Online players (/online)
    # ------------------------------------------------------------------ #
    async def get_online_players(self):
        return await self.fetch_all(
            "SELECT `Nick`, `Rank Name`, `XP`, `Kills`, `Deaths` "
            "FROM rank_system WHERE `Online` = 1 ORDER BY `XP` DESC"
        )

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

        weapons = []
        for weapon in WEAPON_COLUMNS:
            kills = row.get(weapon) or 0
            hs = row.get(f"{weapon} HS") or 0
            if kills:
                weapons.append({"weapon": weapon, "kills": kills, "hs": hs})
        weapons.sort(key=lambda w: w["kills"], reverse=True)
        return {"Name": nick, "weapons": weapons}, 0

    # ------------------------------------------------------------------ #
    # Top killers with a specific weapon (/topweapon)
    # ------------------------------------------------------------------ #
    async def get_top_weapon(self, weapon, limit=TOP_PAGE_SIZE):
        # weapon is validated against WEAPON_COLUMNS by the caller, so it is
        # safe to interpolate as a backticked column name.
        rows = await self.fetch_all(
            f"SELECT `Nick`, `{weapon}` AS kills FROM weapon_kills "
            f"WHERE `{weapon}` > 0 ORDER BY `{weapon}` DESC LIMIT %s",
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
