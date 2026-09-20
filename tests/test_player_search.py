"""Unit tests for player-name search / resolution (utils/database.py).

The pure helpers run as-is; ``resolve_player`` is exercised against a fake
connection pool that emulates MySQL's LIKE semantics in Python, so the whole
resolution ladder (exact -> normalized -> prefix -> fuzzy) is covered without a
database. Run with:  python -m unittest discover -s tests
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import (  # noqa: E402
    Database, escape_like, nick_tokens, normalize_nick, rank_by_similarity,
    similarity, subsequence_pattern,
)


def _like_to_regex(pattern):
    """Translate a MySQL LIKE pattern (backslash-escaped) to a regex."""
    out, i = [], 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if char == "%" else "." if char == "_" else re.escape(char))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE | re.DOTALL)


class FakeDatabase(Database):
    """A Database whose fetch_all answers the two search queries from an
    in-memory player list, emulating LIKE and the ORDER BY."""

    def __init__(self, players):
        # players: list of (Player, Nick, XP)
        self.rows = [{"Player": p, "Nick": n, "XP": xp} for p, n, xp in players]
        self.queries = 0

    async def fetch_all(self, query, args=None):
        self.queries += 1
        if len(args) == 4:  # substring pass: (name, prefix, contains, limit)
            name, prefix, contains, limit = args
            matcher = _like_to_regex(contains)
            prefix_matcher = _like_to_regex(prefix)
            hits = []
            for row in self.rows:
                if not matcher.match(row["Nick"]):
                    continue
                if row["Nick"].lower() == name.lower():
                    rank = 0
                elif prefix_matcher.match(row["Nick"]):
                    rank = 1
                else:
                    rank = 2
                hits.append(dict(row, match_rank=rank))
            hits.sort(key=lambda r: (r["match_rank"], -r["XP"]))
            return hits[:limit]

        subsequence, limit = args  # fuzzy pass
        matcher = _like_to_regex(subsequence)
        hits = [dict(r) for r in self.rows if matcher.match(r["Nick"])]
        hits.sort(key=lambda r: -r["XP"])
        return hits[:limit]


ROSTER = [
    ("STEAM_1", "[AR]*Nabeel*", 5000),
    ("STEAM_2", "NabeelJr", 900),
    ("STEAM_3", "Khaled", 4200),
    ("STEAM_4", "خالد", 3100),
    ("STEAM_5", "sniper|pro", 2500),
]


class TestHelpers(unittest.TestCase):
    def test_escape_like_neutralizes_wildcards(self):
        self.assertEqual(escape_like("100%_x"), "100\\%\\_x")
        self.assertEqual(escape_like("a\\b"), "a\\\\b")

    def test_normalize_strips_decoration_keeps_letters(self):
        self.assertEqual(normalize_nick("[AR]*Nabeel*"), "arnabeel")
        self.assertEqual(normalize_nick("N a B e E l"), "nabeel")

    def test_normalize_preserves_non_latin_scripts(self):
        self.assertEqual(normalize_nick(" خالد "), "خالد")

    def test_normalize_handles_none(self):
        self.assertEqual(normalize_nick(None), "")

    def test_nick_tokens_splits_off_clan_tags(self):
        self.assertEqual(nick_tokens("[AR]*Nabeel*"), ["ar", "nabeel"])
        self.assertEqual(nick_tokens("sniper|pro"), ["sniper", "pro"])
        self.assertEqual(nick_tokens(None), [])

    def test_subsequence_pattern_spans_characters_in_order(self):
        self.assertEqual(subsequence_pattern("nbe"), "%n%b%e%")
        self.assertEqual(subsequence_pattern("a b"), "%a%b%")
        self.assertEqual(subsequence_pattern(""), "%")

    def test_similarity_ignores_decoration(self):
        self.assertGreater(similarity("nabeel", "[AR]*Nabeel*"), 0.7)
        self.assertGreater(similarity("nabel", "Nabeel"), 0.8)
        self.assertEqual(similarity("nabeel", ""), 0.0)

    def test_rank_by_similarity_orders_best_first(self):
        rows = [{"Nick": "Khaled", "XP": 1}, {"Nick": "Nabeel", "XP": 1}]
        self.assertEqual(rank_by_similarity("nabeel", rows)[0][1]["Nick"], "Nabeel")


class TestResolvePlayer(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDatabase(ROSTER)

    async def assert_resolves(self, query, nick):
        key, resolved, mode = await self.db.resolve_player(query)
        self.assertEqual((mode, resolved), (0, nick), f"query={query!r}")
        self.assertTrue(key)

    async def test_exact_nick(self):
        await self.assert_resolves("Khaled", "Khaled")

    async def test_case_insensitive(self):
        await self.assert_resolves("kHaLeD", "Khaled")

    async def test_substring_of_a_single_player(self):
        await self.assert_resolves("hale", "Khaled")

    async def test_bare_name_matches_decorated_nick(self):
        # Both nicks contain "nabeel"; only "[AR]*Nabeel*" has it as a whole
        # word, which beats "NabeelJr" merely starting with it.
        await self.assert_resolves("nabeel", "[AR]*Nabeel*")

    async def test_unique_prefix_of_one_word_resolves(self):
        await self.assert_resolves("snip", "sniper|pro")

    async def test_typo_resolves_via_fuzzy_fallback(self):
        # "khald" is a substring of nothing; the subsequence scan finds Khaled.
        await self.assert_resolves("khald", "Khaled")

    async def test_non_latin_nick(self):
        await self.assert_resolves("خالد", "خالد")

    async def test_wildcard_is_not_a_wildcard(self):
        _, _, mode = await self.db.resolve_player("%")
        self.assertEqual(mode, -1)

    async def test_special_characters_are_matched_literally(self):
        await self.assert_resolves("sniper|pro", "sniper|pro")

    async def test_partial_shared_by_two_players_asks(self):
        # "nabee" prefixes a word of both nicks — the user picks, we don't guess.
        _, candidates, mode = await self.db.resolve_player("nabee")
        self.assertEqual(mode, 1)
        self.assertCountEqual(candidates, ["[AR]*Nabeel*", "NabeelJr"])

    async def test_duplicate_nicks_resolve_to_the_ranked_player(self):
        db = FakeDatabase([("STEAM_A", "player", 10), ("STEAM_B", "player", 99)])
        key, nick, mode = await db.resolve_player("player")
        self.assertEqual((key, nick, mode), ("STEAM_B", "player", 0))

    async def test_unknown_name_reports_not_found(self):
        key, nick, mode = await self.db.resolve_player("zzzzzzzz")
        self.assertEqual((key, nick, mode), (None, None, -1))

    async def test_blank_query_never_hits_the_database(self):
        key, nick, mode = await self.db.resolve_player("   ")
        self.assertEqual((key, nick, mode), (None, None, -1))
        self.assertEqual(self.db.queries, 0)


class TestSearchPlayers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDatabase(ROSTER)

    async def test_prefix_matches_come_before_mere_substrings(self):
        names = await self.db.search_players("nabeel")
        self.assertEqual(names[0], "NabeelJr")

    async def test_suggests_on_typo(self):
        self.assertIn("Khaled", await self.db.search_players("khald"))

    async def test_deduplicates_shared_nicks(self):
        db = FakeDatabase([("STEAM_A", "player", 10), ("STEAM_B", "Player", 99)])
        self.assertEqual(len(await db.search_players("play")), 1)

    async def test_limit_is_respected(self):
        self.assertLessEqual(len(await self.db.search_players("a", limit=2)), 2)


if __name__ == "__main__":
    unittest.main()
