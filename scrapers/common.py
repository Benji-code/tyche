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
from typing import Any, Iterable

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
