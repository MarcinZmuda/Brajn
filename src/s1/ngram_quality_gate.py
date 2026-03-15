"""
===============================================================================
N-gram Quality Gate — heuristic + LLM filtering of S1 n-gram/entity noise
===============================================================================
Removes CSS/JS/HTML artifacts, e-commerce UI, product cards, repeated words,
and other scraping noise from S1 analysis output.

Two stages:
1. Heuristic rules (free, instant) — 9 pattern-based rules
2. Haiku LLM validation (optional, ~$0.002) — contextual filtering

Author: BRAJN Team
===============================================================================
"""

import re
from typing import Dict, List, Tuple, Optional

# ================================================================
# HEURISTIC RULES (Stage 1 — free, instant)
# ================================================================

# Rule 1: Short token sequences (1-2 char tokens)
_RE_SHORT_TOKENS = re.compile(r'^(?:\w{1,2}\s+){2,}')

# Rule 2: Repeated word (menu menu, void void void)
_RE_REPEATED_WORD = re.compile(r'^(\w+)(\s+\1)+$', re.IGNORECASE)

# Rule 3: CSS/JS/HTML first-word tokens
_CSS_JS_FIRST_WORDS = {
    "font", "border", "margin", "padding", "display", "position",
    "background", "color", "text", "line", "flex", "grid",
    "overflow", "visibility", "opacity", "transition", "animation",
    "transform", "cursor", "pointer", "box", "object", "align",
    "justify", "vertical", "height", "width", "max", "min",
    "var", "void", "null", "undefined", "function", "return",
    "const", "let", "class", "import", "export", "default",
    "div", "span", "section", "header", "footer", "nav",
    "input", "button", "select", "option", "form", "label",
}

# Rule 5: E-commerce UI patterns
_ECOMMERCE_PATTERNS = [
    re.compile(r'filtruj\s+wed[łl]ug', re.IGNORECASE),
    re.compile(r'dodaj\s+do\s+koszyk', re.IGNORECASE),
    re.compile(r'inni\s+klienci\s+(?:wybrali|kupili|ogl[aą]dali)', re.IGNORECASE),
    re.compile(r'faq\s+najcz[eę][sś]ciej', re.IGNORECASE),
    re.compile(r'(?:sortuj|filtr)\s+(?:po|wg|wed[łl]ug)', re.IGNORECASE),
    re.compile(r'(?:kup\s+teraz|zamów\s+teraz|do\s+koszyka)', re.IGNORECASE),
    re.compile(r'(?:darmowa\s+dostawa|bezp[łl]atna\s+dostawa)', re.IGNORECASE),
    re.compile(r'(?:porównaj|porównanie)\s+(?:cen|produkt)', re.IGNORECASE),
    re.compile(r'(?:opinie|recenzje)\s+(?:klient|użytkowni)', re.IGNORECASE),
    re.compile(r'(?:newsletter|zapisz\s+si[eę]|subskryb)', re.IGNORECASE),
    re.compile(r'(?:polityka\s+prywatno|regulamin|cookies)', re.IGNORECASE),
    re.compile(r'(?:wyprzeda[żz]|promocj[aeiou]|rabat|kod\s+rabatowy)', re.IGNORECASE),
    re.compile(r'(?:koszyk|zamówieni[eao]|p[łl]atno[sś][cć])', re.IGNORECASE),
]

# Rule 6: Product card patterns
_PRODUCT_CARD_PATTERNS = [
    re.compile(r'^(?:produkt|o\s+produk|bestseller|nowość)\s+', re.IGNORECASE),
    re.compile(r'cena\s+z[łl]', re.IGNORECASE),
    re.compile(r'(?:ochraniacze?\s+na\s+matrac|prze[sś]cierad)', re.IGNORECASE),
    re.compile(r'(?:rozmiar|wymiar|kolor|wariant)\s*:', re.IGNORECASE),
    re.compile(r'(?:stan\s+magazynow|dost[eę]pno[sś][cć]|w\s+magazynie)', re.IGNORECASE),
]

# Rule 2b: Measurement units mixed with product words
_UNIT_PATTERN = re.compile(
    r'\b(?:kg|g|cm|mm|ml|l|szt|zł|pln|eur|usd|%)\b', re.IGNORECASE
)

# Rule 7: Code characters
_RE_CODE_CHARS = re.compile(r'[{}();=<>\\|@#$%^&*]')

# Rule 8: CamelCase or snake_case
_RE_CAMEL = re.compile(r'[a-z][A-Z]')
_RE_SNAKE = re.compile(r'\w+_\w+_\w+')

# Rule 9: Numeric-heavy short n-grams
_RE_DIGIT_HEAVY = re.compile(r'^[\d\s.,;:/-]+$')

