# -*- coding: utf-8 -*-
"""
Agent: Verificare Rezultate
- Arhiveaza pronosticurile din alte_meciuri.json in istoric_pronosticuri.json
- Verifica scorurile finale prin TheSportsDB (API gratuit)
- Calculeaza rata reala de succes (total, pe nivel de incredere, pe pronosticuri "sigure")
- Scrie statistici.json — astfel stim cat de bun e agentul, nu doar cat de bun pare
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

TSDB_KEY  = os.getenv("THESPORTSDB_KEY", "123").strip()
TSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{TSDB_KEY}"

MECIURI_FILE = "alte_meciuri.json"
ISTORIC_FILE = "istoric_pronosticuri.json"
STATS_FILE   = "statistici.json"
MAX_ISTORIC  = 500


def load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def tsdb_get(path: str, params: Dict[str, str]) -> Optional[Dict]:
    try:
        r = requests.get(f"{TSDB_BASE}/{path}", params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


_team_events_cache: Dict[str, List[Dict]] = {}


def evenimente_echipa(team: str) -> List[Dict]:
    """Ultimele meciuri jucate de o echipa (TheSportsDB)."""
    if team in _team_events_cache:
        return _team_events_cache[team]
    events: List[Dict] = []
    data = tsdb_get("searchteams.php", {"t": team})
    teams = (data or {}).get("teams") or []
    if teams:
        res = tsdb_get("eventslast.php", {"id": teams[0].get("idTeam")})
        events = (res or {}).get("results") or []
    _team_events_cache[team] = events
    return events


def gaseste_scor(home: str, away: str, data_meci: str) -> Optional[Dict[str, int]]:
    """Cauta scorul final al meciului home vs away din jurul datei date."""
    for team in (home, away):
        for ev in evenimente_echipa(team):
            hs, as_ = ev.get("intHomeScore"), ev.get("intAwayScore")
            if hs is None or as_ is None:
                continue
            eh = (ev.get("strHomeTeam") or "").lower()
            ea = (ev.get("strAwayTeam") or "").lower()
            h, a = home.lower(), away.lower()
            # potrivire toleranta la diferente de denumire intre API-uri
            if (h in eh or eh in h) and (a in ea or ea in a):
                if ev.get("dateEvent") and abs(
                    (datetime.fromisoformat(ev["dateEvent"]).date()
                     - datetime.fromisoformat(data_meci).date()).days) <= 1:
                    return {"home": int(hs), "away": int(as_)}
    return None


def evalueaza(pronostic: str, hs: int, as_: int) -> Optional[bool]:
    rezultat = "1" if hs > as_ else ("2" if as_ > hs else "X")
    total = hs + as_
    reguli = {
        "1": rezultat == "1", "X": rezultat == "X", "2": rezultat == "2",
        "1X": rezultat in ("1", "X"), "X2": rezultat in ("X", "2"),
        "GG": hs > 0 and as_ > 0, "NG": hs == 0 or as_ == 0,
        "Sub 2.5": total < 3, "Peste 2.5": total > 2,
    }
    return reguli.get(pronostic)


def arhiveaza(istoric: List[Dict]) -> int:
    """Adauga pronosticurile curente in istoric (o singura data per meci)."""
    data = load_json(MECIURI_FILE, {})
    chei = {f"{e['home']}_{e['away']}_{e['data']}" for e in istoric}
    adaugate = 0
    for m in data.get("meciuri", []):
        if not m.get("pronostic"):
            continue
        key = f"{m['home']}_{m['away']}_{m['data']}"
        if key in chei:
            continue
        istoric.append({
            "home": m["home"], "away": m["away"], "data": m["data"],
            "liga": m.get("liga"), "pronostic": m["pronostic"],
            "cota_pronostic": m.get("cota_pronostic"),
            "incredere": m.get("incredere"),
            "prob_piata": m.get("prob_piata"),
            "pronostic_sigur": m.get("pronostic_sigur", False),
            "status": "in_asteptare",
        })
        chei.add(key)
        adaugate += 1
    return adaugate


def verifica(istoric: List[Dict]) -> int:
    azi = datetime.now(timezone.utc).date().isoformat()
    verificate = 0
    for e in istoric:
        if e.get("status") != "in_asteptare" or e.get("data", "") >= azi:
            continue
        scor = gaseste_scor(e["home"], e["away"], e["data"])
        if not scor:
            continue
        corect = evalueaza(e["pronostic"], scor["home"], scor["away"])
        if corect is None:
            continue
        e["scor"]   = f"{scor['home']}-{scor['away']}"
        e["status"] = "corect" if corect else "gresit"
        verificate += 1
        semn = "✓" if corect else "✗"
        print(f"  {semn} {e['home']} {e['scor']} {e['away']} — pronostic {e['pronostic']}")
    return verificate


def statistici(istoric: List[Dict]) -> Dict[str, Any]:
    gata = [e for e in istoric if e.get("status") in ("corect", "gresit")]

    def rata(items):
        c = sum(1 for e in items if e["status"] == "corect")
        return {"total": len(items), "corecte": c,
                "rata": round(c / len(items), 3) if items else None}

    pe_incredere = {}
    for n in (1, 2, 3, 4, 5):
        sub = [e for e in gata if e.get("incredere") == n]
        if sub:
            pe_incredere[f"{n}_stele"] = rata(sub)

    return {
        "actualizat_la": datetime.now(timezone.utc).isoformat(),
        "general": rata(gata),
        "pronosticuri_sigure": rata([e for e in gata if e.get("pronostic_sigur")]),
        "pe_incredere": pe_incredere,
        "in_asteptare": sum(1 for e in istoric if e.get("status") == "in_asteptare"),
    }


def main() -> None:
    istoric = load_json(ISTORIC_FILE, [])
    adaugate   = arhiveaza(istoric)
    verificate = verifica(istoric)
    istoric = istoric[-MAX_ISTORIC:]
    save_json(ISTORIC_FILE, istoric)

    stats = statistici(istoric)
    save_json(STATS_FILE, stats)

    g = stats["general"]
    rata_txt = f"{g['rata']*100:.0f}%" if g["rata"] is not None else "n/a"
    print(f"[OK] {adaugate} pronosticuri arhivate, {verificate} verificate acum.")
    print(f"[OK] Rata generala de succes: {g['corecte']}/{g['total']} ({rata_txt})")


if __name__ == "__main__":
    main()
