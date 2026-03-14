"""
===============================================================================
BRIEF GENERATOR — Czytelny brief contentowy dla copywritera
===============================================================================
Generuje brief z danych S1 + pipeline variables. Bez żargonu technicznego.
10 sekcji: nagłówek, intencja, temat główny, tematy do pokrycia, plan,
warianty językowe, frazy kluczowe, fakty, relacje, styl.

Zwraca strukturę danych do renderowania w panelu i eksportu markdown.
===============================================================================
"""

import json
from datetime import datetime
from typing import Dict, List, Optional


def generate_brief(
    s1_data: Dict,
    variables: Dict,
    pre_batch_map: Dict = None,
) -> Dict:
    """Generate content brief from S1 data and pipeline variables.

    Returns structured brief dict with 10 sections.
    """
    variables = variables or {}
    pre_batch_map = pre_batch_map or {}
    entity_seo = s1_data.get("entity_seo") or {}
    serp = s1_data.get("serp_analysis") or {}
    causal = s1_data.get("causal_triplets") or {}
    factographic = s1_data.get("factographic_triplets") or {}

    brief = {}

    # ── 1. NAGŁÓWEK ──
    brief["header"] = {
        "main_keyword": s1_data.get("main_keyword", ""),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "target_length": variables.get("DLUGOSC_CEL", ""),
        "ymyl_category": variables.get("YMYL_KLASYFIKACJA", "brak"),
    }

    # ── 2. INTENCJA WYSZUKIWANIA ──
    ai_overview = variables.get("AI_OVERVIEW_TEXT", "")
    featured_snippet = variables.get("FEATURED_SNIPPET_TEXT", "")
    competitors = serp.get("competitors") or []
    comp_table = []
    for i, c in enumerate(competitors[:6]):
        comp_table.append({
            "rank": i + 1,
            "domain": _extract_domain(c.get("url", "")),
            "words": c.get("word_count", 0),
            "h2_count": c.get("h2_count", 0),
        })
    word_counts = [c.get("word_count", 0) for c in competitors if c.get("word_count", 0) > 0]
    avg_words = round(sum(word_counts) / max(len(word_counts), 1)) if word_counts else 0
    brief["search_intent"] = {
        "ai_overview": ai_overview[:500] if ai_overview else "",
        "featured_snippet": featured_snippet[:500] if featured_snippet else "",
        "competitors": comp_table,
        "avg_competitor_words": avg_words,
    }

    # ── 3. TEMAT GŁÓWNY ──
    main_entity = variables.get("ENCJA_GLOWNA", s1_data.get("main_keyword", ""))
    placement = entity_seo.get("entity_placement") or {}
    brief["main_topic"] = {
        "entity": main_entity,
        "keyword": s1_data.get("main_keyword", ""),
        "placement_instruction": placement.get("placement_instruction", ""),
        "subject_ratio_target": variables.get("SUBJECT_RATIO_PCT", ""),
        "first_paragraph_entities": placement.get("first_paragraph_entities") or [],
    }

    # ── 4. TEMATY DO POKRYCIA ──
    must_cover = entity_seo.get("must_cover_concepts") or []
    should_cover = entity_seo.get("should_cover_concepts") or []
    differentiators = entity_seo.get("differentiator_concepts") or []

    # Build per-entity enriched context from ENCJE_KRYTYCZNE_Z_KONTEKSTEM
    enriched_raw = variables.get("ENCJE_KRYTYCZNE_Z_KONTEKSTEM", "")
    enriched_lookup = {}
    if enriched_raw:
        try:
            enriched_list = json.loads(enriched_raw) if isinstance(enriched_raw, str) else enriched_raw
            if isinstance(enriched_list, list):
                for item in enriched_list:
                    if isinstance(item, dict):
                        ent = item.get("entity", "")
                        role = item.get("role", "SHOULD")
                        cov = item.get("coverage", "")
                        enriched_lookup[ent.lower()] = {"role": role, "coverage": cov}
        except (json.JSONDecodeError, TypeError):
            pass

    brief["topics"] = {
        "must_cover": _format_entity_list_with_context(must_cover, enriched_lookup),
        "should_cover": _format_entity_list_with_context(should_cover, enriched_lookup),
        "differentiators": _format_entity_list_with_context(differentiators, enriched_lookup),
    }

    # ── 5. PLAN ARTYKUŁU ──
    h2_plan = variables.get("_h2_plan_list") or []
    plan_sections = []
    for i, h2 in enumerate(h2_plan):
        batch_key = f"batch_{i+1}"
        batch_data = pre_batch_map.get(batch_key) or {}
        plan_sections.append({
            "h2": h2,
            "entities": batch_data.get("entities", []),
            "hard_facts": batch_data.get("hard_facts", []),
        })

    # FAQ with priority markers: unanswered PAA = high priority
    paa_unanswered = set()
    for q in (variables.get("_paa_unanswered") or []):
        paa_unanswered.add(q.lower().strip())
    faq_questions = variables.get("_faq_questions") or []
    faq_with_priority = []
    for q in faq_questions[:6]:
        is_unanswered = q.lower().strip() in paa_unanswered
        faq_with_priority.append({
            "question": q,
            "priority": "unanswered" if is_unanswered else "standard",
        })
    brief["plan"] = {
        "h1_suggestion": variables.get("H1_PROPOZYCJA", ""),
        "intro_length": variables.get("DLUGOSC_INTRO", ""),
        "sections": plan_sections,
        "faq": faq_with_priority,
        "has_ymyl": bool(variables.get("YMYL_CONTEXT")),
        "ymyl_context": variables.get("YMYL_CONTEXT", ""),
    }

    # ── 6. WARIANTY JĘZYKOWE ──
    brief["language_variants"] = {
        "named": variables.get("NAMED_FORMS", ""),
        "nominal": variables.get("NOMINAL_FORMS", ""),
        "pronominal": variables.get("PRONOMINAL_CUES", ""),
        "periphrases": variables.get("PERYFRAZY", ""),
        "colloquial": variables.get("WARIANTY_POTOCZNE", ""),
        "formal": variables.get("WARIANTY_FORMALNE", ""),
        "rotation_pattern": "Pelna nazwa \u2192 Opis zastepczy \u2192 Zaimek \u2192 (nowy akapit = znow pelna nazwa). NIE powtarzaj tej samej formy 3 razy z rzedu.",
    }

    # ── 7. FRAZY KLUCZOWE ──
    ngrams = s1_data.get("ngrams") or []
    extended = s1_data.get("extended_terms") or []
    phrases = []
    for ng in ngrams + extended:
        text = ng.get("ngram") or ng.get("text") or ""
        weight = float(ng.get("weight") or 0)
        freq_min = ng.get("freq_min", 0)
        freq_max = ng.get("freq_max", 0)
        if text and freq_max > 0:
            if weight >= 0.5:
                priority = "OBOWIĄZKOWA"
            elif weight >= 0.3:
                priority = "WAŻNA"
            else:
                priority = "OPCJONALNA"
            phrases.append({
                "phrase": text,
                "freq_range": f"{freq_min}-{freq_max}",
                "priority": priority,
                "weight": round(weight, 3),
            })
    phrases.sort(key=lambda p: (-{"OBOWIĄZKOWA": 3, "WAŻNA": 2, "OPCJONALNA": 1}[p["priority"]], -p["weight"]))
    brief["keyphrases"] = phrases[:30]

    # ── 8. FAKTY I DANE ──
    hard_facts = []
    hf_raw = variables.get("_hard_facts") or s1_data.get("hard_facts") or []
    for hf in hf_raw:
        if isinstance(hf, dict):
            hard_facts.append({
                "value": hf.get("value", ""),
                "category": hf.get("category", ""),
                "source": hf.get("source_snippet", "")[:100],
            })
        elif isinstance(hf, str):
            hard_facts.append({"value": hf, "category": "", "source": ""})
    brief["hard_facts"] = hard_facts[:20]

    # ── 9. RELACJE I MECHANIZMY ──
    chains = causal.get("chains") or []
    singles = causal.get("singles") or []
    causal_items = []
    for c in chains + singles:
        if isinstance(c, dict):
            causal_items.append({
                "cause": c.get("cause", ""),
                "effect": c.get("effect", ""),
                "type": c.get("relation_type", ""),
                "is_chain": c.get("is_chain", False),
            })

    # SPO triples
    spo_items = []
    facto_raw = factographic.get("spo") or []
    for t in facto_raw:
        if isinstance(t, dict):
            spo_items.append({
                "subject": t.get("subject", ""),
                "predicate": t.get("verb", t.get("predicate", "")),
                "object": t.get("object", ""),
            })

    brief["relations"] = {
        "causal_chains": causal_items[:10],
        "spo_triples": spo_items[:10],
    }

    # ── 10. STYL I REGUŁY ──
    cooc_pairs = variables.get("PARY_KOOCCURRENCE", "")
    brief["style"] = {
        "ymyl_context": variables.get("YMYL_CONTEXT", ""),
        "cooccurrence_pairs": cooc_pairs,
        "banned_phrases": "Warto zaznaczyć, Należy podkreślić, Jest to ważne, W dzisiejszym artykule, Kluczowym aspektem, Co więcej, Ponadto, Niemniej jednak",
    }

    return brief


