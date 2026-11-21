import unittest

from clips import select


def moment(**kw):
    m = {"id": "120000-1", "date": "2026-11-17 12:00:00", "map": "de_dust2", "type": "multikill", "player": "Ace",
         "entity": 5, "team": "CT", "kills": 4, "headshots": 2, "weapons": "ak47 ak47 ak47 ak47", "extra": "",
         "score": 75, "enemies": 0, "start": 100.0, "end": 102.1, "logged": 106.2}
    m.update(kw)
    return m


def kill(t, k=5):
    return {"t": t, "k": k, "v": 9, "hs": 0, "w": "ak47", "kt": 2, "vt": 1, "kn": "Ace", "vn": "Bot"}


class TestLocate(unittest.TestCase):
    def test_works_back_from_the_mark(self):
        # Mark at demo 50.0 was sent at game clock 106.2, so game 100.0 is demo 43.8.
        start, end = select.locate(moment(), {"120000-1": 50.0})
        self.assertAlmostEqual(start, 43.8)
        self.assertAlmostEqual(end, 45.9)

    def test_missing_mark(self):
        self.assertIsNone(select.locate(moment(), {"other": 1.0}))


class TestWindow(unittest.TestCase):
    def test_built_around_own_kills(self):
        kills = [kill(44.0), kill(44.7), kill(45.9), kill(45.0, k=3)]
        self.assertEqual(select.window(moment(), 43.8, 45.9, kills), (41.0, 48.4))

    def test_clutch_keeps_the_ending_but_not_forever(self):
        m = moment(type="clutch", enemies=3, kills=2)
        start, end = select.window(m, 10.0, 59.0, [kill(30.0), kill(40.0)])
        self.assertEqual(start, 27.0)
        self.assertEqual(end, 40.0 + select.CLUTCH_TAIL + select.POST_ROLL)

    def test_long_window_is_trimmed_from_the_start(self):
        kills = [kill(10.0), kill(70.0)]
        start, end = select.window(moment(type="clutch"), 5.0, 70.0, kills)
        self.assertEqual(end - start, select.MAX_LENGTH)
        self.assertEqual(end, 72.5)

    def test_never_before_demo_start(self):
        self.assertEqual(select.window(moment(), 1.0, 2.0, [kill(1.5)])[0], 0.0)


class TestDescribe(unittest.TestCase):
    def test_fast_multikill(self):
        self.assertEqual(select.describe(moment()), "Quad kill: 4 kills in 2.1 s")

    def test_slow_multikill(self):
        self.assertEqual(select.describe(moment(end=110.0)), "Quad kill: 4 kills")

    def test_clutch(self):
        self.assertEqual(select.describe(moment(type="clutch", enemies=3, kills=2)), "1v3 clutch with 2 kills")

    def test_specials(self):
        self.assertEqual(select.describe(moment(type="special", kills=1, extra="noscope", weapons="awp")),
                         "no-scope AWP kill")
        self.assertEqual(select.describe(moment(type="special", kills=2, extra="double air")), "one-shot double kill")
        self.assertEqual(select.describe(moment(type="special", kills=1, extra="knife", weapons="knife")), "knife kill")


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.demo = {"map": "de_dust2", "marks": {"120000-1": 50.0, "120004-2": 52.0, "130000-3": 200.0},
                     "kills": [kill(44.0), kill(44.7), kill(45.9), kill(194.0, k=7)]}

    def test_overlapping_moments_of_one_player_merge(self):
        burst = moment()
        clutch = moment(id="120004-2", type="clutch", enemies=3, kills=4, score=110, start=95.0, end=104.1,
                        logged=104.1)
        clips = select.plan([burst, clutch], {"a.dem": self.demo})
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["logged"], [burst, clutch])
        # The clip shows 3 of the clutch's kills: it's a 1v3 with 3 kills, scored on those.
        self.assertEqual(clips[0]["summary"], "1v3 clutch with 3 kills")
        self.assertEqual(clips[0]["score"], 3 * 10 + 15 + 3 * 10 + 3 * 5)

    def test_best_first_low_scores_and_unknown_marks_dropped(self):
        other = moment(id="130000-3", player="Bob", entity=7, score=40, start=190.0, end=190.0, logged=196.0)
        low = moment(id="130000-3", score=20)
        lost = moment(id="999999-9", score=200)
        clips = select.plan([other, moment(), low, lost], {"a.dem": self.demo})
        self.assertEqual([c["player"] for c in clips], ["Ace", "Bob"])
        self.assertEqual(clips[0]["key"], "2026-11-17_120000-1")

    def test_moment_that_began_before_the_demo_is_skipped(self):
        early = moment(id="120000-1", type="clutch", enemies=3, kills=3, start=10.0, end=106.2)  # mark at 50.0
        self.assertEqual(select.plan([early], {"a.dem": self.demo}), [])

    def test_top_limit(self):
        other = moment(id="130000-3", player="Bob", entity=7, score=40, start=190.0, end=190.0, logged=196.0)
        self.assertEqual(len(select.plan([other, moment()], {"a.dem": self.demo}, top=1)), 1)


