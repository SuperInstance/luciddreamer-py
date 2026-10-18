"""Tiles: identity, confidence dynamics, classification, and round-tripping.

Every assertion here is about behaviour that a reader of the docstring
could not have predicted, and several of them are written so that a
plausible-looking mutation of the implementation breaks them.
"""

import hashlib
import unittest

from luciddreamer.tiles import (
    ChartTile, CommandTile, Confidence, Tile, TileStore, TileType, Verifier, VisionTile,
)


def make_command(pattern="set depth to 12", action="DEPTH_SET_12", **kw):
    # CommandTile pins its own tile_type with init=False.
    return CommandTile(
        input_pattern=pattern,
        output_action=action,
        **kw,
    )


class TestTileIdentity(unittest.TestCase):
    def test_tile_id_is_the_documented_sha256_prefix(self):
        tile = make_command()
        content = f"{TileType.COMMAND.value}:{tile.input_pattern}:{tile.output_action}"
        expected = hashlib.sha256(content.encode()).hexdigest()[:16]
        self.assertEqual(tile.tile_id, expected)
        self.assertEqual(len(tile.tile_id), 16)

    def test_tile_id_is_stable_across_instances(self):
        self.assertEqual(make_command().tile_id, make_command().tile_id)

    def test_tile_id_depends_on_all_three_parts(self):
        base = make_command()
        self.assertNotEqual(base.tile_id, make_command(pattern="other").tile_id)
        self.assertNotEqual(base.tile_id, make_command(action="OTHER").tile_id)
        self.assertNotEqual(base.tile_id,
                            make_command(pattern="x", action="y").tile_id)

    def test_a_different_tile_type_is_a_different_tile(self):
        a = Tile(tile_type=TileType.COMMAND, input_pattern="p", output_action="a")
        b = Tile(tile_type=TileType.VISION, input_pattern="p", output_action="a")
        self.assertNotEqual(a.tile_id, b.tile_id)


class TestConfidenceDynamics(unittest.TestCase):
    def test_a_correct_use_adds_exactly_two_percent(self):
        tile = make_command(confidence=0.5)
        tile.record_use(True)
        self.assertAlmostEqual(tile.confidence, 0.52)
        self.assertEqual(tile.times_used, 1)
        self.assertEqual(tile.times_correct, 1)
        self.assertEqual(tile.times_corrected, 0)

    def test_a_wrong_use_subtracts_exactly_ten_percent(self):
        tile = make_command(confidence=0.5)
        tile.record_use(False)
        self.assertAlmostEqual(tile.confidence, 0.40)
        self.assertEqual(tile.times_corrected, 1)
        self.assertEqual(tile.times_correct, 0)

    def test_confidence_is_capped_at_one(self):
        tile = make_command(confidence=0.99)
        tile.record_use(True)
        self.assertEqual(tile.confidence, 1.0)
        for _ in range(50):
            tile.record_use(True)
        self.assertEqual(tile.confidence, 1.0)

    def test_confidence_is_floored_at_zero(self):
        tile = make_command(confidence=0.05)
        tile.record_use(False)
        self.assertEqual(tile.confidence, 0.0)
        for _ in range(50):
            tile.record_use(False)
        self.assertEqual(tile.confidence, 0.0)

    def test_success_rate_of_a_never_used_tile_is_its_confidence(self):
        # This is a deliberate design choice and a subtle one: an unused
        # tile has no observed success rate, so the property falls back
        # to the prior.  It is also the trap a mutation would fall into.
        tile = make_command(confidence=0.8)
        self.assertEqual(tile.times_used, 0)
        self.assertEqual(tile.success_rate, 0.8)

    def test_success_rate_counts_observations_not_the_prior(self):
        tile = make_command(confidence=0.8)
        tile.record_use(True)
        tile.record_use(False)
        self.assertEqual(tile.success_rate, 0.5)


