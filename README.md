# tyche

Positive-EV betting finder: compare Australian soft-book prices against sharp references (Pinnacle, Betfair Exchange), confirm with a "wisdom of the crowd" model, size with fractional Kelly, and log every recommendation so strategies can be judged later.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
source .venv/bin/activate        # or prefix commands with .venv/bin/
```

## Run

```bash
python -m soccer.run             # 15 European leagues, all books (~1 min)
python -m tennis.run             # ATP, WTA, Challenger, WTA 125 match winner (~15 s)
```

Each run prints book status, cross-book matching coverage, unmapped names (as paste-ready dictionary lines), **good bets** with half-Kelly stakes on $100, the +EV prices that were rejected and why, and soft-book arbs. Good bets, arbs and a run summary are appended to `soccer/logs/` or `tennis/logs/`.

Useful flags (both sports): `--min-sharps 1` (allow bets when only Pinnacle or Betfair prices the market), `--min-ev 0.03`, `--bankroll 500 --kelly 0.25`, `--books pinnacle betfair sportsbet ...`, `--save` (keep raw prices in `data/`), `--no-log`. Soccer: `--leagues ...`, `--from-dir data/soccer/<ts>`. Tennis: `--tours ATP WTA`, `--from-csv data/tennis/<ts>.csv`. `--help` lists everything.

## What counts as a good bet (`engine/evaluate.py`)

Risk-neutral to slightly risk-averse: every bet is judged and sized on a **pessimistic** fair probability, because we only bet where our estimate looks best (the winner's curse inflates estimated edges).

For each outcome, every available fair-probability estimate is collected:
- **Pinnacle** with its margin removed three ways (multiplicative, power, Shin), if its margin is ≤ 10%;
- **Betfair** back/lay midpoint, if ≥ $1,000 is matched and the spread is ≤ 10%;
- **Crowd**: the sharp price predicted from the *other* soft books (`engine/crowd.py`: median of their margin-free prices, mapped to a sharp probability by a logistic calibration fitted each run on markets where the sharp price is known).

`p_center` is the sharp average; `p_min` is the lowest estimate of all. A price is a good bet only if:

1. both sharps price it (`--min-sharps 2`),
2. the sharps agree within 3 percentage points,
3. a crowd estimate exists (≥ 3 other soft books),
4. **worst-case EV = p_min × odds − 1 ≥ 1%** (`--min-ev`),
5. EV at `p_center` ≤ 20% (bigger is almost always a mapping error or stale price).

**Stake** = bankroll × ½ × full-Kelly fraction **at p_min**, then capped at 2.5% of bankroll per bet, 5% per event (correlated bets on one match share the cap) and 20% per run (`--kelly`, `--max-stake`, `--max-event`, `--max-total`). Arbs use soft books only (Pinnacle doesn't take Australian customers; Betfair midpoints aren't bettable prices).

The output shows each estimate as fair odds (Pin / BF / Crowd / Worst), EV at worst and at centre, and marks capped stakes with `^`. Rejected prices list which estimate failed them.

## Logs (for judging strategies)

`<sport>/logs/bets.csv`: one row per good bet per run, with odds, Pinnacle / Betfair / crowd probabilities, `p_min` and which estimate set it, worst-case and central EV, capped and uncapped stake, and the full strategy string. If the columns change, the old file is kept as `bets.until-<date>.csv` and a new one is started. The same bet found on several runs repeats with the same `bet_key`: dedupe on it (keep the first) to count each bet once at the price you'd have taken. `result`, `closing_fair_odds` and `pnl` are blank, to be filled by a settlement step. `arbs.csv` holds arb legs, and `runs.csv` has one row per run (books that worked, market counts, crowd-model fit).

## Layout

```
scrapers/      one module per book + registry.py (parallel fetch, failure isolation)
engine/        odds maths, crowd model, evaluation, logger, terminal report (sport-agnostic)
soccer/        mappings.py (TEAMS, league patterns, market names), compare.py (matching), run.py, logs/
tennis/        mappings.py (tours, PLAYERS), compare.py (player matching), run.py, logs/
```

## Books

| Book | Role | Method | Notes |
|---|---|---|---|
| Pinnacle | sharp | keyless guest API | soccer totals include alternate lines (marked `*`) |
| Betfair Exchange | sharp | anonymous read-only exchange API | delayed prices; midpoint of best back/lay |
| Ladbrokes (= Neds) | soft | Entain REST API | soccer fetches each match's markets (slowest book, ~60 s) |
| Unibet | soft | Kambi feed via unibet.com.au | soccer by league path (sport-wide view is truncated) |
| Sportsbet | soft | site JSON API | 1X2 + Over/Under 2.5; tennis match betting |
| PointsBet | soft | public API | match result only |
| Betr (= BlueBet, TopSport) | soft | BlueBet API | one request per sport |
| BetRight | soft | site API | match result only |
| Palmerbet | soft | fixture API | match result only |

Not implemented (details in `scrapers/registry.py`): TAB/TABtouch (Akamai bot filter), bet365 (Cloudflare challenge), Polymarket (blocked in Australia), Dabble, PlayUp and Picklebet (no API found without a browser), and the racing-focused white-label clusters. No bot-protection workarounds are used.

## Conventions

- Every scraper exposes `fetch(sport, competition_filter, **options) -> list[OddsRow]` (schema in `scrapers/common.py`, one row per outcome). Sport packages pass the filter, so "which leagues/tours" lives in one place per sport.
- Team and player names map to Pinnacle's spelling. Most differences are handled by normalisation; the runners print suggested `TEAMS` / `PLAYERS` entries for the rest, to check and paste in.
- Individual scrapers can also be run alone for CSVs, e.g. `python -m scrapers.pinnacle basketball -l NBA`, `python -m scrapers.ladbrokes --list-sports`, `python -m scrapers.unibet basketball/nba`.