def k(t, w="ak47", hs=0):
    return dict(kill(t), w=w, hs=hs)


class TestScore(unittest.TestCase):
    def test_kinds_of_kill(self):
        self.assertEqual([select.kill_points(x) for x in (k(0), k(0, hs=1), k(0, "awp"), k(0, "deagle", 1),
                                                          k(0, "knife"))], [10, 20, 20, 30, 35])

    def test_burst_and_speed(self):
        slow = [k(0), k(3), k(6)]
        fast = [k(0), k(1), k(2)]
        self.assertEqual(select.score_kills(slow), 30 + 15)
        self.assertEqual(select.score_kills(fast), 30 + 15 + 30)
        self.assertEqual(select.best_burst([0, 1, 20, 22, 24, 26]), (4, 6))

    def test_what_we_want_beats_an_easy_clutch(self):
        easy_clutch = select.score_kills([k(0), k(8, hs=1), k(17), k(25)], clutch_enemies=4)
        self.assertGreater(select.score_kills([k(0, "knife"), k(2, "knife"), k(5, "knife")]), easy_clutch)
        self.assertGreater(select.score_kills([k(0, "deagle", 1), k(1.5, "deagle", 1), k(3, "deagle", 1)]), easy_clutch)
        self.assertGreater(select.score_kills([k(0, "awp"), k(1.5, "awp"), k(3, "awp")]), easy_clutch)
        self.assertGreater(select.score_kills([k(0, hs=1), k(2, hs=1), k(4, hs=1)]), easy_clutch)

    def test_only_big_clutches_count_much(self):
        kills = [k(t) for t in (0, 10, 20, 30, 40, 50)]
        self.assertEqual(select.score_kills(kills, 5) - select.score_kills(kills), 25)
        self.assertEqual(select.score_kills(kills, 6) - select.score_kills(kills), 60)


class TestWhatItShows(unittest.TestCase):
    def clip(self, *moments, start=0.0, end=40.0):
        return {"entity": 5, "start": start, "end": end, "moments": list(moments)}

    def test_clutch_counts_only_the_kills_shown(self):
        clutch = moment(type="clutch", enemies=4, kills=4, extra="1v4")
        play = select.what_it_shows(self.clip(clutch, start=20.0), [k(10), k(15), k(25), k(30, hs=1)])
        self.assertEqual((play["type"], play["enemies"], play["kills"], play["headshots"]), ("clutch", 2, 2, 1))
        self.assertEqual(select.describe(play), "1v2 clutch with 2 kills")

    def test_team_kills_and_others_dont_count(self):
        tk = dict(k(5), vt=2)
        play = select.what_it_shows(self.clip(moment()), [k(1), k(2, hs=1), tk, dict(k(3), k=7), k(4, "deagle", 1)])
        self.assertEqual((play["type"], play["kills"], play["weapons"]), ("multikill", 3, "ak47 ak47 deagle"))
        self.assertEqual(play["score"], select.score_kills([k(1), k(2, hs=1), k(4, "deagle", 1)]))

    def test_special_keeps_its_bonus(self):
        noscope = moment(type="special", kills=1, weapons="awp", extra="noscope air")
        play = select.what_it_shows(self.clip(noscope), [k(3, "awp")])
        self.assertEqual((play["type"], play["extra"], play["score"]), ("special", "air noscope", 20 + 30 + 10))
        self.assertEqual(select.describe(play), "no-scope AWP kill")


class TestStreakName(unittest.TestCase):
    def test_names(self):
        self.assertEqual([select.streak_name(n) for n in (1, 2, 3, 5, 6, 12)],
                         ["", "Double kill", "Triple kill", "Multi kill", "Rampage", "Unstoppable"])


class TestRunLimit(unittest.TestCase):
    def test_the_requested_count(self):
        self.assertEqual(select.run_limit({"limit": 15}, 8), 15)   # more than the default is fine
        self.assertEqual(select.run_limit({"limit": 1}, 8), 1)     # /clips-one
        self.assertEqual(select.run_limit({"limit": 500}, 8), select.RUN_MAX)

    def test_default_without_a_count(self):
        for request in ({}, {"limit": None}, {"limit": 0}, {"limit": "5"}, {"limit": True}):
            self.assertEqual(select.run_limit(request, 8), 8)


if __name__ == "__main__":
    unittest.main()
