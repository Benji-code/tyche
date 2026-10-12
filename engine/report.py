"""Terminal output shared by the sport runners."""

from __future__ import annotations

from collections import Counter

from scrapers.registry import FetchResult

from .evaluate import Arb, Candidate, Evaluation, Strategy


def _t(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _odds(p: float | None) -> str:
    return f"{1 / p:.2f}" if p else "-"


def print_books(results: list[FetchResult]) -> None:
    print("\n=== Books ===")
    for r in results:
        status = f"{len(r.rows):>5} prices" if not r.error else f"FAILED: {r.error}"
        print(f"  {r.book:<10} {r.seconds:>5.1f}s  {status}")


def print_good(ev: Evaluation, strategy: Strategy) -> None:
    print(f"\n=== Good bets — {strategy.kelly:g} Kelly at worst-case probability, ${strategy.bankroll:g} bankroll ===")
    print(f"Rule: {strategy.describe()}")
    if not ev.good:
        print("None passed every check this run.")
        return
    hdr = (f"{'Kickoff':<16} {'League':<18} {'Event':<32} {'Mkt':<9} {'Bet':<20} {'Book':<10} "
           f"{'Odds':>6} {'Pin':>6} {'BF':>6} {'Crowd':>6} {'Worst':>6} {'EVmin':>6} {'EV':>6} {'Stake':>7}")
    print(hdr + "\n" + "-" * len(hdr))
    for c in ev.good:
        m = c.market
        bet = _t(m.labels.get(c.selection, c.selection), 19) + ("*" if "pinnacle" in m.alt_line else "")
        stake = f"${c.stake:.2f}" + ("^" if c.stake < c.stake_uncapped - 0.005 else "")
        print(f"{m.kickoff.astimezone().strftime('%a %d %b %H:%M'):<16} {_t(m.league, 18):<18} {_t(m.event, 32):<32} "
              f"{m.label:<9} {bet:<20} {c.book:<10} {c.odds:>6.2f} {_odds(c.sharp_probs.get('pinnacle')):>6} "
              f"{_odds(c.sharp_probs.get('betfair')):>6} {_odds(c.p_crowd):>6} {_odds(c.p_min):>6} "
              f"{c.ev_min:>6.1%} {c.ev:>6.1%} {stake:>7}")
    print("Pin/BF/Crowd/Worst are fair odds; Worst = most pessimistic estimate (decides and sizes the bet). "
          "EVmin = EV at Worst, EV = EV at the sharp average.")
    if any("pinnacle" in c.market.alt_line for c in ev.good):
        print("* Pinnacle price is from an alternate line (higher margin, lower limits).")
    if any(c.stake < c.stake_uncapped - 0.005 for c in ev.good):
        print("^ stake reduced by the per-bet / per-event / total caps.")
    total = sum(c.stake for c in ev.good)
    print(f"{len(ev.good)} bets, total stake ${total:.2f} ({total / strategy.bankroll:.0%} of bankroll).")


def print_rejections(ev: Evaluation, top: int = 8) -> None:
    if not ev.rejected:
        return
    print(f"\n=== {len(ev.rejected)} prices +EV at the sharp average but rejected (a price can fail several checks) ===")
    for reason, n in ev.reasons.most_common():
        print(f"  {n:>4}  {reason}")
    shown = sorted(ev.rejected, key=lambda c: -c.ev)[:top]
    print(f"Top {len(shown)} by EV:")
    for c in shown:
        m = c.market
        print(f"  {c.ev:>6.1%} (worst {c.ev_min:>+6.1%})  {_t(m.event, 34):<34} {m.label:<9} {_t(m.labels.get(c.selection, c.selection), 20):<20} "
              f"{c.book:<10} @{c.odds:<5.2f} -> {', '.join(c.reasons)}")


def print_arbs(arbs: list[Arb], total_stake: float) -> None:
    print(f"\n=== Arbitrage (soft books only, ${total_stake:g} outlay) ===")
    if not arbs:
        print("None found.")
        return
    for a in arbs:
        m = a.market
        print(f"{m.kickoff.astimezone().strftime('%a %d %b %H:%M')}  {m.league}  {m.event}  [{m.label}]  "
              f"profit {a.profit:.2%} (${total_stake * a.profit:.2f})")
        for sel, book, odds, stake in a.legs:
            print(f"    {_t(m.labels.get(sel, sel), 26):<26} {book:<10} @ {odds:<6.2f} stake ${stake:.2f}")


def print_coverage(coverage: dict[str, Counter], books: list[str], title: str) -> None:
    """coverage: league -> Counter(book -> markets matched)."""
    print(f"\n=== {title} ===")
    print(f"{'league':<26}" + "".join(f"{b[:9]:>10}" for b in books))
    for league in sorted(coverage):
        row = coverage[league]
        print(f"{_t(league, 26):<26}" + "".join(f"{row.get(b, 0):>10}" for b in books))
