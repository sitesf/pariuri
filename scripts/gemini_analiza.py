# -*- coding: utf-8 -*-
"""
Agent: Gemini Analiza Meciuri
- Delay 6s intre requesturi (sub limita de 15 RPM)
- Retry automat la 429 (rate limit)
- Detectie automata model disponibil
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE    = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

MODELS_TO_TRY = [
    "gemini-2.0-flash",
    "gemini-1.5-pro-latest",
    "gemini-1.5-pro",
]

INPUT_FILE  = "alte_meciuri.json"
OUTPUT_FILE = "alte_meciuri.json"

DELAY_SECONDS  = 6    # intre requesturi normale
RETRY_WAIT     = 65   # secunde de asteptare la 429
MAX_RETRIES    = 3


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
2. Absente si suspendari importante
3. Tipul meciului si miza
4. Stilul de joc al ambelor echipe
5. Head to head recent

Returneaza EXCLUSIV acest JSON (fara markdown, fara ```json, fara alte cuvinte inainte sau dupa):
{{"pronostic":"1X","tip_pariu":"Gazde nu pierd","cota_recomandata":1.45,"incredere":3,"motiv_scurt":"descriere scurta max 15 cuvinte in romana","pariu_alternativ":"Sub 2.5 goluri","avertisment":"ce ar putea invalida pronosticul"}}

Valori posibile pentru pronostic: 1, X, 2, 1X, X2, GG, NG, Sub 2.5, Peste 2.5
incredere este un numar intreg de la 1 la 5 (5=maxim sigur)
cota_recomandata este un numar zecimal calculat din cotele date"""


def call_gemini(prompt: str, model: str) -> Optional[str]:
    url = GEMINI_BASE.format(model=model, key=GEMINI_API_KEY)

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 256,
            "responseMimeType": "application/json",
        },
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if resp.status_code == 200:
                data = resp.json()
                parts = (data.get("candidates") or [{}])[0] \
                    .get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts).strip()

            elif resp.status_code == 429:
                print(f"    [429] Rate limit. Astept {RETRY_WAIT}s (incercare {attempt}/{MAX_RETRIES})...")
                time.sleep(RETRY_WAIT)
                continue

            else:
                print(f"    [HTTP {resp.status_code}] {resp.text[:120]}")
                return None

        except Exception as e:
            print(f"    [ERR] {e}")
            if attempt < MAX_RETRIES:
                time.sleep(10)

    return None


