# termjack — progress log

A classic blackjack game with a TUI. Kept so a fresh session can pick up where
the last one stopped.

**Status: complete.** All planned work is done; the sections below are the
record of how it got here and what is worth knowing before changing it.

## Decisions (settled — do not relitigate)

- **Language/stack:** Python 3 + stdlib `curses`. No `go`/`cargo` on this box
  and no `pip`, so third-party TUI kits (textual, bubbletea, ratatui) are out.
  stdlib curses means zero install steps.
- **Target size:** 76x22 minimum; the real terminal here is 80x24. Wider and
  taller terminals get a centred, non-stretched felt.
- **Rules:** traditional Vegas. 6-deck shoe, dealer stands on all 17 (S17),
  blackjack pays 3:2, insurance on a dealer ace at 2:1, double on any first
  two cards including after a split, split to 4 hands, split aces get one card
  each and are never a blackjack. Reshuffle at the cut card (75% penetration).
- **Architecture:** the rules engine imports no curses and does no I/O, so it
  is unit-testable and can be driven by a simulator. curses lives only in
  `theme.py` / `render.py` / `app.py`. `trainer.py` follows the same rule.
- **Trainer:** advice is computed, not looked up. Every legal move is priced
  from the dealer's outcome distribution each time a decision comes up, and
  the explanation is generated from the same numbers, so the prose can never
  contradict the verdict. Deliberately *not* a card counter: it prices against
  a full shoe less the cards showing, which is how basic strategy is derived,
  so the same hand always earns the same advice.

## Layout

```
blackjack/cards.py     Card / Suit / Shoe                    (pure)
blackjack/engine.py    Hand, Round state machine, payouts    (pure)
blackjack/theme.py     colour pairs + glyphs, ASCII fallback
blackjack/render.py    panel/card/gauge primitives
blackjack/trainer.py   expected values, graded advice        (pure)
blackjack/app.py       screen composition, animation, input
blackjack/__main__.py  argument parsing, curses.wrapper
tools/verify_odds.py   basic-strategy simulator
tests/test_engine.py   48 rules tests
tests/test_trainer.py  33 trainer tests
termjack               launcher
```

## Things worth knowing

- **Card pitch.** `render.pick_step` chooses the widest pitch at which every
  hand still fits: cards spread out at 6 columns each, or overlap in a fan at
  3 when four split hands are on the table. A hand too wide even fanned is
  clipped with an ellipsis rather than spilling into its neighbour — the total
  badge always shows the true total, so nothing is misreported.
- **Animation.** The engine resolves a round synchronously; the app holds
  per-hand "cards revealed so far" counters and turns one card over every
  85 ms. Outcome badges and the result message are withheld until the reveal
  finishes, so the dealer's draw is not spoiled. Any key skips it.
- **Reveal order.** The opening deal interleaves player/dealer/player/dealer;
  after that it is hands left to right, then the dealer. On a split the app
  inserts a fresh counter at the index the hand was *inserted at*, captured
  before `act()`, because the engine may advance past it (split aces finish
  immediately).
- **Net figure** in the sidebar is bankroll plus whatever is still at risk on
  the table, against the buy-in, so it does not dip while a hand is live.
- **Integer chips.** Payouts floor, so a $25 blackjack pays $37, not $37.50.
  Deliberate: chips are whole dollars.
- **Trainer layout.** The panel wants 3 rows and the table will not go below
  `TABLE_MIN_H` (15), so it only appears at 23 rows or more. Below that
  `App.trainer_shown` is false and the coach does not grade at all — tallying
  moves the player cannot read would only skew `Calls`. The sidebar divider
  moved up one row to make room for `Calls` and `Ins.` inside the shorter
  panel; both are bounds-checked against the panel floor before drawing.
- **Grading happens before the engine moves.** `Coach.review` is called with
  the pre-action hand, in `_handle_player`, ahead of `game.act`. The note then
  stays up through the deal animation and the settlement — it grades the
  decision, not the outcome, so it spoils nothing — and is cleared on the
  next deal.
- **Trainer prose fits one line.** Every explanation is written to fit the
  panel interior at the 76-column minimum (72 chars including the head), and
  `NoteFitsThePanelTests` walks the whole chart to hold that.

## Verification

- `python3 -m unittest discover -s tests` — 84 tests, all passing.
- The trainer's expected values reproduce the basic-strategy chart in
  `tools/verify_odds.py` cell for cell: every hard total, every soft total,
  every pair. That is the check that matters — the advice is only worth
  giving if the arithmetic behind it lands where the book does. Its dealer
  bust rates also match published S17 tables to a tenth of a point.
- The one deliberate divergence is a three-or-more-card 16 against a ten,
  which stands. Real composition-dependent play, always inside the coin-flip
  threshold, and tested as such.
- Grading costs ~0.2 ms per decision, against a 30 ms frame budget.
- `python3 tools/verify_odds.py` — 500k hands of perfect basic strategy give a
  0.462% house edge and a 43.50 / 47.98 / 8.52 win-lose-push split, matching
  published figures for these rules. This is the sharpest check that the rules
  and payouts are right.
- A 200k-step random-play soak asserts the bankroll never goes negative, every
  settled hand gets an outcome, the hole card is always up at settlement, and
  the player is never left in a turn with no legal action.
- Screens checked at 76x22, 80x24 and 120x34: opening, deal, hit, bust,
  double, split to four hands, insurance offered/taken, dealer blackjack,
  natural, out of chips, and the too-small-terminal notice.

## Session log

### 2026-09-07
- Empty repo. Surveyed toolchains: no go, no rust, no pip. Python 3.14.7,
  node 26. Chose Python + curses.
- Wrote `cards.py`, `engine.py`, `theme.py`, `render.py`, `app.py`, entry point.
- Used tmux (`new-session -x/-y` plus `capture-pane -p`) to screenshot the TUI
  headlessly at fixed sizes — the thing that made visual iteration possible.
- Test suite written by a subagent; it found one real bug (a made 21 holding an
  untouched ace displayed as "11/21"), now fixed by treating 21 as never soft.
- Fixed along the way: multi-character key hints, the Net figure double-counting
  the live bet, dealer/player cards not aligning, duplicated BUST/BLACKJACK
  badges, the felt stretching on tall terminals, split hands drifting apart on
  wide ones, and the split reveal index.

### 2026-09-07 (later) — trainer
- Added `blackjack/trainer.py`: dealer outcome distribution (S17, conditioned
  on the peek having ruled out a natural), then stand/hit/double/split
  expected values, a `Situation` reading of the hand in front of the player,
  and a `Coach` that grades the move played against the best one.
- New TRAINER panel above the result panel, same shape. `t` toggles it,
  `--no-trainer` starts it hidden. `Calls` in the sidebar tracks the tally.
- Insurance gets graded too, which is where the trainer earns its keep: it
  says decline even on the hands where insurance would have paid.
- Checked in tmux at 76x22 (panel correctly sits out), 80x24 and 120x34, in
  Unicode and `--ascii`, across hit / stand / double / split / insurance.
- `verify_odds.py` re-run at 500k hands: 0.462% house edge, unchanged. The
  engine was not touched.
