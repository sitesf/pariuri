# -*- coding: utf-8 -*-
"""
Agent: Alte Meciuri
- 14 ligi populare europene
- Pronostic simplu bazat pe cote
- Max 20 meciuri selectate (cele mai clare)
- Output flat: cota_1, cota_x, cota_2, pronostic, motiv
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
CACHE_FILE  = "cache_alte_meciuri.json"

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

MAX_MECIURI = 20
DAYS_AHEAD  = 2   # azi + maine — suficient, putine requesturi

# 14 ligi populare (1 request / liga)
ODDS_SPORT_KEYS = [
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

CACHE_TTL = 6 * 60 * 60   # 6 ore


# ── Cache ────────────────────────────────────────────────────────────────────

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
        self.data[key] = {
            "value": value,
            "expires_at": time.time() + ttl,
        }


cache = DiskCache(CACHE_FILE)


# ── Helpers ───────────────────────────────────────────────────────────────────

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


# ── Pronostic logic ───────────────────────────────────────────────────────────

def calculeaza_pronostic(c1: float, cx: float, c2: float):
    """
    Returneaza (pronostic, motiv, claritate).
    claritate = cat de sigur e pronosticul (mai mic = mai sigur).
    """
    if not all([c1, cx, c2]):
        return None, None, 999

    min_c = min(c1, cx, c2)

    # Favorit clar acasa
    if c1 == min_c and c1 < 1.65:
        return "1", f"Gazde favorite clare (cota {c1:.2f})", c1

    # Favorit clar deplasare
    if c2 == min_c and c2 < 1.65:
        return "2", f"Oaspeti favoriți clari (cota {c2:.2f})", c2

    # Acasa nu pierde
    if c1 == min_c and 1.65 <= c1 < 2.10:
        return "1X", f"Gazde ușor favorizate (cota 1: {c1:.2f}, X: {cx:.2f})", c1

    # Deplasare nu pierde
    if c2 == min_c and 1.65 <= c2 < 2.10:
        return "X2", f"Oaspeți ușor favorizați (cota 2: {c2:.2f}, X: {cx:.2f})", c2

    # Meci echilibrat, sanse de egal
    if abs(c1 - c2) < 0.40 and 2.60 <= cx <= 3.60:
        return "X", f"Meci echilibrat, egal posibil (1:{c1:.2f} X:{cx:.2f} 2:{c2:.2f})", cx

    return None, None, 999


# ── API ───────────────────────────────────────────────────────────────────────

def odds_get(sport_key: str) -> List[Dict]:
    if not ODDS_API_KEY:
        return []

    cache_key = f"odds_{sport_key}"
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
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            cache.set(cache_key, data, CACHE_TTL)
            return data
        else:
            print(f"[odds-api] {sport_key}: HTTP {resp.status_code}")
            return []
    except Exception as exc:
        print(f"[odds-api] {sport_key}: {exc}")
        return []


def extract_h2h(match: Dict) -> Optional[Dict[str, float]]:
    """Extrage cotele 1/X/2 din primul bookmaker disponibil."""
    home = match.get("home_team", "")
    away = match.get("away_team", "")
    result: Dict[str, float] = {}

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
            if len(result) == 3:
                return result
    return result if result else None


def liga_name(sport_key: str) -> str:
    mapping = {
        "soccer_uefa_champs_league":              "UEFA Champions League",
        "soccer_uefa_europa_league":              "UEFA Europa League",
        "soccer_uefa_europa_conference_league":   "UEFA Conference League",
        "soccer_epl":                             "Premier League",
        "soccer_spain_la_liga":                   "La Liga",
        "soccer_italy_serie_a":                   "Serie A",
        "soccer_germany_bundesliga":              "Bundesliga",
        "soccer_france_ligue_one":                "Ligue 1",
        "soccer_netherlands_eredivisie":          "Eredivisie",
        "soccer_portugal_primeira_liga":          "Primeira Liga",
        "soccer_turkey_super_league":             "Süper Lig",
        "soccer_belgium_first_div":               "Belgian Pro League",
        "soccer_scotland_premiership":            "Scottish Premiership",
        "soccer_efl_champ":                       "Championship",
    }
    return mapping.get(sport_key, sport_key)


# ── Main ──────────────────────────────────────────────────────────────────────

def collect() -> List[Dict]:
    start = datetime.now(timezone.utc).date()
    end   = start + timedelta(days=DAYS_AHEAD)

    candidates = []

    for sport_key in ODDS_SPORT_KEYS:
        matches = odds_get(sport_key)
        for match in matches:
            # Filtru interval date
            commence = match.get("commence_time", "")
            try:
                match_date = datetime.fromisoformat(
                    commence.replace("Z", "+00:00")
                ).date()
            except Exception:
                continue
            if match_date < start or match_date > end:
                continue

            h2h = extract_h2h(match)
            if not h2h or len(h2h) < 2:
                continue

            c1 = h2h.get("1")
            cx = h2h.get("X")
            c2 = h2h.get("2")

            pronostic, motiv, claritate = calculeaza_pronostic(c1, cx, c2)

            candidates.append({
                "data":       format_date(commence),
                "ora":        format_time(commence),
                "home":       match.get("home_team", ""),
                "away":       match.get("away_team", ""),
                "liga":       liga_name(sport_key),
                "cota_1":     round(c1, 2) if c1 else None,
                "cota_x":     round(cx, 2) if cx else None,
                "cota_2":     round(c2, 2) if c2 else None,
                "pronostic":  pronostic,
                "motiv":      motiv,
                "_claritate": claritate,
            })

    # Sorteaza: mai intai cele cu pronostic, apoi dupa claritate
    candidates.sort(key=lambda x: (
        0 if x["pronostic"] else 1,
        x["_claritate"]
    ))

    # Pastreaza max 20, sterge campul intern
    output = []
    for item in candidates[:MAX_MECIURI]:
        item.pop("_claritate", None)
        output.append(item)

    return output


def main() -> None:
    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date   = (datetime.now(timezone.utc) + timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%d")

    matches = []
    status  = ""
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
