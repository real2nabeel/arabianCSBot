"""Server activity graph and admin activity tracking."""
from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

import discord
from PIL import Image

from cogs.server_monitor import ServerMonitor, SERVER_KEY, PERIOD_SELECT_ID
from utils.activity import (
    DAY, PERIODS, PERIOD_OPTIONS, AdminTracker, admin_rows, build_series, day_key, format_admin_table,
    format_ago, format_hours, local_zone, period_for, render_activity_graph, tick_times,
)


class PeriodTests(TestCase):
    def test_dropdown_lists_the_eight_spans_in_order(self):
        self.assertEqual([label for _, label in PERIOD_OPTIONS],
                         ["24 hours", "7 days", "1 month", "3 months", "6 months", "1 year", "3 years",
                          "Max (all time)"])
        self.assertFalse(PERIODS["24h"].hourly)
        self.assertTrue(all(p.hourly for key, p in PERIODS.items() if key != "24h"))
        for period in PERIODS.values():
            self.assertLessEqual(period.seconds // period.bucket, 200)

    def test_max_spans_all_recorded_data_with_a_readable_scale(self):
        end = 1_900_000_000
        for days in (0.5, 5, 40, 150, 400, 1500):
            period = period_for("max", end - days * DAY, end)
            self.assertGreaterEqual(period.seconds, min(days, 1) * DAY)
            self.assertLessEqual(period.seconds // period.bucket, 200)
            self.assertEqual(period.label, "ALL TIME")
        self.assertFalse(period_for("max", end - 3600, end).hourly)
        self.assertEqual(period_for("max", None, end).seconds, DAY)

    def test_month_ticks_land_on_the_first_of_each_month(self):
        zone = local_zone(3)
        start = datetime(2026, 1, 15, tzinfo=zone).timestamp()
        end = datetime(2026, 7, 10, tzinfo=zone).timestamp()
        ticks = [datetime.fromtimestamp(t, zone) for t in tick_times(start, end, PERIODS["6m"], 3)]
        self.assertEqual([(t.month, t.day, t.hour) for t in ticks], [(m, 1, 0) for m in range(2, 8)])
        two_monthly = [datetime.fromtimestamp(t, zone).month for t in tick_times(start, end, PERIODS["1y"], 3)]
        self.assertEqual(two_monthly, [3, 5, 7])


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
        with patch("cogs.server_monitor.STAFF_ACTIVITY_CHANNEL_ID", 5):
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


class GraphCardTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_bot = SimpleNamespace(
            get_first_activity_ts=AsyncMock(return_value=None),
            get_activity_buckets=AsyncMock(return_value={}), get_hourly_buckets=AsyncMock(return_value={}),
            get_monitor_message_id=AsyncMock(return_value=None), set_monitor_message_id=AsyncMock(),
        )
        self.bot = SimpleNamespace(db_bot=self.db_bot, user=SimpleNamespace(id=88))
        self.cog = ServerMonitor(self.bot)

    def select_of(self, view):
        components = view.to_components()
        row = components[0]["components"][1]
        return row["components"][0]

    def test_dropdown_marks_the_current_span_and_survives_restarts(self):
        view, _ = self.cog.graph_view("1y")
        self.assertTrue(view.is_persistent())
        select = self.select_of(view)
        self.assertEqual(select["custom_id"], PERIOD_SELECT_ID)
        self.assertEqual(len(select["options"]), 8)
        self.assertEqual([o["value"] for o in select["options"] if o.get("default")], ["1y"])

    async def test_raw_samples_only_for_short_spans(self):
        await self.cog.activity_png("24h")
        self.db_bot.get_activity_buckets.assert_awaited_once()
        self.db_bot.get_hourly_buckets.assert_not_awaited()
        await self.cog.activity_png("3y")
        self.db_bot.get_hourly_buckets.assert_awaited_once()

    async def test_choosing_a_span_redraws_the_same_message_and_is_kept(self):
        interaction = SimpleNamespace(
            data={"values": ["3m"]},
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )
        with patch("cogs.server_monitor.render_activity_graph", return_value=b"png"):
            await self.cog.on_period_selected(interaction)
        interaction.response.defer.assert_awaited_once()
        kwargs = interaction.edit_original_response.call_args.kwargs
        self.assertEqual(len(kwargs["attachments"]), 1)
        self.assertEqual([o["value"] for o in self.select_of(kwargs["view"])["options"] if o.get("default")], ["3m"])
        self.assertEqual(self.cog.graph_period, "3m")

    async def test_unknown_span_is_rejected(self):
        interaction = SimpleNamespace(data={"values": ["10y"]},
                                      response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()))
        await self.cog.on_period_selected(interaction)
        interaction.response.defer.assert_not_awaited()
        self.assertEqual(self.cog.graph_period, "24h")

    async def test_graph_goes_to_the_private_staff_channel_only(self):
        message = SimpleNamespace(id=66, author=self.bot.user)
        public = SimpleNamespace(guild=SimpleNamespace(default_role=Mock()), send=AsyncMock(return_value=message),
                                 permissions_for=Mock(return_value=discord.Permissions(view_channel=True)))
        self.cog.channel = Mock(return_value=public)
        with patch("cogs.server_monitor.STAFF_ACTIVITY_CHANNEL_ID", 5), \
             patch("cogs.server_monitor.render_activity_graph", return_value=b"png"):
            with self.assertRaises(ValueError):
                await self.cog.post_activity_graph()
            public.send.assert_not_awaited()
            public.permissions_for = Mock(return_value=discord.Permissions.none())
            with patch("cogs.server_monitor.GUILD_ID", 100):
                await self.cog.post_activity_graph()
        self.cog.channel.assert_called_with(5)
        self.assertEqual(len(public.send.call_args.kwargs["files"]), 1)
        self.db_bot.set_monitor_message_id.assert_awaited_once_with(100, SERVER_KEY, "activity_graph", 66)
