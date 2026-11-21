"""Choosing which highlights become clips, and the time window of each. Pure functions, unit-tested.

A *moment* is one line of the plugin's clips_YYYYMMDD.jsonl. Its start/end/logged times are the server's game
clock; ``locate`` turns them into demo time using the "[clips] mark <id>" line the plugin put in the demo at
``logged``. Moments by the same player that overlap (a 4-kill burst inside a clutch) become one clip.
"""

PRE_ROLL = 3.0        # seconds shown before the first kill
POST_ROLL = 2.5       # seconds shown after the last kill
CLUTCH_TAIL = 8.0     # a clutch can end with a defuse a few seconds after the last kill
MAX_LENGTH = 40.0     # longest clip; a long clutch is trimmed from the start
MIN_LENGTH = 5.0      # anything shorter isn't worth a clip

WEAPON_NAMES = {
    "ak47": "AK-47", "m4a1": "M4A1", "awp": "AWP", "scout": "Scout", "deagle": "Deagle", "usp": "USP",
    "glock18": "Glock", "famas": "FAMAS", "galil": "Galil", "sg552": "SG 552", "aug": "AUG", "p90": "P90",
    "mp5navy": "MP5", "ump45": "UMP", "mac10": "MAC-10", "tmp": "TMP", "m249": "M249", "m3": "M3",
    "xm1014": "XM1014", "g3sg1": "G3SG1", "sg550": "SG 550", "p228": "P228", "fiveseven": "Five-seveN",
    "elite": "Dual Berettas", "knife": "knife", "grenade": "HE grenade",
}


# What the server's kill-streak announcer (AQS) calls N kills; 4 has no announcement there, so it gets the name of
# the sound AQS ships for it.
STREAKS = {2: "Double kill", 3: "Triple kill", 4: "Quad kill", 5: "Multi kill", 6: "Rampage", 7: "Killing spree",
           8: "Dominating", 9: "Impressive"}


RUN_MAX = 20            # most clips one /clips-run may ask for (cogs/clips.py RUN_MAX)


def run_limit(request, default):
    """How many clips a requested run makes: the request's "limit" (from /clips-run's count or /clips-one), at most
    RUN_MAX, or ``default`` when the request names none."""
    limit = request.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        return min(limit, RUN_MAX)
    return default


def streak_name(kills):
    """"Triple kill" for 3 kills, ... "Unstoppable" from 10; "" below 2."""
    return "Unstoppable" if kills >= 10 else STREAKS.get(kills, "")


def weapon_name(code):
    return WEAPON_NAMES.get(code, code.upper())


def locate(moment, marks):
    """(demo_start, demo_end) of a moment, or None if its mark isn't in this demo."""
    t = marks.get(moment["id"])
    if t is None:
        return None
    return t - (moment["logged"] - moment["start"]), t - (moment["logged"] - moment["end"])


def window(moment, demo_start, demo_end, kills):
    """Clip window in demo time, built around the player's own kills in that span."""
    own = sorted(k["t"] for k in kills
                 if k["k"] == moment["entity"] and demo_start - 0.5 <= k["t"] <= demo_end + 0.5)
    first = own[0] if own else demo_start
    last = own[-1] if own else demo_end
    if moment["type"] == "clutch":
        last = min(max(last, demo_end), last + CLUTCH_TAIL)
    start, end = first - PRE_ROLL, last + POST_ROLL
    if end - start > MAX_LENGTH:
        start = end - MAX_LENGTH
    return max(0.0, start), end


