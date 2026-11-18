import os
import tempfile
import unittest
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