# Polish diacritics for ASCII-only check
_POLISH_DIACRITICS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def is_garbage_ngram(text: str) -> Tuple[bool, str]:
    """Check if n-gram is garbage. Returns (is_garbage, reason)."""
    if not text or len(text.strip()) < 2:
        return True, "empty_or_too_short"

    t = text.strip()
    t_lower = t.lower()
    words = t_lower.split()

    # Rule 1: Short token sequences (t n i, e t n, var e)
    if len(words) >= 2 and all(len(w) <= 2 for w in words):
        return True, "short_token_sequence"

    # Rule 2: Repeated word (menu menu, void void)
    if _RE_REPEATED_WORD.match(t):
        return True, "repeated_word"

    # Rule 2b: Content word repeated in multi-word ngram (non-consecutive)
    # Catches: "obciążeniowa kg kołdra obciążeniowa", "melatonina melatonina",
    # "kołdra obciążeniowa classic kołdra"
    if len(words) >= 2:
        long_words = [w for w in words if len(w) > 3]
        if len(long_words) >= 2 and len(long_words) != len(set(long_words)):
            return True, "repeated_content_word"

    # Rule 2c: Measurement unit mixed with product words in 3+ word ngram
    # Catches: "obciążeniowa kg kołdra", "kołdra 7kg obciążeniowa"
    if len(words) >= 3 and _UNIT_PATTERN.search(t):
        non_unit_words = [w for w in words if not _UNIT_PATTERN.match(w)]
        if len(non_unit_words) >= 2:
            return True, "product_spec_with_unit"

    # Rule 2d: Short unit+product patterns from product cards
    # Catches: "cena zł", "200 cm kołdra", "kg materac"
    _UNIT_PRODUCT_PATTERNS = [
        re.compile(r'^\d+\s*(cm|mm|kg|g|ml|l|zł|pln)\b', re.IGNORECASE),
        re.compile(r'^(cena|wymiar|waga|rozmiar)\s+(zł|pln|cm|kg)', re.IGNORECASE),
        re.compile(r'\b(szt|op|kpl)\b', re.IGNORECASE),
    ]
    for pat in _UNIT_PRODUCT_PATTERNS:
        if pat.search(t_lower):
            return True, "unit_product_pattern"

    # Rule 3: First word is CSS/JS/HTML + rest has no Polish chars
    if len(words) >= 2 and words[0] in _CSS_JS_FIRST_WORDS:
        rest = " ".join(words[1:])
        if not any(c in _POLISH_DIACRITICS for c in rest):
            return True, "css_js_html_prefix"

    # Rule 4: Purely ASCII multi-word, no Polish word, short avg length
    if len(words) >= 2 and not any(c in _POLISH_DIACRITICS for c in t):
        avg_len = sum(len(w) for w in words) / len(words)
        _POLISH_COMMON = {
            "jak", "co", "to", "na", "do", "nie", "jest", "czy", "dla",
            "po", "od", "za", "bez", "przez", "nad", "pod", "ile", "gdzie",
            "jaki", "jaka", "jakie", "ten", "ta", "te", "ale", "lub",
            "tak", "bardzo", "tylko", "przed", "przy", "ktory", "ktora",
        }
        has_polish_word = any(w in _POLISH_COMMON for w in words)
        if avg_len < 6 and not has_polish_word:
            return True, "ascii_non_polish"

    # Rule 5: E-commerce UI patterns
    for pat in _ECOMMERCE_PATTERNS:
        if pat.search(t):
            return True, "ecommerce_ui"

    # Rule 6: Product card patterns
    for pat in _PRODUCT_CARD_PATTERNS:
        if pat.search(t):
            return True, "product_card"

    # Rule 7: Code characters
    if _RE_CODE_CHARS.search(t):
        return True, "code_chars"

    # Rule 8: CamelCase or snake_case
    if _RE_CAMEL.search(t) or _RE_SNAKE.search(t):
        return True, "camelcase_or_snakecase"

    # Rule 9: Digit-heavy
    if _RE_DIGIT_HEAVY.match(t):
        return True, "digit_heavy"

    # Rule 10: Navigation/footer vocabulary — short n-grams (≤4 words)
    # composed entirely of site-chrome words
    if len(words) <= 4:
        _NAV_WORDS = {
            "serwis", "strona", "portal", "wersja", "wydanie",
            "redakcja", "archiwum", "kontakt", "mapa", "menu",
            "szukaj", "wyszukiwarka", "newsletter", "rss",
            "drukuj", "kontrast", "czcionka", "czcionki",
            "nota", "prawna", "informacje", "informacji",
            "online", "biuletyn", "publicznej", "deklaracja",
            "inne", "powrót", "góry", "policja", "policji",
            "najważniejsze", "najwazniejsze", "serwisu",
        }
        if all(w in _NAV_WORDS for w in words):
            return True, "nav_footer_vocabulary"

    return False, ""