class TestConfidenceClass(unittest.TestCase):
    def test_the_boundaries_are_inclusive_at_the_bottom(self):
        cases = [
            (1.00, Confidence.COMPILED),
            (0.90, Confidence.VERIFIED),
            (0.70, Confidence.TENTATIVE),
            (0.50, Confidence.AMBIGUOUS),
            (0.49, Confidence.UNKNOWN),
            (0.00, Confidence.UNKNOWN),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(make_command(confidence=value).confidence_class, expected)

    def test_a_tile_just_below_a_boundary_is_not_promoted(self):
        self.assertEqual(make_command(confidence=0.8999).confidence_class,
                         Confidence.TENTATIVE)
        self.assertEqual(make_command(confidence=0.6999).confidence_class,
                         Confidence.AMBIGUOUS)


class TestSerialisation(unittest.TestCase):
    def test_to_dict_then_from_dict_is_a_fixed_point(self):
        tile = make_command(confidence=0.75, source="captain", trip_id="T1",
                            vessel="MV Test")
        tile.record_use(True)
        again = Tile.from_dict(tile.to_dict())
        self.assertEqual(again.to_dict(), tile.to_dict())

    def test_from_dict_ignores_the_derived_fields(self):
        data = make_command().to_dict()
        data["tile_id"] = "deadbeefdeadbeef"
        data["confidence_class"] = "nonsense"
        data["success_rate"] = 42.0
        tile = Tile.from_dict(data)
        self.assertNotEqual(tile.tile_id, "deadbeefdeadbeef")
        self.assertNotEqual(tile.success_rate, 42.0)

    def test_the_serialised_form_carries_the_classification(self):
        d = make_command(confidence=0.95).to_dict()
        self.assertEqual(d["confidence_class"], Confidence.VERIFIED.value)
        self.assertEqual(d["tile_type"], TileType.COMMAND.value)
        self.assertEqual(d["verifier"], Verifier.MODEL.value)


class TestTileStore(unittest.TestCase):
    def setUp(self):
        self.store = TileStore()

    def test_add_returns_the_tile_id_and_stores_the_tile(self):
        tile = make_command()
        tid = self.store.add(tile)
        self.assertEqual(tid, tile.tile_id)
        self.assertIs(self.store.get(tid), tile)

    def test_get_returns_none_for_an_unknown_id(self):
        self.assertIsNone(self.store.get("nope"))

    def test_find_by_pattern_is_exact_or_regex_not_substring(self):
        # find_by_pattern() matches the query against the TILE's regex,
        # so a bare substring does not match.  "depth" finds nothing.
        self.store.add(make_command(pattern="set depth to 12"))
        self.store.add(make_command(pattern="set depth to 30", action="DEPTH_SET_30"))
        self.store.add(make_command(pattern="turn to port", action="TURN_PORT"))
        self.assertEqual(len(self.store.find_by_pattern("depth")), 0)
        self.assertEqual(len(self.store.find_by_pattern("set depth to 12")), 1)
        self.assertEqual(len(self.store.find_by_pattern("set depth to 30")), 1)

    def test_find_by_pattern_applies_the_tiles_own_regex(self):
        tile = make_command(pattern="set depth to (\\d+)", action="DEPTH")
        tile.regex_pattern = r"^set depth to (\d+)$"
        self.store.add(tile)
        self.assertEqual(len(self.store.find_by_pattern("set depth to 12")), 1)
        self.assertEqual(len(self.store.find_by_pattern("set depth to abc")), 0)

    def test_find_by_pattern_sorts_by_confidence_descending(self):
        self.store.add(make_command(pattern="cmd", action="LOW", confidence=0.3))
        self.store.add(make_command(pattern="cmd", action="HIGH", confidence=0.95))
        # both share the pattern, so both match exactly
        results = self.store.find_by_pattern("cmd")
        self.assertEqual([r.output_action for r in results], ["HIGH", "LOW"])

    def test_find_by_pattern_swallows_an_invalid_tile_regex(self):
        tile = make_command(pattern="cmd")
        tile.regex_pattern = "([unclosed"
        self.store.add(tile)
        self.assertEqual(len(self.store.find_by_pattern("cmd")), 1)

    def test_find_by_type_selects_one_type(self):
        self.store.add(make_command())
        self.store.add(VisionTile(input_pattern="obstacle ahead",
                                  output_action="AVOID"))
        self.assertEqual(len(self.store.find_by_type(TileType.COMMAND)), 1)
        self.assertEqual(len(self.store.find_by_type(TileType.VISION)), 1)

    def test_find_compiled_only_returns_fully_confident_tiles(self):
        # find_compiled() is confidence >= 1.0, which is exactly the
        # COMPILED class -- a 0.95 tile is VERIFIED, not compiled.
        self.store.add(make_command(confidence=1.0, action="A"))
        self.store.add(make_command(confidence=0.95, action="B"))
        self.store.add(make_command(confidence=0.5, action="C"))
        compiled = self.store.find_compiled()
        self.assertEqual([t.output_action for t in compiled], ["A"])

    def test_find_ambiguous_excludes_compiled_tiles(self):
        self.store.add(make_command(confidence=1.0, action="A"))
        self.store.add(make_command(confidence=0.5, action="B"))
        ambiguous = self.store.find_ambiguous()
        self.assertEqual([t.output_action for t in ambiguous], ["B"])

    def test_find_ambiguous_spans_the_tentative_class_too(self):
        # The band is [0.5, 0.9), and confidence_class() calls
        # [0.70, 0.90) TENTATIVE -- so find_ambiguous() returns tiles
        # that are not AMBIGUOUS by class.  The name is narrower than
        # the behaviour; this pins the actual behaviour.
        self.store.add(make_command(confidence=0.75, action="TENTATIVE"))
        self.store.add(make_command(confidence=0.55, action="AMBIG"))
        self.assertEqual(len(self.store.find_ambiguous()), 2)

    def test_adding_the_same_tile_twice_does_not_double_index_it(self):
        # Regression: the type index held the id twice, so
        # find_by_type() returned the SAME tile twice while len(store)
        # said 1.  A consumer counting tiles by type double-counted.
        tile = make_command()
        self.store.add(tile)
        self.store.add(tile)
        self.assertEqual(len(self.store), 1)
        self.assertEqual(len(self.store.find_by_type(TileType.COMMAND)), 1)

    def test_remove_reports_whether_it_removed_anything(self):
        tid = self.store.add(make_command())
        self.assertTrue(self.store.remove(tid))
        self.assertFalse(self.store.remove(tid))
        self.assertEqual(len(self.store), 0)

    def test_export_import_round_trips_the_store(self):
        self.store.add(make_command(confidence=0.9, action="A"))
        self.store.add(make_command(pattern="other", action="B"))
        blob = self.store.export_json()
        other = TileStore()
        n = other.import_json(blob)
        self.assertEqual(n, 2)
        self.assertEqual(len(other), 2)
        self.assertEqual(sorted(t.output_action for t in other), ["A", "B"])

    def test_iteration_yields_every_tile(self):
        for i in range(3):
            self.store.add(make_command(pattern=f"p{i}", action=f"a{i}"))
        self.assertEqual(len(list(self.store)), 3)


class TestSubclasses(unittest.TestCase):
    def test_chart_tile_keeps_its_own_fields_through_serialisation(self):
        tile = ChartTile(input_pattern="chart", output_action="CHART",
                         region="42N70W", depth_range=(10.0, 20.0),
                         features=["shoal", "wreck"])
        again = Tile.from_dict(tile.to_dict())
        self.assertEqual(again.region, "42N70W")
        self.assertEqual(tuple(again.depth_range), (10.0, 20.0))
        self.assertEqual(list(again.features), ["shoal", "wreck"])
        self.assertEqual(again.tile_type, TileType.CHART)


if __name__ == "__main__":
    unittest.main()
