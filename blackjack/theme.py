"""Colour pairs and glyphs.

One place to change the look. Pairs are registered once at startup; everything
else refers to them through the module-level names.
"""

from __future__ import annotations

import curses

# Pair ids. 0 is reserved by curses for the terminal default.
FRAME = 1        # idle panel borders
FRAME_HI = 2     # border of the panel that currently has focus
TITLE = 3        # panel titles sitting in the border
LABEL = 4        # dim captions
TEXT = 5         # ordinary text
CARD = 6         # card face, black suits
CARD_RED = 7     # card face, red suits
CARD_BACK = 8    # face-down card
WIN = 9
LOSE = 10
PUSH = 11
CHIP = 12        # bankroll / bet figures
KEY = 13         # the bracketed letter in a key hint
ACCENT = 14      # active-hand marker, gauge fill
DIM = 15

_DEFAULT = -1


def _pair(idx: int, fg: int, bg: int = _DEFAULT) -> None:
    try:
        curses.init_pair(idx, fg, bg)
    except curses.error:
        pass


def setup() -> bool:
    """Install the palette. Returns False on a monochrome terminal."""
    if not curses.has_colors():
        return False
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass

    rich = curses.COLORS >= 256
    if rich:
        grey, slate, sky, ice = 240, 245, 39, 117
        red, green, gold, plum = 203, 78, 220, 176
        card_bg, back_bg = 253, 24
        ink = 235
    else:
        grey, slate, sky, ice = curses.COLOR_BLUE, curses.COLOR_WHITE, \
            curses.COLOR_CYAN, curses.COLOR_CYAN
        red, green, gold, plum = curses.COLOR_RED, curses.COLOR_GREEN, \
            curses.COLOR_YELLOW, curses.COLOR_MAGENTA
        card_bg, back_bg = curses.COLOR_WHITE, curses.COLOR_BLUE
        ink = curses.COLOR_BLACK

    _pair(FRAME, grey)
    _pair(FRAME_HI, sky)
    _pair(TITLE, ice)
    _pair(LABEL, slate)
    _pair(TEXT, curses.COLOR_WHITE)
    _pair(CARD, ink, card_bg)
    _pair(CARD_RED, red, card_bg)
    _pair(CARD_BACK, ice, back_bg)
    _pair(WIN, green)
    _pair(LOSE, red)
    _pair(PUSH, gold)
    _pair(CHIP, gold)
    _pair(KEY, plum)
    _pair(ACCENT, sky)
    _pair(DIM, grey)
    return True


def c(pair: int, bold: bool = False, dim: bool = False) -> int:
    attr = curses.color_pair(pair)
    if bold:
        attr |= curses.A_BOLD
    if dim:
        attr |= curses.A_DIM
    return attr


class Glyphs:
    """Box-drawing set, with an ASCII fallback for terminals that mangle UTF-8."""

    def __init__(self, unicode_ok: bool = True):
        self.unicode = unicode_ok
        if unicode_ok:
            self.tl, self.tr, self.bl, self.br = "╭", "╮", "╰", "╯"
            self.h, self.v = "─", "│"
            self.tee_l, self.tee_r = "├", "┤"
            self.tee_d, self.tee_u, self.joint = "┬", "┴", "┼"
            self.card_tl, self.card_tr = "╭", "╮"
            self.card_bl, self.card_br = "╰", "╯"
            self.back = "▓"
            self.gauge_full, self.gauge_empty = "█", "░"
            self.marker = "▸"
            self.tick, self.cross, self.near = "✓", "✗", "≈"
            self.suits = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
        else:
            self.tl = self.tr = self.bl = self.br = "+"
            self.h, self.v = "-", "|"
            self.tee_l, self.tee_r = "+", "+"
            self.tee_d = self.tee_u = self.joint = "+"
            self.card_tl = self.card_tr = self.card_bl = self.card_br = "+"
            self.back = "#"
            self.gauge_full, self.gauge_empty = "#", "."
            self.marker = ">"
            self.tick, self.cross, self.near = "+", "x", "~"
            self.suits = {"S": "s", "H": "h", "D": "d", "C": "c"}
