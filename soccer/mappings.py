"""Cross-bookmaker name mappings for soccer.

TEAMS maps a canonical team name (Pinnacle's spelling, since it's the reference
book) to what each other book calls that team. Only add an entry when the names
differ after normalisation: case, accents, punctuation, single digits and
tokens like FC / AFC / SC / AC are already ignored (see normalise() in
compare.py), so "1. FC Köln" vs "FC Koln" style differences don't need entries.

When the runner sees an unmapped name it prints a suggested line to paste here.

MARKETS maps a comparable market kind to each book's market name (regex, full match).
"""

from __future__ import annotations

TEAMS: dict[str, dict[str, str | list[str]]] = {
    # --- England ---
    "Brighton": {"ladbrokes": "Brighton & Hove Albion"},
    "Tottenham Hotspur": {"unibet": "Tottenham"},
    "Wolverhampton": {"ladbrokes": "Wolverhampton Wanderers", "unibet": "Wolves"},
    "Birmingham City": {"unibet": "Birmingham"},
    "Bolton Wanderers": {"unibet": "Bolton"},
    "West Bromwich Albion": {"unibet": "West Bromwich"},
    "West Ham United": {"unibet": "West Ham"},
    "MK Dons": {"unibet": "Milton Keynes Dons"},
    # --- Italy ---
    "Internazionale": {"ladbrokes": "Inter Milan", "unibet": "Inter"},
    "Fiorentina": {"ladbrokes": "ACF Fiorentina"},
    "Atalanta": {"ladbrokes": "Atalanta BC"},
    "Como": {"ladbrokes": "Como 1907"},
    "Genoa": {"ladbrokes": "Genoa CFC"},
    "Ascoli": {"ladbrokes": "Ascoli Calcio 1898"},
    "Carrarese": {"ladbrokes": "Carrarese Calcio 1908"},
    "Vicenza": {"ladbrokes": "LR Vicenza"},
    "Mantova": {"ladbrokes": "Mantova 1911"},
    "Pisa": {"ladbrokes": "Pisa Sporting Club"},
    "Sampdoria": {"ladbrokes": "UC Sampdoria"},
    "Avellino": {"ladbrokes": "US Avellino 1912"},
    "Catanzaro": {"ladbrokes": "US Catanzaro 1929"},
    # --- Spain ---
    "Osasuna": {"ladbrokes": "CA Osasuna"},
    "Alaves": {"ladbrokes": "Deportivo Alaves"},
    "Espanyol": {"ladbrokes": "Espanyol Barcelona"},
    "Deportivo La Coruna": {"unibet": "Deportivo A Coruña"},
    "Albacete": {"ladbrokes": "Albacete Balompie", "unibet": "Albacete Balompié"},
    "Real Sociedad II": {"ladbrokes": "Real Sociedad B", "unibet": "Real Sociedad B"},
    "Real Valladolid": {"unibet": "Valladolid"},
    # --- Germany ---
    "FC Koln": {"ladbrokes": "1. FC Cologne"},
    "Mainz 05": {"ladbrokes": "1. FSV Mainz 05"},
    "Paderborn": {"ladbrokes": "SC Paderborn 07", "unibet": "SC Paderborn 07"},
    "Elversberg": {"ladbrokes": "SV 07 Elversberg"},
    "Nurnberg": {"ladbrokes": "1. FC Nuremberg"},
    "Darmstadt": {"ladbrokes": "SV Darmstadt 98", "unibet": "Darmstadt 98"},
    "Osnabruck": {"ladbrokes": "VfL 1899 Osnabruck"},
    # --- France ---
    "Paris Saint-Germain": {"unibet": "PSG"},
    "Auxerre": {"ladbrokes": "AJ Auxerre"},
    "Angers": {"ladbrokes": "Angers SCO"},
    "Troyes": {"ladbrokes": "ESTAC Troyes"},
    "Lille": {"ladbrokes": "Lille OSC"},
    "Nice": {"ladbrokes": "OGC Nice"},
    "Lyon": {"ladbrokes": "Olympique Lyon"},
    "Marseille": {"ladbrokes": "Olympique Marseille"},
    "Strasbourg": {"ladbrokes": "RC Strasbourg Alsace"},
    "Brest": {"ladbrokes": "Stade Brest 29"},
    "Rennes": {"ladbrokes": "Stade Rennais"},
    "Nancy": {"ladbrokes": "AS Nancy Lorraine"},
    "Clermont": {"ladbrokes": "Clermont Foot 63"},
    "Dijon": {"ladbrokes": "Dijon FCO"},
    "Guingamp": {"ladbrokes": "EA Guingamp"},
    "Grenoble": {"ladbrokes": "Grenoble Foot"},
    # --- Netherlands ---
    "Ajax": {"ladbrokes": "Ajax Amsterdam"},
    "Excelsior": {"ladbrokes": "Excelsior Rotterdam", "unibet": "Excelsior Rotterdam"},
    "Feyenoord": {"ladbrokes": "Feyenoord Rotterdam"},
    "PSV": {"ladbrokes": "PSV Eindhoven", "unibet": "PSV Eindhoven"},
    "Cambuur Leeuwaarden": {"ladbrokes": "SC Cambuur", "unibet": "Cambuur Leeuwarden"},
    "Willem II": {"ladbrokes": "Willem II Tilburg"},
    # --- Turkey ---
    "Amedspor": {"ladbrokes": "Amed Sportif Faaliyetler", "unibet": "Amed Sportif Faaliyetler"},
    "Corum Belediyespor": {"ladbrokes": "Corum FK"},
    "Goztepe": {"ladbrokes": "Goztepe Izmir"},
    "Gaziantep": {"unibet": "Gaziantep B.B."},
}

# Comparable markets: kind -> book -> market_name regexes (full match).
# 1X2 = full-time (regulation) home/draw/away; TOTAL = full-time total goals.
MARKETS: dict[str, dict[str, list[str]]] = {
    "1X2": {
        "pinnacle": [r"Moneyline"],
        "ladbrokes": [r"Match Result"],
        "unibet": [r"Full Time"],
    },
    "TOTAL": {
        "pinnacle": [r"Total", r"Total \(alt\)"],  # (alt) = not Pinnacle's main line
        "ladbrokes": [r"Over/Under Total Goals [\d.]+"],
        "unibet": [r"Total Goals"],
    },
}

# Every selection a market kind needs before it can be devigged / arbed.
MARKET_SELECTIONS: dict[str, tuple[str, ...]] = {
    "1X2": ("home", "draw", "away"),
    "TOTAL": ("over", "under"),
}
