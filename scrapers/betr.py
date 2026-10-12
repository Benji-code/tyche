"""Betr odds scraper (also covers BlueBet and TopSport, which now redirect to Betr).

Betr's frontend still calls BlueBet's API:
    GET https://web20-api.bluebet.com.au/MasterCategory?EventTypeId=<id>&WithLevelledMarkets=true
        -> every competition in a sport, each match with its Match Result prices

One request per sport.
"""

from __future__ import annotations

from collections import defaultdict

from .common import CompetitionFilter, JsonClient, OddsRow, accept_all, iso_utc, market_rows, side_of, split_teams, utc_now_iso

BOOKMAKER = "betr"
BASE = "https://web20-api.bluebet.com.au"
EVENT_TYPES = {"soccer": 100, "tennis": 104}


class BetrClient:
    def __init__(self, delay: float = 0.4):
        self.http = JsonClient({"Origin": "https://www.betr.com.au", "Referer": "https://www.betr.com.au/"}, delay=delay)

    def sport(self, sport: str) -> dict:
        return self.http.get(f"{BASE}/MasterCategory", {"EventTypeId": EVENT_TYPES[sport], "WithLevelledMarkets": "true"})


def fetch(sport: str, competition_filter: CompetitionFilter = accept_all, client: BetrClient | None = None) -> list[OddsRow]:
    client = client or BetrClient()
    data = client.sport(sport)
    scraped_at = utc_now_iso()
    rows: list[OddsRow] = []
    for master in data.get("MasterCategories") or []:
        for cat in master.get("Categories") or []:
            label = competition_filter(cat["CategoryName"], master.get("MasterCategory"))
            if not label:
                continue
            for me in cat.get("MasterEvents") or []:
                if me.get("MasterEventClassName") not in ("Match", "Matches") or not me.get("Markets"):
                    continue
                home, away = split_teams(me["MasterEventName"])
                by_market: dict[int, list[dict]] = defaultdict(list)
                for o in me["Markets"]:
                    if o.get("EventName", "").startswith("Match Result"):
                        by_market[o["EventId"]].append(o)
                for market_id, outcomes in by_market.items():
                    rows += market_rows(
                        scraped_at=scraped_at, bookmaker=BOOKMAKER, sport=sport.upper(), league=label,
                        event_id=me["MasterEventId"], home=home, away=away,
                        start_time=iso_utc(me.get("MinAdvertisedStartTime")),
                        market_id=market_id, market_type="Match", market_name="Match Result",
                        outcomes=[(o["FixedMarketId"], o["OutcomeName"], side_of(o["OutcomeName"], home, away), o.get("Price"), None)
                                  for o in outcomes],
                        event_state="LIVE" if me.get("IsLive") else "NOT_STARTED",
                    )
    return rows
