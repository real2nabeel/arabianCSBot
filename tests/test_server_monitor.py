"""Population boundary, outage, delivery, and role subscription checks."""
import asyncio
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands

from utils.server_monitor import ActivityWindow, human_count
from cogs.server_monitor import ServerMonitor, SERVER_KEY


class PopulationTests(TestCase):
    def test_humans_exclude_bots_and_invalid_counts_are_unknown(self):
        self.assertEqual(human_count(SimpleNamespace(player_count=22, bot_count=7, max_players=32)), 15)
        for info in (None, SimpleNamespace(player_count=15),
                     SimpleNamespace(player_count=14, bot_count=15, max_players=32),
                     SimpleNamespace(player_count=35, bot_count=0, max_players=32)):
            self.assertIsNone(human_count(info))

    def observe(self, window, humans, now, armed=True, last_alert=0):
        return window.observe(humans, now=now, wall_time=10000 + now,
                              armed=armed, last_alert=last_alert)

    def test_exact_fifteen_and_two_minutes(self):
        window = ActivityWindow()
        for now in (0, 30, 60, 90):
            self.assertIsNone(self.observe(window, 15, now))
        self.assertEqual(self.observe(window, 15, 120), "alert")

    def test_drop_resets_sustain(self):
        window = ActivityWindow()
        for humans, now in ((15, 0), (15, 30), (14, 60), (15, 90), (15, 120), (15, 150), (15, 180)):
            self.assertIsNone(self.observe(window, humans, now))
        self.assertEqual(self.observe(window, 15, 210), "alert")

    def test_failed_query_or_long_gap_does_not_count_as_sustain(self):
        for middle in (None, 15):
            window = ActivityWindow()
            self.observe(window, 15, 0)
            self.observe(window, middle, 30)
            self.assertIsNone(self.observe(window, 15, 150))

    def test_rearm_is_strictly_below_four_for_five_minutes(self):
        window = ActivityWindow()
        for now in range(0, 330, 30):
            self.assertIsNone(self.observe(window, 4, now, armed=False))
        for now in range(330, 630, 30):
            self.assertIsNone(self.observe(window, 3, now, armed=False))
        self.assertEqual(self.observe(window, 3, 630, armed=False), "rearm")

    def test_outage_does_not_rearm(self):
        window = ActivityWindow()
        for now in range(0, 360, 30):
            self.assertIsNone(self.observe(window, None, now, armed=False))

    def test_busy_session_never_repeats_and_restart_keeps_cooldown(self):
        window = ActivityWindow()
        for now in range(0, 360, 30):
            self.assertIsNone(self.observe(window, 20, now, armed=False))
        window = ActivityWindow()  # restart: timers reset, DB cooldown retained
        for now in range(0, 150, 30):
            self.assertIsNone(self.observe(window, 15, now, last_alert=10000))

    def test_cooldown_boundary_after_rearm(self):
        window = ActivityWindow()
        for now in (0, 30, 60, 90):
            self.assertIsNone(self.observe(window, 15, now, last_alert=2920))
        self.assertEqual(self.observe(window, 15, 120, last_alert=2920), "alert")


class MonitorTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = SimpleNamespace(claim_server_alert=AsyncMock(return_value=True),
                                  set_monitor_message=AsyncMock())
        self.bot = SimpleNamespace(db_bot=self.db, user=SimpleNamespace(id=88))
        self.cog = ServerMonitor(self.bot)

    async def test_claim_precedes_targeted_ping(self):
        role = SimpleNamespace(id=55, mention="<@&55>", mentionable=False, is_default=lambda: False)
        guild = SimpleNamespace(me=Mock(), get_role=Mock(return_value=role))
        channel = SimpleNamespace(guild=guild, send=AsyncMock(), permissions_for=Mock(
            return_value=discord.Permissions.all()))
        self.cog.channel = Mock(return_value=channel)
        self.cog.window.observe = Mock(return_value="alert")
        info = SimpleNamespace(map_name="de_dust2", player_count=22, max_players=32)
        with patch("cogs.server_monitor.GUILD_ID", 100):
            await self.cog.activity({"armed": 1, "last_alert": 0}, info, 15, 120)
            kwargs = channel.send.call_args.kwargs
            self.assertEqual(kwargs["content"], "<@&55>")
            self.assertEqual(kwargs["allowed_mentions"].to_dict()["roles"], [55])
            self.assertEqual(kwargs["allowed_mentions"].to_dict()["parse"], [])
            channel.send.reset_mock()
            self.db.claim_server_alert.return_value = False
            await self.cog.activity({"armed": 1, "last_alert": 0}, info, 15, 120)
            channel.send.assert_not_awaited()

    async def test_enabled_extension_starts_and_unloads_without_network(self):
        async with commands.Bot(command_prefix="!", intents=discord.Intents.none()) as bot:
            bot.db_bot = SimpleNamespace(ensure_server_monitor_schema=AsyncMock(), ensure_leaderboard_schema=AsyncMock())
            with patch("cogs.server_monitor.GUILD_ID", 100), \
                 patch("cogs.server_monitor.DASHBOARD_CHANNEL_ID", 99), \
                 patch("cogs.server_monitor.ACTIVITY_ALERT_CHANNEL_ID", 0):
                cog = ServerMonitor(bot)
                await bot.add_cog(cog)
                bot.db_bot.ensure_server_monitor_schema.assert_awaited_once()
                self.assertTrue(cog.poll.is_running())
                self.assertFalse(hasattr(cog, "view"))
                await bot.remove_cog("ServerMonitor")
                await asyncio.sleep(0)
                self.assertTrue(cog.poll.get_task().cancelled())

    async def test_existing_dashboard_is_edited_not_reposted(self):
        message = SimpleNamespace(id=77, author=self.bot.user, pinned=True, edit=AsyncMock())
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message), send=AsyncMock())
        self.cog.channel = Mock(return_value=channel)
        await self.cog.update_message({"dashboard_id": 77}, "dashboard_id", 99, self.cog.dashboard_embed(None))
        message.edit.assert_awaited_once()
        channel.send.assert_not_awaited()

    async def test_missing_dashboard_is_recreated_and_saved(self):
        message = SimpleNamespace(id=78, author=self.bot.user, pinned=True)
        response = SimpleNamespace(status=404, reason="Not found")
        channel = SimpleNamespace(fetch_message=AsyncMock(side_effect=discord.NotFound(response, "missing")),
                                  send=AsyncMock(return_value=message))
        self.cog.channel = Mock(return_value=channel)
        await self.cog.update_message({"dashboard_id": 77}, "dashboard_id", 99, self.cog.dashboard_embed(None))
        self.assertEqual(self.db.set_monitor_message.call_args.args[1:], (SERVER_KEY, "dashboard_id", 78))

    async def test_old_panel_deleted_and_cleared(self):
        message = SimpleNamespace(author=self.bot.user, delete=AsyncMock())
        self.cog.channel = Mock(return_value=SimpleNamespace(fetch_message=AsyncMock(return_value=message)))
        with patch("cogs.server_monitor.ACTIVITY_ALERT_CHANNEL_ID", 99):
            await self.cog.remove_old_panel({"panel_id": 77})
        message.delete.assert_awaited_once()
        self.assertEqual(self.db.set_monitor_message.call_args.args[-2:], ("panel_id", None))

    async def test_leaderboard_replaces_attachment_then_skips_unchanged_data(self):
        self.db.get_leaderboard_message = AsyncMock(return_value={"message_id": 77})
        self.db.set_leaderboard_message = AsyncMock()
        players = [{"Rank": 1, "Name": "Falcon", "Kills": 100, "Deaths": 10, "Headshots": 40}]
        self.bot.db_live = SimpleNamespace(get_top_players=AsyncMock(return_value=(players, 1)))
        message = SimpleNamespace(id=77, author=self.bot.user, edit=AsyncMock())
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message), send=AsyncMock())
        self.cog.channel = Mock(return_value=channel)
        with patch("cogs.server_monitor.render_leaderboard", return_value=b"png") as render:
            await self.cog.update_leaderboard()
            await self.cog.update_leaderboard()
            render.assert_called_once()
        message.edit.assert_awaited_once()
        self.assertEqual(len(message.edit.call_args.kwargs["attachments"]), 1)
        self.assertIsNone(message.edit.call_args.kwargs["embed"])
        self.assertEqual(message.edit.call_args.kwargs["content"], "**🏆 DD2 · Top 50**")
        self.assertIsNone(message.edit.call_args.kwargs["view"])
        channel.send.assert_not_awaited()

    def test_offline_card_does_not_show_stale_map_or_count(self):
        self.cog.last_success = 10000
        embed = self.cog.dashboard_embed(None)
        self.assertEqual(embed.fields[0].value, "Unavailable")
        self.assertEqual(embed.fields[1].value, "Unavailable")
        self.assertIn("unreachable", embed.description)
