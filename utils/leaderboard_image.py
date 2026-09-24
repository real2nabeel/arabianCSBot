"""Render a complete season leaderboard as a single Discord attachment."""
from io import BytesIO
from pathlib import Path
import unicodedata

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

BACKGROUND = "#14171f"
SURFACE = "#1d2230"
TEXT = "#f2f4f8"
MUTED = "#aab4c7"
GOLD = "#f3b955"


def font(size, bold=False):
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    windows = "arialbd.ttf" if bold else "arial.ttf"
    for path in (Path("/usr/share/fonts/truetype/dejavu") / filename,
                 Path("C:/Windows/Fonts") / windows):
        if path.is_file():
            # Shape names explicitly for identical Windows/Linux rendering.
            return ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)
    raise RuntimeError("Leaderboard font missing: install fonts-dejavu-core")


def fit_name(draw, name, face, width):
    name = "".join(c for c in str(name or "Unknown") if not unicodedata.category(c).startswith("C"))[:256]
    name = get_display(arabic_reshaper.reshape(name))
    if draw.textlength(name, font=face) <= width:
        return name
    while name and draw.textlength(name + "…", font=face) > width:
        name = name[:-1]
    return name + "…"


def render_leaderboard(players, updated_at):
    """Wide 1800x1050 graphic; caller runs this CPU work outside the event loop."""
    players = players[:50]
    image = Image.new("RGB", (1800, 1050), BACKGROUND)
    draw = ImageDraw.Draw(image)
    small, body, bold = font(24), font(30), font(30, True)
    draw.rectangle((0, 0, 1800, 8), fill=GOLD)
    draw.text((50, 32), "DD2 · TOP 50", font=font(48, True), fill=TEXT)
    draw.text((1750, 49), "SEASON LEADERBOARD", font=small, fill=MUTED, anchor="ra")

    for column in range(2):
        x = 50 + column * 880
        # Names last so Arabic names cannot reorder adjacent numeric columns.
        for right, label in ((42, "#"), (178, "KILLS"), (310, "DEATHS"), (424, "HS")):
            draw.text((x + right, 110), label, font=small, fill=MUTED, anchor="ra")
        draw.text((x + 452, 110), "PLAYER", font=small, fill=MUTED)
        for index, player in enumerate(players[column * 25:(column + 1) * 25]):
            y = 152 + index * 33
            if index % 2 == 0:
                draw.rounded_rectangle((x - 10, y - 2, x + 820, y + 30), radius=4, fill=SURFACE)
            draw.text((x + 42, y), str(player["Rank"]), font=bold,
                      fill=GOLD if player["Rank"] <= 3 else MUTED, anchor="rt")
            for right, key in ((178, "Kills"), (310, "Deaths"), (424, "Headshots")):
                value = f"{player[key]:,}"
                face = body
                size = 30
                while draw.textlength(value, font=face) > 104 and size > 12:
                    size -= 1
                    face = font(size)
                draw.text((x + right, y), value, font=face, fill=TEXT, anchor="rt")
            draw.text((x + 452, y), fit_name(draw, player["Name"], body, 360), font=body, fill=TEXT, anchor="lt")
    if not players:
        draw.text((900, 485), "A new season awaits.", font=font(45, True), fill=TEXT, anchor="mm")
        draw.text((900, 550), "Join the server and claim your place.", font=font(30), fill=MUTED, anchor="mm")
    draw.line((50, 990, 1750, 990), fill="#323b4e", width=2)
    draw.text((50, 1008), "arabian-servers.com", font=small, fill=GOLD)
    draw.text((1750, 1008), f"Updated {updated_at:%d %b %Y · %H:%M} UTC",
              font=small, fill=MUTED, anchor="ra")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
