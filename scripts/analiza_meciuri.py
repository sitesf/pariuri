# -*- coding: utf-8 -*-
"""
Analiza meciuri - pronosticuri pentru urmatoarele 5 zile.

Surse de date:
  1. API-Football (https://www.api-football.com)        - principal (fixtures, standings, statistici)
  2. football-data.org (https://www.football-data.org)  - backup pentru ligile top (12 competitii)
  3. The Odds API (https://the-odds-api.com)            - cote H2H reale de la bookmakeri
  4. Understat (https://understat.com)                  - xG real pentru top 5 ligi (scraping public)

Strategia de minim consum apeluri:
  - Cache pe disc (cache.json) cu TTL diferit per tip date
  - Fixtures intr-un singur apel pe interval (from/to), nu loop pe zile
  - football-data.org preluat pe ligile pe care le acopera
  - Understat scrapat o data pe sezon (TTL 7 zile)
  - Cele 3 bilete sugerate calculate din lista finala, fara apeluri suplimentare

Output: meciuri.json - lista de meciuri + 3 bilete pre-calculate.
Daca o sursa cade, scriptul continua cu ce are. Nu inventeaza meciuri.
"""

import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from itertools import combinations
from typing import Any, Dict, List, Optional

import requests

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/Bucharest")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=3))


# ============================================================
# CONFIGURARE
# ============================================================

OUTPUT_FILE = "meciuri.json"
CACHE_FILE = "cache.json"

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY", "").strip()

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
UNDERSTAT_BASE = "https://understat.com/league"

MAX_MATCHES = 10
DAYS_AHEAD = 5
MIN_CONFIDENCE = 65
ODDS_MIN = 1.30
ODDS_MAX = 2.30

CACHE_TTL = {
    "fixtures":    60 * 60,
    "standings":   24 * 60 * 60,
    "team_stats":  24 * 60 * 60,
    "fd_matches":  60 * 60,
    "fd_standings":24 * 60 * 60,
    "odds":        30 * 60,
    "understat":   7 * 24 * 60 * 60,
    "season":      24 * 60 * 60,
}

# (api_football_id, nume, code_football_data_org, slug_understat)
LEAGUES_CONFIG = [
    (39,  "Premier League",         "PL",  "EPL"),
    (140, "LaLiga",                 "PD",  "La_liga"),
    (135, "Serie A",                "SA",  "Serie_A"),
    (78,  "Bundesliga",             "BL1", "Bundesliga"),
    (61,  "Ligue 1",                "FL1", "Ligue_1"),
    (2,   "UEFA Champions League",  "CL",  None),
    (3,   "UEFA Europa League",     None,  None),
    (848, "UEFA Conference League", None,  None),
    (40,  "Championship",           "ELC", None),
    (88,  "Eredivisie",             "DED", None),
    (94,  "Primeira Liga",          "PPL", None),
    (203, "Super Lig",              None,  None),
    (144, "Pro League",             None,  None),
    (79,  "Bundesliga 2",           None,  None),
    (136, "Serie B",                None,  None),
    (141, "LaLiga 2",               None,  None),
    (62,  "Ligue 2",                None,  None),
    (197, "Super League Greece",    None,  None),
    (283, "Liga 1 Romania",         None,  None),
    (71,  "Brasileirao Serie A",    "BSA", None),
]

API_FOOTBALL_LEAGUES = {x[0]: x[1] for x in LEAGUES_CONFIG}
FD_BY_AF_ID = {x[0]: x[2] for x in LEAGUES_CONFIG if x[2]}
UNDERSTAT_BY_AF_ID = {x[0]: x[3] for x in LEAGUES_CONFIG if x[3]}

ODDS_SPORT_KEYS = [
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_spain_la_liga_2",
    "soccer_italy_serie_a",
    "soccer_italy_serie_b",
    "soccer_germany_bundesliga",
    "soccer_germany_bundesliga2",
    "soccer_france_ligue_one",
    "soccer_france_ligue_two",
    "soccer_portugal_primeira_liga",
    "soccer_netherlands_eredivisie",
    "soccer_turkey_super_league",
    "soccer_belgium_first_div",
    "soccer_efl_champ",
    "soccer_brazil_campeonato",
    "soccer_greece_super_league",
]


