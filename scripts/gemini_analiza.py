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

# TheSportsDB — API gratuit pentru rezultate recente reale (cheia publica "123")
TSDB_KEY  = os.getenv("THESPORTSDB_KEY", "123").strip()
TSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{TSDB_KEY}"
FORM_CACHE_FILE = "cache_forma_echipe.json"
GEMINI_BASE    = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

MODELS_TO_TRY = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

INPUT_FILE  = "alte_meciuri.json"
OUTPUT_FILE = "alte_meciuri.json"

DELAY_SECONDS  = 7    # intre requesturi normale (sub 10 RPM, limita free 2.5-flash)
RETRY_WAIT     = 65   # secunde de asteptare la 429
MAX_RETRIES    = 3


# Valoarea de piata a loturilor nationale (Transfermarkt, aproximativ, milioane €).
# Indicator obiectiv de forta: Brazilia (~900) >> Mexic (~200).
VALORI_LOT = {
    "England": 1500, "France": 1250, "Spain": 1100, "Portugal": 950,
    "Brazil": 900, "Germany": 850, "Argentina": 800, "Netherlands": 750,
    "Italy": 700, "Belgium": 550, "Norway": 500, "Turkey": 420,
    "Uruguay": 350, "Morocco": 350, "Croatia": 300, "Colombia": 300,
    "Denmark": 300, "Switzerland": 280, "Austria": 300, "Sweden": 300,
    "Ukraine": 280, "Japan": 260, "USA": 250, "Senegal": 250,
    "Nigeria": 250, "Poland": 240, "Serbia": 240, "Greece": 240,
    "Ecuador": 220, "Scotland": 200, "Ivory Coast": 200, "Czechia": 190,
    "Czech Republic": 190, "Mexico": 200, "Hungary": 150, "South Korea": 150,
    "Ghana": 150, "Algeria": 150, "Wales": 140, "Slovakia": 120,
    "Romania": 120, "Canada": 120, "Egypt": 120, "Slovenia": 100,
    "Cameroon": 100, "Paraguay": 90, "Chile": 80, "Australia": 80,
    "Venezuela": 70, "Tunisia": 60, "Iran": 50, "Saudi Arabia": 50,
    "South Africa": 50, "Peru": 40, "Uzbekistan": 30, "Costa Rica": 30,
    "Panama": 30, "Qatar": 25, "Cape Verde": 20, "Curacao": 20,
    "Iraq": 20, "Jordan": 15, "Honduras": 15, "Haiti": 15,
    "New Zealand": 15, "Bolivia": 15,
}


def valoare_lot(team: str) -> Optional[int]:
    if team in VALORI_LOT:
        return VALORI_LOT[team]
    for nume, val in VALORI_LOT.items():
        if nume.lower() in team.lower() or team.lower() in nume.lower():
            return val
    return None


