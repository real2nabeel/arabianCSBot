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
    """Bounded 1800px graphic; caller runs this CPU work outside the event loop."""
    players = players[:50]
    image = Image.new("RGB", (1800, 1700), BACKGROUND)
    draw = ImageDraw.Draw(image)
    small, body, bold = font(23), font(26), font(28, True)
    draw.rectangle((0, 0, 1800, 8), fill=GOLD)
    draw.text((60, 43), "ARABIAN SERVERS", font=font(25, True), fill=GOLD)
    draw.text((60, 89), "DD2 · TOP 50", font=font(65, True), fill=TEXT)
    draw.text((1740, 121), "SEASON LEADERBOARD", font=font(25), fill=MUTED, anchor="ra")

    accents = (GOLD, "#c4d4ea", "#cf986c")
    for index, player in enumerate(players[:3]):
        x = 60 + index * 570
        draw.rounded_rectangle((x, 203, x + 540, 352), radius=14, fill=SURFACE)
        draw.rectangle((x + 20, 225, x + 24, 325), fill=accents[index])
        draw.text((x + 43, 223), f"#{index + 1}", font=font(28, True), fill=accents[index])
        name = fit_name(draw, player["Name"], font(35, True), 445)
        draw.text((x + 43, 265), name, font=font(35, True), fill=TEXT)
        draw.text((x + 43, 313), f"{player['Kills']:,} kills", font=small, fill=MUTED)

    for column in range(2):
        x = 60 + column * 870
        # Names last so Arabic names cannot reorder adjacent numeric columns.
        for right, label in ((42, "#"), (178, "KILLS"), (310, "DEATHS"), (424, "HS")):
            draw.text((x + right, 392), label, font=small, fill=MUTED, anchor="ra")
        draw.text((x + 452, 392), "PLAYER", font=small, fill=MUTED)
        for index, player in enumerate(players[column * 25:(column + 1) * 25]):
            y = 438 + index * 46
            if index % 2 == 0:
                draw.rounded_rectangle((x - 10, y - 4, x + 820, y + 38), radius=5, fill=SURFACE)
            draw.text((x + 42, y), str(player["Rank"]), font=bold,
                      fill=GOLD if player["Rank"] <= 3 else MUTED, anchor="ra")
            for right, key in ((178, "Kills"), (310, "Deaths"), (424, "Headshots")):
                value = f"{player[key]:,}"
                face = body if len(value) <= 7 else font(19)
                draw.text((x + right, y + 2), value, font=face, fill=TEXT, anchor="ra")
            draw.text((x + 452, y + 2), fit_name(draw, player["Name"], body, 350), font=body, fill=TEXT)
    if not players:
        draw.text((900, 750), "A new season awaits.", font=font(45, True), fill=TEXT, anchor="mm")
        draw.text((900, 815), "Join the server and claim your place.", font=font(30), fill=MUTED, anchor="mm")
    draw.line((60, 1623, 1740, 1623), fill="#323b4e", width=2)
    draw.text((60, 1647), "arabian-servers.com", font=small, fill=GOLD)
    draw.text((1740, 1647), f"Updated {updated_at:%d %b %Y · %H:%M} UTC",
              font=small, fill=MUTED, anchor="ra")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