# ============================================================
# CACHE PE DISC
# ============================================================

class DiskCache:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as exc:
                print(f"[cache] read failed: {exc}")
                self.data = {}

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[cache] write failed: {exc}")

    def get(self, key: str) -> Optional[Any]:
        entry = self.data.get(key)
        if not entry:
            return None
        if time.time() > entry.get("expires_at", 0):
            return None
        return entry.get("value")

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.data[key] = {
            "value": value,
            "expires_at": time.time() + ttl_seconds,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

    def cleanup(self) -> None:
        now = time.time()
        keys_to_remove = [k for k, e in self.data.items() if now > e.get("expires_at", 0) + 7 * 24 * 60 * 60]
        for k in keys_to_remove:
            del self.data[k]


cache = DiskCache(CACHE_FILE)


# ============================================================
# UTILITARE
# ============================================================

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


def normalize_name(name: str) -> str:
    clean = (name or "").lower()
    for token in [" fc", " cf", " afc", " sc", ".", "-", "_", "'"]:
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


# ============================================================
# API-FOOTBALL
# ============================================================

def api_football_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not API_FOOTBALL_KEY:
        raise RuntimeError("Lipseste API_FOOTBALL_KEY in env / GitHub Secrets.")

    url = f"{API_FOOTBALL_BASE}/{endpoint.lstrip('/')}"
    headers = {"x-apisports-key": API_FOOTBALL_KEY}

    response = requests.get(url, headers=headers, params=params or {}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"API-Football HTTP {response.status_code}: {response.text[:300]}")

    data = response.json()
    errors = data.get("errors")
    if errors:
        if isinstance(errors, dict) and any(errors.values()):
            raise RuntimeError(f"API-Football errors: {errors}")
        if isinstance(errors, list) and len(errors) > 0:
            raise RuntimeError(f"API-Football errors: {errors}")
    return data


def _get_current_season(league_id: int) -> Optional[int]:
    cache_key = f"af_season_{league_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = api_football_get("leagues", {"id": league_id}).get("response", [])
        if not data:
            return None
        for s in data[0].get("seasons", []):
            if s.get("current"):
                year = safe_int(s.get("year"))
                cache.set(cache_key, year, CACHE_TTL["season"])
                return year
    except Exception as exc:
        print(f"[api-football] season detect fail liga {league_id}: {exc}")
    return None


def api_football_fixtures_range(date_from: str, date_to: str) -> List[Dict[str, Any]]:
    """3 nivele de fallback: global -> per liga -> per zi."""
    cache_key = f"af_fixtures_{date_from}_{date_to}"
    cached = cache.get(cache_key)
    if cached is not None:
        print(f"[cache HIT] api-football fixtures {date_from} - {date_to}")
        return cached

    # Nivel 1: apel global cu from/to
    try:
        data = api_football_get("fixtures", {
            "from": date_from, "to": date_to,
            "timezone": "Europe/Bucharest",
        }).get("response", [])
        if data:
            cache.set(cache_key, data, CACHE_TTL["fixtures"])
            print(f"[api-football] fixtures global: {len(data)} meciuri")
            return data
    except Exception as exc:
        print(f"[api-football] global from/to failed: {exc}")

    # Nivel 2: per liga din lista de 20
    try:
        all_fixtures: List[Dict[str, Any]] = []
        for league_id in API_FOOTBALL_LEAGUES.keys():
            try:
                season = _get_current_season(league_id)
                if not season:
                    continue
                resp = api_football_get("fixtures", {
                    "league": league_id, "season": season,
                    "from": date_from, "to": date_to,
                    "timezone": "Europe/Bucharest",
                }).get("response", [])
                all_fixtures.extend(resp)
            except Exception as exc:
                print(f"[api-football] liga {league_id}: {exc}")
                continue
        if all_fixtures:
            cache.set(cache_key, all_fixtures, CACHE_TTL["fixtures"])
            print(f"[api-football] fixtures per-liga: {len(all_fixtures)} meciuri")
            return all_fixtures
    except Exception as exc:
        print(f"[api-football] per-liga loop failed: {exc}")

    # Nivel 3: per zi
    print("[api-football] fallback final: per zi")
    all_fixtures = []
    start = datetime.strptime(date_from, "%Y-%m-%d")
    end = datetime.strptime(date_to, "%Y-%m-%d")
    cursor = start
    while cursor <= end:
        target = cursor.strftime("%Y-%m-%d")
        try:
            resp = api_football_get("fixtures", {
                "date": target, "timezone": "Europe/Bucharest",
            }).get("response", [])
            all_fixtures.extend(resp)
        except Exception as exc:
            print(f"[api-football] zi {target}: {exc}")
        cursor += timedelta(days=1)

    cache.set(cache_key, all_fixtures, CACHE_TTL["fixtures"])
    return all_fixtures


def api_football_standings(league_id: int, season: int) -> Dict[int, Dict[str, Any]]:
    cache_key = f"af_standings_{league_id}_{season}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    table: Dict[int, Dict[str, Any]] = {}
    try:
        data = api_football_get("standings", {"league": league_id, "season": season}).get("response", [])
        if data:
            blocks = data[0].get("league", {}).get("standings", [])
            if blocks:
                for row in blocks[0]:
                    team_id = (row.get("team") or {}).get("id")
                    if team_id:
                        table[int(team_id)] = row
    except Exception as exc:
        print(f"[api-football] standings fail liga {league_id}: {exc}")

    cache.set(cache_key, table, CACHE_TTL["standings"])
    return table


def api_football_team_stats(league_id: int, season: int, team_id: int) -> Dict[str, Any]:
    cache_key = f"af_teamstats_{league_id}_{season}_{team_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data: Dict[str, Any] = {}
    try:
        data = api_football_get("teams/statistics", {
            "league": league_id, "season": season, "team": team_id,
        }).get("response", {}) or {}
    except Exception as exc:
        print(f"[api-football] team stats fail t={team_id}: {exc}")

    cache.set(cache_key, data, CACHE_TTL["team_stats"])
    return data


# ============================================================
# FOOTBALL-DATA.ORG
# ============================================================

def fd_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not FOOTBALL_DATA_KEY:
        return {}
    url = f"{FOOTBALL_DATA_BASE}/{endpoint.lstrip('/')}"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    response = requests.get(url, headers=headers, params=params or {}, timeout=30)
    if response.status_code != 200:
        print(f"[football-data] HTTP {response.status_code}: {response.text[:200]}")
        return {}
    return response.json()


def fd_fixtures_index(date_from: str, date_to: str) -> Dict[str, Dict[str, Any]]:
    if not FOOTBALL_DATA_KEY:
        return {}
    cache_key = f"fd_matches_{date_from}_{date_to}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # dateTo e EXCLUSIV in football-data.org, deci adaugam +1 zi
    real_to = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    data = fd_get("matches", {"dateFrom": date_from, "dateTo": real_to})

    index: Dict[str, Dict[str, Any]] = {}
    for m in data.get("matches", []):
        home = (m.get("homeTeam") or {}).get("name", "")
        away = (m.get("awayTeam") or {}).get("name", "")
        if not home or not away:
            continue
        key = f"{normalize_name(home)}__{normalize_name(away)}"
        index[key] = m

    cache.set(cache_key, index, CACHE_TTL["fd_matches"])
    print(f"[football-data] fixtures index: {len(index)} meciuri")
    return index


def fd_find_match(index: Dict[str, Dict[str, Any]], home: str, away: str) -> Optional[Dict[str, Any]]:
    direct = index.get(f"{normalize_name(home)}__{normalize_name(away)}")
    if direct:
        return direct
    for key, payload in index.items():
        try:
            kh, ka = key.split("__", 1)
        except ValueError:
            continue
        if teams_match(home, kh) and teams_match(away, ka):
            return payload
    return None


# ============================================================
# THE ODDS API
# ============================================================

def odds_api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    if not ODDS_API_KEY:
        return []
    url = f"{ODDS_API_BASE}/{path.lstrip('/')}"
    query = dict(params or {})
    query["apiKey"] = ODDS_API_KEY
    response = requests.get(url, params=query, timeout=30)
    if response.status_code != 200:
        print(f"[the-odds-api] HTTP {response.status_code}: {response.text[:200]}")
        return []
    return response.json()


def odds_decimal_h2h(match: Dict[str, Any], home: str, away: str) -> Optional[Dict[str, float]]:
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


def odds_map_for_range(date_from: str, date_to: str) -> Dict[str, Dict[str, float]]:
    cache_key = f"odds_h2h_{date_from}_{date_to}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    mapped: Dict[str, Dict[str, float]] = {}
    if not ODDS_API_KEY:
        cache.set(cache_key, mapped, CACHE_TTL["odds"])
        return mapped

    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end = datetime.strptime(date_to, "%Y-%m-%d").date()

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
            prices = odds_decimal_h2h(match, home, away)
            if not prices:
                continue
            mapped[f"{normalize_name(home)}__{normalize_name(away)}"] = prices

    cache.set(cache_key, mapped, CACHE_TTL["odds"])
    print(f"[the-odds-api] cote H2H: {len(mapped)} meciuri")
    return mapped


def odds_find(odds_index: Dict[str, Dict[str, float]], home: str, away: str) -> Optional[Dict[str, float]]:
    direct = odds_index.get(f"{normalize_name(home)}__{normalize_name(away)}")
    if direct:
        return direct
    for key, prices in odds_index.items():
        try:
            kh, ka = key.split("__", 1)
        except ValueError:
            continue
        if teams_match(home, kh) and teams_match(away, ka):
            return prices
    return None


# ============================================================
# UNDERSTAT (xG real, scraping)
# ============================================================

def understat_team_xg(league_slug: str) -> Dict[str, Dict[str, float]]:
    cache_key = f"understat_{league_slug}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result: Dict[str, Dict[str, float]] = {}
    try:
        url = f"{UNDERSTAT_BASE}/{league_slug}"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; FootballAnalysis/1.0)"}
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"[understat] HTTP {response.status_code} la {league_slug}")
            cache.set(cache_key, result, CACHE_TTL["understat"])
            return result

        match = re.search(r"var\s+teamsData\s*=\s*JSON\.parse\('([^']+)'\)", response.text)
        if not match:
            print(f"[understat] teamsData lipseste pentru {league_slug}")
            cache.set(cache_key, result, CACHE_TTL["understat"])
            return result

        raw = match.group(1)
        decoded = raw.encode("utf-8").decode("unicode_escape")
        teams_data = json.loads(decoded)

        for team_info in teams_data.values():
            team_name = team_info.get("title", "")
            history = team_info.get("history", [])
            if not history:
                continue

            xg_h_for, xg_h_ag, n_h = 0.0, 0.0, 0
            xg_a_for, xg_a_ag, n_a = 0.0, 0.0, 0
            for game in history:
                xg = safe_float(game.get("xG"))
                xga = safe_float(game.get("xGA"))
                if game.get("h_a") == "h":
                    xg_h_for += xg; xg_h_ag += xga; n_h += 1
                elif game.get("h_a") == "a":
                    xg_a_for += xg; xg_a_ag += xga; n_a += 1

            result[normalize_name(team_name)] = {
                "xg_home_for":     round(xg_h_for / n_h, 3) if n_h else 0.0,
                "xg_home_against": round(xg_h_ag / n_h, 3) if n_h else 0.0,
                "xg_away_for":     round(xg_a_for / n_a, 3) if n_a else 0.0,
                "xg_away_against": round(xg_a_ag / n_a, 3) if n_a else 0.0,
                "games_home":      n_h,
                "games_away":      n_a,
            }

        print(f"[understat] {league_slug}: {len(result)} echipe cu xG real")
    except Exception as exc:
        print(f"[understat] fail pentru {league_slug}: {exc}")

    cache.set(cache_key, result, CACHE_TTL["understat"])
    return result