def render_brief_markdown(brief: Dict) -> str:
    """Render brief as readable Markdown for export."""
    lines = []
    h = brief.get("header") or {}
    lines.append(f"# BRIEF CONTENTOWY")
    lines.append(f"**Hasło:** {h.get('main_keyword', '')}")
    lines.append(f"**Data:** {h.get('date', '')}")
    lines.append(f"**Docelowa długość:** {h.get('target_length', '')} słów")
    lines.append(f"**YMYL:** {h.get('ymyl_category', 'brak')}")
    lines.append("")

    # 2. Intent
    si = brief.get("search_intent") or {}
    lines.append("## 1. Intencja wyszukiwania")
    if si.get("ai_overview"):
        lines.append(f"**AI Overview:** {si['ai_overview']}")
    if si.get("featured_snippet"):
        lines.append(f"**Featured Snippet:** {si['featured_snippet']}")
    if si.get("competitors"):
        lines.append("")
        lines.append("| # | Domena | Słowa | H2 |")
        lines.append("|---|--------|-------|----|")
        for c in si["competitors"]:
            lines.append(f"| {c['rank']} | {c['domain']} | {c['words']} | {c['h2_count']} |")
    lines.append("")

    # 3. Main topic
    mt = brief.get("main_topic") or {}
    lines.append("## 2. Temat główny")
    lines.append(f"**Encja centralna:** {mt.get('entity', '')}")
    if mt.get("placement_instruction"):
        lines.append(f"**Instrukcja rozmieszczenia:** {mt['placement_instruction']}")
    if mt.get("first_paragraph_entities"):
        lines.append(f"**Encje w pierwszym akapicie:** {', '.join(mt['first_paragraph_entities'])}")
    lines.append("")

    # 4. Topics
    topics = brief.get("topics") or {}
    lines.append("## 3. Tematy do pokrycia")
    def _render_topic_group(items, label):
        if not items:
            return
        lines.append(f"**{label}:**")
        for t in items:
            if isinstance(t, dict):
                text = t.get("text", "")
                cov = t.get("coverage", "")
                ctx = f" -- w {cov} artykulow konkurencji" if cov else ""
                lines.append(f"- {text}{ctx}")
            else:
                lines.append(f"- {t}")
    _render_topic_group(topics.get("must_cover"), "OBOWIAZKOWE")
    _render_topic_group(topics.get("should_cover"), "WAZNE")
    _render_topic_group(topics.get("differentiators"), "WYROZNIKI")
    lines.append("")

    # 5. Plan
    plan = brief.get("plan") or {}
    lines.append("## 4. Plan artykułu")
    if plan.get("h1_suggestion"):
        lines.append(f"**H1:** {plan['h1_suggestion']}")
    lines.append(f"**Intro:** ~{plan.get('intro_length', '?')} słów")
    lines.append("")
    for i, s in enumerate(plan.get("sections") or []):
        lines.append(f"### H2: {s['h2']}")
        if s.get("entities"):
            lines.append(f"Tematy: {', '.join(str(e) for e in s['entities'][:5])}")
        if s.get("hard_facts"):
            lines.append(f"Fakty: {', '.join(str(f) for f in s['hard_facts'][:3])}")
        lines.append("")
    if plan.get("faq"):
        lines.append("### FAQ")
        for q in plan["faq"]:
            if isinstance(q, dict):
                qtxt = q.get("question", "")
                prio = q.get("priority", "standard")
                marker = " <-- priorytet: nikt na to nie odpowiada w SERP" if prio == "unanswered" else ""
                lines.append(f"- {qtxt}{marker}")
            else:
                lines.append(f"- {q}")
    lines.append("")

    # 6. Variants
    lv = brief.get("language_variants") or {}
    lines.append("## 5. Warianty jezykowe")
    if lv.get("named"):
        lines.append(f"**Pelna nazwa:** {lv['named']}")
    if lv.get("nominal"):
        lines.append(f"**Opisy zastepcze:** {lv['nominal']}")
    if lv.get("pronominal"):
        lines.append(f"**Zaimki:** {lv['pronominal']}")
    if lv.get("periphrases"):
        lines.append(f"**Peryfrazy:** {lv['periphrases']}")
    if lv.get("colloquial"):
        lines.append(f"**Warianty potoczne:** {lv['colloquial']}")
    if lv.get("formal"):
        lines.append(f"**Warianty formalne:** {lv['formal']}")
    if lv.get("rotation_pattern"):
        lines.append(f"**Wzorzec rotacji:** {lv['rotation_pattern']}")
    lines.append("")

    # 7. Keyphrases
    kp = brief.get("keyphrases") or []
    if kp:
        lines.append("## 6. Frazy kluczowe")
        lines.append("| Fraza | Zakres | Priorytet |")
        lines.append("|-------|--------|-----------|")
        for p in kp:
            lines.append(f"| {p['phrase']} | {p['freq_range']}× | {p['priority']} |")
        lines.append("")

    # 8. Hard facts
    hf = brief.get("hard_facts") or []
    if hf:
        lines.append("## 7. Fakty i dane")
        for f in hf:
            cat = f" ({f['category']})" if f.get("category") else ""
            lines.append(f"- {f['value']}{cat}")
        lines.append("")

    # 9. Relations
    rel = brief.get("relations") or {}
    lines.append("## 8. Relacje i mechanizmy")
    if rel.get("causal_chains"):
        lines.append("**Łańcuchy przyczynowo-skutkowe:**")
        for c in rel["causal_chains"]:
            lines.append(f"- {c['cause']} → {c['effect']}")
    if rel.get("spo_triples"):
        lines.append("**Fakty do opisania (SPO):**")
        for t in rel["spo_triples"]:
            lines.append(f"- {t['subject']} → {t['predicate']} → {t['object']}")
    lines.append("")

    # 10. Style
    style = brief.get("style") or {}
    lines.append("## 9. Styl i reguły")
    lines.append("- Naturalny, publicystyczny polski")
    lines.append('- Mow do czytelnika: "mozesz", "pamietaj", "jesli"')
    lines.append("- Średnia długość zdania: 11-15 słów")
    lines.append("- Aktywna strona czasownika")
    if style.get("banned_phrases"):
        lines.append(f"- **Zakazane frazy:** {style['banned_phrases']}")
    if style.get("cooccurrence_pairs"):
        lines.append(f"- **Pary tematyczne:** {style['cooccurrence_pairs']}")
    if style.get("ymyl_context"):
        lines.append(f"- **YMYL:** {style['ymyl_context'][:200]}")

    return "\n".join(lines)


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    import re
    m = re.search(r'https?://(?:www\.)?([^/]+)', url)
    return m.group(1) if m else url[:30]


def _format_entity_list(items: list) -> list:
    """Format entity list to simple strings."""
    result = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            text = item.get("display_text") or item.get("text") or item.get("entity") or ""
            if text:
                result.append(text)
    return result[:10]


def _format_entity_list_with_context(items: list, enriched_lookup: dict) -> list:
    """Format entity list with per-entity coverage context."""
    result = []
    for item in items:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = item.get("display_text") or item.get("text") or item.get("entity") or ""
        else:
            continue
        if not text:
            continue
        ctx = enriched_lookup.get(text.lower(), {})
        coverage = ctx.get("coverage", "")
        result.append({"text": text, "coverage": coverage})
    return result[:10]
