"""Scrape ATP / WTA match-winner prices from every book, print good bets and arbs, and log them.

    python -m tennis.run                                  # ATP, WTA, Challenger, WTA 125; all books
    python -m tennis.run --tours ATP WTA                  # main tours only
    python -m tennis.run --min-sharps 1                   # allow bets with only Pinnacle or Betfair
    python -m tennis.run --save --no-log

Same good-bet rule as soccer (engine/evaluate.py): it must clear 1% EV at the
most pessimistic of the Pinnacle / Betfair / crowd estimates, with both sharps
pricing it. Good bets, arbs and a run summary are appended to tennis/logs/.
"""

from __future__ import annotations

import argparse
import csv
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from engine.cli import add_strategy_args, strategy_from
from engine.evaluate import evaluate, find_arbs
from engine.logger import BetLogger, new_run_id
from engine.report import print_arbs, print_books, print_coverage, print_good, print_rejections
from scrapers.common import OddsRow, write_csv
from scrapers.registry import BOOKS, SHARP_BOOKS, SOFT_BOOKS, fetch_all

from .compare import build, coverage, suggest_mappings
from .mappings import ALL_TOURS, DEFAULT_TOURS, tour_filter

SPORT_DIR = Path(__file__).parent


def load_csv(path: str) -> list[OddsRow]:
    out = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            r["line"] = float(r["line"]) if r["line"] else None
            r["odds_decimal"] = float(r["odds_decimal"])
            r["suspended"] = r["suspended"] == "True"
            r["liquidity"] = float(r["liquidity"]) if r.get("liquidity") else None
            out.append(OddsRow(**r))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Tennis +EV / arbitrage finder across AU books.")
    parser.add_argument("--tours", nargs="+", choices=ALL_TOURS, default=list(DEFAULT_TOURS))
    parser.add_argument("--books", nargs="+", choices=list(BOOKS), default=list(BOOKS))
    parser.add_argument("--from-csv", help="analyse a CSV saved with --save instead of scraping (not logged)")
    parser.add_argument("--save", action="store_true", help="write scraped prices to data/tennis/<timestamp>.csv")
    parser.add_argument("--no-log", action="store_true", help="don't append to tennis/logs/")
    parser.add_argument("-v", "--verbose", action="store_true")
    add_strategy_args(parser)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    strategy = strategy_from(args)
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()

    if args.from_csv:
        rows = load_csv(args.from_csv)
        results = []
    else:
        print(f"Scraping {', '.join(args.tours)} from {len(args.books)} books in parallel ...", flush=True)
        results = fetch_all("tennis", args.books, tour_filter(args.tours))
        rows = [r for res in results for r in res.rows]
        print_books(results)
        if args.save:
            out = Path(f"data/tennis/{time.strftime('%Y%m%d_%H%M%S')}.csv")
            write_csv(rows, out)
            print(f"Saved {len(rows)} prices to {out}")

    matched = build(rows)
    sharp = [b for b in SHARP_BOOKS if b in args.books]
    soft = [b for b in SOFT_BOOKS if b in args.books]
    ev = evaluate(matched.markets, sharp, soft, strategy)
    arbs = find_arbs(matched.markets, soft, strategy.bankroll)

    print_coverage(coverage(matched), [b for b in BOOKS if b in args.books], "Matches priced alongside a sharp book")
    suggestions, unmatched = suggest_mappings(matched)
    if suggestions:
        print("\nUnmapped player names (share an opponent and kickoff with a sharp-book match). "
              "Check, then add to PLAYERS in tennis/mappings.py:")
        print("\n".join(suggestions))
    if unmatched:
        print(f"\n{unmatched} soft-book matches have no sharp-book match (often not posted by Pinnacle/Betfair yet).")
    print(f"\nMarkets: {len(matched.markets)} matches, {ev.markets_with_sharp} with a usable sharp price. "
          f"Crowd model: {ev.model.describe()}")

    print_good(ev, strategy)
    print_rejections(ev)
    print_arbs(arbs, strategy.bankroll)

    if not args.from_csv and not args.no_log:
        run_id = new_run_id()
        log = BetLogger(SPORT_DIR)
        log.log_bets(run_id, ev.good, strategy)
        log.log_arbs(run_id, arbs)
        log.log_run(run_id, "tennis", started.isoformat(timespec="seconds"),
                    [r.book for r in results if not r.error], [r.book for r in results if r.error],
                    ev, len(arbs), strategy, time.monotonic() - t0)
        print(f"\nLogged run {run_id} to {log.dir}/ ({len(ev.good)} bets, {len(arbs)} arbs)")


if __name__ == "__main__":
    main()
