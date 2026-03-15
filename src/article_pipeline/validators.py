"""
Article validation — checkpoints from BRAJEN_PROMPTS_v1.0.
Local validation (no LLM needed) for quick checks.
"""
import re
import json

# ── Validation lists (canonical definitions) ──
BANNED_OPENERS = [
    # Czasowe
    "w dzisiejszych czasach", "w obecnych czasach", "wspolczesnie",
    "w dzisiejszym swiecie", "w dynamicznie zmieniajacym sie swiecie",
    # Hedge
    "nie ulega watpliwosci", "nie da sie ukryc", "jak wiadomo",
    "kazdy z nas", "coraz wiecej osob",
    # Warto-frazy
    "warto wiedziec", "warto zauwazyc", "warto podkreslic",
    "warto pamietac", "warto dodac", "warto wspomniec",
    # Nalezy-frazy
    "nalezy podkreslic", "nalezy zauwazyc", "nalezy zaznaczyc",
    "nalezy pamietac", "nalezy miec na uwadze",
    # Waznosc
    "istotne jest", "kluczowe jest", "wazne jest, aby",
]

BANNED_ANYWHERE = [
    # Connectory / podsumowania
    "co wiecej", "podsumowujac", "reasumujac", "w podsumowaniu",
    "to prowadzi nas do wniosku", "w skrocie", "ogolnie rzecz biorac",
    "mam nadzieje, ze", "oczywiscie", "to jeszcze", "to juz",
    # Kalki / anglicyzmy
    "posiadac", "zaadresowac", "zaimplementowac", "targetowac",
    # Hiperbole AI
    "niesamowity", "niezwykly", "wyjatkowy", "rewolucyjny",
    "przelomowy", "game changer", "holistyczny", "kompleksowy",
    # Pseudo-prawnicze
    "na podstawie dostepnych danych", "w swietle obowiazujacych przepisow",
    "zgodnie z litera prawa", "ustawodawca przewidzial",
]

BANNED_CHARS = [
    "\u2014",  # em dash — zakazany, uzywaj krotkiego myslnika lub przecinka
]

FORBIDDEN_PHRASES = [
    "warto zaznaczyc", "warto podkreslic", "nalezy zaznaczyc",
    "nalezy podkreslic", "jest to wazne", "w dzisiejszym artykule",
    "kluczowym aspektem", "podsumowujac powyzsze", "jak wspomniano wczesniej",
    "co wiecej,", "ponadto,", "niemniej jednak,", "w zwiazku z powyzszym,",
    "majac na uwadze", "nie sposob nie wspomniec", "wiele osob blednie",
]


def check_forbidden_phrases(text: str) -> list[str]:
    """Check text for forbidden AI phrases (core list). Returns list of found phrases."""
    found = []
    text_lower = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in text_lower:
            found.append(phrase)
    return found


def check_banned_openers(text: str) -> list[str]:
    """Check for banned sentence/paragraph openers (secondary check)."""
    found = []
    # Split into sentences and check first words
    sentences = re.split(r'(?<=[.!?])\s+', text)
    for sent in sentences:
        sent_lower = sent.strip().lower()
        for opener in BANNED_OPENERS:
            if sent_lower.startswith(opener.lower()):
                found.append(opener)
                break
    return list(set(found))


def check_banned_anywhere(text: str) -> list[str]:
    """Check for phrases banned anywhere in the text (secondary check)."""
    found = []
    text_lower = text.lower()
    for phrase in BANNED_ANYWHERE:
        if phrase.lower() in text_lower:
            found.append(phrase)
    return found


def check_banned_chars(text: str) -> list[dict]:
    """Check for banned characters like em-dash (secondary check)."""
    found = []
    for char in BANNED_CHARS:
        count = text.count(char)
        if count > 0:
            found.append({"char": repr(char), "name": "em dash (—)" if char == "\u2014" else repr(char), "count": count})
    return found


def check_entity_coverage(text: str, entities: list[str]) -> dict:
    """Check if all critical entities appear at least once."""
    text_lower = text.lower()
    missing = []
    present = []
    for entity in entities:
        if entity.lower() in text_lower:
            present.append(entity)
        else:
            missing.append(entity)
    return {"present": present, "missing": missing}


def check_hard_facts(text: str, hard_facts: list) -> dict:
    """Check if hard facts from SERP are used exactly. Supports both str and dict items."""
    used = []
    missing = []
    for fact in hard_facts:
        val = fact.get("value", "") if isinstance(fact, dict) else str(fact)
        if val and val in text:
            used.append(val)
        elif val:
            missing.append(val)
    return {"used": used, "missing": missing}


