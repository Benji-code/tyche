"""Tennis mappings: which tournaments count, and player-name exceptions.

classify() maps a book's competition name to a tour. Only singles on the
tours in DEFAULT_TOURS are fetched by default (ITF / UTR are thin and poorly
priced by the sharps; doubles names are too inconsistent to match).

PLAYERS maps a canonical player name (Pinnacle's spelling) to what other books
call them. Most names match automatically (see tennis/compare.py: surname +
first initial, or the same set of name parts in any order), so only add
entries the runner flags as unmapped.
"""

from __future__ import annotations

import re
import unicodedata

DEFAULT_TOURS = ("ATP", "WTA", "ATP Challenger", "WTA 125")
ALL_TOURS = DEFAULT_TOURS + ("ITF",)

PLAYERS: dict[str, dict[str, str | list[str]]] = {
    # Pinnacle truncates long names, so it can need an alias too.
    "Santiago Rodriguez Taverna": {"pinnacle": "Santiago Rodriguez Tave", "palmerbet": "Santiago Fa Rodriguez Taverna",
                                   "pointsbet": "Santiago Fa Rodriguez Taverna"},
    "Elmer Moller": {"pointsbet": "Elmer Moeller"},
    "Gabriela Knutson": {"betright": "Gabriela Andrea Knutson"},
    "Irene Burillo Escorihuela": {"ladbrokes": "Irene Burillo", "palmerbet": "Irene Burillo"},
    "Mateus Alves": {"pointsbet": "Mateus de Carvalho Cardoso Alves"},
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.replace("ı", "i")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]", " ", s)).strip()


def classify(name: str) -> str | None:
    n = _norm(name)
    if re.search(r"doubles|\bdbl\b|\bmixed\b", n):
        return None
    if re.search(r"\butr\b|exhibition|\bitf\b|\b[mw](15|25|35|40|50|60|75|80|100)\b", n):
        return "ITF"
    if "challenger" in n:
        return "ATP Challenger"
    if re.search(r"wta ?125|\b125k\b", n):
        return "WTA 125"
    if re.search(r"\bwta\b|women|ladies", n):
        return "WTA"
    if re.search(r"\batp\b|\bmen'?s?\b|\bmens\b", n):
        return "ATP"
    return None


def tour_filter(tours: tuple[str, ...] | list[str] = DEFAULT_TOURS):
    """Competition filter for the scrapers: returns "<tour> | <tournament>" or None."""
    wanted = set(tours)

    def match(name: str, region: str | None = None) -> str | None:
        tour = classify(name)
        return f"{tour} | {name}" if tour in wanted else None

    return match
