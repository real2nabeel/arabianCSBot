import datetime as dt
import unittest

from utils import clips

META = {"player": "Ace", "summary": "4 kills in 2.1 s", "map": "de_dust2"}


class TestText(unittest.TestCase):
    def test_caption(self):
        text = clips.caption(META, "🔥 {player} – {summary} on {map}\n🎮 connect {server}\n\n{hashtags}",
                             "1.2.3.4:27015", "#CS16")
        self.assertEqual(text, "🔥 Ace – 4 kills in 2.1 s on de_dust2\n🎮 connect 1.2.3.4:27015\n\n#CS16")

    def test_unknown_fields_are_kept(self):
        self.assertEqual(clips.caption(META, "{player} {oops}", "", ""), "Ace {oops}")

    def test_title_is_trimmed(self):
        t = clips.title({"player": "A" * 120, "summary": "x"})
        self.assertEqual(len(t), 100)
        self.assertTrue(t.endswith(" #Shorts"))


class TestHours(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(clips.parse_hours("12-23"), (12, 23))
        self.assertEqual(clips.parse_hours(""), (0, 23))
        with self.assertRaises(ValueError):
            clips.parse_hours("12-25")

    def test_wraps_midnight(self):
        self.assertTrue(clips.in_hours(dt.datetime(2026, 1, 1, 1), (20, 2)))
        self.assertFalse(clips.in_hours(dt.datetime(2026, 1, 1, 12), (20, 2)))


class TestMayPost(unittest.TestCase):
    now = dt.datetime(2026, 11, 18, 18, 0)

    def test_outside_hours(self):
        self.assertFalse(clips.may_post(self.now.replace(hour=9), (12, 23), [], 2, 240))

    def test_daily_limit(self):
        posted = [self.now - dt.timedelta(hours=6), self.now - dt.timedelta(hours=5)]
        self.assertFalse(clips.may_post(self.now, (12, 23), posted, 2, 60))
        self.assertTrue(clips.may_post(self.now, (12, 23), posted, 3, 60))

    def test_yesterday_does_not_count(self):
        posted = [self.now - dt.timedelta(days=1), self.now - dt.timedelta(days=1, hours=1)]
        self.assertTrue(clips.may_post(self.now, (12, 23), posted, 2, 240))

    def test_gap(self):
        self.assertFalse(clips.may_post(self.now, (12, 23), [self.now - dt.timedelta(minutes=100)], 5, 240))
        self.assertTrue(clips.may_post(self.now, (12, 23), [self.now - dt.timedelta(minutes=300)], 5, 240))

    def test_off(self):
        self.assertFalse(clips.may_post(self.now, (12, 23), [], 0, 0))


class TestQueue(unittest.TestCase):
    def test_oldest_approved_first_skipping_posted(self):
        t = dt.datetime(2026, 11, 18)
        approved = [("b", t + dt.timedelta(hours=1)), ("a", t), ("c", t + dt.timedelta(hours=2))]
        self.assertEqual(clips.next_clip(approved, set()), "a")
        self.assertEqual(clips.next_clip(approved, {"a"}), "b")
        self.assertIsNone(clips.next_clip(approved, {"a", "b", "c"}))


class TestDecision(unittest.TestCase):
    def test_only_approvers_count(self):
        self.assertEqual(clips.decision({clips.APPROVE: {5}}, {1, 2}), "pending")
        self.assertEqual(clips.decision({clips.APPROVE: {5, 2}}, {1, 2}), "approved")

    def test_rejection_wins(self):
        self.assertEqual(clips.decision({clips.APPROVE: {1}, clips.REJECT: {2}}, {1, 2}), "rejected")



class TestRunReport(unittest.TestCase):
    def test_done(self):
        self.assertEqual(clips.run_report({"state": "done", "made": 2, "requested_by": 7}),
                         "🎬 Clip run finished (started by <@7>): 2 new clips below.")
        self.assertIn("1 couldn't be made (Boom)",
                      clips.run_report({"state": "done", "made": 1, "failed": 1, "error": "Boom"}))

    def test_busy_and_nothing(self):
        self.assertIn("in a game", clips.run_report({"state": "busy"}))
        self.assertIn("no new highlights", clips.run_report({"state": "nothing"}))

    def test_running_has_no_report(self):
        self.assertIsNone(clips.run_report({"state": "running"}))


if __name__ == "__main__":
    unittest.main()
