"""
===============================================================================
EDITORIAL PROOFREADER — Post-generation article correction
===============================================================================
One LLM call (Sonnet, temperature 0.2) that returns surgical corrections:
1. LANGUAGE: typos, grammar, declension, prepositions, comma errors
2. FACTS: amounts/dates wrong vs hard_facts, hallucinated studies, contradictions
3. STRUCTURE: H2 mismatch vs plan, missing main entity in intro, duplicate sentences

Returns JSON with corrections that are applied via str.replace().
Each correction is applied ONLY if the original text appears EXACTLY ONCE.

Cost: ~$0.01-0.02 per article (one Sonnet call).
===============================================================================
"""

import json
import re
from typing import Dict, List, Optional


_PROOFREADER_SYSTEM = """Jesteś korektorem i redaktorem polskich artykułów SEO.
Analizujesz artykuł i zwracasz chirurgiczne poprawki w formacie JSON.
Temperature 0.2 — precyzja, nie kreatywność. Max 30 poprawek."""

_PROOFREADER_PROMPT = """Przeanalizuj poniższy artykuł i znajdź błędy w 3 kategoriach:

1. JĘZYK (severity: low)
   - Literówki, ortografia
   - Błędy odmiany (zły przypadek, zła osoba/czas)
   - Złe przyimki
   - Powtórzenie tego samego słowa w sąsiednich zdaniach (NIE dotyczy fraz kluczowych SEO)
   - Brak/nadmiar przecinków

2. FAKTY (severity: high)
   - Kwoty/daty/progi niezgodne z poniższymi HARD FACTS
   - Wymyślone badania, statystyki, cytaty (halucynacja)
   - Błędne nazwy przepisów/ustaw/artykułów
   - Sprzeczności wewnętrzne

3. STRUKTURA (severity: medium)
   - Brak encji głównej ("{main_entity}") w intro lub H1
   - Duplikaty zdań między sekcjami (to samo zdanie pojawia się 2+ razy)

REGUŁY:
- NIE przepisuj artykułu. NIE zmieniaj stylu. NIE dodawaj treści.
- Każda poprawka to MINIMALNA zmiana: 1-5 słów.
- Frazy kluczowe SEO ({main_keyword}) NIGDY nie zmieniaj.
- Zgłaszaj TYLKO rzeczywiste błędy, nie subiektywne preferencje.
- Max 30 poprawek.

HARD FACTS (wartości absolutne — artykuł MUSI je mieć poprawnie):
{hard_facts}

ENCJA GŁÓWNA: {main_entity}

ARTYKUŁ:
{article}

Zwróć TYLKO JSON (bez markdown code block):
{{
  "corrections": [
    {{
      "original": "dokładny fragment z artykułu (10-50 znaków)",
      "replacement": "poprawiony fragment",
      "reason": "krótkie wyjaśnienie",
      "type": "language|fact|structure",
      "severity": "low|medium|high"
    }}
  ],
  "hallucinations": [
    {{"text": "podejrzany fragment", "reason": "dlaczego to halucynacja", "severity": "high"}}
  ],
  "summary": {{
    "language_issues": 0,
    "fact_issues": 0,
    "structure_issues": 0,
    "overall_quality": "good|acceptable|needs_work"
  }}
}}"""


def _apply_corrections(article: str, corrections: List[Dict]) -> tuple:
    """Apply corrections to article text.

    Only applies if original text appears EXACTLY ONCE.
    Sorts by severity: high first, then medium, then low.

    Returns (corrected_text, applied_count, skipped_count).
    """
    severity_order = {"high": 0, "medium": 1, "low": 2}
    sorted_corrections = sorted(
        corrections,
        key=lambda c: severity_order.get(c.get("severity", "low"), 2)
    )

    applied = 0
    skipped = 0
    text = article

    for corr in sorted_corrections:
        original = corr.get("original", "")
        replacement = corr.get("replacement", "")

        if not original or not replacement or original == replacement:
            skipped += 1
            continue

        count = text.count(original)
        if count == 1:
            text = text.replace(original, replacement, 1)
            applied += 1
            print(f"[PROOFREADER] Applied: '{original[:40]}' → '{replacement[:40]}' ({corr.get('type')}/{corr.get('severity')})")
        else:
            skipped += 1
            if count == 0:
                print(f"[PROOFREADER] Skipped (not found): '{original[:50]}'")
            else:
                print(f"[PROOFREADER] Skipped (ambiguous, {count}x): '{original[:50]}'")

    return text, applied, skipped


def proofread_article(
    article_text: str,
    s1_data: Dict,
    variables: Dict = None,
    model: str = "sonnet",
) -> Dict:
    """Run editorial proofreading on the article.

    Args:
        article_text: Full article in markdown
        s1_data: Full S1 data (for hard_facts)
        variables: Pipeline variables (for main_entity, main_keyword)
        model: LLM model to use

    Returns:
        Dict with corrected_text, corrections, hallucinations, stats
    """
    from src.common.llm import claude_call

    variables = variables or {}
    main_entity = variables.get("ENCJA_GLOWNA", "")
    main_keyword = s1_data.get("main_keyword", "")

    # Collect hard facts
    hard_facts_list = []
    entity_seo = s1_data.get("entity_seo") or {}

    # From variables
    hf_raw = variables.get("_hard_facts") or s1_data.get("hard_facts") or []
    for hf in hf_raw:
        if isinstance(hf, dict):
            val = hf.get("value", "")
            cat = hf.get("category", "")
            if val:
                hard_facts_list.append(f"- {val} ({cat})" if cat else f"- {val}")
        elif isinstance(hf, str) and hf:
            hard_facts_list.append(f"- {hf}")

    hard_facts_text = "\n".join(hard_facts_list[:20]) if hard_facts_list else "(brak hard facts)"

    prompt = _PROOFREADER_PROMPT.format(
        main_entity=main_entity,
        main_keyword=main_keyword,
        hard_facts=hard_facts_text,
        article=article_text[:12000],  # Cap to avoid token overflow
    )

    try:
        response_text, usage = claude_call(
            system_prompt=_PROOFREADER_SYSTEM,
            user_prompt=prompt,
            model=model,
            max_tokens=3000,
            temperature=0.2,
        )

        # Parse JSON from response
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if not json_match:
            print("[PROOFREADER] No JSON in response")
            return {"corrected_text": article_text, "error": "no_json", "stats": {"applied": 0}}

        result = json.loads(json_match.group())
        corrections = result.get("corrections") or []
        hallucinations = result.get("hallucinations") or []
        summary = result.get("summary") or {}

        # Apply corrections
        corrected_text, applied, skipped = _apply_corrections(article_text, corrections)

        print(f"[PROOFREADER] Applied {applied}/{len(corrections)} corrections, "
              f"skipped {skipped}. Hallucinations: {len(hallucinations)}. "
              f"Quality: {summary.get('overall_quality', 'unknown')}")

        return {
            "corrected_text": corrected_text,
            "corrections": corrections,
            "hallucinations": hallucinations,
            "summary": summary,
            "stats": {
                "total": len(corrections),
                "applied": applied,
                "skipped": skipped,
                "hallucination_count": len(hallucinations),
            },
        }

    except Exception as e:
        print(f"[PROOFREADER] Error: {e}")
        return {
            "corrected_text": article_text,
            "error": str(e),
            "stats": {"applied": 0},
        }
