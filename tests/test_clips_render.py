import unittest

from clips import render


class TestFirstFrameClock(unittest.TestCase):
    LOG = ("Input #0, x11grab, from ':98':\n  Duration: N/A, start: 1763485123.456789, bitrate: N/A\n"
           "  Stream #0:0: Video: rawvideo (BGR[0] / 0x30524742), bgr0, 1920x1080, 60 fps\n"
           "Input #1, pulse, from 'clips.monitor':\n  Duration: N/A, start: 1763485123.500000, bitrate: 1536 kb/s\n")

    def test_reads_the_screen_input(self):
        self.assertEqual(render.first_frame_clock(self.LOG), 1763485123.456789)

    def test_none_without_it(self):
        self.assertIsNone(render.first_frame_clock("Output #0, matroska, to 'raw.mkv':"))


class TestSyncPoints(unittest.TestCase):
    SEEN = [(1763485124.0, 5000.0, 2922.6), (1763485125.0, 5001.0, 2923.1)]   # (wall, monotonic, demo time)

    def test_wall_clock_start(self):
        self.assertEqual(render.sync_points(self.SEEN, 1763485123.5), [(0.5, 2922.6), (1.5, 2923.1)])

    def test_monotonic_start(self):
        self.assertEqual(render.sync_points(self.SEEN, 4999.75), [(0.25, 2922.6), (1.25, 2923.1)])


class TestMissingFile(unittest.TestCase):
    def test_model(self):
        err = render.RenderError("CS couldn't play the demo: Cannot continue without model "
                                 "sprites/arabian_servers_sign.spr, disconnecting.")
        self.assertEqual(render.missing_file(err), "sprites/arabian_servers_sign.spr")

    def test_other_errors_and_unsafe_paths(self):
        self.assertIsNone(render.missing_file(render.RenderError("CS did not reach the moment within 400 s")))
        self.assertIsNone(render.missing_file("Cannot continue without model ../../etc/passwd, disconnecting."))
        self.assertIsNone(render.missing_file("Cannot continue without model /etc/passwd, disconnecting."))


if __name__ == "__main__":
    unittest.main()
