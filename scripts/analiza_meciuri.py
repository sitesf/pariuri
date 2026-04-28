import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
API_FOOTBALL_HOST = os.getenv("API_FOOTBALL_HOST", "v3.football.api-sports.io")
OUTPUT_FILE = "meciuri.json"
TARGET_LEAGUES = [39, 140, 135, 78, 61, 2, 3, 848]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def api_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if not API_FOOTBALL_KEY:
        raise RuntimeError("API_FOOTBALL_KEY lipseste")
    response = requests.get(
        f"https://{API_FOOTBALL_HOST}/{path}",
        headers={"x-apisports-key": API_FOOTBALL_KEY},
        params=params,
        timeout=45,
    )
    response.raise_for_status()
    return response.json()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def form_score(form: str) -> float:
    form = (form or "")[-5:].upper()
    points = 0
    for result in form:
        if result == "W":
            points += 3
        elif result == "D":
            points += 1
    return points / 15 if form else 0.5


def standings_map(league_id: int, season: int) -> Dict[int, Dict[str, Any]]:
    data = api_get("standings", {"league": league_id, "season": season})
    result: Dict[int, Dict[str, Any]] = {}
    blocks = data.get("response", [])
    if not blocks:
        return result
    for group in blocks[0].get("league", {}).get("standings", []):
        for row in group:
            team_id = row.get("team", {}).get("id")
            if team_id:
                result[int(team_id)] = row
    return result


def team_value_proxy(row: Dict[str, Any]) -> float:
    all_stats = row.get("all", {})
    goals_for = safe_float(all_stats.get("goals", {}).get("for"))
    goals_against = safe_float(all_stats.get("goals", {}).get("against"))
    points = safe_float(row.get("points"))
    rank = safe_float(row.get("rank"), 20)
    return (points * 1.35) + (goals_for * 0.65) - (goals_against * 0.45) + max(0, 22 - rank)


def odds_map(date_str: str) -> Dict[int, Dict[str, Any]]:
    try:
        data = api_get("odds", {"date": date_str, "bookmaker": 8, "bet": 1})
    except Exception as exc:
        print(f"Odds unavailable: {exc}")
        return {}
    mapped: Dict[int, Dict[str, Any]] = {}
    for item in data.get("response", []):
        fixture_id = item.get("fixture", {}).get("id")
        bookmakers = item.get("bookmakers", [])
        if not fixture_id or not bookmakers:
            continue
        values = bookmakers[0].get("bets", [{}])[0].get("values", [])
        mapped[int(fixture_id)] = {v.get("value"): safe_float(v.get("odd")) for v in values}
    return mapped


def pick_prediction(home_row: Dict[str, Any], away_row: Dict[str, Any], odd_values: Dict[str, float]) -> Optional[Dict[str, Any]]:
    home_rank = safe_float(home_row.get("rank"), 20)
    away_rank = safe_float(away_row.get("rank"), 20)
    home_form = form_score(home_row.get("form", ""))
    away_form = form_score(away_row.get("form", ""))
    home_value = team_value_proxy(home_row)
    away_value = team_value_proxy(away_row)

    rank_component = max(min((away_rank - home_rank) / 18, 1), -1)
    form_component = home_form - away_form
    value_component = max(min((home_value - away_value) / 45, 1), -1)
    home_advantage = 0.10

    score_home = 0.48 + (rank_component * 0.18) + (form_component * 0.22) + (value_component * 0.17) + home_advantage
    score_away = 0.48 - (rank_component * 0.18) - (form_component * 0.22) - (value_component * 0.17)

    if score_home >= score_away:
        pick = "1"
        raw_score = score_home
        odd = odd_values.get("Home") or odd_values.get("1") or 1.0
    else:
        pick = "2"
        raw_score = score_away
        odd = odd_values.get("Away") or odd_values.get("2") or 1.0

    confidence = int(max(50, min(92, raw_score * 100)))
    odd = safe_float(odd, 1.0)

    if confidence < 80 or odd < 1.35:
        return None

    return {
        "pronostic": pick,
        "cota": round(odd, 2),
        "scor_incredere": confidence,
        "forma_home_score": round(home_form, 2),
        "forma_away_score": round(away_form, 2),
        "valoare_home_proxy": round(home_value, 2),
        "valoare_away_proxy": round(away_value, 2),
        "rank_home": int(home_rank),
        "rank_away": int(away_rank),
    }


