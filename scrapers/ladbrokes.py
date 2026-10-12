"""Ladbrokes AU / Neds odds scraper.

Both brands are Entain Australia and share one backend: same event ids, same
category ids, and (as of Oct 2026) identical prices. Pick one with --brand.

Endpoints (what the sites' frontends call):
    POST https://api.{brand}.com.au/graphql            SportingCategories -> sport ids
    GET  https://api.{brand}.com.au/v2/sport/event-request?category_ids=[...]
         -> every open event in a sport, with its main market only (H2H / Match Result)
    GET  https://api.{brand}.com.au/v2/sport/event-card?id=<event_id>
         -> every market for one event (line, totals, props, ...)

The API rejects requests without a JSON Content-Type header.

Usage:
    python -m scrapers.ladbrokes --list-sports
    python -m scrapers.ladbrokes --list-competitions basketball
    python -m scrapers.ladbrokes basketball --competition NBA
    python -m scrapers.ladbrokes basketball --competition NBA --event-cards
    python -m scrapers.ladbrokes soccer ice-hockey --brand neds -o data/neds.csv
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from collections import Counter
from typing import Iterator

from .common import JsonClient, OddsRow, utc_now_iso, write_csv

log = logging.getLogger(__name__)

BRANDS = ("ladbrokes", "neds")

# Price keys look like "<entrant_id>:<price_type_id>:"; this type is fixed-odds win.
FIXED_WIN_PRICE_TYPE = "940b8704-e497-4a76-b390-00918ff7d282"
MARKET_STATUS_OPEN = "4bc8fe96-296b-4b4c-aea4-85c94f63b9c6"

# Markets kept by --core-only: full-game markets comparable across books.
# Structure alone isn't enough (soccer has "Result after 15 minutes", team
# totals, etc. that look identical), so whitelist names. Extend as needed.
CORE_MARKETS = {"Match", "Handicap", "Over/Under"}
CORE_MARKET_NAME = re.compile(
    r"^(head to head|match result|money line|match betting"
    r"|line|handicap|asian handicap|puck line|run line"
    r"|total|total points|total goals|total runs|over/under total goals [\d.]+)$",
    re.IGNORECASE,
)

CATEGORIES_QUERY = """
query SportingCategories {
  categories: sportingCategories { id name category slug }
}
"""


class EntainClient:
    def __init__(self, brand: str = "ladbrokes", delay: float = 0.5):
        if brand not in BRANDS:
            raise ValueError(f"brand must be one of {BRANDS}")
        self.brand = brand
        self.base = f"https://api.{brand}.com.au"
        self.http = JsonClient(
            {
                "Content-Type": "application/json",
                "Origin": f"https://www.{brand}.com.au",
                "Referer": f"https://www.{brand}.com.au/",
            },
            delay=delay,
        )

    def categories(self) -> list[dict]:
        """[{id, name, category, slug}, ...] e.g. slug 'basketball', category 'BASKETBALL'."""
        data = self.http.post(f"{self.base}/graphql", {"operationName": "SportingCategories", "query": CATEGORIES_QUERY})
        return data["data"]["categories"]

    def event_request(self, category_id: str) -> dict:
        return self.http.get(
            f"{self.base}/v2/sport/event-request",
            {"category_ids": json.dumps([category_id])},
        )

    def event_card(self, event_id: str) -> dict:
        return self.http.get(f"{self.base}/v2/sport/event-card", {"id": event_id})


def _decimal_odds(price: dict) -> float | None:
    odds = price.get("odds") or {}
    num, den = odds.get("numerator"), odds.get("denominator")
    if num is None or not den:
        return None
    return round(num / den + 1, 4)


def _prices_by_entrant(prices: dict) -> dict[str, dict]:
    out = {}
    for key, price in prices.items():
        entrant_id, price_type, *_ = key.split(":")
        if price_type == FIXED_WIN_PRICE_TYPE:
            out[entrant_id] = price
    return out


def _selection(entrant: dict) -> str | None:
    side = entrant.get("home_away")
    if side in ("HOME", "AWAY"):
        return side.lower()
    name = entrant.get("name", "").strip().lower()
    if name in ("draw", "over", "under"):
        return name
    return None


def _classify(market: dict, selections: list[str | None]) -> str:
    """Map to the same generic market types Kambi uses (Match / Handicap / Over/Under)."""
    counts = Counter(selections)
    if counts == Counter({"over": 1, "under": 1}):
        return "Over/Under"
    # Exactly one home and one away (plus optional draw); excludes margin bands,
    # which tag every bucket as HOME or AWAY.
    if counts["home"] == 1 and counts["away"] == 1 and counts["draw"] <= 1 and counts[None] == 0:
        return "Handicap" if market.get("handicap") is not None else "Match"
    return "Other"


def _is_core(market: dict, market_type: str) -> bool:
    return market_type in CORE_MARKETS and bool(CORE_MARKET_NAME.match(market.get("name", "").strip()))


def _outcome_line(market: dict, selection: str | None) -> float | None:
    handicap = market.get("handicap")
    if handicap is None:
        return None
    # Entain stores a two-way line from the AWAY side's perspective: NBA
    # "Houston (1.30 fav) vs Dallas, handicap +8.5" means Dallas +8.5 /
    # Houston -8.5. Verified against H2H favourites in NBA and NHL markets.
    if selection == "home":
        return -handicap
    return handicap


def parse(payload: dict, bookmaker: str, sport: str, scraped_at: str, core_only: bool = False) -> Iterator[OddsRow]:
    """Turn an event-request or event-card payload into OddsRows."""
    events = payload.get("events") or {}
    entrants = payload.get("entrants") or {}
    prices = _prices_by_entrant(payload.get("prices") or {})

    participants: dict[str, dict[str, str]] = {}
    for p in (payload.get("event_participants") or {}).values():
        participants.setdefault(p["event_id"], {})[p.get("home_away", "")] = p["name"]

    for market in (payload.get("markets") or {}).values():
        event = events.get(market.get("event_id"))
        if not event:
            continue
        ents = [entrants[e] for e in market.get("entrant_ids", []) if e in entrants]
        selections = [_selection(e) for e in ents]
        market_type = _classify(market, selections)
        if core_only and not _is_core(market, market_type):
            continue

        is_open = market.get("market_status_id") == MARKET_STATUS_OPEN
        teams = participants.get(event["id"], {})
        for ent, sel in zip(ents, selections):
            price = prices.get(ent["id"])
            odds = _decimal_odds(price) if price else None
            if odds is None:
                continue
            yield OddsRow(
                scraped_at=scraped_at,
                bookmaker=bookmaker,
                sport=sport,
                league=(event.get("competition") or {}).get("name", ""),
                event_id=event["id"],
                event_name=event.get("name", ""),
                home_team=teams.get("HOME"),
                away_team=teams.get("AWAY"),
                start_time=event.get("advertised_start", ""),
                event_state=event.get("match_status", ""),
                market_id=market["id"],
                market_type=market_type,
                market_name=market.get("name", ""),
                line=_outcome_line(market, sel),
                outcome_id=ent["id"],
                outcome_label=ent.get("name", ""),
                selection=sel,
                participant=ent.get("name") if sel in ("home", "away") else None,
                odds_decimal=odds,
                status="OPEN" if is_open else "CLOSED",
                suspended=not is_open,
            )


def _resolve_sport(categories: list[dict], name: str) -> dict:
    key = name.strip().lower().replace("_", "-")
    for c in categories:
        if key in (c["slug"], c["category"].lower().replace("_", "-"), c["name"].lower()):
            return c
    raise SystemExit(f"Unknown sport '{name}'. Try --list-sports.")


def _matches_competition(event: dict, competitions: list[str] | None) -> bool:
    if not competitions:
        return True
    name = (event.get("competition") or {}).get("name", "").lower()
    return any(c.lower() == name for c in competitions)


def scrape(
    sports: list[str],
    brand: str = "ladbrokes",
    competitions: list[str] | None = None,
    event_cards: bool = False,
    core_only: bool = False,
    client: EntainClient | None = None,
) -> list[OddsRow]:
    client = client or EntainClient(brand)
    bookmaker = f"{brand}_au"
    categories = client.categories()
    rows: list[OddsRow] = []
    seen: set[str] = set()

    for sport_name in sports:
        cat = _resolve_sport(categories, sport_name)
        listing = client.event_request(cat["id"])
        events = {
            eid: e for eid, e in (listing.get("events") or {}).items()
            if _matches_competition(e, competitions)
        }
        scraped_at = utc_now_iso()

        if event_cards:
            # Head-to-head events only; outrights have no event card worth fetching.
            payloads = []
            for eid, e in events.items():
                if len(e.get("participant_ids") or []) != 2:
                    continue
                payloads.append(client.event_card(eid))
        else:
            listing["events"] = events
            payloads = [listing]

        before = len(rows)
        for payload in payloads:
            for row in parse(payload, bookmaker, cat["category"], scraped_at, core_only):
                if row.event_id not in events or row.outcome_id in seen:
                    continue
                seen.add(row.outcome_id)
                rows.append(row)
        log.info("%s: %d outcomes from %d events", cat["slug"], len(rows) - before, len(events))

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Ladbrokes AU / Neds odds to CSV.")
    parser.add_argument("sports", nargs="*", help="sport slugs, e.g. basketball, australian-rules, soccer")
    parser.add_argument("--brand", choices=BRANDS, default="ladbrokes")
    parser.add_argument("-c", "--competition", action="append", help="only this competition (repeatable), e.g. NBA")
    parser.add_argument("--event-cards", action="store_true", help="fetch every market per match (1 request per event)")
    parser.add_argument("--core-only", action="store_true", help="keep only Match / Handicap / Over/Under markets")
    parser.add_argument("-o", "--output", help="CSV path (default: data/<brand>_<timestamp>.csv)")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between requests (default 0.5)")
    parser.add_argument("--list-sports", action="store_true", help="print available sports and exit")
    parser.add_argument("--list-competitions", metavar="SPORT", help="print competitions for a sport and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    client = EntainClient(args.brand, delay=args.delay)

    if args.list_sports:
        for c in client.categories():
            print(f"{c['slug']:<24} {c['name']}")
        return

    if args.list_competitions:
        cat = _resolve_sport(client.categories(), args.list_competitions)
        events = client.event_request(cat["id"]).get("events") or {}
        counts = Counter((e.get("competition") or {}).get("name", "?") for e in events.values())
        for name, n in counts.most_common():
            print(f"{name:<48} {n}")
        return

    if not args.sports:
        parser.error("give at least one sport (or --list-sports)")

    rows = scrape(
        args.sports,
        brand=args.brand,
        competitions=args.competition,
        event_cards=args.event_cards,
        core_only=args.core_only,
        client=client,
    )
    output = args.output or f"data/{args.brand}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    n = write_csv(rows, output)
    log.info("Wrote %d rows to %s", n, output)


if __name__ == "__main__":
    main()
