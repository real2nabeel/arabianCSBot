"""Server activity graph and admin activity tracking."""
from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

import discord
from PIL import Image

from cogs.server_monitor import ServerMonitor, SERVER_KEY
from utils.activity import (
    PERIODS, AdminTracker, admin_rows, build_series, day_key, format_admin_table,
    format_ago, format_hours, render_activity_graph,
)


class TrackerTests(TestCase):
    def test_only_admins_present_at_both_polls_are_credited(self):
        tracker = AdminTracker(max_gap=70)
        self.assertEqual(tracker.observe({"A", "B"}, 0), (0, set()))
        self.assertEqual(tracker.observe({"A", "C"}, 30), (30, {"A"}))
        self.assertEqual(tracker.observe({"A", "C"}, 60), (30, {"A", "C"}))

    def test_outage_failed_query_and_long_gap_credit_nothing(self):
        tracker = AdminTracker(max_gap=70)
        tracker.observe({"A"}, 0)
        self.assertEqual(tracker.observe(None, 30), (0, set()))
        self.assertEqual(tracker.observe({"A"}, 60), (0, set()))
        self.assertEqual(tracker.observe({"A"}, 200), (0, set()))
        self.assertEqual(tracker.observe({"A"}, 230), (30, {"A"}))

    def test_day_uses_configured_offset(self):
        moment = datetime(2026, 11, 14, 22, 30, tzinfo=timezone.utc).timestamp()
        self.assertEqual(day_key(moment, 0), date(2026, 11, 14))
        self.assertEqual(day_key(moment, 3), date(2026, 11, 15))


class SeriesTests(TestCase):
    def test_buckets_distinguish_players_outage_and_missing_data(self):
        period = PERIODS["24h"]
        end = 1_000_000 * 900 + 10
        last = (end + 3 * 3600) // period.bucket
        rows = {last: {"avg": 4.5, "peak": 9, "samples": 30},
                last - 1: {"avg": None, "peak": None, "samples": 0}}
        start, points = build_series(rows, period, end, 3)
        self.assertEqual(len(points), 96)
        self.assertEqual(points[-1], (4.5, 9))
        self.assertEqual(points[-2], "offline")
        self.assertIsNone(points[0])
        self.assertEqual((start + 3 * 3600) % period.bucket, 0)

    def test_graphs_render_for_every_period_with_and_without_data(self):
        updated = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
        for period in PERIODS.values():
            count = period.seconds // period.bucket
            busy = [(i % 20 + 0.5, i % 20 + 3) if i % 17 else "offline" for i in range(count)]
            busy[5] = None
            for points in (busy, [None] * count):
                data = render_activity_graph(points, 1_700_000_000, period, updated, 3)
                image = Image.open(BytesIO(data))
                self.assertEqual(image.size, (1800, 760))
                image.verify()


class AdminTableTests(TestCase):
    def test_rows_sorted_by_recent_hours_and_names_last(self):
        admins = [
            {"steam_id": "S1", "nick": "Quiet", "online": False, "season_seconds": 360000},
            {"steam_id": "S2", "nick": "مشرف عربي", "online": True, "season_seconds": 7200},
            {"steam_id": "S3", "nick": "Never", "online": False, "season_seconds": 0},
        ]
        activity = {"S1": {"week": 0, "month": 5400, "last_seen": 1000},
                    "S2": {"week": 45000, "month": 45000, "last_seen": 99999}}
        rows = admin_rows(admins, activity, now=1000 + 3 * 86400)
        self.assertEqual([r["nick"] for r in rows], ["مشرف عربي", "Quiet", "Never"])
        self.assertEqual(rows[0]["seen"], "online now")
        self.assertEqual(rows[1]["seen"], "3d ago")
        self.assertEqual(rows[2]["seen"], "—")
        lines = format_admin_table(rows).splitlines()
        self.assertTrue(lines[0].endswith("ADMIN"))
        self.assertTrue(lines[1].endswith("مشرف عربي"))
        self.assertIn("12.5h", lines[1])
        widths = {line.index(name) for line, name in zip(lines[1:], ("مشرف", "Quiet", "Never"))}
        self.assertEqual(len(widths), 1)

    def test_formatting(self):
        self.assertEqual(format_hours(0), "0h")
        self.assertEqual(format_hours(5400), "1.5h")
        self.assertEqual(format_hours(360000), "100h")
        self.assertEqual(format_ago(None, 100), "—")
        self.assertEqual(format_ago(0, 100), "—")
        self.assertEqual(format_ago(100, 100 + 600), "10m ago")


class RecordingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_bot = SimpleNamespace(
            add_activity_sample=AsyncMock(), credit_admin_time=AsyncMock(), mark_admins_seen=AsyncMock(),
            get_monitor_message_id=AsyncMock(return_value=None), set_monitor_message_id=AsyncMock(),
        )
        self.admins = [{"steam_id": "STEAM_0:1:1", "nick": "Boss", "online": True, "season_seconds": 10},
                       {"steam_id": "STEAM_0:1:2", "nick": "Away", "online": False, "season_seconds": 10}]
        self.db_live = SimpleNamespace(get_admins=AsyncMock(return_value=self.admins))
        self.bot = SimpleNamespace(db_bot=self.db_bot, db_live=self.db_live, user=SimpleNamespace(id=88))
        self.cog = ServerMonitor(self.bot)

    async def test_offline_poll_records_gap_and_skips_rank_table(self):
        await self.cog.record_players(None, 1000)
        await self.cog.record_admins(None, 1000, 0)
        self.db_bot.add_activity_sample.assert_awaited_once_with(SERVER_KEY, 1000, None)
        self.db_live.get_admins.assert_not_awaited()

    async def test_online_admin_credited_from_second_poll(self):
        info = SimpleNamespace(player_count=10, bot_count=2, max_players=32)
        await self.cog.record_players(info, 1000)
        self.assertEqual(self.db_bot.add_activity_sample.call_args.args, (SERVER_KEY, 1000, 8))
        await self.cog.record_admins(info, 1000, 0)
        self.db_bot.credit_admin_time.assert_not_awaited()
        await self.cog.record_admins(info, 1030, 30)
        args = self.db_bot.credit_admin_time.call_args.args
        self.assertEqual((args[2], args[3]), (30, ["STEAM_0:1:1"]))
        self.assertEqual(self.db_bot.mark_admins_seen.call_args.args[1], [("STEAM_0:1:1", "Boss")])

    async def test_admin_table_refuses_public_channel(self):
        everyone = Mock()
        channel = SimpleNamespace(guild=SimpleNamespace(default_role=everyone),
                                  permissions_for=Mock(return_value=discord.Permissions(view_channel=True)))
        self.cog.channel = Mock(return_value=channel)
        with patch("cogs.server_monitor.ADMIN_ACTIVITY_CHANNEL_ID", 5):
            with self.assertRaises(ValueError):
                await self.cog.post_admin_activity()
        channel.permissions_for.assert_called_once_with(everyone)

    async def test_admin_table_posted_once_then_edited(self):
        self.db_bot.get_admin_activity = AsyncMock(return_value={})
        message = SimpleNamespace(id=55, author=self.bot.user, edit=AsyncMock())
        channel = SimpleNamespace(guild=SimpleNamespace(default_role=Mock()), send=AsyncMock(return_value=message),
                                  fetch_message=AsyncMock(return_value=message),
                                  permissions_for=Mock(return_value=discord.Permissions.none()))
        self.cog.channel = Mock(return_value=channel)
        with patch("cogs.server_monitor.GUILD_ID", 100):
            await self.cog.post_admin_activity()
            await self.cog.post_admin_activity()
        channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        self.db_bot.set_monitor_message_id.assert_awaited_once_with(100, SERVER_KEY, "admin_activity", 55)
        embed = message.edit.call_args.kwargs["embed"]
        self.assertIn("Boss", embed.description)
        self.assertIn("Away", embed.description)
