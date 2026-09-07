"""Tests for the key handling and layout arithmetic in blackjack.app.

`App.handle` is pure state -- it reads keys and drives the engine and the
coach -- so it runs here against a screen that only knows how big it is. The
same screen answers the questions the layout asks before it draws anything:
whether a panel fits, and where. Only the parts that never draw belong here.
"""

from __future__ import annotations

import unittest

from blackjack import app as app_mod, trainer
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


class ChartLayoutTests(unittest.TestCase):
    """Where the chart goes, and that it always fits once it gets there."""

    def app(self, h: int, w: int, chart_on: bool = True) -> App:
        return App(Screen(h, w), Game(bankroll=500), chart_on=chart_on)

    def test_a_wide_table_docks_the_chart_beside_the_felt(self):
        self.assertTrue(self.app(34, 120).chart_docked)

    def test_a_narrow_table_lays_the_chart_over_the_felt(self):
        narrow = self.app(24, 80)
        self.assertTrue(narrow.chart_shown)
        self.assertFalse(narrow.chart_docked)

    def test_docking_never_squeezes_the_felt_below_its_floor(self):
        for w in range(app_mod.MIN_W, 200):
            table = self.app(40, w)
            if table.chart_docked:
                felt = table._table_size()[1] - 4 - app_mod.CHART_DOCK_W
                self.assertGreaterEqual(felt, app_mod.CARDS_MIN_W, f"at {w} columns")

    def test_a_terminal_too_small_to_play_on_shows_no_chart(self):
        self.assertFalse(self.app(21, 75).chart_shown)

    def test_the_chart_stays_hidden_until_it_is_asked_for(self):
        self.assertFalse(self.app(34, 120, chart_on=False).chart_shown)

    def test_c_toggles_the_chart(self):
        table = self.app(34, 120, chart_on=False)
        table.handle(ord("c"))
        self.assertTrue(table.chart_on)
        table.handle(ord("C"))
        self.assertFalse(table.chart_on)

    def test_every_column_fits_the_block_it_is_drawn_in(self):
        """The block is sized once, for the widest and tallest any upcard
        makes it, so the chart does not resize as the dealer's card changes."""
        for up in range(10):
            ch = trainer.chart(6, up)
            left = 1 + len(ch.hard) + 2 + len(ch.soft)   # HARD, a blank, SOFT
            right = 1 + len(ch.pairs)                    # PAIRS
            with self.subTest(up=ch.upcard):
                self.assertLessEqual(max(left, right), app_mod.CHART_BODY_H)
                for rows, width in ((ch.hard + ch.soft, app_mod.CHART_LEFT_W),
                                    (ch.pairs, app_mod.CHART_RIGHT_W)):
                    for row in rows:
                        self.assertLessEqual(
                            1 + len(row.label) + 1 + len(row.action.label), width,
                            f"'{row.label} {row.action.label}' vs {ch.upcard}")


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