def understat_lookup(understat_data: Dict[str, Dict[str, float]], team_name: str) -> Optional[Dict[str, float]]:
    direct = understat_data.get(normalize_name(team_name))
    if direct:
        return direct
    for key, value in understat_data.items():
        if teams_match(team_name, key):
            return value
    return None


# ============================================================
# LOGICA DE PRONOSTIC
# ============================================================

def form_points(form: str) -> int:
    points = 0
    for char in (form or "")[-5:]:
        if char == "W": points += 3
        elif char == "D": points += 1
    return points


def estimate_odds_for_market(market: str, confidence: int) -> float:
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


def predictions_1x2(home_row: Dict, away_row: Dict, odds_prices: Optional[Dict[str, float]]) -> List[Dict[str, Any]]:
    if not home_row or not away_row:
        return []

    rank_home = safe_int(home_row.get("rank"), 99)
    rank_away = safe_int(away_row.get("rank"), 99)
    points_home = form_points(home_row.get("form", "") or "")
    points_away = form_points(away_row.get("form", "") or "")

    rank_advantage = max(min(rank_away - rank_home, 14), -14)
    form_advantage = points_home - points_away

    score_home = 50 + (rank_advantage * 2.0) + (form_advantage * 2.2) + 5
    score_away = 50 + (-rank_advantage * 2.0) + (-form_advantage * 2.2)

    if score_home > score_away:
        conf = int(max(50, min(92, score_home)))
        cota = (odds_prices or {}).get("1") or estimate_odds_for_market("1", conf)
        return [{
            "tip_pariu": "1X2", "pronostic": "1",
            "scor_incredere": conf, "cota": round(float(cota), 2),
            "motiv": f"Gazdele: rang {rank_home} vs {rank_away}, forma {points_home}p vs {points_away}p in ultimele 5.",
        }]
    else:
        conf = int(max(50, min(92, score_away)))
        cota = (odds_prices or {}).get("2") or estimate_odds_for_market("2", conf)
        return [{
            "tip_pariu": "1X2", "pronostic": "2",
            "scor_incredere": conf, "cota": round(float(cota), 2),
            "motiv": f"Oaspetii: rang {rank_away} vs {rank_home}, forma {points_away}p vs {points_home}p in ultimele 5.",
        }]


