"""Match tennis match-winner prices across books into engine Markets.

Books disagree on name format ("Jannik Sinner", "J. Sinner", "Sinner, Jannik",
"Sinner J.") and on which player is listed first, so markets are keyed by the
pair of players, not home/away. A player resolves to the sharp books'
spelling via, in order: PLAYERS aliases, surname + first initial, then the
same set of name parts in any order (catches "Zhang Zhizhen" vs "Zhizhen Zhang").
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from engine.markets import Market
from scrapers.common import OddsRow
from scrapers.registry import SHARP_BOOKS, book_of

from .mappings import PLAYERS

KICKOFF_TOLERANCE = timedelta(hours=36)  # tennis start times are estimates ("followed by")
EXCLUDE_MARKET = re.compile(r"set|game|\(alt\)|handicap|total", re.IGNORECASE)


def _tokens(name: str) -> tuple[list[str], str, list[str]]:
    """(surname tokens, first initial, all tokens)."""
    raw = unicodedata.normalize("NFKD", name.replace("ı", "i")).encode("ascii", "ignore").decode().lower()
    if "," in raw:
        last, first = raw.split(",", 1)
        last_t = re.sub(r"[^a-z ]", " ", last.replace("-", " ")).split()
        first_t = re.sub(r"[^a-z ]", " ", first.replace("-", " ")).split()
        return last_t, (first_t[0][0] if first_t else ""), last_t + first_t
    toks = re.sub(r"[^a-z ]", " ", raw.replace("-", " ")).split()
    initials = [t for t in toks if len(t) == 1]
    if initials:
        return [t for t in toks if len(t) > 1], initials[0], toks
    return toks[1:], (toks[0][0] if toks else ""), toks


def player_key(name: str) -> str:
    surname, initial, _ = _tokens(name)
    return f"{' '.join(surname)}|{initial}"


def token_key(name: str) -> str:
    return " ".join(sorted(t for t in _tokens(name)[2] if len(t) > 1))


class PlayerResolver:
    def __init__(self, sharp_names: Iterable[str], players: dict[str, dict[str, str | list[str]]] = PLAYERS):
        self.display: dict[str, str] = {}
        primary: dict[str, set[str]] = defaultdict(set)
        self.by_tokens: dict[str, str] = {}
        for n in sharp_names:
            k = player_key(n)
            self.display.setdefault(k, n)
            primary[k].add(token_key(n))
            self.by_tokens.setdefault(token_key(n), k)
        # A surname+initial shared by two different sharp players (e.g. two "Wang X.") is ambiguous.
        self.by_primary = {k: k for k, toks in primary.items() if len(toks) == 1}
        self.alias: dict[tuple[str, str], str] = {}
        for canonical, per_book in players.items():
            ck = player_key(canonical)
            self.display.setdefault(ck, canonical)
            for book, names in per_book.items():
                for n in [names] if isinstance(names, str) else names:
                    self.alias[(book, n.strip().lower())] = ck

    def key(self, book: str, name: str) -> str:
        if (book, name.strip().lower()) in self.alias:
            return self.alias[(book, name.strip().lower())]
        k = player_key(name)
        if k in self.by_primary:
            return k
        return self.by_tokens.get(token_key(name), k)

    def name(self, key: str, fallback: str) -> str:
        return self.display.get(key, fallback)


@dataclass
class Event:
    players: tuple[str, str]
    names: dict[str, tuple[str, str]] = field(default_factory=dict)  # book -> raw names (listing order)
    start: dict[str, datetime] = field(default_factory=dict)
    league: dict[str, str] = field(default_factory=dict)


@dataclass
class Matched:
    markets: list[Market]
    events: dict[str, Event]
    resolver: PlayerResolver


def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _usable(r: OddsRow) -> bool:
    return (r.market_type == "Match" and not EXCLUDE_MARKET.search(r.market_name)
            and "/" not in (r.outcome_label or "") and r.status.upper() == "OPEN" and not r.suspended
            and r.event_state != "LIVE")


def build(rows: Iterable[OddsRow]) -> Matched:
    rows = [r for r in rows if _usable(r)]
    now = datetime.now(timezone.utc)
    sharp_names = [r.outcome_label for b in SHARP_BOOKS for r in rows if book_of(r) == b]
    resolver = PlayerResolver(sharp_names)

    by_market: dict[tuple[str, str, str], list[OddsRow]] = defaultdict(list)
    for r in rows:
        by_market[(book_of(r), r.event_id, r.market_id)].append(r)

    events: dict[str, Event] = {}
    prices: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)  # event key -> book -> player -> odds
    liquidity: dict[str, dict[str, float]] = defaultdict(dict)
    for (book, _, _), outcomes in by_market.items():
        if len(outcomes) != 2:
            continue
        start = _parse_time(outcomes[0].start_time)
        if start <= now - timedelta(hours=1):
            continue
        keys = [resolver.key(book, o.outcome_label) for o in outcomes]
        if keys[0] == keys[1]:
            continue
        ek = "|".join(sorted(keys))
        ev = events.setdefault(ek, Event(tuple(sorted(keys))))
        order = sorted(outcomes, key=lambda o: o.selection != "home")
        ev.names[book] = (order[0].outcome_label, order[1].outcome_label)
        ev.start.setdefault(book, start)
        ev.league.setdefault(book, outcomes[0].league)
        prices[ek][book] = {k: o.odds_decimal for k, o in zip(keys, outcomes)}
        if outcomes[0].liquidity is not None:
            liquidity[ek][book] = outcomes[0].liquidity

    markets: list[Market] = []
    for ek, ev in events.items():
        ref = next((ev.start[b] for b in SHARP_BOOKS if b in ev.start), None)
        books = {b: p for b, p in prices[ek].items() if ref is None or abs(ev.start[b] - ref) <= KICKOFF_TOLERANCE}
        naming = next((b for b in SHARP_BOOKS if b in ev.names), next(iter(ev.names)))
        first, second = ev.names[naming]
        k1 = resolver.key(naming, first)
        ordered = (k1, ev.players[1] if ev.players[0] == k1 else ev.players[0])
        labels = {k: resolver.name(k, raw) for k, raw in zip(ordered, (first, second))}
        league = ev.league.get("pinnacle") or ev.league.get(naming) or ""
        m = Market(
            sport="tennis", league=league, event=f"{labels[ordered[0]]} v {labels[ordered[1]]}",
            event_key=ek, kickoff=ref or min(ev.start.values()), kind="H2H", line=None,
            selections=ev.players, labels=labels, prices=books,
            liquidity={b: v for b, v in liquidity[ek].items() if b in books},
        )
        markets.append(m)
    return Matched(markets, events, resolver)


def tour_of(league: str) -> str:
    return league.split(" | ", 1)[0] if " | " in league else league


def coverage(matched: Matched) -> dict[str, Counter]:
    """tour -> book -> matches priced that a sharp book also prices."""
    out: dict[str, Counter] = defaultdict(Counter)
    for m in matched.markets:
        if any(b in m.prices for b in SHARP_BOOKS):
            for b in m.prices:
                out[tour_of(m.league)][b] += 1
    return out


def suggest_mappings(matched: Matched) -> tuple[list[str], int]:
    """For soft-book matches no sharp book lists, find a sharp match within the
    kickoff window that shares one player and suggest a PLAYERS entry for the other."""
    sharp_events = [e for e in matched.events.values() if any(b in e.start for b in SHARP_BOOKS)]
    by_player: dict[str, list[Event]] = defaultdict(list)
    for e in sharp_events:
        for p in e.players:
            by_player[p].append(e)
    suggestions: dict[str, dict[str, str]] = defaultdict(dict)
    unmatched = 0
    for ev in matched.events.values():
        if any(b in ev.start for b in SHARP_BOOKS):
            continue
        found = False
        for book, raw in ev.names.items():
            start = ev.start[book]
            for known in ev.players:
                for s in by_player.get(known, []):
                    sharp_start = next(s.start[b] for b in SHARP_BOOKS if b in s.start)
                    if abs(sharp_start - start) > KICKOFF_TOLERANCE:
                        continue
                    other_soft = next(p for p in ev.players if p != known)
                    other_sharp = next(p for p in s.players if p != known)
                    soft_raw = next(n for n in raw if matched.resolver.key(book, n) == other_soft)
                    sharp_name = matched.resolver.name(other_sharp, other_sharp)
                    if difflib.SequenceMatcher(None, token_key(soft_raw), token_key(sharp_name)).ratio() >= 0.5:
                        suggestions[sharp_name][book] = soft_raw
                        found = True
        unmatched += not found
    lines = []
    for sharp, per_book in sorted(suggestions.items()):
        books = ", ".join(f'"{b}": "{raw}"' for b, raw in sorted(per_book.items()))
        lines.append(f'    "{sharp}": {{{books}}},')
    return lines, unmatched
