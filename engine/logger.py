"""Append-only CSV logs of every run's good bets, for judging strategies later.

Files live in <sport package>/logs/:
    bets.csv   one row per good bet per run. The same bet found on several runs
               appears several times with the same bet_key; dedupe on bet_key
               (keep the first) to count it once at the price you'd have taken.
    arbs.csv   one row per arb leg per run.
    runs.csv   one row per run: which books worked, how many markets, the
               strategy settings and the crowd-model fit.

result / closing_fair_odds / pnl are left blank for a later settlement step.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .evaluate import Arb, Candidate, Evaluation, Strategy

BET_FIELDS = [
    "logged_at", "run_id", "sport", "league", "event", "kickoff", "market", "line", "selection",
    "book", "odds", "fair_odds", "ev", "p_sharp", "p_min", "ev_min", "min_source", "pinnacle_prob",
    "betfair_prob", "crowd_prob", "ev_crowd", "sharp_alt_line", "n_soft_books", "stake", "stake_uncapped",
    "bankroll", "kelly", "strategy", "bet_key", "result", "closing_fair_odds", "pnl",
]
ARB_FIELDS = ["logged_at", "run_id", "sport", "league", "event", "kickoff", "market", "line",
              "profit", "selection", "book", "odds", "stake", "arb_key"]
RUN_FIELDS = ["run_id", "started_at", "sport", "books_ok", "books_failed", "markets", "markets_with_sharp",
              "good_bets", "rejected", "arbs", "strategy", "crowd_model", "seconds"]


def _append(path: Path, fields: list[str], rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open() as f:
            header = f.readline().strip().split(",")
        if header != fields:
            # Schema changed: keep the old log intact under a dated name and start fresh.
            path.rename(path.with_name(f"{path.stem}.until-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}"))
    new = not path.exists()
    n = 0
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)
            n += 1
    return n


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class BetLogger:
    def __init__(self, sport_dir: str | Path):
        self.dir = Path(sport_dir) / "logs"

    def log_bets(self, run_id: str, candidates: list[Candidate], strategy: Strategy) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = []
        for c in candidates:
            m = c.market
            rows.append({
                "logged_at": now, "run_id": run_id, "sport": m.sport, "league": m.league, "event": m.event,
                "kickoff": m.kickoff.isoformat(), "market": m.kind, "line": "" if m.line is None else m.line,
                "selection": m.labels.get(c.selection, c.selection), "book": c.book, "odds": c.odds,
                "fair_odds": round(c.fair_odds, 4), "ev": round(c.ev, 4), "p_sharp": round(c.p_sharp, 4),
                "p_min": round(c.p_min, 4), "ev_min": round(c.ev_min, 4), "min_source": c.min_source,
                "pinnacle_prob": _r(c.sharp_probs.get("pinnacle")), "betfair_prob": _r(c.sharp_probs.get("betfair")),
                "crowd_prob": _r(c.p_crowd), "ev_crowd": _r(c.ev_crowd), "sharp_alt_line": "pinnacle" in m.alt_line,
                "n_soft_books": c.n_soft_books, "stake": round(c.stake, 2),
                "stake_uncapped": round(c.stake_uncapped, 2), "bankroll": strategy.bankroll,
                "kelly": strategy.kelly, "strategy": strategy.describe(), "bet_key": c.bet_key,
            })
        return _append(self.dir / "bets.csv", BET_FIELDS, rows)

    def log_arbs(self, run_id: str, arbs: list[Arb]) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = []
        for a in arbs:
            m = a.market
            for sel, book, odds, stake in a.legs:
                rows.append({
                    "logged_at": now, "run_id": run_id, "sport": m.sport, "league": m.league, "event": m.event,
                    "kickoff": m.kickoff.isoformat(), "market": m.kind, "line": "" if m.line is None else m.line,
                    "profit": round(a.profit, 4), "selection": m.labels.get(sel, sel), "book": book,
                    "odds": odds, "stake": round(stake, 2), "arb_key": m.key,
                })
        return _append(self.dir / "arbs.csv", ARB_FIELDS, rows)

    def log_run(self, run_id: str, sport: str, started_at: str, books_ok: list[str], books_failed: list[str],
                ev: Evaluation, n_arbs: int, strategy: Strategy, seconds: float) -> None:
        _append(self.dir / "runs.csv", RUN_FIELDS, [{
            "run_id": run_id, "started_at": started_at, "sport": sport,
            "books_ok": " ".join(books_ok), "books_failed": " ".join(books_failed),
            "markets": ev.markets_total, "markets_with_sharp": ev.markets_with_sharp,
            "good_bets": len(ev.good), "rejected": len(ev.rejected), "arbs": n_arbs,
            "strategy": strategy.describe(), "crowd_model": ev.model.describe(), "seconds": round(seconds, 1),
        }])


def _r(x: float | None) -> float | str:
    return "" if x is None else round(x, 4)
