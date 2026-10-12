"""Betfair Exchange AU scraper (sharp reference).

Uses the anonymous read-only endpoints behind betfair.com.au (prices are
delayed a few seconds without a login, which is fine for a reference):

    POST https://scan-inbf.betfair.com.au/www/sports/navigation/facet/v1/search
        -> competitions / events / market ids
    GET  https://ero.betfair.com.au/www/sports/exchange/readonly/v1/bymarket?marketIds=...
        -> best back / lay prices and matched volume

odds_decimal is the back/lay midpoint (averaged in probability space), which is
the exchange's estimate of the fair price before commission. Runners whose
spread is too wide get no price, so their market drops out. liquidity = the
market's total matched volume in AUD.
"""

from __future__ import annotations

import re

import requests

from .common import CompetitionFilter, JsonClient, OddsRow, accept_all, market_rows, side_of, split_teams, utc_now_iso

BOOKMAKER = "betfair"
SEARCH_URL = "https://scan-inbf.betfair.com.au/www/sports/navigation/facet/v1/search"
PRICES_URL = "https://ero.betfair.com.au/www/sports/exchange/readonly/v1/bymarket"
EVENT_TYPES = {"soccer": 1, "tennis": 2}
MARKET_TYPES = {
    "soccer": ["MATCH_ODDS", "OVER_UNDER_15", "OVER_UNDER_25", "OVER_UNDER_35"],
    "tennis": ["MATCH_ODDS"],
}
MAX_SPREAD = 1.10  # lay / back above this (10%) is too wide to trust the midpoint
BATCH = 20
TOTAL_GOALS = re.compile(r"^(Over|Under) ([\d.]+) Goals$")


class BetfairClient:
    def __init__(self, delay: float = 0.3):
        self.http = JsonClient(
            {"Content-Type": "application/json", "Origin": "https://www.betfair.com.au", "Referer": "https://www.betfair.com.au/"},
            delay=delay,
        )

    def _search(self, sport: str, facets: list[dict], competition_ids: list[int] | None = None) -> dict:
        flt = {
            "marketBettingTypes": ["ODDS"],
            "productTypes": ["EXCHANGE"],
            "marketTypeCodes": MARKET_TYPES[sport],
            "selectBy": "FIRST_TO_START_AZ",
            "contentGroup": {"language": "en", "regionCode": "ASIA"},
            "turnInPlayEnabled": True,
            "maxResults": 0,
            "eventTypeIds": [EVENT_TYPES[sport]],
        }
        if competition_ids:
            flt["competitionIds"] = competition_ids
        body = {"filter": flt, "facets": facets, "currencyCode": "AUD", "locale": "en_GB"}
        return self.http.post(f"{SEARCH_URL}?alt=json", body)

    def competitions(self, sport: str) -> list[tuple[int, str, str | None]]:
        data = self._search(sport, [{"type": "COMPETITION", "maxValues": 1000, "skipValues": 0, "applyNextTo": 0}])
        comps = data.get("attachments", {}).get("competitions", {}).values()
        return [(c["competitionId"], c["name"], c.get("region")) for c in comps]

    def prices(self, market_ids: list[str]) -> list[dict]:
        nodes: list[dict] = []
        for i in range(0, len(market_ids), BATCH):
            nodes += self._prices_batch(market_ids[i:i + BATCH])
        return nodes

    def _prices_batch(self, ids: list[str]) -> list[dict]:
        # The endpoint rejects requests over a data-weight limit with a 400; halve and retry.
        try:
            data = self.http.get(PRICES_URL, {
                "alt": "json", "currencyCode": "AUD", "locale": "en", "marketIds": ",".join(ids),
                "types": "MARKET_STATE,MARKET_DESCRIPTION,EVENT,RUNNER_DESCRIPTION,RUNNER_STATE,RUNNER_EXCHANGE_PRICES_BEST",
            })
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 400 or len(ids) == 1:
                raise
            mid = len(ids) // 2
            return self._prices_batch(ids[:mid]) + self._prices_batch(ids[mid:])
        return [n for et in data.get("eventTypes") or [] for n in et.get("eventNodes") or []]


def _midpoint(runner: dict) -> float | None:
    ex = runner.get("exchange") or {}
    back = (ex.get("availableToBack") or [{}])[0].get("price")
    lay = (ex.get("availableToLay") or [{}])[0].get("price")
    if not back or not lay or lay / back > MAX_SPREAD:
        return None
    return 1 / ((1 / back + 1 / lay) / 2)


def fetch(sport: str, competition_filter: CompetitionFilter = accept_all, client: BetfairClient | None = None) -> list[OddsRow]:
    client = client or BetfairClient()
    labels: dict[int, str] = {}
    for comp_id, name, region in client.competitions(sport):
        label = competition_filter(name, region)
        if label:
            labels[comp_id] = label
    if not labels:
        return []

    # Market -> competition comes from a second search per competition batch.
    market_comp: dict[str, int] = {}
    comp_ids = list(labels)
    for i in range(0, len(comp_ids), 50):
        facets = [{"type": "MARKET", "maxValues": 2000, "skipValues": 0, "applyNextTo": 0}]
        data = client._search(sport, facets, comp_ids[i:i + 50])
        for mid, m in data.get("attachments", {}).get("markets", {}).items():
            market_comp[mid] = m.get("competitionId")

    scraped_at = utc_now_iso()
    rows: list[OddsRow] = []
    for node in client.prices(list(market_comp)):
        event = node.get("event") or {}
        home, away = split_teams(event.get("eventName", ""))
        for m in node.get("marketNodes") or []:
            state, desc = m.get("state") or {}, m.get("description") or {}
            if state.get("status") != "OPEN":
                continue
            mtype = desc.get("marketType", "")
            runners = m.get("runners") or []
            outcomes = []
            for r in runners:
                name = (r.get("description") or {}).get("runnerName", "")
                total = TOTAL_GOALS.match(name)
                if mtype == "MATCH_ODDS" and sport == "tennis":
                    # Event names use surnames only; runner names are full, so use listing order.
                    sel = "home" if (r.get("state") or {}).get("sortPriority") == 1 else "away"
                elif mtype == "MATCH_ODDS":
                    sel = side_of(name, home, away)
                elif total:
                    sel = total.group(1).lower()
                else:
                    sel = None
                outcomes.append((r["selectionId"], name, sel, _midpoint(r), float(total.group(2)) if total else None))
            if any(o[3] is None for o in outcomes):
                continue  # incomplete market: can't derive a fair book
            if mtype == "MATCH_ODDS" and sport == "tennis" and len(runners) == 2:
                names = [o[1] for o in outcomes]
                home, away = names[0], names[1]
            is_total = mtype.startswith("OVER_UNDER")
            rows += market_rows(
                scraped_at=scraped_at, bookmaker=BOOKMAKER, sport=sport.upper(),
                league=labels.get(market_comp.get(m["marketId"]), ""),
                event_id=node.get("eventId"), home=home, away=away,
                start_time=desc.get("marketTime", ""),
                market_id=m["marketId"],
                market_type="Over/Under" if is_total else "Match",
                market_name=desc.get("marketName", ""),
                outcomes=outcomes,
                event_state="LIVE" if state.get("inplay") else "NOT_STARTED",
                liquidity=state.get("totalMatched"),
            )
    return rows
