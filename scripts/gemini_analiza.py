# -*- coding: utf-8 -*-
"""
Agent: Gemini Analiza Meciuri
- Citeste alte_meciuri.json
- Trimite fiecare meci catre Gemini 2.0 Flash cu grounding web
- Extrage pronostic + cota + tip pariu
- Actualizeaza alte_meciuri.json cu campurile noi
"""

import json
import os
import time
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import requests

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

INPUT_FILE  = "alte_meciuri.json"
OUTPUT_FILE = "alte_meciuri.json"

# Pauza intre requesturi ca sa nu depasim rate limit
DELAY_BETWEEN_REQUESTS = 3  # secunde


def build_prompt(match: Dict[str, Any]) -> str:
    home  = match.get("home", "")
    away  = match.get("away", "")
    liga  = match.get("liga", "")
    data  = match.get("data", "")
    ora   = match.get("ora", "")
    c1    = match.get("cota_1")
    cx    = match.get("cota_x")
    c2    = match.get("cota_2")

    cote_str = ""
    if c1: cote_str += f"Cota 1 (victorie {home}): {c1}\n"
    if cx: cote_str += f"Cota X (egal): {cx}\n"
    if c2: cote_str += f"Cota 2 (victorie {away}): {c2}\n"

    return f"""Ești un analist sportiv profesionist specializat în fotbal european. Analizează meciul de mai jos urmând metodologia completa:

MECI: {home} vs {away}
Competiție: {liga}
Data: {data}, ora {ora}
{cote_str}

METODOLOGIE OBLIGATORIE:

PASUL 1 — Caută și verifică în timp real:
- Forma recentă (ultimele 5-10 meciuri, toate competițiile) cu rezultate exacte și goluri
- Forma acasă vs deplasare (CRITIC)
- Absențe și suspendări importante
- Statistici BTTS, Over/Under 2.5 în meciurile recente
- Head-to-Head ultimele 5 confruntări
- Cornere per meci

PASUL 2 — Identifică factorii decisivi:
- Factori cu greutate MARE: absența marcatorului principal, forma în deplasare, oboseală, record acasă
- Factori cu greutate MEDIE: forma generală, motivație, stil de joc
- Tipul meciului (ligă/cupă/european, faza turneului)

PASUL 3 — Calibrare după tipul meciului:
- Semifinală/Finală europeană → Under 2.5, 1X acasă
- Tur eliminatoriu → 1X gazdă, BTTS Nu
- Meci de ligă fără miză → Over 2.5
- Derby local → Sub 2.5, 1X

REGULI STRICTE:
- NU oferi pronostic dacă nu ai date din ultimele 2 săptămâni
- Prioritizează forma în deplasare vs acasă
- EVITĂ pronostic bazat doar pe reputație
- Scopul este un pronostic CORECT sau deloc

La finalul analizei, returnează OBLIGATORIU un bloc JSON exact în acest format (fără alte modificări):

```json
{{
  "pronostic": "1X",
  "tip_pariu": "Gazdele nu pierd",
  "cota_recomandata": 1.45,
  "incredere": 3,
  "motiv_scurt": "Arsenal forma excelenta acasa, Atletico joaca defensiv in deplasare",
  "pariu_alternativ": "Sub 2.5 goluri",
  "avertisment": "Atletico poate marca din contraatac"
}}
```

Valorile posibile pentru "pronostic": 1, X, 2, 1X, X2, GG, NG, Sub 2.5, Peste 2.5
"incredere" este un număr de la 1 la 5 (5 = maxim sigur)
"cota_recomandata" este cota efectivă pentru pronosticul ales (calculată din cotele date)
"""


def call_gemini(prompt: str) -> Optional[str]:
    if not GEMINI_API_KEY:
        print("[gemini] Lipseste GEMINI_API_KEY")
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2000,
        },
        "tools": [{"google_search": {}}],
    }

    try:
        resp = requests.post(
            GEMINI_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=45,
        )
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts)
        else:
            print(f"[gemini] HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[gemini] Eroare: {e}")
    return None


