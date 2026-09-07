"""The curses application: screen composition, animation, input."""

from __future__ import annotations

import curses
import time
from typing import NamedTuple

from . import render, theme, trainer
from .cards import Card, Suit
from .engine import Action, Game, Hand, Outcome, Phase
from .render import center, gauge, keyhint, panel, put
from .theme import Glyphs, c

SIDEBAR_W = 18
HAND_INDENT = 2   # gutter that holds the active-hand marker
HAND_GAP = 3      # columns between split hands
BLOCK_H = 13      # dealer block + divider + player block, unpadded
TABLE_MIN_H = BLOCK_H + 2   # the block plus the panel's own borders
TRAINER_H = 3     # the trainer panel, same shape as the message panel

# The chart. Two columns of rows -- hard and soft totals on the left, pairs on
# the right -- sized to the widest each will ever be, so the block does not
# resize as the dealer's upcard changes.
CHART_MOVE_W = 6                  # 'double', the longest move word
CHART_LABEL_W = 5                 # '12-16', 'A2-A7'
CHART_PAIR_W = 6                  # '9s-10s'
CHART_LEFT_W = 1 + CHART_LABEL_W + 1 + CHART_MOVE_W   # a marker gutter, then
CHART_RIGHT_W = 1 + CHART_PAIR_W + 1 + CHART_MOVE_W   # the label and the move
CHART_COL_GAP = 2
CHART_BODY_W = CHART_LEFT_W + CHART_COL_GAP + CHART_RIGHT_W
CHART_BODY_H = 10                 # HARD + 4, a blank, SOFT + 3; PAIRS + 7
CHART_DOCK_W = CHART_BODY_W + 3   # a divider and a column of air either side
CHART_DOCK_H = CHART_BODY_H + 1   # the heading, then the block
CHART_OVER_W = CHART_BODY_W + 4   # its own borders instead of the divider
CHART_OVER_H = CHART_BODY_H + 2
CARDS_MIN_W = 38    # felt the table will not give up to dock the chart beside

MIN_W, MIN_H = 76, 22
FRAME_MS = 30

# The rhythm of the deal, in seconds. Nothing lands the moment it is played:
# a card is pitched, pauses face down, then turns over, and the beats around
# the hole card are longer because that is where a table holds its breath.
PITCH = 0.16          # dead air before a card is pitched
FLIP_FRAME = 0.055    # one frame of a card turning over
FLIP_TIME = FLIP_FRAME * len(render.FLIP_FRAMES)
HOLE_BEAT = 0.55      # before the dealer turns the hole card up
DRAW_BEAT = 0.30      # before each card the dealer draws for itself
SETTLE_BEAT = 0.45    # after the last card, before the result is called


class Beat(NamedTuple):
    """One step of the deal: a card turning over, or a held pause.

    `delay` is the dead air in front of it; a card beat then runs for the
    length of a turn, and a `wait` beat is nothing but its delay.
    """
    kind: str      # 'card', 'hole' or 'wait'
    which: int     # hand index, or -1 for the dealer
    index: int     # which card of that hand
    delay: float

    @property
    def span(self) -> float:
        return self.delay + (0.0 if self.kind == "wait" else FLIP_TIME)


def visible(hand: Hand, shown: int) -> Hand:
    """The hand as far as it has been dealt, so its total counts up with the
    cards on the felt instead of being announced before they land."""
    if shown >= len(hand.cards):
        return hand
    return Hand(cards=hand.cards[:shown], bet=hand.bet, doubled=hand.doubled,
                from_split=hand.from_split)

def total_text(hand) -> str:
    """Badge text for a hand. The outcome chip already says BUST/BLACKJACK, so
    this stays numeric and just carries the colour."""
    if hand.is_blackjack:
        return "BJ"
    if hand.is_bust:
        return str(hand.total)
    return hand.label()


CHART_STYLE = {
    Action.HIT: theme.ACCENT,
    Action.STAND: theme.PUSH,
    Action.DOUBLE: theme.WIN,
    Action.SPLIT: theme.KEY,
}


OUTCOME_STYLE = {
    Outcome.BLACKJACK: ("BLACKJACK", theme.CHIP),
    Outcome.WIN: ("WIN", theme.WIN),
    Outcome.PUSH: ("PUSH", theme.PUSH),
    Outcome.LOSE: ("LOSE", theme.LOSE),
    Outcome.BUST: ("BUST", theme.LOSE),
}


