"""Tests for the key handling in blackjack.app.

`App.handle` is pure state -- it reads keys and drives the engine and the
coach -- so it runs here against a screen that only knows how big it is.
Only the parts that never draw belong in this file.
"""

from __future__ import annotations

import unittest

from blackjack.app import App
from blackjack.cards import Card, Suit
from blackjack.engine import Game, Hand, Phase, Round

S = Suit.SPADES
H = Suit.HEARTS


class Screen:
    """Enough of a curses window for `handle`: a size, and nothing else."""

    def __init__(self, h: int = 40, w: int = 120):
        self.size = (h, w)

    def getmaxyx(self) -> tuple[int, int]:
        return self.size


def table(bankroll: int, bet: int) -> App:
    """A dealer ace on the table, with the insurance decision pending."""
    game = Game(bankroll=bankroll)
    game.round = Round(hands=[Hand(cards=[Card("K", S), Card("6", S)], bet=bet)],
                       dealer=Hand(cards=[Card("A", S), Card("2", H)]))
    game.phase = Phase.INSURANCE
    app = App(Screen(), game)
    app.shown_dealer, app.shown_hands = 2, [2]      # nothing left to animate
    return app


class InsuranceKeyTests(unittest.TestCase):
    def test_insuring_stakes_half_the_bet(self):
        app = table(bankroll=500, bet=100)
        app.handle(ord("y"))
        self.assertEqual(app.game.round.insurance, 50)
        self.assertEqual(app.game.bankroll, 450)

    def test_an_unaffordable_insurance_is_not_graded(self):
        """Betting the stack leaves nothing to insure with, and `y` is drawn
        greyed out. Pressing it anyway must not book a wrong call against the
        player for a side bet the engine was never going to place."""
        app = table(bankroll=20, bet=100)
        self.assertFalse(app.game.can_insure())
        app.handle(ord("y"))
        self.assertEqual(app.coach.calls, 0)
        self.assertIsNone(app.coach.note)
        self.assertEqual(app.game.round.insurance, 0)
        self.assertEqual(app.game.bankroll, 20)
        self.assertIs(app.game.phase, Phase.INSURANCE)   # still their call

    def test_declining_is_always_allowed(self):
        app = table(bankroll=20, bet=100)
        app.handle(ord("n"))
        self.assertEqual(app.coach.calls, 1)
        self.assertEqual(app.coach.note.verdict, "right")
        self.assertIsNot(app.game.phase, Phase.INSURANCE)


if __name__ == "__main__":
    unittest.main()
