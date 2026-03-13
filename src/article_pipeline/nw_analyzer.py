"""
NW/Surfer coverage analyzer — compares NW terms against S1 n-grams
to identify gaps for the article pipeline.
"""


def analyze_nw_coverage(nw_terms: list, s1_data: dict) -> dict:
    """
    Compare NW/Surfer terms against S1 n-grams to find coverage gaps.

    Args:
        nw_terms: List of NW/Surfer keyword strings from the panel UI.
        s1_data: Full S1 analysis data dict.

    Returns:
        Dict with 'prompt_block' (str for template) and 'stats'.
    """
    if not nw_terms:
        return {"prompt_block": "", "stats": {"total": 0, "covered": 0, "missing": 0}}

    # Collect all known terms from S1
    ngrams = s1_data.get("ngrams") or []
    extended = s1_data.get("extended_terms") or []

    known_lower = set()
    for ng in ngrams + extended:
        text = ng.get("ngram", "") if isinstance(ng, dict) else str(ng)
        if text:
            known_lower.add(text.strip().lower())

    # Also check main keyword and semantic keyphrases
    main_kw = (s1_data.get("main_keyword") or "").lower()
    if main_kw:
        known_lower.add(main_kw)
    for kp in s1_data.get("semantic_keyphrases") or []:
        text = kp if isinstance(kp, str) else kp.get("text", "") if isinstance(kp, dict) else ""
        if text:
            known_lower.add(text.strip().lower())

    # Classify NW terms
    covered = []
    missing = []
    for term in nw_terms:
        term = term.strip()
        if not term:
            continue
        if term.lower() in known_lower:
            covered.append(term)
        else:
            missing.append(term)

    stats = {
        "total": len(covered) + len(missing),
        "covered": len(covered),
        "missing": len(missing),
    }

    # Build prompt block for missing terms
    prompt_block = ""
    if missing:
        lines = [
            "DODATKOWE FRAZY NW/Surfer (wpleć naturalnie w treść — każda min. 1×):"
        ]
        for term in missing:
            lines.append(f"  • {term}")
        prompt_block = "\n".join(lines)

    return {"prompt_block": prompt_block, "stats": stats}