def describe(moment):
    """Short human description, e.g. "4 kills in 2.1 s", "1v3 clutch", "no-scope AWP kill"."""
    kind, kills = moment["type"], moment.get("kills", 0)
    extra = moment.get("extra", "").split()
    weapons = moment.get("weapons", "").split()
    if kind == "multikill":
        text = f"{streak_name(kills)}: {kills} kills" if kills >= 3 else f"{kills} kills"
        span = moment["end"] - moment["start"]
        if 0 < span <= 6:
            text += f" in {span:.1f} s"
        return text
    if kind == "clutch":
        enemies = moment.get("enemies") or (extra[0][2:] if extra and extra[0].startswith("1v") else "?")
        return f"1v{enemies} clutch" + (f" with {kills} kills" if kills > 1 else "")
    if "double" in extra:
        return "one-shot double kill"
    if "noscope" in extra:
        sniper = next((w for w in weapons if w in ("awp", "scout", "g3sg1", "sg550")), "awp")
        return f"no-scope {weapon_name(sniper)} kill"
    if "knife" in extra:
        return "knife kill"
    if "air" in extra:
        return "mid-air kill"
    return f"{kills} kill" + ("s" if kills != 1 else "")


def plan(moments, demos, top=8, min_score=30):
    """Pick clips from the day's moments.

    ``demos``: {path: scan result} (see clips.demo.scan). Returns clip dicts, best first:
    {"key", "demo", "map", "entity", "player", "team", "start", "end", "score", "moments", "summary", "logged"}.
    ``moments`` is one moment describing what the clip shows, scored on it (``what_it_shows``); ``logged`` the
    plugin's moments it came from. ``min_score`` applies to the plugin's scores.
    """
    found = []
    for m in moments:
        if m.get("score", 0) < min_score or not m.get("entity"):
            continue
        for path, info in demos.items():
            span = locate(m, info["marks"])
            if span is None or info.get("map") not in (None, "", m.get("map")):
                continue
            if span[0] < 0:
                break   # the moment began before this demo did (HLTV joined mid-round): it wasn't all recorded
            start, end = window(m, span[0], span[1], info["kills"])
            if end - start < MIN_LENGTH:
                break
            found.append({"demo": path, "map": m.get("map", info.get("map", "")), "entity": m["entity"],
                          "player": m["player"], "team": m.get("team", ""), "start": start, "end": end,
                          "score": m["score"], "moments": [m]})
            break

    # Merge overlapping clips of the same player in the same demo.
    found.sort(key=lambda c: (c["demo"], c["entity"], c["start"]))
    merged = []
    for c in found:
        last = merged[-1] if merged else None
        if last and last["demo"] == c["demo"] and last["entity"] == c["entity"] and c["start"] <= last["end"]:
            last["end"] = max(last["end"], c["end"])
            if last["end"] - last["start"] > MAX_LENGTH:
                last["start"] = last["end"] - MAX_LENGTH
            last["score"] = max(last["score"], c["score"]) + min(last["score"], c["score"]) // 2
            last["moments"] += c["moments"]
        else:
            merged.append(c)

    for c in merged:
        first = c["moments"][0]
        c["key"] = f"{first.get('date', '')[:10]}_{first['id']}".replace(" ", "_")
        c["logged"] = c["moments"]
        play = what_it_shows(c, demos[c["demo"]]["kills"])
        c["moments"] = [play]
        c["score"] = play["score"]
        c["summary"] = describe(play)
    merged.sort(key=lambda c: -c["score"])
    return merged[:top]


# ---- scoring a clip by what it shows -------------------------------------------------------------------------------
# The plugin's moments only say where to look. A clip is scored on the followed player's kills inside it (from the
# demo's kill lines), so a long clutch trimmed to 40 seconds counts the kills it still shows. What we want most: many
# kills in a short time, knife kills, headshots (Deagle ones above all), and AWP kills, which count like headshots.
KILL_POINTS = 10        # any kill
HEADSHOT_POINTS = 10    # added for a headshot, or for an AWP / Scout kill
DEAGLE_HS_POINTS = 20   # added instead for a Deagle headshot
KNIFE_POINTS = 25       # added for a knife kill
BURST_GAP = 4.0         # most seconds between two kills of one burst (as the plugin)
BURST_POINTS = 15       # per kill past the second in the best burst
FAST_GAP = 1.5          # a burst averaging this many seconds or less between kills is fast...
FAST_POINTS = 10        # ...and gets this per kill
CLUTCH_REAL = 6         # a clutch against this many or more is a real play
CLUTCH_SMALL = 5        # per enemy for a smaller clutch
CLUTCH_BIG = 60         # for a real one, plus CLUTCH_SMALL x2 per enemy past CLUTCH_REAL
EXTRA_POINTS = {"noscope": 30, "double": 35, "air": 10}   # from the plugin: once each per clip
SNIPERS = ("awp", "scout")


