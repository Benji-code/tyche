"""Scrape the soccer leagues, then print +EV bets and arbitrage with stake sizing.

    python -m soccer.run                              # scrape everything (~2-3 min) and analyse
    python -m soccer.run --leagues england_premier_league italy_serie_a
    python -m soccer.run --from-dir data/soccer/20261012_174000   # re-analyse saved CSVs, no scraping
    python -m soccer.run --min-ev 0.01 --bankroll 100 --kelly 0.5 --save

EV is measured against Pinnacle's devigged price. Stakes are fractional Kelly
on --bankroll, sized per bet independently (they don't account for each other).
Arbs exclude Pinnacle by default since it doesn't take Australian customers.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime
from pathlib import Path

from scrapers.common import write_csv
from scrapers.soccer import BOOKS, LEAGUES, scrape_all

from .compare import (
    SHARP,
    Arb,
    Comparison,
    MarketKey,
    ValueBet,
    build,
    coverage,
    find_arbs,
    find_value,
    load_csv_dir,
    suggest_mappings,
)

SELECTION_LABEL = {"home": "Home", "draw": "Draw", "away": "Away", "over": "Over", "under": "Under"}


def _match_name(cmp: Comparison, key: MarketKey) -> str:
    ev = cmp.events[(key.league, key.home, key.away)]
    raw = ev.names.get(SHARP) or next(iter(ev.names.values()))
    return f"{cmp.resolver.name(key.home, raw[0])} v {cmp.resolver.name(key.away, raw[1])}"


def _kickoff(cmp: Comparison, key: MarketKey) -> str:
    ev = cmp.events[(key.league, key.home, key.away)]
    start = ev.start.get(SHARP) or next(iter(ev.start.values()))
    return start.astimezone().strftime("%a %d %b %H:%M")


def _bet_label(cmp: Comparison, key: MarketKey, selection: str) -> str:
    if key.kind == "TOTAL":
        return f"{SELECTION_LABEL[selection]} {key.line:g}"
    if selection == "draw":
        return "Draw"
    team = key.home if selection == "home" else key.away
    ev = cmp.events[(key.league, key.home, key.away)]
    raw = ev.names.get(SHARP) or next(iter(ev.names.values()))
    return cmp.resolver.name(team, raw[0] if selection == "home" else raw[1])


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def print_value(cmp: Comparison, bets: list[ValueBet], bankroll: float, kelly: float) -> None:
    print(f"\n=== +EV bets (vs devigged Pinnacle) — stakes at {kelly:g} Kelly on ${bankroll:g} ===")
    if not bets:
        print("None found at this threshold.")
        return
    hdr = f"{'Kickoff':<16} {'League':<22} {'Match':<36} {'Mkt':<5} {'Bet':<22} {'Book':<10} {'Odds':>6} {'Fair':>6} {'EV':>6} {'Stake':>7}"
    print(hdr + "\n" + "-" * len(hdr))
    for b in bets:
        label = _truncate(_bet_label(cmp, b.key, b.selection), 21) + ("*" if b.sharp_alternate else "")
        print(
            f"{_kickoff(cmp, b.key):<16} {_truncate(b.key.league, 22):<22} "
            f"{_truncate(_match_name(cmp, b.key), 36):<36} {b.key.kind:<5} "
            f"{label:<22} {b.book:<10} "
            f"{b.odds:>6.2f} {1 / b.fair_prob:>6.2f} {b.ev:>6.1%} {'$' + format(b.stake, '.2f'):>7}"
        )
    if any(b.sharp_alternate for b in bets):
        print("\n* Fair price from a Pinnacle alternate line (not its main line): higher margin, "
              "lower limits, less reliable.")
    total = sum(b.stake for b in bets)
    print(f"\n{len(bets)} bets, total suggested stake ${total:.2f}. Stakes are independent; "
          "if the total is more than you want at risk, scale them all down proportionally.")


def print_arbs(cmp: Comparison, arbs: list[Arb], total_stake: float) -> None:
    print(f"\n=== Arbitrage (stakes for ${total_stake:g} total outlay) ===")
    if not arbs:
        print("None found.")
        return
    for a in arbs:
        print(f"{_kickoff(cmp, a.key)}  {a.key.league}  {_match_name(cmp, a.key)}  [{a.key.kind}]  "
              f"profit {a.profit:.2%} (${total_stake * a.profit:.2f})")
        for sel, book, odds, stake in a.legs:
            print(f"    {_bet_label(cmp, a.key, sel):<26} {book:<10} @ {odds:<6.2f} stake ${stake:.2f}")


def print_diagnostics(cmp: Comparison) -> None:
    print("\n=== Matching coverage (events matched to Pinnacle / events listed) ===")
    cov = coverage(cmp)
    soft = [b for b in BOOKS if b != SHARP]
    print(f"{'league':<26}{SHARP:>10}" + "".join(f"{b:>14}" for b in soft))
    for league in LEAGUES:
        if league not in cov:
            continue
        row = cov[league]
        sharp_n = row.get(SHARP, (0, 0))[1]
        cells = "".join(f"{'%d/%d' % row[b] if b in row else '-':>14}" for b in soft)
        print(f"{league:<26}{sharp_n:>10}{cells}")

    suggestions, no_fixture = suggest_mappings(cmp)
    if suggestions:
        print("\nUnmapped team names (same league + kickoff as a Pinnacle game). "
              "Check, then add to TEAMS in soccer/mappings.py:")
        print("\n".join(suggestions))
    if no_fixture:
        print(f"\n{no_fixture} soft-book listings have no Pinnacle game at that kickoff "
              "(usually Pinnacle hasn't posted it yet).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Find +EV and arbitrage soccer bets across Pinnacle, Ladbrokes, Unibet.")
    parser.add_argument("--leagues", nargs="+", choices=list(LEAGUES), default=list(LEAGUES), metavar="LEAGUE")
    parser.add_argument("--books", nargs="+", choices=BOOKS, default=list(BOOKS))
    parser.add_argument("--from-dir", help="analyse saved per-league CSVs instead of scraping")
    parser.add_argument("--save", action="store_true", help="also write the scraped CSVs to data/soccer/<timestamp>/")
    parser.add_argument("--fast", action="store_true", help="Ladbrokes 1X2 only (skips per-event requests, no totals)")
    parser.add_argument("--min-ev", type=float, default=0.02, help="minimum EV to show (default 0.02 = 2%%)")
    parser.add_argument("--max-ev", type=float, default=0.30, help="hide EV above this as likely errors (default 0.30)")
    parser.add_argument("--bankroll", type=float, default=100.0)
    parser.add_argument("--kelly", type=float, default=0.5, help="Kelly fraction (default 0.5 = half Kelly)")
    parser.add_argument("--devig", choices=["power", "multiplicative"], default="power")
    parser.add_argument("--all-books", action="store_true", help="list every soft book with an edge, not just the best")
    parser.add_argument("--arb-include-pinnacle", action="store_true", help="allow Pinnacle legs in arbs")
    parser.add_argument("--delay", type=float, default=0.7)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.from_dir:
        rows = [(lg, r) for lg, r in load_csv_dir(args.from_dir) if lg in args.leagues]
        source = args.from_dir
    else:
        print(f"Scraping {len(args.leagues)} leagues from {', '.join(args.books)} ...", flush=True)
        t0 = time.monotonic()
        by_book = scrape_all(args.leagues, args.books, args.delay, args.fast, pinnacle_alternates=True)
        rows = [(lg, r) for book in by_book.values() for lg, rs in book.items() for r in rs]
        source = f"live scrape ({time.monotonic() - t0:.0f}s)"
        if args.save:
            out_dir = Path(f"data/soccer/{time.strftime('%Y%m%d_%H%M%S')}")
            for lg in args.leagues:
                write_csv([r for book in by_book.values() for r in book.get(lg, [])], out_dir / f"{lg}.csv")
            print(f"Saved CSVs to {out_dir}")

    cmp = build(rows)
    bets = find_value(
        cmp,
        min_ev=args.min_ev,
        max_ev=args.max_ev,
        bankroll=args.bankroll,
        kelly=args.kelly,
        devig_method=args.devig,
        best_book_only=not args.all_books,
    )
    arbs = find_arbs(cmp, total_stake=args.bankroll, include_sharp=args.arb_include_pinnacle)

    print(f"\nSource: {source} · {len(rows)} prices · analysed {datetime.now().strftime('%H:%M:%S')}")
    print_diagnostics(cmp)
    print_value(cmp, bets, args.bankroll, args.kelly)
    print_arbs(cmp, arbs, args.bankroll)


if __name__ == "__main__":
    main()
