# termjack

A classic blackjack table in the terminal.

```
╭─ TABLE ───────────────────────────────────────── shoe 98% ─╮╭─ CHIPS ────────╮
│ DEALER   showing 8                                         ││                │
│   ╭───╮ ╭───╮                                              ││ Bank      $450 │
│   │8  │ │▓▓▓│                                              ││ Bet        $25 │
│   │  ♦│ │▓▓▓│                                              ││ Net         $0 │
│   ╰───╯ ╰───╯                                              ││                │
├────────────────────────────────────────────────────────────┤│ Shoe           │
│ PLAYER  (2 hands)                                          ││ ██████████████ │
│ ▸  18              20                                      ││                │
│ ▸ ╭───╮ ╭───╮     ╭───╮ ╭───╮                              ││ ────────────── │
│   │K  │ │8  │     │J  │ │10 │                              ││ Won          0 │
│   │  ♠│ │  ♣│     │  ♦│ │  ♥│                              ││ Lost         0 │
│   ╰───╯ ╰───╯     ╰───╯ ╰───╯                              ││ Push         0 │
│   $25             $25                                      ││ BJ           0 │
╰────────────────────────────────────────────────────────────╯╰────────────────╯
╭─ YOUR TURN ──────────────────────────────────────────────────────────────────╮
│ Split.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
 [h]it   [s]tand   [d]ouble                                             [q]uit
```

## Play

```sh
./termjack           # or: python3 -m blackjack
```

No dependencies — Python 3.10 or newer and its standard `curses` module, which
ships with Python on Linux and macOS. Needs a terminal of at least 76x22.

```
--bankroll N    starting chips (default 500)
--decks N       decks in the shoe, 1-8 (default 6)
--seed N        seed the shuffle for a reproducible shoe
--ascii         plain ASCII box drawing, for terminals without Unicode
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
| `q` | leave the table |

Any key during a deal skips the animation.

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
blackjack/app.py       screen composition, animation, input
tools/verify_odds.py   basic-strategy simulator, checks the house edge
tests/test_engine.py   unit tests
```

## Tests

```sh
python3 -m unittest discover -s tests      # 48 tests
python3 tools/verify_odds.py               # ~500k hands of basic strategy
```

`verify_odds.py` plays perfect basic strategy against the engine and reports
the house edge. These rules should give up about 0.5% — a number that moves
noticeably if the rules or payouts ever drift:

```
win/lose/push 43.50% / 47.98% / 8.52%
house edge    0.462%
```
