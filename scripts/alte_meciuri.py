# -*- coding: utf-8 -*-
"""
Agent separat: Alte Meciuri

Scop:
  - ia meciurile gasite de API-Football pentru urmatoarele zile
  - adauga cote H2H daca exista in The Odds API
  - NU aplica filtre de incredere, NU alege pronosticuri, NU limiteaza dupa cota
  - scrie output in alte_meciuri.json

Necesita aceleasi GitHub Secrets ca analiza_meciuri.py:
  API_FOOTBALL_KEY
  ODDS_API_KEY optional, pentru cote reale
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/Bucharest")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=3))

OUTPUT_FILE = "alte_meciuri.json"
CACHE_FILE = "cache_alte_meciuri.json"

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

DAYS_AHEAD = 5

# Lasa set() gol daca vrei toate meciurile gasite de API-Football.
# Exemplu restrictie: TARGET_LEAGUES = {39, 140, 135}
TARGET_LEAGUES = set()

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

CACHE_TTL = {
    "fixtures": 60 * 60,
    "odds": 30 * 60,
}


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
            except Exception:
                self.data = {}

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

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


cache = DiskCache(CACHE_FILE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_local_date(iso_string: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
    except Exception:
        return ""


def format_local_time(iso_string: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ).strftime("%H:%M")
    except Exception:
        return ""


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
    common = a_words & b_words
    return bool(common) and (len(common) / min(len(a_words), len(b_words))) >= 0.5


def api_football_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not API_FOOTBALL_KEY:
        raise RuntimeError("Lipseste API_FOOTBALL_KEY in GitHub Secrets.")

    response = requests.get(
        f"{API_FOOTBALL_BASE}/{endpoint.lstrip('/')}",
        headers={"x-apisports-key": API_FOOTBALL_KEY},
        params=params or {},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"API-Football HTTP {response.status_code}: {response.text[:300]}")

    data = response.json()
    errors = data.get("errors")
    if isinstance(errors, dict) and any(errors.values()):
        raise RuntimeError(f"API-Football errors: {errors}")
    if isinstance(errors, list) and errors:
        raise RuntimeError(f"API-Football errors: {errors}")
    return data


def api_football_fixtures_range(date_from: str, date_to: str) -> List[Dict[str, Any]]:
    cache_key = f"af_all_fixtures_{date_from}_{date_to}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    fixtures: List[Dict[str, Any]] = []

    try:
        fixtures = api_football_get("fixtures", {
            "from": date_from,
            "to": date_to,
            "timezone": "Europe/Bucharest",
        }).get("response", [])
    except Exception as exc:
        print(f"[api-football] global from/to failed: {exc}")

    # Fallback per zi. Ajuta cand planul API nu accepta intervalul complet.
    if not fixtures:
        start = datetime.strptime(date_from, "%Y-%m-%d")
        end = datetime.strptime(date_to, "%Y-%m-%d")
        cursor = start
        while cursor <= end:
            target = cursor.strftime("%Y-%m-%d")
            try:
                fixtures.extend(api_football_get("fixtures", {
                    "date": target,
                    "timezone": "Europe/Bucharest",
                }).get("response", []))
            except Exception as exc:
                print(f"[api-football] zi {target}: {exc}")
            cursor += timedelta(days=1)

    cache.set(cache_key, fixtures, CACHE_TTL["fixtures"])
    return fixtures


def odds_api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    if not ODDS_API_KEY:
        return []
    query = dict(params or {})
    query["apiKey"] = ODDS_API_KEY
    response = requests.get(f"{ODDS_API_BASE}/{path.lstrip('/')}", params=query, timeout=30)
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
    cache_key = f"odds_all_h2h_{date_from}_{date_to}"
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
            if prices:
                mapped[f"{normalize_name(home)}__{normalize_name(away)}"] = prices

    cache.set(cache_key, mapped, CACHE_TTL["odds"])
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


def collect_all_matches() -> List[Dict[str, Any]]:
    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc) + timedelta(days=DAYS_AHEAD - 1)).strftime("%Y-%m-%d")

    fixtures = api_football_fixtures_range(start_date, end_date)
    odds_index = odds_map_for_range(start_date, end_date)

    output: List[Dict[str, Any]] = []
    seen: set = set()

    for item in fixtures:
        league = item.get("league", {}) or {}
        fixture = item.get("fixture", {}) or {}
        teams = item.get("teams", {}) or {}
        home = teams.get("home", {}) or {}
        away = teams.get("away", {}) or {}

        fixture_id = fixture.get("id")
        if not fixture_id or fixture_id in seen:
            continue
        seen.add(fixture_id)

        status_short = ((fixture.get("status") or {}).get("short") or "")
        if status_short and status_short not in ("NS", "TBD"):
            continue

        league_id = league.get("id")
        if TARGET_LEAGUES and league_id not in TARGET_LEAGUES:
            continue

        home_name = home.get("name", "")
        away_name = away.get("name", "")
        if not home_name or not away_name:
            continue

        prices = odds_find(odds_index, home_name, away_name) or {}
        match_iso = fixture.get("date", "")

        output.append({
            "data": format_local_date(match_iso),
            "ora": format_local_time(match_iso),
            "fixture_id": fixture_id,
            "home": home_name,
            "away": away_name,
            "liga": f"{league.get('name', '')} - {league.get('country', '')}".strip(" -"),
            "cote": {
                "1": prices.get("1"),
                "X": prices.get("X"),
                "2": prices.get("2"),
            },
            "are_cote": bool(prices),
        })

    output.sort(key=lambda x: (x.get("data", ""), x.get("ora", ""), x.get("liga", "")))
    return output


def main() -> None:
    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc) + timedelta(days=DAYS_AHEAD - 1)).strftime("%Y-%m-%d")

    error_msg = None
    matches: List[Dict[str, Any]] = []

    try:
        matches = collect_all_matches()
        status = f"date reale: {len(matches)} meciuri gasite, fara filtre de selectie"
    except Exception as exc:
        error_msg = str(exc)
        status = f"eroare API: {exc}"
        print(f"[main] collect failed: {exc}")

    payload = {
        "data_start": start_date,
        "data_final": end_date,
        "updated_at": now_iso(),
        "surse": ["API-Football", "The Odds API"],
        "status_date": status,
        "numar_meciuri": len(matches),
        "configuratie": {
            "zile_inainte": DAYS_AHEAD,
            "target_leagues": sorted(list(TARGET_LEAGUES)),
            "filtre_predictie": "nu se aplica",
        },
        "meciuri": matches,
    }
    if error_msg:
        payload["eroare"] = error_msg

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    cache.save()
    print(f"[OK] {OUTPUT_FILE}: {len(matches)} meciuri. Status: {status}")


if __name__ == "__main__":
    main()
