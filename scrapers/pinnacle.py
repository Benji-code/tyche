"""Pinnacle odds scraper (sharp reference).

Pinnacle's official API needs a funded account. Instead we read the guest API
that pinnacle.com's frontend uses, which needs no key:

    https://guest.api.arcadia.pinnacle.com/0.1/sports
    https://guest.api.arcadia.pinnacle.com/0.1/sports/{sport_id}/leagues?all=false
    https://guest.api.arcadia.pinnacle.com/0.1/sports/{sport_id}/matchups
    https://guest.api.arcadia.pinnacle.com/0.1/sports/{sport_id}/markets/straight

Two requests per sport cover every league. Prices are American odds; markets
are keyed by period (0 = full game / regulation for soccer, 1 = 1st half, ...).

Usage:
    python -m scrapers.pinnacle --list-sports
    python -m scrapers.pinnacle --list-leagues basketball
    python -m scrapers.pinnacle basketball -l NBA
    python -m scrapers.pinnacle soccer -l "England - Premier League" --core-only
    python -m scrapers.pinnacle hockey --alternates --periods 0 1
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Iterator

from .common import JsonClient, OddsRow, canonical_sport, utc_now_iso, write_csv

log = logging.getLogger(__name__)

BOOKMAKER = "pinnacle"
BASE_URL = "https://guest.api.arcadia.pinnacle.com/0.1"
HEADERS = {"Referer": "https://www.pinnacle.com/", "Origin": "https://www.pinnacle.com"}
SPORT_ALIASES = {
    "FOOTBALL": "AMERICAN_FOOTBALL",
    "HOCKEY": "ICE_HOCKEY",
    "AUSSIE_RULES": "AUSTRALIAN_RULES",
    "E_SPORTS": "ESPORTS",
}

# Pinnacle market type -> generic type shared with the other scrapers.
MARKET_TYPES = {
    "moneyline": ("Match", "Moneyline"),
    "spread": ("Handicap", "Spread"),
    "total": ("Over/Under", "Total"),
    "team_total": ("Team Total", "Team Total"),
}
CORE_TYPES = {"moneyline", "spread", "total"}


class PinnacleClient:
    def __init__(self, delay: float = 1.0):
        self.http = JsonClient(HEADERS, delay=delay)

    def get(self, path: str, params: dict | None = None):
        return self.http.get(f"{BASE_URL}/{path}", params)

    def sports(self) -> list[dict]:
        return self.get("sports")

    def leagues(self, sport_id: int) -> list[dict]:
        return self.get(f"sports/{sport_id}/leagues", {"all": "false"})

    def matchups(self, sport_id: int) -> list[dict]:
        return self.get(f"sports/{sport_id}/matchups", {"withSpecials": "false"})

    def markets(self, sport_id: int) -> list[dict]:
        return self.get(f"sports/{sport_id}/markets/straight", {"primaryOnly": "false", "withSpecials": "false"})


def american_to_decimal(price: float) -> float:
    if price > 0:
        return round(1 + price / 100, 4)
    return round(1 + 100 / abs(price), 4)


def _resolve_sport(sports: list[dict], name: str) -> dict:
    key = name.strip().lower().replace("_", " ").replace("-", " ")
    for s in sports:
        if key in (s["name"].lower(), canonical_sport(s["name"], SPORT_ALIASES).lower().replace("_", " ")):
            return s
    raise SystemExit(f"Unknown sport '{name}'. Try --list-sports.")


def _resolve_leagues(matchups: list[dict], wanted: list[str] | None) -> set[str] | None:
    """Map requested names to league names present. An exact (case-insensitive)
    match wins; otherwise fall back to substring, so 'NBA' doesn't pull in 'WNBA'
    but 'Premier League' still finds 'England - Premier League'."""
    if not wanted:
        return None
    available = {m["league"]["name"] for m in matchups if m.get("league")}
    resolved: set[str] = set()
    for w in wanted:
        exact = {n for n in available if n.lower() == w.lower()}
        resolved |= exact or {n for n in available if w.lower() in n.lower()}
    return resolved


def parse(
    matchups: list[dict],
    markets: list[dict],
    scraped_at: str,
    leagues: list[str] | None = None,
    periods: set[int] = frozenset({0}),
    alternates: bool = False,
    core_only: bool = False,
) -> Iterator[OddsRow]:
    league_names = _resolve_leagues(matchups, leagues)
    # Only top-level head-to-head matchups; children are corners/bookings/props.
    games = {
        m["id"]: m
        for m in matchups
        if m.get("type") == "matchup"
        and not m.get("parentId")
        and m.get("units", "Regular") == "Regular"
        and (league_names is None or m["league"]["name"] in league_names)
    }

    for mk in markets:
        game = games.get(mk.get("matchupId"))
        if game is None or mk.get("period") not in periods:
            continue
        if mk.get("isAlternate") and not alternates:
            continue
        mtype = mk.get("type")
        if mtype not in MARKET_TYPES or (core_only and mtype not in CORE_TYPES):
            continue

        teams = {p["alignment"]: p["name"] for p in game.get("participants", [])}
        generic_type, label = MARKET_TYPES[mtype]
        if mtype == "team_total":
            label = f"Team Total {teams.get(mk.get('side'), mk.get('side', ''))}"
        if mk.get("isAlternate"):
            label = f"{label} (alt)"
        if mk["period"] != 0:
            label = f"{label} (period {mk['period']})"

        market_id = f"{game['id']}:{mk['key']}"
        status = mk.get("status", "open")
        for p in mk.get("prices") or []:
            if p.get("price") is None:
                continue
            designation = p.get("designation")
            if mtype == "team_total":
                participant = teams.get(mk.get("side"))
            else:
                participant = teams.get(designation)
            yield OddsRow(
                scraped_at=scraped_at,
                bookmaker=BOOKMAKER,
                sport=canonical_sport(game["league"]["sport"]["name"], SPORT_ALIASES),
                league=game["league"]["name"],
                event_id=str(game["id"]),
                event_name=f"{teams.get('home', '?')} vs {teams.get('away', '?')}",
                home_team=teams.get("home"),
                away_team=teams.get("away"),
                start_time=game.get("startTime", ""),
                event_state="LIVE" if game.get("isLive") else game.get("status", ""),
                market_id=market_id,
                market_type=generic_type,
                market_name=label,
                line=p.get("points"),
                outcome_id=f"{market_id}:{designation}",
                outcome_label=participant if designation in ("home", "away") else str(designation).title(),
                selection=designation,
                participant=participant,
                odds_decimal=american_to_decimal(p["price"]),
                status=status.upper(),
                suspended=status != "open",
            )


def scrape(
    sports: list[str],
    leagues: list[str] | None = None,
    periods: set[int] = frozenset({0}),
    alternates: bool = False,
    core_only: bool = False,
    include_live: bool = True,
    client: PinnacleClient | None = None,
) -> list[OddsRow]:
    client = client or PinnacleClient()
    all_sports = client.sports()
    rows: list[OddsRow] = []
    for name in sports:
        sport = _resolve_sport(all_sports, name)
        matchups = client.matchups(sport["id"])
        markets = client.markets(sport["id"])
        scraped_at = utc_now_iso()
        before = len(rows)
        for row in parse(matchups, markets, scraped_at, leagues, periods, alternates, core_only):
            if not include_live and row.event_state == "LIVE":
                continue
            rows.append(row)
        log.info("%s: %d outcomes", sport["name"], len(rows) - before)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Pinnacle odds to CSV.")
    parser.add_argument("sports", nargs="*", help="sport names, e.g. basketball, soccer, hockey")
    parser.add_argument("-l", "--league", action="append", help="league name or substring (repeatable), e.g. NBA")
    parser.add_argument("--periods", type=int, nargs="+", default=[0], help="periods to keep (default 0 = full game)")
    parser.add_argument("--alternates", action="store_true", help="include alternate spreads / totals")
    parser.add_argument("--core-only", action="store_true", help="moneyline / spread / total only (drop team totals)")
    parser.add_argument("--prematch-only", action="store_true", help="skip events already in play")
    parser.add_argument("-o", "--output", help="CSV path (default: data/pinnacle_<timestamp>.csv)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1.0)")
    parser.add_argument("--list-sports", action="store_true", help="print sports with open matchups and exit")
    parser.add_argument("--list-leagues", metavar="SPORT", help="print leagues for a sport and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    client = PinnacleClient(delay=args.delay)

    if args.list_sports:
        for s in sorted(client.sports(), key=lambda s: -s.get("matchupCount", 0)):
            if s.get("matchupCount"):
                print(f"{s['name']:<24} {s['matchupCount']}")
        return

    if args.list_leagues:
        sport = _resolve_sport(client.sports(), args.list_leagues)
        for lg in sorted(client.leagues(sport["id"]), key=lambda l: -l.get("matchupCount", 0)):
            print(f"{lg['name']:<48} {lg.get('matchupCount', 0)}")
        return

    if not args.sports:
        parser.error("give at least one sport (or --list-sports)")

    rows = scrape(
        args.sports,
        leagues=args.league,
        periods=set(args.periods),
        alternates=args.alternates,
        core_only=args.core_only,
        include_live=not args.prematch_only,
        client=client,
    )
    output = args.output or f"data/pinnacle_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    n = write_csv(rows, output)
    log.info("Wrote %d rows to %s", n, output)


if __name__ == "__main__":
    main()
