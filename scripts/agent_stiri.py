# -*- coding: utf-8 -*-
"""
Agent stiri sportive - fotbal, in romana.

Surse:
  1. BBC Sport Football (RSS)
  2. Sky Sports Football (RSS)
  3. The Guardian Football (RSS)
  4. ESPN Soccer (RSS)
  5. Goal.com (RSS)
  6. ProSport.ro (scraping homepage, fallback)

Logica:
  - Rulare de 2 ori pe zi (10:00 si 19:00 RO)
  - Pana la 5 stiri NOI per rulare (daca nu gaseste, nu forteaza)
  - Acumulare in stiri.json - lista creste, cele mai vechi de 7 zile se sterg
  - Anti-duplicate prin hash titlu normalizat + verificare similaritate cu istoricul
  - Gemini Flash (gratuit) selecteaza si rezuma in romana
  - Fallback: daca Gemini cade, primele 3 stiri din RSS, traduse minimal

Output: stiri.json cu format:
{
  "updated_at": "...",
  "stiri": [
    { "id": "...", "titlu": "...", "rezumat": "...", "categorie": "Fotbal",
      "surse": [...], "data_publicare": "ISO", "data_afisaj": "29 aprilie 2026, 10:00" }
  ]
}
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import feedparser
import requests
from bs4 import BeautifulSoup

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/Bucharest")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=3))


# ============================================================
# CONFIGURARE
# ============================================================

OUTPUT_FILE = "stiri.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()  # fallback optional

NEWS_PER_RUN = 5
RETENTION_DAYS = 7
MAX_RSS_ITEMS_PER_FEED = 15
MAX_TOTAL_FOR_LLM = 60

RSS_FEEDS = [
    ("BBC Sport Football",     "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("Sky Sports Football",    "https://www.skysports.com/rss/12040"),
    ("The Guardian Football",  "https://www.theguardian.com/football/rss"),
    ("FourFourTwo",            "https://www.fourfourtwo.com/feeds/all"),
    ("World Soccer",           "https://www.worldsoccer.com/feed"),
]

# Site-uri cu scraping homepage (fallback / completare RO)
SCRAPE_SITES = [
    ("ProSport.ro", "https://www.prosport.ro/"),
    ("GSP.ro",      "https://www.gsp.ro/"),
]

LUNI_RO = [
    "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
    "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
]


# ============================================================
# UTILITARE
# ============================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_local_display() -> str:
    dt = datetime.now(LOCAL_TZ)
    return f"{dt.day} {LUNI_RO[dt.month - 1]} {dt.year}, {dt.strftime('%H:%M')}"


def clean_text(value: str) -> str:
    return " ".join((value or "").replace("\n", " ").split()).strip()


def normalize_title(title: str) -> str:
    """Pentru deduplicare: lowercase, fara punctuatie, fara stopwords scurte."""
    text = (title or "").lower()
    text = re.sub(r"[^\w\s]", " ", text)
    words = [w for w in text.split() if len(w) >= 3]
    return " ".join(sorted(set(words)))


def title_hash(title: str) -> str:
    return hashlib.md5(normalize_title(title).encode("utf-8")).hexdigest()[:12]


def titles_similar(title_a: str, title_b: str, threshold: float = 0.55) -> bool:
    """Doua titluri sunt similare daca au >threshold cuvinte comune (din cel mai scurt)."""
    a_words = set(normalize_title(title_a).split())
    b_words = set(normalize_title(title_b).split())
    if not a_words or not b_words:
        return False
    common = a_words & b_words
    smaller = min(len(a_words), len(b_words))
    if smaller == 0:
        return False
    return (len(common) / smaller) >= threshold


# ============================================================
# COLECTARE STIRI
# ============================================================

def collect_rss_items() -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:MAX_RSS_ITEMS_PER_FEED]:
                title = clean_text(entry.get("title", ""))
                summary = clean_text(entry.get("summary", ""))
                # Curatare HTML din summary
                summary = BeautifulSoup(summary, "html.parser").get_text(" ")
                summary = clean_text(summary)
                link = entry.get("link", "")
                published = entry.get("published", "") or entry.get("updated", "")
                if title:
                    items.append({
                        "source": source_name,
                        "title": title,
                        "summary": summary[:500],
                        "link": link,
                        "published": published,
                    })
            print(f"[RSS] {source_name}: {len(feed.entries[:MAX_RSS_ITEMS_PER_FEED])} stiri")
        except Exception as exc:
            print(f"[RSS] {source_name} esec: {exc}")
    return items


def collect_scrape_items() -> List[Dict[str, str]]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SportNewsBot/1.0)"}
    items: List[Dict[str, str]] = []
    for source_name, url in SCRAPE_SITES:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            seen_titles = set()
            count = 0
            # Cautam titluri lungi (probabil articole) in <h1>, <h2>, <h3> si <a>
            for tag in soup.select("h1, h2, h3, a"):
                text = clean_text(tag.get_text(" "))
                if 35 <= len(text) <= 200 and text not in seen_titles:
                    # Filtram navigatie / categorii
                    lower = text.lower()
                    if any(skip in lower for skip in ["meniu", "abonare", "newsletter", "cookie", "politica", "termenii"]):
                        continue
                    seen_titles.add(text)
                    href = tag.get("href", "") if tag.name == "a" else url
                    if href and not href.startswith("http"):
                        href = url.rstrip("/") + "/" + href.lstrip("/")
                    items.append({
                        "source": source_name,
                        "title": text,
                        "summary": "",
                        "link": href or url,
                        "published": "",
                    })
                    count += 1
                if count >= 12:
                    break
            print(f"[SCRAPE] {source_name}: {count} titluri")
        except Exception as exc:
            print(f"[SCRAPE] {source_name} esec: {exc}")
    return items


# ============================================================
# DEDUPLICARE INPUT
# ============================================================

def dedupe_input_items(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Daca acelasi subiect apare la mai multe surse, le grupam ca semnal de cross-reference."""
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = title_hash(item["title"])
        if key in grouped:
            grouped[key]["sources"].add(item["source"])
            if not grouped[key]["summary"] and item.get("summary"):
                grouped[key]["summary"] = item["summary"]
        else:
            grouped[key] = {
                "title": item["title"],
                "summary": item.get("summary", ""),
                "sources": {item["source"]},
                "link": item.get("link", ""),
                "published": item.get("published", ""),
            }

    # Si verificare similaritate fuzzy: daca doua titluri sunt similare, le unim
    keys = list(grouped.keys())
    merged_keys: set = set()
    for i, key_a in enumerate(keys):
        if key_a in merged_keys:
            continue
        for key_b in keys[i + 1:]:
            if key_b in merged_keys:
                continue
            if titles_similar(grouped[key_a]["title"], grouped[key_b]["title"]):
                grouped[key_a]["sources"].update(grouped[key_b]["sources"])
                merged_keys.add(key_b)

    result = []
    for key, val in grouped.items():
        if key in merged_keys:
            continue
        result.append({
            "title": val["title"],
            "summary": val["summary"],
            "sources": sorted(list(val["sources"])),
            "link": val["link"],
            "published": val["published"],
            "cross_ref_count": len(val["sources"]),
        })

    # Sortam: cele cu mai multe surse primele (mai bine confirmate)
    result.sort(key=lambda x: x["cross_ref_count"], reverse=True)
    return result