def check_paragraph_uniformity(text: str) -> list[dict]:
    """Check if 4+ consecutive paragraphs have identical sentence count."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    issues = []
    sentence_counts = []
    for p in paragraphs:
        sentences = re.split(r"[.!?]+\s+", p)
        sentences = [s for s in sentences if s.strip()]
        sentence_counts.append(len(sentences))

    for i in range(len(sentence_counts) - 3):
        window = sentence_counts[i : i + 4]
        if len(set(window)) == 1:
            issues.append({
                "type": "AKAPIT_UNIFORMITY",
                "location": f"akapity {i+1}-{i+4}",
                "detail": f"Wszystkie {window[0]} zdań",
            })
    return issues


def check_list_overuse(text: str) -> int:
    """Count bullet/numbered lists in main text (excluding FAQ)."""
    faq_start = text.lower().find("faq")
    if faq_start == -1:
        faq_start = text.lower().find("najczęściej zadawane")
    main_text = text[:faq_start] if faq_start > 0 else text

    list_pattern = re.findall(r"(?:^|\n)\s*[-•*]\s+", main_text)
    numbered_pattern = re.findall(r"(?:^|\n)\s*\d+[.)]\s+", main_text)

    # Count groups of consecutive list items as one list
    list_count = 0
    in_list = False
    for line in main_text.split("\n"):
        is_list_item = bool(re.match(r"\s*[-•*]\s+|\s*\d+[.)]\s+", line))
        if is_list_item and not in_list:
            list_count += 1
            in_list = True
        elif not is_list_item:
            in_list = False

    return list_count


# ================================================================
# C1. Foreign characters (Cyrillic, CJK, Arabic)
# ================================================================

def check_foreign_characters(text: str) -> list[dict]:
    """Detect non-Polish/non-Latin characters (Cyrillic, CJK, Arabic, etc.)."""
    issues = []

    # Cyrylica
    cyrillic = re.findall(r'[а-яА-ЯёЁ]+', text)
    if cyrillic:
        for match in cyrillic[:5]:
            issues.append({
                "type": "FOREIGN_CHARSET",
                "severity": "critical",
                "text": match,
                "script": "cyrillic",
                "detail": f"Rosyjski/cyrylica w polskim tekście: '{match}'",
            })

    # CJK (chiński/japoński/koreański)
    cjk = re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]+', text)
    if cjk:
        for match in cjk[:3]:
            issues.append({
                "type": "FOREIGN_CHARSET",
                "severity": "critical",
                "text": match,
                "script": "cjk",
                "detail": f"Znaki CJK w polskim tekście: '{match}'",
            })

    # Arabski
    arabic = re.findall(r'[\u0600-\u06ff]+', text)
    if arabic:
        for match in arabic[:3]:
            issues.append({
                "type": "FOREIGN_CHARSET",
                "severity": "critical",
                "text": match,
                "script": "arabic",
                "detail": f"Znaki arabskie w polskim tekście: '{match}'",
            })

    return issues


# ================================================================
# C2. Brand names detection
# ================================================================

def check_brand_names(text: str, allowed_brands: list[str] = None) -> list[dict]:
    """Detect potential brand/company names not in allowed list."""
    allowed = set(b.lower() for b in (allowed_brands or []))
    issues = []

    # Szukaj nazw własnych w FAQ (najczęstsze miejsce)
    faq_section = ""
    for marker in ["najczęściej zadawane", "## FAQ", "## Najczęściej"]:
        idx = text.lower().find(marker.lower())
        if idx >= 0:
            faq_section = text[idx:]
            break

    faq_headings = re.findall(r'^##\s+(.+)$', faq_section, re.MULTILINE)
    for heading in faq_headings:
        words = heading.split()
        for i, word in enumerate(words):
            if i == 0 or not word or not word[0].isalpha():
                continue
            # Słowo z wielkiej litery w środku pytania, nie jest akronimem ≤4 znaków
            if word[0].isupper() and len(word) > 4 and word.upper() != word:
                candidate = word
                if i + 1 < len(words) and words[i + 1][0:1].isupper():
                    candidate = f"{word} {words[i + 1]}"
                if candidate.lower() not in allowed:
                    issues.append({
                        "type": "BRAND_NAME",
                        "severity": "critical",
                        "text": candidate,
                        "location": f"FAQ: {heading[:60]}",
                        "detail": f"Nazwa firmy '{candidate}' nie jest w dozwolonych — usuń z artykułu.",
                    })

    return issues


# ================================================================
# C3. Meta-comments detection
# ================================================================

_META_COMMENT_PATTERNS = [
    re.compile(r"bez podania źródła", re.IGNORECASE),
    re.compile(r"brak danych (?:na temat|dotyczących|referencyjnych)", re.IGNORECASE),
    re.compile(r"nie (?:znaleziono|udało się|podano) (?:informacji|danych|źródła)", re.IGNORECASE),
    re.compile(r"(?:dane|informacje) referencyjne", re.IGNORECASE),
    re.compile(r"(?:wymaga|potrzebuje) weryfikacji", re.IGNORECASE),
    re.compile(r"(?:tu|tutaj) (?:wstaw|dodaj|uzupełnij)", re.IGNORECASE),
    re.compile(r"(?:TODO|FIXME|XXX|UWAGA DLA AUTORA)", re.IGNORECASE),
    re.compile(r"\[(?:źródło|citation|ref)\s*(?:needed|potrzebne)?\]", re.IGNORECASE),
    re.compile(r"(?:patrz|zob\.|por\.|cf\.)\s+(?:sekcja|rozdział|punkt)", re.IGNORECASE),
]


def check_meta_comments(text: str) -> list[dict]:
    """Detect editorial meta-comments that LLM left in article text."""
    issues = []
    for pattern in _META_COMMENT_PATTERNS:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            context = text[start:end].replace("\n", " ")
            issues.append({
                "type": "META_COMMENT",
                "severity": "high",
                "text": match.group(),
                "context": f"...{context}...",
                "detail": "LLM wstawił komentarz redakcyjny do treści artykułu.",
            })
    return issues


# ================================================================
# C4. Keyword stuffing detection
# ================================================================

def check_keyword_stuffing(text: str, main_keyword: str = "",
                            max_per_section: int = 2) -> list[dict]:
    """Check if keyword appears more than max_per_section times in any H2 section."""
    if not main_keyword:
        return []

    issues = []
    kw_lower = main_keyword.lower()

    # Podziel na sekcje (po ## nagłówkach)
    sections = re.split(r'^##\s+', text, flags=re.MULTILINE)

    for i, section in enumerate(sections):
        if not section.strip():
            continue
        section_lower = section.lower()
        count = section_lower.count(kw_lower)
        if count > max_per_section:
            first_line = section.split('\n')[0].strip()[:60]
            issues.append({
                "type": "KEYWORD_STUFFING",
                "severity": "medium",
                "keyword": main_keyword,
                "count": count,
                "max": max_per_section,
                "section": first_line,
                "detail": f"'{main_keyword}' × {count} w sekcji (max {max_per_section})",
            })

    # Sprawdź powtarzające się trigramy 3+ słowowe
    from collections import Counter
    words = text.lower().split()
    if len(words) > 5:
        trigrams = [' '.join(words[i:i+3]) for i in range(len(words) - 2)]
        trigram_counts = Counter(trigrams)
        _STOP = {'i', 'w', 'na', 'z', 'do', 'się', 'nie', 'to', 'jest', 'za',
                 'po', 'od', 'jak', 'ale', 'co', 'ten', 'czy', 'dla', 'lub', 'tak'}
        for trigram, cnt in trigram_counts.most_common(10):
            if cnt >= 4 and len(trigram) > 10:
                stop_heavy = all(w in _STOP for w in trigram.split())
                if not stop_heavy:
                    issues.append({
                        "type": "PHRASE_REPETITION",
                        "severity": "low",
                        "phrase": trigram,
                        "count": cnt,
                        "detail": f"Fraza '{trigram}' powtórzona {cnt}x",
                    })

    return issues


def check_bold_in_prose(text: str) -> list[str]:
    """Check for bold text inside narrative paragraphs."""
    issues = []
    paragraphs = text.split("\n\n")
    for i, p in enumerate(paragraphs):
        if p.strip().startswith("#") or p.strip().startswith("<h"):
            continue
        bolds = re.findall(r"\*\*[^*]+\*\*|<strong>[^<]+</strong>|<b>[^<]+</b>", p)
        if bolds:
            for b in bolds:
                issues.append(f"akapit {i+1}: {b[:50]}")
    return issues


def validate_batch(text: str, batch_num: int, batch_data: dict, variables: dict) -> dict:
    """
    Validate a single batch against checkpoints.
    """
    errors = []
    warnings = []
    passed = []

    # Forbidden phrases
    forbidden = check_forbidden_phrases(text)
    if forbidden:
        errors.append({
            "type": "AI_PHRASES",
            "severity": "HIGH",
            "fragments": forbidden,
        })
    else:
        passed.append("AI_PHRASES")

    # Entity coverage
    encje = batch_data.get("encje_obowiazkowe", [])
    if encje:
        coverage = check_entity_coverage(text, encje)
        if coverage["missing"]:
            errors.append({
                "type": "ENTITY_MISSING",
                "severity": "MEDIUM",
                "missing": coverage["missing"],
            })
        else:
            passed.append("ENTITY_COVERAGE")

    # Main entity in every section
    main_entity = variables.get("ENCJA_GLOWNA", "")
    if main_entity and main_entity.lower() not in text.lower():
        warnings.append({
            "type": "MAIN_ENTITY_MISSING",
            "detail": f"'{main_entity}' nie znaleziony w batchu {batch_num}",
        })

    # Length info (no enforcement)
    word_count = len(text.split())
    print(f"[VALIDATOR] Batch {batch_num}: {word_count} words")

    return {"errors": errors, "warnings": warnings, "passed": passed}


def validate_global(full_text: str, variables: dict) -> dict:
    """
    Validate the complete assembled article.
    Returns validation result with score.
    """
    errors = []
    warnings = []
    passed = []
    score = 100

    # 1. Forbidden phrases
    forbidden = check_forbidden_phrases(full_text)
    if forbidden:
        errors.append({"type": "AI_PHRASES", "severity": "HIGH", "fragments": forbidden})
        score -= len(forbidden) * 5
    else:
        passed.append("AI_PHRASES")

    # 2. Entity coverage
    try:
        encje = json.loads(variables.get("ENCJE_KRYTYCZNE", "[]"))
    except (json.JSONDecodeError, TypeError):
        encje = []
    if encje:
        coverage = check_entity_coverage(full_text, encje)
        if coverage["missing"]:
            errors.append({"type": "ENTITY_COVERAGE", "severity": "MEDIUM", "missing": coverage["missing"]})
            score -= len(coverage["missing"]) * 3
        else:
            passed.append("ENTITY_COVERAGE")

    # 3. Hard facts
    hard_facts = variables.get("_hard_facts", [])
    if hard_facts:
        facts_check = check_hard_facts(full_text, hard_facts)
        if facts_check["missing"]:
            warnings.append({"type": "HARD_FACTS_MISSING", "missing": facts_check["missing"]})
            score -= len(facts_check["missing"]) * 2
        else:
            passed.append("HARD_FACTS")

    # 4. Paragraph uniformity
    uniformity = check_paragraph_uniformity(full_text)
    if uniformity:
        warnings.append({"type": "AKAPIT_UNIFORMITY", "issues": uniformity})
        score -= len(uniformity) * 2
    else:
        passed.append("AKAPIT_UNIFORMITY")

    # 5. List overuse
    list_count = check_list_overuse(full_text)
    if list_count > 3:
        warnings.append({"type": "LIST_OVERUSE", "count": list_count})
        score -= (list_count - 3) * 3
    else:
        passed.append("LIST_OVERUSE")

    # 6. Bold in prose
    bold_issues = check_bold_in_prose(full_text)
    if bold_issues:
        warnings.append({"type": "BOLD_IN_PROSE", "locations": bold_issues})
        score -= len(bold_issues) * 2
    else:
        passed.append("BOLD_IN_PROSE")

    # 7. Total length (info only, no penalty)
    word_count = len(full_text.split())
    target = variables.get("_target_length", 0)
    print(f"[VALIDATOR] Global: {word_count} words (reference target: {target})")
    passed.append("LENGTH_TARGET")

    # 8. Main entity in all sections
    main_entity = variables.get("ENCJA_GLOWNA", "")
    if main_entity:
        sections = re.split(r"<h2|##\s", full_text)
        missing_sections = sum(1 for s in sections[1:] if main_entity.lower() not in s.lower())
        if missing_sections:
            warnings.append({
                "type": "MAIN_ENTITY_SECTIONS",
                "missing_in": f"{missing_sections} sekcji",
            })
            score -= missing_sections * 3

    # 9. Banned openers (secondary — lower penalty)
    openers = check_banned_openers(full_text)
    if openers:
        warnings.append({"type": "BANNED_OPENERS", "fragments": openers})
        score -= len(openers) * 2
    else:
        passed.append("BANNED_OPENERS")

    # 10. Banned anywhere phrases (secondary — lower penalty)
    banned = check_banned_anywhere(full_text)
    if banned:
        warnings.append({"type": "BANNED_ANYWHERE", "fragments": banned})
        score -= len(banned) * 2
    else:
        passed.append("BANNED_ANYWHERE")

    # 11. Banned characters (em-dash etc.)
    bad_chars = check_banned_chars(full_text)
    if bad_chars:
        warnings.append({"type": "BANNED_CHARS", "chars": bad_chars})
        score -= sum(c["count"] for c in bad_chars)
    else:
        passed.append("BANNED_CHARS")

    score = max(0, min(100, score))

    return {
        "errors": errors,
        "warnings": warnings,
        "passed": passed,
        "score": score,
        "word_count": word_count,
    }
