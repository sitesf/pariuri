import json
import os
import random
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests


OUTPUT_FILE = "meciuri.json"

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()

API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

# Ligi principale API-Football.
# Daca vrei mai multe meciuri, poti lasa lista goala: TARGET_LEAGUES = set()
TARGET_LEAGUES = {
    2,    # UEFA Champions League
    3,    # UEFA Europa League
    39,   # Premier League
    140,  # LaLiga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    94,   # Primeira Liga
    88,   # Eredivisie
    203,  # Super Lig
    283,  # Liga 1 Romania
}

# The Odds API foloseste chei diferite pentru competitii.
ODDS_SPORT_KEYS = [
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_portugal_primeira_liga",
    "soccer_netherlands_eredivisie",
    "soccer_turkey_super_league",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def api_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not API_FOOTBALL_KEY:
        raise RuntimeError("Lipseste API_FOOTBALL_KEY in GitHub Secrets.")

    url = f"{API_FOOTBALL_BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "x-apisports-key": API_FOOTBALL_KEY,
    }

    response = requests.get(url, headers=headers, params=params or {}, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(f"API-Football HTTP {response.status_code}: {response.text[:500]}")

    data = response.json()

    errors = data.get("errors")
    if errors:
        raise RuntimeError(f"API-Football errors: {errors}")

    return data


def odds_api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    if not ODDS_API_KEY:
        return []

    url = f"{ODDS_API_BASE_URL}/{path.lstrip('/')}"
    query = dict(params or {})
    query["apiKey"] = ODDS_API_KEY

    response = requests.get(url, params=query, timeout=30)

    if response.status_code != 200:
        print(f"The Odds API warning HTTP {response.status_code}: {response.text[:300]}")
        return []

    return response.json()


def normalize_name(name: str) -> str:
    clean = name.lower()
    for token in [" fc", " cf", " afc", " sc", ".", "-", "_"]:
        clean = clean.replace(token, " ")
    return " ".join(clean.split())


def teams_match(name_a: str, name_b: str) -> bool:
    a = normalize_name(name_a)
    b = normalize_name(name_b)

    if not a or not b:
        return False

    if a == b:
        return True

    a_words = set(a.split())
    b_words = set(b.split())

    if not a_words or not b_words:
        return False

    common = a_words.intersection(b_words)
    return len(common) >= 1 and (len(common) / min(len(a_words), len(b_words))) >= 0.5


def decimal_odds_from_bookmakers(match: Dict[str, Any], home: str, away: str) -> Optional[Dict[str, float]]:
    for bookmaker in match.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue

            result = {}
            for outcome in market.get("outcomes", []):
                outcome_name = outcome.get("name", "")
                price = outcome.get("price")

                if price is None:
                    continue

                if teams_match(outcome_name, home):
                    result["1"] = float(price)
                elif teams_match(outcome_name, away):
                    result["2"] = float(price)
                elif outcome_name.lower() in {"draw", "x", "egal"}:
                    result["X"] = float(price)

            if result:
                return result

    return None


def odds_map_for_range(start_date: datetime, days: int = 5) -> Dict[str, Dict[str, float]]:
    mapped: Dict[str, Dict[str, float]] = {}

    if not ODDS_API_KEY:
        print("ODDS_API_KEY lipseste. Scriptul va folosi cote estimate.")
        return mapped

    start = start_date.date()
    end = (start_date + timedelta(days=days)).date()

    for sport_key in ODDS_SPORT_KEYS:
        data = odds_api_get(
            f"sports/{sport_key}/odds",
            {
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
        )

        if not isinstance(data, list):
            continue

        for match in data:
            commence_time = match.get("commence_time", "")
            try:
                match_date = datetime.fromisoformat(commence_time.replace("Z", "+00:00")).date()
            except Exception:
                continue

            if match_date < start or match_date > end:
                continue

            home = match.get("home_team", "")
            away = match.get("away_team", "")

            prices = decimal_odds_from_bookmakers(match, home, away)
            if not prices:
                continue

            key = f"{normalize_name(home)}__{normalize_name(away)}"
            mapped[key] = prices

    return mapped


def find_odds(odds: Dict[str, Dict[str, float]], home: str, away: str) -> Optional[Dict[str, float]]:
    direct_key = f"{normalize_name(home)}__{normalize_name(away)}"
    if direct_key in odds:
        return odds[direct_key]

    for key, prices in odds.items():
        try:
            odd_home, odd_away = key.split("__", 1)
        except ValueError:
            continue

        if teams_match(home, odd_home) and teams_match(away, odd_away):
            return prices

    return None


def get_standings_cached(
    league_id: int,
    season: int,
    cache: Dict[str, Dict[int, Dict[str, Any]]],
) -> Dict[int, Dict[str, Any]]:
    cache_key = f"{league_id}_{season}"

    if cache_key in cache:
        return cache[cache_key]

    data = api_get("standings", {"league": league_id, "season": season}).get("response", [])
    table: Dict[int, Dict[str, Any]] = {}

    if data:
        standings_blocks = data[0].get("league", {}).get("standings", [])
        if standings_blocks:
            for row in standings_blocks[0]:
                team = row.get("team", {})
                team_id = team.get("id")
                if team_id:
                    table[int(team_id)] = row

    cache[cache_key] = table
    return table


def form_points(form: str) -> int:
    points = 0
    for char in (form or "")[-5:]:
        if char == "W":
            points += 3
        elif char == "D":
            points += 1
    return points


def estimate_odds(confidence: int) -> float:
    if confidence >= 82:
        return 1.45
    if confidence >= 76:
        return 1.60
    if confidence >= 70:
        return 1.75
    if confidence >= 64:
        return 1.90
    return 2.05


def build_prediction(
    home_row: Dict[str, Any],
    away_row: Dict[str, Any],
    odds_prices: Optional[Dict[str, float]],
) -> Dict[str, Any]:
    rank_home = int(home_row.get("rank") or 99)
    rank_away = int(away_row.get("rank") or 99)

    form_home = home_row.get("form", "") or ""
    form_away = away_row.get("form", "") or ""

    points_home = form_points(form_home)
    points_away = form_points(form_away)

    # Scor simplu si transparent.
    # Avantaj rang, forma si avantaj teren propriu.
    rank_advantage = max(min(rank_away - rank_home, 12), -12)
    form_advantage = points_home - points_away

    score_home = 50 + (rank_advantage * 2.2) + (form_advantage * 2.4) + 5
    score_away = 50 + (-rank_advantage * 2.2) + (-form_advantage * 2.4)

    if score_home >= score_away:
        pronostic = "1"
        confidence = int(max(50, min(92, score_home)))
    else:
        pronostic = "2"
        confidence = int(max(50, min(92, score_away)))

    cota = None
    if odds_prices and pronostic in odds_prices:
        cota = odds_prices[pronostic]

    if cota is None:
        cota = estimate_odds(confidence)

    return {
        "pronostic": pronostic,
        "cota": round(float(cota), 2),
        "scor_incredere": confidence,
        "rank_home": rank_home,
        "rank_away": rank_away,
    }


def fallback_matches(reason: str = "") -> List[Dict[str, Any]]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    examples = [
        ("Arsenal", "Everton", "Premier League · England", "1", 1.72, 84),
        ("Inter", "Genoa", "Serie A · Italy", "1", 1.58, 86),
        ("Barcelona", "Valencia", "LaLiga · Spain", "1", 1.65, 85),
        ("PSG", "Lille", "Ligue 1 · France", "1", 1.70, 83),
        ("Bayern", "Mainz", "Bundesliga · Germany", "1", 1.50, 87),
    ]

    return [
        {
            "data": today,
            "fixture_id": index,
            "home": home,
            "away": away,
            "liga": liga,
            "ora": "18:00",
            "pronostic": pronostic,
            "cota": cota,
            "scor_incredere": score,
            "forma_home": "WWDWW",
            "forma_away": "LDLWD",
            "motiv": f"Exemplu local. {reason or 'Configureaza API_FOOTBALL_KEY pentru date reale.'}",
        }
        for index, (home, away, liga, pronostic, cota, score) in enumerate(examples, start=1)
    ]


def collect_matches() -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    standings_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}

    start_date = datetime.now(timezone.utc)
    odds = odds_map_for_range(start_date, days=5)

    for day_offset in range(5):
        target_date = (start_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        fixtures = api_get("fixtures", {"date": target_date}).get("response", [])

        for item in fixtures:
            league = item.get("league", {})
            league_id = league.get("id")
            season = league.get("season")

            if not league_id or not season:
                continue

            if TARGET_LEAGUES and league_id not in TARGET_LEAGUES:
                continue

            fixture = item.get("fixture", {})
            fixture_id = fixture.get("id")

            teams = item.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            home_id = home.get("id")
            away_id = away.get("id")

            if not fixture_id or not home_id or not away_id:
                continue

            try:
                table = get_standings_cached(int(league_id), int(season), standings_cache)
            except Exception as exc:
                print(f"Standings warning for league {league_id}: {exc}")
                continue

            home_row = table.get(int(home_id))
            away_row = table.get(int(away_id))

            if not home_row or not away_row:
                continue

            home_name = home.get("name", "")
            away_name = away.get("name", "")
            match_odds = find_odds(odds, home_name, away_name)

            prediction = build_prediction(home_row, away_row, match_odds)

            # Filtru echilibrat. Accepta cote intre 1.30 si 2.30 si scor minim 60.
            if prediction["scor_incredere"] < 60:
                continue

            if not (1.30 <= prediction["cota"] <= 2.30):
                continue

            match_time = fixture.get("date", "")

            output.append(
                {
                    "data": target_date,
                    "fixture_id": fixture_id,
                    "home": home_name,
                    "away": away_name,
                    "liga": f"{league.get('name', '')} · {league.get('country', '')}",
                    "ora": match_time[11:16] if len(match_time) >= 16 else "",
                    "forma_home": (home_row.get("form", "") or "")[-5:],
                    "forma_away": (away_row.get("form", "") or "")[-5:],
                    "motiv": (
                        f"Diferenta rang: {prediction['rank_home']} vs {prediction['rank_away']}. "
                        f"Forma si clasamentul favorizeaza selectia {prediction['pronostic']}."
                    ),
                    **prediction,
                }
            )

    # Sorteaza dupa incredere, apoi dupa cota.
    output.sort(key=lambda x: (x.get("scor_incredere", 0), x.get("cota", 0)), reverse=True)

    return output[:20]


def main() -> None:
    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc) + timedelta(days=4)).strftime("%Y-%m-%d")

    try:
        matches = collect_matches()
        source_status = "date reale"

        if not matches:
            source_status = "date reale, dar niciun meci nu a trecut filtrele"
    except Exception as exc:
        print(f"API-Football failed, using fallback: {exc}")
        matches = fallback_matches(str(exc))
        source_status = f"fallback local: {exc}"

    payload = {
        "data_start": start_date,
        "data_final": end_date,
        "updated_at": now_iso(),
        "sursa": "API-Football + The Odds API",
        "status_date": source_status,
        "meciuri": matches,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
