#!/usr/bin/env python3
"""Play a few hundred thousand hands of perfect basic strategy against the
engine and print the resulting house edge.

Basic strategy for this game's rules (6 decks, dealer stands on all 17, double
after split allowed, no surrender) is worth about 0.5% to the house. If the
engine's rules or payouts drift, this number moves well outside that range --
so it is a sharp check that a unit test cannot easily give.

    python3 tools/verify_odds.py [hands]
"""

from __future__ import annotations

import random
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blackjack.engine import Action, Game, Phase, hand_total  # noqa: E402

H, S, D, P = "H", "S", "D", "P"

# Dealer upcard is indexed 2..11, where 11 is an ace.
HARD = {
    5: {u: H for u in range(2, 12)},
    6: {u: H for u in range(2, 12)},
    7: {u: H for u in range(2, 12)},
    8: {u: H for u in range(2, 12)},
    9: {u: (D if 3 <= u <= 6 else H) for u in range(2, 12)},
    10: {u: (D if 2 <= u <= 9 else H) for u in range(2, 12)},
    11: {u: (D if u <= 10 else H) for u in range(2, 12)},
    12: {u: (S if 4 <= u <= 6 else H) for u in range(2, 12)},
    13: {u: (S if u <= 6 else H) for u in range(2, 12)},
    14: {u: (S if u <= 6 else H) for u in range(2, 12)},
    15: {u: (S if u <= 6 else H) for u in range(2, 12)},
    16: {u: (S if u <= 6 else H) for u in range(2, 12)},
}
for t in range(17, 22):
    HARD[t] = {u: S for u in range(2, 12)}

# Keyed by the non-ace card in a two-card soft hand.
SOFT = {
    2: {u: (D if 5 <= u <= 6 else H) for u in range(2, 12)},
    3: {u: (D if 5 <= u <= 6 else H) for u in range(2, 12)},
    4: {u: (D if 4 <= u <= 6 else H) for u in range(2, 12)},
    5: {u: (D if 4 <= u <= 6 else H) for u in range(2, 12)},
    6: {u: (D if 3 <= u <= 6 else H) for u in range(2, 12)},
    7: {u: (D if 3 <= u <= 6 else (S if u in (2, 7, 8) else H)) for u in range(2, 12)},
    8: {u: S for u in range(2, 12)},
    9: {u: S for u in range(2, 12)},
}

PAIRS = {
    11: {u: P for u in range(2, 12)},                                  # A,A
    10: {u: S for u in range(2, 12)},
    9: {u: (P if (2 <= u <= 6 or u in (8, 9)) else S) for u in range(2, 12)},
    8: {u: P for u in range(2, 12)},
    7: {u: (P if u <= 7 else H) for u in range(2, 12)},
    6: {u: (P if u <= 6 else H) for u in range(2, 12)},
    5: {u: (D if 2 <= u <= 9 else H) for u in range(2, 12)},           # play as 10
    4: {u: (P if 5 <= u <= 6 else H) for u in range(2, 12)},
    3: {u: (P if u <= 7 else H) for u in range(2, 12)},
    2: {u: (P if u <= 7 else H) for u in range(2, 12)},
}


def decide(hand, upcard, available) -> Action:
    up = upcard.value
    cards = hand.cards

    if hand.is_pair and Action.SPLIT in available:
        move = PAIRS[cards[0].value][up]
        if move == P:
            return Action.SPLIT

    total, soft = hand_total(cards)
    if soft and len(cards) == 2 and total <= 21:
        other = total - 11
        move = SOFT.get(other, {}).get(up, H)
    else:
        move = HARD.get(min(total, 21), {}).get(up, S)

    if move == D:
        if Action.DOUBLE in available:
            return Action.DOUBLE
        # Doubling is off the table with three or more cards; soft doubles are
        # defensive and become stands, hard doubles stay hits.
        move = S if (soft and total >= 18) else H
    return Action.HIT if move == H else Action.STAND


def main(target: int = 500_000) -> int:
    rng = random.Random(20260907)
    game = Game(bankroll=10**12, rng=rng)
    game.bet = 100
    staked = 0
    rounds = 0

    while rounds < target:
        if game.phase is Phase.BETTING:
            game.bet = 100
            game.deal()
            staked += 100
            rounds += 1
        elif game.phase is Phase.INSURANCE:
            game.take_insurance(False)          # never a basic-strategy play
        elif game.phase is Phase.PLAYER:
            available = game.available()
            action = decide(game.round.hand, game.round.dealer.cards[0], available)
            if action not in available:
                action = Action.STAND if Action.STAND in available else Action.HIT
            if action is Action.DOUBLE:
                staked += game.round.hand.bet
            elif action is Action.SPLIT:
                staked += game.round.hand.bet
            game.act(action)
        else:
            game.next_round()

    net = game.bankroll - game.starting_bankroll
    n = game.hands_played
    edge = -net / staked
    print(f"rounds        {rounds}")
    print(f"hands         {n}")
    print(f"shuffles      {game.shoe.shuffles}")
    print(f"win/lose/push {game.wins/n:.2%} / {game.losses/n:.2%} / {game.pushes/n:.2%}")
    # Naturals that pushed against a dealer natural book as pushes, not
    # blackjacks, so this lands a touch under the 4.75% dealing frequency.
    print(f"naturals      {game.blackjacks/rounds:.2%}  (theory 4.75%, less BJ pushes)")
    print(f"house edge    {edge:.3%}  (basic strategy, these rules: ~0.5%)")
    ok = 0.001 <= edge <= 0.011
    print("VERDICT       " + ("plausible" if ok else "OUT OF RANGE -- check the rules"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 500_000))
