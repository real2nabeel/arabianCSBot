"""Choosing which highlights become clips, and the time window of each. Pure functions, unit-tested.

A *moment* is one line of the plugin's clips_YYYYMMDD.jsonl. Its start/end/logged times are the server's game
clock; ``locate`` turns them into demo time using the "[clips] mark <id>" line the plugin put in the demo at
``logged``. Moments by the same player that overlap (a 4-kill burst inside a clutch) become one clip.
"""

PRE_ROLL = 3.0        # seconds shown before the first kill
POST_ROLL = 2.5       # seconds shown after the last kill
CLUTCH_TAIL = 8.0     # a clutch can end with a defuse a few seconds after the last kill
MAX_LENGTH = 40.0     # longest clip; a long clutch is trimmed from the start

WEAPON_NAMES = {
    "ak47": "AK-47", "m4a1": "M4A1", "awp": "AWP", "scout": "Scout", "deagle": "Deagle", "usp": "USP",
    "glock18": "Glock", "famas": "FAMAS", "galil": "Galil", "sg552": "SG 552", "aug": "AUG", "p90": "P90",
    "mp5navy": "MP5", "ump45": "UMP", "mac10": "MAC-10", "tmp": "TMP", "m249": "M249", "m3": "M3",
    "xm1014": "XM1014", "g3sg1": "G3SG1", "sg550": "SG 550", "p228": "P228", "fiveseven": "Five-seveN",
    "elite": "Dual Berettas", "knife": "knife", "grenade": "HE grenade",
}


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
        text = f"{kills} kills"
        span = moment["end"] - moment["start"]
        if span <= 6:
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
    {"key", "demo", "map", "entity", "player", "team", "start", "end", "score", "moments", "summary"}.
    """
    found = []
    for m in moments:
        if m.get("score", 0) < min_score or not m.get("entity"):
            continue
        for path, info in demos.items():
            span = locate(m, info["marks"])
            if span is None or info.get("map") not in (None, "", m.get("map")):
                continue
            start, end = window(m, span[0], span[1], info["kills"])
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
        parts = []
        for m in sorted(c["moments"], key=lambda m: -m["score"]):
            text = describe(m)
            if text not in parts:
                parts.append(text)
        c["summary"] = ", ".join(parts[:2])
        first = c["moments"][0]
        c["key"] = f"{first.get('date', '')[:10]}_{first['id']}".replace(" ", "_")
    merged.sort(key=lambda c: -c["score"])
    return merged[:top]