# ============================================================
# ISTORIC - INCARCARE / SALVARE / CURATARE
# ============================================================

def load_history() -> List[Dict[str, Any]]:
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        items = payload.get("stiri", [])
        # Compatibilitate cu schema veche care nu avea id/data_publicare
        upgraded = []
        for item in items:
            if "id" not in item:
                item["id"] = title_hash(item.get("titlu", ""))
            if "data_publicare" not in item:
                # Daca avem updated_at general, il folosim
                item["data_publicare"] = payload.get("updated_at", now_iso())
            if "data_afisaj" not in item:
                item["data_afisaj"] = ""
            upgraded.append(item)
        return upgraded
    except Exception as exc:
        print(f"[history] read failed: {exc}")
        return []


def cleanup_old(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    kept = []
    for item in history:
        try:
            pub = datetime.fromisoformat(item["data_publicare"].replace("Z", "+00:00"))
        except Exception:
            kept.append(item)
            continue
        if pub >= cutoff:
            kept.append(item)
    removed = len(history) - len(kept)
    if removed:
        print(f"[history] sters {removed} stiri mai vechi de {RETENTION_DAYS} zile")
    return kept


def is_already_in_history(candidate_title: str, history: List[Dict[str, Any]]) -> bool:
    candidate_id = title_hash(candidate_title)
    for item in history:
        if item.get("id") == candidate_id:
            return True
        if titles_similar(candidate_title, item.get("titlu", ""), threshold=0.55):
            return True
    return False


# ============================================================
# TRADUCERE FALLBACK (Google Translate gratuit, fara cheie)
# ============================================================

# Dictionar mic pentru corectii dupa Google Translate
FOOTBALL_GLOSSARY_RO = {
    "manager": "antrenor",
    "Manager": "Antrenor",
    "draw": "egal",
    "Draw": "Egal",
    "goalkeeper": "portar",
    "Goalkeeper": "Portar",
    "transfer window": "perioada de transferuri",
    "Transfer window": "Perioada de transferuri",
    "summer transfer": "transfer de vara",
    "winter transfer": "transfer de iarna",
    "matchday": "etapa",
    "Matchday": "Etapa",
    "fixture": "meci",
    "Fixture": "Meci",
    "kick-off": "start",
    "Kick-off": "Start",
    "extra time": "prelungiri",
    "Extra time": "Prelungiri",
    "penalties": "lovituri de departajare",
    "Penalties": "Lovituri de departajare",
    "head coach": "antrenor principal",
    "Head coach": "Antrenor principal",
    "club world cup": "Cupa Mondiala a Cluburilor",
    "Club World Cup": "Cupa Mondiala a Cluburilor",
}


def google_translate_free(text: str, target: str = "ro", source: str = "en") -> str:
    """Traducere prin endpoint-ul public Google Translate. Fara cheie, fara cost."""
    if not text:
        return text
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": source,
            "tl": target,
            "dt": "t",
            "q": text[:5000],
        }
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        # Format raspuns: [[[translation, original, ...], ...], ...]
        translated = "".join([seg[0] for seg in data[0] if seg[0]])
        return translated.strip() or text
    except Exception as exc:
        print(f"[google-translate] esec: {exc}")
        return text


