"""Scrape the soccer leagues from every book, print good bets and arbs, and log them.

    python -m soccer.run                                   # all books, all leagues
    python -m soccer.run --leagues england_premier_league italy_serie_a
    python -m soccer.run --min-sharps 1                    # allow bets with only Pinnacle or Betfair
    python -m soccer.run --from-dir data/soccer/<ts>       # re-analyse saved CSVs (no scraping, no logging)
    python -m soccer.run --save --no-log

A bet is "good" only if it clears 1% EV at the most pessimistic of the
Pinnacle / Betfair / crowd estimates, with both sharps pricing it; see
engine/evaluate.py. Good bets, arbs and a run summary are appended to
soccer/logs/.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from engine.cli import add_strategy_args, strategy_from
from engine.evaluate import evaluate, find_arbs
from engine.logger import BetLogger, new_run_id
from engine.report import print_arbs, print_books, print_coverage, print_good, print_rejections
from scrapers.common import write_csv
from scrapers.registry import BOOKS, SHARP_BOOKS, SOFT_BOOKS, fetch_all

from .compare import build, coverage, load_csv_dir, suggest_mappings
from .mappings import LEAGUE_PATTERNS, UNIBET_PATHS, league_filter

SPORT_DIR = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Soccer +EV / arbitrage finder across AU books.")
    parser.add_argument("--leagues", nargs="+", choices=list(LEAGUE_PATTERNS), default=list(LEAGUE_PATTERNS), metavar="LEAGUE")
    parser.add_argument("--books", nargs="+", choices=list(BOOKS), default=list(BOOKS))
    parser.add_argument("--from-dir", help="analyse saved CSVs instead of scraping (not logged)")
    parser.add_argument("--save", action="store_true", help="write scraped prices to data/soccer/<timestamp>/")
    parser.add_argument("--no-log", action="store_true", help="don't append to soccer/logs/")
    parser.add_argument("-v", "--verbose", action="store_true")
    add_strategy_args(parser)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    strategy = strategy_from(args)
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()

    if args.from_dir:
        rows = [r for r in load_csv_dir(args.from_dir) if r.league in args.leagues]
        results = []
    else:
        print(f"Scraping {len(args.leagues)} leagues from {len(args.books)} books in parallel ...", flush=True)
        unibet_paths = {lg: UNIBET_PATHS[lg] for lg in args.leagues}
        results = fetch_all("soccer", args.books, league_filter(args.leagues), {"unibet": {"paths": unibet_paths}})
        rows = [r for res in results for r in res.rows]
        print_books(results)
        if args.save:
            out = Path(f"data/soccer/{time.strftime('%Y%m%d_%H%M%S')}")
            for lg in args.leagues:
                write_csv([r for r in rows if r.league == lg], out / f"{lg}.csv")
            print(f"Saved CSVs to {out}")

    matched = build(rows)
    sharp = [b for b in SHARP_BOOKS if b in args.books]
    soft = [b for b in SOFT_BOOKS if b in args.books]
    ev = evaluate(matched.markets, sharp, soft, strategy)
    arbs = find_arbs(matched.markets, soft, strategy.bankroll)

    print_coverage(coverage(matched), [b for b in BOOKS if b in args.books], "Events matched to a sharp book")
    suggestions, no_fixture = suggest_mappings(matched)
    if suggestions:
        print("\nUnmapped team names (same league + kickoff as a Pinnacle game). Check, then add to TEAMS in soccer/mappings.py:")
        print("\n".join(suggestions))
    if no_fixture:
        print(f"\n{no_fixture} soft-book listings have no sharp-book game at that kickoff (usually not posted yet).")
    print(f"\nMarkets: {len(matched.markets)} total, {ev.markets_with_sharp} with a usable sharp price. "
          f"Crowd model: {ev.model.describe()}")

    print_good(ev, strategy)
    print_rejections(ev)
    print_arbs(arbs, strategy.bankroll)

    if not args.from_dir and not args.no_log:
        run_id = new_run_id()
        log = BetLogger(SPORT_DIR)
        log.log_bets(run_id, ev.good, strategy)
        log.log_arbs(run_id, arbs)
        log.log_run(run_id, "soccer", started.isoformat(timespec="seconds"),
                    [r.book for r in results if not r.error], [r.book for r in results if r.error],
                    ev, len(arbs), strategy, time.monotonic() - t0)
        print(f"\nLogged run {run_id} to {log.dir}/ ({len(ev.good)} bets, {len(arbs)} arbs)")


if __name__ == "__main__":
    main()
