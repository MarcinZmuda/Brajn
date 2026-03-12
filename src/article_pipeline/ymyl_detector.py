"""
YMYL (Your Money Your Life) detector.
Classifies topics into: prawo, zdrowie, finanse, none.
Used to determine disclaimer requirements and enrichment strategies.
"""
from src.common.llm import claude_call

YMYL_KEYWORDS = {
    "prawo": [
        "kodeks", "ustawa", "sąd", "wyrok", "kara", "mandat", "prawnik",
        "adwokat", "radca", "prokuratura", "przestępstwo", "wykroczenie",
        "rozwód", "alimenty", "spadek", "testament", "umowa", "odszkodowanie",
        "pozew", "apelacja", "egzekucja", "komornik", "notariusz",
    ],
    "zdrowie": [
        "lekarz", "choroba", "leczenie", "lek", "dawka", "objaw", "diagnoza",
        "operacja", "szpital", "terapia", "antybiotyk", "ból", "zabieg",
        "ciąża", "dieta", "suplementy", "witamina", "alergia", "depresja",
    ],
    "finanse": [
        "kredyt", "pożyczka", "inwestycja", "giełda", "podatek", "PIT",
        "VAT", "konto", "bank", "ubezpieczenie", "emerytura", "hipoteka",
        "rata", "odsetki", "ZUS", "faktura",
    ],
}

DISCLAIMERS = {
    "prawo": {
        "heading": "Zastrzeżenie prawne",
        "body": "Niniejszy artykuł ma charakter wyłącznie informacyjny i nie stanowi porady prawnej. W indywidualnych sprawach zalecamy konsultację z wykwalifikowanym prawnikiem.",
    },
    "zdrowie": {
        "heading": "Zastrzeżenie medyczne",
        "body": "Niniejszy artykuł ma charakter wyłącznie informacyjny i edukacyjny. Nie stanowi porady medycznej ani nie zastępuje konsultacji z lekarzem lub innym wykwalifikowanym specjalistą.",
    },
    "finanse": {
        "heading": "Zastrzeżenie finansowe",
        "body": "Niniejszy artykuł ma charakter wyłącznie informacyjny i nie stanowi porady finansowej ani rekomendacji inwestycyjnej.",
    },
}


def detect_ymyl_local(keyword: str) -> dict:
    """
    Fast local YMYL detection based on keyword matching.
    Returns {"category": "prawo"|"zdrowie"|"finanse"|"none", "confidence": float}
    """
    keyword_lower = keyword.lower()
    scores = {}

    for category, keywords in YMYL_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in keyword_lower)
        if score > 0:
            scores[category] = score

    if not scores:
        return {"category": "none", "confidence": 0.0, "is_ymyl": False}

    best = max(scores, key=scores.get)
    confidence = min(1.0, scores[best] / 3)

    return {
        "category": best,
        "confidence": confidence,
        "is_ymyl": True,
        "disclaimer": DISCLAIMERS.get(best, {}),
    }


def detect_ymyl_llm(keyword: str) -> dict:
    """
    LLM-based YMYL detection for ambiguous cases.
    Uses Claude Haiku for fast, cheap classification.
    """
    try:
        response, _ = claude_call(
            system_prompt="Klasyfikujesz zapytania SEO pod kątem YMYL (Your Money Your Life).",
            user_prompt=f"""Sklasyfikuj hasło SEO: "{keyword}"

Kategorie:
- "prawo" — treści prawne, sądowe, regulacje
- "zdrowie" — medyczne, zdrowotne, farmaceutyczne
- "finanse" — finansowe, bankowe, podatkowe, inwestycyjne
- "none" — brak YMYL

Zwróć TYLKO JSON: {{"category": "...", "confidence": 0.0-1.0}}""",
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            temperature=0.0,
        )

        import json
        first = response.find("{")
        last = response.rfind("}")
        if first >= 0 and last >= 0:
            data = json.loads(response[first:last+1])
            category = data.get("category", "none")
            if category in DISCLAIMERS:
                data["is_ymyl"] = True
                data["disclaimer"] = DISCLAIMERS[category]
            else:
                data["is_ymyl"] = False
            return data

    except Exception as e:
        print(f"[YMYL] LLM detection error: {e}")

    return detect_ymyl_local(keyword)


def detect_ymyl(keyword: str) -> dict:
    """
    Detect YMYL category. Uses local first, LLM for low-confidence cases.
    """
    local = detect_ymyl_local(keyword)
    if local["confidence"] >= 0.5:
        return local
    return detect_ymyl_llm(keyword)


def get_disclaimer_text(category: str) -> str:
    """Get disclaimer text for a YMYL category."""
    aliases = {"medycyna": "zdrowie", "finance": "finanse"}
    category = aliases.get(category, category)
    d = DISCLAIMERS.get(category)
    if d:
        return f"\n\n**{d['heading']}**\n{d['body']}"
    return ""