def apply_glossary(text: str) -> str:
    """Corecteaza termenii fotbalistici dupa traducerea Google."""
    result = text
    for en, ro in FOOTBALL_GLOSSARY_RO.items():
        result = result.replace(en, ro)
    return result


def translate_to_romanian(text: str) -> str:
    """Wrapper care traduce + aplica glossarul."""
    if not text or not text.strip():
        return text
    translated = google_translate_free(text, target="ro", source="en")
    return apply_glossary(translated)

def build_prompt(items: List[Dict[str, Any]], history_titles: List[str]) -> str:
    compact = json.dumps(items[:MAX_TOTAL_FOR_LLM], ensure_ascii=False, indent=2)
    history_titles_str = "\n".join(f"- {t}" for t in history_titles[:30]) if history_titles else "(istoric gol)"

    return f"""Esti un editor sportiv obiectiv specializat pe FOTBAL.

Ai primit titluri si rezumate de la 5 surse internationale + 1 site Romania.
Sarcina:
1. Selecteaza pana la {NEWS_PER_RUN} stiri NOI relevante despre FOTBAL.
2. STRICT: nu repeta nimic din lista de stiri deja publicate de mai jos.
3. STRICT: doar stiri de pe surse de top, evita zvonurile si subiectele neclare.
4. Prefera stiri confirmate de mai multe surse (campul cross_ref_count = numar surse).
5. Scrie titlul si rezumatul in LIMBA ROMANA, clar si neutru.
6. Daca nu gasesti {NEWS_PER_RUN} stiri noi de calitate, returneaza mai putine. NU inventa.

Stiri DEJA publicate (NU le repeta, nici parafrazate):
{history_titles_str}

Returneaza STRICT JSON valid, fara markdown, schema:
{{
  "stiri": [
    {{
      "titlu": "Titlu in romana, clar, fara clickbait",
      "rezumat": "60-100 cuvinte in romana, factual, neutru",
      "categorie": "Fotbal",
      "surse": ["nume sursa 1", "nume sursa 2"]
    }}
  ]
}}

Date sursa de procesat:
{compact}
"""


