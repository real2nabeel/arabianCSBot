import unittest

from clips import demo


class TestEncode(unittest.TestCase):
    def test_types(self):
        # byte, short, long, angle (1/256 turn), coord (1/8 unit), entity
        self.assertEqual(demo.encode_args("1:40"), bytes([40]))
        self.assertEqual(demo.encode_args("3:4096"), bytes([0x00, 0x10]))
        self.assertEqual(demo.encode_args("3:-1"), bytes([0xFF, 0xFF]))
        self.assertEqual(demo.encode_args("4:4098"), bytes([0x02, 0x10, 0, 0]))
        self.assertEqual(demo.encode_args("5:90.0"), bytes([64]))
        self.assertEqual(demo.encode_args("6:-12.5"), bytes([0x9C, 0xFF]))
        self.assertEqual(demo.encode_args("8:5"), bytes([5, 0]))
        self.assertEqual(demo.encode_args(""), b"")

    def test_unknown_type(self):
        with self.assertRaises(ValueError):
            demo.encode_args("7:hello")


class TestUserMessage(unittest.TestCase):
    TABLE = {"SetFOV": (95, 1), "ScreenFade": (98, 10), "Varying": (60, 255)}

    def test_fixed_size(self):
        fade = "3:4096,3:512,3:0,1:255,1:255,1:255,1:255"
        self.assertEqual(demo._user_message(self.TABLE, "ScreenFade", fade),
                         bytes([98, 0x00, 0x10, 0x00, 0x02, 0, 0, 255, 255, 255, 255]))
        self.assertEqual(demo._user_message(self.TABLE, "SetFOV", "1:10"), bytes([95, 10]))

    def test_wrong_size_or_unknown_is_dropped(self):
        self.assertEqual(demo._user_message(self.TABLE, "SetFOV", "1:10,1:5"), b"")
        self.assertEqual(demo._user_message(self.TABLE, "Nope", "1:1"), b"")

    def test_variable_size_gets_a_length(self):
        self.assertEqual(demo._user_message(self.TABLE, "Varying", "1:7,1:8"), bytes([60, 2, 7, 8]))

    def test_table_from_demo_bytes(self):
        data = b"xx" + bytes([39, 95, 1]) + b"SetFOV\x00" + b"\x00" * 9 + bytes([39, 71, 12]) + b"Damage\x00"
        self.assertEqual(demo.user_messages(data), {"SetFOV": (95, 1), "Damage": (71, 12)})


def _demo_bytes(times, table_msg, extra=None):
    """A minimal demo: one directory entry holding a network frame at each time, then the end frame."""
    import struct
    frames = b""
    for i, t in enumerate(times):
        msg = (table_msg if i == 0 else b"") + (extra or {}).get(i, b"") + b"\x01"   # svc_nop
        frames += struct.pack("<Bfi", 1, t, i) + b"\x00" * demo.FRAME_INFO_LEN + struct.pack("<i", len(msg)) + msg
    frames += struct.pack("<Bfi", 5, times[-1], len(times))
    offset = demo.HEADER_LEN
    diroff = offset + len(frames)
    header = bytearray(b"HLDEMO\x00\x00" + b"\x00" * (demo.HEADER_LEN - 8))
    struct.pack_into("<i", header, demo.HEADER_LEN - 4, diroff)
    entry = bytearray(demo.ENTRY_LEN)
    struct.pack_into("<ii", entry, 84, offset, len(frames))
    return bytes(header) + frames + struct.pack("<i", 1) + bytes(entry)


class TestSyncMarkers(unittest.TestCase):
    TEXTMSG = bytes([39, 77, 255]) + b"TextMsg\x00"

    def test_console_text(self):
        table = {"TextMsg": (77, 255)}
        self.assertEqual(demo.console_text(table, "hi"), bytes([77, 4, 2]) + b"hi\x00")
        self.assertEqual(demo.console_text({}, "hi"), b"")

    def test_follow_adds_markers_until_the_moment(self):
        import os
        import re
        import tempfile
        times = [i * 0.25 for i in range(13)]   # 0 .. 3 s
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "a.dem"), os.path.join(tmp, "b.dem")
            open(src, "wb").write(_demo_bytes(times, self.TEXTMSG))
            demo.follow(src, dst, entity=3, t0=10, t1=11, sync_until=2.0)
            out = open(dst, "rb").read()
            marks = [float(x) for x in re.findall(rb"\[clipsync\] ([0-9.]+)", out)]
            # none in the frame that registers TextMsg, then every half second until the moment
            self.assertEqual(marks, [0.25, 0.75, 1.25, 1.75])
            self.assertEqual(demo.SYNC_RE.findall("x[clipsync] 1.50y"), ["1.50"])
            self.assertEqual(demo.SYNC_RE.findall("[clipsync] 230.25.\n[clipsync] 7"), ["230.25", "7"])
            # with sync_end: every SYNC_FINE (0.1 s, here every frame of 0.25 s) from the moment on, until sync_end
            demo.follow(src, dst, entity=3, t0=10, t1=11, sync_until=2.0, sync_end=2.8)
            out = open(dst, "rb").read()
            marks = [float(x) for x in re.findall(rb"\[clipsync\] ([0-9.]+)", out)]
            self.assertEqual(marks, [0.25, 0.75, 1.25, 1.75, 2.25, 2.5, 2.75])
            demo.follow(src, dst, entity=3, t0=10, t1=11, commands=(1.0, "host_framerate 0;echo ==SLOW=="))
            out = open(dst, "rb").read()
            self.assertEqual(out.count(b"\x09host_framerate 0;echo ==SLOW==\n\x00"), 1)
            # still a readable demo with the same frames
            self.assertEqual([round(t, 2) for _, _, t, m in demo._frames(out, demo.HEADER_LEN, len(out)) if m],
                             times)