def predictions_goals(
    home_stats: Dict, away_stats: Dict,
    home_xg_real: Optional[Dict[str, float]], away_xg_real: Optional[Dict[str, float]],
) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = []

    xg_home, xg_away = 0.0, 0.0
    sursa_xg = "estimat din mediile sezonale"

    # Prefer Understat daca avem date suficiente
    if home_xg_real and away_xg_real and home_xg_real.get("games_home", 0) >= 3 and away_xg_real.get("games_away", 0) >= 3:
        xg_home = (home_xg_real["xg_home_for"] + away_xg_real["xg_away_against"]) / 2
        xg_away = (away_xg_real["xg_away_for"] + home_xg_real["xg_home_against"]) / 2
        sursa_xg = "Understat"
    else:
        if not home_stats or not away_stats:
            return options
        h_goals = home_stats.get("goals", {}) or {}
        a_goals = away_stats.get("goals", {}) or {}
        h_for_home = safe_float(((h_goals.get("for") or {}).get("average") or {}).get("home"))
        h_against_home = safe_float(((h_goals.get("against") or {}).get("average") or {}).get("home"))
        a_for_away = safe_float(((a_goals.get("for") or {}).get("average") or {}).get("away"))
        a_against_away = safe_float(((a_goals.get("against") or {}).get("average") or {}).get("away"))
        if h_for_home == 0 and a_for_away == 0:
            return options
        xg_home = ((h_for_home + a_against_away) / 2) if (h_for_home and a_against_away) else max(h_for_home, a_against_away)
        xg_away = ((a_for_away + h_against_home) / 2) if (a_for_away and h_against_home) else max(a_for_away, h_against_home)

    total_xg = xg_home + xg_away

    fts_home_rate = fts_away_rate = 0.0
    cs_home_rate = cs_away_rate = 0.0
    if home_stats and away_stats:
        fts_h = home_stats.get("failed_to_score", {}) or {}
        fts_a = away_stats.get("failed_to_score", {}) or {}
        cs_h = home_stats.get("clean_sheet", {}) or {}
        cs_a = away_stats.get("clean_sheet", {}) or {}
        played_h = ((home_stats.get("fixtures") or {}).get("played") or {})
        played_a = ((away_stats.get("fixtures") or {}).get("played") or {})
        gh = max(safe_int(played_h.get("home")), 1)
        ga = max(safe_int(played_a.get("away")), 1)
        fts_home_rate = safe_int(fts_h.get("home")) / gh
        fts_away_rate = safe_int(fts_a.get("away")) / ga
        cs_home_rate = safe_int(cs_h.get("home")) / gh
        cs_away_rate = safe_int(cs_a.get("away")) / ga

    sursa_label = f"({sursa_xg})"

    if xg_home >= 1.05 and xg_away >= 1.0 and fts_home_rate < 0.30 and fts_away_rate < 0.40:
        gg_score = 55 + min(20, (xg_home + xg_away - 2.0) * 12) + (1 - max(fts_home_rate, fts_away_rate)) * 8
        gg_conf = int(max(50, min(85, gg_score)))
        if gg_conf >= MIN_CONFIDENCE:
            options.append({
                "tip_pariu": "GG / NG", "pronostic": "GG (ambele inscriu)",
                "scor_incredere": gg_conf, "cota": round(estimate_odds_for_market("GG", gg_conf), 2),
                "motiv": f"xG: {xg_home:.2f} vs {xg_away:.2f} {sursa_label}. Ambele atacuri creeaza ocazii.",
            })

    if (xg_home < 0.85 or xg_away < 0.80) and (fts_home_rate > 0.30 or fts_away_rate > 0.40 or cs_home_rate > 0.40 or cs_away_rate > 0.30):
        ng_score = 55 + (cs_home_rate + cs_away_rate) * 18 + (fts_home_rate + fts_away_rate) * 14
        ng_conf = int(max(50, min(82, ng_score)))
        if ng_conf >= MIN_CONFIDENCE:
            options.append({
                "tip_pariu": "GG / NG (Solist)", "pronostic": "NG (cel mult o echipa inscrie)",
                "scor_incredere": ng_conf, "cota": round(estimate_odds_for_market("NG", ng_conf), 2),
                "motiv": f"xG: {xg_home:.2f} vs {xg_away:.2f} {sursa_label}. Apararile: CS {cs_home_rate:.0%}/{cs_away_rate:.0%}.",
            })

    if total_xg >= 2.85:
        over_score = 50 + (total_xg - 2.5) * 22 - max(fts_home_rate, fts_away_rate) * 10
        over_conf = int(max(50, min(85, over_score)))
        if over_conf >= MIN_CONFIDENCE:
            options.append({
                "tip_pariu": "Goluri", "pronostic": "Peste 2.5",
                "scor_incredere": over_conf, "cota": round(estimate_odds_for_market("Peste 2.5", over_conf), 2),
                "motiv": f"Goluri asteptate combinate: {total_xg:.2f} {sursa_label}.",
            })

    if total_xg <= 2.05:
        under_score = 50 + (2.5 - total_xg) * 26 + (cs_home_rate + cs_away_rate) * 8
        under_conf = int(max(50, min(82, under_score)))
        if under_conf >= MIN_CONFIDENCE:
            options.append({
                "tip_pariu": "Goluri", "pronostic": "Sub 2.5",
                "scor_incredere": under_conf, "cota": round(estimate_odds_for_market("Sub 2.5", under_conf), 2),
                "motiv": f"Goluri asteptate combinate: {total_xg:.2f} {sursa_label}. CS: {cs_home_rate:.0%}/{cs_away_rate:.0%}.",
            })

    return options


