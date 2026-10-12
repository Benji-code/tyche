"""Cross-bookmaker name mappings for soccer.

TEAMS maps a canonical team name (Pinnacle's spelling, since it's the reference
book) to what each other book calls that team. Only add an entry when the names
differ after normalisation: case, accents, punctuation, single digits and
tokens like FC / AFC / SC / AC are already ignored (see normalise() in
compare.py), so "1. FC Köln" vs "FC Koln" style differences don't need entries.

When the runner sees an unmapped name it prints a suggested line to paste here.

LEAGUE_PATTERNS decides which competitions every scraper fetches and which
league slug they belong to (league_for). UNIBET_PATHS covers Unibet, whose
sport-wide soccer view is truncated.

MARKETS maps a comparable market kind to each book's market name (regex, full match).
"""

from __future__ import annotations

import re
import unicodedata

TEAMS: dict[str, dict[str, str | list[str]]] = {
    # --- England ---
    "Birmingham City": {"betfair": "Birmingham", "pointsbet": "Birmingham", "sportsbet": "Birmingham", "unibet": "Birmingham"},
    "Blackburn Rovers": {"betfair": "Blackburn", "pointsbet": "Blackburn", "sportsbet": "Blackburn"},
    "Bolton Wanderers": {"betfair": "Bolton", "pointsbet": "Bolton", "sportsbet": "Bolton", "unibet": "Bolton"},
    "Bradford City": {"sportsbet": "Bradford"},
    "Brighton": {"betr": "Brighton & Hove Albion", "betright": "Brighton & Hove Albion", "ladbrokes": "Brighton & Hove Albion", "palmerbet": "Brighton & Hove Albion"},
    "Cambridge United": {"sportsbet": "Cambridge Utd"},
    "Cardiff City": {"betfair": "Cardiff", "pointsbet": "Cardiff", "sportsbet": "Cardiff"},
    "Charlton Athletic": {"betfair": "Charlton", "pointsbet": "Charlton", "sportsbet": "Charlton"},
    "Coventry City": {"betfair": "Coventry", "pointsbet": "Coventry", "sportsbet": "Coventry"},
    "Doncaster Rovers": {"sportsbet": "Doncaster"},
    "Huddersfield Town": {"sportsbet": "Huddersfield"},
    "Hull City": {"betfair": "Hull", "pointsbet": "Hull", "sportsbet": "Hull"},
    "Ipswich Town": {"betfair": "Ipswich", "pointsbet": "Ipswich", "sportsbet": "Ipswich"},
    "Leeds United": {"betfair": "Leeds", "pointsbet": "Leeds", "sportsbet": "Leeds"},
    "Leicester City": {"sportsbet": "Leicester"},
    "Lincoln City": {"betfair": "Lincoln", "pointsbet": "Lincoln", "sportsbet": "Lincoln"},
    "Luton Town": {"betfair": "Luton", "sportsbet": "Luton"},
    "MK Dons": {"betr": "Milton Keynes Dons", "betright": "Milton Keynes Dons", "palmerbet": "Milton Keynes Dons", "pointsbet": "Milton Keynes Dons", "unibet": "Milton Keynes Dons"},
    "Manchester City": {"betfair": "Man City", "pointsbet": "Man City", "sportsbet": "Man City"},
    "Manchester United": {"betfair": "Man Utd", "pointsbet": "Man Utd", "sportsbet": "Man Utd"},
    "Mansfield Town": {"sportsbet": "Mansfield"},
    "Newcastle United": {"betfair": "Newcastle", "pointsbet": "Newcastle", "sportsbet": "Newcastle"},
    "Norwich City": {"betfair": "Norwich", "pointsbet": "Norwich", "sportsbet": "Norwich"},
    "Nottingham Forest": {"betfair": "Nottm Forest", "pointsbet": "Nottm Forest", "sportsbet": "Nottm Forest"},
    "Notts County": {"sportsbet": "Notts Co"},
    "Oxford United": {"sportsbet": "Oxford Utd"},
    "Peterborough United": {"sportsbet": "Peterborough"},
    "Plymouth Argyle": {"sportsbet": "Plymouth"},
    "Preston North End": {"betfair": "Preston", "pointsbet": "Preston", "sportsbet": "Preston"},
    "Sheffield United": {"betfair": "Sheff Utd", "pointsbet": "Sheffield Utd", "sportsbet": "Sheff Utd"},
    "Sheffield Wednesday": {"sportsbet": "Sheff Wed"},
    "Stockport County": {"sportsbet": "Stockport"},
    "Stoke City": {"betfair": "Stoke", "pointsbet": "Stoke", "sportsbet": "Stoke"},
    "Swansea City": {"betfair": "Swansea", "pointsbet": "Swansea", "sportsbet": "Swansea"},
    "Tottenham Hotspur": {"betfair": "Tottenham", "pointsbet": "Tottenham", "sportsbet": "Tottenham", "unibet": "Tottenham"},
    "West Bromwich Albion": {"betfair": "West Brom", "pointsbet": "West Brom", "sportsbet": "West Brom", "unibet": "West Bromwich"},
    "West Ham United": {"betfair": "West Ham", "betr": "West Ham", "betright": "West Ham", "pointsbet": "West Ham", "sportsbet": "West Ham", "unibet": "West Ham"},
    "Wigan Athletic": {"sportsbet": "Wigan"},
    "Wolverhampton": {"betfair": "Wolves", "betr": "Wolverhampton Wanderers", "betright": "Wolverhampton Wanderers", "ladbrokes": "Wolverhampton Wanderers", "palmerbet": "Wolverhampton Wanderers", "pointsbet": "Wolves", "sportsbet": "Wolves", "unibet": "Wolves"},
    "Wycombe Wanderers": {"sportsbet": "Wycombe"},
    # --- Italy ---
    "Ascoli": {"ladbrokes": "Ascoli Calcio 1898"},
    "Atalanta": {"ladbrokes": "Atalanta BC"},
    "Avellino": {"ladbrokes": "US Avellino 1912", "sportsbet": "Calcio Avellino SSD"},
    "Carrarese": {"ladbrokes": "Carrarese Calcio 1908"},
    "Catanzaro": {"ladbrokes": "US Catanzaro 1929"},
    "Como": {"ladbrokes": "Como 1907"},
    "Fiorentina": {"ladbrokes": "ACF Fiorentina"},
    "Genoa": {"ladbrokes": "Genoa CFC"},
    "Hellas Verona": {"sportsbet": "Verona"},
    "Internazionale": {"betfair": "Inter", "ladbrokes": "Inter Milan", "pointsbet": "Inter", "sportsbet": "Inter", "unibet": "Inter"},
    "Mantova": {"ladbrokes": "Mantova 1911"},
    "Modena": {"betright": "Modena FC 2018", "palmerbet": "Modena FC 2018", "pointsbet": "Modena FC 2018"},
    "Pisa": {"ladbrokes": "Pisa Sporting Club"},
    "Sampdoria": {"ladbrokes": "UC Sampdoria"},
    "Sudtirol": {"palmerbet": "F.C. Südtirol-Alto Adige"},
    "Vicenza": {"ladbrokes": "LR Vicenza", "sportsbet": "LR Vicenza Virtus"},
    "Virtus Entella": {"sportsbet": "Entella"},
    # --- Spain ---
    "Alaves": {"betr": "Deportivo Alaves", "betright": "Deportivo Alaves", "ladbrokes": "Deportivo Alaves", "palmerbet": "Deportivo Alaves"},
    "Albacete": {"ladbrokes": "Albacete Balompie", "palmerbet": "Albacete Balompié", "pointsbet": "Albacete Balompié", "unibet": "Albacete Balompié"},
    "Deportivo La Coruna": {"betfair": "Deportivo", "pointsbet": "Deportivo", "sportsbet": "Deportivo", "unibet": "Deportivo A Coruña"},
    "Espanyol": {"ladbrokes": "Espanyol Barcelona"},
    "Osasuna": {"ladbrokes": "CA Osasuna"},
    "Real Betis": {"betfair": "Betis", "pointsbet": "Betis", "sportsbet": "Betis"},
    "Real Oviedo": {"betfair": "Oviedo", "sportsbet": "Oviedo"},
    "Real Sociedad": {"pointsbet": "Sociedad"},
    "Real Sociedad II": {"ladbrokes": "Real Sociedad B", "palmerbet": "Real Sociedad B", "pointsbet": "Real Sociedad B", "sportsbet": "Sociedad B", "unibet": "Real Sociedad B"},
    "Real Valladolid": {"betfair": "Valladolid", "sportsbet": "Valladolid", "unibet": "Valladolid"},
    # --- Germany ---
    "Bayer Leverkusen": {"betfair": "Leverkusen", "betr": "Bayer 04 Leverkusen", "betright": "Bayer 04 Leverkusen", "palmerbet": "Bayer 04 Leverkusen", "pointsbet": "Leverkusen", "sportsbet": "Leverkusen"},
    "Bayern Munich": {"betr": "FC Bayern München", "betright": "FC Bayern München", "palmerbet": "FC Bayern München"},
    "Borussia Dortmund": {"betfair": "Dortmund", "sportsbet": "Dortmund"},
    "Borussia Monchengladbach": {"betfair": "Mgladbach", "pointsbet": "Mgladbach", "sportsbet": "Mgladbach"},
    "Darmstadt": {"betr": "SV Darmstadt 98", "ladbrokes": "SV Darmstadt 98", "palmerbet": "SV Darmstadt 98", "pointsbet": "SV Darmstadt 98", "unibet": "Darmstadt 98"},
    "Eintracht Braunschweig": {"sportsbet": "Braunschweig"},
    "Elversberg": {"ladbrokes": "SV 07 Elversberg"},
    "Energie Cottbus": {"sportsbet": "Cottbus"},
    "FC Koln": {"ladbrokes": "1. FC Cologne"},
    "Greuther Furth": {"betr": "SpVgg Greuther Fürth", "palmerbet": "SpVgg Greuther Fürth", "pointsbet": "SpVgg Greuther Fürth"},
    "Hamburger SV": {"pointsbet": "Hamburg"},
    "Hannover 96": {"sportsbet": "Hannover"},
    "Hertha BSC": {"sportsbet": "Hertha Berlin"},
    "Hoffenheim": {"betr": "1899 Hoffenheim", "betright": "1899 Hoffenheim", "palmerbet": "1899 Hoffenheim"},
    "Karlsruher": {"sportsbet": "Karlsruhe"},
    "Mainz 05": {"betfair": "Mainz", "ladbrokes": "1. FSV Mainz 05", "pointsbet": "Mainz", "sportsbet": "Mainz"},
    "Nurnberg": {"ladbrokes": "1. FC Nuremberg"},
    "Osnabruck": {"ladbrokes": "VfL 1899 Osnabruck"},
    "Paderborn": {"betr": "SC Paderborn 07", "betright": "SC Paderborn 07", "ladbrokes": "SC Paderborn 07", "palmerbet": "SC Paderborn 07", "unibet": "SC Paderborn 07"},
    "Schalke 04": {"pointsbet": "Schalke"},
    # --- France ---
    "Angers": {"betr": "Angers SCO", "betright": "Angers SCO", "ladbrokes": "Angers SCO", "palmerbet": "Angers SCO"},
    "Auxerre": {"betr": "AJ Auxerre", "betright": "AJ Auxerre", "ladbrokes": "AJ Auxerre", "palmerbet": "AJ Auxerre"},
    "Brest": {"betr": "Stade Brestois 29", "betright": "Stade Brestois 29", "ladbrokes": "Stade Brest 29", "palmerbet": "Stade Brestois 29"},
    "Clermont": {"betr": "Clermont Foot", "ladbrokes": "Clermont Foot 63", "palmerbet": "Clermont Foot", "pointsbet": "Clermont Foot"},
    "Dijon": {"betr": "Dijon FCO", "ladbrokes": "Dijon FCO", "palmerbet": "Dijon FCO", "pointsbet": "Dijon FCO"},
    "Dunkerque": {"betr": "USL Dunkerque", "palmerbet": "USL Dunkerque", "pointsbet": "USL Dunkerque"},
    "Grenoble": {"betr": "Grenoble Foot 38", "ladbrokes": "Grenoble Foot", "palmerbet": "Grenoble Foot 38", "pointsbet": "Grenoble Foot 38"},
    "Guingamp": {"betr": "En Avant Guingamp", "ladbrokes": "EA Guingamp", "palmerbet": "En Avant Guingamp", "pointsbet": "En Avant Guingamp"},
    "Lille": {"betr": "Lille OSC", "betright": "Lille OSC", "ladbrokes": "Lille OSC", "palmerbet": "Lille OSC"},
    "Lyon": {"betr": "Olympique Lyonnais", "betright": "Olympique Lyonnais", "ladbrokes": "Olympique Lyon", "palmerbet": "Olympique Lyonnais"},
    "Marseille": {"betr": "Olympique Marseille", "betright": "Olympique Marseille", "ladbrokes": "Olympique Marseille", "palmerbet": "Olympique Marseille"},
    "Nancy": {"ladbrokes": "AS Nancy Lorraine"},
    "Nice": {"betr": "OGC Nice", "betright": "OGC Nice", "ladbrokes": "OGC Nice", "palmerbet": "OGC Nice"},
    "Paris Saint-Germain": {"betfair": "Paris St-G", "pointsbet": "PSG", "sportsbet": "Paris St-G", "unibet": "PSG"},
    "Red Star": {"betr": "Red Star FC 93", "palmerbet": "Red Star FC 93", "pointsbet": "Red Star FC 93"},
    "Rennes": {"betr": "Stade Rennais", "betright": "Stade Rennais", "ladbrokes": "Stade Rennais", "palmerbet": "Stade Rennais", "pointsbet": "Stade Rennais"},
    "Saint-Etienne": {"sportsbet": "St Etienne"},
    "Stade Lavallois": {"sportsbet": "Laval"},
    "Strasbourg": {"ladbrokes": "RC Strasbourg Alsace"},
    "Troyes": {"betfair": "ESTAC Troyes", "ladbrokes": "ESTAC Troyes", "pointsbet": "Estac Troyes", "sportsbet": "ESTAC Troyes"},
    # --- Netherlands ---
    "Ajax": {"ladbrokes": "Ajax Amsterdam"},
    "Cambuur Leeuwaarden": {"betr": "Cambuur Leeuwarden", "ladbrokes": "SC Cambuur", "palmerbet": "Cambuur Leeuwarden", "unibet": "Cambuur Leeuwarden"},
    "Excelsior": {"betr": "Excelsior Rotterdam", "betright": "Excelsior Rotterdam", "ladbrokes": "Excelsior Rotterdam", "palmerbet": "Excelsior Rotterdam", "pointsbet": "Excelsior Rotterdam", "unibet": "Excelsior Rotterdam"},
    "Feyenoord": {"ladbrokes": "Feyenoord Rotterdam"},
    "NEC Nijmegen": {"betr": "NEC", "palmerbet": "NEC"},
    "PSV": {"betr": "PSV Eindhoven", "ladbrokes": "PSV Eindhoven", "palmerbet": "PSV Eindhoven", "unibet": "PSV Eindhoven"},
    "Willem II": {"ladbrokes": "Willem II Tilburg"},
    # --- Turkey ---
    "Amedspor": {"betfair": "Amed Sportif Faaliyetler", "betr": "Amed Sportif Faaliyetler", "betright": "Amed Sportif Faaliyetler", "ladbrokes": "Amed Sportif Faaliyetler", "unibet": "Amed Sportif Faaliyetler"},
    "Corum Belediyespor": {"betr": "Çorum FK", "ladbrokes": "Corum FK", "pointsbet": "Çorum FK"},
    "Gaziantep": {"betr": "Gazişehir Gaziantep F.K.", "betright": "Gazişehir Gaziantep F.K.", "unibet": "Gaziantep B.B."},
    "Goztepe": {"ladbrokes": "Goztepe Izmir"},
}

