"""Different players per month, counted from the live rank table."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cogs.server_monitor import ServerMonitor, SERVER_KEY
from utils.activity import format_player_months, month_key, month_readings, shift_month, valid_month


class MonthHelperTests(TestCase):
    def test_month_keys(self):
        moment = datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc).timestamp()
        self.assertEqual(month_key(moment, 0), "2026-11")
        self.assertEqual(month_key(moment, 3), "2026-12")
        self.assertEqual(shift_month("2026-12", 1), "2027-01")
        self.assertEqual(shift_month("2027-01", -1), "2026-12")
        self.assertEqual(shift_month("2026-11", -12), "2025-11")
        for good in ("2026-01", "2026-12"):
            self.assertTrue(valid_month(good))
        for bad in ("2026-00", "2026-13", "0000/00", "", None, "2026-1"):
            self.assertFalse(valid_month(bad))


class ReadingTests(TestCase):
    def test_first_look_saves_this_month_and_new_players_for_the_season(self):
        rows = month_readings({"2026-08": 3103, "2026-09": 2354, "2026-11": 567},
                              {"2026-09": 2248, "2026-10": 2144, "2026-11": 1285}, {}, "2026-11")
        self.assertEqual(rows, [("2026-08", None, 3103), ("2026-09", None, 2354), ("2026-11", 1285, 567)])

    def test_last_month_is_finished_off_only_when_it_was_being_counted(self):
        first, last = {"2026-12": 3}, {"2026-11": 1200, "2026-12": 90}
        rows = month_readings(first, last, {"2026-11": {"players": 1290}}, "2026-12")
        self.assertEqual(rows, [("2026-11", 1200, None), ("2026-12", 90, 3)])
        rows = month_readings(first, last, {"2026-11": {"players": None}}, "2026-12")
        self.assertEqual(rows, [("2026-12", 90, 3)])

    def test_server_clock_decides_the_month(self):
        # Just after midnight on the bot's clock, nobody has a December login yet:
        # November is still the month being counted.
        rows = month_readings({}, {"2026-10": 50, "2026-11": 1300}, {"2026-11": {"players": 1290}}, "2026-12")
        self.assertEqual(rows, [("2026-11", 1300, None)])

    def test_bad_dates_are_ignored(self):
        rows = month_readings({"0000-00": 4, "2099-01": 1, "2026-11": 5},
                              {"2099-01": 1, "2026-13": 2, "2026-11": 9}, {}, "2026-11")
        self.assertEqual(rows, [("2026-11", 9, 5)])

    def test_empty_table(self):
        self.assertEqual(month_readings({}, {}, {}, "2026-11"), [])


class TableTests(TestCase):
    def test_newest_first_with_gaps_shown_as_dashes(self):
        saved = {"2026-08": {"players": None, "new_players": 3103},
                 "2026-09": {"players": None, "new_players": 2354},
                 "2026-11": {"players": 1285, "new_players": 567}}
        table, note = format_player_months(saved)
        self.assertEqual(table.splitlines(), [
            "MONTH      PLAYERS     NEW",
            "Nov 2026     1,285     567",
            "Sep 2026         –   2,354",
            "Aug 2026         –   3,103",
        ])
        self.assertIn("counted since Nov 2026", note)

    def test_limit_and_nothing_saved(self):
        saved = {f"2026-{m:02d}": {"players": m, "new_players": m} for m in range(1, 13)}
        table, _ = format_player_months(saved, limit=6)
        self.assertEqual(len(table.splitlines()), 7)
        self.assertTrue(table.splitlines()[1].startswith("Dec 2026"))
        self.assertIsNone(format_player_months({}))


class RecordingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_live = SimpleNamespace(count_players_by_month=AsyncMock(
            side_effect=lambda column: {"First Login": {"2026-11": 5}, "Last Login": {"2026-11": 9}}[column]))
        self.db_bot = SimpleNamespace(get_player_months=AsyncMock(return_value={}),
                                      save_player_months=AsyncMock())
        self.cog = ServerMonitor(SimpleNamespace(db_bot=self.db_bot, db_live=self.db_live))

    async def test_counted_every_ten_minutes(self):
        wall = datetime(2026, 11, 15, 12, tzinfo=timezone.utc).timestamp()
        with patch("cogs.server_monitor.ACTIVITY_UTC_OFFSET", 0):
            await self.cog.record_player_months(wall, 0)
            await self.cog.record_player_months(wall + 300, 300)
            await self.cog.record_player_months(wall + 600, 600)
        self.assertEqual(self.db_bot.save_player_months.await_count, 2)
        self.db_bot.save_player_months.assert_awaited_with(SERVER_KEY, [("2026-11", 9, 5)])

    async def test_table_text_and_database_errors(self):
        self.assertIsNone(await self.cog.safe_player_months_text())
        self.db_bot.get_player_months.return_value = {"2026-11": {"players": 9, "new_players": 5}}
        text = await self.cog.safe_player_months_text()
        self.assertTrue(text.startswith("**Players per month**\n```"))
        self.assertIn("Nov 2026", text)
        self.db_bot.get_player_months.side_effect = RuntimeError("down")
        with self.assertLogs("cogs.server_monitor", "ERROR"):
            self.assertIsNone(await self.cog.safe_player_months_text())