class TestAnimDelay(unittest.TestCase):
    def test_animation_goes_in_a_later_frame(self):
        import os
        import tempfile
        times = [i * 0.02 for i in range(20)]          # a frame every 20 ms
        line = b"\x08[clips] anim t=5.00 p=3 a=5 b=0\x00"   # in the frame at 0.10 s
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "a.dem"), os.path.join(tmp, "b.dem")
            open(src, "wb").write(_demo_bytes(times, b"", extra={5: line}))
            demo.follow(src, dst, entity=3, t0=0, t1=1)
            out = open(dst, "rb").read()
            frames = [(round(t, 2), out[m:fe]) for _, fe, t, m in demo._frames(out, demo.HEADER_LEN, len(out)) if m]
            with_anim = [t for t, body in frames if bytes([demo.SVC_WEAPONANIM, 5, 0]) in body]
            self.assertEqual(with_anim, [0.16])   # 0.10 + ANIM_DELAY, the first frame at or after 0.15


class TestOverlays(unittest.TestCase):
    def test_zooms_and_bars_of_the_followed_player(self):
        import os
        import tempfile
        times = [i * 0.1 for i in range(20)]
        lines = {3: b"\x08[clips] msg t=1.00 p=3 n=SetFOV a=1:40\x00",
                 4: b"\x08[clips] msg t=1.00 p=3 n=SetFOV a=1:40\x00",          # HLTV repeating a line
                 5: b"\x08[clips] msg t=1.10 p=4 n=SetFOV a=1:10\x00",          # another player
                 8: b"\x08[clips] msg t=1.20 p=3 n=BarTime a=3:5\x00",
                 12: b"\x08[clips] msg t=1.30 p=3 n=BarTime2 a=3:10,3:40\x00",
                 15: b"\x08[clips] msg t=1.40 p=3 n=SetFOV a=1:90\x00"}
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.dem")
            open(src, "wb").write(_demo_bytes(times, b"", extra=lines))
            got = demo.overlays(src, entity=3, t0=0, t1=5)
        self.assertEqual(got["zooms"], [(0.3, 40), (1.5, 90)])
        self.assertEqual(got["bars"], [(0.8, 5, 0), (1.2, 10, 40)])
        self.assertEqual(got["weapons"], [])

    def test_weapons_start_with_the_one_held(self):
        import os
        import tempfile
        times = [i * 0.1 for i in range(20)]
        lines = {1: b"\x08[clips] weapon t=1.00 p=3 w=ak47\x00",
                 2: b"\x08[clips] weapon t=1.10 p=3 w=awp\x00",       # before the window: held when it starts
                 6: b"\x08[clips] weapon t=1.50 p=4 w=knife\x00",     # another player
                 9: b"\x08[clips] weapon t=1.80 p=3 w=deagle\x00"}
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.dem")
            open(src, "wb").write(_demo_bytes(times, b"", extra=lines))
            got = demo.overlays(src, entity=3, t0=0.5, t1=5)
        self.assertEqual(got["weapons"], [(0.5, "awp"), (0.9, "deagle")])


class TestCommands(unittest.TestCase):
    def test_several_commands_go_in_at_their_times(self):
        import os
        import tempfile
        times = [i * 0.5 for i in range(8)]
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "a.dem"), os.path.join(tmp, "b.dem")
            open(src, "wb").write(_demo_bytes(times, b""))
            demo.follow(src, dst, entity=3, t0=10, t1=11,
                        commands=[(2.0, "crosshair 1"), (0.9, "crosshair 0"), (0.1, "echo a")])
            out = open(dst, "rb").read()
        frames = [(round(t, 2), out[m:m + 200]) for _, _, t, m in demo._frames(out, demo.HEADER_LEN, len(out)) if m]
        at = {cmd: next(t for t, body in frames if b"\x09" + cmd + b"\n\x00" in body)
              for cmd in (b"echo a", b"crosshair 0", b"crosshair 1")}
        self.assertEqual(at, {b"echo a": 0.5, b"crosshair 0": 1.0, b"crosshair 1": 2.0})

    def test_a_list_of_one_command(self):
        import os
        import tempfile
        times = [i * 0.5 for i in range(8)]
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "a.dem"), os.path.join(tmp, "b.dem")
            open(src, "wb").write(_demo_bytes(times, b""))
            demo.follow(src, dst, entity=3, t0=10, t1=11, commands=[(1.0, "echo a")])
            out = open(dst, "rb").read()
        self.assertEqual(out.count(b"\x09echo a\n\x00"), 1)


if __name__ == "__main__":
    unittest.main()
