"""Blackjack rules.

Traditional Vegas shoe game:

  * 6-deck shoe, reshuffled when the cut card comes out
  * dealer stands on all 17 (S17)
  * blackjack pays 3:2
  * insurance offered on a dealer ace, pays 2:1
  * double down on any first two cards, including after a split
  * split up to 4 hands; split aces get exactly one card each and never
    count as blackjack

No curses, no I/O: everything here is testable in isolation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto

from .cards import Card, Shoe

MAX_HANDS = 4


class Action(Enum):
    HIT = ("h", "hit")
    STAND = ("s", "stand")
    DOUBLE = ("d", "double")
    SPLIT = ("p", "split")

    def __init__(self, key: str, label: str):
        self.key = key
        self.label = label


class Phase(Enum):
    BETTING = auto()       # waiting for the player to size a bet
    INSURANCE = auto()     # dealer shows an ace, side bet offered
    PLAYER = auto()        # player acting on the active hand
    DEALER = auto()        # dealer drawing out
    SETTLED = auto()       # payouts booked, waiting for the next deal


class Outcome(Enum):
    BLACKJACK = "blackjack"
    WIN = "win"
    PUSH = "push"
    LOSE = "lose"
    BUST = "bust"


def hand_total(cards: list[Card]) -> tuple[int, bool]:
    """Best total for a set of cards, plus whether it is soft.

    Aces count 11 while that keeps the total at or under 21, else 1.
    """
    total = sum(c.value for c in cards)
    aces = sum(1 for c in cards if c.is_ace)
    soft = aces > 0
    while total > 21 and aces:
        total -= 10
        aces -= 1
        soft = aces > 0
    return total, soft


@dataclass
class Hand:
    cards: list[Card] = field(default_factory=list)
    bet: int = 0
    doubled: bool = False
    stood: bool = False
    from_split: bool = False
    split_aces: bool = False
    outcome: Outcome | None = None
    payout: int = 0          # returned to the bankroll at settlement

    # -- totals ------------------------------------------------------------
    @property
    def total(self) -> int:
        return hand_total(self.cards)[0]

    @property
    def soft(self) -> bool:
        return hand_total(self.cards)[1]

    @property
    def is_bust(self) -> bool:
        return self.total > 21

    @property
    def is_blackjack(self) -> bool:
        """Natural 21. A 21 assembled after a split does not count."""
        return len(self.cards) == 2 and self.total == 21 and not self.from_split

    @property
    def is_pair(self) -> bool:
        return len(self.cards) == 2 and self.cards[0].value == self.cards[1].value

    @property
    def is_done(self) -> bool:
        return self.stood or self.is_bust or self.total == 21

    def label(self) -> str:
        """Total as shown on screen: '17' hard, '7/17' soft, 'BUST', '21'.

        A soft hand is only shown both ways while the choice still matters; at
        21 there is nothing left to decide, so it reads as a plain 21.
        """
        if self.is_blackjack:
            return "BLACKJACK"
        if self.is_bust:
            return "BUST"
        total, soft = hand_total(self.cards)
        if soft and total < 21:
            return f"{total - 10}/{total}"
        return str(total)


@dataclass
class Round:
    hands: list[Hand]
    dealer: Hand
    active: int = 0                 # index into hands
    hole_down: bool = True          # dealer's second card still face down
    insurance: int = 0              # amount staked on the side bet
    insurance_offered: bool = False
    insurance_result: str | None = None   # 'won' | 'lost' | None

    @property
    def hand(self) -> Hand:
        return self.hands[self.active]

    @property
    def is_split(self) -> bool:
        return len(self.hands) > 1


class Game:
    """Bankroll, shoe, statistics, and the round currently on the table."""

    MIN_BET = 5
    MAX_BET = 500
    CHIPS = (5, 25, 100)

    def __init__(self, bankroll: int = 500, decks: int = 6,
                 rng: random.Random | None = None):
        self.shoe = Shoe(decks=decks, rng=rng)
        self.bankroll = bankroll
        self.starting_bankroll = bankroll
        self.bet = 25
        self.phase = Phase.BETTING
        self.round: Round | None = None
        self.wins = 0
        self.losses = 0
        self.pushes = 0
        self.blackjacks = 0
        self.hands_played = 0
        self.message = "Place your bet."

    # -- betting -----------------------------------------------------------
    @property
    def max_bet(self) -> int:
        return min(self.MAX_BET, self.bankroll)

    def adjust_bet(self, delta: int) -> bool:
        """Nudge the wager inside the table limits. False if it did not move."""
        new = max(self.MIN_BET, min(self.max_bet, self.bet + delta))
        if new == self.bet:
            return False
        self.bet = new
        return True

    def clamp_bet(self) -> None:
        self.bet = max(self.MIN_BET, min(self.max_bet, self.bet))

    @property
    def is_broke(self) -> bool:
        return self.bankroll < self.MIN_BET

    # -- dealing -----------------------------------------------------------
    def deal(self) -> None:
        """Take the wager and put four cards on the table."""
        if self.phase not in (Phase.BETTING, Phase.SETTLED):
            return
        if self.shoe.needs_shuffle:
            self.shoe.shuffle()
        self.clamp_bet()
        if self.bet > self.bankroll:
            self.message = "Not enough chips for that bet."
            return

        self.bankroll -= self.bet
        player = Hand(bet=self.bet)
        dealer = Hand()
        player.cards.append(self.shoe.deal())
        dealer.cards.append(self.shoe.deal())
        player.cards.append(self.shoe.deal())
        dealer.cards.append(self.shoe.deal())
        self.round = Round(hands=[player], dealer=dealer)

        if dealer.cards[0].is_ace:
            self.round.insurance_offered = True
            self.phase = Phase.INSURANCE
            self.message = "Dealer shows an ace. Insurance?"
        else:
            self._after_insurance()

    # -- insurance ---------------------------------------------------------
    @property
    def insurance_cost(self) -> int:
        rnd = self.round
        return rnd.hands[0].bet // 2 if rnd else 0

    def can_insure(self) -> bool:
        return (self.phase is Phase.INSURANCE
                and self.bankroll >= self.insurance_cost)

    def take_insurance(self, taken: bool) -> None:
        if self.phase is not Phase.INSURANCE:
            return
        if taken and self.can_insure():
            self.round.insurance = self.insurance_cost
            self.bankroll -= self.round.insurance
        self._after_insurance()

    def _after_insurance(self) -> None:
        """Peek at the hole card when the upcard could make a blackjack."""
        rnd = self.round
        up = rnd.dealer.cards[0]
        dealer_bj = rnd.dealer.is_blackjack

        if rnd.insurance:
            if dealer_bj:
                # Side bet pays 2:1, so the stake plus twice it comes back.
                rnd.insurance_result = "won"
                self.bankroll += rnd.insurance * 3
            else:
                rnd.insurance_result = "lost"

        if (up.is_ace or up.is_ten) and dealer_bj:
            rnd.hole_down = False
            self._settle()
            return

        if rnd.hands[0].is_blackjack:
            self.phase = Phase.PLAYER
            self._advance()
            return

        self.phase = Phase.PLAYER
        self.message = "Your move."

    # -- player actions ----------------------------------------------------
    def available(self) -> list[Action]:
        if self.phase is not Phase.PLAYER or self.round is None:
            return []
        hand = self.round.hand
        if hand.is_done or hand.split_aces:
            return []
        actions = [Action.HIT, Action.STAND]
        first_two = len(hand.cards) == 2
        if first_two and self.bankroll >= hand.bet:
            actions.append(Action.DOUBLE)
        if (first_two and hand.is_pair
                and len(self.round.hands) < MAX_HANDS
                and self.bankroll >= hand.bet):
            actions.append(Action.SPLIT)
        return actions

    def act(self, action: Action) -> bool:
        """Apply a player action. False if it was not legal right now."""
        if action not in self.available():
            return False
        return {
            Action.HIT: self.hit,
            Action.STAND: self.stand,
            Action.DOUBLE: self.double,
            Action.SPLIT: self.split,
        }[action]()

    def hit(self) -> bool:
        hand = self.round.hand
        hand.cards.append(self.shoe.deal())
        if hand.is_bust:
            self.message = "Bust."
        self._advance()
        return True

    def stand(self) -> bool:
        self.round.hand.stood = True
        self._advance()
        return True

    def double(self) -> bool:
        hand = self.round.hand
        self.bankroll -= hand.bet
        hand.bet *= 2
        hand.doubled = True
        hand.cards.append(self.shoe.deal())
        hand.stood = True
        self.message = "Bust." if hand.is_bust else "Doubled down."
        self._advance()
        return True

    def split(self) -> bool:
        rnd = self.round
        hand = rnd.hand
        moved = hand.cards.pop()
        aces = moved.is_ace

        new = Hand(cards=[moved], bet=hand.bet, from_split=True, split_aces=aces)
        hand.from_split = True
        hand.split_aces = aces
        self.bankroll -= hand.bet
        rnd.hands.insert(rnd.active + 1, new)

        # One fresh card to each half.
        hand.cards.append(self.shoe.deal())
        new.cards.append(self.shoe.deal())
        self.message = "Split aces." if aces else "Split."
        self._advance()
        return True

    def _advance(self) -> None:
        """Move to the next hand needing a decision, or on to the dealer."""
        rnd = self.round
        while rnd.active < len(rnd.hands):
            hand = rnd.hand
            if not hand.is_done and not hand.split_aces:
                return
            rnd.active += 1
        rnd.active = len(rnd.hands) - 1
        self._dealer_turn()

    # -- dealer ------------------------------------------------------------
    def _dealer_turn(self) -> None:
        rnd = self.round
        rnd.hole_down = False
        self.phase = Phase.DEALER

        # The dealer only plays out if some hand is still live.
        if any(not h.is_bust for h in rnd.hands):
            everyone_natural = all(h.is_blackjack for h in rnd.hands)
            if not everyone_natural:
                while rnd.dealer.total < 17:
                    rnd.dealer.cards.append(self.shoe.deal())
        self._settle()

    # -- settlement --------------------------------------------------------
    def _settle(self) -> None:
        rnd = self.round
        dealer = rnd.dealer
        d_total = dealer.total
        d_bj = dealer.is_blackjack
        d_bust = dealer.is_bust

        for hand in rnd.hands:
            if hand.is_bust:
                hand.outcome = Outcome.BUST
                hand.payout = 0
            elif hand.is_blackjack and not d_bj:
                hand.outcome = Outcome.BLACKJACK
                hand.payout = hand.bet + (hand.bet * 3) // 2
            elif d_bj and not hand.is_blackjack:
                hand.outcome = Outcome.LOSE
                hand.payout = 0
            elif hand.is_blackjack and d_bj:
                hand.outcome = Outcome.PUSH
                hand.payout = hand.bet
            elif d_bust or hand.total > d_total:
                hand.outcome = Outcome.WIN
                hand.payout = hand.bet * 2
            elif hand.total == d_total:
                hand.outcome = Outcome.PUSH
                hand.payout = hand.bet
            else:
                hand.outcome = Outcome.LOSE
                hand.payout = 0

            self.bankroll += hand.payout
            self.hands_played += 1
            if hand.outcome is Outcome.BLACKJACK:
                self.blackjacks += 1
                self.wins += 1
            elif hand.outcome is Outcome.WIN:
                self.wins += 1
            elif hand.outcome is Outcome.PUSH:
                self.pushes += 1
            else:
                self.losses += 1

        self.phase = Phase.SETTLED
        self.message = self._settlement_message()
        self.clamp_bet()

    def _settlement_message(self) -> str:
        rnd = self.round
        net = sum(h.payout for h in rnd.hands) - sum(h.bet for h in rnd.hands)
        if rnd.insurance:
            net += rnd.insurance * 2 if rnd.insurance_result == "won" else -rnd.insurance

        if rnd.dealer.is_blackjack:
            head = "Dealer has blackjack."
        elif rnd.dealer.is_bust:
            head = "Dealer busts."
        elif len(rnd.hands) == 1 and rnd.hands[0].is_blackjack:
            head = "Blackjack!"
        else:
            head = f"Dealer stands on {rnd.dealer.total}."

        if net > 0:
            return f"{head} You win ${net}."
        if net < 0:
            return f"{head} You lose ${-net}."
        return f"{head} Push."

    # -- next round --------------------------------------------------------
    def next_round(self) -> None:
        if self.phase is not Phase.SETTLED:
            return
        self.round = None
        self.phase = Phase.BETTING
        self.clamp_bet()
        if self.is_broke:
            self.message = "You are out of chips."
        elif self.shoe.needs_shuffle:
            self.message = "Shuffling the shoe. Place your bet."
        else:
            self.message = "Place your bet."
