"""
SERP data fetcher — SerpAPI integration.
Extracts: organic results, PAA, Featured Snippet, AI Overview, Related Searches.
"""
import json
import requests
from src.common.config import SERPAPI_KEY
from src.common.llm import claude_call


def _generate_paa_claude_fallback(keyword: str, serp_data: dict) -> list:
    """Generate PAA questions using Claude when SerpAPI returns no related_questions."""
    try:
        snippets = []
        for r in serp_data.get("organic_results", [])[:6]:
            s = r.get("snippet", "")
            if s:
                snippets.append(s)

        ai_overview_text = ""
        aio = serp_data.get("ai_overview", {})
        if isinstance(aio, dict):
            ai_overview_text = aio.get("text", "") or aio.get("snippet", "")
        elif isinstance(aio, str):
            ai_overview_text = aio

        context_parts = []
        if snippets:
            context_parts.append("Fragmenty z SERP:\n" + "\n".join(f"- {s}" for s in snippets))
        if ai_overview_text:
            context_parts.append(f"Google AI Overview:\n{ai_overview_text[:400]}")

        context = "\n\n".join(context_parts) if context_parts else f"Temat: {keyword}"

        prompt = f"""Dla zapytania "{keyword}" wygeneruj 6 pytań z sekcji Google "Ludzie pytają też" (PAA).

Kontekst z SERP:
{context}

Zwróć TYLKO JSON array (bez markdown):
[
  {{"question": "Pytanie 1?", "answer": "Krótka odpowiedź 1-2 zdania"}},
  {{"question": "Pytanie 2?", "answer": "Krótka odpowiedź 1-2 zdania"}}
]

6 pytań. Pytania muszą być naturalne, jak rzeczywiście zadają je użytkownicy Google."""

        raw, _ = claude_call(
            system_prompt="",
            user_prompt=prompt,
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            temperature=0.7,
            timeout=30,
        )

        first = raw.find("[")
        last = raw.rfind("]")
        if first == -1 or last == -1:
            return []

        items = json.loads(raw[first : last + 1])
        result = []
        for item in items[:6]:
            if isinstance(item, dict) and item.get("question"):
                result.append({
                    "question": item["question"],
                    "answer": item.get("answer", ""),
                    "source": "claude_fallback",
                })

        print(f"[SERP] Claude PAA fallback: {len(result)} questions")
        return result

    except Exception as e:
        print(f"[SERP] PAA fallback error: {e}")
        return []


def fetch_serp_data(keyword: str, num_results: int = 8) -> dict:
    """
    Fetch full SERP data from SerpAPI:
    - Organic results (URLs, titles, snippets)
    - PAA (People Also Ask)
    - Featured Snippet
    - AI Overview
    - Related Searches
    """
    empty_result = {
        "organic_results": [],
        "paa": [],
        "featured_snippet": None,
        "ai_overview": None,
        "related_searches": [],
        "serp_titles": [],
        "serp_snippets": [],
    }

    if not SERPAPI_KEY:
        print("[SERP] SerpAPI key not configured")
        return empty_result

    try:
        print(f"[SERP] Fetching for: {keyword}")
        response = requests.get(
            "https://serpapi.com/search",
            params={
                "q": keyword,
                "api_key": SERPAPI_KEY,
                "num": num_results,
                "hl": "pl",
                "gl": "pl",
            },
            timeout=30,
        )

        if response.status_code != 200:
            print(f"[SERP] Error: HTTP {response.status_code}")
            return empty_result

        serp_data = response.json()

        # AI Overview
        ai_overview = None
        ai_overview_data = serp_data.get("ai_overview", {})
        if ai_overview_data:
            ai_overview = {
                "text": ai_overview_data.get("text", "") or ai_overview_data.get("snippet", ""),
                "sources": [
                    {
                        "title": src.get("title", ""),
                        "link": src.get("link", ""),
                        "snippet": src.get("snippet", ""),
                    }
                    for src in ai_overview_data.get("sources", [])[:5]
                ],
                "text_blocks": ai_overview_data.get("text_blocks", []),
            }

        # PAA
        paa_questions = []
        for q in serp_data.get("related_questions", []):
            paa_questions.append({
                "question": q.get("question", ""),
                "answer": q.get("snippet", ""),
                "source": q.get("link", ""),
                "title": q.get("title", ""),
            })

        if not paa_questions:
            paa_questions = _generate_paa_claude_fallback(keyword, serp_data)

        # Featured Snippet
        featured_snippet = None
        answer_box = serp_data.get("answer_box", {})
        if answer_box:
            featured_snippet = {
                "type": answer_box.get("type", "unknown"),
                "title": answer_box.get("title", ""),
                "answer": answer_box.get("answer", "") or answer_box.get("snippet", ""),
                "source": answer_box.get("link", ""),
                "displayed_link": answer_box.get("displayed_link", ""),
            }

        # Related Searches
        related_searches = [
            rs.get("query", "")
            for rs in serp_data.get("related_searches", [])
            if rs.get("query")
        ]

        # Organic results
        organic_results = serp_data.get("organic_results", [])
        serp_titles = [r.get("title", "") for r in organic_results if r.get("title")]
        serp_snippets = [r.get("snippet", "") for r in organic_results if r.get("snippet")]

        print(f"[SERP] Found: {len(organic_results)} organic, {len(paa_questions)} PAA, "
              f"{len(related_searches)} related, snippet={'yes' if featured_snippet else 'no'}, "
              f"AI overview={'yes' if ai_overview else 'no'}")

        return {
            "organic_results": organic_results,
            "paa": paa_questions,
            "featured_snippet": featured_snippet,
            "ai_overview": ai_overview,
            "related_searches": related_searches,
            "serp_titles": serp_titles,
            "serp_snippets": serp_snippets,
        }

    except Exception as e:
        print(f"[SERP] Fetch error: {e}")
        return empty_result
