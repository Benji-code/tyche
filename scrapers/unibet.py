"""Unibet Australia odds scraper.

Unibet runs on the Kambi sportsbook platform. Rather than parsing HTML we hit
the same JSON feed the site's frontend uses:

    https://www.unibet.com.au/sportsbook-feeds/views/filter/{sport}/{league}/all/matches

A view returns one market "category" at a time (e.g. Moneyline, then Spread),
so we fetch the default view, read the categories it advertises, and refetch
once per category.

Usage:
    python -m scrapers.unibet --list-sports
    python -m scrapers.unibet --list-leagues football
    python -m scrapers.unibet basketball/nba
    python -m scrapers.unibet basketball/nba football/england/premier_league -o data/unibet.csv
    python -m scrapers.unibet australian_rules --all-markets
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any, Iterator

from .common import CompetitionFilter, JsonClient, OddsRow, accept_all, canonical_sport, utc_now_iso, write_csv

log = logging.getLogger(__name__)

BOOKMAKER = "unibet_au"
BASE_URL = "https://www.unibet.com.au/sportsbook-feeds/views"
HEADERS = {"Referer": "https://www.unibet.com.au/betting/sports/home"}
SPORT_ALIASES = {"FOOTBALL": "SOCCER", "UFC_MMA": "MIXED_MARTIAL_ARTS"}

# Kambi outcome types -> normalised selection, for matching against other books.
SELECTION_BY_TYPE = {
    "OT_ONE": "home",
    "OT_CROSS": "draw",
    "OT_TWO": "away",
    "OT_OVER": "over",
    "OT_UNDER": "under",
}


class UnibetClient:
    def __init__(self, delay: float = 1.0):
        self.http = JsonClient(HEADERS, delay=delay)

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return self.http.get(f"{BASE_URL}/{path}", params)

    def list_sports(self) -> list[dict]:
        data = self.get("sports/a-z")
        for widget in _widgets(data):
            if "sports" in widget:
                return widget["sports"]
        return []

    def list_leagues(self, sport: str) -> list[tuple[str, int]]:
        """(filter path, bet offer count) for each league in a sport-wide view."""
        leagues = []

        def walk(groups: list[dict] | None) -> None:
            for g in groups or []:
                if g.get("navigationUrl"):
                    path = g["navigationUrl"].split("/filter/", 1)[-1]
                    leagues.append((path, g.get("boCount") or 0))
                walk(g.get("subGroups"))

        walk(self.matches_view(sport).get("groups"))
        return leagues

    def matches_view(self, filter_path: str, category: int | None = None) -> dict:
        """Return the TOURNAMENT widget's `matches` block for e.g. 'basketball/nba'."""
        params: dict[str, Any] = {"includeParticipants": "true"}
        if category is not None:
            params["category"] = category
        data = self.get(f"filter/{_normalise_filter(filter_path)}/all/matches", params)
        for widget in _widgets(data):
            if widget.get("widgetType") == "TOURNAMENT" and widget.get("matches"):
                return widget["matches"]
        return {}


def _normalise_filter(filter_path: str) -> str:
    """'basketball/nba' -> 'basketball/nba'; 'basketball' -> 'basketball/all'."""
    parts = [p for p in filter_path.strip("/").lower().split("/") if p]
    if len(parts) == 1:
        parts.append("all")
    return "/".join(parts)


def _widgets(view: dict) -> Iterator[dict]:
    for section in view.get("layout", {}).get("sections", []):
        yield from section.get("widgets", [])


def _iter_events(matches: dict) -> Iterator[dict]:
    """Yield event entries from a matches block.

    League views list events directly; sport-wide views nest them under
    groups -> subGroups -> ... -> events.
    """
    yield from matches.get("events") or []

    def walk(groups: list[dict] | None) -> Iterator[dict]:
        for g in groups or []:
            yield from g.get("events") or []
            yield from walk(g.get("subGroups"))

    yield from walk(matches.get("groups"))


def _categories(matches: dict, all_markets: bool) -> list[int]:
    """Category ids to fetch. By default only the main 'combined_layout' group
    (head-to-head, line, totals); with all_markets, every advertised category."""
    ids: list[int] = []
    for group in matches.get("categoryGroups") or []:
        if all_markets or group.get("categoryGroupName") == "combined_layout":
            ids.extend(c["id"] for c in group.get("categories", []))
    return ids


