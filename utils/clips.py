"""Clip posting decisions. Pure functions (no Discord, no DB), unit-tested in tests/test_clips.py."""
import datetime as dt
import zlib

from clips.select import streak_name

APPROVE = "👍"
REJECT = "❌"

# ---- post text ------------------------------------------------------------------------------------------------------
# Search on YouTube, Instagram and TikTok reads the caption, and only its first line shows under the video, so the
# first line ("hook") says what happened with a number and the words people search for (CS 1.6, Dust2, clutch, ace).
# The player is credited further down. Each kind of moment has a few phrasings; a clip always gets the same one
# (picked from its id), so a retried post keeps its text, and the daily posts don't all read alike.
WEAPON_WORDS = {"ak47": "AK-47", "m4a1": "M4A1", "awp": "AWP", "deagle": "Deagle", "knife": "knife", "usp": "USP",
                "glock18": "Glock", "scout": "Scout", "famas": "FAMAS", "galil": "Galil", "mp5navy": "MP5",
                "p90": "P90", "hegrenade": "grenade", "m3": "M3", "xm1014": "XM1014", "aug": "AUG", "sg552": "SG 552",
                "g3sg1": "G3SG1", "sg550": "SG 550", "elite": "Dual Berettas", "fiveseven": "Five-SeveN",
                "p228": "P228", "tmp": "TMP", "mac10": "MAC-10", "ump45": "UMP45", "m249": "M249"}

HOOKS = {
    "clutch": ["CS 1.6 – 1v{n} clutch with {k} kills", "1v{n} clutch on Dust2 – CS 1.6",
               "Last one alive in a 1v{n} – CS 1.6 clutch"],
    "knife": ["{k} knife kills in {s} seconds", "{k} knife kills, {s} seconds – CS 1.6",
              "Knife only: {k} kills in {s} seconds – CS 1.6"],
    "headshots": ["{k} headshots in {s} seconds – CS 1.6", "{N}, all headshots – CS 1.6 Dust2",
                  "{k} kills, {k} headshots – CS 1.6"],
    "headshots_weapon": ["{k} {W} headshots in {s} seconds – CS 1.6", "{W} {N}, all headshots – CS 1.6",
                         "{k} {W} headshots in a row – CS 1.6"],
    "weapon": ["{k} {W} kills in {s} seconds – CS 1.6", "{W} {N} in {s} seconds – CS 1.6 Dust2",
               "{N} with the {W} – CS 1.6"],
    "multikill": ["{N}: {k} kills in {s} seconds – CS 1.6", "{k} kills in {s} seconds on Dust2 – CS 1.6",
                  "{N} on Dust2 – CS 1.6"],
    "untimed": ["{k} kills – CS 1.6 Dust2", "{k}K on Dust2 – CS 1.6"],
    "noscope": ["No-scope {W} kill – CS 1.6", "No scope, no problem – CS 1.6 {W}"],
    "double": ["One shot, two kills – CS 1.6 {W}", "Two kills, one bullet – CS 1.6"],
    "air": ["Mid-air kill – CS 1.6", "Killed while flying – CS 1.6"],
    "single": ["{W} kill – CS 1.6 Dust2"],
}
QUESTIONS = {
    "clutch": ["Could you clutch this?", "Would you have won this 1v{n}?", "What would you have done here?"],
    "kills": ["Rate this from 1 to 10.", "Could you do this?", "How many would you have got?"],
    "special": ["Skill or luck?", "Rate this from 1 to 10."],
}
TAGS = {"clutch": "#clutch", "headshot": "#headshot", "knife": "#knife", "awp": "#awp", "kills": "#multikill"}


def _main_moment(meta):
    moments = meta.get("moments") or []
    return max(moments, key=lambda m: m.get("score", 0)) if moments else None


def _pick(options, meta, salt=""):
    key = f"{meta.get('key', '')}{salt}"
    return options[zlib.crc32(key.encode()) % len(options)]


def _seconds(span):
    return f"{span:.1f}".rstrip("0").rstrip(".")


def moment_text(meta):
    """(hook, question, hashtag) for a clip, from its best moment. Falls back to the old "player – summary"."""
    m = _main_moment(meta)
    if not m:
        return f"{meta.get('player', '')} – {meta.get('summary', '')}", "", ""
    kind = m.get("type")
    k = int(m.get("kills") or 0)
    n = int(m.get("enemies") or 0)
    weapons = (m.get("weapons") or "").split()
    tags = set((m.get("extra") or "").split())
    one = WEAPON_WORDS.get(weapons[0], weapons[0].upper()) if weapons and len(set(weapons)) == 1 else ""
    span = float(m.get("end") or 0) - float(m.get("start") or 0)
    all_hs = k >= 2 and int(m.get("headshots") or 0) >= k
    if kind == "clutch":
        group, ask, tag = "clutch", "clutch", "clutch"
    elif kind == "multikill" and span <= 0:
        group, ask, tag = "untimed", "kills", "kills"
    elif kind == "multikill" and one == "knife":
        group, ask, tag = "knife", "kills", "knife"
    elif kind == "multikill" and all_hs:
        group, ask, tag = ("headshots_weapon" if one else "headshots"), "kills", "headshot"
    elif kind == "multikill":
        group, ask, tag = ("weapon" if one else "multikill"), "kills", ("awp" if one == "AWP" else "kills")
    elif "noscope" in tags:
        group, ask, tag = "noscope", "special", "awp"
    elif "double" in tags:
        group, ask, tag = "double", "special", ("awp" if one == "AWP" else "kills")
    elif "air" in tags:
        group, ask, tag = "air", "special", ""
    else:
        group, ask, tag = "single", "special", ("knife" if one == "knife" else "")
    values = {"k": k, "n": n, "s": _seconds(span), "W": one or "weapon", "N": streak_name(k) or f"{k} kills"}
    hook = _pick(HOOKS[group], meta).format(**values)
    hook = hook[0].upper() + hook[1:]
    question = _pick(QUESTIONS[ask], meta, "q").format(**values)
    return hook, question, TAGS.get(tag, "")


