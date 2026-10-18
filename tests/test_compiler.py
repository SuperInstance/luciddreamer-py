"""The compiler: when does a soft behaviour become hard code?

The gates are the whole point of the module, so most of these tests
assert that something did NOT compile.
"""

import re
import unittest

from luciddreamer.compiler import CompiledCommand, RigidFinder
from luciddreamer.tiles import CommandTile, TileStore, TileType


def command(confidence=1.0, uses=3, corrected=0, **kw):
    t = CommandTile(input_pattern=kw.pop("input_pattern", "set depth to 12"),
                    output_action=kw.pop("output_action", "DEPTH_SET_12"),
                    confidence=confidence, **kw)
    t.times_used = uses
    t.times_corrected = corrected
    t.times_correct = max(0, uses - corrected)
    return t


class TestCompileGates(unittest.TestCase):
    def setUp(self):
        self.store = TileStore()
        self.finder = RigidFinder(self.store)

    def test_a_fully_confident_well_used_tile_compiles(self):
        tile = command(confidence=1.0, uses=3)
        self.store.add(tile)
        cmd = self.finder.try_compile(tile)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.action, "DEPTH_SET_12")

    def test_a_tile_below_the_confidence_threshold_does_not_compile(self):
        tile = command(confidence=0.97, uses=100)
        self.store.add(tile)
        self.assertIsNone(self.finder.try_compile(tile))

    def test_a_tile_at_the_confidence_threshold_does_compile(self):
        tile = command(confidence=0.975, uses=3)
        self.store.add(tile)
        self.assertIsNotNone(self.finder.try_compile(tile))

    def test_a_tile_with_too_few_uses_does_not_compile(self):
        tile = command(confidence=1.0, uses=2)
        self.store.add(tile)
        self.assertIsNone(self.finder.try_compile(tile))

    def test_a_tile_with_too_many_corrections_does_not_compile(self):
        # 1 correction in 3 uses is a 33% error rate, over the 5%
        # stability threshold, even at full confidence.
        tile = command(confidence=1.0, uses=3, corrected=1)
        self.store.add(tile)
        self.assertIsNone(self.finder.try_compile(tile))

    def test_a_single_correction_in_many_uses_still_compiles(self):
        tile = command(confidence=1.0, uses=100, corrected=1)
        self.store.add(tile)
        self.assertIsNotNone(self.finder.try_compile(tile))

    def test_a_non_command_tile_never_compiles(self):
        from luciddreamer.tiles import VisionTile
        tile = VisionTile(input_pattern="salmon", output_action="LAND",
                          confidence=1.0)
        tile.times_used = 100
        self.store.add(tile)
        self.assertIsNone(self.finder.try_compile(tile))

    def test_compile_all_only_returns_the_tiles_that_pass(self):
        self.store.add(command(confidence=1.0, uses=3, output_action="OK"))
        self.store.add(command(confidence=0.5, uses=3, output_action="TOO_LOW"))
        self.store.add(command(confidence=1.0, uses=1, output_action="TOO_FEW"))
        compiled = self.finder.compile_all()
        self.assertEqual([c.action for c in compiled], ["OK"])


class TestCompiledMatching(unittest.TestCase):
    def setUp(self):
        self.store = TileStore()
        self.finder = RigidFinder(self.store)

    def test_a_compiled_command_matches_its_own_text(self):
        tile = command(confidence=1.0, uses=3)
        tile.regex_pattern = r"^set depth to (?P<n>\d+)$"
        self.store.add(tile)
        self.finder.try_compile(tile)
        result = self.finder.match("set depth to 12")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("n"), "12")

    def test_text_outside_the_pattern_does_not_match(self):
        tile = command(confidence=1.0, uses=3)
        tile.regex_pattern = r"^set depth to (?P<n>\d+)$"
        self.store.add(tile)
        self.finder.try_compile(tile)
        self.assertIsNone(self.finder.match("set depth to twelve"))

    def test_the_auto_pattern_escapes_regex_metacharacters(self):
        tile = command(confidence=1.0, uses=3, input_pattern="a.b(c)")
        self.store.add(tile)
        self.finder.try_compile(tile)
        # The dot must not act as a wildcard.
        self.assertIsNone(self.finder.match("axb(c)"))
        self.assertIsNotNone(self.finder.match("a.b(c)"))

    def test_the_auto_pattern_turns_digits_into_a_named_group(self):
        tile = command(confidence=1.0, uses=3, input_pattern="set depth to 12")
        self.store.add(tile)
        self.finder.try_compile(tile)
        result = self.finder.match("set depth to 30")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("n"), "30")

    def test_the_auto_pattern_makes_a_trailing_e_optional(self):
        tile = command(confidence=1.0, uses=3, input_pattern="raise depth")
        self.store.add(tile)
        self.finder.try_compile(tile)
        self.assertIsNotNone(self.finder.match("raise depth"))
        self.assertIsNotNone(self.finder.match("raises depth"))
        self.assertIsNone(self.finder.match("raised depth"))

    def test_two_digit_groups_get_distinct_names(self):
        # Two groups with the same name are a re.error at match time,
        # so the second one has to be numbered.
        tile = command(confidence=1.0, uses=3,
                       input_pattern="set depth 12 and speed 30")
        self.store.add(tile)
        self.finder.try_compile(tile)
        result = self.finder.match("set depth 15 and speed 20")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("n"), "15")
        self.assertEqual(result.get("n2"), "20")


class TestCoverage(unittest.TestCase):
    def test_coverage_of_an_empty_store_is_zero(self):
        self.assertEqual(RigidFinder(TileStore()).coverage, 0.0)

    def test_coverage_counts_the_confident_tiles(self):
        store = TileStore()
        store.add(command(confidence=1.0, uses=3, output_action="A"))
        store.add(command(confidence=0.5, uses=3, output_action="B"))
        finder = RigidFinder(store)
        self.assertAlmostEqual(finder.coverage, 0.5)

    def test_compiled_count_reflects_what_was_compiled(self):
        store = TileStore()
        tile = command(confidence=1.0, uses=3)
        store.add(tile)
        finder = RigidFinder(store)
        self.assertEqual(finder.compiled_count, 0)
        finder.try_compile(tile)
        self.assertEqual(finder.compiled_count, 1)


class TestCompiledCommand(unittest.TestCase):
    def test_match_returns_none_for_non_matching_text(self):
        cmd = CompiledCommand(pattern=r"^hello$", action="GREET")
        self.assertIsNone(cmd.match("goodbye"))
        self.assertIsNotNone(cmd.match("hello"))

    def test_a_malformed_pattern_raises_at_construction(self):
        # CompiledCommand compiles eagerly, so a bad pattern is loud
        # rather than silently matching nothing.
        with self.assertRaises(re.error):
            CompiledCommand(pattern="([unclosed", action="X")

    def test_one_malformed_tile_does_not_kill_the_whole_pass(self):
        # Regression: a single tile with a bad regex raised out of
        # try_compile() and compile_all(), so every other tile in the
        # store went uncompiled because of one bad one.
        store = TileStore()
        good = command(confidence=1.0, uses=5, output_action="GOOD")
        store.add(good)
        bad = command(confidence=1.0, uses=5, output_action="BAD")
        bad.regex_pattern = "([unclosed"
        store.add(bad)
        finder = RigidFinder(store)
        compiled = finder.compile_all()
        self.assertEqual([c.action for c in compiled], ["GOOD"])


if __name__ == "__main__":
    unittest.main()
