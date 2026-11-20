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


class TestHideSpectatorBar(unittest.TestCase):
    RES = ('"Resource/UI/SpectatorGUI.res"\n{\n\t"TopBar"\n\t{\n\t\t"visible"\t\t"1"\n\t\t"tall"\t\t\t"66"\n'
           '\t\t"enabled"\t\t"0"\n\t}\n}\n')

    def test_hidden_ui(self):
        out = render.hidden_ui(self.RES)
        self.assertIn('"visible"\t\t"0"', out)
        self.assertIn('"tall"\t\t\t"0"', out)
        self.assertIn('"enabled"\t\t"0"', out)
        self.assertTrue(out.rstrip().endswith(render.HIDDEN_MARK))

    def test_patches_once_and_keeps_the_original(self):
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as hl:
            ui = os.path.join(hl, "cstrike", "resource", "UI")
            os.makedirs(ui)
            for name in render.SPECTATOR_UI:
                with open(os.path.join(ui, name), "w", encoding="latin1") as fh:
                    fh.write(self.RES)
            with mock.patch.object(render, "HL", hl):
                self.assertTrue(render.hide_spectator_bar())
                first = open(os.path.join(ui, "Spectator.res"), encoding="latin1").read()
                self.assertTrue(render.hide_spectator_bar())      # already hidden: unchanged
                self.assertEqual(open(os.path.join(ui, "Spectator.res"), encoding="latin1").read(), first)
                self.assertEqual(open(os.path.join(ui, "Spectator.res.orig"), encoding="latin1").read(), self.RES)
                os.remove(os.path.join(ui, "Spectator.res"))
                self.assertFalse(render.hide_spectator_bar())     # no layout file: the bar can't be hidden


class TestStartWait(unittest.TestCase):
    def test_waits_until_the_moment(self):
        self.assertAlmostEqual(render.start_wait(495.0, 495.8), 0.8)

    def test_a_little_late_starts_at_once(self):
        self.assertEqual(render.start_wait(496.2, 495.8), 0.0)
        self.assertEqual(render.start_wait(183.1, 181.3), 0.0)

    def test_too_late_is_an_error(self):
        with self.assertRaises(render.RenderError):
            render.start_wait(500.0, 495.8)


class TestWriteConfig(unittest.TestCase):
    def test_brightness_is_set_before_the_demo_loads(self):
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as hl:
            os.makedirs(os.path.join(hl, "cstrike"))
            with mock.patch.object(render, "HL", hl), mock.patch.object(render, "BRIGHTNESS", "1.5"), \
                    mock.patch.object(render, "GAMMA", "2.6"):
                render.write_config()
            with open(os.path.join(hl, "cstrike", "clipfind.cfg")) as fh:
                lines = fh.read().splitlines()
        self.assertIn("brightness 1.5", lines)
        self.assertIn("gamma 2.6", lines)
        self.assertLess(lines.index("gamma 2.6"), lines.index("playdemo " + render.DEMO_NAME))
        self.assertIn(render.CROSSHAIR_ON, lines)   # a render never starts with the last one's crosshair hidden
        self.assertIn("cl_crosshair_translucent 1", lines)


def kill(t, w, k=5):
    return {"t": t, "k": k, "w": w}


class TestSniperCrosshair(unittest.TestCase):
    def test_from_weapon_lines(self):
        weapons = [(10.0, "awp"), (14.0, "deagle"), (20.0, "scout"), (21.0, "scout")]
        self.assertEqual(render.sniper_spans(weapons, [], [], 5), [(10.0, 14.0), (20.0, None)])
        self.assertEqual(render.sniper_spans([(3.0, "ak47")], [], [kill(4, "awp")], 5), [])   # lines win
        self.assertEqual(render.crosshair_commands([(10.0, 14.0), (20.0, None)]),
                         [(10.0, 'cl_crosshair_color "0 0 0"'), (14.0, 'cl_crosshair_color "50 250 50"'),
                          (20.0, 'cl_crosshair_color "0 0 0"')])

    def test_guessed_for_older_demos(self):
        kills = [kill(10.0, "awp"), kill(12.0, "awp"), kill(13.0, "ak47"), kill(30.0, "scout", k=7),
                 kill(16.5, "awp"), kill(400.0, "awp")]
        zooms = [(11.0, 40), (11.5, 90), (25.0, 10)]
        # 16.5 joins the first span (a short gap, no blink); 25.0 is its own; 400 is outside the window. No kill
        # with another weapon before the first or after the last: hidden from the window's start to the end.
        self.assertEqual(render.sniper_spans([], zooms, kills, 5, 0, 60),
                         [(0, 16.5 + render.GUESS_AFTER), (25.0 - render.GUESS_BEFORE, None)])
        # A rifle kill before and after: those edges stay guessed.
        more = kills + [kill(5.0, "ak47"), kill(40.0, "deagle")]
        self.assertEqual(render.sniper_spans([], zooms, more, 5, 0, 60),
                         [(10.0 - render.GUESS_BEFORE, 16.5 + render.GUESS_AFTER),
                          (25.0 - render.GUESS_BEFORE, 25.0 + render.GUESS_AFTER)])
        self.assertEqual(render.sniper_spans([], [], [kill(10.0, "ak47")], 5, 0, 60), [])


if __name__ == "__main__":
    unittest.main()
