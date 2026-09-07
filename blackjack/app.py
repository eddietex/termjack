"""The curses application: screen composition, animation, input."""

from __future__ import annotations

import curses
import time

from . import render, theme, trainer
from .cards import Card, Suit
from .engine import Action, Game, Outcome, Phase
from .render import center, gauge, keyhint, panel, put
from .theme import Glyphs, c

SIDEBAR_W = 18
HAND_INDENT = 2   # gutter that holds the active-hand marker
HAND_GAP = 3      # columns between split hands
BLOCK_H = 13      # dealer block + divider + player block, unpadded
TABLE_MIN_H = BLOCK_H + 2   # the block plus the panel's own borders
TRAINER_H = 3     # the trainer panel, same shape as the message panel
MIN_W, MIN_H = 76, 22
DEAL_TICK = 0.085          # seconds between cards during a deal
FRAME_MS = 30

def total_text(hand) -> str:
    """Badge text for a hand. The outcome chip already says BUST/BLACKJACK, so
    this stays numeric and just carries the colour."""
    if hand.is_blackjack:
        return "BJ"
    if hand.is_bust:
        return str(hand.total)
    return hand.label()


OUTCOME_STYLE = {
    Outcome.BLACKJACK: ("BLACKJACK", theme.CHIP),
    Outcome.WIN: ("WIN", theme.WIN),
    Outcome.PUSH: ("PUSH", theme.PUSH),
    Outcome.LOSE: ("LOSE", theme.LOSE),
    Outcome.BUST: ("BUST", theme.LOSE),
}