def filter_ngrams_quality(ngrams: list) -> list:
    """Filter n-grams using heuristic rules. Returns clean list."""
    clean = []
    removed = []
    for ng in ngrams:
        text = (ng.get("ngram") or ng.get("text") or "").strip()
        is_garbage, reason = is_garbage_ngram(text)
        if is_garbage:
            removed.append((text, reason))
        else:
            clean.append(ng)

    if removed:
        print(f"[QUALITY_GATE] Removed {len(removed)} garbage n-grams: "
              f"{[(t, r) for t, r in removed[:8]]}{'...' if len(removed) > 8 else ''}")
    return clean


def filter_entities_quality(entities: list) -> list:
    """Filter entities using lighter rules (preserve proper nouns). Returns clean list."""
    clean = []
    removed = []
    for e in entities:
        text = e if isinstance(e, str) else (e.get("text") or e.get("entity") or "")
        text = text.strip()

        is_garbage = False
        reason = ""

        # Only apply strict rules to entities
        if _RE_REPEATED_WORD.match(text):
            is_garbage, reason = True, "repeated_word"
        elif _RE_CODE_CHARS.search(text):
            is_garbage, reason = True, "code_chars"
        elif _RE_CAMEL.search(text) or _RE_SNAKE.search(text):
            is_garbage, reason = True, "camelcase_or_snakecase"
        elif len(text.split()) >= 2 and all(len(w) <= 2 for w in text.split()):
            is_garbage, reason = True, "short_token_sequence"
        else:
            for pat in _ECOMMERCE_PATTERNS:
                if pat.search(text):
                    is_garbage, reason = True, "ecommerce_ui"
                    break

        if is_garbage:
            removed.append((text, reason))
        else:
            clean.append(e)

    if removed:
        print(f"[QUALITY_GATE] Removed {len(removed)} garbage entities: "
              f"{[(t, r) for t, r in removed[:5]]}{'...' if len(removed) > 5 else ''}")
    return clean


def filter_triples_quality(triples: list) -> list:
    """Filter factographic triples — remove platform/shop-specific ones."""
    _PLATFORM_PATTERNS = [
        re.compile(r'(?:serwis|platforma|strona|witryna|portal)\s+(?:oferuje|zawiera|udost[eę]pnia)', re.IGNORECASE),
        re.compile(r'(?:sekcj[aąeę]\s+b2b|panel\s+klienta|konto\s+u[żz]ytkownika)', re.IGNORECASE),
        re.compile(r'(?:koszyk|zamówieni[eao]|dostaw[aąeę]|p[łl]atno[sś])', re.IGNORECASE),
    ]

    clean = []
    removed = []
    for t in triples:
        if not isinstance(t, dict):
            clean.append(t)
            continue

        subj = t.get("subject", "")
        obj = t.get("object", "")
        combined = f"{subj} {obj}"

        is_garbage = False
        for pat in _PLATFORM_PATTERNS:
            if pat.search(combined):
                is_garbage = True
                break

        if is_garbage:
            removed.append(f"{subj} → {obj}")
        else:
            clean.append(t)

    if removed:
        print(f"[QUALITY_GATE] Removed {len(removed)} platform triples: {removed[:3]}")
    return clean


# ================================================================
# LLM VALIDATION (Stage 2 — Haiku, ~$0.002)
# ================================================================

_QUALITY_GATE_PROMPT = """Jesteś filtrem jakości danych SEO. Dostajesz listę n-gramów, encji i trójek faktograficznych
wyciągniętych z SERP dla hasła: "{keyword}".

Twoim zadaniem jest USUNĄĆ elementy, które NIE DOTYCZĄ tematu artykułu, a są artefaktami scrapingu:
- CSS/JS/HTML (font size, border radius, display flex)
- UI e-commerce (dodaj do koszyka, filtruj według, inni klienci wybrali)
- Nawigacja strony (menu, sidebar, footer links)
- Karty produktowe (produkt X, bestseller X, cena zł)
- Trójki o platformie/sklepie (Serwis oferuje..., Platforma zawiera...)
- Powtórzenia (void void, menu menu)

ZACHOWAJ elementy związane z tematem "{keyword}" — nawet jeśli brzmią dziwnie.
W razie wątpliwości — ZACHOWAJ.

N-GRAMY:
{ngrams_text}

ENCJE:
{entities_text}

TRÓJKI FAKTOGRAFICZNE:
{triples_text}

Zwróć JSON (TYLKO JSON, bez markdown):
{{"ngrams_remove": ["fraza1", "fraza2"], "entities_remove": ["encja1"], "triples_remove_indices": [0, 3]}}

Jeśli wszystko OK, zwróć: {{"ngrams_remove": [], "entities_remove": [], "triples_remove_indices": []}}"""