# Comparable markets: kind -> book -> market_name regexes (full match).
# 1X2 = full-time (regulation) home/draw/away; TOTAL = full-time total goals.
MARKETS: dict[str, dict[str, list[str]]] = {
    "1X2": {
        "pinnacle": [r"Moneyline"],
        "betfair": [r"Match Odds"],
        "ladbrokes": [r"Match Result"],
        "unibet": [r"Full Time"],
        "sportsbet": [r"Win-Draw-Win"],
        "pointsbet": [r"Match Result"],
        "betr": [r"Match Result"],
        "betright": [r"Match Result"],
        "palmerbet": [r"Fulltime Match Result"],
    },
    "TOTAL": {
        "pinnacle": [r"Total", r"Total \(alt\)"],  # (alt) = not Pinnacle's main line
        "betfair": [r"Over/Under [\d.]+ Goals"],
        "ladbrokes": [r"Over/Under Total Goals [\d.]+"],
        "unibet": [r"Total Goals"],
        "sportsbet": [r"Over/Under [\d.]+ Goals"],
    },
}

# Every selection a market kind needs before it can be devigged / arbed.
MARKET_SELECTIONS: dict[str, tuple[str, ...]] = {
    "1X2": ("home", "draw", "away"),
    "TOTAL": ("over", "under"),
}


