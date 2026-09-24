from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

import discord
from PIL import Image, ImageDraw

from cogs.server_management import ServerManagement
from utils.leaderboard_image import render_leaderboard, fit_name, font
from utils.server_management import member_profile


class ImageTests(TestCase):
    def test_full_board_and_empty_season_are_valid_bounded_pngs(self):
        rows = [{"Rank": i + 1, "Name": "لاعب عربي " + "Long name " * 20,
                 "Kills": 11566 - i, "Deaths": 5019, "Headshots": 2652} for i in range(50)]
        for players in (rows, []):
            data = render_leaderboard(players, datetime.now(timezone.utc))
            self.assertLess(len(data), 8 * 1024 * 1024)
            image = Image.open(BytesIO(data))
            self.assertEqual(image.size, (1800, 1700))
            image.verify()

    def test_long_name_is_fitted_to_its_column(self):
        draw = ImageDraw.Draw(Image.new("RGB", (400, 100)))
        face = font(26)
        name = fit_name(draw, "لاعب عربي " * 40, face, 350)
        self.assertLessEqual(draw.textlength(name, font=face), 350)
        self.assertTrue(name.endswith("…"))

    def test_departed_member_keeps_a_named_profile_link(self):
        link = member_profile(SimpleNamespace(id=123, display_name="Nabeel"))
        self.assertEqual(link, "[Nabeel](https://discord.com/users/123)")


class RoleLogTests(IsolatedAsyncioTestCase):
    async def test_position_only_update_is_silent_but_permissions_still_log(self):
        cog = ServerManagement(SimpleNamespace())
        cog.send_log = AsyncMock()
        common = dict(id=1, name="Member", colour=discord.Colour.default(),
                      hoist=False, mentionable=False, guild=SimpleNamespace(id=100))
        before = SimpleNamespace(**common, position=10, permissions=discord.Permissions.none())
        after = SimpleNamespace(**common, position=11, permissions=discord.Permissions.none())
        await cog.on_guild_role_update(before, after)
        cog.send_log.assert_not_awaited()
        after.permissions = discord.Permissions(manage_messages=True)
        await cog.on_guild_role_update(before, after)
        cog.send_log.assert_awaited_once()
