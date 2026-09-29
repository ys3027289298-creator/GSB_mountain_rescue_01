import json
import unittest

from mountain.core import (
    DEFAULT_SEED,
    FUEL_PER_FLIGHT,
    HELICOPTER_CAPACITY,
    RADIO_CHANNELS,
    SHELTER_CAPACITY,
    CommandError,
    RescueGame,
)


class SplitSuppliesTest(unittest.TestCase):
    def test_split_deducts_shared_supplies_once(self):
        game = RescueGame()
        game.execute("split alpha bravo")
        alpha = game.teams["alpha"]["supplies"]
        bravo = game.teams["bravo"]["supplies"]
        self.assertEqual(alpha, 5)
        self.assertEqual(bravo, 5)
        self.assertEqual(alpha + bravo, 10)

    def test_split_twice_keeps_conservation(self):
        game = RescueGame()
        game.execute("split alpha bravo")
        game.execute("split bravo charlie")
        total = sum(t["supplies"] for t in game.teams.values())
        self.assertEqual(total, 10)


class AvalancheRoadTest(unittest.TestCase):
    def test_blocked_road_prevents_entry(self):
        game = RescueGame()
        game.execute("move alpha camp")
        game.blocked["camp|north"] = 2
        with self.assertRaises(CommandError):
            game.execute("move alpha north")
        self.assertEqual(game.teams["alpha"]["location"], "camp")

    def test_storm_blocks_road_and_move_fails(self):
        game = RescueGame(seed=DEFAULT_SEED)
        for _ in range(20):
            game.execute("advance")
            if game.blocked:
                break
        self.assertTrue(game.blocked, "fixed seed should produce a storm")
        road = next(iter(game.blocked))
        a, b = road.split("|")
        game.teams["alpha"]["location"] = a
        with self.assertRaises(CommandError):
            game.execute("move alpha %s" % b)


class InjuredTransferTest(unittest.TestCase):
    def test_transfer_removes_injured_from_origin(self):
        game = RescueGame()
        game.execute("injured north")
        game.execute("transfer injured-1 camp")
        self.assertNotIn("injured-1", game.locations["north"]["injured"])
        self.assertIn("injured-1", game.locations["camp"]["injured"])

    def test_transfer_from_helicopter_clears_onboard(self):
        game = RescueGame()
        game.execute("injured base")
        game.execute("board injured-1")
        game.execute("transfer injured-1 shelter")
        self.assertNotIn("injured-1", game.helicopter["onboard"])
        self.assertIn("injured-1", game.locations["shelter"]["injured"])


class HelicopterFuelTest(unittest.TestCase):
    def test_fuel_never_goes_negative(self):
        game = RescueGame()
        hops = 100 // FUEL_PER_FLIGHT
        for i in range(hops):
            game.execute("fly camp" if i % 2 == 0 else "fly base")
        self.assertEqual(game.helicopter["fuel"], 0)
        with self.assertRaises(CommandError):
            game.execute("fly camp")
        self.assertEqual(game.helicopter["fuel"], 0)
        self.assertGreaterEqual(game.helicopter["fuel"], 0)


class WeatherHazardTest(unittest.TestCase):
    def test_weather_improvement_does_not_clear_hazards_early(self):
        game = RescueGame()
        game.locations["peak"]["hazards"]["avalanche"] = 2
        game.execute("advance")
        self.assertIn("avalanche", game.locations["peak"]["hazards"])
        game.execute("advance")
        self.assertNotIn("avalanche", game.locations["peak"]["hazards"])

    def test_blocked_road_expires_on_own_timer(self):
        game = RescueGame()
        game.blocked["camp|north"] = 2
        game.execute("advance")
        self.assertIn("camp|north", game.blocked)
        game.execute("advance")
        self.assertNotIn("camp|north", game.blocked)


class RadioChannelTest(unittest.TestCase):
    def test_cancel_restores_radio_channel(self):
        game = RescueGame()
        game.execute("signal north")
        self.assertEqual(len(game.channels), len(RADIO_CHANNELS) - 1)
        game.execute("cancel M1")
        self.assertEqual(sorted(game.channels), sorted(RADIO_CHANNELS))
        self.assertEqual(game.missions, {})
        self.assertEqual(game.signals, [])

    def test_channels_exhaustion_is_reported(self):
        game = RescueGame()
        for loc in ("north", "south", "peak"):
            game.execute("signal %s" % loc)
        with self.assertRaises(CommandError):
            game.execute("signal camp")


class DuplicateSignalTest(unittest.TestCase):
    def test_duplicate_signal_creates_single_mission(self):
        game = RescueGame()
        game.execute("signal north")
        with self.assertRaises(CommandError):
            game.execute("signal north")
        self.assertEqual(len(game.missions), 1)
        self.assertEqual(game.signals, ["north"])


class SnapshotRestoreTest(unittest.TestCase):
    def test_restore_keeps_search_range_and_history(self):
        game = RescueGame()
        game.execute("move alpha camp")
        game.execute("search alpha")
        game.execute("snapshot cp")
        searched_at_snapshot = list(game.teams["alpha"]["searched"])
        game.execute("move alpha base")
        game.execute("search alpha")
        game.execute("restore cp")
        self.assertEqual(game.teams["alpha"]["searched"], searched_at_snapshot)
        self.assertEqual(game.teams["alpha"]["search_range"], 1)
        self.assertEqual(game.teams["alpha"]["location"], "camp")

    def test_restore_is_deep_copy(self):
        game = RescueGame()
        game.execute("snapshot cp")
        game.execute("injured north")
        game.execute("restore cp")
        game.execute("injured south")
        game.execute("restore cp")
        self.assertEqual(game.locations["north"]["injured"], [])
        self.assertEqual(game.locations["south"]["injured"], [])


