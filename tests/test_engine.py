"""Tests for the traditional blackjack rules implemented in blackjack.engine.

Covers the rules claimed in engine.py's module docstring:
  * 6-deck shoe, reshuffle when cut card passed (~75% penetration)
  * dealer stands on all 17 (S17), including soft 17
  * blackjack pays 3:2
  * insurance offered on dealer ace, pays 2:1
  * double down on any first two cards, incl. after split
  * split up to 4 hands; split aces get exactly one card each and never
    count as blackjack
"""

from __future__ import annotations

import random
import unittest

from blackjack.cards import Card, Shoe, Suit, full_deck
from blackjack.engine import (
    Action,
    Game,
    Hand,
    Outcome,
    Phase,
    Round,
    hand_total,
)

S = Suit.SPADES
H = Suit.HEARTS
D = Suit.DIAMONDS
C = Suit.CLUBS


def stack(game: Game, cards: list[Card]) -> None:
    """Force the shoe to deal `cards` in order (cards[0] dealt first).

    Also disables the cut card so this doesn't trigger a mid-test reshuffle;
    callers must supply enough cards for the whole scenario, since running
    the stacked list dry falls back to a fresh (random) shuffle.
    """
    game.shoe._cards = list(reversed(cards))
    game.shoe._cut = 0


# ---------------------------------------------------------------------------
# hand_total
# ---------------------------------------------------------------------------
class HandTotalTests(unittest.TestCase):
    def test_hard_total_no_aces(self):
        cards = [Card("10", S), Card("9", H)]
        self.assertEqual(hand_total(cards), (19, False))

    def test_soft_total_single_ace(self):
        cards = [Card("A", S), Card("6", H)]
        self.assertEqual(hand_total(cards), (17, True))

    def test_ace_demoted_when_it_would_bust(self):
        # A + 9 + 5: ace must count as 1, giving a hard 15.
        cards = [Card("A", S), Card("9", H), Card("5", D)]
        self.assertEqual(hand_total(cards), (15, False))

    def test_two_aces_plus_nine_is_21(self):
        cards = [Card("A", S), Card("A", H), Card("9", D)]
        self.assertEqual(hand_total(cards), (21, True))

    def test_three_aces_plus_eight_is_21(self):
        cards = [Card("A", S), Card("A", H), Card("A", D), Card("8", C)]
        self.assertEqual(hand_total(cards), (21, True))

    def test_multi_ace_bust_forces_all_aces_low(self):
        # A + A + 10 + 5 = 11+11+10+5=37 -> both aces low -> 1+1+10+5=17
        cards = [Card("A", S), Card("A", H), Card("10", D), Card("5", C)]
        self.assertEqual(hand_total(cards), (17, False))

    def test_natural_blackjack_total(self):
        cards = [Card("A", S), Card("K", H)]
        self.assertEqual(hand_total(cards), (21, True))


