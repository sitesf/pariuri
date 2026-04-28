import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import feedparser
import requests
from bs4 import BeautifulSoup

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

RSS_FEEDS = [
    "https://www.espn.com/espn/rss/news",
    "https://www.skysports.com/rss/12040",
    "https://www.bbc.co.uk/sport/rss.xml",
]

FALLBACK_SITES = [
    "https://www.espn.com/",
    "https://www.skysports.com/",
    "https://www.bbc.com/sport",
]

OUTPUT_FILE = "stiri.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: str) -> str:
    return " ".join((value or "").replace("\n", " ").split()).strip()


def collect_rss_items() -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        source_name = clean_text(feed.feed.get("title", feed_url))
        for entry in feed.entries[:12]:
            title = clean_text(entry.get("title", ""))
            summary = clean_text(entry.get("summary", ""))
            link = entry.get("link", "")
            if title:
                items.append({
                    "source": source_name,
                    "title": title,
                    "summary": summary[:500],
                    "link": link,
                })
    return items


def collect_site_headlines() -> List[Dict[str, str]]:
    headers = {"User-Agent": "Mozilla/5.0 SportAIRadar/1.0"}
    items: List[Dict[str, str]] = []
    for url in FALLBACK_SITES:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            titles = []
            for tag in soup.select("h1, h2, h3, a"):
                text = clean_text(tag.get_text(" "))
                if 35 <= len(text) <= 160 and text not in titles:
                    titles.append(text)
                if len(titles) >= 12:
                    break
            for title in titles:
                items.append({"source": url, "title": title, "summary": "", "link": url})
        except Exception as exc:
            print(f"Site fallback failed for {url}: {exc}")
    return items


def build_prompt(items: List[Dict[str, str]]) -> str:
    compact = json.dumps(items[:45], ensure_ascii=False, indent=2)
    return f"""
Esti un editor sportiv obiectiv.
Ai primit titluri si rezumate din 3 surse sportive.
Sarcina ta:
1. identifica 3 subiecte care apar sau sunt sustinute de mai multe surse;
2. evita zvonurile neverificate;
3. scrie 3 stiri scurte, clare, neutre;
4. fiecare stire trebuie sa aiba titlu, rezumat, categorie si surse.

Returneaza strict JSON valid, fara markdown, cu schema:
{{
  "stiri": [
    {{
      "titlu": "...",
      "rezumat": "maxim 80 de cuvinte",
      "categorie": "Fotbal/Tenis/Baschet/General",
      "surse": ["sursa 1", "sursa 2"]
    }}
  ]
}}

Date sursa:
{compact}
""".strip()


def call_openai(prompt: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY lipseste")
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": "Raspunzi doar cu JSON valid."},
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


def call_gemini(prompt: str) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY lipseste")
    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
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
    response.raise_for_status()
    content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(content)


def fallback_news(items: List[Dict[str, str]]) -> Dict[str, Any]:
    selected = items[:3]
    stiri = []
    for item in selected:
        stiri.append({
            "titlu": item.get("title", "Actualizare sportiva"),
            "rezumat": item.get("summary") or "Subiect preluat automat din fluxurile sportive. Configureaza cheia LLM pentru rezumat AI verificat incrucisat.",
            "categorie": "General",
            "surse": [item.get("source", "RSS")],
        })
    return {"stiri": stiri}


def normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    news = payload.get("stiri", [])
    if not isinstance(news, list):
        news = []
    clean_news = []
    for item in news[:3]:
        clean_news.append({
            "titlu": clean_text(str(item.get("titlu", "Actualizare sportiva"))),
            "rezumat": clean_text(str(item.get("rezumat", "")))[:650],
            "categorie": clean_text(str(item.get("categorie", "General"))),
            "surse": item.get("surse", [])[:3] if isinstance(item.get("surse"), list) else [],
        })
    return {"updated_at": now_iso(), "stiri": clean_news}


def main() -> None:
    items = collect_rss_items()
    if len(items) < 9:
        items.extend(collect_site_headlines())

    if not items:
        payload = {"stiri": []}
    else:
        prompt = build_prompt(items)
        try:
            provider = os.getenv("LLM_PROVIDER", "openai").lower()
            payload = call_gemini(prompt) if provider == "gemini" else call_openai(prompt)
        except Exception as exc:
            print(f"LLM failed, using fallback. Error: {exc}")
            payload = fallback_news(items)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(normalize_payload(payload), file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
