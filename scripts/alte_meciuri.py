# -*- coding: utf-8 -*-
"""
Agent: Alte Meciuri
- 14 ligi principale + ligi extra daca < 50 meciuri
- h2h + bts + totals intr-un singur request per liga
- 7 zile inainte, 50 meciuri max
- Rulare: miercuri 05:00 UTC
"""

import json
import os
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/Bucharest")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=3))

OUTPUT_FILE = "alte_meciuri.json"
CACHE_FILE  = "cache_alte_meciuri.json"

ODDS_API_KEY  = os.getenv("ODDS_API_KEY", "").strip()
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

MAX_MECIURI = 50
DAYS_AHEAD  = 7

# Cupa Mondiala 2026 (11 iunie - 19 iulie 2026)
# Pe durata turneului se iau DOAR meciurile de la Cupa Mondiala;
# celelalte ligi sunt suspendate si revin automat dupa finala.
WORLD_CUP_KEY   = "soccer_fifa_world_cup"
WORLD_CUP_START = datetime(2026, 6, 1,  tzinfo=timezone.utc).date()
WORLD_CUP_END   = datetime(2026, 7, 19, tzinfo=timezone.utc).date()


def world_cup_mode() -> bool:
    today = datetime.now(timezone.utc).date()
    return WORLD_CUP_START <= today <= WORLD_CUP_END

# 14 ligi principale
MAIN_LEAGUES = [
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie",
    "soccer_portugal_primeira_liga",
    "soccer_turkey_super_league",
    "soccer_belgium_first_div",
    "soccer_scotland_premiership",
    "soccer_efl_champ",
]

# Ligi extra — interogate doar daca < 50 meciuri
EXTRA_LEAGUES = [
    "soccer_spain_la_liga_2",
    "soccer_italy_serie_b",
    "soccer_germany_bundesliga2",
    "soccer_france_ligue_two",
    "soccer_greece_super_league",
    "soccer_austria_bundesliga",
    "soccer_denmark_superliga",
    "soccer_sweden_allsvenskan",
    "soccer_norway_eliteserien",
    "soccer_poland_ekstraklasa",
    "soccer_czech_rep_1_liga",
    "soccer_switzerland_superleague",
    "soccer_romania_1",
    "soccer_croatia_hnl",
]

CACHE_TTL = 12 * 60 * 60  # 12 ore


class DiskCache:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {}
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

    def set(self, key: str, value: Any, ttl: int) -> None:
        self.data[key] = {"value": value, "expires_at": time.time() + ttl}


cache = DiskCache(CACHE_FILE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
    except Exception:
        return ""


def format_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ).strftime("%H:%M")
    except Exception:
        return ""


def calc_dc(ca: float, cb: float) -> float:
    """Double chance: 1/(1/ca + 1/cb)"""
    if ca and cb:
        return 1 / (1 / ca + 1 / cb)
    return 0


def liga_name(sport_key: str) -> str:
    mapping = {
        "soccer_fifa_world_cup":                "Cupa Mondială 2026",
        "soccer_uefa_champs_league":            "UEFA Champions League",
        "soccer_uefa_europa_league":            "UEFA Europa League",
        "soccer_uefa_europa_conference_league": "UEFA Conference League",
        "soccer_epl":                           "Premier League",
        "soccer_spain_la_liga":                 "La Liga",
        "soccer_italy_serie_a":                 "Serie A",
        "soccer_germany_bundesliga":            "Bundesliga",
        "soccer_france_ligue_one":              "Ligue 1",
        "soccer_netherlands_eredivisie":        "Eredivisie",
        "soccer_portugal_primeira_liga":        "Primeira Liga",
        "soccer_turkey_super_league":           "Süper Lig",
        "soccer_belgium_first_div":             "Belgian Pro League",
        "soccer_scotland_premiership":          "Scottish Premiership",
        "soccer_efl_champ":                     "Championship",
        "soccer_spain_la_liga_2":               "La Liga 2",
        "soccer_italy_serie_b":                 "Serie B",
        "soccer_germany_bundesliga2":           "Bundesliga 2",
        "soccer_france_ligue_two":              "Ligue 2",
        "soccer_greece_super_league":           "Super League Grecia",
        "soccer_austria_bundesliga":            "Bundesliga Austria",
        "soccer_denmark_superliga":             "Superliga Danemarca",
        "soccer_sweden_allsvenskan":            "Allsvenskan",
        "soccer_norway_eliteserien":            "Eliteserien",
        "soccer_poland_ekstraklasa":            "Ekstraklasa",
        "soccer_czech_rep_1_liga":              "1. Liga Cehia",
        "soccer_switzerland_superleague":       "Super League Elvetia",
        "soccer_romania_1":                     "Liga 1 Romania",
        "soccer_croatia_hnl":                   "HNL Croatia",
    }
    return mapping.get(sport_key, sport_key)


def odds_get(sport_key: str) -> List[Dict]:
    if not ODDS_API_KEY:
        return []
    cache_key = f"odds3_{sport_key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports/{sport_key}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
            timeout=25,
        )
        if resp.status_code == 200:
            data = resp.json()
            cache.set(cache_key, data, CACHE_TTL)
            print(f"[odds-api] {sport_key}: {len(data)} meciuri")
            return data
        else:
            print(f"[odds-api] {sport_key}: HTTP {resp.status_code}")
            return []
    except Exception as exc:
        print(f"[odds-api] {sport_key}: {exc}")
        return []


