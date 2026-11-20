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

    def test_title_without_moments_falls_back(self):
        self.assertEqual(clips.title(META), "Ace – 4 kills in 2.1 s")
        self.assertEqual(len(clips.title({"player": "A" * 120, "summary": "x"})), 100)


def moment(**kw):
    m = {"type": "multikill", "kills": 4, "headshots": 2, "weapons": "knife knife knife knife", "extra": "",
         "score": 125, "enemies": 0, "start": 27.01, "end": 34.88}
    m.update(kw)
    return m


def clip(key="2026-11-18_232849-2", **kw):
    return {"key": key, "player": "Melo", "summary": "4 kills", "map": "de_dust2", "moments": [moment(**kw)]}


class TestMomentText(unittest.TestCase):
    def hooks(self, **kw):
        """Every phrasing this kind of clip can get (over many clip ids)."""
        return {clips.moment_text(clip(f"k{i}", **kw))[0] for i in range(60)}

    def test_knife_multikill(self):
        self.assertEqual(self.hooks(), {"4 knife kills in 7.9 seconds", "4 knife kills, 7.9 seconds – CS 1.6",
                                        "Knife only: 4 kills in 7.9 seconds – CS 1.6"})

    def test_clutch_streaks_and_specials(self):
        self.assertIn("1v4 clutch on Dust2 – CS 1.6", self.hooks(type="clutch", enemies=4, kills=4, weapons=""))
        self.assertIn("Multi kill with the AWP – CS 1.6",
                      self.hooks(kills=5, headshots=0, weapons="awp " * 5, start=0, end=4.9))
        self.assertIn("No-scope AWP kill – CS 1.6", self.hooks(type="special", kills=1, weapons="awp", extra="noscope"))
        self.assertIn("Quad kill: 4 kills in 7.9 seconds – CS 1.6", self.hooks(weapons="ak47 ak47 deagle m4a1"))

    def test_all_headshots(self):
        self.assertIn("3 Deagle headshots in 7.9 seconds – CS 1.6",
                      self.hooks(kills=3, headshots=3, weapons="deagle deagle deagle"))
        self.assertIn("Triple kill, all headshots – CS 1.6 Dust2",
                      self.hooks(kills=3, headshots=3, weapons="ak47 deagle ak47"))
        self.assertEqual(clips.moment_text(clip(kills=3, headshots=3, weapons="ak47 deagle ak47"))[2], "#headshot")

    def test_same_clip_same_text_and_no_emojis(self):
        a = clips.moment_text(clip())
        self.assertEqual(a, clips.moment_text(clip()))
        self.assertEqual(a[2], "#knife")
        for i in range(60):
            for text in clips.moment_text(clip(f"k{i}", type="clutch", enemies=3, kills=2)):
                self.assertTrue(all(ord(ch) < 0x2000 or ch == "–" for ch in text), text)

    def test_caption_adds_the_moment_hashtag_once(self):
        template = "{hook}\n{question}\n\n{player}\nconnect {server}\n\n{hashtags}"
        text = clips.caption(clip(), template, "1.2.3.4:27015", "#cs16 #counterstrike #dust2 #كاونتر_سترايك")
        lines = text.split("\n")
        self.assertEqual(lines[0], clips.moment_text(clip())[0])
        self.assertEqual(lines[-1], "#cs16 #counterstrike #dust2 #knife #كاونتر_سترايك")
        self.assertEqual(clips.caption(clip(), "{hashtags}", "", "#cs16 #Knife"), "#cs16 #Knife")

    def test_title_is_the_hook(self):
        self.assertEqual(clips.title(clip()), clips.moment_text(clip())[0])


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


class TestQueuePage(unittest.TestCase):
    def queue(self, n):
        return {"clips": [dict(clip(f"k{i}"), player="Player%d" % i, score=200 - i) for i in range(n)]}

    def test_first_page_lists_titles_best_first(self):
        text, pages = clips.queue_page(self.queue(45))
        lines = text.split("\n")
        self.assertEqual(pages, 3)
        self.assertEqual(len(lines), 21)                       # header + 20 rows
        self.assertTrue(lines[1].lstrip().startswith("1    200"))
        self.assertIn(clips.moment_text(clip("k0"))[0], lines[1])
        self.assertTrue(lines[1].endswith("Player0"))

    def test_last_page_and_out_of_range(self):
        text, pages = clips.queue_page(self.queue(45), page=9)  # past the end: the last page
        self.assertEqual(len(text.split("\n")), 6)
        self.assertTrue(text.split("\n")[1].lstrip().startswith("41"))

    def test_long_names_are_cut_and_empty_queue(self):
        q = {"clips": [dict(clip(), player="X" * 40, score=90)]}
        self.assertTrue(clips.queue_page(q)[0].endswith("X" * 15 + "…"))
        self.assertEqual(clips.queue_page({"clips": []}), ("No clips are waiting to be made.", 1))


if __name__ == "__main__":
    unittest.main()
