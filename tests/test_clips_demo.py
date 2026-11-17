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


def _demo_bytes(times, table_msg):
    """A minimal demo: one directory entry holding a network frame at each time, then the end frame."""
    import struct
    frames = b""
    for i, t in enumerate(times):
        msg = (table_msg if i == 0 else b"") + b"\x01"   # svc_nop
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
            # still a readable demo with the same frames
            self.assertEqual([round(t, 2) for _, _, t, m in demo._frames(out, demo.HEADER_LEN, len(out)) if m],
                             times)


if __name__ == "__main__":
    unittest.main()
