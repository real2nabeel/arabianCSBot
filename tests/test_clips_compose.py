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


if __name__ == "__main__":
    unittest.main()
