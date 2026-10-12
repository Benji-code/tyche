"""Wisdom of the crowd: predict the sharp price from soft-book prices.

1. Consensus: devig each soft book's market, take the median probability per
   outcome across books, renormalise.
2. Calibration: soft books share biases (e.g. they shade favourites
   differently from Pinnacle), so a raw consensus isn't the sharp price. Each
   run fits logit(p_sharp) = a + b * logit(p_consensus) by least squares on
   every market where the sharp price is known, per market kind when there
   are enough points. The fitted line turns any soft consensus into a
   predicted sharp probability.

When checking a bet at book X, the consensus is built from the *other* soft
books (leave-one-out), so a book can't vouch for its own price.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .markets import Market
from .odds import devig, logit, sigmoid

MIN_FIT_POINTS = 30


def consensus(market: Market, books: list[str], method: str = "power") -> dict[str, float] | None:
    probs: dict[str, list[float]] = {s: [] for s in market.selections}
    for b in books:
        if market.complete(b):
            for s, p in zip(market.selections, devig(market.implied(b), method)):
                probs[s].append(p)
    if not books or any(not v for v in probs.values()):
        return None
    med = {s: statistics.median(v) for s, v in probs.items()}
    total = sum(med.values())
    return {s: p / total for s, p in med.items()}


@dataclass
class Fit:
    a: float = 0.0
    b: float = 1.0
    n: int = 0

    def apply(self, p: float) -> float:
        return sigmoid(self.a + self.b * logit(p))


def _least_squares(points: list[tuple[float, float]]) -> Fit:
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        return Fit(n=n)
    b = sum((x - mx) * (y - my) for x, y in points) / sxx
    return Fit(a=my - b * mx, b=b, n=n)


@dataclass
class CrowdModel:
    fits: dict[str, Fit] = field(default_factory=dict)  # market kind -> fit; "*" = pooled
    method: str = "power"

    @classmethod
    def fit(
        cls,
        markets: list[Market],
        soft_books: list[str],
        sharp_fair: dict[str, dict[str, float]],  # market.key -> selection -> sharp probability
        min_books: int = 3,
        method: str = "power",
    ) -> "CrowdModel":
        by_kind: dict[str, list[tuple[float, float]]] = {}
        for m in markets:
            fair = sharp_fair.get(m.key)
            books = [b for b in soft_books if m.complete(b)]
            if not fair or len(books) < min_books:
                continue
            cons = consensus(m, books, method)
            if cons:
                for s in m.selections:
                    by_kind.setdefault(m.kind, []).append((logit(cons[s]), logit(fair[s])))
        model = cls(method=method)
        pooled = [pt for pts in by_kind.values() for pt in pts]
        model.fits["*"] = _least_squares(pooled) if len(pooled) >= MIN_FIT_POINTS else Fit(n=len(pooled))
        for kind, pts in by_kind.items():
            if len(pts) >= MIN_FIT_POINTS:
                model.fits[kind] = _least_squares(pts)
        return model

    def predict(self, market: Market, books: list[str]) -> dict[str, float] | None:
        cons = consensus(market, books, self.method)
        if cons is None:
            return None
        fit = self.fits.get(market.kind) or self.fits.get("*") or Fit()
        raw = {s: fit.apply(p) for s, p in cons.items()}
        total = sum(raw.values())
        return {s: p / total for s, p in raw.items()}

    def describe(self) -> str:
        parts = [f"{k}: a={f.a:+.3f} b={f.b:.3f} (n={f.n})" for k, f in sorted(self.fits.items())]
        return "; ".join(parts) or "identity"
