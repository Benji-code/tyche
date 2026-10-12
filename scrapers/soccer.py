"""Scrape core soccer markets for a fixed set of European leagues across the
sharp (Pinnacle) and soft (Ladbrokes, Unibet) books, writing one CSV per league.

Each book names leagues differently, so LEAGUES maps our slug to each book's
name(s). Neds is skipped: it shares Ladbrokes' prices.

Usage:
    python -m scrapers.soccer                         # all leagues, all books
    python -m scrapers.soccer --leagues england_premier_league italy_serie_a
    python -m scrapers.soccer --books pinnacle unibet
    python -m scrapers.soccer --fast                  # Ladbrokes match result only (no per-event requests)

Output: data/soccer/<timestamp>/<league>.csv
"""

from __future__ import annotations

import argparse
import logging
import time
from collections import defaultdict
from pathlib import Path

from . import ladbrokes, pinnacle, unibet
from .common import OddsRow, write_csv

log = logging.getLogger(__name__)

BOOKS = ("pinnacle", "ladbrokes", "unibet")

# slug -> per-book league names. Pinnacle/Ladbrokes match the league name exactly
# (case-insensitive); Unibet uses filter paths. Belgium's Ladbrokes/Unibet names
# were unverified at time of writing (no fixtures listed), so several candidates
# are tried.
LEAGUES: dict[str, dict[str, list[str]]] = {
    "england_premier_league": {
        "pinnacle": ["England - Premier League"],
        "ladbrokes": ["Premier League"],
        "unibet": ["football/england/premier_league"],
    },
    "england_championship": {
        "pinnacle": ["England - Championship"],
        "ladbrokes": ["Championship"],
        "unibet": ["football/england/the_championship"],
    },
    "england_league_one": {
        "pinnacle": ["England - League 1"],
        "ladbrokes": ["League One"],
        "unibet": ["football/england/league_one"],
    },
    "italy_serie_a": {
        "pinnacle": ["Italy - Serie A"],
        "ladbrokes": ["Italian Serie A"],
        "unibet": ["football/italy/serie_a"],
    },
    "italy_serie_b": {
        "pinnacle": ["Italy - Serie B"],
        "ladbrokes": ["Italian Serie B"],
        "unibet": ["football/italy/serie_b"],
    },
    "spain_la_liga": {
        "pinnacle": ["Spain - La Liga"],
        "ladbrokes": ["Spanish La Liga"],
        "unibet": ["football/spain/la_liga"],
    },
    "spain_segunda": {
        "pinnacle": ["Spain - Segunda Division"],
        "ladbrokes": ["Spanish Segunda Division"],
        "unibet": ["football/spain/la_liga_2"],
    },
    "germany_bundesliga": {
        "pinnacle": ["Germany - Bundesliga"],
        "ladbrokes": ["German Bundesliga"],
        "unibet": ["football/germany/bundesliga"],
    },
    "germany_2_bundesliga": {
        "pinnacle": ["Germany - Bundesliga 2"],
        "ladbrokes": ["German 2. Bundesliga"],
        "unibet": ["football/germany/2__bundesliga"],
    },
    "france_ligue_1": {
        "pinnacle": ["France - Ligue 1"],
        "ladbrokes": ["French Ligue 1"],
        "unibet": ["football/france/ligue_1"],
    },
    "france_ligue_2": {
        "pinnacle": ["France - Ligue 2"],
        "ladbrokes": ["French Ligue 2"],
        "unibet": ["football/france/ligue_2"],
    },
    "portugal_primeira_liga": {
        "pinnacle": ["Portugal - Primeira Liga"],
        "ladbrokes": ["Portuguese Primeira Liga"],
        "unibet": ["football/portugal/primeira_liga"],
    },
    "belgium_pro_league": {
        "pinnacle": ["Belgium - Pro League"],
        "ladbrokes": ["Belgian Pro League", "Belgian First Division A", "Belgian Jupiler Pro League"],
        "unibet": [
            "football/belgium/pro_league",
            "football/belgium/jupiler_pro_league",
            "football/belgium/first_division_a",
        ],
    },
    "netherlands_eredivisie": {
        "pinnacle": ["Netherlands - Eredivisie"],
        "ladbrokes": ["Dutch Eredivisie"],
        "unibet": ["football/netherlands/eredivisie"],
    },
    "turkey_super_lig": {
        "pinnacle": ["Turkey - Super League"],
        "ladbrokes": ["Turkish Super Lig"],
        "unibet": ["football/turkey/super_lig"],
    },
}


