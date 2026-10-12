"""Match soccer prices across books into engine Markets.

Rows arrive with OddsRow.league already set to our league slug (the scrapers
apply soccer.mappings.league_filter). Here we resolve team names, check
kickoffs agree, and group prices into 1X2 / TOTAL markets.
"""

from __future__ import annotations

import csv
import difflib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from engine.markets import Market
from scrapers.common import OddsRow
from scrapers.registry import SHARP_BOOKS, book_of

from .mappings import MARKET_SELECTIONS, MARKETS, TEAMS

NAMING_BOOK = "pinnacle"  # canonical team spellings come from here
KICKOFF_TOLERANCE = timedelta(hours=2)

_STRIP_TOKENS = {
    "fc", "afc", "cf", "sc", "ac", "as", "us", "ss", "ssc", "ud", "cd", "sd", "rc",
    "fk", "sk", "sv", "bk", "vfb", "vfl", "tsg", "fsv", "club", "calcio", "de", "the",
}
# Letters NFKD doesn't decompose to ASCII (Turkish dotless i, Scandinavian ø, ...).
_TRANSLITERATE = str.maketrans({"ı": "i", "İ": "I", "ø": "o", "Ø": "O", "ß": "ss", "æ": "ae", "đ": "d", "ł": "l"})


def normalise(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.translate(_TRANSLITERATE)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(t for t in s.split() if t not in _STRIP_TOKENS and not (len(t) == 1 and t.isdigit()))


class TeamResolver:
    """Maps (book, raw team name) -> canonical key using TEAMS + normalise()."""

    def __init__(self, teams: dict[str, dict[str, str | list[str]]] = TEAMS):
        self.alias: dict[tuple[str, str], str] = {}
        self.display: dict[str, str] = {}
        for canonical, per_book in teams.items():
            key = normalise(canonical)
            self.display[key] = canonical
            for book, names in per_book.items():
                for n in [names] if isinstance(names, str) else names:
                    self.alias[(book, normalise(n))] = key

    def key(self, book: str, name: str) -> str:
        n = normalise(name)
        return self.alias.get((book, n), n)

    def name(self, key: str, fallback: str) -> str:
        return self.display.get(key, fallback)


@dataclass
class Event:
    league: str
    home: str
    away: str
    names: dict[str, tuple[str, str]] = field(default_factory=dict)  # book -> raw (home, away)
    start: dict[str, datetime] = field(default_factory=dict)  # book -> kickoff


@dataclass
class Matched:
    markets: list[Market]
    events: dict[tuple[str, str, str], Event]
    resolver: TeamResolver


def load_csv_dir(path: str | Path) -> list[OddsRow]:
    """Read CSVs written by soccer.run --save."""
    out = []
    for f in sorted(Path(path).glob("*.csv")):
        with f.open() as fh:
            for r in csv.DictReader(fh):
                r["line"] = float(r["line"]) if r["line"] else None
                r["odds_decimal"] = float(r["odds_decimal"])
                r["suspended"] = r["suspended"] == "True"
                r["liquidity"] = float(r["liquidity"]) if r.get("liquidity") else None
                if not r.get("league"):
                    r["league"] = f.stem
                out.append(OddsRow(**r))
    return out


def _market_kind(book: str, market_name: str) -> str | None:
    for kind, per_book in MARKETS.items():
        if any(re.fullmatch(p, market_name) for p in per_book.get(book, [])):
            return kind
    return None


def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def build(rows: Iterable[OddsRow], resolver: TeamResolver | None = None) -> Matched:
    resolver = resolver or TeamResolver()
    now = datetime.now(timezone.utc)
    events: dict[tuple[str, str, str], Event] = {}
    # (league, home, away, kind, line) -> book -> selection -> row
    grouped: dict[tuple, dict[str, dict[str, OddsRow]]] = defaultdict(lambda: defaultdict(dict))

    for r in rows:
        book = book_of(r)
        kind = _market_kind(book, r.market_name)
        if not kind or not r.home_team or not r.away_team or r.selection is None:
            continue
        start = _parse_time(r.start_time)
        if start <= now or r.suspended or r.status.upper() != "OPEN" or r.event_state == "LIVE":
            continue  # prematch, open prices only
        home, away = resolver.key(book, r.home_team), resolver.key(book, r.away_team)
        ev = events.setdefault((r.league, home, away), Event(r.league, home, away))
        ev.names[book] = (r.home_team, r.away_team)
        ev.start.setdefault(book, start)
        grouped[(r.league, home, away, kind, r.line if kind == "TOTAL" else None)][book].setdefault(r.selection, r)

    # Same teams but kickoffs far apart means a different fixture: drop that book.
    dropped: set[tuple[tuple[str, str, str], str]] = set()
    for key, ev in events.items():
        ref = next((ev.start[b] for b in SHARP_BOOKS if b in ev.start), None)
        if ref is None:
            continue
        for book, start in list(ev.start.items()):
            if abs(start - ref) > KICKOFF_TOLERANCE:
                dropped.add((key, book))
                del ev.start[book]

    markets: list[Market] = []
    for (league, home, away, kind, line), books in grouped.items():
        ev = events[(league, home, away)]
        raw = ev.names.get(NAMING_BOOK) or next(iter(ev.names.values()))
        home_name, away_name = resolver.name(home, raw[0]), resolver.name(away, raw[1])
        sels = MARKET_SELECTIONS[kind]
        labels = ({"home": home_name, "draw": "Draw", "away": away_name} if kind == "1X2"
                  else {"over": f"Over {line:g}", "under": f"Under {line:g}"})
        m = Market(
            sport="soccer", league=league, event=f"{home_name} v {away_name}",
            event_key=f"{league}|{home}|{away}", kickoff=min(ev.start.values()) if ev.start else now,
            kind=kind, line=line, selections=sels, labels=labels,
        )
        for book, outcomes in books.items():
            if ((league, home, away), book) in dropped:
                continue
            m.prices[book] = {s: r.odds_decimal for s, r in outcomes.items()}
            first = next(iter(outcomes.values()))
            if first.liquidity is not None:
                m.liquidity[book] = first.liquidity
            if first.market_name.endswith("(alt)"):
                m.alt_line.add(book)
        markets.append(m)
    return Matched(markets, events, resolver)


def coverage(matched: Matched) -> dict[str, Counter]:
    """league -> book -> events that are matched to a sharp-book event."""
    out: dict[str, Counter] = defaultdict(Counter)
    for ev in matched.events.values():
        if any(b in ev.start for b in SHARP_BOOKS):
            for book in ev.start:
                out[ev.league][book] += 1
    return out


def suggest_mappings(matched: Matched, max_kickoff_gap: timedelta = timedelta(minutes=20)) -> tuple[list[str], int]:
    """For events Pinnacle doesn't list under the same names, look for a
    Pinnacle event in the same league at the same kickoff and suggest TEAMS
    entries (Betfair included). Returns (suggested lines, number of listings
    with no Pinnacle fixture at that kickoff)."""
    sharp_events = [e for e in matched.events.values() if NAMING_BOOK in e.start]
    suggestions: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    no_fixture = 0
    for ev in matched.events.values():
        if NAMING_BOOK in ev.start:
            continue
        for book, (raw_home, raw_away) in ev.names.items():
            if book not in ev.start:
                continue
            cands = [s for s in sharp_events
                     if s.league == ev.league and abs(s.start[NAMING_BOOK] - ev.start[book]) <= max_kickoff_gap]

            def score(s: Event) -> float:
                return difflib.SequenceMatcher(None, f"{ev.home}|{ev.away}", f"{s.home}|{s.away}").ratio()

            best = max(cands, key=score, default=None)
            if best is None or score(best) < 0.5:
                no_fixture += 1
                continue
            sh, sa = best.names[NAMING_BOOK]
            for raw, sharp_name, key in ((raw_home, sh, ev.home), (raw_away, sa, ev.away)):
                if key not in (best.home, best.away):
                    suggestions[(sharp_name, ev.league)][book] = raw
    lines = []
    for (sharp, league), per_book in sorted(suggestions.items(), key=lambda x: (x[0][1], x[0][0])):
        books = ", ".join(f'"{b}": "{raw}"' for b, raw in sorted(per_book.items()))
        lines.append(f'    "{sharp}": {{{books}}},  # {league}')
    return lines, no_fixture
