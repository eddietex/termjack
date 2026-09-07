"""Tests for the trainer in blackjack.trainer.

The sharp one is `BasicStrategyTests`: it walks every cell of the basic
strategy chart that `tools/verify_odds.py` plays to a 0.46% house edge and
checks that the trainer's expected-value arithmetic picks the same move. That
chart is the trainer's ground truth -- the advice is only worth giving if the
numbers behind it land where the book does.
"""

from __future__ import annotations

import importlib.util
import os
import unittest

from blackjack.cards import Card, Suit
from blackjack.engine import Action, Game, Hand, Phase, Round
from blackjack import trainer

S = Suit.SPADES
H = Suit.HEARTS

UPCARDS = list(range(2, 11)) + [11]      # 11 is an ace
PANEL_COLS = 72                          # the trainer panel's interior at 76x22


def _load_chart():
    """The basic-strategy tables from tools/verify_odds.py, kept in one place."""
    path = os.path.join(os.path.dirname(__file__), "..", "tools", "verify_odds.py")
    spec = importlib.util.spec_from_file_location("verify_odds", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHART = _load_chart()
MOVES = {"H": Action.HIT, "S": Action.STAND,
         "D": Action.DOUBLE, "P": Action.SPLIT}


def card(value: int) -> Card:
    return Card({11: "A", 10: "K"}.get(value, str(value)), S)


def situation(cards: list[Card], up: int, bankroll: int = 500):
    """Put a hand on the table and ask the trainer to read it."""
    game = Game(bankroll=bankroll)
    game.round = Round(hands=[Hand(cards=list(cards), bet=25)],
                       dealer=Hand(cards=[card(up), Card("2", H)]))
    game.phase = Phase.PLAYER
    return game, trainer.read(game)


# ---------------------------------------------------------------------------
# the dealer's odds
# ---------------------------------------------------------------------------
class DealerDistributionTests(unittest.TestCase):
    def setUp(self):
        self.p = trainer.probabilities(trainer.composition(6, []))

    def test_every_upcard_gives_a_distribution(self):
        for up in range(10):
            with self.subTest(up=up):
                d = trainer.dealer_distribution(up, self.p)
                self.assertAlmostEqual(sum(d), 1.0, places=9)
                self.assertTrue(all(x >= 0.0 for x in d))

    def test_bust_rates_match_published_s17_tables(self):
        # Standard six-deck, stand-on-all-17 figures, to a tenth of a point.
        want = {2: 0.354, 3: 0.374, 4: 0.395, 5: 0.416, 6: 0.423,
                7: 0.262, 8: 0.245, 9: 0.228, 10: 0.230, 11: 0.167}
        for up, expected in want.items():
            with self.subTest(up=up):
                d = trainer.dealer_distribution(trainer._index(card(up)), self.p)
                self.assertAlmostEqual(d[trainer.BUST], expected, places=2)

    def test_a_weak_upcard_busts_more_often_than_a_strong_one(self):
        bust = [trainer.dealer_distribution(trainer._index(card(u)), self.p)[trainer.BUST]
                for u in (6, 7, 10)]
        self.assertGreater(bust[0], bust[1])
        self.assertGreater(bust[1], bust[2])

    def test_peek_rules_out_a_natural_under_an_ace(self):
        # The hole card cannot be a ten, so a 21 has to be built from three or
        # more cards and is much rarer than the raw 8/13 of the shoe.
        d = trainer.dealer_distribution(trainer.ACE, self.p)
        self.assertLess(d[4], 0.10)
        self.assertAlmostEqual(d[4], 0.078, places=2)

    def test_peek_rules_out_a_natural_under_a_ten(self):
        d = trainer.dealer_distribution(trainer.TEN, self.p)
        self.assertLess(d[4], 0.05)


# ---------------------------------------------------------------------------
# what a move is worth
# ---------------------------------------------------------------------------
class ExpectedValueTests(unittest.TestCase):
    def setUp(self):
        self.p = trainer.probabilities(trainer.composition(6, []))
        self.d = trainer.dealer_distribution(trainer._index(card(6)), self.p)

    def test_standing_is_worth_more_the_higher_the_total(self):
        evs = [trainer.ev_stand(t, self.d) for t in range(12, 22)]
        self.assertEqual(evs, sorted(evs))

    def test_standing_on_a_bust_hand_loses_the_bet(self):
        self.assertEqual(trainer.ev_stand(22, self.d), -1.0)

    def test_standing_on_21_wins_everything_but_a_dealer_21(self):
        self.assertAlmostEqual(trainer.ev_stand(21, self.d), 1.0 - self.d[4])

    def test_doubling_11_beats_hitting_it_against_a_six(self):
        hit = trainer.ev_hit(11, False, self.p, self.d, {})
        self.assertGreater(trainer.ev_double(11, False, self.p, self.d), hit)

    def test_hitting_a_hand_that_cannot_bust_beats_standing_on_it(self):
        for total in range(5, 12):
            with self.subTest(total=total):
                self.assertGreater(
                    trainer.ev_hit(total, False, self.p, self.d, {}),
                    trainer.ev_stand(total, self.d))

    def test_splitting_eights_beats_playing_them_as_sixteen(self):
        split = trainer.ev_split(trainer._index(card(8)), self.p, self.d)
        self.assertGreater(split, trainer.ev_stand(16, self.d))
        self.assertGreater(split, trainer.ev_hit(16, False, self.p, self.d, {}))

    def test_insurance_is_a_losing_bet_on_a_fresh_shoe(self):
        self.assertLess(trainer.ev_insurance(self.p), 0.0)

    def test_insurance_breaks_even_when_a_third_of_the_shoe_is_tens(self):
        p = [0.0] * 10
        p[trainer.TEN] = 1 / 3
        p[1] = 2 / 3
        self.assertAlmostEqual(trainer.ev_insurance(tuple(p)), 0.0, places=9)


# ---------------------------------------------------------------------------
# the chart
# ---------------------------------------------------------------------------
class BasicStrategyTests(unittest.TestCase):
    """Every cell of the chart, rederived from expected values."""

    def _assert_picks(self, cards, up, want, allow_split=False):
        game, s = situation(cards, up)
        if not allow_split:
            s.evs.pop(Action.SPLIT, None)
        expected = MOVES[want]
        if expected is Action.DOUBLE and Action.DOUBLE not in s.evs:
            expected = Action.HIT
        self.assertEqual(
            s.best, expected,
            f"{[str(c) for c in cards]} vs {up}: wanted {want}, "
            f"got {s.best.label} from {({a.label: round(v, 4) for a, v in s.evs.items()})}")

    def test_hard_totals(self):
        for total in range(5, 20):
            pair = next((a, total - a) for a in range(2, 11)
                        if 2 <= total - a <= 10 and a != total - a)
            for up in UPCARDS:
                with self.subTest(total=total, up=up):
                    self._assert_picks([card(pair[0]), card(pair[1])], up,
                                       CHART.HARD[total][up])

    def test_soft_totals(self):
        for other in range(2, 10):
            for up in UPCARDS:
                with self.subTest(soft=other, up=up):
                    self._assert_picks([card(11), card(other)], up,
                                       CHART.SOFT[other][up])

    def test_pairs(self):
        for value in UPCARDS:
            for up in UPCARDS:
                with self.subTest(pair=value, up=up):
                    self._assert_picks([card(value), card(value)], up,
                                       CHART.PAIRS[value][up], allow_split=True)

    def test_multi_card_sixteen_stands_against_a_ten(self):
        # The one place the trainer parts company with the total-only chart,
        # and a real rule: the low cards a three-card 16 is built from are the
        # ones that would have rescued a hit. It is always a coin flip.
        cards = [card(5), card(4), card(7)]
        game, s = situation(cards, 10)
        self.assertIs(s.best, Action.STAND)
        self.assertLess(s.evs[Action.STAND] - s.evs[Action.HIT], trainer.CLOSE)


# ---------------------------------------------------------------------------
# reading the table
# ---------------------------------------------------------------------------
class ReadTests(unittest.TestCase):
    def test_no_reading_without_a_decision_to_make(self):
        game = Game(bankroll=500)
        self.assertIsNone(trainer.read(game))

    def test_only_legal_moves_are_priced(self):
        game, s = situation([card(8), card(8)], 6, bankroll=0)
        self.assertEqual(set(s.evs), {Action.HIT, Action.STAND})

    def test_a_short_bankroll_never_recommends_a_double(self):
        game, s = situation([card(6), card(5)], 6, bankroll=0)
        self.assertIs(s.best, Action.HIT)

    def test_the_hand_and_upcard_come_out_of_the_shoe(self):
        game, s = situation([card(10), card(10)], 10)
        counts = trainer.composition(6, [card(10)] * 3)
        self.assertEqual(counts[trainer.TEN], 96 - 3)
        self.assertAlmostEqual(sum(s.p), 1.0, places=9)


# ---------------------------------------------------------------------------
# grading
# ---------------------------------------------------------------------------
class CoachTests(unittest.TestCase):
    def test_the_best_move_is_graded_right(self):
        game, _ = situation([card(8), card(8)], 6)
        note = trainer.Coach().review(game, Action.SPLIT)
        self.assertEqual(note.verdict, "right")
        self.assertEqual(note.move, "Split")

    def test_a_bad_move_is_graded_wrong_and_names_the_right_one(self):
        game, _ = situation([card(10), card(10)], 6)
        note = trainer.Coach().review(game, Action.HIT)
        self.assertEqual(note.verdict, "wrong")
        self.assertEqual(note.move, "Stand")

    def test_a_coin_flip_is_graded_close_rather_than_wrong(self):
        game, s = situation([card(10), card(6)], 10)
        loser = Action.STAND if s.best is Action.HIT else Action.HIT
        self.assertLess(s.evs[s.best] - s.evs[loser], trainer.CLOSE)
        self.assertEqual(trainer.Coach().review(game, loser).verdict, "close")

    def test_the_chip_names_the_players_figure_when_they_got_it_wrong(self):
        game, _ = situation([card(10), card(10)], 6)
        note = trainer.Coach().review(game, Action.HIT)
        self.assertIn("stand ", note.stats)
        self.assertIn("yours ", note.stats)

    def test_the_chip_names_the_runner_up_when_they_got_it_right(self):
        game, _ = situation([card(10), card(10)], 6)
        note = trainer.Coach().review(game, Action.STAND)
        self.assertIn("stand ", note.stats)
        self.assertNotIn("yours", note.stats)

    def test_the_tally_counts_only_the_best_move_as_right(self):
        coach = trainer.Coach()
        game, _ = situation([card(10), card(10)], 6)
        coach.review(game, Action.STAND)
        coach.review(game, Action.HIT)
        self.assertEqual((coach.right, coach.calls), (1, 2))

    def test_clearing_drops_the_note_but_keeps_the_tally(self):
        coach = trainer.Coach()
        game, _ = situation([card(10), card(10)], 6)
        coach.review(game, Action.STAND)
        coach.clear()
        self.assertIsNone(coach.note)
        self.assertEqual(coach.calls, 1)

    def test_an_illegal_move_is_not_graded(self):
        coach = trainer.Coach()
        game, _ = situation([card(10), card(6)], 6)
        self.assertIsNone(coach.review(game, Action.SPLIT))
        self.assertEqual(coach.calls, 0)

    def test_insurance_is_always_the_wrong_bet_to_take(self):
        game = Game(bankroll=500)
        game.round = Round(hands=[Hand(cards=[card(10), card(6)], bet=25)],
                           dealer=Hand(cards=[card(11), Card("2", H)]))
        game.phase = Phase.INSURANCE
        coach = trainer.Coach()
        self.assertEqual(coach.review_insurance(game, True).verdict, "wrong")
        self.assertEqual(coach.review_insurance(game, False).verdict, "right")
        self.assertEqual(coach.review_insurance(game, False).move, "Decline")


# ---------------------------------------------------------------------------
# what gets drawn
# ---------------------------------------------------------------------------
class NoteFitsThePanelTests(unittest.TestCase):
    """The panel is one line; nothing the trainer says may need two."""

    def _check(self, note):
        line = f"X {note.move}. {note.body}"
        self.assertLessEqual(len(line), PANEL_COLS, line)
        self.assertLessEqual(len(note.stats), 30, note.stats)
        self.assertTrue(note.body.endswith("."), note.body)
        self.assertTrue(note.body.isascii(), note.body)

    def test_every_chart_cell_fits(self):
        coach = trainer.Coach()
        for cards in ([[card(a), card(b)] for a in range(2, 12)
                       for b in range(2, 12) if a <= b]):
            for up in UPCARDS:
                game, s = situation(cards, up)
                if s is None:          # a natural: nothing to decide
                    continue
                for action in s.evs:
                    with self.subTest(cards=[str(c) for c in cards],
                                      up=up, action=action.label):
                        self._check(coach.review(game, action))

    def test_a_three_card_hand_fits(self):
        coach = trainer.Coach()
        for up in UPCARDS:
            game, s = situation([card(5), card(4), card(7)], up)
            for action in s.evs:
                with self.subTest(up=up, action=action.label):
                    self._check(coach.review(game, action))

    def test_the_insurance_note_fits(self):
        game = Game(bankroll=500)
        game.round = Round(hands=[Hand(cards=[card(10), card(6)], bet=25)],
                           dealer=Hand(cards=[card(11), Card("2", H)]))
        game.phase = Phase.INSURANCE
        self._check(trainer.Coach().review_insurance(game, False))


if __name__ == "__main__":
    unittest.main()