def _bucket_by_league_name(rows: list[OddsRow], book: str, slugs: list[str]) -> dict[str, list[OddsRow]]:
    """Assign rows to slugs using the row's league name (Pinnacle / Ladbrokes)."""
    name_to_slug = {n.lower(): s for s in slugs for n in LEAGUES[s][book]}
    out: dict[str, list[OddsRow]] = defaultdict(list)
    for r in rows:
        slug = name_to_slug.get(r.league.lower())
        if slug:
            out[slug].append(r)
    return out


def scrape_pinnacle(slugs: list[str], delay: float, alternates: bool = False) -> dict[str, list[OddsRow]]:
    names = [n for s in slugs for n in LEAGUES[s]["pinnacle"]]
    rows = pinnacle.scrape(
        ["soccer"], leagues=names, core_only=True, alternates=alternates, client=pinnacle.PinnacleClient(delay)
    )
    return _bucket_by_league_name(rows, "pinnacle", slugs)


def scrape_ladbrokes(slugs: list[str], delay: float, fast: bool) -> dict[str, list[OddsRow]]:
    names = [n for s in slugs for n in LEAGUES[s]["ladbrokes"]]
    rows = ladbrokes.scrape(
        ["soccer"],
        competitions=names,
        event_cards=not fast,
        core_only=True,
        client=ladbrokes.EntainClient("ladbrokes", delay),
    )
    return _bucket_by_league_name(rows, "ladbrokes", slugs)


def scrape_unibet(slugs: list[str], delay: float) -> dict[str, list[OddsRow]]:
    # Unibet's league names aren't unique ("Premier League"), so bucket by the
    # path each request was made for rather than by name.
    client = unibet.UnibetClient(delay)
    return {s: unibet.scrape(LEAGUES[s]["unibet"], client=client) for s in slugs}


def scrape_all(
    slugs: list[str],
    books: list[str] = list(BOOKS),
    delay: float = 0.7,
    fast: bool = False,
    pinnacle_alternates: bool = False,
) -> dict[str, dict[str, list[OddsRow]]]:
    """Returns {book: {league_slug: rows}}. A failing book yields {} rather than raising."""
    runners = {
        "pinnacle": lambda: scrape_pinnacle(slugs, delay, pinnacle_alternates),
        "ladbrokes": lambda: scrape_ladbrokes(slugs, delay, fast),
        "unibet": lambda: scrape_unibet(slugs, delay),
    }
    by_book: dict[str, dict[str, list[OddsRow]]] = {}
    for book in books:
        log.info("Scraping %s ...", book)
        try:
            by_book[book] = runners[book]()
        except Exception:
            # One book failing (blocked, endpoint changed) shouldn't lose the others.
            log.exception("%s failed; continuing without it", book)
            by_book[book] = {}
    return by_book


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape European soccer leagues across sharp and soft books.")
    parser.add_argument("--leagues", nargs="+", choices=list(LEAGUES), default=list(LEAGUES), metavar="LEAGUE",
                        help=f"subset of leagues (default all): {', '.join(LEAGUES)}")
    parser.add_argument("--books", nargs="+", choices=BOOKS, default=list(BOOKS))
    parser.add_argument("--fast", action="store_true",
                        help="Ladbrokes: match result only, skipping one request per event")
    parser.add_argument("--delay", type=float, default=0.7, help="seconds between requests per book (default 0.7)")
    parser.add_argument("-o", "--output-dir", help="default: data/soccer/<timestamp>")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    slugs = args.leagues
    out_dir = Path(args.output_dir or f"data/soccer/{time.strftime('%Y%m%d_%H%M%S')}")

    by_book = scrape_all(slugs, args.books, args.delay, args.fast)

    # Write one file per league and print a coverage table: events per book.
    header = f"{'league':<26}" + "".join(f"{b:>11}" for b in args.books) + "   file"
    print("\n" + header + "\n" + "-" * len(header))
    for slug in slugs:
        rows = [r for book in args.books for r in by_book[book].get(slug, [])]
        counts = [len({r.event_id for r in by_book[b].get(slug, [])}) for b in args.books]
        path = out_dir / f"{slug}.csv"
        write_csv(rows, path)
        print(f"{slug:<26}" + "".join(f"{c:>11}" for c in counts) + f"   {path}")
        for book, c in zip(args.books, counts):
            if c == 0:
                log.warning("%s: no events from %s (no fixtures, or league name needs updating in LEAGUES)", slug, book)


if __name__ == "__main__":
    main()
