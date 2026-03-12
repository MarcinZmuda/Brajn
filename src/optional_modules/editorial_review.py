"""
Editorial Review — optional module.
AI-powered article review for quality, accuracy, and style.
"""
from src.common.llm import claude_call


def run_editorial(text: str, s1_data: dict = None) -> dict:
    """
    Run editorial review on article text.
    Returns review with suggestions and score.
    """
    main_keyword = (s1_data or {}).get("main_keyword", "")

    system = """Jesteś doświadczonym redaktorem naczelnym polskiego portalu informacyjnego.
Oceniasz artykuł pod kątem: jakości języka, spójności, poprawności merytorycznej, SEO, naturalności.
Zwróć JSON z oceną i konkretnymi sugestiami poprawek."""

    user = f"""Przeanalizuj poniższy artykuł SEO na temat "{main_keyword}".

ARTYKUŁ:
{text[:15000]}

Zwróć JSON:
{{
  "score": 0-100,
  "summary": "krótkie podsumowanie jakości",
  "strengths": ["mocne strony"],
  "issues": [
    {{
      "severity": "HIGH/MEDIUM/LOW",
      "type": "language/seo/accuracy/structure",
      "description": "opis problemu",
      "suggestion": "propozycja poprawki",
      "location": "wskazanie miejsca w tekście"
    }}
  ],
  "seo_assessment": {{
    "keyword_integration": "natural/forced/missing",
    "structure_quality": "good/average/poor",
    "readability": "high/medium/low"
  }}
}}"""

    response, usage = claude_call(
        system_prompt=system,
        user_prompt=user,
        max_tokens=3000,
        temperature=0.3,
    )

    import json
    try:
        first = response.find("{")
        last = response.rfind("}")
        if first >= 0 and last >= 0:
            result = json.loads(response[first:last+1])
            result["usage"] = usage
            return result
    except json.JSONDecodeError:
        pass

    return {
        "score": 0,
        "summary": "Nie udało się przeprowadzić recenzji",
        "raw_response": response[:500],
        "usage": usage,
    }