def collect_matches() -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    standings_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}

    for day_offset in range(5):
        target_date = (datetime.now(timezone.utc) + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        fixtures = api_get("fixtures", {"date": target_date}).get("response", [])
        odds = odds_map(target_date)

        for item in fixtures:
        league = item.get("league", {})
        league_id = league.get("id")
        season = league.get("season")
        if TARGET_LEAGUES and league_id not in TARGET_LEAGUES:
            continue

        home = item.get("teams", {}).get("home", {})
        away = item.get("teams", {}).get("away", {})
        home_id = home.get("id")
        away_id = away.get("id")
        fixture_id = item.get("fixture", {}).get("id")
        if not all([league_id, season, home_id, away_id, fixture_id]):
            continue

        cache_key = f"{league_id}-{season}"
        if cache_key not in standings_cache:
            try:
                standings_cache[cache_key] = standings_map(int(league_id), int(season))
            except Exception as exc:
                print(f"Standings failed for {cache_key}: {exc}")
                standings_cache[cache_key] = {}

        table = standings_cache[cache_key]
        home_row = table.get(int(home_id))
        away_row = table.get(int(away_id))
        if not home_row or not away_row:
            continue

        prediction = pick_prediction(home_row, away_row, odds.get(int(fixture_id), {}))
        if not prediction:
            continue

        match_time = item.get("fixture", {}).get("date", "")
        output.append({
            "fixture_id": fixture_id,
            "home": home.get("name", ""),
            "away": away.get("name", ""),
            "liga": f"{league.get('name', '')} · {league.get('country', '')}",
            "ora": match_time[11:16] if len(match_time) >= 16 else "",
            "forma_home": home_row.get("form", "")[-5:],
            "forma_away": away_row.get("form", "")[-5:],
            "motiv": f"Diferenta rang: {prediction['rank_home']} vs {prediction['rank_away']}. Forma si valoarea proxy favorizeaza selectia {prediction['pronostic']}.",
            **prediction,
        })

    output.sort(key=lambda x: (x["scor_incredere"], x["cota"]), reverse=True)
    balanced = [m for m in output if 1.50 <= safe_float(m.get("cota")) <= 2.60]
    remaining = [m for m in output if m not in balanced]
    return (balanced + remaining)[:20]


def fallback_matches() -> List[Dict[str, Any]]:
    samples = []
    names = [
        ("Arsenal", "Everton", "Premier League · England", "1", 1.72, 84),
        ("Inter", "Genoa", "Serie A · Italy", "1", 1.58, 86),
        ("Barcelona", "Valencia", "LaLiga · Spain", "1", 1.65, 85),
        ("PSG", "Lille", "Ligue 1 · France", "1", 1.70, 83),
        ("Bayern", "Mainz", "Bundesliga · Germany", "1", 1.50, 87),
    ]
    for index, item in enumerate(names, start=1):
        samples.append({
            "fixture_id": index,
            "home": item[0],
            "away": item[1],
            "liga": item[2],
            "ora": "18:00",
            "pronostic": item[3],
            "cota": item[4],
            "scor_incredere": item[5],
            "forma_home": "WWDWW",
            "forma_away": "LDLWD",
            "motiv": "Exemplu local. Configureaza API_FOOTBALL_KEY pentru date reale.",
        })
    return samples


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        matches = collect_matches()
        source_status = "date reale"
    except Exception as exc:
        print(f"API-Football failed, using fallback: {exc}")
        matches = fallback_matches()
        source_status = f"fallback local: {exc}"

    payload = {
        "data_meciuri": today,
        "updated_at": now_iso(),
        "sursa": "API-Football + The Odds API",
        "status_date": source_status,
        "meciuri": matches,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
