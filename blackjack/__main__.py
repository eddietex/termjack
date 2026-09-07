"""Entry point: `python3 -m blackjack`."""

from __future__ import annotations

import argparse
import curses
import locale
import os
import sys

from .app import App
from .engine import Game


def _unicode_ok() -> bool:
    enc = (locale.getpreferredencoding(False) or "").lower()
    return "utf" in enc


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="termjack", description="A classic blackjack table in the terminal.")
    p.add_argument("--bankroll", type=int, default=500,
                   help="starting chips (default: 500)")
    p.add_argument("--decks", type=int, default=6,
                   help="decks in the shoe (default: 6)")
    p.add_argument("--seed", type=int, default=None,
                   help="seed the shuffle, for a reproducible shoe")
    p.add_argument("--ascii", action="store_true",
                   help="plain ASCII box drawing instead of Unicode")
    p.add_argument("--no-trainer", dest="trainer", action="store_false",
                   help="start with the trainer panel hidden (t toggles it)")
    return p.parse_args(argv)


def _run(stdscr, game: Game, unicode_ok: bool, trainer_on: bool) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    _install_theme()
    App(stdscr, game, unicode_ok=unicode_ok, trainer_on=trainer_on).run()


def _install_theme() -> bool:
    from . import theme
    return theme.setup()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.decks < 1 or args.decks > 8:
        print("decks must be between 1 and 8", file=sys.stderr)
        return 2
    if args.bankroll < 5:
        print("bankroll must be at least 5", file=sys.stderr)
        return 2

    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")

    import random
    rng = random.Random(args.seed) if args.seed is not None else None
    game = Game(bankroll=args.bankroll, decks=args.decks, rng=rng)
    unicode_ok = _unicode_ok() and not args.ascii

    try:
        curses.wrapper(_run, game, unicode_ok, args.trainer)
    except curses.error as exc:
        print(f"terminal error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass

    print(f"You left the table with ${game.bankroll} "
          f"({game.wins}W / {game.losses}L / {game.pushes}P).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
