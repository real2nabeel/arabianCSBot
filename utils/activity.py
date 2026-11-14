"""Pure helpers for the server activity graph and the admin activity table.

No Discord or database access here: the cog feeds in samples and rows, and
these functions decide what is credited and what is drawn.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image, ImageDraw

from utils.leaderboard_image import BACKGROUND, SURFACE, TEXT, MUTED, GOLD, font

PEAK = "#7fb6ff"
OFFLINE = "#d9534f"
GRID = "#323b4e"


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    seconds: int
    bucket: int  # seconds per plotted point
    tick: int  # seconds between x-axis labels
    tick_format: str


PERIODS = {
    "24h": Period("24h", "LAST 24 HOURS", 86400, 900, 3 * 3600, "%H:%M"),
    "7d": Period("7d", "LAST 7 DAYS", 7 * 86400, 3600, 86400, "%a %d"),
    "30d": Period("30d", "LAST 30 DAYS", 30 * 86400, 6 * 3600, 5 * 86400, "%d %b"),
}


def local_zone(offset_hours):
    return timezone(timedelta(hours=offset_hours))


def zone_label(offset_hours):
    return "UTC" if offset_hours == 0 else f"UTC{offset_hours:+d}"


def day_key(wall_time, offset_hours):
    """The local calendar day a moment belongs to."""
    return datetime.fromtimestamp(wall_time, local_zone(offset_hours)).date()


@dataclass
class AdminTracker:
    """Credit time to admins seen online at two consecutive polls.

    A session is undercounted by at most one poll interval, but time is never
    credited across an outage, a failed query or a gap longer than max_gap.
    """
    max_gap: float
    last_time: float | None = None
    last_online: set = field(default_factory=set)

    def observe(self, online, now):
        if online is None:
            self.last_time, self.last_online = None, set()
            return 0, set()
        online = set(online)
        seconds, credited = 0, set()
        if self.last_time is not None and 0 < now - self.last_time <= self.max_gap:
            seconds = round(now - self.last_time)
            credited = online & self.last_online
        self.last_time, self.last_online = now, online
        return (seconds, credited) if credited else (0, set())


def build_series(rows, period, end, offset_hours):
    """Turn per-bucket DB aggregates into one point per bucket.

    ``rows`` maps bucket index -> {"avg", "peak", "samples"} where samples is the
    number of successful polls. A bucket with rows but no successful poll was an
    outage; a bucket with no rows at all is missing data (bot not running).
    Returns (start_ts, [point or None]) where point is (avg, peak) or "offline".
    """
    offset = offset_hours * 3600
    last = (int(end) + offset) // period.bucket
    first = last - period.seconds // period.bucket + 1
    points = []
    for index in range(first, last + 1):
        row = rows.get(index)
        if row is None:
            points.append(None)
        elif not row["samples"]:
            points.append("offline")
        else:
            points.append((float(row["avg"]), int(row["peak"])))
    return first * period.bucket - offset, points


def summarize(points):
    online = [p for p in points if isinstance(p, tuple)]
    if not online:
        return None
    peak_index = max(range(len(points)), key=lambda i: points[i][1] if isinstance(points[i], tuple) else -1)
    return {
        "peak": points[peak_index][1],
        "peak_index": peak_index,
        "average": sum(p[0] for p in online) / len(online),
    }


def nice_ceiling(value):
    for step in (4, 8, 12, 16, 20, 24, 32, 40, 48, 64):
        if value <= step:
            return step
    return ((int(value) + 15) // 16) * 16


def render_activity_graph(points, start, period, updated_at, offset_hours, server_name="DD2"):
    """1800x760 PNG of average and peak human players per bucket."""
    zone = local_zone(offset_hours)
    image = Image.new("RGB", (1800, 760), BACKGROUND)
    draw = ImageDraw.Draw(image)
    small, body = font(24), font(30)
    draw.rectangle((0, 0, 1800, 8), fill=GOLD)
    draw.text((50, 32), f"{server_name} · SERVER ACTIVITY", font=font(48, True), fill=TEXT)
    draw.text((1750, 49), period.label, font=small, fill=MUTED, anchor="ra")

    stats = summarize(points)
    if stats:
        peak_time = datetime.fromtimestamp(start + stats["peak_index"] * period.bucket, zone)
        peak_when = peak_time.strftime("%H:%M" if period.key == "24h" else "%a %d %b, %H:%M")
        summary = [("PEAK", f"{stats['peak']} players", peak_when),
                   ("AVERAGE", f"{stats['average']:.1f} players", "while online")]
        x = 50
        for column, (label, value, note) in enumerate(summary):
            face = font(36, True)
            draw.text((x, 112), label, font=small, fill=MUTED)
            draw.text((x, 142), value, font=face, fill=GOLD if column == 0 else TEXT)
            note_x = x + draw.textlength(value, font=face) + 18
            draw.text((note_x, 152), note, font=small, fill=MUTED)
            x = max(x + 520, note_x + draw.textlength(note, font=small) + 80)

    left, top, right, bottom = 120, 220, 1750, 640
    top_value = nice_ceiling(stats["peak"] if stats else 0)
    for step in range(5):
        value = top_value * step // 4
        y = bottom - (bottom - top) * step / 4
        draw.line((left, y, right, y), fill=GRID, width=1)
        draw.text((left - 16, y), str(value), font=small, fill=MUTED, anchor="rm")

    count = len(points)
    width = (right - left) / count

    def x_of(i):
        return left + (i + 0.5) * width

    def y_of(value):
        return bottom - (bottom - top) * min(value, top_value) / top_value

    # Average as a filled area and peak as a line, both broken at gaps.
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shade = ImageDraw.Draw(overlay)
    runs, run = [], []
    for i, point in enumerate(points):
        if isinstance(point, tuple):
            run.append(i)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    for run in runs:
        if len(run) == 1:
            i = run[0]
            shade.rectangle((x_of(i) - width / 2, y_of(points[i][0]), x_of(i) + width / 2, bottom),
                            fill=(243, 185, 85, 110))
            continue
        polygon = [(x_of(run[0]), bottom)] + [(x_of(i), y_of(points[i][0])) for i in run] + [(x_of(run[-1]), bottom)]
        shade.polygon(polygon, fill=(243, 185, 85, 110))
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))
    draw = ImageDraw.Draw(image)
    for run in runs:
        draw.line([(x_of(i), y_of(points[i][0])) for i in run], fill=GOLD, width=3)
        draw.line([(x_of(i), y_of(points[i][1])) for i in run], fill=PEAK, width=2)
    for i, point in enumerate(points):
        if point == "offline":
            draw.rectangle((left + i * width, bottom - 8, left + (i + 1) * width, bottom), fill=OFFLINE)
    draw.line((left, bottom, right, bottom), fill=MUTED, width=2)

    # X-axis labels on whole local hours/days.
    first_tick = start - (start + offset_hours * 3600) % period.tick
    if first_tick < start:
        first_tick += period.tick
    end = start + count * period.bucket
    tick = first_tick
    while tick < end:
        x = left + (tick - start) / period.bucket * width
        draw.line((x, bottom, x, bottom + 8), fill=MUTED, width=2)
        label = datetime.fromtimestamp(tick, zone).strftime(period.tick_format)
        draw.text((x, bottom + 14), label, font=small, fill=MUTED, anchor="ma")
        tick += period.tick

    if not stats:
        draw.rounded_rectangle((560, 360, 1240, 470), radius=8, fill=SURFACE)
        draw.text((900, 415), "No player data recorded yet.", font=body, fill=TEXT, anchor="mm")

    legend_y = 700
    x = 50
    for colour, label, height in ((GOLD, "Average players", 14), (PEAK, "Peak players", 4),
                                  (OFFLINE, "Server offline", 14)):
        draw.rectangle((x, legend_y + 14 - height // 2, x + 28, legend_y + 14 + height // 2), fill=colour)
        draw.text((x + 40, legend_y + 1), label, font=small, fill=MUTED)
        x += 300
    draw.text((1750, legend_y + 1),
              f"Updated {updated_at.astimezone(zone):%d %b %Y · %H:%M} {zone_label(offset_hours)}",
              font=small, fill=MUTED, anchor="ra")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def format_hours(seconds):
    hours = (seconds or 0) / 3600
    if hours == 0:
        return "0h"
    if hours < 99.95:
        return f"{hours:.1f}h"
    return f"{hours:,.0f}h"


def format_ago(last_seen, now):
    if not last_seen:
        return "—"  # not seen since the bot started recording
    delta = max(0, now - last_seen)
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def short_name(name, limit=20):
    name = " ".join(str(name or "Unknown").split())
    return name if len(name) <= limit else name[:limit - 1] + "…"


def admin_rows(admins, activity, now):
    """Merge current admins (live rank table) with recorded activity.

    ``admins``: dicts with steam_id, nick, online, season_seconds.
    ``activity``: steam_id -> {"week", "month", "last_seen"}.
    Sorted by the last 7 days, then 30 days, then season time.
    """
    rows = []
    for admin in admins:
        record = activity.get(admin["steam_id"], {})
        rows.append({
            "nick": admin["nick"],
            "online": admin["online"],
            "week": int(record.get("week") or 0),
            "month": int(record.get("month") or 0),
            "season": int(admin["season_seconds"] or 0),
            "seen": "online now" if admin["online"] else format_ago(record.get("last_seen"), now),
        })
    rows.sort(key=lambda r: (-r["week"], -r["month"], -r["season"], r["nick"].lower()))
    return rows


def format_admin_table(rows):
    """Fixed-width table for a Discord code block; names last so RTL text cannot break columns."""
    lines = [f"{'7 DAYS':>7} {'30 DAYS':>8} {'SEASON':>7}  {'LAST SEEN':<10}  ADMIN"]
    for row in rows:
        lines.append(f"{format_hours(row['week']):>7} {format_hours(row['month']):>8} "
                     f"{format_hours(row['season']):>7}  {row['seen']:<10}  {short_name(row['nick'])}")
    return "\n".join(lines)