def kill_points(k):
    if k["w"] == "knife":
        return KILL_POINTS + KNIFE_POINTS
    if k["hs"] and k["w"] == "deagle":
        return KILL_POINTS + DEAGLE_HS_POINTS
    if k["hs"] or k["w"] in SNIPERS:
        return KILL_POINTS + HEADSHOT_POINTS
    return KILL_POINTS


def best_burst(times):
    """The longest run of kills with at most BURST_GAP seconds between them: (kills, seconds)."""
    best, run = (0, 0.0), []
    for t in sorted(times):
        run = run + [t] if run and t - run[-1] <= BURST_GAP else [t]
        if len(run) > best[0] or (len(run) == best[0] and run[-1] - run[0] < best[1]):
            best = (len(run), run[-1] - run[0])
    return best


def score_kills(kills, clutch_enemies=0, extras=()):
    """Score for a clip showing ``kills`` (the followed player's, in order). ``clutch_enemies``: the N of the 1vN
    clutch the clip shows (0: no clutch)."""
    score = sum(kill_points(k) for k in kills)
    n, span = best_burst([k["t"] for k in kills])
    if n >= 3:
        score += BURST_POINTS * (n - 2)
        if span / (n - 1) <= FAST_GAP:
            score += FAST_POINTS * n
    if clutch_enemies >= CLUTCH_REAL:
        score += CLUTCH_BIG + 2 * CLUTCH_SMALL * (clutch_enemies - CLUTCH_REAL)
    elif clutch_enemies:
        score += CLUTCH_SMALL * clutch_enemies
    return score + sum(EXTRA_POINTS.get(e, 0) for e in set(extras))


def what_it_shows(clip, kills):
    """One moment describing the clip as it will be seen, in the plugin's format (type, kills, headshots, weapons,
    extra, enemies, start/end, score), so the headline and post text describe what's on screen. A clutch is 1vN
    with N the kills shown (at most the enemies it started against): a 1v4 that shows 2 kills is a 1v2. ``start`` and
    ``end`` are the first and last kill's demo times."""
    logged = clip["moments"]
    own = sorted((k for k in kills if k["k"] == clip["entity"] and k.get("vt") != k.get("kt")
                  and clip["start"] <= k["t"] <= clip["end"]), key=lambda k: k["t"])
    extras = sorted({e for m in logged for e in (m.get("extra") or "").split() if e in EXTRA_POINTS})
    clutches = [m for m in logged if m["type"] == "clutch"]
    enemies = min(len(own), max(int(m.get("enemies") or 0) for m in clutches)) if clutches else 0
    if enemies:
        kind = "clutch"
    elif len(own) >= 3 or (len(own) == 2 and not extras):
        kind = "multikill"
    else:
        kind = "special"
    first = logged[0]
    return {"id": first["id"], "date": first.get("date", ""), "map": first.get("map", ""), "round": first.get("round"),
            "type": kind, "kills": len(own), "headshots": sum(1 for k in own if k["hs"]),
            "weapons": " ".join(k["w"] for k in own), "extra": " ".join(extras), "enemies": enemies,
            "start": own[0]["t"] if own else clip["start"], "end": own[-1]["t"] if own else clip["start"],
            "score": score_kills(own, enemies, extras)}
