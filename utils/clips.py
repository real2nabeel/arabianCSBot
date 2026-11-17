"""Clip posting decisions. Pure functions (no Discord, no DB), unit-tested in tests/test_clips.py."""
import datetime as dt

APPROVE = "👍"
REJECT = "❌"


def caption(meta, template, server, hashtags):
    """Post text for a clip. Unknown {fields} in the template are left as they are."""
    values = {"player": meta.get("player", ""), "summary": meta.get("summary", ""),
              "map": meta.get("map", ""), "server": server, "hashtags": hashtags}

    class Keep(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    return template.format_map(Keep(values)).strip()


def title(meta, limit=100):
    """Short title (YouTube): "Name – 4 kills in 2.1 s #Shorts", trimmed to ``limit`` characters."""
    tail = " #Shorts"
    text = f"{meta.get('player', '')} – {meta.get('summary', '')}"
    return text[:limit - len(tail)].rstrip() + tail


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