def call_gemini(prompt: str) -> Dict[str, Any]:
    """Apel Gemini cu retry automat 3x pentru erori tranzitorii (503, 429, timeout)."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY lipseste")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"

    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.25,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=60,
            )
            # Erori tranzitorii care merita retry
            if response.status_code in (503, 429, 500, 502, 504):
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                wait = (3 ** attempt)  # 1s, 3s, 9s
                print(f"[gemini] {last_error} - retry {attempt + 1}/3 dupa {wait}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
            content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(content)
        except requests.exceptions.Timeout as exc:
            last_error = f"timeout: {exc}"
            wait = (3 ** attempt)
            print(f"[gemini] {last_error} - retry {attempt + 1}/3 dupa {wait}s")
            time.sleep(wait)
            continue
        except Exception as exc:
            # Erori non-tranzitorii (404 model deprecat, 401 cheie gresita, etc.) - nu retry
            raise

    raise RuntimeError(f"Gemini esec dupa 3 retries: {last_error}")


def call_openai(prompt: str) -> Dict[str, Any]:
    """Fallback daca Gemini cade si OPENAI_API_KEY exista."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY lipseste")
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": "Raspunzi doar cu JSON valid, in romana."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.25,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


# ============================================================
# CONSTRUIRE STIRI NOI
# ============================================================

