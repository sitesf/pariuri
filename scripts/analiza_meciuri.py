# -*- coding: utf-8 -*-
"""
Analiza meciuri pentru azi si maine.
Genereaza pana la 10 pronosticuri reale, alegand pentru fiecare meci
piata cu cea mai mare incredere dintre: 1X2, GG/NG (solist), Peste/Sub 2.5 goluri.

Surse:
- API-Football (https://www.api-football.com) - fixtures, standings, statistici echipe.
- The Odds API (https://the-odds-api.com) - cote H2H reale (optional).

Daca nu sunt meciuri reale care trec filtrele, lista iese goala. Nu inventeaza.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    LOCAL_TZ = ZoneInfo("Europe/Bucharest")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=3))  # fallback EEST


# ---------- Configurare ----------

OUTPUT_FILE = "meciuri.json"

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()

API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

# Numar maxim de meciuri afisate.
MAX_MATCHES = 10
# Azi + maine.
DAYS_AHEAD = 2
# Prag minim de incredere pentru ca un pronostic sa intre in lista.
MIN_CONFIDENCE = 68
# Interval de cota acceptat (evita atat cote prea mici cat si prea mari).
ODDS_MIN = 1.30
ODDS_MAX = 2.30

# Ligi tinta pentru API-Football. Lista goala = toate ligile.
TARGET_LEAGUES = {
    2,    # UEFA Champions League
    3,    # UEFA Europa League
    848,  # UEFA Conference League
    39,   # Premier League
    140,  # LaLiga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    94,   # Primeira Liga
    88,   # Eredivisie
    203,  # Super Lig
    283,  # Liga 1 Romania
    40,   # Championship Anglia
    144,  # Pro League Belgia
    197,  # Super League Greek
}

# Chei The Odds API pentru competitiile principale.
ODDS_SPORT_KEYS = [
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_portugal_primeira_liga",
    "soccer_netherlands_eredivisie",
    "soccer_turkey_super_league",
]


# ---------- Utilitare ----------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_local_time(iso_string: str) -> str:
    if not iso_string:
        return ""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ).strftime("%H:%M")
    except Exception:
        return iso_string[11:16] if len(iso_string) >= 16 else ""


# ---------- API-Football ----------

def api_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not API_FOOTBALL_KEY:
        raise RuntimeError("Lipseste API_FOOTBALL_KEY in env / GitHub Secrets.")

    url = f"{API_FOOTBALL_BASE_URL}/{endpoint.lstrip('/')}"
    headers = {"x-apisports-key": API_FOOTBALL_KEY}

    response = requests.get(url, headers=headers, params=params or {}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"API-Football HTTP {response.status_code}: {response.text[:400]}")

    data = response.json()
    errors = data.get("errors")
    # API-Football returneaza {} sau [] cand nu sunt erori; non-empty = problema.
    if errors:
        if isinstance(errors, dict) and any(errors.values()):
            raise RuntimeError(f"API-Football errors: {errors}")
        if isinstance(errors, list) and len(errors) > 0:
            raise RuntimeError(f"API-Football errors: {errors}")

    return data


# ---------- The Odds API ----------

def odds_api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    if not ODDS_API_KEY:
        return []

    url = f"{ODDS_API_BASE_URL}/{path.lstrip('/')}"
    query = dict(params or {})
    query["apiKey"] = ODDS_API_KEY

    response = requests.get(url, params=query, timeout=30)
    if response.status_code != 200:
        print(f"The Odds API warning HTTP {response.status_code}: {response.text[:200]}")
        return []

    return response.json()


def normalize_name(name: str) -> str:
    clean = (name or "").lower()
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
    common = a_words & b_words
    return len(common) >= 1 and (len(common) / min(len(a_words), len(b_words))) >= 0.5


def decimal_odds_h2h(match: Dict[str, Any], home: str, away: str) -> Optional[Dict[str, float]]:
    for bookmaker in match.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            result: Dict[str, float] = {}
            for outcome in market.get("outcomes", []):
                price = outcome.get("price")
                if price is None:
                    continue
                outcome_name = outcome.get("name", "")
                if teams_match(outcome_name, home):
                    result["1"] = float(price)
                elif teams_match(outcome_name, away):
                    result["2"] = float(price)
                elif outcome_name.lower() in {"draw", "x", "egal"}:
                    result["X"] = float(price)
            if result:
                return result
    return None


def odds_map_for_range(start_date: datetime, days: int) -> Dict[str, Dict[str, float]]:
    mapped: Dict[str, Dict[str, float]] = {}
    if not ODDS_API_KEY:
        print("ODDS_API_KEY lipseste. Cotele 1X2 vor fi estimate.")
        return mapped

    start = start_date.date()
    end = (start_date + timedelta(days=days)).date()

    for sport_key in ODDS_SPORT_KEYS:
        data = odds_api_get(
            f"sports/{sport_key}/odds",
            {"regions": "eu", "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso"},
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
            prices = decimal_odds_h2h(match, home, away)
            if not prices:
                continue
            mapped[f"{normalize_name(home)}__{normalize_name(away)}"] = prices

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


# ---------- Cache standings + statistici echipe ----------

def get_standings_cached(league_id: int, season: int, cache: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    key = f"std_{league_id}_{season}"
    if key in cache:
        return cache[key]

    table: Dict[int, Dict[str, Any]] = {}
    try:
        data = api_get("standings", {"league": league_id, "season": season}).get("response", [])
        if data:
            standings_blocks = data[0].get("league", {}).get("standings", [])
            if standings_blocks:
                for row in standings_blocks[0]:
                    team_id = (row.get("team") or {}).get("id")
                    if team_id:
                        table[int(team_id)] = row
    except Exception as exc:
        print(f"Standings warning league {league_id}/{season}: {exc}")

    cache[key] = table
    return table


def get_team_stats_cached(league_id: int, season: int, team_id: int, cache: Dict[str, Any]) -> Dict[str, Any]:
    key = f"ts_{league_id}_{season}_{team_id}"
    if key in cache:
        return cache[key]

    data: Dict[str, Any] = {}
    try:
        data = api_get(
            "teams/statistics",
            {"league": league_id, "season": season, "team": team_id},
        ).get("response", {}) or {}
    except Exception as exc:
        print(f"Team stats warning team {team_id} league {league_id}: {exc}")

    cache[key] = data
    return data


# ---------- Pronosticuri ----------

def form_points(form: str) -> int:
    points = 0
    for char in (form or "")[-5:]:
        if char == "W":
            points += 3
        elif char == "D":
            points += 1
    return points


def estimate_odds_for_market(market: str, confidence: int) -> float:
    """Cota estimata cand nu avem oferta reala de la bookmaker."""
    if market in ("1", "2"):
        if confidence >= 82: return 1.45
        if confidence >= 76: return 1.60
        if confidence >= 70: return 1.75
        if confidence >= 64: return 1.90
        return 2.05
    if market == "GG":
        if confidence >= 78: return 1.55
        if confidence >= 70: return 1.70
        return 1.85
    if market == "NG":
        if confidence >= 78: return 1.75
        if confidence >= 70: return 1.90
        return 2.05
    if market == "Peste 2.5":
        if confidence >= 78: return 1.55
        if confidence >= 70: return 1.70
        return 1.90
    if market == "Sub 2.5":
        if confidence >= 78: return 1.65
        if confidence >= 70: return 1.80
        return 2.00
    return 1.95


def build_predictions_1x2(home_row: Dict, away_row: Dict, odds_prices: Optional[Dict[str, float]]) -> List[Dict[str, Any]]:
    """Pronosticuri 1 sau 2 pe baza de clasament + forma."""
    options: List[Dict[str, Any]] = []

    rank_home = safe_int(home_row.get("rank"), 99)
    rank_away = safe_int(away_row.get("rank"), 99)

    points_home = form_points(home_row.get("form", "") or "")
    points_away = form_points(away_row.get("form", "") or "")

    rank_advantage = max(min(rank_away - rank_home, 14), -14)
    form_advantage = points_home - points_away

    score_home = 50 + (rank_advantage * 2.0) + (form_advantage * 2.2) + 5  # +5 avantaj teren
    score_away = 50 + (-rank_advantage * 2.0) + (-form_advantage * 2.2)

    if score_home > score_away:
        conf = int(max(50, min(92, score_home)))
        cota = (odds_prices or {}).get("1") or estimate_odds_for_market("1", conf)
        options.append({
            "tip_pariu": "1X2",
            "pronostic": "1",
            "scor_incredere": conf,
            "cota": round(float(cota), 2),
            "motiv": (
                f"Gazdele: rang {rank_home} vs {rank_away}, forma "
                f"{points_home}p vs {points_away}p in ultimele 5."
            ),
        })
    else:
        conf = int(max(50, min(92, score_away)))
        cota = (odds_prices or {}).get("2") or estimate_odds_for_market("2", conf)
        options.append({
            "tip_pariu": "1X2",
            "pronostic": "2",
            "scor_incredere": conf,
            "cota": round(float(cota), 2),
            "motiv": (
                f"Oaspetii: rang {rank_away} vs {rank_home}, forma "
                f"{points_away}p vs {points_home}p in ultimele 5."
            ),
        })

    return options


def build_predictions_goals(home_stats: Dict, away_stats: Dict) -> List[Dict[str, Any]]:
    """GG / NG (solist) si Peste/Sub 2.5 goluri pe baza statisticilor sezonului."""
    options: List[Dict[str, Any]] = []

    if not home_stats or not away_stats:
        return options

    h_goals = home_stats.get("goals", {}) or {}
    a_goals = away_stats.get("goals", {}) or {}

    h_for_home = safe_float(((h_goals.get("for") or {}).get("average") or {}).get("home"))
    h_against_home = safe_float(((h_goals.get("against") or {}).get("average") or {}).get("home"))
    a_for_away = safe_float(((a_goals.get("for") or {}).get("average") or {}).get("away"))
    a_against_away = safe_float(((a_goals.get("against") or {}).get("average") or {}).get("away"))

    # Daca nu avem nicio medie, ne oprim.
    if h_for_home == 0 and a_for_away == 0 and h_against_home == 0 and a_against_away == 0:
        return options

    # xG estimat: media intre atacul echipei A si apararea echipei B.
    xg_home = ((h_for_home + a_against_away) / 2) if (h_for_home and a_against_away) else max(h_for_home, a_against_away)
    xg_away = ((a_for_away + h_against_home) / 2) if (a_for_away and h_against_home) else max(a_for_away, h_against_home)
    total_xg = xg_home + xg_away

    # Failed-to-score si clean-sheets.
    fts_h = home_stats.get("failed_to_score", {}) or {}
    fts_a = away_stats.get("failed_to_score", {}) or {}
    cs_h = home_stats.get("clean_sheet", {}) or {}
    cs_a = away_stats.get("clean_sheet", {}) or {}

    played_h = ((home_stats.get("fixtures") or {}).get("played") or {})
    played_a = ((away_stats.get("fixtures") or {}).get("played") or {})

    games_home_h = max(safe_int(played_h.get("home")), 1)
    games_away_a = max(safe_int(played_a.get("away")), 1)

    fts_home_rate = safe_int(fts_h.get("home")) / games_home_h
    fts_away_rate = safe_int(fts_a.get("away")) / games_away_a
    cs_home_rate = safe_int(cs_h.get("home")) / games_home_h
    cs_away_rate = safe_int(cs_a.get("away")) / games_away_a

    # ---- GG (ambele echipe inscriu) ----
    if xg_home >= 1.05 and xg_away >= 1.0 and fts_home_rate < 0.30 and fts_away_rate < 0.40:
        gg_score = 55 + min(20, (xg_home + xg_away - 2.0) * 12) + (1 - max(fts_home_rate, fts_away_rate)) * 8
        gg_conf = int(max(50, min(85, gg_score)))
        if gg_conf >= MIN_CONFIDENCE:
            options.append({
                "tip_pariu": "GG / NG",
                "pronostic": "GG (ambele inscriu)",
                "scor_incredere": gg_conf,
                "cota": round(estimate_odds_for_market("GG", gg_conf), 2),
                "motiv": (
                    f"Gazde acasa marcheaza {h_for_home:.2f}/meci, oaspeti deplasare {a_for_away:.2f}/meci. "
                    f"FTS rate: {fts_home_rate:.0%} vs {fts_away_rate:.0%}."
                ),
            })

    # ---- NG / Solist (cel mult o echipa inscrie) ----
    if (xg_home < 0.85 or xg_away < 0.80) and (fts_home_rate > 0.30 or fts_away_rate > 0.40 or cs_home_rate > 0.40 or cs_away_rate > 0.30):
        ng_score = 55 + (cs_home_rate + cs_away_rate) * 18 + (fts_home_rate + fts_away_rate) * 14
        ng_conf = int(max(50, min(82, ng_score)))
        if ng_conf >= MIN_CONFIDENCE:
            options.append({
                "tip_pariu": "GG / NG (Solist)",
                "pronostic": "NG (cel mult o echipa inscrie)",
                "scor_incredere": ng_conf,
                "cota": round(estimate_odds_for_market("NG", ng_conf), 2),
                "motiv": (
                    f"xG estimat: {xg_home:.2f} vs {xg_away:.2f}. "
                    f"Clean sheets: {cs_home_rate:.0%} acasa, {cs_away_rate:.0%} deplasare."
                ),
            })

    # ---- Peste 2.5 goluri ----
    if total_xg >= 2.85:
        over_score = 50 + (total_xg - 2.5) * 22 - max(fts_home_rate, fts_away_rate) * 10
        over_conf = int(max(50, min(85, over_score)))
        if over_conf >= MIN_CONFIDENCE:
            options.append({
                "tip_pariu": "Goluri",
                "pronostic": "Peste 2.5",
                "scor_incredere": over_conf,
                "cota": round(estimate_odds_for_market("Peste 2.5", over_conf), 2),
                "motiv": (
                    f"Goluri asteptate combinat: {total_xg:.2f}. "
                    f"({xg_home:.2f} gazde + {xg_away:.2f} oaspeti)"
                ),
            })

    # ---- Sub 2.5 goluri ----
    if total_xg <= 2.05:
        under_score = 50 + (2.5 - total_xg) * 26 + (cs_home_rate + cs_away_rate) * 8
        under_conf = int(max(50, min(82, under_score)))
        if under_conf >= MIN_CONFIDENCE:
            options.append({
                "tip_pariu": "Goluri",
                "pronostic": "Sub 2.5",
                "scor_incredere": under_conf,
                "cota": round(estimate_odds_for_market("Sub 2.5", under_conf), 2),
                "motiv": (
                    f"Goluri asteptate combinat: {total_xg:.2f}. "
                    f"Apararile: clean sheets {cs_home_rate:.0%}/{cs_away_rate:.0%}."
                ),
            })

    return options


def build_all_predictions(
    home_row: Dict,
    away_row: Dict,
    home_stats: Dict,
    away_stats: Dict,
    odds_prices: Optional[Dict[str, float]],
) -> List[Dict[str, Any]]:
    options = []
    options.extend(build_predictions_1x2(home_row, away_row, odds_prices))
    options.extend(build_predictions_goals(home_stats, away_stats))
    return options


# ---------- Agregare meciuri ----------

def collect_matches() -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    standings_cache: Dict[str, Any] = {}
    team_stats_cache: Dict[str, Any] = {}

    start_date = datetime.now(timezone.utc)
    odds = odds_map_for_range(start_date, days=DAYS_AHEAD)

    for day_offset in range(DAYS_AHEAD):
        target_date = (start_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        try:
            fixtures = api_get("fixtures", {"date": target_date}).get("response", [])
        except Exception as exc:
            print(f"Fixtures fetch failed for {target_date}: {exc}")
            continue

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
            status_short = ((fixture.get("status") or {}).get("short") or "")
            # Numai meciuri care nu au inceput inca.
            if status_short and status_short not in ("NS", "TBD"):
                continue

            teams = item.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            home_id = home.get("id")
            away_id = away.get("id")
            if not fixture_id or not home_id or not away_id:
                continue

            table = get_standings_cached(int(league_id), int(season), standings_cache)
            home_row = table.get(int(home_id))
            away_row = table.get(int(away_id))
            if not home_row or not away_row:
                continue  # ex: cupe, fara clasament direct

            home_stats = get_team_stats_cached(int(league_id), int(season), int(home_id), team_stats_cache)
            away_stats = get_team_stats_cached(int(league_id), int(season), int(away_id), team_stats_cache)

            home_name = home.get("name", "")
            away_name = away.get("name", "")
            match_odds = find_odds(odds, home_name, away_name)

            candidates = build_all_predictions(home_row, away_row, home_stats, away_stats, match_odds)
            if not candidates:
                continue

            # Cea mai buna predictie pentru acest meci.
            best = max(candidates, key=lambda x: x["scor_incredere"])

            # Filtre finale.
            if best["scor_incredere"] < MIN_CONFIDENCE:
                continue
            if not (ODDS_MIN <= best["cota"] <= ODDS_MAX):
                continue

            match_iso = fixture.get("date", "")

            output.append({
                "data": target_date,
                "fixture_id": fixture_id,
                "home": home_name,
                "away": away_name,
                "liga": f"{league.get('name', '')} · {league.get('country', '')}".strip(" ·"),
                "ora": format_local_time(match_iso),
                "forma_home": (home_row.get("form", "") or "")[-5:],
                "forma_away": (away_row.get("form", "") or "")[-5:],
                "tip_pariu": best["tip_pariu"],
                "pronostic": best["pronostic"],
                "cota": best["cota"],
                "scor_incredere": best["scor_incredere"],
                "motiv": best["motiv"],
                "alternative": [
                    {
                        "tip_pariu": opt["tip_pariu"],
                        "pronostic": opt["pronostic"],
                        "cota": opt["cota"],
                        "scor_incredere": opt["scor_incredere"],
                    }
                    for opt in candidates if opt is not best
                ],
            })

    # Sortare: incredere desc, apoi cota desc (pentru aceeasi incredere preferam cota mai mare).
    output.sort(key=lambda x: (x.get("scor_incredere", 0), x.get("cota", 0)), reverse=True)
    return output[:MAX_MATCHES]


# ---------- Main ----------

def main() -> None:
    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc) + timedelta(days=DAYS_AHEAD - 1)).strftime("%Y-%m-%d")

    matches: List[Dict[str, Any]] = []
    error_msg: Optional[str] = None

    try:
        matches = collect_matches()
        if matches:
            source_status = f"date reale: {len(matches)} meci(uri)"
        else:
            source_status = "date reale, dar niciun meci nu trece filtrele de incredere/cota azi-maine"
    except Exception as exc:
        error_msg = str(exc)
        source_status = f"eroare API: {exc}"
        print(f"Collection failed: {exc}")

    payload = {
        "data_start": start_date,
        "data_final": end_date,
        "updated_at": now_iso(),
        "sursa": "API-Football + The Odds API",
        "status_date": source_status,
        "numar_meciuri": len(matches),
        "configuratie": {
            "max_meciuri": MAX_MATCHES,
            "zile_inainte": DAYS_AHEAD,
            "incredere_minima": MIN_CONFIDENCE,
            "cota_min": ODDS_MIN,
            "cota_max": ODDS_MAX,
            "piete": ["1X2", "GG / NG (Solist)", "Peste 2.5 / Sub 2.5 goluri"],
        },
        "meciuri": matches,
    }
    if error_msg:
        payload["eroare"] = error_msg

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    print(f"Scris {OUTPUT_FILE} cu {len(matches)} meciuri. Status: {source_status}")


if __name__ == "__main__":
    main()
