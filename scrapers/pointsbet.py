"""PointsBet AU odds scraper.

    GET https://api.au.pointsbet.com/api/v2/sports/<sport>/competitions
    GET https://api.au.pointsbet.com/api/v2/competitions/<key>/events/featured?includeLive=false
        -> events with their featured "Match Result" market

One request per competition. Only the match result market is in the featured
payload; totals would need one request per event.
"""

from __future__ import annotations

from .common import CompetitionFilter, JsonClient, OddsRow, accept_all, iso_utc, market_rows, side_of, utc_now_iso

BOOKMAKER = "pointsbet"
BASE = "https://api.au.pointsbet.com/api/v2"
SIDES = {"Home": "home", "Away": "away", "Draw": "draw"}


class PointsBetClient:
    def __init__(self, delay: float = 0.4):
        self.http = JsonClient({"Origin": "https://pointsbet.com.au", "Referer": "https://pointsbet.com.au/"}, delay=delay)

    def competitions(self, sport: str) -> list[tuple[str, str, str | None]]:
        data = self.http.get(f"{BASE}/sports/{sport}/competitions")
        seen, out = set(), []
        for locale in data.get("locales") or []:
            region = None if locale.get("key") == "featured" else locale.get("name")
            for c in locale.get("competitions") or []:
                if c["key"] not in seen:
                    seen.add(c["key"])
                    out.append((c["key"], c["name"], region))
        return out

    def events(self, comp_key: str) -> list[dict]:
        return self.http.get(f"{BASE}/competitions/{comp_key}/events/featured", {"includeLive": "false"}).get("events") or []


def _parse_event(ev: dict, sport: str, league: str, scraped_at: str) -> list[OddsRow]:
    home, away = ev.get("homeTeam"), ev.get("awayTeam")
    markets = (ev.get("specialFixedOddsMarkets") or []) + (ev.get("fixedOddsMarkets") or [])
    for m in markets:
        if m.get("eventClass") != "Match Result":
            continue
        outcomes = []
        for o in m.get("outcomes") or []:
            sel = SIDES.get(o.get("side")) or side_of(o["name"], home, away)
            outcomes.append((o.get("fixedMarketId") or o["key"], o["name"], sel,
                             o.get("price") if o.get("isOpenForBetting", True) else None, None))
        return market_rows(
            scraped_at=scraped_at, bookmaker=BOOKMAKER, sport=sport.upper(), league=league,
            event_id=ev["key"], home=home, away=away, start_time=iso_utc(ev.get("startsAt")),
            market_id=m["key"], market_type="Match", market_name="Match Result", outcomes=outcomes,
            event_state="LIVE" if ev.get("isLive") else "NOT_STARTED",
        )
    return []


def fetch(sport: str, competition_filter: CompetitionFilter = accept_all, client: PointsBetClient | None = None) -> list[OddsRow]:
    client = client or PointsBetClient()
    rows: list[OddsRow] = []
    for key, name, region in client.competitions(sport):
        label = competition_filter(name, region)
        if not label:
            continue
        scraped_at = utc_now_iso()
        for ev in client.events(key):
            rows += _parse_event(ev, sport, label, scraped_at)
    return rows
