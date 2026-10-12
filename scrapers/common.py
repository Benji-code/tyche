"""Shared output schema for all bookmaker scrapers.

Every scraper emits OddsRow records (one row per outcome) so downstream
devigging / EV code can treat soft and sharp books identically. Group rows by
(bookmaker, event_id, market_id) to reconstruct a complete market.
"""

from __future__ import annotations

import csv
import logging
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

log = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


@dataclass
class OddsRow:
    scraped_at: str        # ISO-8601 UTC timestamp of the fetch
    bookmaker: str         # e.g. "unibet_au"
    sport: str             # e.g. "BASKETBALL"
    league: str            # e.g. "NBA"
    event_id: str          # bookmaker's own event id
    event_name: str
    home_team: str | None
    away_team: str | None
    start_time: str        # ISO-8601 UTC
    event_state: str       # NOT_STARTED / STARTED / ...
    market_id: str         # bookmaker's id for this market instance
    market_type: str       # generic type, e.g. "Match", "Handicap", "Over/Under"
    market_name: str       # specific market, e.g. "Moneyline - Including Overtime"
    line: float | None     # handicap / total line, None for head-to-head
    outcome_id: str
    outcome_label: str     # raw label from the book
    selection: str | None  # normalised: home / draw / away / over / under / None
    participant: str | None
    odds_decimal: float
    status: str            # OPEN / SUSPENDED / ...
    suspended: bool        # market-level suspension flag
    liquidity: float | None = None  # exchange matched volume (Betfair); None elsewhere


FIELDNAMES = [f.name for f in fields(OddsRow)]


class JsonClient:
    """requests.Session wrapper with a minimum gap between requests and
    exponential backoff on 429 / 5xx."""

    def __init__(
        self,
        headers: dict[str, str],
        delay: float = 1.0,
        max_retries: int = 3,
        timeout: float = 15.0,
    ):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json", **headers})
        self.delay = delay
        self.max_retries = max_retries
        self.timeout = timeout
        self._last_request = 0.0

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        for attempt in range(1, self.max_retries + 1):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                backoff = 2 ** attempt
                log.warning("%s -> HTTP %s, retrying in %ss", url, resp.status_code, backoff)
                time.sleep(backoff)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        raise RuntimeError(f"Giving up on {url} after {self.max_retries} attempts")

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", url, params=params)

    def post(self, url: str, json: Any) -> Any:
        return self.request("POST", url, json=json)


# Sport pipelines pass scrapers a filter: (competition name, region or None) ->
# the label to store in OddsRow.league, or None to skip that competition. This
# keeps "which leagues/tours do we want" in one place per sport, not per book.
CompetitionFilter = Callable[[str, "str | None"], "str | None"]


def accept_all(name: str, region: str | None = None) -> str:
    return name


def market_rows(
    *,
    scraped_at: str,
    bookmaker: str,
    sport: str,
    league: str,
    event_id: Any,
    home: str | None,
    away: str | None,
    start_time: str,
    market_id: Any,
    market_type: str,
    market_name: str,
    outcomes: Iterable[tuple[Any, str, str | None, float | None, float | None]],
    event_state: str = "NOT_STARTED",
    status: str = "OPEN",
    liquidity: float | None = None,
) -> list[OddsRow]:
    """Build the rows for one market. outcomes: (outcome_id, label, selection, odds, line).
    Outcomes without a usable price are dropped."""
    rows = []
    for outcome_id, label, selection, odds, line in outcomes:
        if not odds or odds <= 1:
            continue
        rows.append(OddsRow(
            scraped_at=scraped_at,
            bookmaker=bookmaker,
            sport=sport,
            league=league,
            event_id=str(event_id),
            event_name=f"{home} v {away}" if home and away else "",
            home_team=home,
            away_team=away,
            start_time=start_time,
            event_state=event_state,
            market_id=str(market_id),
            market_type=market_type,
            market_name=market_name,
            line=line,
            outcome_id=str(outcome_id),
            outcome_label=label,
            selection=selection,
            participant=label if selection in ("home", "away") else None,
            odds_decimal=round(float(odds), 4),
            status=status,
            suspended=status != "OPEN",
            liquidity=liquidity,
        ))
    return rows


def side_of(name: str, home: str | None, away: str | None) -> str | None:
    """'home' / 'away' / 'draw' for an outcome label in a head-to-head market."""
    n = name.strip().lower()
    if n in ("draw", "the draw", "x", "tie"):
        return "draw"
    if home and n == home.strip().lower():
        return "home"
    if away and n == away.strip().lower():
        return "away"
    return None


def split_teams(event_name: str) -> tuple[str | None, str | None]:
    for sep in (" v ", " vs ", " - ", " @ "):
        if sep in event_name:
            home, away = event_name.split(sep, 1)
            return (away.strip(), home.strip()) if sep == " @ " else (home.strip(), away.strip())
    return None, None


def iso_utc(value: Any) -> str:
    """Epoch seconds / ms or ISO string -> ISO-8601 UTC."""
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
    return str(value).replace(".0000000Z", "Z")


def canonical_sport(name: str, aliases: dict[str, str] | None = None) -> str:
    """Normalise a sport name to UPPER_SNAKE (Ladbrokes' enum is the canonical set:
    SOCCER, AMERICAN_FOOTBALL, ICE_HOCKEY, ...). Aliases are per-bookmaker because
    the same word differs: Unibet's FOOTBALL is soccer, Pinnacle's is American."""
    key = name.strip().upper().replace(" ", "_").replace("-", "_")
    return (aliases or {}).get(key, key)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_csv(rows: Iterable[OddsRow], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
            n += 1
    return n
