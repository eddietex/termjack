# termjack

A classic blackjack table in the terminal.

```
╭─ TABLE ───────────────────────────────────────── shoe 98% ─╮╭─ CHIPS ────────╮
│ DEALER   showing 6                                         ││                │
│   ╭───╮ ╭───╮                                              ││ Bank      $450 │
│   │6  │ │▓▓▓│                                              ││ Bet        $25 │
│   │  ♠│ │▓▓▓│                                              ││ Net         $0 │
│   ╰───╯ ╰───╯                                              ││                │
├────────────────────────────────────────────────────────────┤│ Shoe           │
│ PLAYER  (2 hands)                                          ││ ██████████████ │
│ ▸  18              14                                      ││ ────────────── │
│ ▸ ╭───╮ ╭───╮     ╭───╮ ╭───╮                              ││ Won          0 │
│   │8  │ │J  │     │8  │ │6  │                              ││ Lost         0 │
│   │  ♦│ │  ♣│     │  ♣│ │  ♥│                              ││ Push         0 │
│   ╰───╯ ╰───╯     ╰───╯ ╰───╯                              ││ BJ           0 │
│   $25             $25                                      ││ Calls      1/1 │
│                                                            ││                │
╰────────────────────────────────────────────────────────────╯╰────────────────╯
╭─ TRAINER ──────────────────────────────────────── split +0.33 / stand -0.16 ─╮
│ ✓ Split. Always split 8s - 16 is the worst hand you can hold.                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ YOUR TURN ──────────────────────────────────────────────────────────────────╮
│ Split.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
 [h]it   [s]tand   [d]ouble   [t]rainer                                 [q]uit
```

## Play

```sh
./termjack           # or: python3 -m blackjack
```

No dependencies — Python 3.10 or newer and its standard `curses` module, which
ships with Python on Linux and macOS. Needs a terminal of at least 76x22, or
23 rows for the trainer panel to have somewhere to sit.

```
--bankroll N    starting chips (default 500)
--decks N       decks in the shoe, 1-8 (default 6)
--seed N        seed the shuffle for a reproducible shoe
--ascii         plain ASCII box drawing, for terminals without Unicode
--no-trainer    start with the trainer hidden
```

## Keys

| | |
|---|---|
| `←` `→` | size the bet (`↑` `↓` for $25 steps) |
| `1` `2` `3` | add a $5 / $25 / $100 chip |
| `enter` | deal, and start the next hand |
| `h` `s` | hit, stand |
| `d` `p` | double down, split |
| `y` `n` | take or decline insurance |
| `r` | buy back in after going broke |
| `t` | show or hide the trainer |
| `q` | leave the table |

Any key during a deal skips the animation.

## Trainer

Every decision you make — hit, stand, double, split, and the insurance call —
is graded in the panel above the result. The head names the move to make and
the mark says whether you made it: `✓` you did, `✗` you didn't, `≈` the two
were close enough that it barely mattered. The border carries the arithmetic,
in units of your bet:

```
╭─ TRAINER ──────────────────────────────────────── stand -0.17 / yours -0.64 ─╮
│ ✗ Stand. Hard 18 stands: one more card busts it 77% of the time.             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

`Calls` in the sidebar keeps the running tally; only the best move counts.

The advice is not a lookup table. `trainer.py` prices every legal move from
first principles each time: the dealer's chances of landing on 17, 18, 19, 20,
21 or a bust, then what standing, hitting, doubling and splitting are worth
against that spread. The move with the highest expected value is the right one,
and the sentence explaining it is written from the same numbers, so the reason
can never disagree with the verdict.

Three assumptions, all of them the ones basic strategy is derived under:

- The shoe is a full one less the cards showing in this decision. The trainer
  is not a card counter — it teaches the chart, so the same hand earns the same
  advice however deep into the shoe it turns up.
- Cards are drawn with replacement, so a long draw does not deplete the shoe.
- A split is priced as twice one hand playing on with a double allowed, which
  ignores resplitting and reads a shade low.

Together those are worth well under a tenth of a percent, and the test suite
checks the result cell by cell against the same basic-strategy chart that
`tools/verify_odds.py` plays to a 0.46% house edge. Every hard total, soft
total and pair agrees. The one place the trainer knowingly parts company with
the chart is a 16 made of three or more cards against a ten, which really does
stand — the low cards it is built from are the ones that would have rescued a
hit. It is a coin flip either way, so it grades as `≈`.

## House rules

Traditional Vegas shoe game:

- six decks, reshuffled when the cut card comes out at 75% penetration
- dealer stands on all 17, soft 17 included
- blackjack pays 3:2
- insurance offered on a dealer ace, pays 2:1
- double down on any first two cards, including after a split
- split up to four hands; split aces get one card each and never count as
  a blackjack

## Layout

The rules engine has no curses import and no I/O, so it can be tested and
simulated on its own.

```
blackjack/cards.py     Card / Suit / Shoe
blackjack/engine.py    hands, the round state machine, payouts
blackjack/theme.py     colour pairs and glyphs
blackjack/render.py    panels, cards, gauges
blackjack/trainer.py   expected values, the graded advice
blackjack/app.py       screen composition, animation, input
tools/verify_odds.py   basic-strategy simulator, checks the house edge
tests/test_engine.py   rules unit tests
tests/test_trainer.py  odds, advice, and the whole strategy chart
```

## Tests

```sh
python3 -m unittest discover -s tests      # 81 tests
python3 tools/verify_odds.py               # ~500k hands of basic strategy
```

`verify_odds.py` plays perfect basic strategy against the engine and reports
the house edge. These rules should give up about 0.5% — a number that moves
noticeably if the rules or payouts ever drift:

```
win/lose/push 43.50% / 47.98% / 8.52%
house edge    0.462%
```
