"""
Variable extraction from S1 data — populates all template placeholders.
Maps S1 response to BRAJEN_PROMPTS_v1.0 variables.

Dokument referencyjny: BRAJEN SEO — Prompty produkcyjne v1.0, Sekcja 7.
"""
import re
import json


def extract_global_variables(s1_data: dict, target_length: int = 2000) -> dict:
    """
    Extract global variables from S1 data.
    Full mapping per BRAJEN_PROMPTS_v1.0 Section 7.
    """
    main_entity, main_salience = _extract_main_entity(s1_data)
    must_cover = _extract_must_cover(s1_data, main_entity)

    ngrams = s1_data.get("ngrams") or []
    extended = s1_data.get("extended_terms") or []
    ngrams_formatted = _format_ngrams_with_limits(ngrams)

    h2_plan = _build_h2_plan(s1_data)

    serp = s1_data.get("serp_analysis") or {}
    target_length = _calc_target_length(serp, target_length)
    paa_unanswered, paa_standard = _extract_paa(s1_data, serp)
    related = _get_related_searches(serp)
    brands = _extract_brands_from_related(related)
    hard_facts = _extract_hard_facts(s1_data, serp)

    causal = s1_data.get("causal_triplets") or {}
    chains = causal.get("chains") or []
    relations = causal.get("singles") or []

    h2_patterns_raw = (
        s1_data.get("h2_patterns") or
        serp.get("competitor_h2_patterns") or []
    )
    h2_patterns = _clean_h2_list(h2_patterns_raw)[:15]

    peryfrazy, warianty_potoczne, warianty_formalne, anglicyzmy = \
        _extract_search_variants(s1_data)

    entity_seo = s1_data.get("entity_seo") or {}
    concept_entities = entity_seo.get("concept_entities") or []
    entity_placement = entity_seo.get("entity_placement") or {}

    return {
        "HASLO_GLOWNE":             s1_data.get("main_keyword", ""),
        "ENCJA_GLOWNA":             main_entity,
        "SALIENCE":                 str(round(main_salience, 2)),
        "DLUGOSC_CEL":              str(target_length),
        "LICZBA_H2":                str(len(h2_plan)),
        "PLAN_ARTYKULU":            "\n".join(f"{i+1}. {h}" for i, h in enumerate(h2_plan)),
        "PLAN_H2":                  json.dumps(h2_plan, ensure_ascii=False),
        "ENCJE_KRYTYCZNE":          json.dumps(must_cover, ensure_ascii=False),
        "NGRAMY_Z_CZESTOTLIWOSCIA": ngrams_formatted,
        "NGRAMY_Z_LIMITAMI":        json.dumps(
            [{"ngram": ng.get("ngram",""), "min": ng.get("freq_min",0), "max": ng.get("freq_max",5)}
             for ng in ngrams], ensure_ascii=False),
        "LANCUCHY_KAUZALNE":        json.dumps(chains, ensure_ascii=False),
        "RELACJE_KAUZALNE":         json.dumps(relations, ensure_ascii=False),
        "PERYFRAZY":                json.dumps(peryfrazy, ensure_ascii=False),
        "PERYFRAZY_ALL":            json.dumps(peryfrazy, ensure_ascii=False),
        "WARIANTY_POTOCZNE":        json.dumps(warianty_potoczne, ensure_ascii=False),
        "WARIANTY_FORMALNE":        json.dumps(warianty_formalne, ensure_ascii=False),
        "ANGLICYZMY":               json.dumps(anglicyzmy, ensure_ascii=False),
        "HARD_FACTS_ALL":           json.dumps(hard_facts, ensure_ascii=False),
        "PAA_BEZ_ODPOWIEDZI":       json.dumps(paa_unanswered, ensure_ascii=False),
        "PAA_STANDARDOWE":          json.dumps(paa_standard, ensure_ascii=False),
        "MARKI_Z_RELATED_SEARCHES": json.dumps(brands, ensure_ascii=False),
        "WZORCE_H2_KONKURENCJI":    json.dumps(h2_patterns, ensure_ascii=False),
        "YMYL_KLASYFIKACJA":        "none",
        "NW_LUKI":                   "",  # filled by orchestrator if nw_terms provided
        "YMYL_CONTEXT":              "",  # filled by orchestrator legal/medical enricher
        "PUBMED_CYTAT":             "",
        "PYTANIE_SNIPPETOWE":       (paa_unanswered[0] if paa_unanswered
                                     else paa_standard[0] if paa_standard
                                     else s1_data.get("main_keyword", "")),
        "DLUGOSC_INTRO":            str(min(180, target_length // 9)),
        # internal keys (prefixed _)
        "_h2_plan_list":            h2_plan,
        "_paa_unanswered":          paa_unanswered,
        "_paa_standard":            paa_standard,
        "_related_searches":        related,
        "_hard_facts":              hard_facts,
        "_brands":                  brands,
        "_target_length":           target_length,
        "_ngrams":                  ngrams,
        "_ngrams_full":             ngrams + extended,
        "_concept_entities":        concept_entities,
        "_entity_placement":        entity_placement,
        "_chains":                  chains,
        "_relations":               relations,
        "_h2_patterns":             h2_patterns,
        "_must_cover":              must_cover,
        "_main_salience":           main_salience,
    }


# ── helpers ───────────────────────────────────────────────────

def _extract_main_entity(s1_data):
    """
    Wyciąga encję główną z S1.
    Garbage filtering delegated to web_garbage_filter.is_entity_garbage (Level 1-11).
    Fallback → main_keyword jeśli lista jest pusta lub same garbage.
    """
    entity_seo = s1_data.get("entity_seo") or {}
    main_keyword = s1_data.get("main_keyword") or ""

    try:
        try:
            from src.s1.web_garbage_filter import is_entity_garbage
        except ImportError:
            from web_garbage_filter import is_entity_garbage
    except ImportError:
        is_entity_garbage = None

    def _is_garbage(text):
        if not text:
            return True
        if is_entity_garbage:
            return is_entity_garbage(text)
        return False

    # 1. entity_salience list (already filtered by entity_salience.py v3.1)
    salience_list = entity_seo.get("entity_salience") or []
    if salience_list and isinstance(salience_list, list):
        for item in salience_list:
            if not isinstance(item, dict):
                continue
            text = item.get("entity") or item.get("text") or ""
            score = float(item.get("salience") or item.get("score") or 0.5)
            if text and not _is_garbage(text):
                return text, score

    # 2. entities sorted by importance
    entities = entity_seo.get("entities") or []
    if entities:
        sorted_ents = sorted(
            [e for e in entities if isinstance(e, dict) and e.get("text")],
            key=lambda e: float(e.get("importance") or e.get("salience") or 0),
            reverse=True,
        )
        for top in sorted_ents:
            text = top.get("text") or ""
            score = float(top.get("importance") or top.get("salience") or 0.5)
            if text and not _is_garbage(text):
                return text, score

    # 3. fallback → main_keyword
    return main_keyword, 1.0


def _extract_must_cover(s1_data, main_entity):
    entity_seo = s1_data.get("entity_seo") or {}
    result = []

    for src_key in ("must_cover_concepts", "should_cover_concepts"):
        for item in (entity_seo.get(src_key) or [])[:6]:
            text = item if isinstance(item, str) else item.get("text") or item.get("entity") or ""
            if text and text not in result:
                result.append(text)
        if len(result) >= 5:
            break

    for src_key in ("entities", "concept_entities"):
        for e in (entity_seo.get(src_key) or [])[:6]:
            text = e.get("text") or "" if isinstance(e, dict) else str(e)
            if text and text not in result:
                result.append(text)
        if len(result) >= 10:
            break

    # ensure main entity is first
    if main_entity in result:
        result.remove(main_entity)
    if main_entity:
        result.insert(0, main_entity)
    return result[:12]


def _format_ngrams_with_limits(ngrams):
    lines = []
    for ng in ngrams:
        name = ng.get("ngram") or ng.get("text") or ""
        if not name:
            continue
        fmin = ng.get("freq_min", 0)
        fmax = ng.get("freq_max", 0)
        weight = ng.get("weight", 0)
        if fmin == fmax == 0:
            fmin = max(1, int(weight * 5))
            fmax = max(fmin, int(weight * 10))
        lines.append(f"{name} · {fmin}-{fmax}x")
    return "\n".join(lines)


def _build_h2_plan(s1_data):
    h2_plan = []

    h2_scored = s1_data.get("h2_scored_candidates") or {}
    for c in (h2_scored.get("must_have") or []) + (h2_scored.get("high_priority") or []):
        text = c.get("text") or "" if isinstance(c, dict) else str(c)
        if text and text not in h2_plan:
            h2_plan.append(text)

    if not h2_plan:
        patterns = (
            s1_data.get("h2_patterns") or
            (s1_data.get("serp_analysis") or {}).get("competitor_h2_patterns") or []
        )
        for p in patterns[:8]:
            text = p if isinstance(p, str) else p.get("text") or p.get("pattern") or ""
            if text and text not in h2_plan:
                h2_plan.append(text)

    if not h2_plan:
        kw = s1_data.get("main_keyword") or "Temat"
        h2_plan = [
            f"Czym jest {kw}",
            f"Jak działa {kw}",
            f"Zalety i wady: {kw}",
            f"Jak wybrać {kw}",
        ]

    return h2_plan[:8]


def _calc_target_length(serp, default=2000):
    word_counts = sorted([
        c.get("word_count") or c.get("words") or 0
        for c in (serp.get("competitors") or []) if isinstance(c, dict)
        if (c.get("word_count") or c.get("words") or 0) > 200
    ])
    if not word_counts:
        return default
    mid = len(word_counts) // 2
    median = (word_counts[mid] if len(word_counts) % 2 == 1
              else (word_counts[mid-1] + word_counts[mid]) // 2)
    return max(default, int(median * 1.1))


def _extract_paa(s1_data, serp):
    paa_unanswered, paa_standard = [], []

    # from content_gaps
    for g in ((s1_data.get("content_gaps") or {}).get("paa_unanswered") or []):
        q = g if isinstance(g, str) else g.get("question") or g.get("topic") or ""
        if q and q not in paa_unanswered:
            paa_unanswered.append(q)

    # from serp paa_questions
    for item in (serp.get("paa_questions") or s1_data.get("paa_questions") or []):
        if isinstance(item, str):
            if item not in paa_standard and item not in paa_unanswered:
                paa_standard.append(item)
        elif isinstance(item, dict):
            question = item.get("question") or item.get("text") or ""
            if not question:
                continue
            answer = item.get("answer") or item.get("snippet") or ""
            if not answer or len(str(answer).strip()) < 20:
                if question not in paa_unanswered:
                    paa_unanswered.append(question)
            else:
                if question not in paa_standard and question not in paa_unanswered:
                    paa_standard.append(question)

    return paa_unanswered[:8], paa_standard[:10]


def _get_related_searches(serp):
    result = []
    for r in (serp.get("related_searches") or []):
        text = r if isinstance(r, str) else r.get("query") or r.get("text") or ""
        if text:
            result.append(text)
    return result[:10]


def _extract_hard_facts(s1_data, serp):
    facts = []
    sources = list(serp.get("competitor_snippets") or serp.get("serp_snippets") or [])
    featured = serp.get("featured_snippet") or {}
    sources.append(featured.get("answer") or "" if isinstance(featured, dict) else str(featured))
    ai_ov = serp.get("ai_overview") or {}
    sources.append(ai_ov.get("text") or "" if isinstance(ai_ov, dict) else "")

    for text in sources:
        if not text or not isinstance(text, str):
            continue
        facts += re.findall(r"\d[\d\s]*[,.]?\d*\s*(?:zł|PLN|EUR|USD|€|\$|tys\. zł|mln zł)", text)
        facts += re.findall(r"(?:20[12]\d|19\d{2})\s*(?:r\.|roku|rok)", text)
        facts += re.findall(r"\d+[,.]?\d*\s*(?:proc\.|%|procent)", text)
        facts += re.findall(r"\d+[,.]?\d*\s*(?:kg|g|cm|mm|m²|m2|km|l|ml|h|min|godzin|dni|lat|miesięcy)", text)

    seen, unique = set(), []
    for f in facts:
        k = re.sub(r"\s+", " ", f).strip().lower()
        if k not in seen and len(k) > 2:
            seen.add(k)
            unique.append(f.strip())
    return unique[:25]


def _extract_search_variants(s1_data):
    v = s1_data.get("search_variants") or {}
    return (v.get("peryfrazy") or [], v.get("warianty_potoczne") or [],
            v.get("warianty_formalne") or [], v.get("anglicyzmy") or [])


def _extract_brands_from_related(related_searches):
    known = {
        "ikea", "decathlon", "jysk", "allegro", "amazon", "empik",
        "leroy merlin", "castorama", "obi", "media expert", "rtv euro agd",
        "euro agd", "komputronik", "morele", "x-kom", "neonet",
        "pepco", "sinsay", "h&m", "zara", "reserved", "rossmann",
        "hebe", "biedronka", "lidl", "aldi", "carrefour", "kaufland",
    }
    brands = []
    for rs in related_searches:
        text = rs.lower() if isinstance(rs, str) else str(rs).lower()
        for b in known:
            if b in text:
                bd = b.title()
                if bd not in brands:
                    brands.append(bd)
    return brands


def _clean_h2_list(h2_list):
    seen, clean = set(), []
    for h in h2_list:
        text = (h if isinstance(h, str) else h.get("text") or h.get("pattern") or "").strip()
        if 5 <= len(text) <= 120 and text.lower() not in seen:
            seen.add(text.lower())
            clean.append(text)
    return clean


def fill_template(template: str, variables: dict) -> str:
    """Replace {{PLACEHOLDER}} in template with variable values."""
    result = template
    for key, value in variables.items():
        if key.startswith("_"):
            continue
        result = result.replace("{{" + key + "}}", str(value) if value is not None else "")
    return result
