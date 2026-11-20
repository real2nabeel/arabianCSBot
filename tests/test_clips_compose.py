import os
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageFont

from clips import compose


class TestNextKbps(unittest.TestCase):
    def test_lowered_in_proportion_with_room_to_spare(self):
        size = compose.DISCORD_BYTES * 1.02            # 2% over, as seen on a hard clip
        self.assertEqual(compose.next_kbps(4500, size), int(4500 / 1.02 * 0.97))

    def test_never_below_the_floor(self):
        self.assertEqual(compose.next_kbps(310, compose.DISCORD_BYTES * 3), 300)


class TestDiscordCopy(unittest.TestCase):
    """ffmpeg is replaced by a stand-in that writes a file of a chosen size for each second pass."""

    def run_copy(self, sizes, length=17.0):
        out = tempfile.mkdtemp()
        dc = os.path.join(out, "discord.mp4")
        calls, sizes = [], list(sizes)

        def fake_run(cmd, check):
            calls.append(cmd)
            if "2" == cmd[cmd.index("-pass") + 1]:
                with open(dc, "wb") as fh:
                    fh.write(b"\0" * int(sizes.pop(0)))

        with mock.patch.object(compose.subprocess, "run", side_effect=fake_run):
            kbps = compose.discord_copy("hq.mp4", dc, length, os.path.join(out, "pass"))
        rates = [c[c.index("-b:v") + 1] for c in calls if c[c.index("-pass") + 1] == "2"]
        return kbps, rates

    def test_under_the_aim_is_made_once(self):
        kbps, rates = self.run_copy([compose.DISCORD_BYTES - 1000])
        self.assertEqual(len(rates), 1)
        self.assertEqual(rates[0], f"{kbps}k")

    def test_over_the_aim_is_made_again_lower(self):
        first = compose.DISCORD_BYTES * 1.02
        kbps, rates = self.run_copy([first, compose.DISCORD_BYTES - 1000])
        self.assertEqual(len(rates), 2)
        start = int(rates[0][:-1])
        self.assertEqual(kbps, compose.next_kbps(start, first))
        self.assertEqual(rates[1], f"{kbps}k")

    def test_stops_after_the_last_try(self):
        over = compose.DISCORD_BYTES * 1.05
        _, rates = self.run_copy([over] * compose.DISCORD_TRIES)
        self.assertEqual(len(rates), compose.DISCORD_TRIES)
        self.assertTrue(all(int(a[:-1]) > int(b[:-1]) for a, b in zip(rates, rates[1:])))


class TestFeedScale(unittest.TestCase):
    """Rows are drawn at full size, then shrunk by FEED_SCALE (the font and game icons are stand-ins here)."""
    KILL = dict(k=1, kn="chibchib", kt=1, w="deagle", hs=1, vn="ALGERIAN", vt=2, t=10.0, v=2)

    def row(self, scale):
        icon = Image.new("RGBA", (64, 32), (255, 150, 30, 255))
        with mock.patch.object(compose, "FEED_SCALE", scale),                 mock.patch.object(compose, "FONT_OBJ", ImageFont.load_default(size=compose.FONT_SIZE)),                 mock.patch.object(compose, "icon", return_value=icon):
            return compose.row_image(self.KILL, featured=1)

    def test_rows_are_shrunk(self):
        full, small = self.row(1.0), self.row(compose.FEED_SCALE)
        self.assertEqual(small.size, (round(full.width * compose.FEED_SCALE), round(full.height * compose.FEED_SCALE)))

    def test_feed_uses_the_shrunk_rows(self):
        kills = [dict(self.KILL, t=10.0 + i, v=2 + i) for i in range(3)]
        with mock.patch.object(compose, "row_image", side_effect=lambda k, f: Image.new("RGBA", (300, 40))):
            out = tempfile.mkdtemp()
            states = compose.feed_states(kills, start=9.0, length=8.0, offset=0.0, featured=1, tmp=out)
        heights = []
        for _, _, path in states:
            with Image.open(path) as im:
                heights.append(im.height)
        tallest = max(heights)
        self.assertEqual(tallest, 3 * (40 + round(compose.ROW_GAP * compose.FEED_SCALE)))
        self.assertEqual(compose.FEED_SCALE, 0.65)