def extract_json_from_response(text: str) -> Optional[Dict]:
    """Extrage blocul JSON din raspunsul Gemini."""
    # Cauta bloc json intre ```json si ```
    pattern = r"```json\s*(\{.*?\})\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    # Fallback: cauta orice { } care contine "pronostic"
    pattern2 = r'\{[^{}]*"pronostic"[^{}]*\}'
    match2 = re.search(pattern2, text, re.DOTALL)
    if match2:
        try:
            return json.loads(match2.group(0))
        except Exception:
            pass

    return None


def calc_cota_pronostic(match: Dict, pronostic: str) -> Optional[float]:
    """Calculeaza cota efectiva pentru pronosticul ales."""
    c1 = match.get("cota_1")
    cx = match.get("cota_x")
    c2 = match.get("cota_2")

    if pronostic == "1" and c1:    return float(c1)
    if pronostic == "2" and c2:    return float(c2)
    if pronostic == "X" and cx:    return float(cx)
    if pronostic == "1X" and c1 and cx:
        return round(1 / (1/float(c1) + 1/float(cx)), 2)
    if pronostic == "X2" and cx and c2:
        return round(1 / (1/float(cx) + 1/float(c2)), 2)
    return None


def analizeaza_meci(match: Dict) -> Dict:
    """Trimite meciul la Gemini si returneaza campurile noi."""
    home = match.get("home", "")
    away = match.get("away", "")
    print(f"[gemini] Analizez: {home} vs {away}...")

    prompt = build_prompt(match)
    response_text = call_gemini(prompt)

    if not response_text:
        print(f"[gemini] Nu am primit raspuns pentru {home} vs {away}")
        return match

    extracted = extract_json_from_response(response_text)

    if not extracted:
        print(f"[gemini] Nu am putut extrage JSON pentru {home} vs {away}")
        # Salvam analiza bruta ca fallback
        match["analiza_bruta"] = response_text[:500]
        return match

    pronostic = extracted.get("pronostic")
    cota_rec  = extracted.get("cota_recomandata")

    # Daca Gemini nu a dat cota, o calculam noi
    if not cota_rec and pronostic:
        cota_rec = calc_cota_pronostic(match, pronostic)

    match["pronostic"]        = pronostic
    match["tip_pariu"]        = extracted.get("tip_pariu", "")
    match["cota_pronostic"]   = round(float(cota_rec), 2) if cota_rec else match.get("cota_pronostic")
    match["incredere"]        = extracted.get("incredere", 3)
    match["motiv"]            = extracted.get("motiv_scurt", "")
    match["pariu_alternativ"] = extracted.get("pariu_alternativ", "")
    match["avertisment"]      = extracted.get("avertisment", "")
    match["analizat_de"]      = "gemini-2.0-flash"
    match["analizat_la"]      = datetime.now(timezone.utc).isoformat()

    print(f"[gemini] {home} vs {away} → {pronostic} (cota {cota_rec}, incredere {extracted.get('incredere')}/5)")
    return match


def main():
    if not os.path.exists(INPUT_FILE):
        print(f"[ERR] {INPUT_FILE} nu exista. Ruleaza mai intai alte_meciuri.py")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    meciuri = data.get("meciuri", [])
    if not meciuri:
        print("[ERR] Nu exista meciuri in JSON.")
        return

    print(f"[OK] {len(meciuri)} meciuri de analizat...")

    meciuri_analizate = []
    analizate_ok = 0

    for i, match in enumerate(meciuri):
        # Skip daca meciul a fost deja analizat recent
        if match.get("analizat_de") == "gemini-2.0-flash" and match.get("pronostic"):
            print(f"[skip] {match.get('home')} vs {match.get('away')} — deja analizat")
            meciuri_analizate.append(match)
            continue

        match_actualizat = analizeaza_meci(match)
        meciuri_analizate.append(match_actualizat)

        if match_actualizat.get("pronostic"):
            analizate_ok += 1

        # Pauza intre requesturi
        if i < len(meciuri) - 1:
            time.sleep(DELAY_BETWEEN_REQUESTS)

    data["meciuri"]    = meciuri_analizate
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["gemini_analiza"] = {
        "total":     len(meciuri),
        "analizate": analizate_ok,
        "model":     "gemini-2.0-flash",
        "la":        datetime.now(timezone.utc).isoformat(),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] {OUTPUT_FILE} actualizat: {analizate_ok}/{len(meciuri)} meciuri analizate de Gemini")


if __name__ == "__main__":
    main()
