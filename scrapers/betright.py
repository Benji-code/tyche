"""BetRight odds scraper.

    GET https://next-api.betright.com.au/Sports/MasterCategory?eventTypeId=<id>   competitions by country
    GET https://next-api.betright.com.au/Sports/Category?categoryId=<id>           matches with Match Result prices

BetRight names competitions without the country ("Premier League" under
"England"), so the filter gets the country as the region.
"""

from __future__ import annotations

from collections import defaultdict

from .common import CompetitionFilter, JsonClient, OddsRow, accept_all, iso_utc, market_rows, side_of, split_teams, utc_now_iso

BOOKMAKER = "betright"
BASE = "https://next-api.betright.com.au/Sports"
EVENT_TYPES = {"soccer": 100, "tennis": 104}


class BetRightClient:
    def __init__(self, delay: float = 0.4):
        self.http = JsonClient({"Origin": "https://betright.com.au", "Referer": "https://betright.com.au/"}, delay=delay)

    def competitions(self, sport: str) -> list[tuple[int, str, str | None]]:
        data = self.http.get(f"{BASE}/MasterCategory", {"eventTypeId": EVENT_TYPES[sport]})
        return [(c["categoryId"], c["categoryName"], m.get("masterCategory"))
                for m in data.get("masterCategories") or [] for c in m.get("categories") or []]

    def category(self, category_id: int) -> list[dict]:
        data = self.http.get(f"{BASE}/Category", {"categoryId": category_id})
        return [me for m in data.get("masterCategories") or [] for c in m.get("categories") or []
                for me in c.get("masterEvents") or []]


def fetch(sport: str, competition_filter: CompetitionFilter = accept_all, client: BetRightClient | None = None) -> list[OddsRow]:
    client = client or BetRightClient()
    rows: list[OddsRow] = []
    for cat_id, name, region in client.competitions(sport):
        label = competition_filter(name, region)
        if not label:
            continue
        scraped_at = utc_now_iso()
        for me in client.category(cat_id):
            if not me.get("markets") or "match" not in (me.get("masterEventClassName") or "").lower():
                continue
            home, away = split_teams(me["masterEventName"])
            by_market: dict[int, list[dict]] = defaultdict(list)
            for o in me["markets"]:
                if o.get("eventName") == "Match Result":
                    by_market[o["eventId"]].append(o)
            for market_id, outcomes in by_market.items():
                rows += market_rows(
                    scraped_at=scraped_at, bookmaker=BOOKMAKER, sport=sport.upper(), league=label,
                    event_id=me["masterEventId"], home=home, away=away,
                    start_time=iso_utc(me.get("minAdvertisedStartTimeUtc")),
                    market_id=market_id, market_type="Match", market_name="Match Result",
                    outcomes=[(o["fixedMarketId"], o["outcomeName"], side_of(o["outcomeName"], home, away), o.get("price"), None)
                              for o in outcomes],
                )
    return rows