# League slug -> regexes over the normalised competition name, tried on the
# bare name and on "<region> <name>" (some books, e.g. BetRight, put the
# country in a separate field). Anchored so "Brazil Serie A", "Austrian
# Bundesliga" or "Scottish Championship" don't match.
_EN = r"(english |england |england - |efl )?(sky bet )?"
LEAGUE_PATTERNS: dict[str, list[str]] = {
    "england_premier_league": [rf"^{_EN}premier league$", r"^epl$"],
    "england_championship": [rf"^{_EN}(the )?championship$"],
    "england_league_one": [rf"^{_EN}league (one|1)$"],
    "italy_serie_a": [r"^(italian |italy |italy - )?serie a$"],
    "italy_serie_b": [r"^(italian |italy |italy - )?serie b$"],
    "spain_la_liga": [r"^(spanish |spain |spain - )?(la ?liga|primera division)$"],
    "spain_segunda": [r"^(spanish |spain |spain - )?(la ?liga 2|segunda( division)?|la ?liga hypermotion)$"],
    "germany_bundesliga": [r"^(german |germany |germany - )?bundesliga$"],
    "germany_2_bundesliga": [r"^(german |germany |germany - )?(2\.? ?bundesliga|bundesliga 2|second bundesliga)$"],
    "france_ligue_1": [r"^(french |france |france - )?ligue 1$"],
    "france_ligue_2": [r"^(french |france |france - )?ligue 2$"],
    "portugal_primeira_liga": [r"^(portuguese |portugal |portugal - )?(primeira liga|liga portugal( betclic)?)$"],
    "belgium_pro_league": [r"^(belgian |belgium |belgium - )(pro league|first division a|jupiler (pro )?league)$"],
    "netherlands_eredivisie": [r"^(dutch |netherlands |netherlands - |holland )?eredivisie$"],
    "turkey_super_lig": [r"^(turkish |turkey |turkey - |turkiye )(super lig|super league)$", r"^super lig$"],
}
_COMPILED = {slug: [re.compile(p) for p in pats] for slug, pats in LEAGUE_PATTERNS.items()}

