"""Decide which soft-book prices are good bets, size them, and find arbs.

The rule is risk-neutral to slightly risk-averse: judge and size every bet on
a *pessimistic* fair probability, because we only ever bet where our estimate
looks best (the winner's curse inflates the average estimated edge).

For each outcome we collect every fair-probability estimate available:
    - each bookmaker sharp (Pinnacle) with its margin removed three ways:
      multiplicative, power and Shin,
    - each exchange sharp (Betfair) back/lay midpoint,
    - the crowd: the sharp price predicted from the other soft books (engine.crowd).
p_center is the average of the sharps (power-devigged for Pinnacle); p_min is
the lowest estimate of all.

A soft price is a *candidate* when its EV at p_center is >= min_ev. It is a
*good bet* only if:
    1. at least min_sharps sharp books price it (default 2: Pinnacle AND Betfair),
    2. the sharps agree (max probability gap <= sharp_tolerance),
    3. a crowd estimate exists (>= min_crowd_books other soft books),
    4. worst-case EV = p_min * odds - 1 is >= min_ev,
    5. EV at p_center <= max_ev (bigger is almost always a mapping error or stale price).

Stake = bankroll * kelly * full-Kelly fraction at p_min, then capped per bet,
per event (correlated bets on one match share a cap) and in total for the run.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from .crowd import CrowdModel
from .markets import Market
from .odds import devig, kelly_fraction

DEVIG_METHODS = ("multiplicative", "power", "shin")


@dataclass(frozen=True)
class Strategy:
    min_ev: float = 0.01                # worst-case EV threshold
    max_ev: float = 0.20                # central EV above this = likely error
    min_sharps: int = 2
    sharp_tolerance: float = 0.03       # max |p_pinnacle - p_betfair| for any outcome
    min_crowd_books: int = 3            # other soft books needed for a crowd estimate
    devig: str = "power"                # method for the central estimate and the crowd
    max_sharp_overround: float = 1.10   # skip bookmaker sharps quoting a wider market than this
    min_exchange_liquidity: float = 1000.0  # AUD matched before an exchange price counts
    bankroll: float = 100.0
    kelly: float = 0.5
    max_stake: float = 0.025            # per bet, fraction of bankroll
    max_event: float = 0.05             # all bets on one event combined
    max_total: float = 0.20             # all bets in one run combined

    def describe(self) -> str:
        return (f"worstEV>={self.min_ev:.1%} sharps>={self.min_sharps} tol={self.sharp_tolerance:.0%} "
                f"crowd>={self.min_crowd_books}bk liq>={self.min_exchange_liquidity:g} "
                f"kelly={self.kelly:g}@p_min caps={self.max_stake:.1%}/{self.max_event:.0%}/{self.max_total:.0%}")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Candidate:
    market: Market
    selection: str
    book: str
    odds: float
    sharp_probs: dict[str, float]       # sharp book -> central fair probability
    estimates: dict[str, float]         # every estimate, e.g. "pinnacle:shin", "betfair:mid", "crowd"
    p_sharp: float                      # p_center
    p_crowd: float | None
    ev: float                           # EV at p_center
    stake: float = 0.0
    stake_uncapped: float = 0.0
    n_soft_books: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def p_min(self) -> float:
        return min(self.estimates.values())

    @property
    def min_source(self) -> str:
        return min(self.estimates, key=self.estimates.get)

    @property
    def ev_min(self) -> float:
        return self.p_min * self.odds - 1

    @property
    def ev_crowd(self) -> float | None:
        return None if self.p_crowd is None else self.p_crowd * self.odds - 1

    @property
    def good(self) -> bool:
        return not self.reasons

    @property
    def fair_odds(self) -> float:
        return 1 / self.p_sharp

    @property
    def bet_key(self) -> str:
        return f"{self.market.key}|{self.selection}|{self.book}"


@dataclass
class Arb:
    market: Market
    legs: list[tuple[str, str, float, float]]  # (selection, book, odds, stake)
    profit: float


@dataclass
class Evaluation:
    good: list[Candidate]
    rejected: list[Candidate]
    reasons: Counter
    model: CrowdModel
    markets_with_sharp: int
    markets_total: int


def sharp_estimates(market: Market, book: str, strategy: Strategy) -> dict[str, dict[str, float]] | None:
    """{method: {selection: probability}} from one sharp book, or None if untrustworthy."""
    if not market.complete(book):
        return None
    implied = market.implied(book)
    if book in market.liquidity:  # exchange: midpoints are already ~fair, just normalise
        if market.liquidity[book] < strategy.min_exchange_liquidity:
            return None
        return {"mid": dict(zip(market.selections, devig(implied, "multiplicative")))}
    if sum(implied) > strategy.max_sharp_overround:
        return None
    return {m: dict(zip(market.selections, devig(implied, m))) for m in DEVIG_METHODS}


def _central(per_method: dict[str, dict[str, float]], strategy: Strategy) -> dict[str, float]:
    return per_method.get(strategy.devig) or per_method.get("mid") or next(iter(per_method.values()))


def apply_caps(bets: list[Candidate], strategy: Strategy) -> None:
    """Per-bet, per-event and total caps, scaling stakes down proportionally."""
    b = strategy.bankroll
    for c in bets:
        c.stake = min(c.stake_uncapped, b * strategy.max_stake)
    by_event: dict[str, list[Candidate]] = defaultdict(list)
    for c in bets:
        by_event[f"{c.market.sport}|{c.market.event_key}"].append(c)
    for group in by_event.values():
        total = sum(c.stake for c in group)
        if total > b * strategy.max_event:
            for c in group:
                c.stake *= b * strategy.max_event / total
    total = sum(c.stake for c in bets)
    if total > b * strategy.max_total:
        for c in bets:
            c.stake *= b * strategy.max_total / total


def evaluate(markets: list[Market], sharp_books: list[str], soft_books: list[str], strategy: Strategy) -> Evaluation:
    estimates: dict[str, dict[str, dict[str, dict[str, float]]]] = {}  # market.key -> book -> method -> probs
    for m in markets:
        per_book = {b: e for b in sharp_books if (e := sharp_estimates(m, b, strategy))}
        if per_book:
            estimates[m.key] = per_book

    center: dict[str, dict[str, float]] = {}  # market.key -> selection -> mean of the sharps' central estimates
    for m in markets:
        if per := estimates.get(m.key):
            center[m.key] = {s: sum(_central(e, strategy)[s] for e in per.values()) / len(per) for s in m.selections}
    model = CrowdModel.fit(markets, soft_books, center, strategy.min_crowd_books, strategy.devig)

    good: list[Candidate] = []
    rejected: list[Candidate] = []
    reasons: Counter = Counter()
    for m in markets:
        per = estimates.get(m.key)
        if not per:
            continue
        p_center = center[m.key]
        centrals = {b: _central(e, strategy) for b, e in per.items()}
        gap = max(max(c[s] for c in centrals.values()) - min(c[s] for c in centrals.values()) for s in m.selections)
        complete_soft = [b for b in soft_books if m.complete(b)]

        best: dict[str, Candidate] = {}
        for s in m.selections:
            for book in soft_books:
                odds = m.prices.get(book, {}).get(s)
                if not odds or p_center[s] * odds - 1 < strategy.min_ev:
                    continue
                others = [b for b in complete_soft if b != book]
                pred = model.predict(m, others) if len(others) >= strategy.min_crowd_books else None
                ests = {f"{b}:{method}": probs[s] for b, e in per.items() for method, probs in e.items()}
                if pred:
                    ests["crowd"] = pred[s]
                c = Candidate(
                    market=m, selection=s, book=book, odds=odds,
                    sharp_probs={b: cp[s] for b, cp in centrals.items()}, estimates=ests,
                    p_sharp=p_center[s], p_crowd=pred[s] if pred else None,
                    ev=p_center[s] * odds - 1, n_soft_books=len(complete_soft),
                )
                c.stake_uncapped = strategy.bankroll * strategy.kelly * kelly_fraction(c.p_min, odds)

                if len(per) < strategy.min_sharps:
                    c.reasons.append(f"only {len(per)} sharp")
                elif gap > strategy.sharp_tolerance:
                    c.reasons.append("sharps disagree")
                if pred is None:
                    c.reasons.append("too few books for crowd")
                if c.ev_min < strategy.min_ev:
                    c.reasons.append(f"worst-case EV below min ({c.min_source.split(':')[0]})")
                if c.ev > strategy.max_ev:
                    c.reasons.append("EV implausibly high")

                if c.good:
                    if s not in best or c.ev_min > best[s].ev_min:
                        best[s] = c
                else:
                    rejected.append(c)
                    reasons.update(set(c.reasons))
        good.extend(best.values())

    good.sort(key=lambda c: -c.ev_min)
    apply_caps(good, strategy)
    return Evaluation(good, rejected, reasons, model, len(estimates), len(markets))


def find_arbs(markets: list[Market], books: list[str], total_stake: float = 100.0) -> list[Arb]:
    """Best price per outcome across the given (bettable) books; arb if implied sum < 1."""
    arbs: list[Arb] = []
    for m in markets:
        best: dict[str, tuple[float, str]] = {}
        for b in books:
            for s, odds in m.prices.get(b, {}).items():
                if s in m.selections and odds > best.get(s, (0.0, ""))[0]:
                    best[s] = (odds, b)
        if len(best) < len(m.selections):
            continue
        inv = sum(1 / best[s][0] for s in m.selections)
        if inv < 1 and len({best[s][1] for s in m.selections}) > 1:
            legs = [(s, best[s][1], best[s][0], total_stake * (1 / best[s][0]) / inv) for s in m.selections]
            arbs.append(Arb(m, legs, 1 / inv - 1))
    return sorted(arbs, key=lambda a: -a.profit)