class TestVideoTime(unittest.TestCase):
    # playback falling behind: 1 demo second took 2 video seconds, then normal speed
    SYNC = [(0.6, 100.0), (2.6, 101.0), (3.6, 102.0)]

    def test_interpolates_between_markers(self):
        self.assertAlmostEqual(compose.video_time(self.SYNC, 100.5), 1.6)
        self.assertAlmostEqual(compose.video_time(self.SYNC, 101.5), 3.1)

    def test_one_to_one_outside_the_markers(self):
        self.assertAlmostEqual(compose.video_time(self.SYNC, 99.0), -0.4)
        self.assertAlmostEqual(compose.video_time(self.SYNC, 103.0), 4.6)

    def test_steady_takes_out_late_markers(self):
        # every other marker seen 0.4 s late
        sync = [(t - 0.7 + (0.4 if i % 2 else 0), t) for i, t in enumerate([100.0, 100.1, 100.2, 100.3, 100.4])]
        self.assertEqual([round(v, 2) for v, _ in compose.steady(sync)], [99.3, 99.4, 99.5, 99.6, 99.7])

    def test_feed_follows_the_markers(self):
        kill = dict(TestFeedScale.KILL, t=101.5)
        with mock.patch.object(compose, "row_image", side_effect=lambda k, f: Image.new("RGBA", (300, 40))):
            synced = compose.feed_states([kill], 100.0, 8.0, 0.46, 1, tempfile.mkdtemp(), sync=self.SYNC)
            fixed = compose.feed_states([kill], 100.0, 8.0, 0.46, 1, tempfile.mkdtemp())
        self.assertAlmostEqual(synced[0][0], 3.1 + compose.FEED_LEAD)
        self.assertAlmostEqual(fixed[0][0], 1.96)