class App:
    def __init__(self, stdscr, game: Game, unicode_ok: bool = True,
                 trainer_on: bool = True, chart_on: bool = False,
                 animate_on: bool = True):
        self.scr = stdscr
        self.game = game
        self.g = Glyphs(unicode_ok)
        self.running = True
        self.trainer_on = trainer_on
        self.chart_on = chart_on
        self.animate_on = animate_on
        self.coach = trainer.Coach()

        # Animation state: how many cards of each hand have landed, whether
        # the hole card has been turned up, and the beats still to play.
        self.shown_dealer = 0
        self.shown_hands: list[int] = []
        self.hole_up = False
        self.queue: list[Beat] = []
        self.beat: Beat | None = None
        self.beat_at = 0.0
        self.opening = False
        self.message = game.message
        self._splash = (Card("A", Suit.SPADES), Card("K", Suit.HEARTS))

    # -- animation ---------------------------------------------------------
    def _shown(self, which: int) -> int:
        if which < 0:
            return self.shown_dealer
        while len(self.shown_hands) <= which:
            self.shown_hands.append(0)
        return self.shown_hands[which]

    def _show(self, which: int, count: int) -> None:
        if which < 0:
            self.shown_dealer = count
        else:
            while len(self.shown_hands) <= which:
                self.shown_hands.append(0)
            self.shown_hands[which] = count

    def _stage(self, opening: bool) -> None:
        """Script whatever the engine has just put on the table.

        The engine resolves a whole action at once -- a split deals two cards,
        the dealer draws itself out to 17 in one go -- so the difference
        between what it holds and what is on the felt becomes the queue of
        beats that puts the rest down one card at a time.
        """
        rnd = self.game.round
        if rnd is None:
            return
        self.opening = opening
        if not self.animate_on:
            self._reveal_all()
            return
        if opening:
            self.shown_dealer = 0
            self.shown_hands = [0] * len(rnd.hands)
            self.hole_up = False

        beats: list[Beat] = []
        dealt = [min(self._shown(i), len(h.cards)) for i, h in enumerate(rnd.hands)]
        dealer_dealt = min(self.shown_dealer, len(rnd.dealer.cards))

        if opening:
            # Pitched one at a time round the table, the dealer's second card
            # face down: player, dealer, player, hole.
            for which, idx in ((0, 0), (-1, 0), (0, 1), (-1, 1)):
                beats.append(Beat("card", which, idx, PITCH))
            dealt[0], dealer_dealt = 2, 2

        for i, hand in enumerate(rnd.hands):
            for j in range(dealt[i], len(hand.cards)):
                beats.append(Beat("card", i, j, PITCH))
        if not rnd.hole_down and not self.hole_up:
            beats.append(Beat("hole", -1, 1, HOLE_BEAT))
        for j in range(max(dealer_dealt, 2), len(rnd.dealer.cards)):
            beats.append(Beat("card", -1, j, DRAW_BEAT))
        # Let the last card sit for a moment before the table calls the round.
        if beats and self.game.phase is Phase.SETTLED:
            beats.append(Beat("wait", 0, 0, SETTLE_BEAT))

        if not beats:
            return
        self.queue.extend(beats)
        if self.beat is None:
            self.beat, self.beat_at = self.queue.pop(0), time.monotonic()

    @property
    def animating(self) -> bool:
        return self.beat is not None

    def _land(self, beat: Beat) -> None:
        """Commit a finished beat: the card is down, or the hole card is up."""
        if beat.kind == "card":
            self._show(beat.which, beat.index + 1)
        elif beat.kind == "hole":
            self.hole_up = True

    def _advance_reveal(self) -> None:
        """Retire every beat whose time has run out, and start the next."""
        now = time.monotonic()
        while self.beat is not None and now - self.beat_at >= self.beat.span:
            self._land(self.beat)
            # Chain from when the beat was due rather than from now, so a slow
            # frame does not stretch the deal.
            self.beat_at += self.beat.span
            self.beat = self.queue.pop(0) if self.queue else None
        if self.beat is None:
            self.opening = False

    @property
    def hole_hidden(self) -> bool:
        """Whether the dealer's second card is face down on screen.

        It is pitched face down and stays down until the dealer takes it, so
        the turn it arrives on must not reach the face and neither must the
        pause before it comes up. The one moment it is neither down nor up is
        its own turn, which draws the card itself.
        """
        if self.hole_up:
            return False
        beat = self.beat
        return not (beat is not None and beat.kind == "hole"
                    and self._turn(-1) is not None)

    def _turn(self, which: int) -> tuple[int, int] | None:
        """The card of this hand mid-turn, as `(index, frame)`, or None."""
        beat = self.beat
        if beat is None or beat.kind == "wait" or beat.which != which:
            return None
        elapsed = time.monotonic() - self.beat_at - beat.delay
        if elapsed < 0:
            return None
        return beat.index, min(int(elapsed / FLIP_FRAME),
                               len(render.FLIP_FRAMES) - 1)

    def _staged(self, which: int) -> int:
        """Cards of a hand that need room on the felt: those already down,
        plus the one on its way in, so the layout does not shuffle sideways
        half way through a turn."""
        turn = self._turn(which)
        return max(self._shown(which), turn[0] + 1) if turn else self._shown(which)

    def _reveal_all(self) -> None:
        """Drop the rest of the deal on the table at once, for a player who
        would rather not wait for it."""
        rnd = self.game.round
        self.queue.clear()
        self.beat = None
        self.opening = False
        if not rnd:
            return
        self.shown_dealer = len(rnd.dealer.cards)
        self.shown_hands = [len(h.cards) for h in rnd.hands]
        self.hole_up = not rnd.hole_down

    def _sync_message(self) -> None:
        if not self.animating:
            self.message = self.game.message

    # -- drawing -----------------------------------------------------------
    def _table_size(self) -> tuple[int, int]:
        """Rows and columns the table pane gets, once the sidebar and the
        panels under it have taken theirs."""
        h, w = self.scr.getmaxyx()
        return h - 5 - (TRAINER_H if self.trainer_shown else 0), w - SIDEBAR_W

    def draw(self) -> None:
        scr = self.scr
        scr.erase()
        h, w = scr.getmaxyx()
        if w < MIN_W or h < MIN_H:
            self._draw_too_small(h, w)
            scr.noutrefresh()
            curses.doupdate()
            return

        coached = self.trainer_shown
        table_h, table_w = self._table_size()
        self._draw_table(0, 0, table_h, table_w)
        self._draw_sidebar(0, table_w, table_h, SIDEBAR_W)
        if self.chart_visible and not self.chart_docked:
            self._draw_chart_overlay(0, 0, table_h, table_w)
        if coached:
            self._draw_trainer(table_h, 0, TRAINER_H, w)
        self._draw_message(table_h + (TRAINER_H if coached else 0), 0, 3, w)
        self._draw_hints(h - 2, w)
        scr.noutrefresh()
        curses.doupdate()

    def _draw_too_small(self, h: int, w: int) -> None:
        msg = f"Need at least {MIN_W}x{MIN_H} — this terminal is {w}x{h}."
        center(self.scr, h // 2, 0, w, msg[: max(0, w - 1)], c(theme.LOSE))
        center(self.scr, h // 2 + 1, 0, w, "resize, or q to quit", c(theme.DIM))

    # -- table -------------------------------------------------------------
    def _draw_table(self, y: int, x: int, h: int, w: int) -> None:
        rnd, g = self.game.round, self.g
        shoe = f"shoe {self.game.shoe.fraction_left * 100:.0f}%"

        # A docked chart takes the right of the panel behind a divider; the
        # felt keeps the rest. The overlay case is drawn after everything else.
        docked = self.chart_docked
        dx = x + w - 1 - CHART_DOCK_W if docked else 0
        felt = w - (CHART_DOCK_W if docked else 0)

        # The shoe reading belongs over the felt, so it moves in with it.
        panel(self.scr, y, x, h, w, g, "TABLE", right="" if docked else shoe)
        if docked:
            put(self.scr, y, dx - len(shoe) - 3, f" {shoe} ", c(theme.LABEL))
            self._draw_dock(y, dx, h)

        if rnd is None:
            self._draw_idle(y, x, h, felt)
            return

        ix, iw = x + 2, felt - 4
        # Dealer block is 5 rows, the divider 1, the player block 7. Pad between
        # them, up to a limit, then centre the whole thing in the panel.
        pad = max(0, min(2, (h - 2 - BLOCK_H) // 3))
        block = BLOCK_H + 3 * pad
        start = y + 1 + max(0, (h - 2 - block) // 2)
        dy = start + pad
        divider = dy + 5 + pad
        py = divider + 1 + pad

        self._draw_dealer(dy, ix, iw)
        # The rule between dealer and player stops at the chart's divider.
        edge, cap = (dx, g.joint) if docked else (x + w - 1, g.tee_r)
        put(self.scr, divider, x, g.tee_l + g.h * (edge - x - 1) + cap,
            c(theme.FRAME))
        self._draw_hands(py, ix, iw)

    def _draw_dock(self, y: int, x: int, h: int) -> None:
        """The chart's divider, and the block of rows to the right of it."""
        g = self.g
        put(self.scr, y, x, g.tee_d, c(theme.FRAME))
        for row in range(1, h - 1):
            put(self.scr, y + row, x, g.v, c(theme.FRAME))
        put(self.scr, y + h - 1, x, g.tee_u, c(theme.FRAME))

        top = y + 1 + max(0, (h - 2 - CHART_DOCK_H) // 2)
        bx = x + 2
        ch = self._chart()
        put(self.scr, top, bx, "CHART", c(theme.TITLE, bold=True))
        if ch is not None:
            right = f"vs {ch.upcard}"
            put(self.scr, top, bx + CHART_BODY_W - len(right), right, c(theme.LABEL))
        self._draw_chart_body(top + 1, bx, ch, min(CHART_BODY_H, h - 3))

    def _draw_idle(self, y: int, x: int, h: int, w: int) -> None:
        game, g = self.game, self.g
        mid = y + h // 2

        if game.is_broke:
            center(self.scr, mid - 2, x, w, "OUT OF CHIPS", c(theme.LOSE, bold=True))
            center(self.scr, mid, x, w,
                   f"You sat down with ${game.starting_bankroll}.", c(theme.LABEL))
            center(self.scr, mid + 2, x, w, "Press r to buy back in, q to walk away.",
                   c(theme.LABEL))
            return

        # An ace and a king, fanned, as the table's calling card.
        rules = ["6 decks  ·  dealer stands on all 17",
                 "blackjack pays 3:2  ·  insurance 2:1"]
        cards_w = render.hand_width(2)
        rules_w = max(len(r) for r in rules)
        # The rules sit beside the cards where the felt is wide enough for
        # both -- a docked chart often means it is not -- and drop under the
        # title where it is not, rather than being cut off mid-sentence.
        beside = cards_w + 5 + rules_w <= w - 2
        block = cards_w + 5 + rules_w if beside else cards_w
        bx = x + max(1, (w - block) // 2)
        top = mid - 5

        render.draw_card(self.scr, top, bx, self._splash[0], g)
        render.draw_card(self.scr, top, bx + render.SPREAD_STEP, self._splash[1], g)
        if beside:
            for i, line in enumerate(rules):
                put(self.scr, top + 1 + i, bx + cards_w + 5, line, c(theme.LABEL))

        center(self.scr, top + 5, x, w, "B L A C K J A C K", c(theme.TITLE, bold=True))
        if not beside:
            for i, line in enumerate(rules):
                center(self.scr, top + 6 + i, x, w, line[: w - 2], c(theme.LABEL))
        center(self.scr, top + 8, x, w, f"Bet   ${game.bet}", c(theme.CHIP, bold=True))
        center(self.scr, top + 10, x, w, "press enter to deal", c(theme.ACCENT))

    def _draw_dealer(self, y: int, x: int, w: int) -> None:
        rnd, g = self.game.round, self.g
        put(self.scr, y, x, "DEALER", c(theme.LABEL, bold=True))

        shown = min(self.shown_dealer, len(rnd.dealer.cards))
        turn = self._turn(-1)
        hidden = self.hole_hidden
        if self.hole_up and shown >= 2:
            seen = visible(rnd.dealer, shown)
            render.badge(self.scr, y, x + HAND_INDENT + 6, seen.label(),
                         theme.LOSE if seen.is_bust else theme.TEXT)
        elif shown >= 1:
            # Only the upcard is known; show its value quietly.
            put(self.scr, y, x + HAND_INDENT + 7,
                f"showing {rnd.dealer.cards[0].value}", c(theme.DIM))

        step = render.pick_step([len(rnd.dealer.cards)], w - HAND_INDENT,
                                indent=0, gap=0)
        render.draw_hand(self.scr, y + 1, x + HAND_INDENT, rnd.dealer.cards, g,
                         hole_down=hidden, reveal=shown, step=step,
                         avail=w - HAND_INDENT, turn=turn)

    def _draw_hands(self, y: int, x: int, w: int) -> None:
        rnd, g = self.game.round, self.g
        hands = rnd.hands
        n = len(hands)
        put(self.scr, y, x, "PLAYER" if n == 1 else f"PLAYER  ({n} hands)",
            c(theme.LABEL, bold=True))

        # One pitch for every hand, so the table reads evenly, then give each
        # hand exactly the width it needs and pack them left to right.
        counts = [max(1, self._staged(i)) for i in range(n)]
        step = render.pick_step(counts, w, HAND_INDENT, HAND_GAP)
        widths = [render.hand_width(c, step) for c in counts]
        slack = w - sum(HAND_INDENT + wd for wd in widths) - HAND_GAP * (n - 1)

        hx = x
        for i, hand in enumerate(hands):
            cx = hx + HAND_INDENT
            avail = widths[i] + (max(0, slack) if n == 1 else 0)
            active = (self.game.phase is Phase.PLAYER and i == rnd.active
                      and not self.animating)
            row = y + 1

            if active:
                put(self.scr, row, hx, g.marker, c(theme.ACCENT, bold=True))
                put(self.scr, row + 1, hx, g.marker, c(theme.ACCENT, bold=True))

            # No total until there is a card to total; an empty seat reads
            # as empty rather than as a hand worth nothing.
            seen = visible(hand, self._shown(i))
            if seen.cards:
                pair = theme.LOSE if seen.is_bust else (
                    theme.CHIP if seen.is_blackjack else theme.TEXT)
                badge_w = render.badge(self.scr, row, cx, total_text(seen), pair)
                if hand.doubled:
                    put(self.scr, row, cx + badge_w + 1, "x2",
                        c(theme.PUSH, bold=True))

            render.draw_hand(self.scr, row + 1, cx, hand.cards, g,
                             reveal=self._shown(i), step=step, avail=avail,
                             turn=self._turn(i))

            foot = row + 5
            put(self.scr, foot, cx, f"${hand.bet}", c(theme.CHIP))
            if hand.outcome and not self.animating:
                label, opair = OUTCOME_STYLE[hand.outcome]
                render.badge(self.scr, foot, cx + len(f"${hand.bet}") + 2,
                             label, opair)

            hx = cx + widths[i] + HAND_GAP

    # -- chart -------------------------------------------------------------
    @property
    def chart_shown(self) -> bool:
        h, w = self.scr.getmaxyx()
        return self.chart_on and w >= MIN_W and h >= MIN_H

    @property
    def chart_docked(self) -> bool:
        """Whether the chart fits beside the felt rather than over it.

        Docking is only worth it while the table keeps enough width to lay the
        cards out; below that the chart takes the pane instead, where `c` is
        the way back to the felt."""
        if not self.chart_shown:
            return False
        table_h, table_w = self._table_size()
        return (table_w - 4 - CHART_DOCK_W >= CARDS_MIN_W
                and table_h - 2 >= CHART_DOCK_H)

    @property
    def chart_visible(self) -> bool:
        """Whether the chart is actually on screen. Docked it always is, and
        says so while it waits; over the felt it holds off until there is a
        column to show, rather than smothering the bet with a placeholder."""
        return self.chart_shown and (self.chart_docked or self._chart() is not None)

    def _chart(self) -> trainer.Chart | None:
        """The column for the dealer's upcard, once it is face up."""
        if self.game.round is None or self.shown_dealer < 1:
            return None
        return trainer.chart_for(self.game)

    def _chart_here(self, ch: trainer.Chart) -> trainer.ChartRow | None:
        """The row the hand in front of the player sits on, so it can be lit
        up. Only while there is a decision to make -- the rest of the time the
        chart is being read, not followed."""
        game = self.game
        actions = game.available()
        if not actions or self.animating:
            return None
        hand = game.round.hand
        pair = hand.cards[0].value if Action.SPLIT in actions else None
        found = ch.locate(hand.total, hand.soft, pair)
        if found is None:
            return None
        block, i = found
        return getattr(ch, block)[i]

    def _draw_chart_overlay(self, y: int, x: int, h: int, w: int) -> None:
        """The chart laid over the felt, hugging the right of the table pane so
        the dealer and the first hand stay readable behind it."""
        ch = self._chart()
        oy = y + max(0, (h - CHART_OVER_H) // 2)
        ox = x + max(0, w - 1 - CHART_OVER_W)
        oh, ow = min(CHART_OVER_H, h), min(CHART_OVER_W, w)
        panel(self.scr, oy, ox, oh, ow, self.g, "CHART",
              right=f"vs {ch.upcard}" if ch else "")
        for row in range(1, oh - 1):     # blank the felt showing through
            put(self.scr, oy + row, ox + 1, " " * (ow - 2))
        self._draw_chart_body(oy + 1, ox + 2, ch, oh - 2)

    def _draw_chart_body(self, y: int, x: int, ch: trainer.Chart | None,
                         height: int) -> None:
        if ch is None:
            put(self.scr, y, x, "Deal a hand to see a column.", c(theme.DIM))
            return
        here = self._chart_here(ch)
        left = ([("head", "HARD")] + [("row", r) for r in ch.hard]
                + [("gap", None), ("head", "SOFT")]
                + [("row", r) for r in ch.soft])
        right = [("head", "PAIRS")] + [("row", r) for r in ch.pairs]
        self._draw_chart_column(y, x, left[:height], CHART_LABEL_W, here)
        self._draw_chart_column(y, x + CHART_LEFT_W + CHART_COL_GAP,
                                right[:height], CHART_PAIR_W, here)

    def _draw_chart_column(self, y: int, x: int, items, label_w: int,
                           here) -> None:
        for i, (kind, item) in enumerate(items):
            if kind == "head":
                put(self.scr, y + i, x, item, c(theme.LABEL, bold=True))
            elif kind == "row":
                active = item is here
                if active:
                    put(self.scr, y + i, x, self.g.marker, c(theme.ACCENT, bold=True))
                put(self.scr, y + i, x + 1, item.label,
                    c(theme.TEXT if active else theme.LABEL, bold=active))
                put(self.scr, y + i, x + 2 + label_w, item.action.label,
                    c(CHART_STYLE[item.action], bold=True))

    # -- trainer -----------------------------------------------------------
    @property
    def trainer_shown(self) -> bool:
        """The trainer needs its own three rows, and the table will not give
        them up below `TABLE_MIN_H`. Where they are not there, it sits out --
        grading moves the player cannot read would only skew the tally."""
        h, w = self.scr.getmaxyx()
        if not self.trainer_on or w < MIN_W or h < MIN_H:
            return False
        return h - 5 - TRAINER_H >= TABLE_MIN_H

    def _draw_trainer(self, y: int, x: int, h: int, w: int) -> None:
        note, g = self.coach.note, self.g
        panel(self.scr, y, x, h, w, g, "TRAINER", right=note.stats if note else "")
        if note is None:
            put(self.scr, y + 1, x + 2,
                "Every move gets graded here, with the odds behind it."[: w - 4],
                c(theme.DIM))
            return

        # The head always names the move to make; the mark says whether it was
        # the one played.
        glyph, pair = {"right": (g.tick, theme.WIN),
                       "close": (g.near, theme.PUSH),
                       "wrong": (g.cross, theme.LOSE)}[note.verdict]
        head = f"{glyph} {note.move}. "
        put(self.scr, y + 1, x + 2, head, c(pair, bold=True))
        put(self.scr, y + 1, x + 2 + len(head),
            note.body[: max(0, w - 4 - len(head))], c(theme.TEXT))

    # -- sidebar -----------------------------------------------------------
    @property
    def uncalled(self):
        """The round whose result the engine has booked but the table has not
        called yet. The engine settles the moment the last card is drawn; the
        sidebar has to rewind that, or it gives the hand away while the cards
        are still coming down."""
        if self.animating and self.game.phase is Phase.SETTLED:
            return self.game.round
        return None

    def _draw_sidebar(self, y: int, x: int, h: int, w: int) -> None:
        game, g = self.game, self.g
        held = self.uncalled
        panel(self.scr, y, x, h, w, g, "CHIPS")
        ix, iw = x + 2, w - 4
        row = y + 2

        # Chips owned = bankroll + anything still at risk on the table.
        bank, at_risk = game.bankroll, 0
        if game.round and game.phase in (Phase.INSURANCE, Phase.PLAYER, Phase.DEALER):
            at_risk = sum(h.bet for h in game.round.hands) + game.round.insurance
        elif held:
            # Put the payouts back in the middle: nothing is pushed across
            # until the hand has been called.
            bank -= sum(hand.payout for hand in held.hands)
            if held.insurance_result == "won":
                bank -= held.insurance * 3
            at_risk = sum(hand.bet for hand in held.hands) + held.insurance

        self._stat(row, ix, iw, "Bank", f"${bank}", theme.CHIP, bold=True)
        self._stat(row + 1, ix, iw, "Bet", f"${game.bet}", theme.ACCENT, bold=True)

        net = bank + at_risk - game.starting_bankroll
        text = f"-${abs(net)}" if net < 0 else f"+${net}" if net > 0 else "$0"
        self._stat(row + 2, ix, iw, "Net", text,
                   theme.WIN if net > 0 else theme.LOSE if net < 0 else theme.LABEL)

        row += 4
        put(self.scr, row, ix, "Shoe", c(theme.LABEL))
        gauge(self.scr, row + 1, ix, iw, game.shoe.fraction_left, g)

        row += 2
        put(self.scr, row, ix, g.h * iw, c(theme.FRAME))
        row += 1
        won, lost, push, bj = self._uncounted(held)
        self._stat(row, ix, iw, "Won", str(game.wins - won), theme.WIN)
        self._stat(row + 1, ix, iw, "Lost", str(game.losses - lost), theme.LOSE)
        self._stat(row + 2, ix, iw, "Push", str(game.pushes - push), theme.PUSH)
        self._stat(row + 3, ix, iw, "BJ", str(game.blackjacks - bj), theme.CHIP)

        # Extras only get drawn while there is still panel left to draw them in.
        extra, floor = row + 4, y + h - 1
        if self.trainer_on and self.coach.calls and extra < floor:
            self._stat(extra, ix, iw, "Calls",
                       f"{self.coach.right}/{self.coach.calls}", theme.ACCENT)
            extra += 1
            if extra < floor:
                pct = round(100 * self.coach.right / self.coach.calls)
                self._stat(extra, ix, iw, "Calls %", f"{pct}%", theme.ACCENT)
                extra += 1
        if game.round and game.round.insurance and extra < floor:
            # The side bet is settled off the hole card, so it keeps its own
            # counsel until the hole card is up.
            res = game.round.insurance_result if self.hole_up else None
            pair = theme.WIN if res == "won" else theme.LOSE if res == "lost" else theme.LABEL
            self._stat(extra, ix, iw, "Ins.", f"${game.round.insurance}", pair)

    def _uncounted(self, held) -> tuple[int, int, int, int]:
        """Wins, losses, pushes and blackjacks the engine has already tallied
        for a round the table has not called yet."""
        if held is None:
            return 0, 0, 0, 0
        outs = [hand.outcome for hand in held.hands]
        bj = outs.count(Outcome.BLACKJACK)
        return (bj + outs.count(Outcome.WIN),
                outs.count(Outcome.LOSE) + outs.count(Outcome.BUST),
                outs.count(Outcome.PUSH), bj)

    def _stat(self, y: int, x: int, w: int, label: str, value: str,
              pair: int = theme.TEXT, bold: bool = False) -> None:
        put(self.scr, y, x, label, c(theme.LABEL))
        put(self.scr, y, x + w - len(value), value, c(pair, bold=bold))

    # -- message + hints ---------------------------------------------------
    def _draw_message(self, y: int, x: int, h: int, w: int) -> None:
        game = self.game
        titles = {
            Phase.BETTING: "BET",
            Phase.INSURANCE: "INSURANCE",
            Phase.PLAYER: "YOUR TURN",
            Phase.DEALER: "DEALER",
            Phase.SETTLED: "RESULT",
        }
        # While cards are still landing the round has not reached the player,
        # whatever phase the engine has already moved on to: the title says
        # what the table is doing, and the focus ring waits its turn.
        if self.animating:
            title = "DEALING" if self.opening else (
                "DEALER" if game.phase in (Phase.DEALER, Phase.SETTLED)
                else titles.get(game.phase, ""))
        else:
            title = titles.get(game.phase, "")
        focused = (not self.animating
                   and game.phase in (Phase.PLAYER, Phase.INSURANCE))
        panel(self.scr, y, x, h, w, self.g, title, focused=focused)

        text = self.message
        pair = theme.TEXT
        if not self.animating and game.phase is Phase.SETTLED and game.round:
            low = text.lower()
            pair = theme.WIN if "you win" in low else (
                theme.LOSE if "you lose" in low else theme.PUSH)
        elif self.animating:
            text = self._dealing_text()
            pair = theme.DIM
        put(self.scr, y + 1, x + 2, text[: max(0, w - 4)], c(pair, bold=True))

    def _dealing_text(self) -> str:
        """What the table is doing, while it is doing it."""
        beat = self.beat
        if beat is None:
            return "…"
        if beat.kind == "hole":
            return "Dealer turns the hole card…"
        if self.opening:
            return "Dealing…"
        if beat.which < 0:
            return "Dealer draws…"
        return "…"

    def _draw_hints(self, y: int, w: int) -> None:
        game, g = self.game, self.g
        arrows = "\u2190\u2192" if g.unicode else "<>"
        hints: list[tuple[str, str, bool]] = []

        if self.animating:
            hints = [("any key", "skip", True)]
        elif game.phase is Phase.BETTING:
            if game.is_broke:
                hints = [("r", "rebuy", True)]
            else:
                hints = [(arrows, "bet", True), ("1/2/3", "chip", True),
                         ("enter", "deal", True)]
        elif game.phase is Phase.INSURANCE:
            hints = [("y", "insure", game.can_insure()), ("n", "decline", True)]
        elif game.phase is Phase.PLAYER:
            avail = game.available()
            hints = [(a.key, a.label, True) for a in
                     (Action.HIT, Action.STAND, Action.DOUBLE, Action.SPLIT)
                     if a in avail]
        elif game.phase is Phase.SETTLED:
            hints = [("enter", "next hand", True)]
        # The animation hint leads the toggles because it is the only one
        # whose state the table does not already show: a panel is visibly
        # there or not, whereas an idle felt says nothing about the deal.
        hints.append(("a", "anim", self.animate_on))
        if not self.animating:
            hints.append(("c", "chart", self.chart_visible))
            hints.append(("t", "trainer", self.trainer_shown))

        # Measure before drawing, so the last hint that fits is the last one
        # drawn rather than the first one to overrun [q]uit.
        quit_w = 7
        x = 1
        for key, label, on in hints:
            width = render.hint_width(key, label)
            if x + width > w - quit_w - 2:
                break
            keyhint(self.scr, y, x, key, label, on)
            x += width + 3
        put(self.scr, y, w - quit_w - 1, "[q]uit", c(theme.DIM))

    # -- input -------------------------------------------------------------
    def handle(self, key: int) -> None:
        game = self.game

        if key in (ord("q"), ord("Q")):
            self.running = False
            return
        if key == curses.KEY_RESIZE:
            return
        # Ahead of the skip below, so that reaching for it part way through a
        # deal both turns the animation off and drops what is still coming.
        if key in (ord("a"), ord("A")):
            self.animate_on = not self.animate_on
            if not self.animate_on:
                self._reveal_all()
            self._sync_message()
            return
        if self.animating:
            self._reveal_all()
            self._sync_message()
            return
        if key in (ord("t"), ord("T")):
            self.trainer_on = not self.trainer_on
            return
        if key in (ord("c"), ord("C")):
            self.chart_on = not self.chart_on
            return

        if game.phase is Phase.BETTING:
            self._handle_betting(key)
        elif game.phase is Phase.INSURANCE:
            if key in (ord("y"), ord("Y")) and game.can_insure():
                self._grade_insurance(True)
                game.take_insurance(True)
                self._after_engine()
            elif key in (ord("n"), ord("N"), 27):
                self._grade_insurance(False)
                game.take_insurance(False)
                self._after_engine()
        elif game.phase is Phase.PLAYER:
            self._handle_player(key)
        elif game.phase is Phase.SETTLED:
            if key in (curses.KEY_ENTER, 10, 13, ord(" ")):
                game.next_round()
                self.message = game.message

    def _handle_betting(self, key: int) -> None:
        game = self.game
        if key in (ord("r"), ord("R")) and game.is_broke:
            game.bankroll += game.starting_bankroll
            game.starting_bankroll += game.starting_bankroll
            game.clamp_bet()
            game.message = "Bought back in. Place your bet."
            self.message = game.message
            return
        if game.is_broke:
            return

        step = {curses.KEY_LEFT: -5, ord("-"): -5, ord("h"): -5,
                curses.KEY_RIGHT: 5, ord("+"): 5, ord("="): 5, ord("l"): 5,
                curses.KEY_DOWN: -25, ord("j"): -25,
                curses.KEY_UP: 25, ord("k"): 25,
                ord("1"): 5, ord("2"): 25, ord("3"): 100}.get(key)
        if step is not None:
            game.adjust_bet(step)
            return
        if key in (curses.KEY_ENTER, 10, 13, ord(" ")):
            self.coach.clear()
            game.deal()
            self._stage(opening=True)
            self.message = game.message

    def _handle_player(self, key: int) -> None:
        game = self.game
        for action in game.available():
            if key == ord(action.key):
                if self.trainer_shown:
                    self.coach.review(game, action)
                # Note where the split would land before acting: the engine may
                # advance past the new hand (split aces finish immediately), so
                # `active` afterwards is not where it was inserted.
                index = game.round.active
                before = len(game.round.hands)
                game.act(action)
                if len(game.round.hands) != before:
                    # One card of the pair has moved across, so the hand it
                    # left is back down to a single card and both halves are
                    # dealt to again.
                    self._show(index, 1)
                    self.shown_hands.insert(index + 1, 0)
                self._after_engine()
                return

    def _grade_insurance(self, taken: bool) -> None:
        if self.trainer_shown:
            self.coach.review_insurance(self.game, taken)

    def _after_engine(self) -> None:
        """Queue up any new cards the engine just put on the table."""
        self._stage(opening=False)
        self._sync_message()

    # -- loop --------------------------------------------------------------
    def run(self) -> None:
        self.scr.timeout(FRAME_MS)
        while self.running:
            self._advance_reveal()
            self._sync_message()
            self.draw()
            try:
                key = self.scr.getch()
            except KeyboardInterrupt:
                break
            if key != -1:
                self.handle(key)
