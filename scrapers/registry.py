"""Every scraper behind one interface, fetched in parallel.

Each book's module exposes fetch(sport, competition_filter, **options) ->
list[OddsRow]. Books run concurrently (one thread per book, each still
rate-limited against its own host), and a failing book is reported rather
than raised.

Not implemented, and why (checked Oct 2026):
    TAB / TABtouch  Akamai bot filter drops non-browser connections (no workaround attempted)
    bet365          Cloudflare challenge page (no workaround attempted)
    Polymarket      blocked in Australia (ACMA ISP block)
    Dabble          props / SGM focused; no public fixtures API found
    PlayUp, Picklebet  SPA-only APIs not discoverable without a browser
    White-label clusters (Amused, BSA, Mintsports, Booki): racing-focused,
        mostly copy feed prices for sports, so little value for +EV
    Neds            identical prices to Ladbrokes (same Entain backend)
    BlueBet, TopSport  merged into Betr (scrapers/betr.py)
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from . import betfair, betr, betright, ladbrokes, palmerbet, pinnacle, pointsbet, sportsbet, unibet
from .common import CompetitionFilter, OddsRow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Book:
    name: str
    role: str  # "sharp" (reference price) or "soft" (where we bet)
    fetch: Callable[..., list[OddsRow]]
    sports: tuple[str, ...] = ("soccer", "tennis")


BOOKS: dict[str, Book] = {
    b.name: b
    for b in [
        Book("pinnacle", "sharp", pinnacle.fetch),
        Book("betfair", "sharp", betfair.fetch),
        Book("ladbrokes", "soft", ladbrokes.fetch),
        Book("unibet", "soft", unibet.fetch),
        Book("sportsbet", "soft", sportsbet.fetch),
        Book("pointsbet", "soft", pointsbet.fetch),
        Book("betr", "soft", betr.fetch),
        Book("betright", "soft", betright.fetch),
        Book("palmerbet", "soft", palmerbet.fetch),
    ]
}
SHARP_BOOKS = tuple(n for n, b in BOOKS.items() if b.role == "sharp")
SOFT_BOOKS = tuple(n for n, b in BOOKS.items() if b.role == "soft")

# OddsRow.bookmaker -> registry name (older scrapers tag the brand/region).
BOOK_OF_ROW = {"ladbrokes_au": "ladbrokes", "neds_au": "ladbrokes", "unibet_au": "unibet"}


def book_of(row: OddsRow) -> str:
    return BOOK_OF_ROW.get(row.bookmaker, row.bookmaker)


@dataclass
class FetchResult:
    book: str
    rows: list[OddsRow]
    seconds: float
    error: str | None = None


def fetch_all(
    sport: str,
    books: list[str],
    competition_filter: CompetitionFilter,
    options: dict[str, dict[str, Any]] | None = None,
) -> list[FetchResult]:
    options = options or {}

    def run(name: str) -> FetchResult:
        t0 = time.monotonic()
        try:
            rows = BOOKS[name].fetch(sport, competition_filter, **options.get(name, {}))
            return FetchResult(name, rows, time.monotonic() - t0)
        except Exception as e:  # one book failing shouldn't lose the others
            log.exception("%s failed", name)
            return FetchResult(name, [], time.monotonic() - t0, f"{type(e).__name__}: {e}"[:200])

    wanted = [b for b in books if sport in BOOKS[b].sports]
    with ThreadPoolExecutor(max_workers=len(wanted) or 1) as pool:
        return list(pool.map(run, wanted))
