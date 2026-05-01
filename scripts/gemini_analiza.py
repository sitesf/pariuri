# -*- coding: utf-8 -*-
"""
Agent: Gemini Analiza Meciuri
- Citeste alte_meciuri.json
- Trimite fiecare meci catre Gemini 2.0 Flash
- Extrage pronostic + cota + tip pariu + incredere
- Actualizeaza alte_meciuri.json
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Incercam modele in ordine pana gasim unul disponibil
MODELS_TO_TRY = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
]

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

INPUT_FILE  = "alte_meciuri.json"
OUTPUT_FILE = "alte_meciuri.json"
DELAY       = 4  # secunde intre requesturi


def build_prompt(match: Dict[str, Any]) -> str:
    home = match.get("home", "")
    away = match.get("away", "")
    liga = match.get("liga", "")
    data = match.get("data", "")
    ora  = match.get("ora", "")
    c1   = match.get("cota_1", "-")
    cx   = match.get("cota_x", "-")
    c2   = match.get("cota_2", "-")

    return f"""Esti un analist sportiv profesionist. Analizeaza meciul de mai jos si returneaza DOAR un obiect JSON valid, fara alte texte sau explicatii.

MECI: {home} vs {away}
Competitie: {liga}
Data: {data}, ora {ora}
Cote: 1={c1}, X={cx}, 2={c2}

Analizeaza:
1. Forma recenta a echipelor (ultimele 5-10 meciuri)
2. Absente/suspendari importante
3. Tipul meciului si miza
4. Stilul de joc al ambelor echipe
5. Head to head recent