def caption(meta, template, server, hashtags):
    """Post text for a clip. Template fields: {hook}, {question}, {player}, {server}, {hashtags} (the given ones
    plus one for the kind of moment), and the older {summary} and {map}. Unknown {fields} are left as they are."""
    hook, question, tag = moment_text(meta)
    tags = hashtags.split()
    if tag and tag.lower() not in (t.lower() for t in tags):
        tags.insert(min(3, len(tags)), tag)
    values = {"player": meta.get("player", ""), "summary": meta.get("summary", ""), "map": meta.get("map", ""),
              "server": server, "hashtags": " ".join(tags), "hook": hook, "question": question}

    class Keep(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    return template.format_map(Keep(values)).strip()


def title(meta, limit=100):
    """Short title (YouTube): the caption's first line ("1v4 clutch on Dust2 – CS 1.6"), at most ``limit``
    characters. YouTube shows it in the feed and searches it, so the keywords come first."""
    return moment_text(meta)[0][:limit].rstrip()


def tiktok_draft_dm(meta, caption):
    """The two DMs sent after a clip lands in TikTok's drafts (which have no caption): what's waiting, and the
    caption alone, so a long press copies just the caption."""
    what = f"{meta.get('player', '')} – {meta.get('summary', '')}".strip(" –")
    note = (f"📥 New TikTok draft: **{what}**\n"
            "Open TikTok (the \"content is ready\" notification or your inbox), paste the caption below and post it.")
    return note, caption.strip()[:2000]


def parse_hours(spec):
    """"12-23" -> (12, 23): posting is allowed from hour 12:00 up to 23:59. "0-23" or blank means any time."""
    if not spec:
        return 0, 23
    start, _, end = spec.partition("-")
    start, end = int(start), int(end or start)
    if not (0 <= start <= 23 and 0 <= end <= 23):
        raise ValueError("CLIPS_POST_HOURS must look like 12-23")
    return start, end


def in_hours(local_now, hours):
    start, end = hours
    h = local_now.hour
    return start <= h <= end if start <= end else (h >= start or h <= end)   # e.g. 20-2 wraps midnight


def may_post(local_now, hours, posted_times, per_day, gap_minutes):
    """Whether a platform may post now. ``posted_times``: local datetimes of that platform's earlier posts."""
    if per_day <= 0 or not in_hours(local_now, hours):
        return False
    today = [t for t in posted_times if t.date() == local_now.date()]
    if len(today) >= per_day:
        return False
    if posted_times and local_now - max(posted_times) < dt.timedelta(minutes=gap_minutes):
        return False
    return True


def next_clip(approved, posted_ids):
    """The oldest approved clip not yet on this platform. ``approved``: [(clip_id, approved_at)]."""
    for clip_id, _ in sorted(approved, key=lambda c: (c[1], c[0])):
        if clip_id not in posted_ids:
            return clip_id
    return None


def decision(reactions, approver_ids):
    """Final state from the review message's reactions: {emoji: set of user ids} -> approved/rejected/pending.
    A rejection by any approver wins over approvals."""
    if reactions.get(REJECT, set()) & approver_ids:
        return "rejected"
    if reactions.get(APPROVE, set()) & approver_ids:
        return "approved"
    return "pending"


def run_report(status):
    """Review-channel message for a finished /clips-run (status.json from clips/nightly.py), or None while running."""
    state = status.get("state")
    who = status.get("requested_by")
    by = f" (started by <@{who}>)" if who else ""
    made, failed = status.get("made", 0), status.get("failed", 0)
    if state == "done":
        text = f"🎬 Clip run finished{by}: {made} new clip{'s' if made != 1 else ''} below."
        if failed:
            text += f" {failed} couldn't be made ({status.get('error', 'unknown error')})."
        return text
    if state == "nothing":
        return f"🎬 Clip run finished{by}: no new highlights since the last run."
    if state == "busy":
        text = (f"⏸️ Clip run stopped{by}: the Steam account is in a game on another computer. "
                "Run /clips-run again when nobody is playing on it.")
        return text + (f" {made} clip{'s' if made != 1 else ''} made before that." if made else "")
    if state == "error":
        return f"⚠️ Clip run failed{by}: {status.get('error') or 'unknown error'}"
    return None


QUEUE_PAGE = 20


def queue_page(queue, page=1, per_page=QUEUE_PAGE, name_width=16):
    """(text, pages) for /clips-queue: one page of the clips the host can still make (queue.json from clips/nightly.py),
    best first, as a fixed-width table. Each title is the clip's post title; the player's name comes last so a long
    or right-to-left name can't break the columns."""
    clips = (queue or {}).get("clips") or []
    pages = max(1, -(-len(clips) // per_page))
    page = min(max(1, page), pages)
    rows = clips[(page - 1) * per_page: page * per_page]
    if not rows:
        return "No clips are waiting to be made.", 1
    titles = [moment_text(c)[0] for c in rows]
    width = max(len(t) for t in titles)
    first = (page - 1) * per_page + 1
    lines = [f"{'#':>3}  {'Score':>5}  {'Title':<{width}}  Player"]
    for i, (c, t) in enumerate(zip(rows, titles)):
        name = str(c.get("player", ""))
        name = name if len(name) <= name_width else name[:name_width - 1] + "…"
        lines.append(f"{first + i:>3}  {c.get('score', 0):>5}  {t:<{width}}  {name}")
    return "\n".join(lines), pages
