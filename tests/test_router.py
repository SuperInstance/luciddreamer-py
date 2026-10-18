"""Routing: which path wins, and in what order.

The precedence order is the contract -- compiled, then negative, then
fuzzy, then fallback -- so most of these tests build a situation where
two paths could both match and assert which one won.
"""

import unittest

from luciddreamer.compiler import RigidFinder
from luciddreamer.router import RouteDecision, Router
from luciddreamer.tiles import CommandTile, Tile, TileStore, TileType


def command(pattern, action, confidence=1.0, **kw):
    t = CommandTile(input_pattern=pattern, output_action=action,
                    confidence=confidence, **kw)
    return t


class TestPrecedence(unittest.TestCase):
    def setUp(self):
        self.store = TileStore()
        self.finder = RigidFinder(self.store)
        self.router = Router(self.store, self.finder)

    def test_an_unknown_phrase_falls_back(self):
        decision, payload = self.router.route("something nobody knows")
        self.assertEqual(decision, RouteDecision.FALLBACK)
        self.assertEqual(payload["action"], "UNKNOWN")

    def test_a_fallback_function_is_used_when_one_is_supplied(self):
        router = Router(self.store, self.finder, fallback_fn=lambda t: {"action": "ASK"})
        decision, payload = router.route("anything")
        self.assertEqual(decision, RouteDecision.FALLBACK)
        self.assertEqual(payload["action"], "ASK")

    def test_a_negative_tile_blocks_the_phrase(self):
        self.store.add(Tile(tile_type=TileType.NEGATIVE,
                            input_pattern="turn to port",
                            output_action="port turn is disabled"))
        decision, payload = self.router.route("turn to port now")
        self.assertEqual(decision, RouteDecision.NEGATIVE)
        self.assertEqual(payload["action"], "BLOCKED")

    def test_a_compiled_command_beats_a_negative_tile(self):
        # Compiled is checked first, so a compiled command still runs
        # even when a negative tile mentions the same words.
        tile = command("turn to port", "TURN_PORT", confidence=1.0)
        tile.times_used = 5
        self.store.add(tile)
        self.finder.try_compile(tile)
        self.store.add(Tile(tile_type=TileType.NEGATIVE,
                            input_pattern="turn to port",
                            output_action="disabled"))
        decision, payload = self.router.route("turn to port")
        self.assertEqual(decision, RouteDecision.COMPILED)
        self.assertEqual(payload["action"], "TURN_PORT")

    def test_a_negative_tile_beats_a_fuzzy_match(self):
        self.store.add(command("turn to port", "TURN_PORT", confidence=0.6))
        self.store.add(Tile(tile_type=TileType.NEGATIVE,
                            input_pattern="turn to port",
                            output_action="disabled"))
        decision, _ = self.router.route("turn to port")
        self.assertEqual(decision, RouteDecision.NEGATIVE)

    def test_a_low_confidence_tile_is_not_executed(self):
        # Below the ambiguous band the router must not act on a tile at
        # all -- it falls through to the fallback.  A tile the captain
        # has never confirmed must never steer the boat.
        self.store.add(command("set depth", "SET_DEPTH", confidence=0.3))
        decision, payload = self.router.route("set depth")
        self.assertEqual(decision, RouteDecision.FALLBACK)
        self.assertNotEqual(payload.get("action"), "SET_DEPTH")

    def test_a_tile_exactly_at_the_ambiguous_floor_is_ambiguous(self):
        self.store.add(command("set depth", "SET_DEPTH", confidence=0.5))
        decision, _ = self.router.route("set depth")
        self.assertEqual(decision, RouteDecision.AMBIGUOUS)

    def test_a_tile_just_below_the_ambiguous_floor_is_not_ambiguous(self):
        self.store.add(command("set depth", "SET_DEPTH", confidence=0.4999))
        decision, _ = self.router.route("set depth")
        self.assertEqual(decision, RouteDecision.FALLBACK)

    def test_a_high_confidence_fuzzy_match_routes_as_compiled(self):
        self.store.add(command("set depth", "SET_DEPTH", confidence=0.8))
        decision, payload = self.router.route("set depth")
        self.assertEqual(decision, RouteDecision.COMPILED)
        self.assertEqual(payload["action"], "SET_DEPTH")

    def test_a_mid_confidence_fuzzy_match_asks_for_confirmation(self):
        self.store.add(command("set depth", "SET_DEPTH", confidence=0.6))
        decision, payload = self.router.route("set depth")
        self.assertEqual(decision, RouteDecision.AMBIGUOUS)
        self.assertIn("confirm", payload["message"].lower())

    def test_a_fuzzy_match_records_the_use(self):
        self.store.add(command("set depth", "SET_DEPTH", confidence=0.8))
        self.router.route("set depth")
        self.router.route("set depth")
        tile = self.store.find_by_pattern("set depth")[0]
        self.assertEqual(tile.times_used, 2)


class TestPendingConfirmation(unittest.TestCase):
    def setUp(self):
        self.store = TileStore()
        self.finder = RigidFinder(self.store)
        self.router = Router(self.store, self.finder)

    def test_a_fallback_leaves_a_pending_entry(self):
        # Only a router WITH a fallback function queues a pending
        # review; without one, route() returns UNKNOWN and records
        # nothing to confirm.
        router = Router(self.store, self.finder, fallback_fn=lambda t: {"action": "ASK"})
        router.route("unknown thing")
        self.assertEqual(router.pending_count, 1)

    def test_a_router_without_a_fallback_queues_nothing(self):
        self.router.route("unknown thing")
        self.assertEqual(self.router.pending_count, 0)

    def test_confirming_a_pending_entry_creates_a_tile(self):
        router = Router(self.store, self.finder, fallback_fn=lambda t: {"action": "ASK"})
        router.route("unknown thing")
        tid = router.confirm_pending(0, correct=True)
        self.assertIsNotNone(tid)
        self.assertIsNotNone(self.store.get(tid))
        self.assertEqual(self.router.pending_count, 0)

    def test_a_correction_becomes_a_correction_tile(self):
        router = Router(self.store, self.finder, fallback_fn=lambda t: {"action": "ASK"})
        router.route("unknown thing")
        tid = router.confirm_pending(0, correct=False, correction="DO_THE_THING")
        tile = self.store.get(tid)
        self.assertEqual(tile.tile_type, TileType.CORRECTION)
        self.assertEqual(tile.output_action, "DO_THE_THING")

    def test_confirming_out_of_range_returns_none(self):
        self.assertIsNone(self.router.confirm_pending(5, correct=True))

    def test_stats_report_the_pending_count(self):
        # stats is a property, not a method.
        router = Router(self.store, self.finder, fallback_fn=lambda t: {"action": "ASK"})
        router.route("unknown thing")
        stats = router.stats
        self.assertEqual(stats.get("pending_reviews"), 1)
        self.assertEqual(stats.get("total_tiles"), 0)
        self.assertEqual(stats.get("coverage"), 0.0)


if __name__ == "__main__":
    unittest.main()
