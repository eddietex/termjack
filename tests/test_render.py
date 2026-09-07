"""Tests for the drawing in blackjack.render.

Nothing here needs a terminal. The window is a stub that remembers what was
written to it, and the one curses call the drawing makes -- looking up a
colour pair -- is stubbed out with it, so what a card looks like can be
asserted on directly.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from blackjack import render
from blackjack.cards import Card, Suit
from blackjack.theme import Glyphs

S = Suit.SPADES
H = Suit.HEARTS


class Recorder:
    """A window that keeps the characters written to it."""

    def __init__(self, h: int = 8, w: int = 40):
        self.size = (h, w)
        self.rows = [[" "] * w for _ in range(h)]

    def getmaxyx(self) -> tuple[int, int]:
        return self.size

    def addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        for i, ch in enumerate(text):
            if 0 <= y < self.size[0] and 0 <= x + i < self.size[1]:
                self.rows[y][x + i] = ch

    def text(self) -> str:
        return "\n".join("".join(row) for row in self.rows)


def drawn(**kwargs) -> str:
    """A dealer hand -- a 5 up, a king in the hole -- as it reaches the screen."""
    win, g = Recorder(), Glyphs(True)
    cards = [Card("5", S), Card("K", H)]
    with patch("blackjack.render.c", lambda *a, **k: 0):
        render.draw_hand(win, 0, 0, cards, g, **kwargs)
    return win.text()


class HoleCardTests(unittest.TestCase):
    """The dealer's second card is dealt face down, and every frame of the
    turn it lands on has to keep it that way -- it is the one card on the
    table whose face is worth money."""

    def test_the_hole_card_never_shows_while_it_turns_face_down(self):
        for frame in range(len(render.FLIP_FRAMES) + 2):
            screen = drawn(hole_down=True, reveal=1, turn=(1, frame))
            with self.subTest(frame=frame):
                self.assertNotIn("K", screen)
                self.assertNotIn("♥", screen)

    def test_the_hole_card_never_shows_once_it_has_landed(self):
        screen = drawn(hole_down=True, reveal=2)
        self.assertNotIn("K", screen)
        self.assertIn("5", screen)          # the upcard is up all along

    def test_the_dealer_turning_it_up_does_show_it(self):
        """The one turn that reveals: hole_down off is the dealer taking the
        card, and by the last frame the hand is readable."""
        last = len(render.FLIP_FRAMES) - 1
        self.assertNotIn("K", drawn(hole_down=False, reveal=2, turn=(1, 0)))
        self.assertIn("K", drawn(hole_down=False, reveal=2, turn=(1, last)))

    def test_a_card_on_its_way_in_holds_its_slot(self):
        """The incoming card is drawn even though it has not landed, so the
        cards already down do not shuffle sideways when it does."""
        screen = drawn(reveal=1, turn=(1, 0))
        self.assertEqual(screen.splitlines()[0].rstrip(),
                         "╭───╮ ╭───╮")


if __name__ == "__main__":
    unittest.main()
