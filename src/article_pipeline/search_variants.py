"""
Search Variants Generator — generates periphrases and variant forms.
Used for BRAJEN_PROMPTS_v1.0 variables: PERYFRAZY, WARIANTY_POTOCZNE, WARIANTY_FORMALNE.
"""
import json
from src.common.llm import claude_call


def generate_search_variants(main_keyword: str, secondary_keywords: list = None) -> dict:
    """
    Generate search variants for the main keyword:
    - Periphrases (peryfrazy): alternative ways to say the same thing
    - Colloquial variants (potoczne): how people talk about it informally
    - Formal variants (formalne): official/professional terminology
    """
    secondary = secondary_keywords or []
    secondary_str = ", ".join(secondary[:10]) if secondary else "brak"

    prompt = f"""Dla hasła SEO "{main_keyword}" wygeneruj warianty wyszukiwania.

Dodatkowe frazy: {secondary_str}

Zwróć TYLKO JSON:
{{
  "peryfrazy": ["alternatywne sposoby wyrażenia tego samego", "min 5 peryfraz"],
  "warianty_potoczne": ["jak ludzie mówią nieformalnie", "min 3 warianty"],
  "warianty_formalne": ["oficjalna/profesjonalna terminologia", "min 3 warianty"],
  "anglicyzmy": ["terminy angielskie używane w polskim kontekście"]
}}

Wygeneruj naturalne polskie warianty. Peryfrazy to najważniejsze — muszą brzmieć naturalnie w artykule publicystycznym."""

    try:
        response, _ = claude_call(
            system_prompt="Jesteś polskim lingwistą SEO. Generujesz naturalne warianty fraz.",
            user_prompt=prompt,
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            temperature=0.7,
        )

        first = response.find("{")
        last = response.rfind("}")
        if first >= 0 and last >= 0:
            data = json.loads(response[first:last+1])
            return {
                "peryfrazy": data.get("peryfrazy", []),
                "warianty_potoczne": data.get("warianty_potoczne", []),
                "warianty_formalne": data.get("warianty_formalne", []),
                "anglicyzmy": data.get("anglicyzmy", []),
            }

    except Exception as e:
        print(f"[VARIANTS] Generation error: {e}")

    return _deterministic_fallback(main_keyword)


def _deterministic_fallback(keyword: str) -> dict:
    """Fallback when LLM is unavailable."""
    words = keyword.split()
    return {
        "peryfrazy": [keyword, " ".join(reversed(words))] if len(words) > 1 else [keyword],
        "warianty_potoczne": [],
        "warianty_formalne": [],
        "anglicyzmy": [],
    }
