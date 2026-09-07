"""Cards and the shoe they come out of.

Pure data and randomness -- nothing here knows about blackjack or curses.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


class Suit(Enum):
    SPADES = ("S", "♠", False)
    HEARTS = ("H", "♥", True)
    DIAMONDS = ("D", "♦", True)
    CLUBS = ("C", "♣", False)

    def __init__(self, letter: str, glyph: str, red: bool):
        self.letter = letter
        self.glyph = glyph
        self.red = red


@dataclass(frozen=True)
class Card:
    rank: str
    suit: Suit

    @property
    def value(self) -> int:
        """Blackjack value, counting an ace high. Hand totals soften aces."""
        if self.rank == "A":
            return 11
        if self.rank in ("J", "Q", "K"):
            return 10
        return int(self.rank)

    @property
    def is_ace(self) -> bool:
        return self.rank == "A"

    @property
    def is_ten(self) -> bool:
        return self.value == 10

    def __str__(self) -> str:
        return f"{self.rank}{self.suit.glyph}"


def full_deck() -> list[Card]:
    return [Card(rank, suit) for suit in Suit for rank in RANKS]


class Shoe:
    """A multi-deck shoe with a cut card.

    Cards are dealt off the end of the list so dealing is O(1). ``needs_shuffle``
    goes true once the cut card is reached; the round in progress finishes first,
    which is how a real table plays it.
    """

    def __init__(self, decks: int = 6, penetration: float = 0.75,
                 rng: random.Random | None = None):
        self.decks = decks
        self.penetration = penetration
        self.rng = rng or random.Random()
        self._cards: list[Card] = []
        self._cut = 0
        self.shuffles = 0
        self.shuffle()

    def shuffle(self) -> None:
        self._cards = [c for _ in range(self.decks) for c in full_deck()]
        self.rng.shuffle(self._cards)
        # Cut card sits `penetration` of the way through the shoe.
        self._cut = int(len(self._cards) * (1.0 - self.penetration))
        self.shuffles += 1

    def deal(self) -> Card:
        if not self._cards:
            self.shuffle()
        return self._cards.pop()

    @property
    def remaining(self) -> int:
        return len(self._cards)

    @property
    def total(self) -> int:
        return self.decks * 52

    @property
    def needs_shuffle(self) -> bool:
        return self.remaining <= self._cut

    @property
    def fraction_left(self) -> float:
        """0.0-1.0, for the shoe gauge in the sidebar."""
        return self.remaining / self.total if self.total else 0.0
