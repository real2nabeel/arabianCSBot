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


if __name__ == "__main__":
    unittest.main()
