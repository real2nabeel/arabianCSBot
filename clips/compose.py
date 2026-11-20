"""Turning a raw 1920x1080 spectator recording into the finished clip files.

Layout from ClipsPipeline/format_clips.bat: gameplay over a blurred copy, with a band above the gameplay holding the logo, a
headline for the moment and kill dots (the logo used to sit bottom-right, under the apps' captions and buttons). Those clips were
a player's own screen, gameplay 1680 wide and so 945 tall. HLTV playback adds spectator bars: the renderer hides the
top one (render.hide_spectator_bar), the bottom one is cropped off, and the rest is zoomed to the same 945 height
(1938 wide, a little more of the sides cut off). If the top bar couldn't be hidden, both bars are cropped and the
gameplay is 1680 wide (693 tall). The game's own kill feed (which HLTV playback can't hide) is replaced by ours: drawn from the demo's "[clips] kill" lines in CS style with the game's own weapon icons,
each line on a soft dark background. Writes hq.mp4 (1080x1920 60 fps, for social media) and discord.mp4
(720x1280, under 9.5 MB: made again at a lower bitrate if it comes out bigger).
"""
import os, shutil, struct, subprocess, tempfile
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from clips.select import streak_name

HL = os.path.join(os.path.expanduser(os.environ.get("CLIPS_HL_DIR", "~/.steam/debian-installation/steamapps/common/Half-Life")), "cstrike")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host", "logo.png")
T_COLOR, CT_COLOR, ICON_COLOR = (255, 80, 80), (153, 204, 255), (255, 150, 30)
FEED_TIME, MAX_ROWS = 6.0, 4          # CS shows a kill for 6 seconds, 4 at most
ICON_SCALE, FONT_SIZE, ROW_GAP = 2, 30, 8
FEED_SCALE = 0.65                     # rows are drawn at the sizes above, then shrunk to this (about CS's own size)
# (crop of the 1920x1080 recording, gameplay width in the 1080x1920 frame), with and without the top bar hidden
FRAMING = {True: ("1920:936:0:0", 1938), False: ("1920:792:0:144", 1680)}


def framing(bar_hidden=True):
    """(ffmpeg crop, gameplay width, gameplay height, gameplay top) in the 1080x1920 frame."""
    crop, width = FRAMING[bool(bar_hidden)]
    w, h = (int(x) for x in crop.split(":")[:2])
    height = round(h * width / w / 2) * 2
    return crop, width, height, (1920 - height) // 2
DISCORD_BYTES = 9.5 * 1024 * 1024    # aim for the Discord copy; Discord's limit is 10 MiB
DISCORD_TRIES = 3                     # encodes at most: the aimed bitrate can come out about 2% big on hard clips
AUDIO_KBPS = 128
KILL_FEED_DELAY = 0.46   # without time markers: a kill shows this long after its demo time (old measurement)
FEED_LEAD = 0.0          # with markers: shift from the frame a kill happens on (checked frame by frame)

def hud_sprites():
    out = {}
    for line in open(os.path.join(HL, "sprites/hud.txt"), encoding="latin1"):
        p = line.split()
        if len(p) == 7 and p[1] == "640":
            out[p[0]] = (p[2], int(p[3]), int(p[4]), int(p[5]), int(p[6]))
    return out