def _rows_from_event(entry: dict, scraped_at: str) -> Iterator[OddsRow]:
    ev = entry["event"]
    path = ev.get("path") or []
    league = path[-1]["englishName"] if path else ev.get("group", "")
    for bo in entry.get("betOffers") or []:
        for o in bo.get("outcomes") or []:
            if o.get("odds") is None:
                continue
            line = o.get("line")
            yield OddsRow(
                scraped_at=scraped_at,
                bookmaker=BOOKMAKER,
                sport=canonical_sport(ev.get("sport", ""), SPORT_ALIASES),
                league=league,
                event_id=str(ev["id"]),
                event_name=ev.get("englishName") or ev.get("name", ""),
                home_team=ev.get("homeName"),
                away_team=ev.get("awayName"),
                start_time=ev.get("start", ""),
                event_state=ev.get("state", ""),
                market_id=str(bo["id"]),
                market_type=bo.get("betOfferType", {}).get("englishName", ""),
                market_name=bo.get("criterion", {}).get("englishLabel", ""),
                # Kambi encodes odds and lines as integers in thousandths.
                line=line / 1000 if line is not None else None,
                outcome_id=str(o["id"]),
                outcome_label=o.get("englishLabel") or o.get("label", ""),
                selection=SELECTION_BY_TYPE.get(o.get("type", "")),
                participant=o.get("participant"),
                odds_decimal=o["odds"] / 1000,
                status=o.get("status", ""),
                suspended=bool(bo.get("suspended")),
            )


def scrape(
    filter_paths: list[str],
    all_markets: bool = False,
    include_live: bool = True,
    client: UnibetClient | None = None,
) -> list[OddsRow]:
    client = client or UnibetClient()
    rows: list[OddsRow] = []
    seen_outcomes: set[str] = set()

    for filter_path in filter_paths:
        base = client.matches_view(filter_path)
        if not base:
            log.warning("No matches found for %s", filter_path)
            continue

        views = [base]
        for cat in _categories(base, all_markets):
            if cat in (base.get("activeCategories") or []):
                continue
            views.append(client.matches_view(filter_path, category=cat))

        scraped_at = utc_now_iso()
        before = len(rows)
        for view in views:
            for entry in _iter_events(view):
                if not include_live and entry["event"].get("state") != "NOT_STARTED":
                    continue
                for row in _rows_from_event(entry, scraped_at):
                    if row.outcome_id in seen_outcomes:
                        continue
                    seen_outcomes.add(row.outcome_id)
                    rows.append(row)
        log.info("%s: %d outcomes across %d views", filter_path, len(rows) - before, len(views))

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Unibet AU odds to CSV.")
    parser.add_argument(
        "filters",
        nargs="*",
        help="sport or sport/league filter paths, e.g. basketball/nba, australian_rules",
    )
    parser.add_argument("-o", "--output", help="CSV path (default: data/unibet_<timestamp>.csv)")
    parser.add_argument("--all-markets", action="store_true", help="fetch every market category, not just main lines")
    parser.add_argument("--prematch-only", action="store_true", help="skip events already in play")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1.0)")
    parser.add_argument("--list-sports", action="store_true", help="print available sports and exit")
    parser.add_argument("--list-leagues", metavar="SPORT", help="print league filter paths for a sport and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    client = UnibetClient(delay=args.delay)

    if args.list_sports:
        for s in client.list_sports():
            print(f"{s['url'].rsplit('/', 1)[-1]:<24} {s['name']:<24} {s.get('boCount', '')}")
        return

    if args.list_leagues:
        for path, count in client.list_leagues(args.list_leagues):
            print(f"{path:<48} {count}")
        return

    if not args.filters:
        parser.error("give at least one filter path (or --list-sports)")

    rows = scrape(args.filters, all_markets=args.all_markets, include_live=not args.prematch_only, client=client)
    output = args.output or f"data/unibet_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    n = write_csv(rows, output)
    log.info("Wrote %d rows to %s", n, output)


if __name__ == "__main__":
    main()


def fetch(
    sport: str,
    competition_filter: CompetitionFilter = accept_all,
    client: UnibetClient | None = None,
    paths: dict[str, list[str]] | None = None,
) -> list[OddsRow]:
    """Uniform entry point used by scrapers.registry.

    Unibet's sport-wide soccer view is truncated, so soccer needs explicit
    league paths ({label: [filter paths]}). Tennis reads the sport-wide view and
    labels each event from its path (e.g. "ATP Shanghai", "Challenger Jinan")."""
    client = client or UnibetClient(delay=0.5)
    rows: list[OddsRow] = []
    if paths:
        for label, ps in paths.items():
            for row in scrape(ps, client=client):
                row.league = label
                rows.append(row)
        return rows

    view = client.matches_view({"soccer": "football", "tennis": "tennis"}[sport])
    scraped_at = utc_now_iso()
    for entry in _iter_events(view):
        path = entry["event"].get("path") or []
        label = competition_filter(" ".join(p["englishName"] for p in path[1:]), None)
        if not label:
            continue
        for row in _rows_from_event(entry, scraped_at):
            row.league = label
            rows.append(row)
    return rows
