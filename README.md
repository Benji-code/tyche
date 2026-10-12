# tyche

Positive-EV betting finder: compare soft-book prices against sharp references (Pinnacle / Betfair).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Scrapers

All scrapers write the same long-format CSV (one row per outcome, schema in `scrapers/common.py`).
Group by `(bookmaker, event_id, market_id)` to get a complete market for devigging.

### Unibet AU

Uses the JSON feed behind unibet.com.au (Kambi platform), no HTML parsing.

```bash
.venv/bin/python -m scrapers.unibet --list-sports
.venv/bin/python -m scrapers.unibet --list-leagues basketball
.venv/bin/python -m scrapers.unibet basketball/nba football/england/premier_league
.venv/bin/python -m scrapers.unibet australian_rules --all-markets --prematch-only -o data/afl.csv
```

- By default fetches the main markets (head-to-head, line/spread, totals). `--all-markets` fetches every category.
- Sport-wide paths (e.g. `football`) return a truncated event list; use league paths for full coverage.
- `odds_decimal` and `line` are already converted from Kambi's integer thousandths.

### Ladbrokes AU / Neds

Same Entain backend for both brands (identical event ids and, so far, identical prices), so `--brand` just picks the host.

```bash
.venv/bin/python -m scrapers.ladbrokes --list-sports
.venv/bin/python -m scrapers.ladbrokes --list-competitions soccer
.venv/bin/python -m scrapers.ladbrokes basketball                                   # main market only, 1 request per sport
.venv/bin/python -m scrapers.ladbrokes basketball -c NBA --event-cards --core-only  # H2H + line + total per game
.venv/bin/python -m scrapers.ladbrokes soccer -c "Premier League" --brand neds --event-cards
```

- Without `--event-cards` you get only each event's main market (H2H / Match Result) plus outright markets.
- `--event-cards` fetches every market per match (one request per event); `--core-only` trims to full-game H2H / line / totals, matched by market name (`CORE_MARKET_NAME` in `scrapers/ladbrokes.py`; extend it for new sports).
- Lines are per outcome: Entain stores a two-way handicap from the away side, the scraper flips it for the home side.

### Pinnacle (sharp reference)

Reads the keyless guest API behind pinnacle.com (two requests per sport, all leagues).

```bash
.venv/bin/python -m scrapers.pinnacle --list-sports
.venv/bin/python -m scrapers.pinnacle --list-leagues soccer
.venv/bin/python -m scrapers.pinnacle basketball -l NBA --core-only
.venv/bin/python -m scrapers.pinnacle soccer -l "England - Premier League"
.venv/bin/python -m scrapers.pinnacle hockey --alternates --periods 0 1
```

- `-l` matches a league name exactly if one exists, otherwise by substring (so use full names like `"England - Premier League"`).
- Defaults: full-game period only, main lines only. `--alternates` adds alt spreads/totals; `--core-only` drops team totals.
- American odds are converted to decimal; spread `line` is already per side.

### European soccer leagues (all books)

Core markets for 15 leagues (EPL, Championship, League One; Serie A/B; La Liga/Segunda; Bundesliga/2. Bundesliga; Ligue 1/2; Primeira Liga; Belgian Pro League; Eredivisie; Super Lig) from Pinnacle, Ladbrokes and Unibet, one CSV per league.

```bash
python -m scrapers.soccer                                   # ~2 min, writes data/soccer/<timestamp>/<league>.csv
python -m scrapers.soccer --leagues england_premier_league italy_serie_a
python -m scrapers.soccer --books pinnacle unibet --fast
```

- League names per book live in `LEAGUES` in `scrapers/soccer.py`. A coverage table is printed at the end; a 0 means no fixtures listed or a name needs fixing.
- Belgium's Ladbrokes/Unibet names are unverified guesses (no fixtures were listed when this was written).
- Books list different horizons: Pinnacle and Unibet often show the next two rounds, Ladbrokes fewer.

## Soccer +EV / arbitrage finder (`soccer/`)

Scrapes the 15 soccer leagues, matches games across books, and prints +EV bets (soft price vs devigged Pinnacle) and arbs with fractional-Kelly stakes.

```bash
python -m soccer.run                                  # scrape (~2 min) + analyse, $100 bankroll at half Kelly
python -m soccer.run --save                           # also keep the CSVs in data/soccer/<timestamp>/
python -m soccer.run --from-dir data/soccer/<ts>      # re-analyse saved CSVs without scraping
python -m soccer.run --min-ev 0.01 --bankroll 500 --kelly 0.25 --devig multiplicative
```

- `soccer/mappings.py`: `TEAMS` (canonical Pinnacle name -> each book's name) and `MARKETS` (which market names are comparable). Unmapped names print as paste-ready lines.
- `soccer/compare.py`: matching, devig (power / multiplicative), EV, Kelly, arbs.
- Compares full-time 1X2 and total goals at identical lines only; prematch, open prices only.
- Arbs exclude Pinnacle legs by default (it doesn't accept Australian customers); `--arb-include-pinnacle` to override.
- EV above `--max-ev` (30%) is hidden as a likely mapping/stale-price error.

### Shared conventions

- `sport` is canonicalised to Ladbrokes' enum (`SOCCER`, `AMERICAN_FOOTBALL`, `ICE_HOCKEY`, ...). Note Unibet's "FOOTBALL" is soccer but Pinnacle's "Football" is American football; each scraper maps its own.
- `market_type` is one of `Match`, `Handicap`, `Over/Under`, `Team Total`, `Other` across all books.
- Team names are **not** yet normalised across books (NBA happens to match; soccer won't).
