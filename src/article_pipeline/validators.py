"""
Article validation — checkpoints from BRAJEN_PROMPTS_v1.0.
Local validation (no LLM needed) for quick checks.
"""
import re
import json
from src.article_pipeline.prompts import (
    FORBIDDEN_PHRASES,
    BANNED_OPENERS,
    BANNED_ANYWHERE,
    BANNED_CHARS,
)


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

    # Length check
    word_count = len(text.split())
    target = int(batch_data.get("target_length", 0)) if batch_data.get("target_length") else 0
    if target and abs(word_count - target) > target * 0.15:
        warnings.append({
            "type": "LENGTH_MISMATCH",
            "detail": f"{word_count} słów vs cel {target} (±15%)",
        })

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

    # 7. Total length
    word_count = len(full_text.split())
    target = variables.get("_target_length", 0)
    if target:
        deviation = abs(word_count - target) / target
        if deviation > 0.1:
            warnings.append({
                "type": "LENGTH_DEVIATION",
                "actual": word_count,
                "target": target,
                "deviation": f"{deviation:.0%}",
            })
            score -= int(deviation * 20)
        else:
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
