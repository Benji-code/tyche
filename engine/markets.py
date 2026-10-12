"""Sport-independent market representation.

Each sport package matches raw OddsRows across books (team / player names,
leagues, kickoff times) and hands the engine a list of Market objects. From
there, finding value, arbs and logging is the same for every sport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Market:
    sport: str
    league: str
    event: str                      # display name, e.g. "Arsenal v Chelsea"
    event_key: str                  # stable canonical id (used in bet keys / logs)
    kickoff: datetime
    kind: str                       # "1X2", "TOTAL", "H2H"
    line: float | None
    selections: tuple[str, ...]     # canonical selection keys, e.g. home/draw/away or player keys
    labels: dict[str, str]          # selection -> display label
    prices: dict[str, dict[str, float]] = field(default_factory=dict)  # book -> selection -> decimal odds
    liquidity: dict[str, float] = field(default_factory=dict)          # book -> matched volume (exchanges)
    alt_line: set[str] = field(default_factory=set)                    # books quoting this as an alternate line

    @property
    def label(self) -> str:
        if self.kind == "TOTAL":
            return f"Total {self.line:g}"
        return {"1X2": "1X2", "H2H": "Match"}.get(self.kind, self.kind)

    def complete(self, book: str) -> bool:
        p = self.prices.get(book, {})
        return all(s in p for s in self.selections)

    def implied(self, book: str) -> list[float]:
        return [1 / self.prices[book][s] for s in self.selections]

    @property
    def key(self) -> str:
        line = "" if self.line is None else f"{self.line:g}"
        return f"{self.sport}|{self.event_key}|{self.kind}|{line}"
