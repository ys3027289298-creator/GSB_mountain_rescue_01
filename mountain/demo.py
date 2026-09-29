"""Fixed-seed demonstration of the mountain rescue core.

Run with: python -m mountain.demo
"""
from .core import DEFAULT_SEED, RescueGame

SCRIPT = (
    "menu",
    "injured north",
    "injured north",
    "injured peak",
    "split alpha bravo",
    "move alpha camp",
    "move bravo camp",
    "move bravo north",
    "search bravo",
    "signal north",
    "signal peak",
    "board injured-1",
    "fly north",
    "board injured-2",
    "fly base",
    "transfer injured-1 shelter",
    "snapshot checkpoint",
    "advance",
    "advance",
    "advance",
    "cancel M2",
    "restore checkpoint",
    "status",
)


def main():
    game = RescueGame(seed=DEFAULT_SEED)
    for line in SCRIPT:
        try:
            result = game.execute(line)
        except Exception as exc:  # demo keeps going so the log is complete
            result = "ERROR: %s" % exc
        print("> %s\n  %s" % (line, result))


if __name__ == "__main__":
    main()