def validate_ngrams_llm(
    ngrams: list,
    entities: list,
    triples: list,
    main_keyword: str,
) -> Optional[Dict]:
    """Use Haiku LLM to contextually filter garbage. Returns removal instructions."""
    try:
        from src.common.llm import call_llm
    except ImportError:
        try:
            from common.llm import call_llm
        except ImportError:
            print("[QUALITY_GATE] LLM module not available, skipping Haiku validation")
            return None

    ngrams_text = "\n".join(
        f"- {ng.get('ngram') or ng.get('text', '')}" for ng in ngrams[:60]
    ) or "(brak)"

    entities_text = "\n".join(
        f"- {e if isinstance(e, str) else e.get('text', '')}" for e in entities[:30]
    ) or "(brak)"

    triples_text = "\n".join(
        f"[{i}] {t.get('subject', '')} → {t.get('verb', t.get('predicate', ''))} → {t.get('object', '')}"
        for i, t in enumerate(triples[:20])
        if isinstance(t, dict)
    ) or "(brak)"

    prompt = _QUALITY_GATE_PROMPT.format(
        keyword=main_keyword,
        ngrams_text=ngrams_text,
        entities_text=entities_text,
        triples_text=triples_text,
    )

    try:
        import json
        response = call_llm(
            prompt=prompt,
            model="haiku",
            temperature=0.0,
            max_tokens=1000,
        )
        # Parse JSON from response
        text = response if isinstance(response, str) else str(response)
        # Find JSON in response
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"[QUALITY_GATE] Haiku validation error: {e}")

    return None


# ================================================================
# MAIN ORCHESTRATOR
# ================================================================

def run_quality_gate(
    ngrams: list = None,
    extended_terms: list = None,
    entities: list = None,
    triples: list = None,
    main_keyword: str = "",
    use_llm: bool = True,
) -> Dict:
    """Run full quality gate: heuristics + optional LLM.

    Returns dict with cleaned lists and stats.
    """
    ngrams = list(ngrams or [])
    extended_terms = list(extended_terms or [])
    entities = list(entities or [])
    triples = list(triples or [])

    stats = {
        "ngrams_before": len(ngrams),
        "extended_before": len(extended_terms),
        "entities_before": len(entities),
        "triples_before": len(triples),
    }

    # Stage 1: Heuristic filtering
    ngrams = filter_ngrams_quality(ngrams)
    extended_terms = filter_ngrams_quality(extended_terms)
    entities = filter_entities_quality(entities)
    triples = filter_triples_quality(triples)

    # Stage 2: LLM validation (optional)
    if use_llm and (ngrams or entities or triples):
        llm_result = validate_ngrams_llm(ngrams, entities, triples, main_keyword)
        if llm_result:
            # Remove n-grams flagged by LLM
            remove_ngrams = set(r.lower() for r in (llm_result.get("ngrams_remove") or []))
            if remove_ngrams:
                before = len(ngrams)
                ngrams = [
                    ng for ng in ngrams
                    if (ng.get("ngram") or ng.get("text", "")).lower() not in remove_ngrams
                ]
                extended_terms = [
                    ng for ng in extended_terms
                    if (ng.get("ngram") or ng.get("text", "")).lower() not in remove_ngrams
                ]
                print(f"[QUALITY_GATE] Haiku removed {before - len(ngrams)} n-grams")

            # Remove entities flagged by LLM
            remove_entities = set(r.lower() for r in (llm_result.get("entities_remove") or []))
            if remove_entities:
                before = len(entities)
                entities = [
                    e for e in entities
                    if (e if isinstance(e, str) else e.get("text", "")).lower() not in remove_entities
                ]
                print(f"[QUALITY_GATE] Haiku removed {before - len(entities)} entities")

            # Remove triples by index
            remove_indices = set(llm_result.get("triples_remove_indices") or [])
            if remove_indices:
                before = len(triples)
                triples = [t for i, t in enumerate(triples) if i not in remove_indices]
                print(f"[QUALITY_GATE] Haiku removed {before - len(triples)} triples")

    stats.update({
        "ngrams_after": len(ngrams),
        "extended_after": len(extended_terms),
        "entities_after": len(entities),
        "triples_after": len(triples),
    })

    return {
        "ngrams": ngrams,
        "extended_terms": extended_terms,
        "entities": entities,
        "triples": triples,
        "stats": stats,
    }