def extract_json(text: str) -> Optional[Dict]:
    if not text:
        return None

    # 1. Direct JSON
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. Bloc ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # 3. Primul { } cu "pronostic"
    m = re.search(r'\{[^{}]*"pronostic"[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    # 4. Orice { }
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    # 5. Extragere camp cu camp prin regex
    result = {}
    str_fields = ["pronostic", "tip_pariu", "motiv_scurt", "pariu_alternativ", "avertisment"]
    num_fields = ["cota_recomandata", "incredere"]

    for f in str_fields:
        m2 = re.search(rf'"{f}"\s*:\s*"([^"]+)"', text)
        if m2:
            result[f] = m2.group(1)

    for f in num_fields:
        m2 = re.search(rf'"{f}"\s*:\s*([\d.]+)', text)
        if m2:
            try:
                result[f] = float(m2.group(1)) if "." in m2.group(1) else int(m2.group(1))
            except Exception:
                pass

    if result.get("pronostic"):
        return result

    print(f"    [WARN] JSON invalid. Text primit: {repr(text[:150])}")
    return None


def calc_cota(match: Dict, pronostic: str) -> Optional[float]:
    c1 = float(match.get("cota_1") or 0)
    cx = float(match.get("cota_x") or 0)
    c2 = float(match.get("cota_2") or 0)
    if pronostic == "1"  and c1:        return c1
    if pronostic == "2"  and c2:        return c2
    if pronostic == "X"  and cx:        return cx
    if pronostic == "1X" and c1 and cx: return round(1 / (1/c1 + 1/cx), 2)
    if pronostic == "X2" and cx and c2: return round(1 / (1/cx + 1/c2), 2)
    return None


def find_model() -> Optional[str]:
    test = {"contents": [{"parts": [{"text": "ok"}]}],
            "generationConfig": {"maxOutputTokens": 5}}
    for model in MODELS_TO_TRY:
        url = GEMINI_BASE.format(model=model, key=GEMINI_API_KEY)
        try:
            r = requests.post(url, json=test, timeout=15)
            if r.status_code == 200:
                print(f"[gemini] Model: {model}")
                return model
            elif r.status_code == 429:
                print(f"[gemini] {model}: rate limit — astept 65s...")
                time.sleep(65)
                r2 = requests.post(url, json=test, timeout=15)
                if r2.status_code == 200:
                    print(f"[gemini] Model: {model}")
                    return model
            else:
                print(f"[gemini] {model}: HTTP {r.status_code}")
        except Exception as e:
            print(f"[gemini] {model}: {e}")
    return None


def main():
    if not GEMINI_API_KEY:
        print("[ERR] GEMINI_API_KEY lipsa.")
        return

    if not os.path.exists(INPUT_FILE):
        print(f"[ERR] {INPUT_FILE} nu exista.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    meciuri = data.get("meciuri", [])
    if not meciuri:
        print("[ERR] Nu exista meciuri.")
        return

    model = find_model()
    if not model:
        print("[ERR] Niciun model disponibil.")
        return

    print(f"[gemini] Analizez {len(meciuri)} meciuri | delay {DELAY_SECONDS}s intre requesturi\n")

    actualizate = []
    ok = 0

    for i, match in enumerate(meciuri):
        home = match.get("home", "?")
        away = match.get("away", "?")

        # Skip daca deja analizat corect
        if match.get("analizat_de", "").startswith("gemini") and match.get("incredere"):
            print(f"  [{i+1:02d}] {home} vs {away} — SKIP (deja analizat)")
            actualizate.append(match)
            ok += 1
            continue

        print(f"  [{i+1:02d}] {home} vs {away}...", end=" ", flush=True)

        text = call_gemini(build_prompt(match), model)
        extracted = extract_json(text) if text else None

        if extracted and extracted.get("pronostic"):
            pronostic = extracted["pronostic"]
            cota_rec  = extracted.get("cota_recomandata") or calc_cota(match, pronostic)

            match["pronostic"]        = pronostic
            match["tip_pariu"]        = extracted.get("tip_pariu", "")
            match["cota_pronostic"]   = round(float(cota_rec), 2) if cota_rec else match.get("cota_pronostic")
            match["incredere"]        = int(extracted.get("incredere") or 3)
            match["motiv"]            = extracted.get("motiv_scurt") or match.get("motiv", "")
            match["pariu_alternativ"] = extracted.get("pariu_alternativ", "")
            match["avertisment"]      = extracted.get("avertisment", "")
            match["analizat_de"]      = f"gemini/{model}"
            match["analizat_la"]      = datetime.now(timezone.utc).isoformat()

            stele = "⭐" * match["incredere"]
            print(f"OK → {pronostic} @ {match['cota_pronostic']} {stele}")
            ok += 1
        else:
            print("SKIP (fara date suficiente)")

        actualizate.append(match)

        # Delay intre requesturi — las un pic de spatiu fata de limita
        if i < len(meciuri) - 1:
            time.sleep(DELAY_SECONDS)

    data["meciuri"]    = actualizate
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["gemini_analiza"] = {
        "total":     len(meciuri),
        "analizate": ok,
        "model":     model,
        "la":        datetime.now(timezone.utc).isoformat(),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Salvat: {ok}/{len(meciuri)} analizate.")


if __name__ == "__main__":
    main()
