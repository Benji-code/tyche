"""Match soccer markets across books, then find +EV bets (soft price vs devigged
Pinnacle) and arbitrage (best price per outcome across books sums under 100%).

Input everywhere is a list of (league_slug, OddsRow).
"""

from __future__ import annotations

import csv
import difflib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from scrapers.common import OddsRow

from .mappings import MARKET_SELECTIONS, MARKETS, TEAMS

SHARP = "pinnacle"
BOOK_FAMILY = {"pinnacle": "pinnacle", "ladbrokes_au": "ladbrokes", "neds_au": "ladbrokes", "unibet_au": "unibet"}
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


@dataclass(frozen=True)
class MarketKey:
    league: str
    home: str  # canonical team keys
    away: str
    kind: str  # 1X2 / TOTAL
    line: float | None


@dataclass
class Event:
    league: str
    home: str
    away: str
    names: dict[str, tuple[str, str]] = field(default_factory=dict)  # book -> raw (home, away)
    start: dict[str, datetime] = field(default_factory=dict)  # book -> kickoff


@dataclass
class ValueBet:
    key: MarketKey
    selection: str
    book: str
    odds: float
    fair_prob: float
    ev: float
    stake: float
    sharp_overround: float
    sharp_alternate: bool  # fair price came from a Pinnacle alternate line, not its main line


@dataclass
class Arb:
    key: MarketKey
    legs: list[tuple[str, str, float, float]]  # (selection, book, odds, stake)
    profit: float


@dataclass
class Comparison:
    events: dict[tuple[str, str, str], Event]
    markets: dict[MarketKey, dict[str, dict[str, OddsRow]]]  # key -> book -> selection -> row
    resolver: TeamResolver


# ---------------------------------------------------------------- loading


def load_csv_dir(path: str | Path) -> list[tuple[str, OddsRow]]:
    """Read data/soccer/<ts>/<league>.csv files written by scrapers.soccer."""
    out = []
    for f in sorted(Path(path).glob("*.csv")):
        with f.open() as fh:
            for r in csv.DictReader(fh):
                r["line"] = float(r["line"]) if r["line"] else None
                r["odds_decimal"] = float(r["odds_decimal"])
                r["suspended"] = r["suspended"] == "True"
                out.append((f.stem, OddsRow(**r)))
    return out


# ---------------------------------------------------------------- matching


def _market_kind(book: str, market_name: str) -> str | None:
    for kind, per_book in MARKETS.items():
        if any(re.fullmatch(p, market_name) for p in per_book.get(book, [])):
            return kind
    return None


def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def build(rows: Iterable[tuple[str, OddsRow]], resolver: TeamResolver | None = None) -> Comparison:
    resolver = resolver or TeamResolver()
    now = datetime.now(timezone.utc)
    events: dict[tuple[str, str, str], Event] = {}
    markets: dict[MarketKey, dict[str, dict[str, OddsRow]]] = defaultdict(lambda: defaultdict(dict))

    for league, r in rows:
        book = BOOK_FAMILY.get(r.bookmaker, r.bookmaker)
        kind = _market_kind(book, r.market_name)
        if not kind or not r.home_team or not r.away_team or r.selection is None:
            continue
        start = _parse_time(r.start_time)
        if start <= now or r.suspended or r.status.upper() != "OPEN":
            continue  # prematch, open prices only
        home, away = resolver.key(book, r.home_team), resolver.key(book, r.away_team)
        ev = events.setdefault((league, home, away), Event(league, home, away))
        ev.names[book] = (r.home_team, r.away_team)
        ev.start[book] = start
        key = MarketKey(league, home, away, kind, r.line if kind == "TOTAL" else None)
        markets[key][book].setdefault(r.selection, r)

    # Same teams but kickoffs far apart means a different fixture: drop the soft side.
    for ev in events.values():
        sharp_start = ev.start.get(SHARP)
        if sharp_start is None:
            continue
        for book, start in list(ev.start.items()):
            if abs(start - sharp_start) > KICKOFF_TOLERANCE:
                for key, books in markets.items():
                    if (key.league, key.home, key.away) == (ev.league, ev.home, ev.away):
                        books.pop(book, None)
                del ev.start[book]
    return Comparison(events, markets, resolver)


# ---------------------------------------------------------------- maths


def devig(implied: list[float], method: str = "power") -> list[float]:
    """Remove the margin from implied probabilities (1/odds)."""
    total = sum(implied)
    if method == "multiplicative":
        return [q / total for q in implied]
    if method == "power":
        # Find k with sum(q_i ** k) == 1; shades longshots more than favourites.
        lo, hi = 1.0, 10.0
        for _ in range(100):
            k = (lo + hi) / 2
            if sum(q**k for q in implied) > 1:
                lo = k
            else:
                hi = k
        return [q**k for q in implied]
    raise ValueError(f"unknown devig method {method}")