class IllegalCommandTest(unittest.TestCase):
    def test_unknown_command_rejected_without_state_change(self):
        game = RescueGame()
        before = game.to_json()
        with self.assertRaises(CommandError):
            game.execute("teleport alpha peak")
        self.assertEqual(game.to_json(), before)

    def test_bad_arguments_rejected_without_state_change(self):
        game = RescueGame()
        before = game.to_json()
        for bad in ("move alpha", "fly", "split alpha", "cancel", "transfer x"):
            with self.assertRaises(CommandError, msg=bad):
                game.execute(bad)
        self.assertEqual(game.to_json(), before)

    def test_unknown_entities_rejected(self):
        game = RescueGame()
        for bad in ("move ghost camp", "move alpha nowhere", "fly nowhere",
                    "signal nowhere", "cancel M99", "transfer ghost camp",
                    "board ghost", "restore missing"):
            with self.assertRaises(CommandError, msg=bad):
                game.execute(bad)


class EmptyDataTest(unittest.TestCase):
    def test_empty_command_rejected(self):
        game = RescueGame()
        for bad in ("", "   ", None):
            with self.assertRaises(CommandError):
                game.execute(bad)

    def test_from_empty_dict_uses_defaults(self):
        game = RescueGame.from_dict({})
        self.assertEqual(game.seed, DEFAULT_SEED)
        self.assertEqual(game.turn, 0)
        self.assertIn("alpha", game.teams)

    def test_from_empty_json_string(self):
        game = RescueGame.from_json("")
        self.assertEqual(game.turn, 0)

    def test_json_roundtrip_preserves_fields(self):
        game = RescueGame()
        game.execute("injured north")
        game.execute("signal north")
        game.execute("advance")
        game.execute("split alpha bravo")
        clone = RescueGame.from_json(game.to_json())
        self.assertEqual(game.to_dict(), clone.to_dict())
        self.assertEqual(json.loads(game.to_json()), json.loads(clone.to_json()))


class CapacityBoundaryTest(unittest.TestCase):
    def test_shelter_capacity_boundary(self):
        game = RescueGame()
        for i in range(SHELTER_CAPACITY):
            game.execute("injured camp")
            game.execute("transfer injured-%d shelter" % (i + 1))
        self.assertEqual(len(game.locations["shelter"]["injured"]), SHELTER_CAPACITY)
        game.execute("injured camp")
        with self.assertRaises(CommandError):
            game.execute("transfer injured-%d shelter" % (SHELTER_CAPACITY + 1))
        self.assertEqual(len(game.locations["shelter"]["injured"]), SHELTER_CAPACITY)

    def test_helicopter_cabin_boundary(self):
        game = RescueGame()
        for i in range(HELICOPTER_CAPACITY):
            game.execute("injured base")
            game.execute("board injured-%d" % (i + 1))
        self.assertEqual(len(game.helicopter["onboard"]), HELICOPTER_CAPACITY)
        game.execute("injured base")
        with self.assertRaises(CommandError):
            game.execute("board injured-%d" % (HELICOPTER_CAPACITY + 1))
        self.assertEqual(len(game.helicopter["onboard"]), HELICOPTER_CAPACITY)


class DuplicateInputTest(unittest.TestCase):
    def test_duplicate_team_name_rejected(self):
        game = RescueGame()
        game.execute("split alpha bravo")
        with self.assertRaises(CommandError):
            game.execute("split alpha bravo")
        self.assertEqual(game.teams["bravo"]["supplies"], 5)

    def test_duplicate_cancel_rejected(self):
        game = RescueGame()
        game.execute("signal north")
        game.execute("cancel M1")
        with self.assertRaises(CommandError):
            game.execute("cancel M1")
        self.assertEqual(sorted(game.channels), sorted(RADIO_CHANNELS))

    def test_repeated_restore_is_idempotent(self):
        game = RescueGame()
        game.execute("injured north")
        game.execute("snapshot cp")
        game.execute("injured south")
        game.execute("restore cp")
        first = game.to_json()
        game.execute("restore cp")
        self.assertEqual(game.to_json(), first)


class SingleMutationTest(unittest.TestCase):
    def test_each_command_changes_state_once(self):
        game = RescueGame()
        game.execute("injured north")
        before = game.to_dict()
        game.execute("transfer injured-1 camp")
        after = game.to_dict()
        changed = [k for k in before if before[k] != after[k]]
        self.assertEqual(changed, ["locations"])

    def test_failed_command_is_transactional(self):
        game = RescueGame()
        game.execute("signal north")
        before = game.to_json()
        with self.assertRaises(CommandError):
            game.execute("signal north")
        self.assertEqual(game.to_json(), before)


class FixedSeedTest(unittest.TestCase):
    def test_fixed_seed_reproduces_weather(self):
        seq = []
        for _ in range(2):
            game = RescueGame(seed=DEFAULT_SEED)
            for _ in range(10):
                game.execute("advance")
            seq.append((game.weather, dict(game.blocked), game.to_json()))
        self.assertEqual(seq[0], seq[1])


if __name__ == "__main__":
    unittest.main()
