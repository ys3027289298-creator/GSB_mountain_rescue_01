"""Mountain rescue game core logic.

All state mutations go through ``RescueGame.execute``. Every command validates
its inputs first and then applies exactly one coherent state change; illegal
commands raise :class:`CommandError` and leave the state untouched.
"""
from __future__ import annotations

import copy
import json
import random

DEFAULT_SEED = 42
FUEL_PER_FLIGHT = 20
HELICOPTER_CAPACITY = 2
SHELTER_CAPACITY = 3
HAZARD_TURNS = 3
RADIO_CHANNELS = ("CH-1", "CH-2", "CH-3")
WEATHERS = ("clear", "cloudy", "storm")
SHELTER = "shelter"

STATE_FIELDS = (
    "seed", "turn", "weather", "locations", "roads", "blocked",
    "teams", "helicopter", "missions", "channels", "signals",
    "seq", "rng_state",
)

MENU = """Mountain Rescue Command Menu
  status                          show game state as JSON
  menu                            show this menu
  injured <location>              register a new injured person
  split <team> <new_team>         split a team, sharing supplies once
  move <team> <location>          move a team along an open road
  search <team>                   search sectors within the team's range
  transfer <injured> <location>   move an injured person to a location
  board <injured>                 load an injured person onto the helicopter
  fly <location>                  fly the helicopter (costs fuel)
  signal <location>               raise a distress signal, opening one mission
  cancel <mission>                cancel a mission, freeing its radio channel
  advance                         advance one turn (weather, hazards, roads)
  snapshot [name]                 save a state snapshot
  restore [name]                  restore a previously saved snapshot
"""


class CommandError(Exception):
    """Raised for illegal commands; the game state is left unchanged."""


def _road_key(a, b):
    return "|".join(sorted((a, b)))


def _to_tuple(value):
    if isinstance(value, list):
        return tuple(_to_tuple(item) for item in value)
    return value


def _default_locations():
    names = ("base", "camp", "north", "south", "peak", SHELTER)
    return {name: {"injured": [], "hazards": {}} for name in names}


def _default_roads():
    pairs = (
        ("base", "camp"), ("camp", "north"), ("camp", "south"),
        ("north", "peak"), ("south", "peak"), ("base", SHELTER),
    )
    return sorted(_road_key(a, b) for a, b in pairs)


def _default_teams():
    return {
        "alpha": {
            "location": "base",
            "supplies": 10,
            "search_range": 1,
            "searched": [],
        }
    }