class App:
    def __init__(self, stdscr, game: Game, unicode_ok: bool = True,
                 trainer_on: bool = True):
        self.scr = stdscr
        self.game = game
        self.g = Glyphs(unicode_ok)
        self.running = True
        self.trainer_on = trainer_on
        self.coach = trainer.Coach()

        # Animation state: how many cards of each hand are on screen yet.
        self.shown_dealer = 0
        self.shown_hands: list[int] = []
        self.last_tick = 0.0
        self.opening = False
        self.message = game.message
        self._splash = (Card("A", Suit.SPADES), Card("K", Suit.HEARTS))

    # -- animation ---------------------------------------------------------
    def _reset_reveal(self, opening: bool) -> None:
        rnd = self.game.round
        self.opening = opening
        if opening:
            self.shown_dealer = 0
            self.shown_hands = [0]
        else:
            self.shown_hands = list(self.shown_hands) if self.shown_hands else [0]
        if rnd:
            while len(self.shown_hands) < len(rnd.hands):
                self.shown_hands.append(0)
        self.last_tick = time.monotonic()

    def _slots(self) -> list[tuple[int, int]]:
        """Reveal order as (hand index or -1 for dealer, card index)."""
        rnd = self.game.round
        if not rnd:
            return []
        if self.opening:
            return [(0, 0), (-1, 0), (0, 1), (-1, 1)]
        order: list[tuple[int, int]] = []
        for i, hand in enumerate(rnd.hands):
            order += [(i, j) for j in range(len(hand.cards))]
        order += [(-1, j) for j in range(len(rnd.dealer.cards))]
        return order

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

    @property
    def animating(self) -> bool:
        return any(self._shown(w) <= i for w, i in self._slots())

    def _advance_reveal(self) -> None:
        """Turn over the next card, if enough time has passed."""
        if not self.animating:
            if self.opening:
                self.opening = False
            return
        now = time.monotonic()
        if now - self.last_tick < DEAL_TICK:
            return
        self.last_tick = now
        for which, idx in self._slots():
            if self._shown(which) <= idx:
                self._show(which, idx + 1)
                return

    def _reveal_all(self) -> None:
        rnd = self.game.round
        if not rnd:
            return
        self.shown_dealer = len(rnd.dealer.cards)
        self.shown_hands = [len(h.cards) for h in rnd.hands]
        self.opening = False

    def _sync_message(self) -> None:
        if not self.animating:
            self.message = self.game.message

    # -- drawing -----------------------------------------------------------
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
        table_h = h - 5 - (TRAINER_H if coached else 0)
        table_w = w - SIDEBAR_W
        self._draw_table(0, 0, table_h, table_w)
        self._draw_sidebar(0, table_w, table_h, SIDEBAR_W)
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
        panel(self.scr, y, x, h, w, g, "TABLE", right=shoe)

        if rnd is None:
            self._draw_idle(y, x, h, w)
            return

        ix, iw = x + 2, w - 4
        # Dealer block is 5 rows, the divider 1, the player block 7. Pad between
        # them, up to a limit, then centre the whole thing in the panel.
        pad = max(0, min(2, (h - 2 - BLOCK_H) // 3))
        block = BLOCK_H + 3 * pad
        start = y + 1 + max(0, (h - 2 - block) // 2)
        dy = start + pad
        divider = dy + 5 + pad
        py = divider + 1 + pad

        self._draw_dealer(dy, ix, iw)
        put(self.scr, divider, x, self.g.tee_l + self.g.h * (w - 2) + self.g.tee_r,
            c(theme.FRAME))
        self._draw_hands(py, ix, iw)

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
        block = cards_w + 5 + max(len(r) for r in rules)
        bx = x + max(1, (w - block) // 2)
        top = mid - 5

        render.draw_card(self.scr, top, bx, self._splash[0], g)
        render.draw_card(self.scr, top, bx + render.SPREAD_STEP, self._splash[1], g)
        for i, line in enumerate(rules):
            put(self.scr, top + 1 + i, bx + cards_w + 5, line, c(theme.LABEL))

        center(self.scr, top + 5, x, w, "B L A C K J A C K", c(theme.TITLE, bold=True))
        center(self.scr, top + 8, x, w, f"Bet   ${game.bet}", c(theme.CHIP, bold=True))
        center(self.scr, top + 10, x, w, "press enter to deal", c(theme.ACCENT))

    def _draw_dealer(self, y: int, x: int, w: int) -> None:
        rnd, g = self.game.round, self.g
        put(self.scr, y, x, "DEALER", c(theme.LABEL, bold=True))

        shown = min(self.shown_dealer, len(rnd.dealer.cards))
        hidden = rnd.hole_down and shown >= 2
        if shown >= 2 and not rnd.hole_down:
            render.badge(self.scr, y, x + HAND_INDENT + 6, rnd.dealer.label(),
                         theme.LOSE if rnd.dealer.is_bust else theme.TEXT)
        elif shown >= 1:
            # Only the upcard is known; show its value quietly.
            put(self.scr, y, x + HAND_INDENT + 7,
                f"showing {rnd.dealer.cards[0].value}", c(theme.DIM))

        step = render.pick_step([len(rnd.dealer.cards)], w - HAND_INDENT,
                                indent=0, gap=0)
        render.draw_hand(self.scr, y + 1, x + HAND_INDENT, rnd.dealer.cards, g,
                         hole_down=hidden, reveal=shown, step=step,
                         avail=w - HAND_INDENT)

    def _draw_hands(self, y: int, x: int, w: int) -> None:
        rnd, g = self.game.round, self.g
        hands = rnd.hands
        n = len(hands)
        put(self.scr, y, x, "PLAYER" if n == 1 else f"PLAYER  ({n} hands)",
            c(theme.LABEL, bold=True))

        # One pitch for every hand, so the table reads evenly, then give each
        # hand exactly the width it needs and pack them left to right.
        counts = [max(1, self._shown(i)) for i in range(n)]
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

            pair = theme.LOSE if hand.is_bust else (
                theme.CHIP if hand.is_blackjack else theme.TEXT)
            badge_w = render.badge(self.scr, row, cx, total_text(hand), pair)
            if hand.doubled:
                put(self.scr, row, cx + badge_w + 1, "x2", c(theme.PUSH, bold=True))

            render.draw_hand(self.scr, row + 1, cx, hand.cards, g,
                             reveal=self._shown(i), step=step, avail=avail)

            foot = row + 5
            put(self.scr, foot, cx, f"${hand.bet}", c(theme.CHIP))
            if hand.outcome and not self.animating:
                label, opair = OUTCOME_STYLE[hand.outcome]
                render.badge(self.scr, foot, cx + len(f"${hand.bet}") + 2,
                             label, opair)

            hx = cx + widths[i] + HAND_GAP

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
    def _draw_sidebar(self, y: int, x: int, h: int, w: int) -> None:
        game, g = self.game, self.g
        panel(self.scr, y, x, h, w, g, "CHIPS")
        ix, iw = x + 2, w - 4
        row = y + 2

        self._stat(row, ix, iw, "Bank", f"${game.bankroll}", theme.CHIP, bold=True)
        self._stat(row + 1, ix, iw, "Bet", f"${game.bet}", theme.ACCENT, bold=True)

        # Chips owned = bankroll + anything still at risk on the table.
        at_risk = 0
        if game.round and game.phase in (Phase.INSURANCE, Phase.PLAYER, Phase.DEALER):
            at_risk = sum(h.bet for h in game.round.hands) + game.round.insurance
        net = game.bankroll + at_risk - game.starting_bankroll
        text = f"-${abs(net)}" if net < 0 else f"+${net}" if net > 0 else "$0"
        self._stat(row + 2, ix, iw, "Net", text,
                   theme.WIN if net > 0 else theme.LOSE if net < 0 else theme.LABEL)

        row += 4
        put(self.scr, row, ix, "Shoe", c(theme.LABEL))
        gauge(self.scr, row + 1, ix, iw, game.shoe.fraction_left, g)

        row += 2
        put(self.scr, row, ix, g.h * iw, c(theme.FRAME))
        row += 1
        self._stat(row, ix, iw, "Won", str(game.wins), theme.WIN)
        self._stat(row + 1, ix, iw, "Lost", str(game.losses), theme.LOSE)
        self._stat(row + 2, ix, iw, "Push", str(game.pushes), theme.PUSH)
        self._stat(row + 3, ix, iw, "BJ", str(game.blackjacks), theme.CHIP)

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
            res = game.round.insurance_result
            pair = theme.WIN if res == "won" else theme.LOSE if res == "lost" else theme.LABEL
            self._stat(extra, ix, iw, "Ins.", f"${game.round.insurance}", pair)

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
        focused = game.phase in (Phase.PLAYER, Phase.INSURANCE)
        panel(self.scr, y, x, h, w, self.g, titles.get(game.phase, ""), focused=focused)

        text = self.message
        pair = theme.TEXT
        if not self.animating and game.phase is Phase.SETTLED and game.round:
            low = text.lower()
            pair = theme.WIN if "you win" in low else (
                theme.LOSE if "you lose" in low else theme.PUSH)
        elif self.animating:
            text = "Dealing…" if self.opening else "…"
            pair = theme.DIM
        put(self.scr, y + 1, x + 2, text[: max(0, w - 4)], c(pair, bold=True))

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
        if not self.animating:
            hints.append(("t", "trainer", self.trainer_shown))

        quit_w = 7
        x = 1
        for key, label, on in hints:
            width = keyhint(self.scr, y, x, key, label, on)
            x += width + 3
            if x > w - quit_w - 4:
                break
        put(self.scr, y, w - quit_w - 1, "[q]uit", c(theme.DIM))

    # -- input -------------------------------------------------------------
    def handle(self, key: int) -> None:
        game = self.game

        if key in (ord("q"), ord("Q")):
            self.running = False
            return
        if key == curses.KEY_RESIZE:
            return
        if self.animating:
            self._reveal_all()
            self._sync_message()
            return
        if key in (ord("t"), ord("T")):
            self.trainer_on = not self.trainer_on
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
            if game.round:
                self._reset_reveal(opening=True)
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
                    self.shown_hands.insert(index + 1, 0)
                self._after_engine()
                return

    def _grade_insurance(self, taken: bool) -> None:
        if self.trainer_shown:
            self.coach.review_insurance(self.game, taken)

    def _after_engine(self) -> None:
        """Queue up any new cards the engine just put on the table."""
        if self.game.round:
            self._reset_reveal(opening=False)
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
