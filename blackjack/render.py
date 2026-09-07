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


# A card turning over: it lands face down, narrows to its edge, and opens out
# face up. Each frame is (visible width, face up yet).
FLIP_FRAMES = ((CARD_W, False), (3, False), (1, False), (3, True), (CARD_W, True))


def turn_frame(frame: int, reveal: bool = True) -> tuple[int, bool]:
    """How wide a card `frame` steps into its turn is, and whether it is face
    up yet. A card pitched face down never comes up, however far round it has
    got, so `reveal` false holds every frame of the turn face down."""
    width, face_up = FLIP_FRAMES[max(0, min(frame, len(FLIP_FRAMES) - 1))]
    return width, face_up and reveal


def draw_turning(win, y: int, x: int, card: Card, g: Glyphs, frame: int,
                 reveal: bool = True) -> None:
    """One frame of a card turning over, centred in the slot it will fill.

    Half way round a card is edge on, so the frames between the back and the
    face carry no rank -- just the shell, narrowing to a single line and
    opening out again in the colour of the suit underneath.

    `reveal` false is a card pitched face down -- the dealer's hole card as it
    is dealt. It turns in the dealer's hand exactly the same way, but comes to
    rest still face down, and no frame of it ever shows the card.
    """
    width, face_up = turn_frame(frame, reveal)
    if width >= CARD_W:
        draw_card(win, y, x, card if face_up else None, g)
        return

    pair = (theme.CARD_RED if card.suit.red else theme.CARD) if face_up \
        else theme.CARD_BACK
    attr = c(pair)
    ox = x + (CARD_W - width) // 2
    if width < 2:
        for row in range(CARD_H):
            put(win, y + row, ox, g.v, attr)
        return

    inner = width - 2
    fill = " " if face_up else g.back
    rows = [g.card_tl + g.h * inner + g.card_tr,
            g.v + fill * inner + g.v,
            g.v + fill * inner + g.v,
            g.card_bl + g.h * inner + g.card_br]
    for i, row in enumerate(rows):
        put(win, y + i, ox, row, attr)


def draw_hand(win, y: int, x: int, cards: list[Card], g: Glyphs,
              hole_down: bool = False, reveal: int | None = None,
              step: int = SPREAD_STEP, avail: int = 999,
              turn: tuple[int, int] | None = None) -> int:
    """Render a hand left to right. Returns the width consumed.

    `reveal` caps how many cards are drawn, which is what animates the deal.
    `hole_down` hides the second card (the dealer's). `turn` is `(index,
    frame)` for the one card partway through turning over -- the card being
    dealt right now, or the hole card coming up -- and its slot is held open
    even though the card has not landed. If the hand is wider than `avail` it
    is clipped and marked with an ellipsis rather than spilling into whatever
    is drawn next to it.
    """
    count = len(cards) if reveal is None else max(0, min(reveal, len(cards)))
    if turn is not None and turn[0] < len(cards):
        count = max(count, turn[0] + 1)
    if count == 0:
        return 0

    clipped = False
    for i in range(count):
        left = i * step
        width = CARD_W if i == count - 1 else step
        if left + width > avail:
            clipped = True
            break
        if turn is not None and i == turn[0]:
            draw_turning(win, y, x + left, cards[i], g, turn[1],
                         reveal=not (hole_down and i == 1))
        else:
            draw_card(win, y, x + left,
                      None if hole_down and i == 1 else cards[i], g, width=width)

    if clipped:
        for row in range(CARD_H):
            put(win, y + row, x + avail - 1, "\u2026" if g.unicode else ">",
                c(theme.DIM))
        return avail
    return hand_width(count, step)


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


def hint_rest(key: str, label: str) -> str:
    """The part of a key hint after the bracket: `[h]it`, else `[p] split`."""
    if label.lower().startswith(key.lower()):
        return label[len(key):]
    return " " + label


def hint_width(key: str, label: str) -> int:
    """Columns `keyhint` takes, so a bar can be measured before it is drawn."""
    return len(key) + 2 + len(hint_rest(key, label))


def keyhint(win, y: int, x: int, key: str, label: str, enabled: bool = True) -> int:
    """`[h]it` when the key is the word's first letter, else `[p] split`."""
    rest = hint_rest(key, label)
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
