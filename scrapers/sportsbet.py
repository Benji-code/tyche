"""Sportsbet odds scraper.

The site's frontend reads two JSON endpoints:
    /apigw/sportsbook-sports/Sportsbook/Sports/NavHierarchy?classId=<id>   competition tree
    /apigw/sportsbook-sports/Sportsbook/Sports/Competitions/<id>?includeTopMarkets=true
        -> every event in a competition with its top markets (Win-Draw-Win,
           Over/Under 2.5 Goals, Match Betting for tennis, ...)

One request per competition.
"""

from __future__ import annotations

import re

from .common import CompetitionFilter, JsonClient, OddsRow, accept_all, iso_utc, market_rows, side_of, utc_now_iso

BOOKMAKER = "sportsbet"
BASE = "https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports"
CLASS_IDS = {"soccer": 29, "tennis": 13}
RESULT_TYPES = {"H": "home", "D": "draw", "A": "away"}
TOTAL_GOALS = re.compile(r"^Over/Under ([\d.]+) Goals$")


class SportsbetClient:
    def __init__(self, delay: float = 0.4):
        self.http = JsonClient({"Referer": "https://www.sportsbet.com.au/"}, delay=delay)

    def competitions(self, sport: str) -> list[tuple[int, str, str | None]]:
        """(competition id, name, region) under a sport class."""
        class_id = CLASS_IDS[sport]
        nav = self.http.get(f"{BASE}/NavHierarchy", {"classId": class_id})
        out: list[tuple[int, str, str | None]] = []

        def walk(items: list[dict], region: str | None, inside: bool) -> None:
            for it in items or []:
                is_class = it.get("idType") == "class"
                if is_class and it.get("id") != class_id:
                    continue
                here = inside or is_class
                if here and it.get("idType") == "competition":
                    out.append((it["id"], it["name"], region))
                sub_region = it["name"] if here and it.get("idType") == "CONST" else region
                walk(it.get("navItems") or [], sub_region, here)

        walk(nav.get("navItems") or [], None, False)
        # Competitions appear under both their region and "Futures/Outrights"; keep one.
        unique: dict[int, tuple[int, str, str | None]] = {}
        for comp in out:
            if comp[0] not in unique or (unique[comp[0]][2] or "").startswith("Futures"):
                unique[comp[0]] = comp
        return list(unique.values())

    def competition(self, comp_id: int) -> dict:
        return self.http.get(f"{BASE}/Competitions/{comp_id}", {"displayType": "default", "includeTopMarkets": "true"})


def _parse_event(ev: dict, sport: str, league: str, scraped_at: str) -> list[OddsRow]:
    home, away = ev.get("participant1"), ev.get("participant2")
    base = dict(
        scraped_at=scraped_at, bookmaker=BOOKMAKER, sport=sport.upper(), league=league,
        event_id=ev["id"], home=home, away=away, start_time=iso_utc(ev.get("startTime")),
        event_state="LIVE" if ev.get("hasBIRStarted") else "NOT_STARTED",
    )
    rows: list[OddsRow] = []
    for m in ev.get("marketList") or []:
        name = m.get("name", "")
        status = "OPEN" if m.get("statusCode") == "A" else "SUSPENDED"
        sels = m.get("selections") or []
        total = TOTAL_GOALS.match(name)
        if sport == "soccer" and name == "Win-Draw-Win":
            outcomes = [(s["id"], s["name"], RESULT_TYPES.get(s.get("resultType")), s.get("price", {}).get("winPrice"), None)
                        for s in sels]
            rows += market_rows(**base, market_id=m["id"], market_type="Match", market_name=name, outcomes=outcomes, status=status)
        elif sport == "soccer" and total:
            line = float(total.group(1))
            outcomes = [(s["id"], s["name"], "over" if s["name"].startswith("Over") else "under",
                         s.get("price", {}).get("winPrice"), line) for s in sels]
            rows += market_rows(**base, market_id=m["id"], market_type="Over/Under", market_name=name, outcomes=outcomes, status=status)
        elif sport == "tennis" and name in ("Match Betting", "Head to Head"):
            outcomes = [(s["id"], s["name"], side_of(s["name"], home, away), s.get("price", {}).get("winPrice"), None)
                        for s in sels]
            rows += market_rows(**base, market_id=m["id"], market_type="Match", market_name=name, outcomes=outcomes, status=status)
    return rows


def fetch(sport: str, competition_filter: CompetitionFilter = accept_all, client: SportsbetClient | None = None) -> list[OddsRow]:
    client = client or SportsbetClient()
    rows: list[OddsRow] = []
    for comp_id, name, region in client.competitions(sport):
        label = competition_filter(name, region)
        if not label:
            continue
        scraped_at = utc_now_iso()
        for ev in client.competition(comp_id).get("events") or []:
            if not ev.get("isFuture"):
                rows += _parse_event(ev, sport, label, scraped_at)
    return rows
