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
  `theme.py` / `render.py` / `app.py`.

## Layout

```
blackjack/cards.py     Card / Suit / Shoe                    (pure)
blackjack/engine.py    Hand, Round state machine, payouts    (pure)
blackjack/theme.py     colour pairs + glyphs, ASCII fallback
blackjack/render.py    panel/card/gauge primitives
blackjack/app.py       screen composition, animation, input
blackjack/__main__.py  argument parsing, curses.wrapper
tools/verify_odds.py   basic-strategy simulator
tests/test_engine.py   48 unit tests
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

## Verification

- `python3 -m unittest discover -s tests` — 48 tests, all passing.
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
