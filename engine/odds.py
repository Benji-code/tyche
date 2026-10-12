"""Odds maths shared by every sport."""

from __future__ import annotations

import math


def devig(implied: list[float], method: str = "power") -> list[float]:
    """Remove the margin from implied probabilities (1/odds)."""
    total = sum(implied)
    if method == "multiplicative":
        return [q / total for q in implied]
    if method == "power":
        # Find k with sum(q_i ** k) == 1; shades longshots more than favourites.
        lo, hi = 0.5, 10.0
        for _ in range(100):
            k = (lo + hi) / 2
            if sum(q**k for q in implied) > 1:
                lo = k
            else:
                hi = k
        probs = [q**k for q in implied]
        s = sum(probs)
        return [p / s for p in probs]
    if method == "shin":
        # Shin (1993): the margin comes from the book protecting itself against a
        # share z of insider money. Solve for z so the probabilities sum to 1.
        def probs_for(z: float) -> list[float]:
            return [((z * z + 4 * (1 - z) * q * q / total) ** 0.5 - z) / (2 * (1 - z)) for q in implied]

        lo, hi = 0.0, 0.4
        for _ in range(100):
            z = (lo + hi) / 2
            if sum(probs_for(z)) > 1:
                lo = z
            else:
                hi = z
        probs = probs_for((lo + hi) / 2)
        s = sum(probs)
        return [p / s for p in probs]
    raise ValueError(f"unknown devig method {method}")


def kelly_fraction(prob: float, odds: float) -> float:
    """Full-Kelly fraction of bankroll for a bet at decimal odds."""
    return max(0.0, (prob * odds - 1) / (odds - 1))


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))