def _load_form_cache() -> Dict[str, Any]:
    if os.path.exists(FORM_CACHE_FILE):
        try:
            with open(FORM_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


_form_cache = _load_form_cache()


def _save_form_cache() -> None:
    try:
        with open(FORM_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_form_cache, f, ensure_ascii=False)
    except Exception:
        pass


def _tsdb_get(path: str, params: Dict[str, str]) -> Optional[Dict]:
    try:
        r = requests.get(f"{TSDB_BASE}/{path}", params=params, timeout=15)
        time.sleep(2)  # limita free TheSportsDB: ~30 requesturi/min
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def forma_echipa(team: str) -> Optional[str]:
    """Ultimele 5 rezultate reale ale echipei (TheSportsDB, gratuit).
    Returneaza un text scurt pentru prompt sau None daca nu gaseste echipa."""
    entry = _form_cache.get(team)
    if entry and time.time() < entry.get("expires_at", 0):
        return entry.get("value")

    value = None
    data = _tsdb_get("searchteams.php", {"t": team})
    teams = (data or {}).get("teams") or []
    if teams:
        team_id = teams[0].get("idTeam")
        res = _tsdb_get("eventslast.php", {"id": team_id})
        events = (res or {}).get("results") or []
        lines = []
        for ev in events[:5]:
            hs, as_ = ev.get("intHomeScore"), ev.get("intAwayScore")
            if hs is None or as_ is None:
                continue
            lines.append(f"{ev.get('dateEvent','')}: {ev.get('strHomeTeam','')} {hs}-{as_} {ev.get('strAwayTeam','')}")
        if lines:
            value = "; ".join(lines)

    _form_cache[team] = {"value": value, "expires_at": time.time() + 24 * 3600}
    return value


def implied_probs(match: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Probabilitati implicite din cote, normalizate (fara marja casei)."""
    try:
        c1 = float(match.get("cota_1") or 0)
        cx = float(match.get("cota_x") or 0)
        c2 = float(match.get("cota_2") or 0)
        if not (c1 and cx and c2):
            return None
        p1, px, p2 = 1 / c1, 1 / cx, 1 / c2
        s = p1 + px + p2
        return {"1": round(p1 / s, 3), "X": round(px / s, 3), "2": round(p2 / s, 3)}
    except Exception:
        return None


def build_prompt(match: Dict[str, Any]) -> str:
    home = match.get("home", "")
    away = match.get("away", "")
    liga = match.get("liga", "")
    data = match.get("data", "")
    ora  = match.get("ora", "")
    c1   = match.get("cota_1", "-")
    cx   = match.get("cota_x", "-")
    c2   = match.get("cota_2", "-")

    probs = implied_probs(match)
    prob_line = ""
    if probs:
        prob_line = (f"Probabilitati implicite din piata (fara marja): "
                     f"1={probs['1']*100:.0f}%, X={probs['X']*100:.0f}%, 2={probs['2']*100:.0f}%\n")

    val_h, val_a = valoare_lot(home), valoare_lot(away)
    valoare_block = ""
    if val_h and val_a:
        raport = max(val_h, val_a) / max(min(val_h, val_a), 1)
        valoare_block = (f"VALOARE LOT (Transfermarkt, aprox., mil. €): {home}={val_h}, {away}={val_a} "
                         f"(raport {raport:.1f}x). O diferenta mare de valoare indica o diferenta "
                         f"clara de calitate individuala — pondereaz-o serios in pronostic.\n")

    forma_h = forma_echipa(home)
    forma_a = forma_echipa(away)
    forma_block = ""
    if forma_h or forma_a:
        forma_block = "\nREZULTATE RECENTE REALE (sursa: TheSportsDB — foloseste-le in locul memoriei tale, sunt actuale):\n"
        if forma_h:
            forma_block += f"- {home}: {forma_h}\n"
        if forma_a:
            forma_block += f"- {away}: {forma_a}\n"

    context_extra = ""
    if "Cupa Mondială" in liga or "World Cup" in liga:
        context_extra = """
CONTEXT TURNEU (Cupa Mondiala 2026, SUA/Canada/Mexic):
- Teren neutru in majoritatea meciurilor: avantajul "gazdelor" din cote e mai mic decat in campionat
- Tine cont de faza turneului (grupe vs eliminatorii): in grupe echipele mari pot rota, in meciul 3 din grupe calificarea poate fi deja decisa (risc de rezultate atipice)
- In faza eliminatorie egalul la 90 de minute e mai probabil (echipele joaca prudent), iar pronosticul X/1X/X2 se refera la rezultatul din timpul regulamentar
- Considera oboseala (interval scurt intre meciuri), deplasarile lungi si conditiile de caldura
- Nationalele au istoric H2H putin relevant; forma din calificari si amicale recente conteaza mai mult"""

    return f"""Esti un analist sportiv profesionist. Analizeaza meciul de mai jos si returneaza DOAR un obiect JSON valid, fara alte texte sau explicatii.

MECI: {home} vs {away}
Competitie: {liga}
Data: {data}, ora {ora}
Cote: 1={c1}, X={cx}, 2={c2}
{prob_line}{valoare_block}{forma_block}{context_extra}

Analizeaza:
1. Forma recenta a echipelor (ultimele 5-10 meciuri)
2. Absente si suspendari importante
3. Tipul meciului si miza
4. Stilul de joc al ambelor echipe
5. Head to head recent

REGULI DE CALIBRARE (obligatorii):
- Foloseste probabilitatile implicite din cote ca punct de plecare; piata greseste rar mult
- NU da un pronostic ferm (1 sau 2) pe o selectie cu probabilitate implicita sub 45% — prefera 1X/X2 sau alt pariu
- incredere 5 doar daca probabilitatea estimata depaseste 75%; incredere 4 pentru 65-75%; incredere 3 pentru 55-65%; altfel 1-2
- Daca nu ai informatii sigure despre absente/forma, nu le inventa — spune asta in avertisment si scade increderea
- Pronosticul trebuie sa fie coerent cu cotele date (nu recomanda 1 daca cota_1 > 3.00)

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
            "maxOutputTokens": 512,
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


def prob_pronostic(match: Dict, pronostic: str) -> Optional[float]:
    """Probabilitatea implicita din piata pentru pronosticul dat."""
    probs = implied_probs(match)
    if not probs:
        return None
    if pronostic in ("1", "X", "2"):
        return probs[pronostic]
    if pronostic == "1X":
        return probs["1"] + probs["X"]
    if pronostic == "X2":
        return probs["X"] + probs["2"]
    return None


def valideaza_incredere(match: Dict, pronostic: str, incredere: int) -> int:
    """Plafoneaza increderea daca pronosticul contrazice probabilitatile din piata."""
    if not implied_probs(match):
        return incredere
    p = prob_pronostic(match, pronostic)
    if p is None:
        return min(incredere, 4)  # GG/NG/Sub/Peste fara cote disponibile: maxim 4
    if p < 0.45:
        return min(incredere, 1)
    if p < 0.55:
        return min(incredere, 2)
    if p < 0.65:
        return min(incredere, 3)
    if p < 0.75:
        return min(incredere, 4)
    return incredere


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
                # 429 = modelul exista, doar e limitat temporar — il folosim,
                # retry-ul din call_gemini() gestioneaza asteptarea
                print(f"[gemini] Model: {model} (rate limit temporar, continui cu retry)")
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
    esecuri_consecutive = 0  # cota zilnica epuizata => abandonam elegant

    for i, match in enumerate(meciuri):
        home = match.get("home", "?")
        away = match.get("away", "?")

        # Skip daca deja analizat corect
        if match.get("analizat_de", "").startswith("gemini") and match.get("incredere"):
            print(f"  [{i+1:02d}] {home} vs {away} — SKIP (deja analizat)")
            actualizate.append(match)
            ok += 1
            continue

        if esecuri_consecutive >= 3:
            print(f"  [{i+1:02d}] {home} vs {away} — SKIP (cota zilnica Gemini epuizata)")
            actualizate.append(match)
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
            incredere = int(extracted.get("incredere") or 3)
            match["incredere"]        = valideaza_incredere(match, pronostic, incredere)
            # Pronostic "sigur": piata insasi da >= 85% sanse selectiei
            p = prob_pronostic(match, pronostic)
            match["prob_piata"]       = round(p, 3) if p else None
            match["pronostic_sigur"]  = bool(p and p >= 0.85)
            match["motiv"]            = extracted.get("motiv_scurt") or match.get("motiv", "")
            match["pariu_alternativ"] = extracted.get("pariu_alternativ", "")
            match["avertisment"]      = extracted.get("avertisment", "")
            match["analizat_de"]      = f"gemini/{model}"
            match["analizat_la"]      = datetime.now(timezone.utc).isoformat()

            stele = "⭐" * match["incredere"]
            print(f"OK → {pronostic} @ {match['cota_pronostic']} {stele}")
            ok += 1
            esecuri_consecutive = 0
        else:
            print("SKIP (fara date suficiente)")
            if text is None:
                esecuri_consecutive += 1

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

    _save_form_cache()
    sigure = sum(1 for m in actualizate if m.get("pronostic_sigur"))
    print(f"\n[OK] Salvat: {ok}/{len(meciuri)} analizate, {sigure} pronosticuri sigure (prob piata >= 85%).")


if __name__ == "__main__":
    main()