def kelly_fraction(prob: float, odds: float) -> float:
    return max(0.0, (prob * odds - 1) / (odds - 1))


def find_value(
    cmp: Comparison,
    min_ev: float = 0.02,
    max_ev: float = 0.30,
    bankroll: float = 100.0,
    kelly: float = 0.5,
    devig_method: str = "power",
    max_sharp_overround: float = 1.10,
    best_book_only: bool = True,
) -> list[ValueBet]:
    bets: list[ValueBet] = []
    for key, books in cmp.markets.items():
        sels = MARKET_SELECTIONS[key.kind]
        sharp = books.get(SHARP, {})
        if not all(s in sharp for s in sels):
            continue
        implied = [1 / sharp[s].odds_decimal for s in sels]
        overround = sum(implied)
        if overround > max_sharp_overround:
            continue
        fair = dict(zip(sels, devig(implied, devig_method)))
        alternate = sharp[sels[0]].market_name.endswith("(alt)")

        for sel in sels:
            candidates = []
            for book, outcomes in books.items():
                if book == SHARP or sel not in outcomes:
                    continue
                odds = outcomes[sel].odds_decimal
                ev = fair[sel] * odds - 1
                # Very large edges are almost always a mapping or stale-price error.
                if min_ev <= ev <= max_ev:
                    stake = bankroll * kelly * kelly_fraction(fair[sel], odds)
                    candidates.append(ValueBet(key, sel, book, odds, fair[sel], ev, stake, overround, alternate))
            if best_book_only and candidates:
                candidates = [max(candidates, key=lambda b: b.ev)]
            bets.extend(candidates)
    return sorted(bets, key=lambda b: -b.ev)


def find_arbs(cmp: Comparison, total_stake: float = 100.0, include_sharp: bool = False) -> list[Arb]:
    arbs: list[Arb] = []
    for key, books in cmp.markets.items():
        sels = MARKET_SELECTIONS[key.kind]
        best: dict[str, tuple[float, str]] = {}
        for book, outcomes in books.items():
            if book == SHARP and not include_sharp:
                continue
            for sel in sels:
                if sel in outcomes and outcomes[sel].odds_decimal > best.get(sel, (0, ""))[0]:
                    best[sel] = (outcomes[sel].odds_decimal, book)
        if len(best) < len(sels):
            continue
        inv = sum(1 / best[s][0] for s in sels)
        if inv < 1:
            legs = [(s, best[s][1], best[s][0], total_stake * (1 / best[s][0]) / inv) for s in sels]
            arbs.append(Arb(key, legs, 1 / inv - 1))
    return sorted(arbs, key=lambda a: -a.profit)


# ---------------------------------------------------------------- diagnostics


def coverage(cmp: Comparison) -> dict[str, dict[str, tuple[int, int]]]:
    """league -> book -> (events matched to a Pinnacle event, events seen)."""
    out: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for ev in cmp.events.values():
        for book in ev.start:
            out[ev.league][book][1] += 1
            if SHARP in ev.start:
                out[ev.league][book][0] += 1
    return {lg: {b: tuple(v) for b, v in d.items()} for lg, d in out.items()}


def suggest_mappings(cmp: Comparison, max_kickoff_gap: timedelta = timedelta(minutes=20)) -> tuple[list[str], int]:
    """For soft-book events with no Pinnacle match, look for a Pinnacle event in
    the same league at the same kickoff and suggest TEAMS entries. Returns
    (suggested lines, count of soft events with no Pinnacle fixture at all)."""
    sharp_events = [e for e in cmp.events.values() if SHARP in e.start]
    suggestions: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)  # (sharp name, league) -> book -> raw
    no_fixture = 0
    for ev in cmp.events.values():
        if SHARP in ev.start:
            continue
        for book, (raw_home, raw_away) in ev.names.items():
            if book not in ev.start:
                continue
            cands = [
                s for s in sharp_events
                if s.league == ev.league and abs(s.start[SHARP] - ev.start[book]) <= max_kickoff_gap
            ]
            def score(s: Event) -> float:
                return difflib.SequenceMatcher(None, f"{ev.home}|{ev.away}", f"{s.home}|{s.away}").ratio()
            best = max(cands, key=score, default=None)
            if best is None or score(best) < 0.5:
                no_fixture += 1
                continue
            sh, sa = best.names[SHARP]
            for raw, sharp_name, key in ((raw_home, sh, ev.home), (raw_away, sa, ev.away)):
                if key not in (best.home, best.away):
                    suggestions[(sharp_name, ev.league)][book] = raw
    lines = []
    for (sharp, league), per_book in sorted(suggestions.items(), key=lambda x: (x[0][1], x[0][0])):
        books = ", ".join(f'"{b}": "{raw}"' for b, raw in sorted(per_book.items()))
        lines.append(f'    "{sharp}": {{{books}}},  # {league}')
    return lines, no_fixture
