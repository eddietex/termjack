"""The trainer: what the right move was, and the numbers behind it.

Every player decision is graded by working out what each legal move is worth,
rather than by looking it up in a table, so the advice comes with its own
arithmetic and the panel can quote real figures instead of received wisdom.

The model
---------
Expected values are in units of the hand's original bet, so they compare
directly: standing on a stiff might be worth -0.15, doubling +0.35. Three
simplifications, all standard for deriving basic strategy, and all worth well
under a tenth of a percent:

  * The shoe is taken to be a full one minus only the cards showing in this
    decision -- the player's hand and the dealer's upcard. The trainer is not
    a card counter; it teaches the chart, so the same hand always earns the
    same advice however deep into the shoe it comes up.
  * Cards are drawn with replacement from that composition, so a long draw
    does not deplete it.
  * A split is valued as twice one hand playing on with a double allowed,
    which ignores resplitting and so understates splits very slightly.

Nothing here imports curses or touches the screen; ``Coach`` takes a ``Game``
and hands back a ``Note`` for the app to draw.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .cards import Card, Suit
from .engine import Action, Game, hand_total

# Card indices: 0 is an ace, 1-8 are the 2 through 9, 9 is any ten.
ACE, TEN = 0, 9
BUST = 5                 # index of the bust bucket in a dealer distribution
CLOSE = 0.01             # an EV gap this small is a coin flip, not a blunder


def _index(card: Card) -> int:
    if card.is_ace:
        return ACE
    if card.is_ten:
        return TEN
    return card.value - 1


def _value(index: int) -> int:
    return 11 if index == ACE else index + 1


def _name(index: int) -> str:
    """How the upcard reads in a sentence: 'an ace', 'a 6', 'a ten'."""
    if index == ACE:
        return "an ace"
    if index == TEN:
        return "a ten"
    article = "an" if index + 1 == 8 else "a"
    return f"{article} {index + 1}"


def composition(decks: int, seen: list[Card]) -> list[int]:
    """Cards left in a full shoe once `seen` have been taken out of it."""
    counts = [4 * decks] * 9 + [16 * decks]
    for card in seen:
        counts[_index(card)] -= 1
    return counts


def probabilities(counts: list[int]) -> tuple[float, ...]:
    total = sum(counts)
    return tuple(n / total for n in counts) if total else (0.0,) * 10


def _draw(total: int, soft: bool, index: int) -> tuple[int | None, bool]:
    """Take one card onto a total. Returns (None, False) if it busts.

    At most one ace is ever worth 11, so `soft` is a single flag: a second ace
    comes in as a 1, and the eleven collapses to a one the moment the hand
    would otherwise go over.
    """
    value = _value(index)
    if index == ACE and (soft or total + 11 > 21):
        value = 1
    new, new_soft = total + value, soft or value == 11
    if new > 21 and new_soft:
        new, new_soft = new - 10, False
    return (new, new_soft) if new <= 21 else (None, False)


# -- the dealer ------------------------------------------------------------
def _dealer_from(total: int, soft: bool, p: tuple[float, ...],
                 memo: dict) -> tuple[float, ...]:
    """Distribution over final totals 17-21 and bust, drawing to S17."""
    if total >= 17:
        out = [0.0] * 6
        out[total - 17] = 1.0
        return tuple(out)
    key = (total, soft)
    if key in memo:
        return memo[key]
    acc = [0.0] * 6
    for i, pi in enumerate(p):
        if pi <= 0.0:
            continue
        new, new_soft = _draw(total, soft, i)
        if new is None:
            acc[BUST] += pi
            continue
        sub = _dealer_from(new, new_soft, p, memo)
        for k in range(6):
            acc[k] += pi * sub[k]
    memo[key] = tuple(acc)
    return memo[key]


def dealer_distribution(up: int, p: tuple[float, ...]) -> tuple[float, ...]:
    """Where the dealer's hand lands, given the upcard.

    The table peeks under a ten or an ace before the player acts, so by the
    time there is a decision to make a natural has been ruled out; the hole
    card is drawn from the shoe with that card excluded.
    """
    barred = TEN if up == ACE else (ACE if up == TEN else None)
    weight = 1.0 - (p[barred] if barred is not None else 0.0)
    start, start_soft = _draw(0, False, up)
    memo: dict = {}
    acc = [0.0] * 6
    for j, pj in enumerate(p):
        if pj <= 0.0 or j == barred:
            continue
        total, soft = _draw(start, start_soft, j)   # two cards never bust
        sub = _dealer_from(total, soft, p, memo)
        share = pj / weight if weight else 0.0
        for k in range(6):
            acc[k] += share * sub[k]
    return tuple(acc)


# -- what each move is worth ----------------------------------------------
def ev_stand(total: int, d: tuple[float, ...]) -> float:
    if total > 21:
        return -1.0
    win = d[BUST] + sum(d[k] for k in range(5) if 17 + k < total)
    push = d[total - 17] if total >= 17 else 0.0
    return win - (1.0 - win - push)


def ev_hit(total: int, soft: bool, p: tuple[float, ...],
           d: tuple[float, ...], memo: dict) -> float:
    """Worth of taking a card and then playing the rest of the hand well."""
    key = (total, soft)
    if key in memo:
        return memo[key]
    ev = 0.0
    for i, pi in enumerate(p):
        if pi <= 0.0:
            continue
        new, new_soft = _draw(total, soft, i)
        if new is None:
            ev -= pi
        else:
            ev += pi * max(ev_stand(new, d), ev_hit(new, new_soft, p, d, memo))
    memo[key] = ev
    return ev


def ev_double(total: int, soft: bool, p: tuple[float, ...],
              d: tuple[float, ...]) -> float:
    """One card, twice the money, no third option."""
    ev = 0.0
    for i, pi in enumerate(p):
        if pi <= 0.0:
            continue
        new, _ = _draw(total, soft, i)
        ev += pi * (-1.0 if new is None else ev_stand(new, d))
    return 2.0 * ev


def ev_split(pair: int, p: tuple[float, ...], d: tuple[float, ...]) -> float:
    """Two hands, each starting on one half of the pair.

    Resplitting is not modelled, so this reads a shade low on the pairs worth
    splitting most -- never enough to change which move comes out on top.
    """
    start, start_soft = _draw(0, False, pair)
    memo: dict = {}
    per_hand = 0.0
    for i, pi in enumerate(p):
        if pi <= 0.0:
            continue
        total, soft = _draw(start, start_soft, i)
        if pair == ACE:
            per_hand += pi * ev_stand(total, d)     # one card each, then stand
            continue
        best = max(ev_stand(total, d), ev_hit(total, soft, p, d, memo),
                   ev_double(total, soft, p, d))    # doubling after a split is on
        per_hand += pi * best
    return 2.0 * per_hand


def ev_insurance(p: tuple[float, ...]) -> float:
    """Per dollar staked. The side bet pays 2:1 and needs a ten one time in
    three; the shoe is nowhere near that generous."""
    return 3.0 * p[TEN] - 1.0


# -- reading a decision ----------------------------------------------------
@dataclass(frozen=True)
class Situation:
    """Everything the trainer worked out about one decision."""
    evs: dict[Action, float]
    total: int
    soft: bool
    pair: int | None          # card index of the pair, if the hand is one
    up: int                   # card index of the dealer's upcard
    dealer: tuple[float, ...]
    p: tuple[float, ...]

    @property
    def best(self) -> Action:
        return max(self.evs, key=self.evs.get)

    def runner_up(self) -> Action:
        rest = [a for a in self.evs if a is not self.best]
        return max(rest, key=self.evs.get)

    @property
    def dealer_busts(self) -> float:
        return self.dealer[BUST]

    @property
    def bust_odds(self) -> float:
        """Chance the very next card busts this hand."""
        return sum(pi for i, pi in enumerate(self.p)
                   if _draw(self.total, self.soft, i)[0] is None)

    @property
    def stand_wins(self) -> float:
        d, t = self.dealer, self.total
        return d[BUST] + sum(d[k] for k in range(5) if 17 + k < t)


def evaluate(decks: int, cards: list[Card], upcard: Card,
             actions: list[Action]) -> Situation:
    """Price every action in `actions` for this hand against this upcard.

    The one place expected values are worked out, so the coach's grade and the
    chart's column can never come from different arithmetic.
    """
    p = probabilities(composition(decks, cards + [upcard]))
    up = _index(upcard)
    dealer = dealer_distribution(up, p)
    total, soft = hand_total(cards)

    memo: dict = {}
    evs = {}
    for action in actions:
        if action is Action.STAND:
            evs[action] = ev_stand(total, dealer)
        elif action is Action.HIT:
            evs[action] = ev_hit(total, soft, p, dealer, memo)
        elif action is Action.DOUBLE:
            evs[action] = ev_double(total, soft, p, dealer)
        elif action is Action.SPLIT:
            evs[action] = ev_split(_index(cards[0]), p, dealer)

    is_pair = len(cards) == 2 and cards[0].value == cards[1].value
    pair = _index(cards[0]) if is_pair else None
    return Situation(evs, total, soft, pair, up, dealer, p)


def read(game: Game) -> Situation | None:
    """Work out what every legal move is worth on the hand in front of us."""
    actions = game.available()
    if not actions or game.round is None:
        return None
    return evaluate(game.shoe.decks, game.round.hand.cards,
                    game.round.dealer.cards[0], actions)


def _why(s: Situation) -> str:
    """One sentence for why the best move is the best move.

    Branching on the move the numbers actually picked, rather than on the shape
    of the hand, keeps the explanation from ever arguing with the verdict.
    """
    best, up, total = s.best, s.up, s.total
    who, Who = _name(up), _name(up).capitalize()
    pair_value = _value(s.pair) if s.pair is not None else 0

    if best is Action.SPLIT:
        if s.pair == ACE:
            return "Always split aces - two shots at 21 beat one soft 12."
        if pair_value == 8:
            return "Always split 8s - 16 is the worst hand you can hold."
        if up <= 5:            # index 5 is a 6: everything through here is weak
            return f"Two live hands while {who} is breaking {s.dealer_busts:.0%} of the time."
        return f"A pair of {pair_value}s does more as two hands than as one {total}."

    if best is Action.DOUBLE:
        if pair_value == 5:
            return "A pair of 5s is a 10 - double it, never split it."
        if s.soft:
            return f"A soft {total} cannot bust, so raise it against {who}."
        if total == 11:
            return f"Nothing doubles better: {s.p[TEN]:.0%} of the shoe turns 11 into 21."
        if total == 10:
            return f"A two-card 20 beats most of what {who} can build."
        return f"Push the bet while {who} is weak - {s.dealer_busts:.0%} bust."

    if best is Action.STAND:
        if s.pair is not None and pair_value == 10:
            return f"Never break a 20 - standing wins {s.stand_wins:.0%} of these."
        if s.pair is not None and pair_value == 9 and _value(up) == 7:
            return "18 stands against a 7 - the dealer's likeliest total is 17."
        if s.soft:
            return f"Soft {total} is good enough against {who}; drawing risks it."
        if total >= 19:
            return f"{total} already wins {s.stand_wins:.0%} against {who} - leave it alone."
        if total >= 17:
            return f"Hard {total} stands: one more card busts it {s.bust_odds:.0%} of the time."
        if _value(up) >= 7:
            # Only ever hard 16 against a ten, and only from three or more
            # cards: the low cards it is built from are the ones that would
            # have saved a hit.
            return f"{total} vs {who} is the closest call on the chart; stand by a hair."
        return f"Let {who} break - {s.dealer_busts:.0%} of the time they will."

    # Hitting.
    if s.soft:
        if total >= 17:
            return f"A soft {total} cannot bust, so the card is free against {who}."
        return f"You cannot bust drawing to a soft {total} - take it."
    if total >= 12:
        if total == 12 and _value(up) in (2, 3):
            return f"Only {s.bust_odds:.0%} of the shoe busts a 12, and {who} rarely breaks."
        return f"{Who} makes 17 or better {1 - s.dealer_busts:.0%} of the time; {total} must improve."
    if total >= 9 and Action.DOUBLE not in s.evs:
        return f"{total} wants a double, but hitting is the next best thing."
    return f"Nothing busts {total} - the card is free."


def _chip(s: Situation, chosen: Action) -> str:
    """The figures that settled it, for the panel's top border: the best move
    against whatever the player did instead, or against the next best when
    they got it right."""
    played = chosen is s.best
    other = s.runner_up() if played else chosen
    label = other.label if played else "yours"
    return (f"{s.best.label} {s.evs[s.best]:+.2f} / "
            f"{label} {s.evs[other]:+.2f}")


@dataclass(frozen=True)
class Note:
    """One graded decision, ready to draw."""
    verdict: str              # 'right' | 'close' | 'wrong'
    move: str                 # the move being recommended, e.g. 'Hit'
    body: str                 # why, in one sentence
    stats: str                # the numbers, for the panel border


class Coach:
    """Grades moves as they are played and keeps the running tally."""

    def __init__(self) -> None:
        self.note: Note | None = None
        self.calls = 0
        self.right = 0

    def clear(self) -> None:
        self.note = None

    def _book(self, note: Note) -> Note:
        self.calls += 1
        if note.verdict == "right":
            self.right += 1
        self.note = note
        return note

    def review(self, game: Game, action: Action) -> Note | None:
        """Grade a player action. Call this before the engine applies it."""
        s = read(game)
        if s is None or action not in s.evs:
            return None
        gap = s.evs[s.best] - s.evs[action]
        verdict = "right" if action is s.best else (
            "close" if gap < CLOSE else "wrong")
        return self._book(Note(verdict, s.best.label.capitalize(), _why(s),
                               _chip(s, action)))

    def review_insurance(self, game: Game, taken: bool) -> Note | None:
        """Grade the side bet. The answer is always no, but say why."""
        if game.round is None:
            return None
        seen = game.round.hands[0].cards + [game.round.dealer.cards[0]]
        p = probabilities(composition(game.shoe.decks, seen))
        ev = ev_insurance(p)
        wants = taken == (ev > 0)
        body = (f"Tens are {p[TEN]:.0%} of the shoe; the bet breaks even "
                f"at {1 / 3:.0%}.")
        return self._book(Note("right" if wants else "wrong",
                               "Insure" if ev > 0 else "Decline", body,
                               f"insurance {ev:+.2f}"))


# -- the chart -------------------------------------------------------------
# The column a player would look up for the dealer's upcard, derived from the
# same expected values the coach grades with rather than transcribed from a
# book -- so the chart and the grade can never disagree.
#
# Rows are built from a representative two-card hand for each total, then
# adjacent rows sharing a verdict are merged into a range: that is how a
# column is actually memorised ("stand on 13 through 16 against a 6"), and it
# keeps the whole strategy inside a panel small enough to sit beside the felt.

_SUIT = Suit.SPADES

# Two cards for each hard total: never an ace, and never a pair where there is
# a choice, so the hand reads hard and the split is not on the table. A hard 4
# can only be a pair of 2s and a hard 20 only two tens; neither is offered the
# split here, so both still price as the hard totals they are.
_HARD_MAKEUP = {
    4: ("2", "2"), 5: ("3", "2"), 6: ("4", "2"), 7: ("5", "2"),
    8: ("6", "2"), 9: ("7", "2"), 10: ("8", "2"), 11: ("9", "2"),
    12: ("10", "2"), 13: ("10", "3"), 14: ("10", "4"), 15: ("10", "5"),
    16: ("10", "6"), 17: ("10", "7"), 18: ("10", "8"), 19: ("10", "9"),
    20: ("K", "10"),
}

HARD_TOTALS = tuple(sorted(_HARD_MAKEUP))          # 4 through 20
SOFT_TOTALS = tuple(range(13, 21))                 # A,2 through A,9
PAIR_VALUES = (11, 2, 3, 4, 5, 6, 7, 8, 9, 10)     # aces first, as charts read

_TWO_CARD = [Action.HIT, Action.STAND, Action.DOUBLE]
_PAIR_PLAY = _TWO_CARD + [Action.SPLIT]


def _rank(index: int) -> str:
    return "A" if index == ACE else "10" if index == TEN else str(index + 1)


def _pair_rank(value: int) -> str:
    return "A" if value == 11 else str(value)


@dataclass(frozen=True)
class ChartRow:
    """One line of a column: the hands it covers, and the move for them."""
    label: str
    action: Action
    lo: int
    hi: int

    def covers(self, key: int) -> bool:
        return self.lo <= key <= self.hi


@dataclass(frozen=True)
class Chart:
    """The three blocks of a strategy column, for one dealer upcard."""
    up: int
    hard: tuple[ChartRow, ...]
    soft: tuple[ChartRow, ...]
    pairs: tuple[ChartRow, ...]

    @property
    def upcard(self) -> str:
        return _rank(self.up)

    def locate(self, total: int, soft: bool, pair: int | None) -> tuple[str, int] | None:
        """Which row the hand in front of the player sits on, if any.

        `pair` is the value of a splittable pair, and None when splitting is
        not on offer -- a pair that cannot be split is read off the hard or
        soft block, which is what the player has to play it as.
        """
        if pair is not None:
            block, key = self.pairs, pair
        elif soft:
            block, key = self.soft, total
        else:
            block, key = self.hard, total
        name = "pairs" if pair is not None else ("soft" if soft else "hard")
        for i, row in enumerate(block):
            if row.covers(key):
                return name, i
        return None


def _verdicts(decks: int, up: int, keys, makeup, actions) -> list[tuple[int, Action]]:
    upcard = Card(_rank(up), _SUIT)
    out = []
    for key in keys:
        cards = [Card(r, _SUIT) for r in makeup(key)]
        out.append((key, evaluate(decks, cards, upcard, list(actions)).best))
    return out


def _merge(verdicts: list[tuple[int, Action]], label) -> tuple[ChartRow, ...]:
    """Collapse consecutive keys that share a verdict into one row.

    Only genuinely adjacent keys merge, so the ace pairs -- listed first but
    numbered 11 -- never fold into the pair of 2s that follows them.
    """
    rows: list[ChartRow] = []
    for key, action in verdicts:
        if rows and rows[-1].action is action and key == rows[-1].hi + 1:
            prev = rows[-1]
            rows[-1] = ChartRow(label(prev.lo, key), action, prev.lo, key)
        else:
            rows.append(ChartRow(label(key, key), action, key, key))
    return tuple(rows)


def _span(one):
    """Turn a formatter for one key into one for a run of them."""
    return lambda lo, hi: one(lo) if lo == hi else f"{one(lo)}-{one(hi)}"


@lru_cache(maxsize=None)
def chart(decks: int, up: int) -> Chart:
    """The strategy column for one upcard. Cached: it costs a few milliseconds
    to derive and, since the trainer does not count, never changes."""
    hard = _merge(_verdicts(decks, up, HARD_TOTALS, lambda t: _HARD_MAKEUP[t],
                            _TWO_CARD), _span(str))
    soft = _merge(_verdicts(decks, up, SOFT_TOTALS,
                            lambda t: ("A", str(t - 11)), _TWO_CARD),
                  _span(lambda t: f"A{t - 11}"))
    pairs = _merge(_verdicts(decks, up, PAIR_VALUES,
                             lambda v: (_pair_rank(v), _pair_rank(v)),
                             _PAIR_PLAY),
                   _span(lambda v: f"{_pair_rank(v)}s"))
    return Chart(up, hard, soft, pairs)


def chart_for(game: Game) -> Chart | None:
    """The column for whatever the dealer is showing right now."""
    if game.round is None or not game.round.dealer.cards:
        return None
    return chart(game.shoe.decks, _index(game.round.dealer.cards[0]))
