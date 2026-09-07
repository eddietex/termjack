"""Tests for the key handling and layout arithmetic in blackjack.app.

`App.handle` is pure state -- it reads keys and drives the engine and the
coach -- so it runs here against a screen that only knows how big it is. The
same screen answers the questions the layout asks before it draws anything:
whether a panel fits, and where. Only the parts that never draw belong here.
"""

from __future__ import annotations

import unittest

import random

from blackjack import app as app_mod, render, trainer
from blackjack.app import App, visible
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


def beat(app: App, count: int = 1) -> None:
    """Run `count` beats of the deal without waiting for them in real time.

    Winding the clock the beat started on backwards past its span is the same
    thing to `_advance_reveal` as the time having passed.
    """
    for _ in range(count):
        if not app.animating:
            return
        app.beat_at -= app.beat.span
        app._advance_reveal()


def settle(app: App) -> None:
    beat(app, 64)


class DealAnimationTests(unittest.TestCase):
    """The deal is a queue of timed beats, so the felt fills a card at a time
    rather than all at once when the engine resolves an action."""

    def deal(self, seed: int = 3) -> App:
        """A dealt round, on a seeded shoe: seed 3 puts 5-6 in front of the
        player against a 5 up, so the round runs its full length."""
        app = App(Screen(), Game(bankroll=500, rng=random.Random(seed)))
        app.handle(ord(" "))              # place the bet, start the deal
        return app

    def test_the_opening_deal_pitches_round_the_table(self):
        app = self.deal()
        order = [(b.kind, b.which, b.index)
                 for b in ([app.beat] + app.queue)[:4]]
        self.assertEqual(order, [("card", 0, 0), ("card", -1, 0),
                                 ("card", 0, 1), ("card", -1, 1)])

    def test_nothing_is_on_the_felt_before_its_beat(self):
        app = self.deal()
        self.assertEqual((app._shown(0), app._shown(-1)), (0, 0))
        beat(app)
        self.assertEqual((app._shown(0), app._shown(-1)), (1, 0))
        beat(app)
        self.assertEqual((app._shown(0), app._shown(-1)), (1, 1))

    def test_a_hand_only_totals_the_cards_that_have_landed(self):
        hand = Hand(cards=[Card("K", S), Card("6", S)], bet=25)
        self.assertEqual(visible(hand, 0).cards, [])
        self.assertEqual(visible(hand, 1).total, 10)
        self.assertEqual(visible(hand, 2).total, 16)

    def test_a_card_pitched_face_down_never_comes_up_mid_turn(self):
        """The turn is the same either way -- what changes is whether it ends
        on the face. A face-down pitch must show a back at every step."""
        frames = len(render.FLIP_FRAMES)
        for f in range(frames + 2):          # past the end, where it holds
            self.assertFalse(render.turn_frame(f, reveal=False)[1],
                             f"frame {f} of a face-down pitch showed the card")
        self.assertTrue(render.turn_frame(frames - 1)[1])
        self.assertFalse(render.turn_frame(0)[1])   # every turn starts down

    def test_the_hole_card_stays_down_until_the_dealer_turns_it(self):
        """The hole card is dealt like a real one: face down, and down it
        stays. Neither the turn it lands on nor the pause before the dealer
        takes it may put the card on screen."""
        app = self.deal()
        turning = 0

        def run() -> None:
            nonlocal turning
            while app.animating:
                beat = app.beat
                if app.hole_up:
                    pass                # turned, and nothing left to protect
                elif beat.kind == "hole" and app._turn(-1) is not None:
                    turning += 1        # its own turn: the one time it shows
                else:
                    self.assertTrue(app.hole_hidden,
                                    f"the hole card showed during {beat.kind}")
                app.beat_at -= beat.span / 8      # an eighth of a beat passes
                app._advance_reveal()

        run()
        if app.game.phase is Phase.INSURANCE:
            app.handle(ord("n"))
            run()
        while app.game.phase is Phase.PLAYER:
            app.handle(ord("s"))
            run()

        self.assertGreater(turning, 0)          # and it did come up in the end
        self.assertTrue(app.hole_up)
        self.assertFalse(app.hole_hidden)

    def test_the_hole_card_waits_for_a_beat_of_its_own(self):
        app = self.deal()
        settle(app)
        if app.game.phase is Phase.INSURANCE:
            app.handle(ord("n"))
            settle(app)
        self.assertFalse(app.hole_up)     # dealt face down, and still down
        while app.game.phase is Phase.PLAYER:
            app.handle(ord("s"))
            settle(app)

        self.assertFalse(app.game.round.hole_down)   # the engine turned it
        self.assertTrue(app.hole_up)                 # and so did the table

    def test_the_dealer_turns_the_hole_card_before_it_draws(self):
        app = App(Screen(), Game(bankroll=500))
        app.game.round = Round(
            hands=[Hand(cards=[Card("K", S), Card("6", S)], bet=25)],
            dealer=Hand(cards=[Card("5", S), Card("6", H)]))
        app.game.phase = Phase.PLAYER
        app.shown_dealer, app.shown_hands, app.hole_up = 2, [2], False
        app.handle(ord("s"))

        kinds = [b.kind for b in [app.beat] + app.queue]
        self.assertEqual(kinds[0], "hole")
        self.assertTrue(all(k == "card" for k in kinds[1:-1]))
        self.assertEqual(kinds[-1], "wait")   # a pause before the result

    def test_a_split_deals_to_both_halves_again(self):
        app = App(Screen(), Game(bankroll=500))
        app.game.round = Round(
            hands=[Hand(cards=[Card("8", S), Card("8", H)], bet=25)],
            dealer=Hand(cards=[Card("9", S), Card("2", H)]))
        app.game.phase = Phase.PLAYER
        app.shown_dealer, app.shown_hands, app.hole_up = 2, [2], False
        app.handle(ord("p"))

        # The card that moved across leaves the first hand a single card, and
        # each half is then dealt its replacement.
        self.assertEqual(app.shown_hands, [1, 0])
        self.assertEqual([(b.which, b.index) for b in [app.beat] + app.queue],
                         [(0, 1), (1, 0), (1, 1)])
        settle(app)
        self.assertEqual(app.shown_hands, [2, 2])

    def test_the_result_is_not_booked_before_the_hand_is_called(self):
        """The engine settles the moment the last card is drawn. Until the
        table has called the hand, the sidebar has to read as it did before,
        or it gives the round away over the dealer's shoulder."""
        app = App(Screen(), Game(bankroll=500))
        app.game.round = Round(
            hands=[Hand(cards=[Card("K", S), Card("9", S)], bet=25)],
            dealer=Hand(cards=[Card("5", S), Card("6", H)]))
        app.game.phase = Phase.PLAYER
        app.shown_dealer, app.shown_hands, app.hole_up = 2, [2], False
        bank, wins, losses = app.game.bankroll, app.game.wins, app.game.losses

        app.handle(ord("s"))
        held = app.uncalled
        self.assertIs(app.game.phase, Phase.SETTLED)   # the engine is done
        self.assertIsNotNone(held)                     # the table is not
        won, lost, _, _ = app._uncounted(held)
        self.assertEqual(app.game.bankroll - sum(h.payout for h in held.hands),
                         bank)
        self.assertEqual((app.game.wins - won, app.game.losses - lost),
                         (wins, losses))

        settle(app)
        self.assertIsNone(app.uncalled)
        self.assertEqual(app._uncounted(None), (0, 0, 0, 0))

    def test_a_key_drops_the_rest_of_the_deal_at_once(self):
        app = self.deal()
        self.assertTrue(app.animating)
        app.handle(ord("s"))              # any key skips
        self.assertFalse(app.animating)
        self.assertEqual(app.queue, [])
        rnd = app.game.round
        self.assertEqual(app._shown(0), len(rnd.hands[0].cards))
        self.assertEqual(app._shown(-1), len(rnd.dealer.cards))
        self.assertEqual(app.hole_up, not rnd.hole_down)

    def test_the_deal_does_not_stretch_when_frames_run_late(self):
        """Beats chain from when they were due, so a frame that arrives late
        catches up instead of adding its lateness to every card after it."""
        app = self.deal()
        spans = [b.span for b in ([app.beat] + app.queue)[:3]]
        start = app.beat_at - sum(spans)      # three beats now overdue
        app.beat_at = start
        app._advance_reveal()

        self.assertEqual(app._shown(0) + app._shown(-1), 3)
        self.assertAlmostEqual(app.beat_at, start + sum(spans))


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