# ============================================================
# AGREGARE
# ============================================================

def collect_matches() -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    standings_cache: Dict[str, Any] = {}
    understat_cache: Dict[str, Dict[str, Dict[str, float]]] = {}

    start_dt = datetime.now(timezone.utc)
    date_from = start_dt.strftime("%Y-%m-%d")
    date_to = (start_dt + timedelta(days=DAYS_AHEAD - 1)).strftime("%Y-%m-%d")

    fixtures = api_football_fixtures_range(date_from, date_to)
    odds_index = odds_map_for_range(date_from, date_to)
    fd_index = fd_fixtures_index(date_from, date_to)

    for league_id, slug in UNDERSTAT_BY_AF_ID.items():
        if slug and slug not in understat_cache:
            understat_cache[slug] = understat_team_xg(slug)

    seen_fixture_ids: set = set()

    for item in fixtures:
        league = item.get("league", {})
        league_id = league.get("id")
        season = league.get("season")
        if not league_id or not season:
            continue
        if league_id not in API_FOOTBALL_LEAGUES:
            continue

        fixture = item.get("fixture", {})
        fixture_id = fixture.get("id")
        if not fixture_id or fixture_id in seen_fixture_ids:
            continue
        seen_fixture_ids.add(fixture_id)

        status_short = ((fixture.get("status") or {}).get("short") or "")
        if status_short and status_short not in ("NS", "TBD"):
            continue

        teams = item.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        home_id = home.get("id")
        away_id = away.get("id")
        if not home_id or not away_id:
            continue

        home_name = home.get("name", "")
        away_name = away.get("name", "")

        std_key = f"{league_id}_{season}"
        if std_key not in standings_cache:
            standings_cache[std_key] = api_football_standings(int(league_id), int(season))
        table = standings_cache[std_key]
        home_row = table.get(int(home_id))
        away_row = table.get(int(away_id))
        if not home_row or not away_row:
            continue

        home_stats = api_football_team_stats(int(league_id), int(season), int(home_id))
        away_stats = api_football_team_stats(int(league_id), int(season), int(away_id))

        slug = UNDERSTAT_BY_AF_ID.get(int(league_id))
        home_xg_real = away_xg_real = None
        if slug and slug in understat_cache:
            home_xg_real = understat_lookup(understat_cache[slug], home_name)
            away_xg_real = understat_lookup(understat_cache[slug], away_name)

        match_odds = odds_find(odds_index, home_name, away_name)

        cross_check = "doar API-Football"
        if league_id in FD_BY_AF_ID:
            fd_match = fd_find_match(fd_index, home_name, away_name)
            if fd_match:
                cross_check = "verificat in football-data.org"

        candidates = []
        candidates.extend(predictions_1x2(home_row, away_row, match_odds))
        candidates.extend(predictions_goals(home_stats, away_stats, home_xg_real, away_xg_real))
        if not candidates:
            continue

        best = max(candidates, key=lambda x: x["scor_incredere"])
        if best["scor_incredere"] < MIN_CONFIDENCE:
            continue
        if not (ODDS_MIN <= best["cota"] <= ODDS_MAX):
            continue

        match_iso = fixture.get("date", "")
        try:
            dt = datetime.fromisoformat(match_iso.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
            match_date_local = dt.strftime("%Y-%m-%d")
        except Exception:
            match_date_local = date_from

        output.append({
            "data": match_date_local,
            "fixture_id": fixture_id,
            "home": home_name,
            "away": away_name,
            "liga": f"{league.get('name', '')} - {league.get('country', '')}".strip(" -"),
            "ora": format_local_time(match_iso),
            "forma_home": (home_row.get("form", "") or "")[-5:],
            "forma_away": (away_row.get("form", "") or "")[-5:],
            "tip_pariu": best["tip_pariu"],
            "pronostic": best["pronostic"],
            "cota": best["cota"],
            "scor_incredere": best["scor_incredere"],
            "motiv": best["motiv"],
            "verificare": cross_check,
            "alternative": [
                {
                    "tip_pariu": opt["tip_pariu"], "pronostic": opt["pronostic"],
                    "cota": opt["cota"], "scor_incredere": opt["scor_incredere"],
                }
                for opt in candidates if opt is not best
            ],
        })

    output.sort(key=lambda x: (x.get("scor_incredere", 0), x.get("cota", 0)), reverse=True)
    return output[:MAX_MATCHES]


# ============================================================
# BILETE SUGERATE
# ============================================================

def generate_betslips(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(matches) < 3:
        return []

    def slip(name: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        cota_totala = 1.0
        for m in items:
            cota_totala *= m["cota"]
        avg_conf = sum(m["scor_incredere"] for m in items) / len(items)
        return {
            "nume": name,
            "fixture_ids": [m["fixture_id"] for m in items],
            "cota_totala": round(cota_totala, 2),
            "incredere_medie": round(avg_conf, 1),
            "numar_meciuri": len(items),
        }

    by_confidence = sorted(matches, key=lambda x: x["scor_incredere"], reverse=True)
    bilete = []

    if len(by_confidence) >= 3:
        bilete.append(slip("Bilet sigur", by_confidence[:3]))
    if len(by_confidence) >= 4:
        bilete.append(slip("Bilet mediu", by_confidence[:4]))

    if len(matches) >= 5:
        best_combo = None
        best_product = 0.0
        candidates_for_combo = sorted(matches, key=lambda x: x["cota"], reverse=True)[:8]
        for combo in combinations(candidates_for_combo, 5):
            avg_conf = sum(m["scor_incredere"] for m in combo) / 5
            if avg_conf < MIN_CONFIDENCE:
                continue
            product = 1.0
            for m in combo:
                product *= m["cota"]
            if product > best_product:
                best_product = product
                best_combo = list(combo)
        if best_combo:
            bilete.append(slip("Bilet cota mare", best_combo))

    return bilete


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    cache.cleanup()

    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc) + timedelta(days=DAYS_AHEAD - 1)).strftime("%Y-%m-%d")

    matches: List[Dict[str, Any]] = []
    error_msg: Optional[str] = None

    try:
        matches = collect_matches()
        if matches:
            source_status = f"date reale: {len(matches)} meci(uri) selectate din {DAYS_AHEAD} zile"
        else:
            source_status = "date reale, dar niciun meci nu trece filtrele"
    except Exception as exc:
        error_msg = str(exc)
        source_status = f"eroare API: {exc}"
        print(f"[main] collect failed: {exc}")

    bilete = generate_betslips(matches) if matches else []

    payload = {
        "data_start": start_date,
        "data_final": end_date,
        "updated_at": now_iso(),
        "surse": [
            "API-Football",
            "football-data.org",
            "The Odds API",
            "Understat (xG real)",
        ],
        "status_date": source_status,
        "numar_meciuri": len(matches),
        "configuratie": {
            "max_meciuri": MAX_MATCHES,
            "zile_inainte": DAYS_AHEAD,
            "incredere_minima": MIN_CONFIDENCE,
            "cota_min": ODDS_MIN,
            "cota_max": ODDS_MAX,
            "ligi_acoperite": [name for _, name, _, _ in LEAGUES_CONFIG],
            "piete": ["1X2", "GG / NG (Solist)", "Peste 2.5 / Sub 2.5 goluri"],
        },
        "bilete_sugerate": bilete,
        "meciuri": matches,
    }
    if error_msg:
        payload["eroare"] = error_msg

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    cache.save()
    print(f"\n[OK] {OUTPUT_FILE}: {len(matches)} meciuri, {len(bilete)} bilete. Status: {source_status}")


if __name__ == "__main__":
    main()