Returneaza EXCLUSIV acest JSON (fara markdown, fara ```json, fara alte cuvinte):
{{"pronostic":"1X","tip_pariu":"Gazde nu pierd","cota_recomandata":1.45,"incredere":3,"motiv_scurt":"descriere scurta in romana","pariu_alternativ":"Sub 2.5 goluri","avertisment":"ce ar putea invalida pronosticul"}}

Valori posibile pentru pronostic: 1, X, 2, 1X, X2, GG, NG, Sub 2.5, Peste 2.5
incredere este un numar intreg de la 1 la 5
cota_recomandata este un numar zecimal calculat din cotele date"""


def call_gemini(prompt: str, model: str) -> Optional[str]:
    url = GEMINI_BASE.format(model=model, key=GEMINI_API_KEY)

    # Incercam mai intai fara grounding (mai simplu, mai stabil)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
        },
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
            return text
        else:
            print(f"  [gemini/{model}] HTTP {resp.status_code}: {resp.text[:150]}")
            return None
    except Exception as e:
        print(f"  [gemini/{model}] Eroare: {e}")
        return None


def call_gemini_with_search(prompt: str, model: str) -> Optional[str]:
    """Varianta cu Google Search grounding."""
    url = GEMINI_BASE.format(model=model, key=GEMINI_API_KEY)

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1024,
        },
        "tools": [{"googleSearch": {}}],
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=45,
        )
        if resp.status_code == 200:
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
            return text
        else:
            print(f"  [gemini-search/{model}] HTTP {resp.status_code}: {resp.text[:150]}")
            return None
    except Exception as e:
        print(f"  [gemini-search/{model}] Eroare: {e}")
        return None


def extract_json(text: str) -> Optional[Dict]:
    """Extrage JSON din text cu multiple strategii."""
    if not text:
        return None

    # Strategie 1: textul e direct JSON valid
    try:
        return json.loads(text)
    except Exception:
        pass

    # Strategie 2: cauta bloc ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # Strategie 3: cauta primul { ... } care contine "pronostic"
    m = re.search(r'\{[^{}]*"pronostic"[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    # Strategie 4: cauta orice { ... } valid
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    # Strategie 5: extrage campuri individual cu regex
    result = {}
    fields = {
        "pronostic":        r'"pronostic"\s*:\s*"([^"]+)"',
        "tip_pariu":        r'"tip_pariu"\s*:\s*"([^"]+)"',
        "motiv_scurt":      r'"motiv_scurt"\s*:\s*"([^"]+)"',
        "pariu_alternativ": r'"pariu_alternativ"\s*:\s*"([^"]+)"',
        "avertisment":      r'"avertisment"\s*:\s*"([^"]+)"',
    }
    num_fields = {
        "cota_recomandata": r'"cota_recomandata"\s*:\s*([\d.]+)',
        "incredere":        r'"incredere"\s*:\s*(\d+)',
    }
    for field, pattern in fields.items():
        m2 = re.search(pattern, text)
        if m2:
            result[field] = m2.group(1)
    for field, pattern in num_fields.items():
        m2 = re.search(pattern, text)
        if m2:
            try:
                result[field] = float(m2.group(1)) if "." in m2.group(1) else int(m2.group(1))
            except Exception:
                pass

    if result.get("pronostic"):
        return result

    print(f"  [extract] Nu am gasit JSON. Raspuns primit: {text[:200]}")
    return None


def calc_cota(match: Dict, pronostic: str) -> Optional[float]:
    c1 = float(match.get("cota_1") or 0)
    cx = float(match.get("cota_x") or 0)
    c2 = float(match.get("cota_2") or 0)
    if pronostic == "1"  and c1: return c1
    if pronostic == "2"  and c2: return c2
    if pronostic == "X"  and cx: return cx
    if pronostic == "1X" and c1 and cx: return round(1/(1/c1+1/cx), 2)
    if pronostic == "X2" and cx and c2: return round(1/(1/cx+1/c2), 2)
    return None


def find_working_model() -> Optional[str]:
    """Gaseste primul model Gemini disponibil."""
    test_payload = {
        "contents": [{"parts": [{"text": "Raspunde doar cu: ok"}]}],
        "generationConfig": {"maxOutputTokens": 10},
    }
    for model in MODELS_TO_TRY:
        url = GEMINI_BASE.format(model=model, key=GEMINI_API_KEY)
        try:
            resp = requests.post(url, json=test_payload, timeout=15)
            if resp.status_code == 200:
                print(f"[gemini] Model disponibil: {model}")
                return model
            else:
                print(f"[gemini] Model {model}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"[gemini] Model {model}: {e}")
    return None


def analizeaza_meci(match: Dict, model: str) -> Dict:
    home = match.get("home", "?")
    away = match.get("away", "?")
    print(f"  → {home} vs {away}...", end=" ", flush=True)

    prompt = build_prompt(match)

    # Incercam mai intai cu search, apoi fara
    text = call_gemini_with_search(prompt, model)
    if not text:
        text = call_gemini(prompt, model)

    if not text:
        print("SKIP (fara raspuns)")
        return match

    extracted = extract_json(text)
    if not extracted:
        print("SKIP (JSON invalid)")
        return match

    pronostic = extracted.get("pronostic") or match.get("pronostic")
    cota_rec  = extracted.get("cota_recomandata")

    if not cota_rec and pronostic:
        cota_rec = calc_cota(match, pronostic)

    match["pronostic"]        = pronostic
    match["tip_pariu"]        = extracted.get("tip_pariu", "")
    match["cota_pronostic"]   = round(float(cota_rec), 2) if cota_rec else match.get("cota_pronostic")
    match["incredere"]        = int(extracted.get("incredere", 3))
    match["motiv"]            = extracted.get("motiv_scurt", match.get("motiv", ""))
    match["pariu_alternativ"] = extracted.get("pariu_alternativ", "")
    match["avertisment"]      = extracted.get("avertisment", "")
    match["analizat_de"]      = f"gemini/{model}"
    match["analizat_la"]      = datetime.now(timezone.utc).isoformat()

    inc = match["incredere"]
    print(f"OK → {pronostic} @ {match['cota_pronostic']} ({'⭐'*inc})")
    return match


def main():
    if not GEMINI_API_KEY:
        print("[ERR] GEMINI_API_KEY lipsa din environment.")
        return

    if not os.path.exists(INPUT_FILE):
        print(f"[ERR] {INPUT_FILE} nu exista.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    meciuri = data.get("meciuri", [])
    if not meciuri:
        print("[ERR] Nu exista meciuri in JSON.")
        return

    print(f"[gemini] Gasesc model disponibil...")
    model = find_working_model()
    if not model:
        print("[ERR] Niciun model Gemini disponibil.")
        return

    print(f"[gemini] Analizez {len(meciuri)} meciuri cu {model}...")

    meciuri_actualizate = []
    ok = 0

    for i, match in enumerate(meciuri):
        # Skip daca deja analizat de Gemini in aceasta rulare
        if match.get("analizat_de", "").startswith("gemini") and match.get("incredere"):
            print(f"  → {match.get('home')} vs {match.get('away')}: SKIP (deja analizat)")
            meciuri_actualizate.append(match)
            ok += 1
            continue

        match = analizeaza_meci(match, model)
        meciuri_actualizate.append(match)

        if match.get("analizat_de", "").startswith("gemini"):
            ok += 1

        if i < len(meciuri) - 1:
            time.sleep(DELAY)

    data["meciuri"]    = meciuri_actualizate
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["gemini_analiza"] = {
        "total":     len(meciuri),
        "analizate": ok,
        "model":     model,
        "la":        datetime.now(timezone.utc).isoformat(),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] {OUTPUT_FILE} salvat: {ok}/{len(meciuri)} analizate de Gemini.")


if __name__ == "__main__":
    main()
