"""Unit tests for the Discord activity leveling math (utils/leveling.py).

Pure functions, no Discord or DB — run with:  python -m unittest
Because real money rides on these thresholds, the boundaries are pinned exactly.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.leveling import (  # noqa: E402
    LEVEL_THRESHOLDS, MAX_LEVEL, DEFAULT_RANK_NAMES,
    level_from_xp, xp_for_level, level_progress, is_max_level, progress_bar,
)


class TestLevelFromXp(unittest.TestCase):
    def test_zero_xp_is_level_zero(self):
        self.assertEqual(level_from_xp(0), 0)

    def test_just_below_first_threshold(self):
        self.assertEqual(level_from_xp(49), 0)

    def test_exact_thresholds_map_to_their_level(self):
        # Reaching a threshold exactly should award that level (e.g. 50 -> L1).
        for level, threshold in enumerate(LEVEL_THRESHOLDS):
            self.assertEqual(
                level_from_xp(threshold), level,
                msg=f"{threshold} XP should be level {level}")

    def test_named_boundaries(self):
        self.assertEqual(level_from_xp(50), 1)       # Silver I
        self.assertEqual(level_from_xp(1000), 6)     # Silver Elite Master
        self.assertEqual(level_from_xp(15000), 18)   # Global Elite

    def test_caps_at_max_level(self):
        self.assertEqual(level_from_xp(15000), MAX_LEVEL)
        self.assertEqual(level_from_xp(10 ** 9), MAX_LEVEL)

    def test_monotonic_non_decreasing(self):
        prev = 0
        for xp in range(0, 16000, 25):
            level = level_from_xp(xp)
            self.assertGreaterEqual(level, prev)
            prev = level


class TestXpForLevel(unittest.TestCase):
    def test_matches_threshold_table(self):
        for level, threshold in enumerate(LEVEL_THRESHOLDS):
            self.assertEqual(xp_for_level(level), threshold)

    def test_clamps_out_of_range(self):
        self.assertEqual(xp_for_level(-5), 0)
        self.assertEqual(xp_for_level(MAX_LEVEL + 10), LEVEL_THRESHOLDS[MAX_LEVEL])

    def test_roundtrip_with_level_from_xp(self):
        # The XP that defines a level must resolve back to that level.
        for level in range(MAX_LEVEL + 1):
            self.assertEqual(level_from_xp(xp_for_level(level)), level)


class TestLevelProgress(unittest.TestCase):
    def test_progress_components_sum_correctly(self):
        for xp in (0, 75, 600, 3500, 9999):
            level, into, needed = level_progress(xp)
            floor = xp_for_level(level)
            self.assertEqual(into, xp - floor)
            self.assertEqual(needed, LEVEL_THRESHOLDS[level + 1] - floor)
            self.assertTrue(0 <= into < needed)

    def test_max_level_has_no_remaining_progress(self):
        level, into, needed = level_progress(15000)
        self.assertEqual(level, MAX_LEVEL)
        self.assertEqual((into, needed), (0, 0))
        self.assertTrue(is_max_level(level))


class TestProgressBar(unittest.TestCase):
    def test_width_is_constant(self):
        self.assertEqual(len(progress_bar(0, 100, width=20)), 20)
        self.assertEqual(len(progress_bar(100, 100, width=20)), 20)

    def test_empty_and_full(self):
        self.assertEqual(progress_bar(0, 100, width=10), "░" * 10)
        self.assertEqual(progress_bar(100, 100, width=10), "█" * 10)

    def test_maxed_bar_is_full(self):
        # needed == 0 (max level) should render a full bar, not crash.
        self.assertEqual(progress_bar(0, 0, width=10), "█" * 10)

    def test_half(self):
        self.assertEqual(progress_bar(50, 100, width=10).count("█"), 5)


class TestThresholdTableIntegrity(unittest.TestCase):
    def test_strictly_increasing(self):
        for a, b in zip(LEVEL_THRESHOLDS, LEVEL_THRESHOLDS[1:]):
            self.assertLess(a, b)

    def test_starts_at_zero(self):
        self.assertEqual(LEVEL_THRESHOLDS[0], 0)

    def test_rank_names_cover_every_level(self):
        # Exactly one name per level 1..MAX_LEVEL, so /levelrole import is total.
        self.assertEqual(sorted(DEFAULT_RANK_NAMES), list(range(1, MAX_LEVEL + 1)))


if __name__ == "__main__":
    unittest.main()
