"""Turning a raw 1920x1080 spectator recording into the finished clip files.

Layout from ClipsPipeline/format_clips.bat: gameplay 1680 wide over a blurred copy, logo 230 px bottom-right.
The spectator bars are cropped off and the game's own kill feed (which HLTV playback can't hide and the crop cuts
off) is replaced by ours: drawn from the demo's "[clips] kill" lines in CS style with the game's own weapon icons,
each line on a soft dark background. Writes hq.mp4 (1080x1920 60 fps, for social media) and discord.mp4
(720x1280, under 9.5 MB: made again at a lower bitrate if it comes out bigger).
"""
import os, shutil, struct, subprocess, tempfile
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HL = os.path.join(os.path.expanduser(os.environ.get("CLIPS_HL_DIR", "~/.steam/debian-installation/steamapps/common/Half-Life")), "cstrike")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host", "logo.png")
T_COLOR, CT_COLOR, ICON_COLOR = (255, 80, 80), (153, 204, 255), (255, 150, 30)
FEED_TIME, MAX_ROWS = 6.0, 4          # CS shows a kill for 6 seconds, 4 at most
ICON_SCALE, FONT_SIZE, ROW_GAP = 2, 30, 8
FEED_SCALE = 0.65                     # rows are drawn at the sizes above, then shrunk to this (about CS's own size)
GAME_W, GAME_TOP = 1680, (1920 - 693) // 2   # gameplay width and top in the 1080x1920 frame
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


def compose(raw, kills, start, out_dir, featured=0, offset=KILL_FEED_DELAY, sync=None):
    """Make out_dir/hq.mp4 and out_dir/discord.mp4 from ``raw``, recorded from demo time ``start``.
    ``kills``: the demo's kill lines (clips.demo.scan); ``sync``: render.record's markers, for the kill feed's timing.
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
        f = (f"[0:v]crop=1920:792:0:144,split=2[g1][g2];"
             f"[g1]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=40:10[bg];"
             f"[g2]scale={GAME_W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[b0];")
        for i, (s, e, _) in enumerate(states):
            f += f"[b{i}][{i + 2}:v]overlay=0:{GAME_TOP + 12}:enable='between(t,{s:.3f},{e:.3f})'[b{i + 1}];"
        f += (f"[1:v]scale=230:-1[logo];[b{len(states)}][logo]overlay=W-w-30:H-h-45[v];"
              f"[0:a]alimiter=limit=0.89:level=false[a]")
        hq = os.path.join(out_dir, "hq.mp4")
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *inputs, "-filter_complex", f,
                        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-r", "60", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                        "-movflags", "+faststart", hq], check=True)
        dc = os.path.join(out_dir, "discord.mp4")
        discord_copy(hq, dc, length, os.path.join(tmp, "pass"))
        return hq, dc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
