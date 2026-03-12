"""
Variable extraction from S1 data — populates all template placeholders.
Maps S1 response to BRAJEN_PROMPTS_v1.0 variables.
"""
import json


def extract_global_variables(s1_data: dict, target_length: int = 2000) -> dict:
    """
    Extract global variables from S1 data for the article pipeline.
    These are used in SYSTEM PROMPT and shared across all batches.
    """
    # Entity with highest salience
    entity_seo = s1_data.get("entity_seo") or {}
    entities = entity_seo.get("entities", [])
    salience_data = entity_seo.get("entity_salience", [])

    main_entity = ""
    main_salience = 0.0
    if salience_data:
        top = salience_data[0] if isinstance(salience_data, list) and salience_data else {}
        main_entity = top.get("entity", top.get("text", ""))
        main_salience = top.get("salience", top.get("score", 0.0))
    elif entities:
        top = entities[0] if isinstance(entities, list) and entities else {}
        main_entity = top.get("text", top.get("entity", ""))
        main_salience = top.get("importance", 0.5)

    # If no entity found, use main keyword
    if not main_entity:
        main_entity = s1_data.get("main_keyword", "")
        main_salience = 1.0

    # Critical entities
    must_cover = entity_seo.get("must_cover_concepts", [])
    if not must_cover and entities:
        must_cover = [e.get("text", "") for e in entities[:10] if e.get("text")]

    # N-grams with frequency limits
    ngrams = s1_data.get("ngrams", [])
    ngrams_with_limits = []
    for ng in ngrams:
        name = ng.get("ngram", "")
        fmin = ng.get("freq_min", 0)
        fmax = ng.get("freq_max", 0)
        ngrams_with_limits.append(f"{name} · {fmin}-{fmax}x")

    # Causal chains
    causal = s1_data.get("causal_triplets") or {}
    chains = causal.get("chains", [])
    relations = causal.get("singles", [])

    # SERP analysis
    serp = s1_data.get("serp_analysis") or {}
    paa = serp.get("paa_questions", [])
    related = serp.get("related_searches", [])
    h2_patterns = serp.get("competitor_h2_patterns", [])

    # Identify PAA without answers in SERP
    paa_unanswered = []
    paa_standard = []
    for q in paa:
        if isinstance(q, dict):
            answer = q.get("answer", "")
            question = q.get("question", "")
            if not answer or len(answer.strip()) < 20:
                paa_unanswered.append(question)
            else:
                paa_standard.append(question)

    # H2 plan from scored candidates
    h2_scored = s1_data.get("h2_scored_candidates") or {}
    h2_plan = []
    for c in (h2_scored.get("must_have", []) + h2_scored.get("high_priority", []))[:8]:
        h2_plan.append(c.get("text", ""))

    # SERP snippets for hard facts
    hard_facts = _extract_hard_facts(serp)

    # Competitor word counts for target length
    competitors = serp.get("competitors", [])
    if competitors:
        word_counts = [c.get("word_count", 0) for c in competitors if c.get("word_count", 0) > 200]
        if word_counts:
            target_length = int(sum(word_counts) / len(word_counts) * 1.1)

    # Related searches as brands
    brands = _extract_brands_from_related(related)

    return {
        "HASLO_GLOWNE": s1_data.get("main_keyword", ""),
        "ENCJA_GLOWNA": main_entity,
        "SALIENCE": str(round(main_salience, 2)),
        "DLUGOSC_CEL": str(target_length),
        "LICZBA_H2": str(len(h2_plan)),
        "PLAN_ARTYKULU": "\n".join(f"{i+1}. {h}" for i, h in enumerate(h2_plan)),
        "PLAN_H2": json.dumps(h2_plan, ensure_ascii=False),
        "ENCJE_KRYTYCZNE": json.dumps(must_cover, ensure_ascii=False),
        "NGRAMY_Z_CZESTOTLIWOSCIA": "\n".join(ngrams_with_limits),
        "NGRAMY_Z_LIMITAMI": json.dumps(
            [{"ngram": ng.get("ngram", ""), "min": ng.get("freq_min", 0), "max": ng.get("freq_max", 5)}
             for ng in ngrams],
            ensure_ascii=False,
        ),
        "LANCUCHY_KAUZALNE": json.dumps(chains, ensure_ascii=False),
        "RELACJE_KAUZALNE": json.dumps(relations, ensure_ascii=False),
        "PERYFRAZY": "[]",  # populated from secondary_variants if available
        "PERYFRAZY_ALL": "[]",
        "WARIANTY_POTOCZNE": "[]",
        "WARIANTY_FORMALNE": "[]",
        "HARD_FACTS_ALL": json.dumps(hard_facts, ensure_ascii=False),
        "PAA_BEZ_ODPOWIEDZI": json.dumps(paa_unanswered, ensure_ascii=False),
        "PAA_STANDARDOWE": json.dumps(paa_standard, ensure_ascii=False),
        "MARKI_Z_RELATED_SEARCHES": json.dumps(brands, ensure_ascii=False),
        "YMYL_KLASYFIKACJA": "none",  # determined by YMYL detector
        "PUBMED_CYTAT": "",
        "WZORCE_H2_KONKURENCJI": json.dumps(h2_patterns[:10], ensure_ascii=False),
        "PYTANIE_SNIPPETOWE": paa_unanswered[0] if paa_unanswered else (paa_standard[0] if paa_standard else s1_data.get("main_keyword", "")),
        "DLUGOSC_INTRO": str(min(150, target_length // 10)),
        # H2 plan as list for iteration
        "_h2_plan_list": h2_plan,
        "_paa_unanswered": paa_unanswered,
        "_paa_standard": paa_standard,
        "_related_searches": related,
        "_hard_facts": hard_facts,
        "_brands": brands,
        "_target_length": target_length,
        "_ngrams": ngrams,
    }


def _extract_hard_facts(serp: dict) -> list[str]:
    """Extract numeric facts from SERP snippets."""
    import re
    facts = []
    snippets = serp.get("competitor_snippets", [])
    featured = serp.get("featured_snippet") or {}
    ai_overview = serp.get("ai_overview") or {}

    all_text = snippets + [featured.get("answer", ""), ai_overview.get("text", "")]

    for text in all_text:
        if not text:
            continue
        # Extract prices
        prices = re.findall(r"\d+[\s,.]?\d*\s*(?:zł|PLN|EUR|USD|€|\$)", text)
        facts.extend(prices)
        # Extract years
        years = re.findall(r"(?:20[12]\d|19\d{2})\s*(?:r\.|roku|rok)", text)
        facts.extend(years)
        # Extract percentages
        pcts = re.findall(r"\d+[\s,.]?\d*\s*%", text)
        facts.extend(pcts)

    return list(dict.fromkeys(facts))[:20]


def _extract_brands_from_related(related_searches: list) -> list[str]:
    """Extract brand names from related searches."""
    brands = []
    known_brand_patterns = [
        "IKEA", "Decathlon", "JYSK", "Allegro", "Amazon", "Empik",
        "Leroy Merlin", "Castorama", "OBI", "Media Expert", "RTV Euro AGD",
    ]
    for rs in related_searches:
        text = rs if isinstance(rs, str) else str(rs)
        for brand in known_brand_patterns:
            if brand.lower() in text.lower() and brand not in brands:
                brands.append(brand)
    return brands


def fill_template(template: str, variables: dict) -> str:
    """Replace {{PLACEHOLDER}} in template with values from variables dict."""
    result = template
    for key, value in variables.items():
        if key.startswith("_"):
            continue
        placeholder = "{{" + key + "}}"
        result = result.replace(placeholder, str(value))
    return result
