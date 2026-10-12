"""Palmerbet odds scraper.

    GET https://fixture.palmerbet.online/fixtures/sports/<sport id>?sportType=<Type>       competition tree
    GET https://fixture.palmerbet.online/fixtures/sports/<competition id>/matches?sportType=<Type>
        -> matches with home / away (/ draw) win prices inline
"""

from __future__ import annotations

from .common import CompetitionFilter, JsonClient, OddsRow, accept_all, iso_utc, market_rows, utc_now_iso

BOOKMAKER = "palmerbet"
BASE = "https://fixture.palmerbet.online/fixtures/sports"
SPORTS = {
    "soccer": ("b4073512-cdd5-4953-950f-3f7ad31fa955", "Soccer"),
    "tennis": ("9d6bbedd-0b09-4031-9884-e264499a2aa5", "Tennis"),
}


class PalmerbetClient:
    def __init__(self, delay: float = 0.4):
        self.http = JsonClient({"Origin": "https://www.palmerbet.com", "Referer": "https://www.palmerbet.com/"}, delay=delay)

    def competitions(self, sport: str) -> list[tuple[str, str]]:
        sport_id, sport_type = SPORTS[sport]
        out: list[tuple[str, str]] = []

        def walk(item_id: str, depth: int) -> None:
            data = self.http.get(f"{BASE}/{item_id}", {"sportType": sport_type})
            for sub in data.get("sportItem", {}).get("subItems") or []:
                if sub.get("isEventGroup"):
                    out.append((sub["id"], sub["title"]))
                elif depth < 2:
                    walk(sub["id"], depth + 1)

        walk(sport_id, 0)
        return out

    def matches(self, sport: str, comp_id: str) -> list[dict]:
        return self.http.get(f"{BASE}/{comp_id}/matches", {"sportType": SPORTS[sport][1]}).get("matches") or []


def fetch(sport: str, competition_filter: CompetitionFilter = accept_all, client: PalmerbetClient | None = None) -> list[OddsRow]:
    client = client or PalmerbetClient()
    rows: list[OddsRow] = []
    for comp_id, title in client.competitions(sport):
        label = competition_filter(title, None)
        if not label:
            continue
        scraped_at = utc_now_iso()
        for m in client.matches(sport, comp_id):
            home_t, away_t = m.get("homeTeam") or {}, m.get("awayTeam") or {}
            home, away = home_t.get("title"), away_t.get("title")
            parts = [("home", home_t.get("win"), home), ("away", away_t.get("win"), away)]
            if m.get("draw"):
                parts.insert(1, ("draw", m["draw"], "Draw"))
            market_id = (home_t.get("win") or {}).get("marketId")
            if not market_id:
                continue
            rows += market_rows(
                scraped_at=scraped_at, bookmaker=BOOKMAKER, sport=sport.upper(), league=label,
                event_id=m["eventId"], home=home, away=away, start_time=iso_utc(m.get("startTime")),
                market_id=market_id, market_type="Match", market_name=(home_t.get("win") or {}).get("title", "Match Result"),
                outcomes=[((o or {}).get("outcomeId"), label_, sel, (o or {}).get("price"), None) for sel, o, label_ in parts],
                event_state="NOT_STARTED" if m.get("status") == "NotStarted" else str(m.get("status", "")).upper(),
            )
    return rows