# ---------------------------------------------------------------------------
# Hand properties
# ---------------------------------------------------------------------------
class HandPropertyTests(unittest.TestCase):
    def test_is_blackjack_true_for_natural(self):
        hand = Hand(cards=[Card("A", S), Card("K", H)])
        self.assertTrue(hand.is_blackjack)

    def test_is_blackjack_false_after_split_even_at_21(self):
        hand = Hand(cards=[Card("A", S), Card("K", H)], from_split=True)
        self.assertFalse(hand.is_blackjack)

    def test_is_blackjack_false_with_three_cards(self):
        hand = Hand(cards=[Card("7", S), Card("7", H), Card("7", D)])
        self.assertFalse(hand.is_blackjack)

    def test_is_pair_same_rank(self):
        hand = Hand(cards=[Card("8", S), Card("8", H)])
        self.assertTrue(hand.is_pair)

    def test_is_pair_same_value_different_rank(self):
        hand = Hand(cards=[Card("K", S), Card("Q", H)])
        self.assertTrue(hand.is_pair)

    def test_is_pair_false_different_value(self):
        hand = Hand(cards=[Card("9", S), Card("8", H)])
        self.assertFalse(hand.is_pair)

    def test_is_bust_true_over_21(self):
        hand = Hand(cards=[Card("10", S), Card("9", H), Card("5", D)])
        self.assertTrue(hand.is_bust)

    def test_is_bust_false_at_21(self):
        hand = Hand(cards=[Card("10", S), Card("9", H), Card("2", D)])
        self.assertFalse(hand.is_bust)

    def test_label_hard_total(self):
        hand = Hand(cards=[Card("10", S), Card("5", H)])
        self.assertEqual(hand.label(), "15")

    def test_label_bust(self):
        hand = Hand(cards=[Card("10", S), Card("9", H), Card("5", D)])
        self.assertEqual(hand.label(), "BUST")

    def test_label_blackjack(self):
        hand = Hand(cards=[Card("A", S), Card("K", H)])
        self.assertEqual(hand.label(), "BLACKJACK")

    def test_label_21_after_split_is_not_blackjack_label(self):
        # A hard (ace-free) 21 built across a split shows as plain "21",
        # not "BLACKJACK" -- distinguishing a made 21 from a natural.
        hand = Hand(cards=[Card("7", S), Card("7", H), Card("7", D)],
                    from_split=True)
        self.assertFalse(hand.is_blackjack)
        self.assertEqual(hand.label(), "21")

    def test_label_21_after_split_with_an_ace_should_also_read_21(self):
        # ENGINE BUG: split K,K, then draw an Ace on one hand -> made 21,
        # correctly not a blackjack (from_split=True), but hand_total()
        # still reports it as "soft" (the ace is untouched at 11), so
        # label() takes the fractional branch and prints "11/21" instead
        # of the plain "21" the method's own docstring promises for a
        # made (non-natural) 21. Money/payout logic is unaffected (it
        # uses hand.total directly), this only mislabels the on-screen
        # total for this reachable, ordinary split scenario.
        hand = Hand(cards=[Card("K", S), Card("A", H)], from_split=True)
        self.assertFalse(hand.is_blackjack)
        self.assertEqual(hand.total, 21)
        self.assertEqual(hand.label(), "21")


# ---------------------------------------------------------------------------
# Full-round payouts
# ---------------------------------------------------------------------------
class PayoutTests(unittest.TestCase):
    def test_player_blackjack_pays_3_to_2(self):
        g = Game(bankroll=500)
        # player: A,K (natural). dealer: 9,7 (no blackjack, no ace up).
        stack(g, [Card("A", S), Card("9", H), Card("K", S), Card("7", H)])
        g.bet = 100
        g.deal()

        hand = g.round.hands[0]
        self.assertEqual(g.phase, Phase.SETTLED)
        self.assertEqual(hand.outcome, Outcome.BLACKJACK)
        self.assertEqual(hand.payout, 250)  # bet(100) + 3:2 of 100 (150)
        self.assertEqual(g.bankroll, 500 - 100 + 250)

    def test_regular_win_pays_1_to_1(self):
        g = Game(bankroll=500)
        # player: 10,9 = 19. dealer: 10,7 = 17 (stands immediately, S17).
        stack(g, [Card("10", S), Card("10", H), Card("9", S), Card("7", H)])
        g.bet = 100
        g.deal()
        g.stand()

        hand = g.round.hands[0]
        self.assertEqual(hand.outcome, Outcome.WIN)
        self.assertEqual(hand.payout, 200)
        self.assertEqual(g.bankroll, 500 - 100 + 200)

    def test_push_returns_the_bet(self):
        g = Game(bankroll=500)
        # both 20.
        stack(g, [Card("10", S), Card("10", H), Card("10", D), Card("10", C)])
        g.bet = 100
        g.deal()
        g.stand()

        hand = g.round.hands[0]
        self.assertEqual(hand.outcome, Outcome.PUSH)
        self.assertEqual(hand.payout, 100)
        self.assertEqual(g.bankroll, 500)  # unchanged

    def test_loss_returns_nothing(self):
        g = Game(bankroll=500)
        # player 16, dealer 19 (stands immediately, no draw needed).
        stack(g, [Card("10", S), Card("10", H), Card("6", S), Card("9", H)])
        g.bet = 100
        g.deal()
        g.stand()

        hand = g.round.hands[0]
        self.assertEqual(hand.outcome, Outcome.LOSE)
        self.assertEqual(hand.payout, 0)
        self.assertEqual(g.bankroll, 400)

    def test_bust_loses_even_when_dealer_also_ends_up_busting(self):
        # Split 8,8. Hand0 -> 18 (stands). Hand1 -> hits into a bust.
        # Dealer then plays out (since hand0 is still alive) and busts too.
        # Hand1 must still show BUST/0, decided before the dealer's result.
        g = Game(bankroll=500)
        stack(g, [
            Card("8", S), Card("10", H), Card("8", D), Card("6", H),  # deal
            Card("10", S),   # -> hand0's second card after split (18)
            Card("5", H),    # -> hand1's second card after split (13)
            Card("10", D),   # -> hand1 hits, busts (23)
            Card("10", C),   # -> dealer hits, busts (26)
        ])
        g.bet = 100
        g.deal()
        g.split()
        g.stand()   # locks hand0 at 18
        g.hit()     # hand1 busts, triggers dealer's turn

        hand0, hand1 = g.round.hands
        self.assertEqual(hand1.total, 23)
        self.assertTrue(hand1.is_bust)
        self.assertEqual(hand1.outcome, Outcome.BUST)
        self.assertEqual(hand1.payout, 0)

        self.assertTrue(g.round.dealer.is_bust)
        self.assertEqual(hand0.outcome, Outcome.WIN)
        self.assertEqual(hand0.payout, 200)