def extract_markets(match: Dict, home: str, away: str) -> Dict[str, Any]:
    """Extrage cotele h2h (1/X/2)."""
    result: Dict[str, Any] = {}
    for bookmaker in match.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                name  = outcome.get("name", "")
                price = outcome.get("price")
                if price is None:
                    continue
                if name == home:
                    result["1"] = float(price)
                elif name == away:
                    result["2"] = float(price)
                else:
                    result["X"] = float(price)
            if len(result) >= 2:
                break
        if len(result) >= 2:
            break
    return result


def alege_pronostic(
    c1, cx, c2
) -> Tuple[Optional[str], Optional[str], float, float]:
    """
    Alege cel mai bun pronostic din cotele h2h.
    Returneaza: (pronostic, motiv, cota_pronostic, probabilitate)
    """
    candidati = []

    if c1 and c1 <= 2.00:
        if c1 < 1.67:
            candidati.append(("1", f"Gazde favorite clare (cota {c1:.2f})", c1, 1/c1))
        elif c1 < 2.00 and cx:
            dc = calc_dc(c1, cx)
            if dc > 1:
                candidati.append(("1X", f"Gazde ușor favorizate (1:{c1:.2f} X:{cx:.2f})", dc, 1/dc))

    if c2 and c2 <= 2.00:
        if c2 < 1.67:
            candidati.append(("2", f"Oaspeți favoriți clari (cota {c2:.2f})", c2, 1/c2))
        elif c2 < 2.00 and cx:
            dc = calc_dc(cx, c2)
            if dc > 1:
                candidati.append(("X2", f"Oaspeți ușor favorizați (2:{c2:.2f} X:{cx:.2f})", dc, 1/dc))

    if not candidati:
        return None, None, 0.0, 0.0

    candidati.sort(key=lambda x: -x[3])
    best = candidati[0]
    return best[0], best[1], best[2], best[3]


def process_league(sport_key: str, start, end) -> List[Dict]:
    matches = odds_get(sport_key)
    output = []
    for match in matches:
        commence = match.get("commence_time", "")
        try:
            match_date = datetime.fromisoformat(commence.replace("Z", "+00:00")).date()
        except Exception:
            continue
        if match_date < start or match_date > end:
            continue

        home = match.get("home_team", "")
        away = match.get("away_team", "")
        mkts = extract_markets(match, home, away)

        if not mkts.get("1"):
            continue

        c1 = mkts.get("1")
        cx = mkts.get("X")
        c2 = mkts.get("2")

        pronostic, motiv, cota_p, prob = alege_pronostic(c1, cx, c2)

        output.append({
            "data":           format_date(commence),
            "ora":            format_time(commence),
            "home":           home,
            "away":           away,
            "liga":           liga_name(sport_key),
            "cota_1":         round(c1, 2) if c1 else None,
            "cota_x":         round(cx, 2) if cx else None,
            "cota_2":         round(c2, 2) if c2 else None,
            "pronostic":      pronostic,
            "motiv":          motiv,
            "cota_pronostic": round(cota_p, 2) if cota_p else None,
            "probabilitate":  round(prob, 3)    if prob    else None,
        })
    return output


def collect() -> List[Dict]:
    start = datetime.now(timezone.utc).date()
    end   = start + timedelta(days=DAYS_AHEAD)

    all_matches = []
    seen = set()

    def add_unique(matches):
        for m in matches:
            key = f"{m['home']}_{m['away']}_{m['data']}"
            if key not in seen:
                seen.add(key)
                all_matches.append(m)

    # Mod Cupa Mondiala: doar meciurile de la CM, restul ligilor suspendate
    if world_cup_mode():
        add_unique(process_league(WORLD_CUP_KEY, start, end))
        print(f"[collect] mod Cupa Mondiala: {len(all_matches)} meciuri")
        all_matches.sort(key=lambda x: (x.get("data") or "", x.get("ora") or ""))
        return all_matches[:MAX_MECIURI]

    # Ligi principale
    for sk in MAIN_LEAGUES:
        add_unique(process_league(sk, start, end))

    print(f"[collect] dupa ligi principale: {len(all_matches)} meciuri")

    # Ligi extra daca < 50
    if len(all_matches) < MAX_MECIURI:
        extra = list(EXTRA_LEAGUES)
        random.shuffle(extra)
        for sk in extra:
            if len(all_matches) >= MAX_MECIURI:
                break
            add_unique(process_league(sk, start, end))
            print(f"[collect] dupa {sk}: {len(all_matches)} meciuri")

    # Sorteaza: cu pronostic primul, apoi dupa probabilitate descrescator
    all_matches.sort(key=lambda x: (
        0 if x.get("pronostic") else 1,
        -(x.get("probabilitate") or 0)
    ))

    return all_matches[:MAX_MECIURI]


def main() -> None:
    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date   = (datetime.now(timezone.utc) + timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%d")

    matches = []
    error   = None

    try:
        matches = collect()
        cu_pronostic = sum(1 for m in matches if m.get("pronostic"))
        status = f"{len(matches)} meciuri gasite, {cu_pronostic} cu pronostic"
        print(f"[OK] {status}")
    except Exception as exc:
        error  = str(exc)
        status = f"eroare: {exc}"
        print(f"[ERR] {exc}")

    payload = {
        "data_start":    start_date,
        "data_final":    end_date,
        "updated_at":    now_iso(),
        "surse":         ["The Odds API"],
        "status_date":   status,
        "numar_meciuri": len(matches),
        "meciuri":       matches,
    }
    if error:
        payload["eroare"] = error

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    cache.save()
    print(f"[OK] {OUTPUT_FILE} scris: {len(matches)} meciuri")


if __name__ == "__main__":
    main()