class TestFraming(unittest.TestCase):
    def test_bar_hidden_matches_the_old_clips_height(self):
        crop, width, height, top = compose.framing(True)
        self.assertEqual(crop, "1920:936:0:0")             # only the bottom band cropped
        self.assertEqual(height, 944)                      # old clips: 1920x1080 at 1680 wide -> 945
        self.assertEqual(top, (1920 - 944) // 2)
        self.assertGreater(width, 1080)                    # the sides are cut off, as before

    def test_fallback_crops_both_bars(self):
        self.assertEqual(compose.framing(False), ("1920:792:0:144", 1680, 692, 614))


class TestScopeAndBar(unittest.TestCase):
    def test_scope_ranges(self):
        zooms = [(100.0, 90), (101.0, 40), (101.5, 10), (103.0, 90), (104.0, 55), (105.0, 0), (106.0, 40)]
        ranges = compose.scope_ranges(zooms, 7.0, lambda t: t - 100.0)
        # 40 then 10 is one scoped stretch; the AUG/SG552 zoom (55) has no scope; still scoped at the end
        self.assertEqual(ranges, [(1.0, 3.0), (6.0, 7.0)])

    def test_scope_ranges_clipped_to_the_clip(self):
        self.assertEqual(compose.scope_ranges([(95.0, 40), (102.0, 90)], 5.0, lambda t: t - 100.0), [(0.0, 2.0)])
        self.assertEqual(compose.scope_ranges([(90.0, 40), (95.0, 90)], 5.0, lambda t: t - 100.0), [])

    def test_bar_ranges(self):
        # a 10 s defuse cancelled after 2 s, then a 5 s defuse with a kit, then a plant past the end of the clip
        bars = [(100.0, 10, 0), (102.0, 0, 0), (103.0, 5, 0), (110.0, 3, 0)]
        self.assertEqual(compose.bar_ranges(bars, 9.0, lambda t: t - 100.0), [(0.0, 2.0, 10, 0), (3.0, 8.0, 5, 0)])

    def test_bar_resumed_partway(self):
        # BarTime2: 10 s bar, 40% already done -> 6 s left
        self.assertEqual(compose.bar_ranges([(100.0, 10, 40)], 20.0, lambda t: t - 100.0), [(0.0, 6.0, 10, 40)])

    def test_bar_images(self):
        frame_png, fill_png = compose.bar_images(tempfile.mkdtemp())
        with Image.open(frame_png) as frame, Image.open(fill_png) as fill:
            self.assertEqual(frame.size, (compose.BAR_W, compose.BAR_H))
            self.assertEqual(fill.width, 2 * compose.BAR_W)
            self.assertEqual(fill.getpixel((10, 2))[3], 255)                    # left half filled
            self.assertEqual(fill.getpixel((compose.BAR_W + 10, 2))[3], 0)      # right half see-through


def moment(**kw):
    m = {"type": "multikill", "kills": 4, "headshots": 2, "weapons": "knife knife knife knife",
         "extra": "knife knife knife knife", "score": 125, "enemies": 0, "start": 27.01, "end": 34.88, "round": 1}
    m.update(kw)
    return m


class TestHeadline(unittest.TestCase):
    def text(self, *moments):
        parts, details = compose.headline(list(moments), "Melo")
        return "".join(t for t, _ in parts), [t for t, a in parts if a], details

    def test_multikill_with_one_weapon(self):
        text, accent, details = self.text(moment())
        self.assertEqual(text, "QUAD KILL · KNIFE")
        self.assertEqual(accent, ["QUAD KILL"])
        self.assertEqual(details, "Melo  ·  4 kills  ·  2 headshots  ·  7.9 s  ·  Round 1")

    def test_streak_names(self):
        self.assertEqual(self.text(moment(weapons="ak47 ak47 deagle"))[0], "QUAD KILL")
        self.assertEqual(self.text(moment(kills=5, weapons="awp " * 5))[0], "MULTI KILL · AWP")
        self.assertEqual(self.text(moment(kills=6, weapons="ak47 m4a1 ak47 ak47 ak47"))[0], "RAMPAGE")
        self.assertEqual(self.text(moment(kills=12, weapons="ak47 m4a1"))[0], "UNSTOPPABLE")

    def test_clutch_and_specials(self):
        text, accent, details = self.text(moment(type="clutch", enemies=3, kills=2, headshots=0, weapons="", extra="1v3"))
        self.assertEqual((text, accent), ("1v3 CLUTCH", ["1v3"]))
        self.assertEqual(details, "Melo  ·  2 kills  ·  Round 1")
        self.assertEqual(self.text(moment(type="special", kills=1, weapons="awp", extra="noscope"))[0], "NO-SCOPE AWP")
        self.assertEqual(self.text(moment(type="special", kills=2, weapons="awp awp", extra="double"))[0], "2 FOR 1 · AWP")

    def test_highest_score_names_the_clip(self):
        low = moment(type="special", kills=1, weapons="awp", extra="noscope", score=40)
        self.assertEqual(self.text(low, moment())[0], "QUAD KILL · KNIFE")


class TestBand(unittest.TestCase):
    def test_images_fit_above_the_gameplay(self):
        _, _, _, top = compose.framing(True)
        parts, details = compose.headline([moment()], "Melo")
        band = compose.band_image(parts, details, top, logo=None)
        self.assertEqual(band.size, (1080, top))
        self.assertEqual(compose.dots_image(2, 4, top).size, (1080, top))

    def test_dots_fill_at_each_kill(self):
        with tempfile.TemporaryDirectory() as tmp:
            states = compose.dot_states([-1.0, 2.0, 3.5, 5.0, 20.0], 10.0, 488, tmp)
            self.assertEqual([(a, b) for a, b, _ in states], [(0.0, 2.0), (2.0, 3.5), (3.5, 5.0), (5.0, 10.0)])
            self.assertTrue(all(os.path.exists(p) for _, _, p in states))
            self.assertEqual(compose.dot_states([4.0], 10.0, 488, tmp), [])   # one kill: no counter

    def test_kill_times_match_the_feed(self):
        kills = [{"t": 105.0}, {"t": 107.5}]
        self.assertEqual(compose.kill_times(kills, 100.0, 0.5), [5.5, 8.0])


if __name__ == "__main__":
    unittest.main()
