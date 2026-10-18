"""Save/load round trips.

The store's export/import path is where a tile's type-specific fields
used to die.  These tests are the regression fence around that.
"""

import json
import unittest

from luciddreamer.tiles import (
    ChartTile, CommandTile, Tile, TileStore, TileType, VisionTile,
)


class TestSubclassFieldsSurviveARoundTrip(unittest.TestCase):
    def test_a_command_tile_keeps_its_regex_pattern(self):
        # regex_pattern is the field compiled matching is built on.
        # It was never written by to_dict() and never restored by
        # from_dict(), so a save/load quietly disarmed the store.
        store = TileStore()
        tile = CommandTile(input_pattern="set depth to (\\d+)",
                           output_action="DEPTH",
                           regex_pattern="^set depth to (\\d+)$")
        store.add(tile)
        other = TileStore()
        other.import_json(store.export_json())
        back = other.get(tile.tile_id)
        self.assertEqual(back.regex_pattern, "^set depth to (\\d+)$")

    def test_the_type_survives_the_round_trip(self):
        store = TileStore()
        tile = CommandTile(input_pattern="p", output_action="a")
        store.add(tile)
        other = TileStore()
        other.import_json(store.export_json())
        back = other.get(tile.tile_id)
        self.assertIsInstance(back, CommandTile)
        self.assertEqual(back.tile_type, TileType.COMMAND)

    def test_a_vision_tile_keeps_its_species_and_hold(self):
        store = TileStore()
        tile = VisionTile(input_pattern="salmon", output_action="LAND",
                          species="Salmo salar", hold_number=3,
                          weight_estimate=4.2)
        store.add(tile)
        other = TileStore()
        other.import_json(store.export_json())
        back = other.get(tile.tile_id)
        self.assertIsInstance(back, VisionTile)
        self.assertEqual(back.species, "Salmo salar")
        self.assertEqual(back.hold_number, 3)
        self.assertAlmostEqual(back.weight_estimate, 4.2)

    def test_a_chart_tile_keeps_its_region_and_features(self):
        store = TileStore()
        tile = ChartTile(input_pattern="chart", output_action="CHART",
                         region="42N70W", depth_range=(10.0, 20.0),
                         features=["shoal", "wreck"])
        store.add(tile)
        other = TileStore()
        other.import_json(store.export_json())
        back = other.get(tile.tile_id)
        self.assertIsInstance(back, ChartTile)
        self.assertEqual(back.region, "42N70W")
        self.assertEqual(list(back.features), ["shoal", "wreck"])

    def test_a_tuple_field_comes_back_as_a_tuple(self):
        store = TileStore()
        tile = ChartTile(input_pattern="chart", output_action="CHART",
                         depth_range=(10.0, 20.0))
        store.add(tile)
        other = TileStore()
        other.import_json(store.export_json())
        back = other.get(tile.tile_id)
        self.assertIsInstance(back.depth_range, tuple)

    def test_the_whole_store_survives(self):
        store = TileStore()
        store.add(CommandTile(input_pattern="a", output_action="A",
                              regex_pattern="^a$"))
        store.add(VisionTile(input_pattern="b", output_action="B",
                             species="cod"))
        store.add(ChartTile(input_pattern="c", output_action="C",
                            region="r"))
        other = TileStore()
        self.assertEqual(other.import_json(store.export_json()), 3)
        self.assertEqual(len(other), 3)
        kinds = sorted(type(t).__name__ for t in other)
        self.assertEqual(kinds, ["ChartTile", "CommandTile", "VisionTile"])


class TestTheExportedDocumentIsSelfDescribing(unittest.TestCase):
    def test_the_export_is_valid_json(self):
        store = TileStore()
        store.add(CommandTile(input_pattern="p", output_action="a"))
        blob = store.export_json()
        data = json.loads(blob)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_the_export_records_the_type_and_the_derived_class(self):
        store = TileStore()
        store.add(CommandTile(input_pattern="p", output_action="a",
                              confidence=0.95))
        entry = json.loads(store.export_json())[0]
        self.assertEqual(entry["tile_type"], "command")
        self.assertEqual(entry["confidence_class"], "verified")

    def test_the_derived_fields_are_not_stored_as_inputs(self):
        # tile_id and confidence_class are DERIVED.  Storing them and
        # reading them back would let a tampered file assert an
        # identity the code did not compute.
        store = TileStore()
        store.add(CommandTile(input_pattern="p", output_action="a"))
        entry = json.loads(store.export_json())[0]
        self.assertIn("tile_id", entry)
        self.assertIn("confidence_class", entry)
        # ...but from_dict must recompute them, not trust them.
        entry["tile_id"] = "0" * 16
        entry["confidence_class"] = "compiled"
        tile = Tile.from_dict(entry)
        self.assertNotEqual(tile.tile_id, "0" * 16)
        self.assertNotEqual(tile.confidence_class.value, "compiled")


if __name__ == "__main__":
    unittest.main()