class DealerNoDrawOnAllBustTests(unittest.TestCase):
    def test_dealer_does_not_draw_when_player_busts(self):
        g = Game(bankroll=500)
        # player 15 -> hits a 10 -> busts at 25. Dealer sits on a made-up
        # low total (5) that would normally demand several hits.
        stack(g, [Card("10", S), Card("2", H), Card("5", S), Card("3", H),
                  Card("10", D)])
        g.bet = 100
        g.deal()
        g.hit()

        dealer = g.round.dealer
        self.assertEqual(len(dealer.cards), 2)
        self.assertEqual(dealer.total, 5)
        self.assertEqual(g.phase, Phase.SETTLED)
        self.assertEqual(g.round.hands[0].outcome, Outcome.BUST)


# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------
class InsuranceTests(unittest.TestCase):
    def test_taking_insurance_against_dealer_blackjack_nets_zero(self):
        g = Game(bankroll=500)
        # player 10,6=16 (not blackjack). dealer A,K = blackjack.
        stack(g, [Card("10", S), Card("A", H), Card("6", S), Card("K", H)])
        g.bet = 100
        g.deal()
        self.assertEqual(g.phase, Phase.INSURANCE)
        self.assertEqual(g.insurance_cost, 50)

        g.take_insurance(True)

        self.assertEqual(g.round.insurance_result, "won")
        hand = g.round.hands[0]
        self.assertEqual(hand.outcome, Outcome.LOSE)
        self.assertEqual(hand.payout, 0)
        # -100 (bet) - 50 (insurance) + 150 (2:1 insurance payout) == 0 net.
        self.assertEqual(g.bankroll, 500)

    def test_declining_insurance_against_dealer_blackjack_loses_bet(self):
        g = Game(bankroll=500)
        stack(g, [Card("10", S), Card("A", H), Card("6", S), Card("K", H)])
        g.bet = 100
        g.deal()
        g.take_insurance(False)

        self.assertIsNone(g.round.insurance_result)
        hand = g.round.hands[0]
        self.assertEqual(hand.outcome, Outcome.LOSE)
        self.assertEqual(g.bankroll, 400)  # lost exactly the bet

    def test_taking_insurance_when_dealer_has_no_blackjack_loses_half_bet(self):
        g = Game(bankroll=500)
        # dealer shows an ace but hole card is a 5: no blackjack.
        stack(g, [Card("10", S), Card("A", H), Card("6", S), Card("5", H)])
        g.bet = 100
        g.deal()
        g.take_insurance(True)

        self.assertEqual(g.round.insurance_result, "lost")
        # Only the insurance side bet (50) has been lost so far; the main
        # hand hasn't been settled yet.
        self.assertEqual(g.bankroll, 500 - 100 - 50)
        self.assertEqual(g.phase, Phase.PLAYER)


