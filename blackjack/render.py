"""Drawing primitives: panels, cards, gauges.

Everything writes onto a curses window and clips itself to that window, so a
resize mid-draw degrades instead of raising.
"""

from __future__ import annotations

import curses

from .cards import Card
from .theme import Glyphs, c
from . import theme

CARD_W = 5      # a fully visible card
CARD_H = 4
FAN_W = 3       # visible sliver of a card that another card overlaps


def put(win, y: int, x: int, text: str, attr: int = 0) -> None:
    """Write text, clipped to the window. Never raises on the bottom-right cell."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    text = text[: max(0, w - x)]
    if not text:
        return
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        # The very last cell of the window always throws; nothing else to do.
        pass


def panel(win, y: int, x: int, h: int, w: int, g: Glyphs, title: str = "",
          focused: bool = False, right: str = "") -> None:
    """A rounded box with an optional title chip set into the top border."""
    if h < 2 or w < 2:
        return
    frame = c(theme.FRAME_HI if focused else theme.FRAME)
    put(win, y, x, g.tl + g.h * (w - 2) + g.tr, frame)
    for row in range(1, h - 1):
        put(win, y + row, x, g.v, frame)
        put(win, y + row, x + w - 1, g.v, frame)
    put(win, y + h - 1, x, g.bl + g.h * (w - 2) + g.br, frame)

    if title:
        chip = f" {title} "
        if len(chip) < w - 4:
            put(win, y, x + 2, chip, c(theme.TITLE, bold=True))
    if right:
        chip = f" {right} "
        if len(chip) < w - 4:
            put(win, y, x + w - 2 - len(chip), chip, c(theme.LABEL))


SPREAD_STEP = CARD_W + 1    # cards side by side with a gap
FAN_STEP = FAN_W            # cards overlapping, only a rank sliver showing


def hand_width(count: int, step: int = SPREAD_STEP) -> int:
    """Columns a hand occupies at the given card pitch."""
    return step * (count - 1) + CARD_W if count > 0 else 0


def pick_step(counts: list[int], avail: int, indent: int, gap: int) -> int:
    """Widest pitch at which every hand still fits side by side.

    Falls back to the fanned pitch (and lets the caller clip) when even that
    is too wide, which only happens with four split hands running long.
    """
    for step in (SPREAD_STEP, FAN_STEP):
        total = sum(indent + hand_width(n, step) for n in counts)
        total += gap * (len(counts) - 1)
        if total <= avail:
            return step
    return FAN_STEP


def card_face(card: Card, g: Glyphs) -> tuple[list[str], int]:
    """Four rows of a face-up card, plus the colour pair to draw them in."""
    suit = g.suits[card.suit.letter]
    rank = card.rank
    pair = theme.CARD_RED if card.suit.red else theme.CARD
    rows = [
        g.card_tl + "───" .replace("─", g.h) + g.card_tr,
        g.v + f"{rank:<3}" + g.v,
        g.v + f"{suit:>3}" + g.v,
        g.card_bl + g.h * 3 + g.card_br,
    ]
    return rows, pair


def card_back(g: Glyphs) -> tuple[list[str], int]:
    rows = [
        g.card_tl + g.h * 3 + g.card_tr,
        g.v + g.back * 3 + g.v,
        g.v + g.back * 3 + g.v,
        g.card_bl + g.h * 3 + g.card_br,
    ]
    return rows, theme.CARD_BACK


def draw_card(win, y: int, x: int, card: Card | None, g: Glyphs,
              width: int = CARD_W) -> None:
    """Draw one card. `width` under CARD_W draws only its left sliver (fanned)."""
    rows, pair = card_face(card, g) if card else card_back(g)
    attr = c(pair)
    for i, row in enumerate(rows):
        put(win, y + i, x, row[:width], attr)


def draw_hand(win, y: int, x: int, cards: list[Card], g: Glyphs,
              hole_down: bool = False, reveal: int | None = None,
              step: int = SPREAD_STEP, avail: int = 999) -> int:
    """Render a hand left to right. Returns the width consumed.

    `reveal` caps how many cards are drawn, which is what animates the deal.
    `hole_down` hides the second card (the dealer's). If the hand is wider than
    `avail` it is clipped and marked with an ellipsis rather than spilling into
    whatever is drawn next to it.
    """
    shown = cards if reveal is None else cards[:reveal]
    if not shown:
        return 0

    clipped = False
    for i, card in enumerate(shown):
        left = i * step
        width = CARD_W if i == len(shown) - 1 else step
        if left + width > avail:
            clipped = True
            break
        draw_card(win, y, x + left, None if hole_down and i == 1 else card, g,
                  width=width)

    if clipped:
        for row in range(CARD_H):
            put(win, y + row, x + avail - 1, "\u2026" if g.unicode else ">",
                c(theme.DIM))
        return avail
    return hand_width(len(shown), step)


def badge(win, y: int, x: int, text: str, pair: int, bold: bool = True) -> int:
    """A small highlighted chip, e.g. a hand total or an outcome."""
    s = f" {text} "
    put(win, y, x, s, c(pair, bold=bold) | curses.A_REVERSE)
    return len(s)


def gauge(win, y: int, x: int, width: int, fraction: float, g: Glyphs,
          pair: int = theme.ACCENT) -> None:
    filled = max(0, min(width, round(width * fraction)))
    put(win, y, x, g.gauge_full * filled, c(pair))
    put(win, y, x + filled, g.gauge_empty * (width - filled), c(theme.DIM))


def keyhint(win, y: int, x: int, key: str, label: str, enabled: bool = True) -> int:
    """`[h]it` when the key is the word's first letter, else `[p] split`."""
    if label.lower().startswith(key.lower()):
        rest = label[len(key):]
    else:
        rest = " " + label
    if enabled:
        put(win, y, x, "[", c(theme.DIM))
        put(win, y, x + 1, key, c(theme.KEY, bold=True))
        put(win, y, x + 1 + len(key), "]", c(theme.DIM))
        put(win, y, x + 2 + len(key), rest, c(theme.TEXT))
    else:
        put(win, y, x, f"[{key}]{rest}", c(theme.DIM, dim=True))
    return len(key) + 2 + len(rest)


def center(win, y: int, x: int, width: int, text: str, attr: int = 0) -> None:
    put(win, y, x + max(0, (width - len(text)) // 2), text, attr)
