"""Pure math for the Discord activity leveling system.

Kept separate from any Discord or database code so the curve can be reasoned
about and tested in isolation. The system is deliberately independent of the
in-game CS 1.6 rank/XP (see utils/database.py) — this is Discord-activity XP.

Levels are defined by an explicit XP threshold table (CS:GO rank tiers) rather
than a formula, so "level N" maps one-to-one onto the in-server rank roles:
level 1 == Silver I, ... level 18 == Global Elite. ``LEVEL_THRESHOLDS[n]`` is
the cumulative XP required to *reach* level ``n`` (level 0 == 0 XP == no rank).
Edit this list to retune the contest; everything else derives from it.
"""

# Cumulative XP to reach each level. Index == level.
#   0:  (no rank)        50:  Silver I            100: Silver II
#   250: Silver III      500: Silver IV           750: Silver Elite
#   1000: Silver Elite Master   1250: Gold Nova I      1500: Gold Nova II
#   2000: Gold Nova III  2500: Gold Nova Master   3000: Master Guardian
#   4000: Master Guardian II    5000: Master Guardian Elite
#   6000: Distinguished Master Guardian   8000: Legendary Eagle
#   10000: Legendary Eagle Master   12500: Supreme Master First Class
#   15000: Global Elite
LEVEL_THRESHOLDS = [
    0, 50, 100, 250, 500, 750, 1000, 1250, 1500, 2000, 2500,
    3000, 4000, 5000, 6000, 8000, 10000, 12500, 15000,
]

MAX_LEVEL = len(LEVEL_THRESHOLDS) - 1

# Canonical name for each level (CS:GO competitive ranks). Used by the
# /levelrole import command to auto-match roles of the same name. Keep this in
# sync with LEVEL_THRESHOLDS — there must be one name per level 1..MAX_LEVEL.
DEFAULT_RANK_NAMES = {
    1: "Silver I",
    2: "Silver II",
    3: "Silver III",
    4: "Silver IV",
    5: "Silver Elite",
    6: "Silver Elite Master",
    7: "Gold Nova I",
    8: "Gold Nova II",
    9: "Gold Nova III",
    10: "Gold Nova Master",
    11: "Master Guardian",
    12: "Master Guardian II",
    13: "Master Guardian Elite",
    14: "Distinguished Master Guardian",
    15: "Legendary Eagle",
    16: "Legendary Eagle Master",
    17: "Supreme Master First Class",
    18: "Global Elite",
}


def level_from_xp(xp):
    """Return the current level for a lifetime ``xp`` total (capped at
    ``MAX_LEVEL``)."""
    level = 0
    for i, threshold in enumerate(LEVEL_THRESHOLDS):
        if xp >= threshold:
            level = i
        else:
            break
    return level


def xp_for_level(level):
    """Cumulative XP required to *reach* ``level``."""
    if level <= 0:
        return 0
    if level >= MAX_LEVEL:
        return LEVEL_THRESHOLDS[MAX_LEVEL]
    return LEVEL_THRESHOLDS[level]


def is_max_level(level):
    return level >= MAX_LEVEL


def level_progress(xp):
    """Break ``xp`` down for display.

    Returns ``(level, into_level, needed)`` where ``into_level`` is the XP
    earned past the current level's threshold and ``needed`` is the XP between
    this level and the next. At max level both are 0 (treat the bar as full).
    """
    level = level_from_xp(xp)
    if level >= MAX_LEVEL:
        return level, 0, 0
    floor = LEVEL_THRESHOLDS[level]
    ceiling = LEVEL_THRESHOLDS[level + 1]
    return level, xp - floor, ceiling - floor


def progress_bar(into_level, needed, width=20):
    """Render a unicode progress bar, e.g. ``██████░░░░░░░░``."""
    if needed <= 0:
        ratio = 1.0
    else:
        ratio = max(0.0, min(1.0, into_level / needed))
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)