_sprites = {}
def sprite(name):
    """First frame of a GoldSrc .spr as a greyscale intensity image (HUD sprites are drawn additively)."""
    if name not in _sprites:
        d = open(os.path.join(HL, "sprites", name + ".spr"), "rb").read()
        assert d[:4] == b"IDSP", name
        p = 40
        n, = struct.unpack_from("<h", d, p); p += 2
        pal = d[p:p + n * 3]; p += n * 3 + 4          # palette, then the frame type
        _, _, w, h = struct.unpack_from("<iiii", d, p); p += 16
        img = Image.new("L", (w, h))
        img.putdata([(pal[i * 3] * 299 + pal[i * 3 + 1] * 587 + pal[i * 3 + 2] * 114) // 1000 for i in d[p:p + w * h]])
        _sprites[name] = img
    return _sprites[name]

SCOPE_FOV = 40   # zoomed at or below this: AWP, Scout, G3SG1, SG550 (the AUG and SG552 zoom to 55, with no scope)


def scope_image():
    """The sniper scope's dotted crosshair with the red centre dot (sprites/sniper_scope.spr, 256x256, colour index
    255 see-through), as RGBA. CS swaps it in for the player who scopes in, but not in HLTV playback: compose draws it
    over the recording, 1:1 at the centre of the screen as the game does."""
    d = open(os.path.join(HL, "sprites", "sniper_scope.spr"), "rb").read()
    assert d[:4] == b"IDSP"
    p = 40
    n, = struct.unpack_from("<h", d, p); p += 2
    pal = d[p:p + n * 3]; p += n * 3 + 4
    _, _, w, h = struct.unpack_from("<iiii", d, p); p += 16
    px = d[p:p + w * h]
    img = Image.frombytes("P", (w, h), px)
    img.putpalette(pal)
    rgba = img.convert("RGBA")
    rgba.putalpha(Image.frombytes("L", (w, h), bytes(0 if i == 255 else 255 for i in px)))
    return rgba


def scope_ranges(zooms, length, to_video):
    """Video time ranges with the player scoped in, from the demo's (demo time, fov) zoom changes (clips.demo.overlays;
    fov 0 or 90 = not zoomed)."""
    out, since = [], None
    for t, fov in sorted(zooms):
        scoped = 0 < fov <= SCOPE_FOV
        if scoped and since is None:
            since = to_video(t)
        elif not scoped and since is not None:
            out.append((since, to_video(t)))
            since = None
    if since is not None:
        out.append((since, length))
    return [(max(0.0, a), min(length, b)) for a, b in out if b > 0 and a < length and b > a]


# CS's plant/defuse progress bar, in screen pixels of the 1920x1080 recording: the middle half of the screen, two
# thirds of the way down, an orange fill growing from the left inside a thin outline.
BAR_X, BAR_Y, BAR_W, BAR_H = 480, 720, 960, 12
BAR_FILL, BAR_EDGE = (255, 140, 0, 255), (255, 140, 0, 160)


def bar_ranges(bars, length, to_video):
    """(video start, video end, seconds, percent at start) for each progress bar shown in the clip, from
    clips.demo.overlays: a bar lasts its seconds, or until the next one (0 seconds = taken away)."""
    bars = sorted(bars)
    out = []
    for i, (t, secs, pct) in enumerate(bars):
        if secs <= 0:
            continue
        end = t + secs * (100 - pct) / 100
        if i + 1 < len(bars):
            end = min(end, bars[i + 1][0])
        a, b = to_video(t), to_video(end)
        if b > 0 and a < length:
            out.append((a, min(b, length), secs, pct))
    return out


def bar_images(tmp):
    """The bar's outline (BAR_W x BAR_H) and a fill strip twice as wide (the left half filled): cropping a BAR_W
    window that slides from the right half to the left one shows the fill growing from the left."""
    frame = Image.new("RGBA", (BAR_W, BAR_H), (0, 0, 0, 110))
    ImageDraw.Draw(frame).rectangle((0, 0, BAR_W - 1, BAR_H - 1), outline=BAR_EDGE, width=2)
    strip = Image.new("RGBA", (2 * BAR_W, BAR_H - 6), (0, 0, 0, 0))
    ImageDraw.Draw(strip).rectangle((0, 0, BAR_W - 7, BAR_H - 7), fill=BAR_FILL)
    paths = os.path.join(tmp, "bar_frame.png"), os.path.join(tmp, "bar_fill.png")
    frame.save(paths[0]); strip.save(paths[1])
    return paths


HUD = None
def icon(key):
    """Weapon icon (d_<weapon>) in the CS orange, or None if the game has no icon of that name."""
    global HUD
    HUD = HUD or hud_sprites()
    if key not in HUD:
        return None
    spr, x, y, w, h = HUD[key]
    a = sprite(spr).crop((x, y, x + w, y + h)).point(lambda v: min(255, int(v * 1.6)))
    a = a.resize((w * ICON_SCALE, h * ICON_SCALE), Image.NEAREST)
    img = Image.new("RGBA", a.size, ICON_COLOR + (0,))
    img.putalpha(a)
    return img

FONT_OBJ = None
def row_image(k, featured):
    global FONT_OBJ
    FONT_OBJ = FONT_OBJ or ImageFont.truetype(FONT, FONT_SIZE)
    parts = []  # (kind, value, colour)
    if k["k"]:
        parts.append(("text", k["kn"], T_COLOR if k["kt"] == 1 else CT_COLOR))
    weapon = icon("d_" + k["w"]) or icon("d_skull")
    parts.append(("img", weapon, None) if weapon else ("text", k["w"], ICON_COLOR))
    if k["hs"] and icon("d_headshot"):
        parts.append(("img", icon("d_headshot"), None))
    parts.append(("text", k["vn"], T_COLOR if k["vt"] == 1 else CT_COLOR))
    pad_x, pad_y, gap = 16, 8, 12
    sizes = []
    for kind, v, _ in parts:
        if kind == "text":
            b = FONT_OBJ.getbbox(v)
            sizes.append((b[2] - b[0], FONT_SIZE))
        else:
            sizes.append(v.size)
    h = max(s[1] for s in sizes) + 2 * pad_y
    w = sum(s[0] for s in sizes) + gap * (len(parts) - 1) + 2 * pad_x
    blur = 6
    img = Image.new("RGBA", (w + 2 * blur, h + 2 * blur), (0, 0, 0, 0))
    # Soft dark background: a rounded box with blurred edges.
    bg = Image.new("L", img.size, 0)
    ImageDraw.Draw(bg).rounded_rectangle((blur, blur, blur + w, blur + h), radius=h // 2, fill=150)
    bg = bg.filter(ImageFilter.GaussianBlur(blur / 2))
    img.paste(Image.new("RGBA", img.size, (0, 0, 0, 255)), mask=bg)
    if featured and k["k"] == featured:   # the featured player's own kills get a thin light outline, like CS
        ImageDraw.Draw(img).rounded_rectangle((blur, blur, blur + w, blur + h), radius=h // 2, outline=(255, 255, 255, 140), width=2)
    draw = ImageDraw.Draw(img)
    x = blur + pad_x
    for (kind, v, colour), (sw, sh) in zip(parts, sizes):
        if kind == "text":
            b = FONT_OBJ.getbbox(v)
            draw.text((x - b[0], blur + (h - FONT_SIZE) // 2 - b[1] + 2), v, font=FONT_OBJ, fill=colour + (255,),
                      stroke_width=2, stroke_fill=(0, 0, 0, 200))
        else:
            img.alpha_composite(v, (x, blur + (h - sh) // 2))
        x += sw + gap
    return img.resize((round(img.width * FEED_SCALE), round(img.height * FEED_SCALE)), Image.LANCZOS)

SYNC_WINDOW = 0.5        # demo seconds: markers reach the console in bursts, some up to ~0.4 s late (never early)


def steady(sync, window=SYNC_WINDOW):
    """``sync`` with each marker's lateness taken out: its video time becomes its demo time plus the smallest
    (video - demo) offset among the markers within ``window`` demo seconds of it."""
    pts = sorted(sync, key=lambda p: p[1])
    return [(d + min(v2 - d2 for v2, d2 in pts if abs(d2 - d) <= window), d) for _, d in pts]


def video_time(sync, t):
    """Video time of demo time ``t``, interpolated between the (video time, demo time) markers in ``sync``; one demo
    second per video second before the first and after the last."""
    pts = sorted(sync, key=lambda p: p[1])
    if t <= pts[0][1]:
        return pts[0][0] + t - pts[0][1]
    for (v0, d0), (v1, d1) in zip(pts, pts[1:]):
        if t <= d1:
            return v0 + (v1 - v0) * (t - d0) / (d1 - d0) if d1 > d0 else v1
    return pts[-1][0] + t - pts[-1][1]


def feed_states(kills, start, length, offset, featured, tmp, sync=None):
    """PNG overlays of the kill feed and the time range each one is on screen (clip seconds). With ``sync`` (from
    render.record) each kill is placed on the frame it happens on, otherwise at its demo time plus ``offset``."""
    if sync and len(sync) >= 2:
        sync = steady(sync)
        shown = [dict(k, at=video_time(sync, k["t"]) + FEED_LEAD) for k in kills]
    else:
        shown = [dict(k, at=k["t"] - start + offset) for k in kills]
    shown = [k for k in shown if -FEED_TIME < k["at"] < length]
    edges = sorted({0.0, length} | {max(0.0, k["at"]) for k in shown} | {k["at"] + FEED_TIME for k in shown if k["at"] + FEED_TIME < length})
    states, rows_cache = [], {}
    for a, b in zip(edges, edges[1:]):
        mid = (a + b) / 2
        rows = [k for k in shown if k["at"] <= mid < k["at"] + FEED_TIME][-MAX_ROWS:]
        if not rows:
            continue
        imgs = []
        for k in rows:
            key = (k["t"], k["k"], k["v"])
            rows_cache[key] = rows_cache.get(key) or row_image(k, featured)
            imgs.append(rows_cache[key])
        gap = round(ROW_GAP * FEED_SCALE)
        canvas = Image.new("RGBA", (1080, sum(i.height for i in imgs) + gap * len(imgs)), (0, 0, 0, 0))
        y = 0
        for i in imgs:
            canvas.alpha_composite(i, (1080 - i.width - 10, y))
            y += i.height + gap
        path = os.path.join(tmp, f"feed{len(states):03d}.png")
        canvas.save(path)
        states.append((a, b, path))
    return states

# ---- the band above the gameplay -----------------------------------------------------------------------------------
# The only part of the frame that TikTok, Reels and Shorts all leave uncovered: below their top tabs (~250 px) and
# above the gameplay. Their captions cover the bottom ~450 px and their buttons the right edge of the lower half, so
# the logo lives here too. Drawn once as a picture; the kill dots are pictures switched on as each kill happens.
BAND_FONT = next((p for p in ("/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
                              "C:/Windows/Fonts/bahnschrift.ttf", FONT) if os.path.exists(p)), FONT)
TEXT_FONT = next((p for p in (FONT, "C:/Windows/Fonts/arialbd.ttf") if os.path.exists(p)), FONT)
SAND, BAND_WHITE, BAND_MUTED = (240, 184, 92), (255, 255, 255), (225, 222, 215)
BAND_X = 64              # side margin
BAND_TOP = 236           # first line; the apps' top tabs end above this


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def headline(moments, player):
    """(headline parts, details line) for a clip's moments: the parts are (text, accent) pairs, the accent drawn in
    sand, and the details line is the player. The moment with the highest score names the clip. Kept short: the
    kill dots count the kills and the post text carries the rest. The weapon shows only when it is the knife."""
    m = max(moments, key=lambda x: x.get("score", 0))
    kills = int(m.get("kills") or 0)
    tags = set((m.get("extra") or "").split())
    knife = set((m.get("weapons") or "").split()) == {"knife"}
    kind = m.get("type")
    if kind == "clutch":
        parts = [(f"1v{int(m.get('enemies') or 0)}", True), (" CLUTCH", False)]
    elif kind == "multikill" and streak_name(kills):
        parts = [(streak_name(kills).upper(), True)] + ([(" · KNIFE", False)] if knife else [])
    elif kind == "multikill":
        parts = [(str(kills), True), (" KNIFE KILLS" if knife else " KILLS", False)]
    elif "noscope" in tags:
        parts = [("NO-SCOPE", True)]
    elif "double" in tags:
        parts = [("2 FOR 1", True)]
    elif "air" in tags:
        parts = [("MID-AIR", True), (" KILL", False)]
    else:
        parts = [("KNIFE", True), (" KILL", False)] if knife else [("KILL", True)]
    return parts, player


def _fit(draw, parts, path, size, width, smallest=40):
    """The largest font from ``size`` down (in steps of 2) that fits ``parts`` into ``width``, but not below
    ``smallest``."""
    while size > smallest:
        f = _font(path, size)
        if sum(draw.textlength(t, font=f) for t, _ in parts) <= width:
            return f
        size -= 2
    return _font(path, smallest)


def _clip_text(draw, text, font, width):
    """``text`` cut short with "…" so it fits ``width``."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip(" ·") + "…"


DOTS_W = 230             # room kept on the right of the headline for the kill dots
DOTS_LABEL_W = 130       # and on the right of the details line for their "3 / 4"
LOGO_SIZE = 116


def play_y(game_top):    # top of the play's line (the headline), above the details line
    return game_top - 128


def _shadowed(d, xy, text, font, fill):
    d.text((xy[0] + 3, xy[1] + 4), text, font=font, fill=(0, 0, 0, 150))
    d.text(xy, text, font=font, fill=fill)


def map_line(map_name):
    """The line under the server name: the clip's map ("de_dust2" -> "DUST2") and the server's age."""
    name = (map_name or "").split("_", 1)[-1].upper()
    return f"{name} · SINCE 2013" if name else "SINCE 2013"


def band_image(parts, details, game_top, logo=LOGO, map_name="de_dust2"):
    """The band above the gameplay (1080 x ``game_top``): a soft dark shade, the logo and server line (with the
    clip's map), the headline and the details line."""
    img = Image.new("RGBA", (1080, game_top), (0, 0, 0, 0))
    shade = Image.new("L", img.size, 0)
    ImageDraw.Draw(shade).rectangle((0, max(0, BAND_TOP - 30), 1080, game_top), fill=150)
    shade = shade.filter(ImageFilter.GaussianBlur(30))
    img.paste(Image.new("RGBA", img.size, (0, 0, 0, 255)), mask=shade)
    d = ImageDraw.Draw(img)
    # The server is the big line (the logo and its name), the play a smaller one under it.
    text_x = BAND_X
    if logo and os.path.exists(logo):
        lg = Image.open(logo).convert("RGBA")
        lg.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
        img.alpha_composite(lg, (BAND_X, BAND_TOP))
        text_x = BAND_X + LOGO_SIZE + 22
    name = _fit(d, [("ARABIAN SERVERS", False)], BAND_FONT, 92, 1080 - BAND_X - text_x)
    _shadowed(d, (text_x, BAND_TOP - 8), "ARABIAN SERVERS", name, BAND_WHITE)
    d.text((text_x + 2, BAND_TOP + 86), map_line(map_name), font=_font(TEXT_FONT, 26), fill=SAND)
    play = _fit(d, parts, BAND_FONT, 60, 1080 - 2 * BAND_X - DOTS_W)
    x = BAND_X
    for text, accent in parts:
        _shadowed(d, (x, play_y(game_top)), text, play, SAND if accent else BAND_WHITE)
        x += d.textlength(text, font=play)
    room = 1080 - 2 * BAND_X - DOTS_LABEL_W     # the dots' "3 / 4" sits at the right end of this line
    small = _fit(d, [(details, False)], TEXT_FONT, 32, room, smallest=24)
    d.text((BAND_X, game_top - 50), _clip_text(d, details, small, room), font=small, fill=BAND_MUTED)
    return img


def dots_image(filled, total, game_top):
    """The kill dots, right of the headline: ``filled`` of ``total`` filled, with "filled / total" under them."""
    img = Image.new("RGBA", (1080, game_top), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r, gap = 17, 14
    if total > 6:      # many kills: smaller dots so they keep to their corner
        r, gap = 12, 8
    x0 = 1080 - BAND_X - total * 2 * r - (total - 1) * gap
    y = play_y(game_top) + 14
    for i in range(total):
        box = (x0 + i * (2 * r + gap), y, x0 + i * (2 * r + gap) + 2 * r, y + 2 * r)
        if i < filled:
            d.ellipse(box, fill=SAND)
        else:
            d.ellipse(box, outline=(255, 255, 255, 200), width=4)
    f = _font(TEXT_FONT, 28)
    label = f"{filled} / {total}"
    d.text((1080 - BAND_X - d.textlength(label, font=f), game_top - 48), label, font=f, fill=BAND_MUTED)
    return img


def kill_times(kills, start, offset, sync=None):
    """Clip seconds at which each kill shows, timed exactly like the kill feed."""
    if sync and len(sync) >= 2:
        s = steady(sync)
        return [video_time(s, k["t"]) + FEED_LEAD for k in kills]
    return [k["t"] - start + offset for k in kills]


def dot_states(times, length, game_top, tmp):
    """(from, to, png) for each count of filled dots: none until the first kill, then one more at each kill."""
    times = sorted(t for t in times if 0 <= t < length)
    total = len(times)
    if total < 2:       # a single kill needs no counter
        return []
    edges = [0.0] + times + [length]
    states = []
    for n, (a, b) in enumerate(zip(edges, edges[1:])):
        if b <= a:
            continue
        path = os.path.join(tmp, f"dots{n:02d}.png")
        dots_image(n, total, game_top).save(path)
        states.append((a, b, path))
    return states


def next_kbps(kbps, size):
    """The video bitrate for another try after a Discord copy of ``size`` bytes came out over DISCORD_BYTES:
    lowered in proportion, plus 3% to spare (x264 overshoots hard clips by about 2%)."""
    return max(300, int(kbps * DISCORD_BYTES / size * 0.97))


def discord_copy(hq, dc, length, log):
    """Make ``dc`` (720x1280) from ``hq`` in two passes, aiming at DISCORD_BYTES. A copy that comes out bigger is made
    again at a lower bitrate, up to DISCORD_TRIES encodes in all. Returns the video bitrate used (kbps)."""
    kbps = max(300, int((DISCORD_BYTES * 8 / length) / 1000) - AUDIO_KBPS - 40)
    for attempt in range(DISCORD_TRIES):
        common = ["-vf", "scale=720:1280:flags=lanczos", "-c:v", "libx264", "-preset", "medium",
                  "-b:v", f"{kbps}k", "-pix_fmt", "yuv420p"]
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", hq, *common, "-pass", "1",
                        "-passlogfile", log, "-an", "-f", "null", "-"], check=True)
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", hq, *common, "-pass", "2",
                        "-passlogfile", log, "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-movflags", "+faststart", dc],
                       check=True)
        size = os.path.getsize(dc)
        if size <= DISCORD_BYTES or kbps <= 300:
            return kbps
        if attempt < DISCORD_TRIES - 1:
            kbps = next_kbps(kbps, size)
    return kbps


def compose(raw, kills, start, out_dir, featured=0, offset=KILL_FEED_DELAY, sync=None, bar_hidden=True,
            zooms=(), bars=(), band=None):
    """Make out_dir/hq.mp4 and out_dir/discord.mp4 from ``raw``, recorded from demo time ``start``.
    ``kills``: the demo's kill lines (clips.demo.scan); ``sync``: render.record's markers, for the kill feed's timing;
    ``bar_hidden``: whether the spectator top bar was hidden while recording (picks the framing); ``zooms``: the
    player's (demo time, fov) zoom changes (clips.demo.overlays), for the sniper scope's crosshair; ``bars``: the
    player's plant/defuse progress bars (clips.demo.overlays); ``band``: {"moments", "player", "map"} for the
    headline band above the gameplay, with the logo in it (without it, the logo goes bottom right as before).
    Returns (hq path, discord path)."""
    os.makedirs(out_dir, exist_ok=True)
    length = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                            "-of", "csv=p=0", raw]))
    tmp = tempfile.mkdtemp(prefix="clip-")
    try:
        states = feed_states(kills, start, length, offset, featured, tmp, sync)
        inputs = ["-i", raw, "-i", LOGO]
        for _, _, p in states:
            inputs += ["-i", p]
        crop, game_w, _, game_top = framing(bar_hidden)
        steady_sync = steady(sync) if sync and len(sync) >= 2 else None
        to_video = (lambda t: video_time(steady_sync, t)) if steady_sync else (lambda t: t - start)
        scoped = scope_ranges(zooms, length, to_video)
        shown_bars = bar_ranges(bars, length, to_video)
        f, last, n = "", "0:v", len(states) + 2      # n: the next input number
        if scoped:
            scope = os.path.join(tmp, "scope.png")
            scope_image().save(scope)
            inputs += ["-i", scope]
            on = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in scoped)
            f += f"[{last}][{n}:v]overlay=(W-w)/2:(H-h)/2:enable='{on}'[sc];"
            last, n = "sc", n + 1
        if shown_bars:
            frame_png, fill_png = bar_images(tmp)
            for i, (a, b, secs, pct) in enumerate(shown_bars):
                inputs += ["-loop", "1", "-i", frame_png, "-loop", "1", "-i", fill_png]
                done = f"({pct}/100+(t-{a:.3f})/{secs * 1.0:.3f})"
                f += (f"[{n + 1}:v]crop={BAR_W}:{BAR_H - 6}:x='{BAR_W}*(1-min(1,max(0,{done})))':y=0[fill{i}];"
                      f"[{last}][{n}:v]overlay={BAR_X}:{BAR_Y}:enable='between(t,{a:.3f},{b:.3f})'[bf{i}];"
                      f"[bf{i}][fill{i}]overlay={BAR_X + 3}:{BAR_Y + 3}:enable='between(t,{a:.3f},{b:.3f})'[bar{i}];")
                last, n = f"bar{i}", n + 2
        f += (f"[{last}]crop={crop},split=2[g1][g2];"
             f"[g1]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=40:10[bg];"
             f"[g2]scale={game_w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[b0];")
        for i, (s, e, _) in enumerate(states):
            f += f"[b{i}][{i + 2}:v]overlay=0:{game_top + 12}:enable='between(t,{s:.3f},{e:.3f})'[b{i + 1}];"
        last = f"b{len(states)}"
        if band:
            parts, details = headline(band["moments"], band["player"])
            band_png = os.path.join(tmp, "band.png")
            band_image(parts, details, game_top, map_name=band.get("map") or "de_dust2").save(band_png)
            inputs += ["-i", band_png]
            f += f"[{last}][{n}:v]overlay=0:0[top];"
            last, n = "top", n + 1
            mine = [k for k in kills if featured and k["k"] == featured]
            for i, (a, b, p) in enumerate(dot_states(kill_times(mine, start, offset, sync), length, game_top, tmp)):
                inputs += ["-i", p]
                f += f"[{last}][{n}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[dots{i}];"
                last, n = f"dots{i}", n + 1
            f += f"[{last}]null[v];"
        else:
            f += f"[1:v]scale=230:-1[logo];[{last}][logo]overlay=W-w-30:H-h-45[v];"
        f += "[0:a]alimiter=limit=0.89:level=false[a]"
        hq = os.path.join(out_dir, "hq.mp4")
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *inputs, "-filter_complex", f,
                        "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-r", "60", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                        "-movflags", "+faststart", hq], check=True)
        dc = os.path.join(out_dir, "discord.mp4")
        discord_copy(hq, dc, length, os.path.join(tmp, "pass"))
        return hq, dc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