# ---------------------------------------------------------------------------
# Dealer play (S17)
# ---------------------------------------------------------------------------
class DealerPlayTests(unittest.TestCase):
    def test_dealer_stands_on_hard_17(self):
        g = Game(bankroll=500)
        stack(g, [Card("10", S), Card("10", H), Card("9", S), Card("7", H)])
        g.bet = 100
        g.deal()
        g.stand()

        dealer = g.round.dealer
        self.assertEqual(len(dealer.cards), 2)
        self.assertEqual(dealer.total, 17)

    def test_dealer_hits_16(self):
        g = Game(bankroll=500)
        stack(g, [Card("10", S), Card("10", H), Card("9", S), Card("6", H),
                  Card("5", D)])
        g.bet = 100
        g.deal()
        g.stand()

        dealer = g.round.dealer
        self.assertEqual(len(dealer.cards), 3)
        self.assertEqual(dealer.total, 21)

    def test_dealer_stands_on_soft_17(self):
        g = Game(bankroll=500)
        # dealer shows an ace with a 6 in the hole = soft 17.
        stack(g, [Card("10", S), Card("A", H), Card("9", S), Card("6", H)])
        g.bet = 100
        g.deal()
        g.take_insurance(False)
        g.stand()

        dealer = g.round.dealer
        self.assertEqual(len(dealer.cards), 2)
        self.assertEqual(dealer.total, 17)
        self.assertTrue(dealer.soft)


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------
class SplitTests(unittest.TestCase):
    def test_split_debits_second_bet_and_deals_one_card_each(self):
        g = Game(bankroll=500)
        stack(g, [Card("8", S), Card("2", H), Card("8", D), Card("3", H),
                  Card("10", S), Card("9", H)])
        g.bet = 100
        g.deal()
        self.assertEqual(g.bankroll, 400)

        g.split()

        self.assertEqual(g.bankroll, 300)  # second 100 debited
        self.assertEqual(len(g.round.hands), 2)
        for hand in g.round.hands:
            self.assertEqual(hand.bet, 100)
            self.assertEqual(len(hand.cards), 2)

    def test_split_aces_get_one_card_each_and_are_never_blackjack(self):
        g = Game(bankroll=500)
        # player A,A. dealer 9,7 (no ace up, no blackjack). Post-split cards
        # are both kings, which would be a natural if this counted as one.
        stack(g, [Card("A", S), Card("9", H), Card("A", D), Card("7", H),
                  Card("K", S), Card("K", H)])
        g.bet = 100
        g.deal()
        g.split()

        hand0, hand1 = g.round.hands
        for hand in (hand0, hand1):
            self.assertEqual(len(hand.cards), 2)
            self.assertTrue(hand.split_aces)
            self.assertEqual(hand.total, 21)
            self.assertFalse(hand.is_blackjack)
            self.assertNotEqual(hand.outcome, Outcome.BLACKJACK)

    def test_split_aces_hand_has_no_available_actions(self):
        # Construct a round directly so the split-aces hand is the active
        # one, isolating the available() guard from the auto-advance flow
        # (which would otherwise always skip straight past it).
        g = Game(bankroll=500)
        split_ace_hand = Hand(cards=[Card("A", S), Card("K", H)],
                               from_split=True, split_aces=True, bet=100)
        other_hand = Hand(cards=[Card("5", S), Card("6", H)], bet=100)
        g.round = Round(hands=[split_ace_hand, other_hand],
                         dealer=Hand(cards=[Card("2", S), Card("3", H)]))
        g.phase = Phase.PLAYER
        g.round.active = 0

        self.assertEqual(g.available(), [])

    def test_max_four_hands_enforced(self):
        g = Game(bankroll=1000)
        four_hands = [Hand(cards=[Card("8", S), Card("8", H)], bet=100)
                      for _ in range(4)]
        g.round = Round(hands=four_hands,
                         dealer=Hand(cards=[Card("2", S), Card("3", H)]))
        g.phase = Phase.PLAYER
        g.round.active = 0
        self.assertNotIn(Action.SPLIT, g.available())

    def test_split_available_with_three_hands(self):
        g = Game(bankroll=1000)
        three_hands = [Hand(cards=[Card("8", S), Card("8", H)], bet=100)
                       for _ in range(3)]
        g.round = Round(hands=three_hands,
                         dealer=Hand(cards=[Card("2", S), Card("3", H)]))
        g.phase = Phase.PLAYER
        g.round.active = 0
        self.assertIn(Action.SPLIT, g.available())