# Unibet filter paths per league (its sport-wide soccer view is truncated).
UNIBET_PATHS: dict[str, list[str]] = {
    "england_premier_league": ["football/england/premier_league"],
    "england_championship": ["football/england/the_championship"],
    "england_league_one": ["football/england/league_one"],
    "italy_serie_a": ["football/italy/serie_a"],
    "italy_serie_b": ["football/italy/serie_b"],
    "spain_la_liga": ["football/spain/la_liga"],
    "spain_segunda": ["football/spain/la_liga_2"],
    "germany_bundesliga": ["football/germany/bundesliga"],
    "germany_2_bundesliga": ["football/germany/2__bundesliga"],
    "france_ligue_1": ["football/france/ligue_1"],
    "france_ligue_2": ["football/france/ligue_2"],
    "portugal_primeira_liga": ["football/portugal/primeira_liga"],
    # Unverified (no fixtures listed when written); several candidates tried.
    "belgium_pro_league": ["football/belgium/pro_league", "football/belgium/jupiler_pro_league",
                           "football/belgium/first_division_a"],
    "netherlands_eredivisie": ["football/netherlands/eredivisie"],
    "turkey_super_lig": ["football/turkey/super_lig"],
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.replace("ı", "i")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.\- ]", " ", s)).strip()