def build_new_news(payload: Dict[str, Any], history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    raw_news = payload.get("stiri", [])
    if not isinstance(raw_news, list):
        return []

    new_items: List[Dict[str, Any]] = []
    seen_ids_in_batch: set = set()

    for raw in raw_news[:NEWS_PER_RUN * 2]:
        titlu = clean_text(str(raw.get("titlu", "")))
        if not titlu:
            continue

        # Anti-duplicate vs istoric
        if is_already_in_history(titlu, history):
            print(f"[skip duplicat istoric] {titlu[:80]}")
            continue

        # Anti-duplicate intra-batch
        item_id = title_hash(titlu)
        if item_id in seen_ids_in_batch:
            continue
        # Si fuzzy intra-batch
        is_dup_in_batch = any(titles_similar(titlu, n["titlu"]) for n in new_items)
        if is_dup_in_batch:
            continue

        seen_ids_in_batch.add(item_id)

        rezumat = clean_text(str(raw.get("rezumat", "")))[:700]
        categorie = clean_text(str(raw.get("categorie", "Fotbal"))) or "Fotbal"
        surse = raw.get("surse", [])
        if not isinstance(surse, list):
            surse = []
        surse = [clean_text(str(s)) for s in surse[:4] if s]

        new_items.append({
            "id": item_id,
            "titlu": titlu,
            "rezumat": rezumat,
            "categorie": categorie,
            "surse": surse,
            "data_publicare": now_iso(),
            "data_afisaj": now_local_display(),
        })

        if len(new_items) >= NEWS_PER_RUN:
            break

    return new_items


def fallback_from_rss(items: List[Dict[str, Any]], history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Lant 4-nivele de fallback pentru a livra stiri in romana indiferent ce cade.

    Nivel 1: selectie deja facuta de Gemini (in fluxul principal, nu aici)
    Nivel 2: Gemini doar pentru traducere (mai simplu decat selectie)
    Nivel 3: OpenAI daca exista cheia
    Nivel 4: Google Translate gratuit (fara cheie) + glossar fotbal RO
    Final: engleza originala (foarte improbabil sa ajungem aici)
    """
    fallback_items: List[Dict[str, Any]] = []
    for item in items:
        title = item["title"]
        if is_already_in_history(title, history):
            continue
        if any(titles_similar(title, f["titlu"]) for f in fallback_items):
            continue
        fallback_items.append({
            "id": title_hash(title),
            "titlu": title,
            "rezumat": item.get("summary") or "(rezumat indisponibil)",
            "categorie": "Fotbal",
            "surse": item.get("sources", []),
            "data_publicare": now_iso(),
            "data_afisaj": now_local_display(),
        })
        if len(fallback_items) >= NEWS_PER_RUN:
            break

    if not fallback_items:
        return fallback_items

    # NIVEL 2: incercam Gemini doar pentru traducere
    if GEMINI_API_KEY:
        try:
            translate_prompt = f"""Traduci urmatoarele stiri sportive din engleza in romana.
Pastreaza acelasi numar de elemente si aceeasi ordine. Nu modifica structura, doar traduci textul.

Returneaza STRICT JSON valid:
{{
  "stiri": [
    {{ "titlu": "titlu tradus in romana", "rezumat": "rezumat tradus in romana sau original daca e gol" }}
  ]
}}

Date de tradus:
{json.dumps([{"titlu": f["titlu"], "rezumat": f["rezumat"]} for f in fallback_items], ensure_ascii=False, indent=2)}
"""
            translated = call_gemini(translate_prompt)
            translated_list = translated.get("stiri", [])
            for i, t in enumerate(translated_list):
                if i < len(fallback_items):
                    new_titlu = clean_text(str(t.get("titlu", "")))
                    new_rezumat = clean_text(str(t.get("rezumat", "")))
                    if new_titlu:
                        fallback_items[i]["titlu"] = new_titlu
                    if new_rezumat:
                        fallback_items[i]["rezumat"] = new_rezumat
            print("[fallback-niv2] traducere Gemini reusita")
            return fallback_items
        except Exception as exc:
            print(f"[fallback-niv2] Gemini traducere esec: {exc}")

    # NIVEL 3: incercam OpenAI daca exista cheia
    if OPENAI_API_KEY:
        try:
            translate_prompt = f"""Traduci urmatoarele stiri sportive din engleza in romana.
Pastreaza ordinea, structura JSON. Doar traducere.

Returneaza JSON cu schema:
{{ "stiri": [{{ "titlu": "...", "rezumat": "..." }}] }}

Date:
{json.dumps([{"titlu": f["titlu"], "rezumat": f["rezumat"]} for f in fallback_items], ensure_ascii=False, indent=2)}
"""
            translated = call_openai(translate_prompt)
            translated_list = translated.get("stiri", [])
            for i, t in enumerate(translated_list):
                if i < len(fallback_items):
                    new_titlu = clean_text(str(t.get("titlu", "")))
                    new_rezumat = clean_text(str(t.get("rezumat", "")))
                    if new_titlu:
                        fallback_items[i]["titlu"] = new_titlu
                    if new_rezumat:
                        fallback_items[i]["rezumat"] = new_rezumat
            print("[fallback-niv3] traducere OpenAI reusita")
            return fallback_items
        except Exception as exc:
            print(f"[fallback-niv3] OpenAI traducere esec: {exc}")

    # NIVEL 4: Google Translate gratuit (fara cheie, ultimul recurs inainte de engleza)
    print("[fallback-niv4] folosesc Google Translate gratuit")
    translated_count = 0
    for item in fallback_items:
        try:
            new_titlu = translate_to_romanian(item["titlu"])
            new_rezumat = translate_to_romanian(item["rezumat"]) if item["rezumat"] else item["rezumat"]
            if new_titlu and new_titlu != item["titlu"]:
                item["titlu"] = new_titlu
                translated_count += 1
            if new_rezumat:
                item["rezumat"] = new_rezumat
        except Exception as exc:
            print(f"[fallback-niv4] traducere item esec: {exc}")
            continue
    print(f"[fallback-niv4] tradus {translated_count}/{len(fallback_items)} cu Google Translate")

    return fallback_items


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    # 1. Incarca istoricul si curata stirile mai vechi de 7 zile
    history = load_history()
    history = cleanup_old(history)
    history_titles = [h.get("titlu", "") for h in history]

    # 2. Colecteaza din toate sursele
    rss_items = collect_rss_items()
    scrape_items = collect_scrape_items()
    all_items = rss_items + scrape_items

    if not all_items:
        print("[main] niciun item colectat. Pastrez istoricul existent.")
        save_payload(history)
        return

    # 3. Deduplicare input + cross-reference (cate surse confirma)
    deduped = dedupe_input_items(all_items)
    print(f"[main] dupa dedupe: {len(deduped)} subiecte distincte (din {len(all_items)} brute)")

    # 4. Filtram cele care sunt deja in istoric (economisim tokeni LLM)
    new_candidates = [d for d in deduped if not is_already_in_history(d["title"], history)]
    print(f"[main] {len(new_candidates)} candidate noi (vs istoric)")

    if not new_candidates:
        print("[main] nimic nou de adaugat. Pastrez istoricul existent.")
        save_payload(history)
        return

    # 5. LLM pentru selectie + rezumat in romana
    new_items: List[Dict[str, Any]] = []
    try:
        prompt = build_prompt(new_candidates, history_titles)
        provider = "gemini" if GEMINI_API_KEY else ("openai" if OPENAI_API_KEY else None)
        if provider == "gemini":
            payload = call_gemini(prompt)
        elif provider == "openai":
            payload = call_openai(prompt)
        else:
            raise RuntimeError("Niciun LLM configurat (GEMINI_API_KEY sau OPENAI_API_KEY)")
        new_items = build_new_news(payload, history)
        print(f"[main] LLM ({provider}) a returnat {len(new_items)} stiri noi valide")
    except Exception as exc:
        print(f"[main] LLM esec: {exc}. Folosesc fallback RSS direct.")
        new_items = fallback_from_rss(new_candidates, history)

    # 6. Adaugam stirile noi in fata listei (cele mai noi sus)
    if new_items:
        history = new_items + history
        print(f"[main] adaugat {len(new_items)} stiri noi. Total in lista: {len(history)}")
    else:
        print("[main] nimic de adaugat dupa procesare.")

    # 7. Salvare
    save_payload(history)


def save_payload(stiri: List[Dict[str, Any]]) -> None:
    payload = {
        "updated_at": now_iso(),
        "updated_at_afisaj": now_local_display(),
        "configuratie": {
            "stiri_per_rulare_max": NEWS_PER_RUN,
            "retentie_zile": RETENTION_DAYS,
            "categorie": "Fotbal",
            "limba": "romana",
            "surse_principale": [name for name, _ in RSS_FEEDS] + [name for name, _ in SCRAPE_SITES],
        },
        "numar_stiri": len(stiri),
        "stiri": stiri,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[OK] {OUTPUT_FILE}: {len(stiri)} stiri totale.")


if __name__ == "__main__":
    main()
