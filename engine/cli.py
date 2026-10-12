"""Command-line flags for Strategy, shared by the sport runners."""

from __future__ import annotations

import argparse

from .evaluate import Strategy


def add_strategy_args(parser: argparse.ArgumentParser) -> None:
    d = Strategy()
    g = parser.add_argument_group("strategy (what counts as a good bet; see engine/evaluate.py)")
    g.add_argument("--min-ev", type=float, default=d.min_ev, help=f"min worst-case EV (default {d.min_ev})")
    g.add_argument("--max-ev", type=float, default=d.max_ev, help=f"hide central EV above this as likely errors (default {d.max_ev})")
    g.add_argument("--min-sharps", type=int, default=d.min_sharps, help="sharp books required (default 2: Pinnacle + Betfair)")
    g.add_argument("--sharp-tolerance", type=float, default=d.sharp_tolerance, help="max probability gap between sharps (default 0.03)")
    g.add_argument("--min-crowd-books", type=int, default=d.min_crowd_books, help="other soft books needed for the crowd estimate (default 3)")
    g.add_argument("--min-liquidity", type=float, default=d.min_exchange_liquidity, help="Betfair matched AUD before it counts (default 1000)")
    g.add_argument("--devig", choices=["power", "multiplicative", "shin"], default=d.devig, help="method for the central estimate")
    g.add_argument("--bankroll", type=float, default=d.bankroll)
    g.add_argument("--kelly", type=float, default=d.kelly, help="Kelly fraction applied at the worst-case probability (default 0.5)")
    g.add_argument("--max-stake", type=float, default=d.max_stake, help="per-bet cap, fraction of bankroll (default 0.025)")
    g.add_argument("--max-event", type=float, default=d.max_event, help="per-event cap, fraction of bankroll (default 0.05)")
    g.add_argument("--max-total", type=float, default=d.max_total, help="per-run cap, fraction of bankroll (default 0.20)")


def strategy_from(args: argparse.Namespace) -> Strategy:
    return Strategy(
        min_ev=args.min_ev, max_ev=args.max_ev, min_sharps=args.min_sharps,
        sharp_tolerance=args.sharp_tolerance, min_crowd_books=args.min_crowd_books, devig=args.devig,
        min_exchange_liquidity=args.min_liquidity, bankroll=args.bankroll, kelly=args.kelly,
        max_stake=args.max_stake, max_event=args.max_event, max_total=args.max_total,
    )