# A bare competition name ("Serie A") only counts when the book's region is
# missing, generic, or this league's country; otherwise "Serie A" under Brazil
# would match. Includes Betfair's ISO-3 region codes.
_COUNTRY = {
    "england": {"england", "english", "united kingdom", "uk", "uk ireland", "great britain", "gbr", "eng"},
    "italy": {"italy", "italian", "ita"},
    "spain": {"spain", "spanish", "esp"},
    "germany": {"germany", "german", "deu", "ger"},
    "france": {"france", "french", "fra"},
    "portugal": {"portugal", "portuguese", "prt", "por"},
    "belgium": {"belgium", "belgian", "bel"},
    "netherlands": {"netherlands", "dutch", "holland", "nld", "ned"},
    "turkey": {"turkey", "turkish", "turkiye", "tur"},
}
_GENERIC_REGIONS = {"featured", "popular", "top leagues", "international", "europe", "world", "futures outrights"}


def league_filter(leagues: list[str]):
    """Competition filter for the scrapers: returns the league slug or None."""
    wanted = {s: _COMPILED[s] for s in leagues}

    def match(name: str, region: str | None = None) -> str | None:
        r = _norm(region) if region else ""
        for slug, pats in wanted.items():
            country = _COUNTRY[slug.split("_")[0]]
            variants = [_norm(f"{region} {name}")] if region else []
            if not r or r in _GENERIC_REGIONS or r in country:
                variants.append(_norm(name))
            if any(p.match(v) for p in pats for v in variants):
                return slug
        return None

    return match