# ---------------------------------------------------------------------------
# Double down
# ---------------------------------------------------------------------------
class DoubleTests(unittest.TestCase):
    def test_double_debits_bet_doubles_it_draws_one_card_and_ends_hand(self):
        g = Game(bankroll=500)
        # dealer already at 17 so it won't need to draw further, keeping
        # the shoe fully deterministic without extra padding cards.
        stack(g, [Card("5", S), Card("10", H), Card("4", S), Card("7", H),
                  Card("7", D)])
        g.bet = 100
        g.deal()
        self.assertEqual(g.bankroll, 400)

        g.double()

        hand = g.round.hands[0]
        self.assertEqual(hand.bet, 200)
        self.assertTrue(hand.doubled)
        self.assertTrue(hand.stood)
        self.assertEqual(len(hand.cards), 3)
        self.assertEqual(g.bankroll, 300)  # second 100 debited, hand lost


# ---------------------------------------------------------------------------
# Bet clamping
# ---------------------------------------------------------------------------
class BetClampingTests(unittest.TestCase):
    def test_adjust_bet_clamps_to_minimum(self):
        g = Game(bankroll=500)
        g.adjust_bet(-1000)
        self.assertEqual(g.bet, Game.MIN_BET)

    def test_adjust_bet_clamps_to_maximum(self):
        g = Game(bankroll=500)
        g.adjust_bet(1_000_000)
        self.assertEqual(g.bet, Game.MAX_BET)

    def test_adjust_bet_clamps_to_bankroll_below_table_max(self):
        g = Game(bankroll=50)
        g.adjust_bet(1_000_000)
        self.assertEqual(g.bet, 50)

    def test_adjust_bet_no_op_returns_false(self):
        g = Game(bankroll=500)
        g.bet = Game.MIN_BET
        self.assertFalse(g.adjust_bet(-1))
        self.assertEqual(g.bet, Game.MIN_BET)

    def test_clamp_bet_pulls_bet_down_after_bankroll_shrinks(self):
        g = Game(bankroll=500)
        g.bet = 500
        g.bankroll = 50
        g.clamp_bet()
        self.assertEqual(g.bet, 50)


# ---------------------------------------------------------------------------
# Shoe
# ---------------------------------------------------------------------------
class ShoeTests(unittest.TestCase):
    def test_six_deck_shoe_has_312_cards(self):
        shoe = Shoe(decks=6, rng=random.Random(0))
        self.assertEqual(shoe.total, 312)
        self.assertEqual(shoe.remaining, 312)

    def test_deal_reduces_remaining_count(self):
        shoe = Shoe(decks=6, rng=random.Random(0))
        shoe.deal()
        self.assertEqual(shoe.remaining, 311)

    def test_needs_shuffle_flips_at_the_cut_card(self):
        shoe = Shoe(decks=6, penetration=0.75, rng=random.Random(0))
        cut = shoe._cut
        self.assertEqual(cut, int(312 * 0.25))

        # Deal down to exactly one card above the cut point.
        for _ in range(shoe.total - (cut + 1)):
            shoe.deal()
        self.assertEqual(shoe.remaining, cut + 1)
        self.assertFalse(shoe.needs_shuffle)

        shoe.deal()
        self.assertEqual(shoe.remaining, cut)
        self.assertTrue(shoe.needs_shuffle)

    def test_full_deck_has_52_unique_cards(self):
        deck = full_deck()
        self.assertEqual(len(deck), 52)
        self.assertEqual(len({(c.rank, c.suit) for c in deck}), 52)

    def test_game_reshuffles_shoe_once_cut_card_is_passed(self):
        g = Game(decks=1, bankroll=500, rng=random.Random(1))
        shuffles_before = g.shoe.shuffles
        # Simulate a near-exhausted shoe (below the cut point for 1 deck).
        g.shoe._cards = g.shoe._cards[:5]
        g.shoe._cut = int(52 * 0.25)
        self.assertTrue(g.shoe.needs_shuffle)

        g.bet = 25
        g.deal()

        self.assertEqual(g.shoe.shuffles, shuffles_before + 1)
        self.assertEqual(g.shoe.remaining, 52 - 4)  # fresh shoe minus 4 dealt
        self.assertFalse(g.shoe.needs_shuffle)


if __name__ == "__main__":
    unittest.main()
