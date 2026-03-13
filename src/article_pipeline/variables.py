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

    peryfrazy, warianty_potoczne, warianty_formalne, anglicyzmy, mention_forms = \
        _extract_search_variants(s1_data)

    factographic = s1_data.get("factographic_triplets") or {}
    facto_all = (factographic.get("spo") or []) + (factographic.get("eav") or [])

    # ── AI Overview & Featured Snippet text ──
    ai_overview_text = _extract_ai_overview_text(serp)
    featured_snippet_text = _extract_featured_snippet_text(serp)

    # ── Key ngram & triplet for Batch 0 ──
    key_ngram = _select_key_ngram(ngrams, main_entity)
    key_triplet = _select_key_triplet(chains, relations)

    entity_seo = s1_data.get("entity_seo") or {}
    concept_entities = entity_seo.get("concept_entities") or []
    entity_placement = entity_seo.get("entity_placement") or {}

    # ── Entity signals for writer prompts ──
    placement_instruction = entity_placement.get("placement_instruction", "")
    cooccurrence_pairs = entity_seo.get("cooccurrence_pairs") or []
    entity_relationships = entity_seo.get("entity_relationships") or []
    salience_list = entity_seo.get("entity_salience") or []

    # Subject ratio for main entity
    subject_ratio_pct = _extract_subject_ratio(salience_list, main_entity)

    # Early entities (avg_first_position in top 20% → intro)
    early_entities = _extract_early_entities(salience_list)

    # Strong cooccurrence pairs (strength >= 0.2, sentence_count >= 3)
    strong_cooccurrence = [
        p for p in cooccurrence_pairs
        if isinstance(p, dict) and p.get("strength", 0) >= 0.2
           and p.get("sentence_co_occurrences", p.get("sentence_count", 0)) >= 3
    ][:8]

    # Heading patterns from competitors
    heading_examples = _extract_heading_examples(salience_list, main_entity)

    # Competitor opening patterns
    competitor_openings = _extract_competitor_openings(serp)

    # Depth opportunities from content gaps
    depth_missing = _extract_depth_missing(s1_data)

    # Must cover with coverage/role info
    must_cover_enriched = _enrich_must_cover(must_cover, salience_list)

    return {
        "HASLO_GLOWNE":             s1_data.get("main_keyword", ""),
        "ENCJA_GLOWNA":             main_entity,
        "SALIENCE":                 str(round(main_salience, 2)),
        "DLUGOSC_CEL":              str(target_length),
        "LICZBA_H2":                str(len(h2_plan)),
        "PLAN_ARTYKULU":            "\n".join(f"{i+1}. {h}" for i, h in enumerate(h2_plan)),
        "PLAN_H2":                  json.dumps(h2_plan, ensure_ascii=False),
        "ENCJE_KRYTYCZNE":          json.dumps(must_cover, ensure_ascii=False),
        "ENCJE_KRYTYCZNE_Z_KONTEKSTEM": json.dumps(must_cover_enriched, ensure_ascii=False),
        "PLACEMENT_INSTRUCTION":    placement_instruction,
        "COOCCURRENCE_PAIRS_JSON":  json.dumps(strong_cooccurrence[:5], ensure_ascii=False),
        "ENTITY_RELATIONSHIPS_JSON": json.dumps(entity_relationships[:10], ensure_ascii=False),
        "SUBJECT_RATIO_PCT":        subject_ratio_pct,
        "EARLY_ENTITIES_JSON":      json.dumps(early_entities, ensure_ascii=False),
        "HEADING_EXAMPLES_JSON":    json.dumps(heading_examples, ensure_ascii=False),
        "COMPETITOR_OPENINGS_JSON": json.dumps(competitor_openings, ensure_ascii=False),
        "DEPTH_MISSING_JSON":       json.dumps(depth_missing, ensure_ascii=False),
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
        "MENTION_FORMS_JSON":       json.dumps(mention_forms, ensure_ascii=False),
        "TROJKI_FAKTOGRAFICZNE_JSON": json.dumps(facto_all[:15], ensure_ascii=False),
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
        "AI_OVERVIEW_TEXT":         ai_overview_text,
        "FEATURED_SNIPPET_TEXT":    featured_snippet_text,
        "KEY_NGRAM":                key_ngram,
        "KEY_TRIPLET":              key_triplet,
        "PIERWSZY_H2":              h2_plan[0] if h2_plan else "",
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
        "_cooccurrence_pairs":      strong_cooccurrence,
        "_entity_relationships":    entity_relationships,
        "_early_entities":          early_entities,
        "_mention_forms":            mention_forms,
        "_factographic_triplets":    facto_all,
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


def format_ngrams_for_section(ngram_names: list, all_ngrams: list, total_sections: int) -> str:
    """Format ngrams assigned to a section WITH per-section frequency budgets.

    Looks up each ngram in the full list to get its whole-article budget,
    then divides by total_sections to produce a per-section ceiling.

    Returns lines like: 'zabezpieczyć meble · max 1-2x w tej sekcji (budżet artykułu: 1-9)'
    """
    # Build lookup: normalized ngram text -> {freq_min, freq_max}
    lookup = {}
    for ng in all_ngrams:
        text = (ng.get("ngram") or ng.get("text") or "").strip().lower()
        if not text:
            continue
        fmin = ng.get("freq_min", 0)
        fmax = ng.get("freq_max", 0)
        weight = ng.get("weight", 0)
        if fmin == fmax == 0:
            fmin = max(1, int(weight * 5))
            fmax = max(fmin, int(weight * 10))
        lookup[text] = {"min": fmin, "max": fmax}

    total = max(2, total_sections)  # intro + H2s + faq
    lines = []
    for name in ngram_names:
        if not name or not isinstance(name, str):
            continue
        info = lookup.get(name.strip().lower(), {})
        art_min = info.get("min", 1)
        art_max = info.get("max", 3)
        # Per-section ceiling: divide article max by sections, round up, min 1
        sec_max = max(1, -(-art_max // total))  # ceiling division
        sec_min = 0  # not every section needs every ngram
        lines.append(f"{name} · max {sec_max}x w tej sekcji (artykuł: {art_min}-{art_max})")
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
    """Return competitor-based target length (no minimum floor)."""
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
    return median


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
    """Extract hard facts with category and source context."""
    raw_facts = []
    sources = list(serp.get("competitor_snippets") or serp.get("serp_snippets") or [])
    featured = serp.get("featured_snippet") or {}
    sources.append(featured.get("answer") or "" if isinstance(featured, dict) else str(featured))
    ai_ov = serp.get("ai_overview") or {}
    sources.append(ai_ov.get("text") or "" if isinstance(ai_ov, dict) else "")

    patterns = [
        ("price", r"\d[\d\s]*[,.]?\d*\s*(?:zł|PLN|EUR|USD|€|\$|tys\.\s*zł|mln\s*zł)"),
        ("date", r"(?:20[12]\d|19\d{2})\s*(?:r\.|roku|rok)"),
        ("percent", r"\d+[,.]?\d*\s*(?:proc\.|%|procent)"),
        ("measure", r"\d+[,.]?\d*\s*(?:kg|g|cm|mm|m²|m2|km|l|ml|h|min|godzin|dni|lat|miesięcy)"),
    ]

    for text in sources:
        if not text or not isinstance(text, str):
            continue
        for category, pattern in patterns:
            for match in re.finditer(pattern, text):
                value = match.group().strip()
                # Extract surrounding context (up to 60 chars each side)
                start = max(0, match.start() - 60)
                end = min(len(text), match.end() + 60)
                snippet = text[start:end].replace("\n", " ").strip()
                if start > 0:
                    snippet = "..." + snippet
                if end < len(text):
                    snippet = snippet + "..."
                raw_facts.append({
                    "value": value,
                    "category": category,
                    "source_snippet": snippet,
                })

    seen, unique = set(), []
    for f in raw_facts:
        k = re.sub(r"\s+", " ", f["value"]).strip().lower()
        if k not in seen and len(k) > 2:
            seen.add(k)
            unique.append(f)
    return unique[:25]


def _extract_subject_ratio(salience_list: list, main_entity: str) -> str:
    """Extract subject_ratio percentage for the main entity."""
    if not salience_list or not main_entity:
        return "70"  # sensible default
    entity_lower = main_entity.lower()
    for item in salience_list:
        if not isinstance(item, dict):
            continue
        text = (item.get("entity") or item.get("entity_text") or "").lower()
        if text == entity_lower or entity_lower in text:
            signals = item.get("signals", {})
            ratio = signals.get("subject_ratio", 0.7)
            return str(int(ratio * 100))
    return "70"


def _extract_early_entities(salience_list: list) -> list:
    """Extract entities that appear early in competitor texts (top 20%)."""
    early = []
    for item in salience_list:
        if not isinstance(item, dict):
            continue
        signals = item.get("signals", {})
        position = signals.get("position", 0)  # higher = earlier
        early_mentions = signals.get("early_mentions", 0)
        entity = item.get("entity") or item.get("entity_text") or ""
        if entity and (position >= 0.8 or early_mentions >= 3):
            early.append(entity)
    return early[:6]


def _extract_heading_examples(salience_list: list, main_entity: str) -> list:
    """Extract heading examples from competitors for the main entity."""
    entity_lower = main_entity.lower()
    for item in salience_list:
        if not isinstance(item, dict):
            continue
        text = (item.get("entity") or item.get("entity_text") or "").lower()
        if text == entity_lower or entity_lower in text:
            return item.get("heading_examples", [])[:5]
    return []


def _extract_competitor_openings(serp: dict) -> list:
    """Extract first paragraphs from competitors for opening pattern analysis."""
    competitors = serp.get("competitors") or []
    openings = []
    for c in competitors[:5]:
        if not isinstance(c, dict):
            continue
        fp = (c.get("first_paragraph") or "").strip()
        if fp and len(fp) > 50:
            openings.append(fp[:200])
    return openings


def _extract_depth_missing(s1_data: dict) -> list:
    """Extract depth opportunities from content gaps."""
    gaps = s1_data.get("content_gaps") or {}
    depth = gaps.get("depth_missing") or gaps.get("shallow_topics") or []
    result = []
    for item in depth[:5]:
        if isinstance(item, str):
            result.append({"topic": item})
        elif isinstance(item, dict):
            result.append({
                "topic": item.get("topic") or item.get("subtopic") or "",
                "avg_words": item.get("avg_words") or item.get("word_count") or 0,
            })
    return result


def _enrich_must_cover(must_cover: list, salience_list: list) -> list:
    """Enrich must_cover entities with coverage/role context from salience data."""
    salience_lookup = {}
    for item in salience_list:
        if not isinstance(item, dict):
            continue
        entity = (item.get("entity") or item.get("entity_text") or "").lower()
        if entity:
            signals = item.get("signals", {})
            dist = signals.get("distribution", "0/0")
            salience_lookup[entity] = dist

    enriched = []
    for entity in must_cover:
        dist = salience_lookup.get(entity.lower(), "")
        if dist:
            parts = dist.split("/")
            try:
                count = int(parts[0])
                total = int(parts[1]) if len(parts) > 1 else 8
                if count >= total * 0.7:
                    role = "MUST"
                elif count >= total * 0.4:
                    role = "SHOULD"
                else:
                    role = "DIFFERENTIATOR"
            except (ValueError, IndexError):
                role = "SHOULD"
        else:
            role = "SHOULD"
        enriched.append({"entity": entity, "coverage": dist, "role": role})
    return enriched


def _extract_search_variants(s1_data):
    v = s1_data.get("search_variants") or {}
    return (v.get("peryfrazy") or [], v.get("warianty_potoczne") or [],
            v.get("warianty_formalne") or [], v.get("anglicyzmy") or [],
            v.get("mention_forms") or {})


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


def _extract_ai_overview_text(serp: dict) -> str:
    """Extract AI Overview text from SERP data as a single string."""
    ai_ov = serp.get("ai_overview") or {}
    if not ai_ov or not isinstance(ai_ov, dict):
        return ""
    text = ai_ov.get("text") or ""
    # If text_blocks available, join them for richer context
    if not text:
        blocks = ai_ov.get("text_blocks") or []
        text = " ".join(b if isinstance(b, str) else b.get("text", "") for b in blocks).strip()
    return text[:2000]


def _extract_featured_snippet_text(serp: dict) -> str:
    """Extract Featured Snippet text from SERP data."""
    fs = serp.get("featured_snippet") or {}
    if not fs or not isinstance(fs, dict):
        return ""
    answer = fs.get("answer") or fs.get("snippet") or ""
    title = fs.get("title") or ""
    if title and answer:
        return f"{title}: {answer}"[:1000]
    return (answer or title)[:1000]


def _select_key_ngram(ngrams: list, main_entity: str) -> str:
    """Select the highest-weight n-gram that contains the main entity."""
    if not ngrams or not main_entity:
        return ""
    entity_lower = main_entity.lower()
    entity_words = set(entity_lower.split())
    for ng in ngrams:
        text = (ng.get("ngram") or "") if isinstance(ng, dict) else str(ng)
        text_lower = text.lower()
        # Check if ngram contains entity (full match or word overlap ≥50%)
        if entity_lower in text_lower:
            return text
        ng_words = set(text_lower.split())
        if entity_words and len(entity_words & ng_words) >= max(1, len(entity_words) * 0.5):
            return text
    return ""


def _select_key_triplet(chains: list, relations: list) -> str:
    """Select the top causal triplet as 'cause → effect' string."""
    # Prefer chains (multi-hop), then single relations
    for source in [chains, relations]:
        if not source:
            continue
        for item in source:
            if isinstance(item, dict):
                cause = item.get("cause") or item.get("przyczyna") or ""
                effect = item.get("effect") or item.get("skutek") or ""
                mid = item.get("mechanism") or item.get("relation_type") or ""
                if cause and effect:
                    if mid and mid not in ("causes", "leads_to"):
                        return f"{cause} → {mid} → {effect}"
                    return f"{cause} → {effect}"
            elif isinstance(item, str) and "→" in item:
                return item
    return ""


def fill_template(template: str, variables: dict) -> str:
    """Replace {{PLACEHOLDER}} in template with variable values."""
    result = template
    for key, value in variables.items():
        if key.startswith("_"):
            continue
        result = result.replace("{{" + key + "}}", str(value) if value is not None else "")
    return result
