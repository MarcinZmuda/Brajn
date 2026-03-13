"""
===============================================================================
ENTITY SEO COMPLIANCE v1.0 — Post-article analysis engine
===============================================================================
Bierze gotowy artykul (markdown) + dane S1 i liczy WSZYSTKIE metryki
entity SEO compliance. Zero API calls — czysto lokalne (Python + spaCy).
Uruchamiany po wygenerowaniu artykulu, obok istniejacego coverage_check.

Metryki:
1. Entity Salience (pozycja, subject_ratio, H1/H2, early_mentions)
2. Co-occurrence Pairs (pary encji w tym samym akapicie)
3. SPO / Factographic Triples (pokrycie trojek w tekscie)
4. Mention Variety (Named / Nominal / Pronominal)
5. Causal Chains (pokrycie lancuchow + obecnosc mechanizmu)
6. Centerpiece Block (pierwsze 100 slow)
7. Naming Consistency (spojnosc form encji)
8. N-gram Budget (reuse coverage_check)
9. Hard Facts (obecnosc twardych danych)
10. Overall Score (wazona srednia)
===============================================================================
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter


# ================================================================
# HELPERS
# ================================================================

def _split_article(article: str) -> Dict[str, Any]:
    """Parse markdown article into structured parts."""
    lines = article.strip().split("\n")
    h1 = ""
    h2_sections = []  # [{heading, text, index}]
    intro_text = ""
    current_h2 = None
    current_text = []
    intro_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            h1 = stripped[2:].strip()
        elif stripped.startswith("## "):
            # Save previous section
            if current_h2:
                h2_sections.append({"heading": current_h2, "text": "\n".join(current_text).strip()})
            elif intro_lines:
                intro_text = "\n".join(intro_lines).strip()
            current_h2 = stripped[3:].strip()
            current_text = []
        else:
            if current_h2:
                current_text.append(line)
            elif h1 and not current_h2:
                intro_lines.append(line)

    # Save last section
    if current_h2:
        h2_sections.append({"heading": current_h2, "text": "\n".join(current_text).strip()})
    elif intro_lines and not intro_text:
        intro_text = "\n".join(intro_lines).strip()

    # Paragraphs (split by double newline)
    full_text = article.replace("# " + h1, "").strip() if h1 else article.strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", full_text) if p.strip() and not p.strip().startswith("## ")]

    return {
        "h1": h1,
        "intro": intro_text,
        "h2_sections": h2_sections,
        "h2_headings": [s["heading"] for s in h2_sections],
        "paragraphs": paragraphs,
        "full_text": article,
        "word_count": len(article.split()),
    }


def _find_all_occurrences(text: str, phrase: str) -> List[int]:
    """Find all start positions of phrase in text (case-insensitive)."""
    positions = []
    text_lower = text.lower()
    phrase_lower = phrase.lower()
    start = 0
    while True:
        idx = text_lower.find(phrase_lower, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


def _count_occurrences(text: str, phrase: str) -> int:
    """Count occurrences of phrase in text (case-insensitive)."""
    return len(_find_all_occurrences(text, phrase))


def _fuzzy_find(text: str, phrase: str, min_prefix: int = 4) -> bool:
    """Check if phrase appears in text, allowing Polish inflection (stem matching)."""
    text_lower = text.lower()
    if phrase.lower() in text_lower:
        return True
    # Try stem: first N chars of each word
    words = phrase.lower().split()
    for word in words:
        if len(word) < min_prefix:
            continue
        stem = word[:max(min_prefix, int(len(word) * 0.7))]
        if stem in text_lower:
            return True
    return False


def _stem_word(word: str, min_len: int = 4) -> str:
    """Get stem of a Polish word (first 75% of chars, min 4)."""
    w = word.lower().strip()
    if len(w) < min_len:
        return w
    return w[:max(min_len, int(len(w) * 0.75))]


def _fuzzy_count_in_sentences(text: str, phrase: str) -> int:
    """Count how many sentences contain a fuzzy match of the phrase.

    For multi-word phrases: a sentence matches if ≥50% of content words
    (length > 3) from the phrase are stem-found in that sentence.
    For single-word phrases: stem match in sentence.
    """
    sentences = re.split(r'[.!?]+\s*', text)
    phrase_words = [w for w in phrase.lower().split() if len(w) > 2]
    if not phrase_words:
        return 0

    count = 0
    for sent in sentences:
        sent_lower = sent.lower()
        if not sent_lower.strip():
            continue

        if phrase.lower() in sent_lower:
            count += 1
            continue

        # Stem matching: check how many words from the phrase appear
        found_words = 0
        for pw in phrase_words:
            stem = _stem_word(pw)
            if stem in sent_lower:
                found_words += 1

        threshold = max(1, len(phrase_words) * 0.5)
        if found_words >= threshold:
            count += 1

    return count


def _fuzzy_find_in_paragraph(paragraph: str, phrase: str) -> bool:
    """Check if phrase (or its stem variant) appears in a paragraph.

    More lenient than _fuzzy_find: checks if ≥50% of content words
    from the phrase are stem-matched in the paragraph.
    """
    para_lower = paragraph.lower()
    if phrase.lower() in para_lower:
        return True

    phrase_words = [w for w in phrase.lower().split() if len(w) > 2]
    if not phrase_words:
        return False

    found = 0
    for pw in phrase_words:
        stem = _stem_word(pw)
        if stem in para_lower:
            found += 1

    return found >= max(1, len(phrase_words) * 0.5)


# ================================================================
# 1. ENTITY SALIENCE ANALYSIS
# ================================================================

def analyze_entity_salience(
    parsed: Dict,
    s1_data: Dict,
    nlp=None,
) -> Dict[str, Any]:
    """
    Analyze entity salience signals in the article.

    Checks:
    - Main entity position (first occurrence)
    - Main entity in H1 and H2s
    - Subject ratio (spaCy dep parse)
    - Early mentions (entities in intro)
    - Entity distribution across sections
    """
    entity_seo = s1_data.get("entity_seo") or {}
    salience_list = entity_seo.get("entity_salience") or []
    main_keyword = s1_data.get("main_keyword") or ""
    full_text = parsed["full_text"]
    full_lower = full_text.lower()

    # Determine main entity
    main_entity_raw = ""
    main_salience = 0.0
    if salience_list:
        top = salience_list[0] if isinstance(salience_list[0], dict) else {}
        main_entity_raw = top.get("entity") or top.get("entity_text") or ""
        main_salience = float(top.get("salience") or top.get("salience_score") or 0)

    main_entity = main_entity_raw
    if main_entity and _count_occurrences(full_text, main_entity) == 0:
        main_entity = main_keyword  # fallback

    # --- Position ---
    first_pos = full_lower.find(main_entity.lower()) if main_entity else -1
    first_pos_pct = round(first_pos / max(len(full_text), 1), 3) if first_pos >= 0 else 1.0
    first_pos_word = len(full_text[:first_pos].split()) if first_pos >= 0 else -1
    in_first_200_words = first_pos_word <= 200 if first_pos_word >= 0 else False

    # --- H1 presence ---
    h1 = parsed["h1"]
    in_h1 = _fuzzy_find(h1, main_entity) if main_entity else False

    # --- H2 presence ---
    h2_with_entity = []
    for h2 in parsed["h2_headings"]:
        if _fuzzy_find(h2, main_entity) or _fuzzy_find(h2, main_keyword):
            h2_with_entity.append(h2)
    in_h2_count = len(h2_with_entity)

    # --- Subject ratio (spaCy) ---
    subject_ratio = 0.0
    as_subject = 0
    as_object = 0
    subject_examples = []
    object_examples = []

    if nlp and main_entity:
        sentences = re.split(r'[.!?]+\s+', full_text)
        entity_sentences = [s for s in sentences if main_entity.lower() in s.lower() or main_keyword.lower() in s.lower()]
        for sent in entity_sentences[:50]:
            try:
                doc = nlp(sent[:500])
                for ent in doc.ents:
                    ent_lower = ent.text.lower()
                    if main_entity.lower() in ent_lower or main_keyword.lower() in ent_lower:
                        root = ent.root
                        if root.dep_ in ("nsubj", "nsubj:pass"):
                            as_subject += 1
                            if len(subject_examples) < 3:
                                subject_examples.append(sent[:100])
                        elif root.dep_ in ("obj", "iobj", "obl", "obl:arg"):
                            as_object += 1
                            if len(object_examples) < 3:
                                object_examples.append(sent[:100])
            except Exception:
                continue
        total_roles = as_subject + as_object
        subject_ratio = round(as_subject / total_roles, 2) if total_roles > 0 else 0.0

    # --- Expected subject ratio from S1 ---
    expected_subject_ratio = 0.0
    if salience_list:
        top = salience_list[0] if isinstance(salience_list[0], dict) else {}
        signals = top.get("signals") or {}
        expected_subject_ratio = float(signals.get("subject_ratio") or 0)

    # --- Early mentions ---
    placement = entity_seo.get("entity_placement") or entity_seo.get("placement_instructions") or {}
    first_para_expected = placement.get("first_paragraph_entities") or []
    intro = parsed["intro"]
    first_para_found = [e for e in first_para_expected if _fuzzy_find(intro, e)]
    first_para_missing = [e for e in first_para_expected if e not in first_para_found]

    # --- Status ---
    position_status = "pass" if in_first_200_words else ("warn" if first_pos_pct < 0.3 else "fail")
    h1_status = "pass" if in_h1 else "fail"
    h2_status = "pass" if in_h2_count >= 2 else ("warn" if in_h2_count >= 1 else "fail")
    sr_status = "pass" if subject_ratio >= expected_subject_ratio * 0.8 else ("warn" if subject_ratio > 0 else "fail")
    early_status = "pass" if len(first_para_missing) == 0 else ("warn" if len(first_para_found) >= len(first_para_expected) * 0.5 else "fail")

    return {
        "main_entity": main_entity,
        "main_entity_raw": main_entity_raw,
        "main_salience": main_salience,
        "position": {
            "first_char": first_pos,
            "first_word": first_pos_word,
            "first_pct": first_pos_pct,
            "in_first_200_words": in_first_200_words,
            "status": position_status,
        },
        "h1": {
            "text": h1,
            "contains_entity": in_h1,
            "status": h1_status,
        },
        "h2": {
            "count_with_entity": in_h2_count,
            "headings_with_entity": h2_with_entity,
            "total_h2": len(parsed["h2_headings"]),
            "status": h2_status,
        },
        "subject_ratio": {
            "actual": subject_ratio,
            "expected": expected_subject_ratio,
            "as_subject": as_subject,
            "as_object": as_object,
            "subject_examples": subject_examples,
            "object_examples": object_examples,
            "status": sr_status,
        },
        "early_mentions": {
            "expected": first_para_expected,
            "found": first_para_found,
            "missing": first_para_missing,
            "status": early_status,
        },
    }


# ================================================================
# 2. CO-OCCURRENCE PAIRS
# ================================================================

def analyze_cooccurrence(
    parsed: Dict,
    s1_data: Dict,
) -> Dict[str, Any]:
    """Check if co-occurrence pairs from S1 appear in the same paragraph."""
    entity_seo = s1_data.get("entity_seo") or {}
    cooc_raw = (
        entity_seo.get("entity_cooccurrence") or
        entity_seo.get("cooccurrence_pairs") or
        []
    )
    placement = entity_seo.get("entity_placement") or {}
    placement_pairs = placement.get("cooccurrence_pairs") or []
    if placement_pairs and not cooc_raw:
        cooc_raw = placement_pairs

    paragraphs = parsed["paragraphs"]
    results = []

    for pair in cooc_raw:
        if isinstance(pair, dict):
            a = pair.get("entity_a") or ""
            b = pair.get("entity_b") or ""
            strength = float(pair.get("strength") or 0)
            comp_sentences = int(pair.get("sentence_co_occurrences") or pair.get("sentence_count") or 0)
        else:
            continue

        if not a or not b:
            continue

        same_paragraph_count = 0
        found_together = False
        for para in paragraphs:
            para_lower = para.lower()
            a_in = a.lower() in para_lower or _fuzzy_find(para, a)
            b_in = b.lower() in para_lower or _fuzzy_find(para, b)
            if a_in and b_in:
                same_paragraph_count += 1
                found_together = True

        status = "pass" if found_together else "fail"
        results.append({
            "entity_a": a,
            "entity_b": b,
            "found_together": found_together,
            "same_paragraph_count": same_paragraph_count,
            "competitor_sentences": comp_sentences,
            "strength": strength,
            "status": status,
        })

    pass_count = sum(1 for r in results if r["status"] == "pass")
    total = len(results)

    return {
        "pairs": results,
        "stats": {
            "total": total,
            "pass": pass_count,
            "fail": total - pass_count,
        },
        "overall_status": "pass" if pass_count == total else ("warn" if pass_count >= total * 0.5 else "fail"),
    }


# ================================================================
# 3. SPO / FACTOGRAPHIC TRIPLES
# ================================================================

def analyze_spo_triples(
    parsed: Dict,
    s1_data: Dict,
) -> Dict[str, Any]:
    """Check coverage of SPO and factographic triples in article text."""
    entity_seo = s1_data.get("entity_seo") or {}
    full_lower = parsed["full_text"].lower()

    triples = []

    # Source 1: Factographic triples
    for t in (s1_data.get("factographic_triples") or
              entity_seo.get("factographic_triples") or []):
        if isinstance(t, dict):
            triples.append({
                "subject": t.get("subject") or "",
                "predicate": t.get("predicate") or t.get("verb") or "",
                "object": t.get("object") or "",
                "type": t.get("triplet_type") or "spo",
                "source": "factographic",
                "confidence": float(t.get("confidence") or 0.8),
            })

    # Source 2: Entity relationships
    for r in (entity_seo.get("entity_relationships") or
              entity_seo.get("relationships") or []):
        if isinstance(r, dict):
            subj = r.get("subject") or ""
            obj = r.get("object") or ""
            if len(subj) < 3 or len(obj) < 3 or len(subj) > 60 or len(obj) > 60:
                continue
            triples.append({
                "subject": subj,
                "predicate": r.get("verb") or "",
                "object": obj,
                "type": "spo",
                "source": "entity_relationships",
                "confidence": 0.5,
            })

    paragraphs = parsed["paragraphs"]

    results = []
    for t in triples:
        subj = t["subject"]
        pred = t["predicate"]
        obj = t["object"]

        subj_found = _fuzzy_find(full_lower, subj)
        pred_found = _fuzzy_find(full_lower, pred) if pred else True
        obj_found = _fuzzy_find(full_lower, obj)

        full_found = subj_found and pred_found and obj_found

        # Paragraph-level SPO matching (more lenient than sentence-level)
        clear_spo = False
        if full_found:
            for para in paragraphs:
                para_lower = para.lower()
                s_in = _fuzzy_find_in_paragraph(para_lower, subj)
                o_in = _fuzzy_find_in_paragraph(para_lower, obj)
                p_in = _fuzzy_find_in_paragraph(para_lower, pred) if pred else True
                if s_in and o_in and p_in:
                    clear_spo = True
                    break
        elif subj_found and obj_found:
            # Fallback: subject and object found in article but not predicate —
            # check paragraph-level co-occurrence
            for para in paragraphs:
                s_in = _fuzzy_find_in_paragraph(para.lower(), subj)
                o_in = _fuzzy_find_in_paragraph(para.lower(), obj)
                if s_in and o_in:
                    full_found = True
                    clear_spo = True
                    break

        status = "pass" if clear_spo else ("warn" if full_found else "fail")
        results.append({
            **t,
            "found_in_article": full_found,
            "clear_spo": clear_spo,
            "status": status,
        })

    results.sort(key=lambda r: (r["source"] != "factographic", -r["confidence"]))

    covered = sum(1 for r in results if r["found_in_article"])
    clear = sum(1 for r in results if r["clear_spo"])

    return {
        "triples": results[:20],
        "stats": {
            "total": len(results),
            "covered": covered,
            "clear_spo": clear,
            "factographic_count": sum(1 for r in results if r["source"] == "factographic"),
        },
        "overall_status": "pass" if covered >= len(results) * 0.6 else "warn",
    }


# ================================================================
# 4. MENTION VARIETY (Named / Nominal / Pronominal)
# ================================================================

def analyze_mention_variety(
    parsed: Dict,
    s1_data: Dict,
) -> Dict[str, Any]:
    """Analyze variety of entity mentions: Named, Nominal, Pronominal."""
    full_text = parsed["full_text"]
    full_lower = full_text.lower()
    variables = s1_data.get("_variables") or s1_data.get("variables") or {}

    mention_forms = s1_data.get("mention_forms") or {}
    if not mention_forms and variables:
        import json
        try:
            mention_forms = json.loads(variables.get("MENTION_FORMS_JSON") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass

    named_forms = mention_forms.get("named") or []
    nominal_forms = mention_forms.get("nominal") or []
    pronominal_forms = mention_forms.get("pronominal") or []

    if isinstance(named_forms, str):
        named_forms = [f.strip() for f in named_forms.split(",") if f.strip()]
    if isinstance(nominal_forms, str):
        nominal_forms = [f.strip() for f in nominal_forms.split(",") if f.strip()]
    if isinstance(pronominal_forms, str):
        pronominal_forms = [f.strip() for f in pronominal_forms.split(",") if f.strip()]

    main_keyword = s1_data.get("main_keyword") or ""
    if main_keyword and main_keyword not in named_forms:
        named_forms.insert(0, main_keyword)

    # Use fuzzy stem-matching to count mentions (handles Polish inflection)
    named_count = sum(_fuzzy_count_in_sentences(full_text, f) for f in named_forms) if named_forms else 0
    nominal_count = sum(_fuzzy_count_in_sentences(full_text, f) for f in nominal_forms) if nominal_forms else 0
    pronominal_count = sum(_fuzzy_count_in_sentences(full_text, f) for f in pronominal_forms) if pronominal_forms else 0

    total = named_count + nominal_count + pronominal_count
    if total == 0:
        total = 1

    named_pct = round(named_count / total * 100, 1)
    nominal_pct = round(nominal_count / total * 100, 1)
    pronominal_pct = round(pronominal_count / total * 100, 1)

    has_data = bool(named_forms or nominal_forms or pronominal_forms)
    if not has_data:
        status = "no_data"
    elif named_pct > 75:
        status = "warn"
    elif nominal_pct < 10 and nominal_forms:
        status = "warn"
    elif pronominal_pct < 5 and pronominal_forms:
        status = "warn"
    else:
        status = "pass"

    named_examples = [f for f in named_forms if _fuzzy_find(full_lower, f)][:5]
    nominal_examples = [f for f in nominal_forms if _fuzzy_find(full_lower, f)][:5]
    pronominal_examples = [f for f in pronominal_forms if _fuzzy_find(full_lower, f)][:5]

    return {
        "has_data": has_data,
        "named": {"count": named_count, "pct": named_pct, "forms": named_forms[:8], "found": named_examples},
        "nominal": {"count": nominal_count, "pct": nominal_pct, "forms": nominal_forms[:8], "found": nominal_examples},
        "pronominal": {"count": pronominal_count, "pct": pronominal_pct, "forms": pronominal_forms[:8], "found": pronominal_examples},
        "total_mentions": total,
        "ideal_ratio": {"named": "40-50%", "nominal": "30-40%", "pronominal": "15-25%"},
        "status": status,
    }


# ================================================================
# 5. CAUSAL CHAINS
# ================================================================

def analyze_causal_chains(
    parsed: Dict,
    s1_data: Dict,
) -> Dict[str, Any]:
    """Check coverage of causal chains and relations in article."""
    full_text = parsed["full_text"]
    full_lower = full_text.lower()

    causal = s1_data.get("causal_triplets") or {}
    chains = causal.get("chains") or []
    singles = causal.get("singles") or []
    all_causal = chains + singles

    mechanism_words = [
        "dlatego", "ponieważ", "bo ", "w efekcie", "przez co", "w rezultacie",
        "gdyż", "dzięki temu", "co oznacza", "co powoduje", "skutkuje",
        "wynika z", "prowadzi do", "zmusza", "umożliwia", "zapobiega",
    ]

    results = []
    for t in all_causal:
        if not isinstance(t, dict):
            continue
        cause = t.get("cause") or ""
        effect = t.get("effect") or ""
        is_chain = t.get("is_chain") or False
        rel_type = t.get("relation_type") or ""

        if not cause or not effect:
            continue

        cause_found = _fuzzy_find(full_lower, cause)
        effect_found = _fuzzy_find(full_lower, effect)
        covered = cause_found and effect_found

        has_mechanism = False
        if covered:
            sentences = re.split(r'[.!?]+\s*', full_text)
            for sent in sentences:
                sent_lower = sent.lower()
                if _fuzzy_find(sent_lower, cause) or _fuzzy_find(sent_lower, effect):
                    for mw in mechanism_words:
                        if mw in sent_lower:
                            has_mechanism = True
                            break
                    if has_mechanism:
                        break

        status = "pass" if covered and has_mechanism else ("warn" if covered else "fail")
        chain_text = f"{cause} → {effect}"

        results.append({
            "chain": chain_text,
            "cause": cause,
            "effect": effect,
            "type": rel_type,
            "is_chain": is_chain,
            "covered": covered,
            "has_mechanism": has_mechanism,
            "status": status,
        })

    covered_count = sum(1 for r in results if r["covered"])
    mechanism_count = sum(1 for r in results if r["has_mechanism"])

    return {
        "chains": results,
        "stats": {
            "total": len(results),
            "covered": covered_count,
            "with_mechanism": mechanism_count,
        },
        "overall_status": "pass" if covered_count >= len(results) * 0.7 else "warn",
    }


# ================================================================
# 6. CENTERPIECE BLOCK
# ================================================================

def analyze_centerpiece(
    parsed: Dict,
    s1_data: Dict,
) -> Dict[str, Any]:
    """Analyze first 100 words of article (centerpiece block)."""
    intro = parsed["intro"]
    main_keyword = s1_data.get("main_keyword") or ""
    entity_seo = s1_data.get("entity_seo") or {}
    placement = entity_seo.get("entity_placement") or {}
    first_para_entities = placement.get("first_paragraph_entities") or []

    words = intro.split()
    first_100 = " ".join(words[:100])
    first_100_lower = first_100.lower()

    first_sentence = re.split(r'[.!?]', intro)[0] if intro else ""
    main_in_first = main_keyword.lower() in first_sentence.lower() if main_keyword else False

    supporting_found = [e for e in first_para_entities if _fuzzy_find(first_100_lower, e)]
    supporting_missing = [e for e in first_para_entities if e not in supporting_found]

    definition_indicators = ["to ", " jest ", " oznacza ", " polega ", " stanowi "]
    definition_present = any(ind in first_100_lower for ind in definition_indicators)

    preview_indicators = ["omówimy", "znajdziesz", "dowiesz się", "przewodniku", "artykule",
                         "przedstawimy", "wyjaśnimy", "przegląd"]
    topic_preview = any(ind in intro.lower() for ind in preview_indicators)

    checks = [main_in_first, definition_present, topic_preview]
    supporting_ok = len(supporting_found) >= max(1, len(first_para_entities) * 0.5)
    checks.append(supporting_ok)
    pass_count = sum(checks)
    status = "pass" if pass_count >= 3 else ("warn" if pass_count >= 2 else "fail")

    return {
        "first_100_words": first_100,
        "word_count": len(words[:100]),
        "main_entity_in_first_sentence": main_in_first,
        "definition_present": definition_present,
        "supporting_entities": {
            "expected": first_para_entities,
            "found": supporting_found,
            "missing": supporting_missing,
            "count_found": len(supporting_found),
            "count_expected": len(first_para_entities),
        },
        "topic_preview_present": topic_preview,
        "status": status,
    }


# ================================================================
# 7. NAMING CONSISTENCY
# ================================================================

def analyze_naming_consistency(
    parsed: Dict,
    s1_data: Dict,
) -> Dict[str, Any]:
    """Check naming consistency of main entity across the article."""
    full_text = parsed["full_text"]
    main_keyword = s1_data.get("main_keyword") or ""

    mention_forms = s1_data.get("mention_forms") or {}
    named = mention_forms.get("named") or ""
    if isinstance(named, str):
        known_forms = [f.strip() for f in named.split(",") if f.strip()]
    elif isinstance(named, list):
        known_forms = named
    else:
        known_forms = []

    if main_keyword and main_keyword not in known_forms:
        known_forms.insert(0, main_keyword)

    variant_counts = []
    for form in known_forms:
        count = _count_occurrences(full_text, form)
        if count > 0:
            variant_counts.append({"form": form, "count": count})

    if main_keyword:
        kw_stem = main_keyword.lower()[:max(6, int(len(main_keyword) * 0.6))]
        pattern = re.compile(r'\b' + re.escape(kw_stem) + r'\w*\b', re.IGNORECASE)
        all_matches = pattern.findall(full_text)
        variant_counter = Counter(all_matches)
        for form, count in variant_counter.most_common(10):
            if not any(v["form"].lower() == form.lower() for v in variant_counts):
                variant_counts.append({"form": form, "count": count})

    variant_counts.sort(key=lambda v: v["count"], reverse=True)

    unique_stems = set()
    for v in variant_counts:
        stem = v["form"].lower()[:5]
        unique_stems.add(stem)

    status = "pass" if len(unique_stems) <= 3 else ("warn" if len(unique_stems) <= 5 else "fail")

    return {
        "variants": variant_counts[:10],
        "unique_forms": len(variant_counts),
        "inconsistencies": [],
        "status": status,
    }


# ================================================================
# 8. HARD FACTS
# ================================================================

def analyze_hard_facts(
    parsed: Dict,
    s1_data: Dict,
) -> Dict[str, Any]:
    """Check if hard facts from SERP are present in article."""
    full_lower = parsed["full_text"].lower()
    variables = s1_data.get("_variables") or {}
    hard_facts_raw = s1_data.get("hard_facts") or variables.get("_hard_facts") or []

    results = []
    for hf in hard_facts_raw:
        if isinstance(hf, dict):
            value = hf.get("value") or ""
            category = hf.get("category") or ""
            snippet = hf.get("source_snippet") or ""
        elif isinstance(hf, str):
            value = hf
            category = ""
            snippet = ""
        else:
            continue

        if not value or len(value) < 2:
            continue

        found = value.lower() in full_lower
        results.append({
            "value": value,
            "category": category,
            "found": found,
            "status": "pass" if found else "fail",
        })

    found_count = sum(1 for r in results if r["found"])

    return {
        "facts": results,
        "stats": {
            "total": len(results),
            "found": found_count,
            "missing": len(results) - found_count,
        },
        "overall_status": "pass" if found_count >= len(results) * 0.7 else "warn",
    }


# ================================================================
# 9. OVERALL SCORE
# ================================================================

def compute_overall_score(compliance: Dict) -> Dict[str, Any]:
    """
    Compute weighted overall compliance score (0-100).

    Weights reflect impact on entity salience:
    - Entity salience signals: 25%
    - SPO triples: 15%
    - Causal chains: 15%
    - Co-occurrence: 10%
    - Mention variety: 10%
    - N-gram budget: 10%
    - Centerpiece: 10%
    - Hard facts: 5%
    """
    weights = {
        "entity_salience": 25,
        "spo_triples": 15,
        "causal_chains": 15,
        "cooccurrence": 10,
        "mention_variety": 10,
        "ngram_budget": 10,
        "centerpiece": 10,
        "hard_facts": 5,
    }

    scores = {}

    # Entity salience
    es = compliance.get("entity_salience") or {}
    es_checks = [
        es.get("position", {}).get("status") == "pass",
        es.get("h1", {}).get("status") == "pass",
        es.get("h2", {}).get("status") == "pass",
        es.get("subject_ratio", {}).get("status") in ("pass", "warn"),
        es.get("early_mentions", {}).get("status") in ("pass", "warn"),
    ]
    scores["entity_salience"] = sum(es_checks) / max(len(es_checks), 1) * 100

    # SPO triples
    spo = (compliance.get("spo_triples") or {}).get("stats") or {}
    spo_total = max(spo.get("total", 1), 1)
    scores["spo_triples"] = min(100, spo.get("covered", 0) / spo_total * 100)

    # Causal chains
    cc = (compliance.get("causal_chains") or {}).get("stats") or {}
    cc_total = max(cc.get("total", 1), 1)
    covered_pts = cc.get("covered", 0) / cc_total * 60
    mechanism_pts = cc.get("with_mechanism", 0) / cc_total * 40
    scores["causal_chains"] = min(100, covered_pts + mechanism_pts)

    # Co-occurrence
    cooc = (compliance.get("cooccurrence") or {}).get("stats") or {}
    cooc_total = max(cooc.get("total", 1), 1)
    scores["cooccurrence"] = cooc.get("pass", 0) / cooc_total * 100 if cooc_total > 0 else 50

    # Mention variety
    mv = compliance.get("mention_variety") or {}
    if mv.get("has_data"):
        named_pct = mv.get("named", {}).get("pct", 100)
        nominal_pct = mv.get("nominal", {}).get("pct", 0)
        named_score = 100 if 35 <= named_pct <= 55 else max(0, 100 - abs(named_pct - 45) * 2)
        nominal_score = 100 if nominal_pct >= 15 else nominal_pct / 15 * 100
        scores["mention_variety"] = (named_score + nominal_score) / 2
    else:
        scores["mention_variety"] = 50

    # N-gram budget
    nb = (compliance.get("ngram_budget") or {}).get("stats") or {}
    nb_total = max(nb.get("total", 1), 1)
    nb_ok = nb.get("ok", 0)
    nb_over = nb.get("over", 0)
    scores["ngram_budget"] = max(0, (nb_ok / nb_total * 100) - (nb_over * 10))

    # Centerpiece
    cp = compliance.get("centerpiece") or {}
    cp_checks = [
        cp.get("main_entity_in_first_sentence"),
        cp.get("definition_present"),
        cp.get("topic_preview_present"),
        (cp.get("supporting_entities") or {}).get("count_found", 0) >= 1,
    ]
    scores["centerpiece"] = sum(bool(c) for c in cp_checks) / max(len(cp_checks), 1) * 100

    # Hard facts
    hf = (compliance.get("hard_facts") or {}).get("stats") or {}
    hf_total = max(hf.get("total", 1), 1)
    scores["hard_facts"] = hf.get("found", 0) / hf_total * 100

    # Weighted average
    total_weight = sum(weights.values())
    weighted_sum = sum(scores.get(k, 50) * weights.get(k, 0) for k in weights)
    overall = round(weighted_sum / total_weight)

    return {
        "overall_score": max(0, min(100, overall)),
        "component_scores": {k: round(v) for k, v in scores.items()},
        "weights": weights,
    }


# ================================================================
# MAIN ENTRY POINT
# ================================================================

def run_entity_seo_compliance(
    article_text: str,
    s1_data: Dict,
    ngram_coverage: Dict = None,
    nlp=None,
) -> Dict[str, Any]:
    """
    Run full Entity SEO Compliance analysis.

    Args:
        article_text: Full article in markdown format
        s1_data: Full S1 analysis data
        ngram_coverage: Pre-computed ngram coverage (from orchestrator.run_coverage_check)
        nlp: spaCy NLP model (optional, enables subject_ratio)

    Returns:
        Complete compliance report dict
    """
    if not article_text or not s1_data:
        return {"error": "Missing article text or S1 data", "overall_score": 0}

    print("[COMPLIANCE] Starting Entity SEO Compliance analysis...")

    parsed = _split_article(article_text)
    print(f"[COMPLIANCE] Parsed: H1='{parsed['h1'][:50]}', {len(parsed['h2_sections'])} H2s, {len(parsed['paragraphs'])} paragraphs")

    compliance = {}

    compliance["entity_salience"] = analyze_entity_salience(parsed, s1_data, nlp)
    print(f"[COMPLIANCE] Entity salience: position={compliance['entity_salience']['position']['status']}, "
          f"h1={compliance['entity_salience']['h1']['status']}, "
          f"subject_ratio={compliance['entity_salience']['subject_ratio']['actual']}")

    compliance["cooccurrence"] = analyze_cooccurrence(parsed, s1_data)
    print(f"[COMPLIANCE] Co-occurrence: {compliance['cooccurrence']['stats']}")

    compliance["spo_triples"] = analyze_spo_triples(parsed, s1_data)
    print(f"[COMPLIANCE] SPO triples: {compliance['spo_triples']['stats']}")

    compliance["mention_variety"] = analyze_mention_variety(parsed, s1_data)
    print(f"[COMPLIANCE] Mention variety: named={compliance['mention_variety']['named']['pct']}%, "
          f"nominal={compliance['mention_variety']['nominal']['pct']}%, "
          f"pronominal={compliance['mention_variety']['pronominal']['pct']}%")

    compliance["causal_chains"] = analyze_causal_chains(parsed, s1_data)
    print(f"[COMPLIANCE] Causal chains: {compliance['causal_chains']['stats']}")

    compliance["centerpiece"] = analyze_centerpiece(parsed, s1_data)
    print(f"[COMPLIANCE] Centerpiece: status={compliance['centerpiece']['status']}")

    compliance["naming_consistency"] = analyze_naming_consistency(parsed, s1_data)
    print(f"[COMPLIANCE] Naming: {compliance['naming_consistency']['unique_forms']} forms, "
          f"status={compliance['naming_consistency']['status']}")

    compliance["hard_facts"] = analyze_hard_facts(parsed, s1_data)
    print(f"[COMPLIANCE] Hard facts: {compliance['hard_facts']['stats']}")

    # N-gram budget (reuse or empty)
    if ngram_coverage:
        compliance["ngram_budget"] = ngram_coverage
    else:
        compliance["ngram_budget"] = {"stats": {"total": 0, "ok": 0, "over": 0, "missing": 0}}

    # Overall score
    scoring = compute_overall_score(compliance)
    compliance["overall_score"] = scoring["overall_score"]
    compliance["component_scores"] = scoring["component_scores"]
    compliance["score_weights"] = scoring["weights"]

    print(f"[COMPLIANCE] Overall score: {compliance['overall_score']}/100")
    print(f"[COMPLIANCE] Components: {scoring['component_scores']}")

    compliance["article_meta"] = {
        "word_count": parsed["word_count"],
        "h1": parsed["h1"],
        "h2_count": len(parsed["h2_sections"]),
        "paragraph_count": len(parsed["paragraphs"]),
    }

    return compliance