class RescueGame:
    def __init__(self, seed=DEFAULT_SEED):
        self.seed = seed
        self.rng = random.Random(seed)
        self.turn = 0
        self.weather = "clear"
        self.locations = _default_locations()
        self.roads = _default_roads()
        self.blocked = {}
        self.teams = _default_teams()
        self.helicopter = {"location": "base", "fuel": 100, "onboard": []}
        self.missions = {}
        self.channels = list(RADIO_CHANNELS)
        self.signals = []
        self.seq = {"mission": 0, "injured": 0}
        self.snapshots = {}

    # ------------------------------------------------------------------
    # command dispatch
    # ------------------------------------------------------------------
    def execute(self, line):
        if not isinstance(line, str) or not line.strip():
            raise CommandError("empty command")
        parts = line.split()
        name, args = parts[0], parts[1:]
        handler = self._COMMANDS.get(name)
        if handler is None:
            raise CommandError("unknown command: %s" % name)
        try:
            return handler(self, *args)
        except TypeError as exc:
            raise CommandError("bad arguments for %s: %s" % (name, exc)) from exc

    def menu(self):
        return MENU

    # ------------------------------------------------------------------
    # commands (validate fully, then mutate exactly once)
    # ------------------------------------------------------------------
    def cmd_status(self):
        return self.to_json()

    def cmd_menu(self):
        return MENU

    def cmd_injured(self, location):
        self._require_location(location)
        self.seq["injured"] += 1
        injured_id = "injured-%d" % self.seq["injured"]
        self.locations[location]["injured"].append(injured_id)
        return "registered %s at %s" % (injured_id, location)

    def cmd_split(self, team, new_name):
        src = self._require_team(team)
        if not new_name or new_name in self.teams:
            raise CommandError("duplicate or invalid team name: %r" % new_name)
        share = src["supplies"] // 2
        src["supplies"] -= share  # shared supplies are deducted exactly once
        self.teams[new_name] = {
            "location": src["location"],
            "supplies": share,
            "search_range": src["search_range"],
            "searched": [],
        }
        return "team %s split from %s with %d supplies" % (new_name, team, share)

    def cmd_move(self, team, dest):
        info = self._require_team(team)
        self._require_location(dest)
        key = _road_key(info["location"], dest)
        if key not in self.roads:
            raise CommandError("no road from %s to %s" % (info["location"], dest))
        if key in self.blocked:
            raise CommandError("road %s is blocked by avalanche" % key)
        info["location"] = dest
        return "team %s moved to %s" % (team, dest)

    def cmd_search(self, team):
        info = self._require_team(team)
        reached = self._reachable(info["location"], info["search_range"])
        for name in reached:
            if name not in info["searched"]:
                info["searched"].append(name)
        found = []
        for name in reached:
            found.extend(self.locations[name]["injured"])
        return "searched %s; found %s" % (
            ",".join(sorted(reached)), ",".join(found) or "nobody")

    def cmd_transfer(self, injured_id, dest):
        self._require_location(dest)
        origin = None
        for name, data in self.locations.items():
            if injured_id in data["injured"]:
                origin = name
                break
        onboard = injured_id in self.helicopter["onboard"]
        if origin is None and not onboard:
            raise CommandError("unknown injured: %s" % injured_id)
        if dest == SHELTER and len(self.locations[SHELTER]["injured"]) >= SHELTER_CAPACITY:
            raise CommandError("shelter is at capacity")
        if origin is not None:
            self.locations[origin]["injured"].remove(injured_id)
        else:
            self.helicopter["onboard"].remove(injured_id)
        self.locations[dest]["injured"].append(injured_id)
        return "transferred %s to %s" % (injured_id, dest)

    def cmd_board(self, injured_id):
        location = self.helicopter["location"]
        if injured_id not in self.locations[location]["injured"]:
            raise CommandError("%s is not at %s" % (injured_id, location))
        if len(self.helicopter["onboard"]) >= HELICOPTER_CAPACITY:
            raise CommandError("helicopter cabin is at capacity")
        self.locations[location]["injured"].remove(injured_id)
        self.helicopter["onboard"].append(injured_id)
        return "%s boarded the helicopter" % injured_id

    def cmd_fly(self, dest):
        self._require_location(dest)
        if self.helicopter["fuel"] < FUEL_PER_FLIGHT:
            raise CommandError("insufficient fuel")
        self.helicopter["fuel"] -= FUEL_PER_FLIGHT
        self.helicopter["location"] = dest
        return "helicopter flew to %s (fuel %d)" % (dest, self.helicopter["fuel"])

    def cmd_signal(self, location):
        self._require_location(location)
        if location in self.signals:
            raise CommandError("distress signal at %s already active" % location)
        if not self.channels:
            raise CommandError("no radio channel available")
        self.seq["mission"] += 1
        mission_id = "M%d" % self.seq["mission"]
        channel = self.channels.pop(0)
        self.missions[mission_id] = {
            "location": location, "channel": channel, "status": "active",
        }
        self.signals.append(location)
        return "mission %s opened on %s" % (mission_id, channel)

    def cmd_cancel(self, mission_id):
        mission = self.missions.get(mission_id)
        if mission is None:
            raise CommandError("unknown mission: %s" % mission_id)
        self.channels.append(mission["channel"])
        self.channels.sort()
        self.signals.remove(mission["location"])
        del self.missions[mission_id]
        return "mission %s cancelled; %s released" % (mission_id, mission["channel"])

    def cmd_advance(self):
        self.turn += 1
        self.weather = self.rng.choice(WEATHERS)
        if self.weather == "storm":
            road = self.roads[self.rng.randrange(len(self.roads))]
            self.blocked[road] = HAZARD_TURNS
            for endpoint in road.split("|"):
                self.locations[endpoint]["hazards"]["avalanche"] = HAZARD_TURNS
        # Hazards expire only on their own timers; improving weather never
        # clears them early.
        for data in self.locations.values():
            for hazard in list(data["hazards"]):
                data["hazards"][hazard] -= 1
                if data["hazards"][hazard] <= 0:
                    del data["hazards"][hazard]
        for road in list(self.blocked):
            self.blocked[road] -= 1
            if self.blocked[road] <= 0:
                del self.blocked[road]
        return "turn %d; weather %s" % (self.turn, self.weather)

    def cmd_snapshot(self, name="auto"):
        self.snapshots[name] = self.to_dict()
        return "snapshot %s saved" % name

    def cmd_restore(self, name="auto"):
        if name not in self.snapshots:
            raise CommandError("unknown snapshot: %s" % name)
        self._load(self.snapshots[name])
        return "snapshot %s restored" % name

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _require_location(self, location):
        if location not in self.locations:
            raise CommandError("unknown location: %r" % location)

    def _require_team(self, team):
        info = self.teams.get(team)
        if info is None:
            raise CommandError("unknown team: %s" % team)
        return info

    def _reachable(self, start, max_hops):
        seen = {start}
        frontier = {start}
        for _ in range(max_hops):
            nxt = set()
            for road in self.roads:
                if road in self.blocked:
                    continue
                a, b = road.split("|")
                if a in frontier and b not in seen:
                    nxt.add(b)
                if b in frontier and a not in seen:
                    nxt.add(a)
            seen |= nxt
            frontier = nxt
        return seen

    # ------------------------------------------------------------------
    # serialization (stable JSON fields)
    # ------------------------------------------------------------------
    def to_dict(self):
        return {
            "seed": self.seed,
            "turn": self.turn,
            "weather": self.weather,
            "locations": copy.deepcopy(self.locations),
            "roads": list(self.roads),
            "blocked": dict(self.blocked),
            "teams": copy.deepcopy(self.teams),
            "helicopter": copy.deepcopy(self.helicopter),
            "missions": copy.deepcopy(self.missions),
            "channels": list(self.channels),
            "signals": list(self.signals),
            "seq": dict(self.seq),
            "rng_state": json.loads(json.dumps(self.rng.getstate())),
        }

    def to_json(self):
        return json.dumps(self.to_dict(), sort_keys=True)

    def _load(self, data):
        if not isinstance(data, dict):
            raise CommandError("snapshot data must be a mapping")
        state = copy.deepcopy(data)
        self.seed = state.get("seed", DEFAULT_SEED)
        self.turn = state.get("turn", 0)
        self.weather = state.get("weather", "clear")
        self.locations = state.get("locations") or _default_locations()
        self.roads = list(state.get("roads") or _default_roads())
        self.blocked = dict(state.get("blocked") or {})
        self.teams = state.get("teams") or _default_teams()
        self.helicopter = state.get("helicopter") or {
            "location": "base", "fuel": 100, "onboard": [],
        }
        self.missions = state.get("missions") or {}
        self.channels = list(state.get("channels") or list(RADIO_CHANNELS))
        self.signals = list(state.get("signals") or [])
        self.seq = dict(state.get("seq") or {"mission": 0, "injured": 0})
        self.rng = random.Random(self.seed)
        if state.get("rng_state") is not None:
            self.rng.setstate(_to_tuple(state["rng_state"]))

    @classmethod
    def from_dict(cls, data):
        game = cls()
        game._load(data)
        return game

    @classmethod
    def from_json(cls, payload):
        if isinstance(payload, str):
            payload = json.loads(payload) if payload.strip() else {}
        return cls.from_dict(payload)


RescueGame._COMMANDS = {
    "status": RescueGame.cmd_status,
    "menu": RescueGame.cmd_menu,
    "injured": RescueGame.cmd_injured,
    "split": RescueGame.cmd_split,
    "move": RescueGame.cmd_move,
    "search": RescueGame.cmd_search,
    "transfer": RescueGame.cmd_transfer,
    "board": RescueGame.cmd_board,
    "fly": RescueGame.cmd_fly,
    "signal": RescueGame.cmd_signal,
    "cancel": RescueGame.cmd_cancel,
    "advance": RescueGame.cmd_advance,
    "snapshot": RescueGame.cmd_snapshot,
    "restore": RescueGame.cmd_restore,
}
