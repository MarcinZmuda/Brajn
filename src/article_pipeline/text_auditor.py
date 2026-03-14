"""
===============================================================================
TEXT AUDITOR — Audyt dowolnego tekstu vs. analiza SERP
===============================================================================
Pipeline: S1 → Quality Gate → Variables → Compliance → Gap Analysis → Rekom.
Yields SSE events for progress tracking.
Koszt: ~$0.004-0.006 per audyt (Haiku only, no Sonnet).
===============================================================================
"""

import json
import re
from typing import Dict, Generator


def run_text_audit(
    main_keyword: str,
    article_text: str,
) -> Generator[dict, None, None]:
    """Full text audit pipeline. Yields events for SSE streaming."""

    # ── Step 1: S1 Analysis ──
    yield {"event": "audit_step", "data": {
        "step": 1, "total": 6, "label": "Analiza SERP i konkurencji"
    }}

    from src.s1.analysis import run_s1_analysis
    s1_data = run_s1_analysis(main_keyword=main_keyword)

    if "error" in s1_data:
        yield {"event": "error", "data": {"message": s1_data["error"]}}
        return

    yield {"event": "audit_step_done", "data": {
        "step": 1,
        "sources": (s1_data.get("summary") or {}).get("total_sources", 0),
        "entities": (s1_data.get("summary") or {}).get("entities_found", 0),
        "ngrams": len(s1_data.get("ngrams") or []),
    }}

    # ── Step 2: Quality Gate ──
    yield {"event": "audit_step", "data": {
        "step": 2, "total": 6, "label": "Filtracja danych S1"
    }}

    try:
        from src.s1.ngram_quality_gate import run_quality_gate
        qg = run_quality_gate(
            ngrams=s1_data.get("ngrams") or [],
            extended_terms=s1_data.get("extended_terms") or [],
            entities=[],
            triples=[],
            main_keyword=main_keyword,
            use_llm=True,
        )
        s1_data["ngrams"] = qg["ngrams"]
        s1_data["extended_terms"] = qg["extended_terms"]
    except Exception as e:
        print(f"[AUDIT] Quality gate skipped: {e}")

    yield {"event": "audit_step_done", "data": {
        "step": 2,
        "ngrams_clean": len(s1_data.get("ngrams") or []),
    }}

    # ── Step 3: Build variables ──
    yield {"event": "audit_step", "data": {
        "step": 3, "total": 6, "label": "Przygotowanie danych referencyjnych"
    }}

    from src.article_pipeline.variables import extract_global_variables
    variables = extract_global_variables(s1_data)

    try:
        from src.article_pipeline.search_variants import generate_search_variants
        ngrams = variables.get("_ngrams") or []
        secondary = [ng.get("ngram", "") for ng in ngrams[:10]]
        variants = generate_search_variants(main_keyword, secondary)
        s1_data["search_variants"] = variants
        s1_data["mention_forms"] = {
            "named": variants.get("named_forms", [main_keyword]),
            "nominal": variants.get("nominal_forms", []),
            "pronominal": variants.get("pronominal_cues", []),
        }
    except Exception as e:
        print(f"[AUDIT] Search variants skipped: {e}")

    yield {"event": "audit_step_done", "data": {"step": 3}}

    # ── Step 4: Entity SEO Compliance ──
    yield {"event": "audit_step", "data": {
        "step": 4, "total": 6, "label": "Analiza tekstu vs. dane SERP"
    }}

    ngram_coverage = _compute_ngram_coverage(article_text, s1_data)

    try:
        from src.article_pipeline.entity_seo_compliance import run_entity_seo_compliance
        nlp = None
        try:
            from src.common.nlp_singleton import get_nlp
            nlp = get_nlp()
        except Exception:
            pass

        compliance = run_entity_seo_compliance(
            article_text=article_text,
            s1_data=s1_data,
            ngram_coverage=ngram_coverage,
            nlp=nlp,
        )
    except Exception as e:
        print(f"[AUDIT] Compliance error: {e}")
        compliance = {"overall_score": 0, "error": str(e)}

    yield {"event": "audit_step_done", "data": {
        "step": 4,
        "score": compliance.get("overall_score", 0),
    }}

    # ── Step 5: Gap Analysis + Recommendations ──
    yield {"event": "audit_step", "data": {
        "step": 5, "total": 6, "label": "Generowanie rekomendacji"
    }}

    gaps = _analyze_gaps(article_text, s1_data, variables, compliance)
    recommendations = _generate_recommendations(compliance, gaps)

    report = _build_audit_report(
        article_text=article_text,
        main_keyword=main_keyword,
        s1_data=s1_data,
        variables=variables,
        compliance=compliance,
        ngram_coverage=ngram_coverage,
        gaps=gaps,
        recommendations=recommendations,
    )

    yield {"event": "audit_step_done", "data": {"step": 5}}

    # ── Step 6: Korekta redakcyjna ──
    yield {"event": "audit_step", "data": {
        "step": 6, "total": 6, "label": "Korekta redakcyjna"
    }}

    proofread = None
    try:
        from src.article_pipeline.editorial_proofreader import proofread_article
        proofread = proofread_article(
            article_text=article_text,
            s1_data=s1_data,
            variables=variables,
            auto_fix=False,
        )
    except Exception as e:
        print(f"[AUDIT] Proofreading error: {e}")

    if proofread:
        report["proofreading"] = proofread

    yield {"event": "audit_step_done", "data": {"step": 6}}
    yield {"event": "audit_complete", "data": report}


# ── N-gram coverage ──────────────────────────────────────────

def _compute_ngram_coverage(article_text: str, s1_data: dict) -> dict:
    """Compute n-gram coverage of article vs S1 data."""
    article = article_text.lower()
    ngrams = (s1_data.get("ngrams") or []) + (s1_data.get("extended_terms") or [])

    missing, under, over, ok = [], [], [], []

    for ng in ngrams:
        term = (ng.get("ngram") or ng.get("text") or "").lower().strip()
        if not term or len(term) < 3:
            continue
        freq_min = ng.get("freq_min", 1)
        freq_max = ng.get("freq_max", 99)
        weight = ng.get("weight", 0)
        actual = len(re.findall(re.escape(term), article))

        entry = {
            "term": ng.get("ngram") or ng.get("text"),
            "actual": actual, "min": freq_min, "max": freq_max,
            "weight": round(weight, 3),
        }

        if actual == 0 and freq_min >= 1:
            missing.append(entry)
        elif 0 < actual < freq_min:
            under.append(entry)
        elif freq_max and actual > freq_max:
            over.append(entry)
        else:
            ok.append(entry)

    total = len(missing) + len(under) + len(over) + len(ok)
    return {
        "missing": sorted(missing, key=lambda x: x["weight"], reverse=True),
        "under": sorted(under, key=lambda x: x["min"] - x["actual"], reverse=True),
        "over": sorted(over, key=lambda x: x["actual"] - x["max"], reverse=True),
        "ok": ok,
        "stats": {
            "total": total,
            "missing": len(missing),
            "under": len(under),
            "over": len(over),
            "ok": len(ok),
            "coverage_pct": round(len(ok) / max(total, 1) * 100),
        },
    }


# ── Gap analysis ─────────────────────────────────────────────

def _analyze_gaps(
    article_text: str,
    s1_data: dict,
    variables: dict,
    compliance: dict,
) -> dict:
    """Compare what S1 says should be in the article vs what IS there."""
    article_lower = article_text.lower()

    # 1. Missing entities
    must_cover = variables.get("_must_cover") or []
    entity_gaps = []
    for entity in must_cover:
        name = entity if isinstance(entity, str) else (entity.get("text", "") if isinstance(entity, dict) else "")
        if not name:
            continue
        found = name.lower() in article_lower
        if not found:
            stem = name.lower()[:max(5, int(len(name) * 0.6))]
            found = stem in article_lower
        if not found:
            entity_gaps.append({
                "entity": name,
                "type": "missing_entity",
                "recommendation": f'Wplec temat "{name}" w artykul -- konkurencja o nim pisze.',
            })

    # 2. Missing PAA questions
    paa_unanswered = variables.get("_paa_unanswered") or []
    paa_gaps = []
    for q in paa_unanswered:
        key_words = [w for w in q.lower().split() if len(w) > 4]
        covered = sum(1 for w in key_words if w in article_lower)
        if covered < len(key_words) * 0.5:
            paa_gaps.append({
                "question": q,
                "type": "unanswered_paa",
                "recommendation": f'Dodaj odpowiedz na pytanie: "{q}" -- Google pokazuje je w People Also Ask.',
            })

    # 3. Missing causal relations
    causal = compliance.get("causal_chains") or {}
    causal_gaps = []
    for c in (causal.get("chains") or []):
        if not c.get("covered"):
            causal_gaps.append({
                "chain": c.get("chain", ""),
                "type": "missing_mechanism",
                "recommendation": f'Wyjasnij mechanizm: {c.get("chain", "")} -- opisz DLACZEGO, nie tylko CO.',
            })

    # 4. Structural gaps
    structural_gaps = []

    h1_match = re.search(r'^#\s+.+', article_text, re.MULTILINE)
    if not h1_match and '<h1' not in article_text.lower():
        structural_gaps.append({
            "type": "missing_h1",
            "recommendation": "Artykul nie ma naglowka H1. Dodaj tytul z fraza glowna.",
        })

    main_kw = variables.get("HASLO_GLOWNE", "").lower()
    first_200 = " ".join(article_text.split()[:200]).lower()
    if main_kw and main_kw not in first_200:
        structural_gaps.append({
            "type": "keyword_not_in_intro",
            "recommendation": f'Fraza "{main_kw}" nie pojawia sie w pierwszych 200 slowach. Wplec ja w intro.',
        })

    target = int(variables.get("DLUGOSC_CEL", 0) or 0)
    actual_words = len(article_text.split())
    if target > 0 and actual_words < target * 0.6:
        structural_gaps.append({
            "type": "too_short",
            "recommendation": f'Artykul ma {actual_words} slow, konkurencja srednio {target}. Rozwaz rozszerzenie o {target - actual_words} slow.',
        })
    elif target > 0 and actual_words > target * 1.5:
        structural_gaps.append({
            "type": "too_long",
            "recommendation": f'Artykul ma {actual_words} slow, konkurencja srednio {target}. Rozwaz skrocenie.',
        })

    # 5. Mention variety
    mention_gaps = []
    mv = compliance.get("mention_variety") or {}
    if mv.get("has_data"):
        named_pct = (mv.get("named") or {}).get("pct", 100)
        if named_pct > 75:
            mention_gaps.append({
                "type": "low_mention_variety",
                "recommendation": f'Fraza glowna pojawia sie w pelnej formie w {named_pct:.0f}% przypadkow. Uzyj wariantow opisowych i zaimkow.',
            })

    return {
        "entity_gaps": entity_gaps,
        "paa_gaps": paa_gaps,
        "causal_gaps": causal_gaps[:5],
        "structural_gaps": structural_gaps,
        "mention_gaps": mention_gaps,
        "total_gaps": (len(entity_gaps) + len(paa_gaps) + min(len(causal_gaps), 5) +
                       len(structural_gaps) + len(mention_gaps)),
    }


# ── Recommendations ──────────────────────────────────────────

def _generate_recommendations(compliance: dict, gaps: dict) -> list:
    """Generate prioritized action list from compliance + gaps."""
    actions = []
    scores = compliance.get("component_scores") or {}

    if scores.get("entity_salience", 100) < 60:
        actions.append({
            "priority": "high",
            "area": "Entity Salience",
            "action": "Encja glowna ma slaba prominencje. Umiesc ja w H1, pierwszym zdaniu i minimum 2 naglowkach H2.",
        })

    if scores.get("spo_triples", 100) < 40:
        actions.append({
            "priority": "high",
            "area": "Trojki faktograficzne",
            "action": "Artykul nie opisuje kluczowych faktow. Kazde wazne zdanie: KTO/CO -> ROBI -> CO/JAK.",
        })

    if scores.get("centerpiece", 100) < 75:
        actions.append({
            "priority": "high",
            "area": "Blok deklaracji tematu",
            "action": "Pierwsze 100 slow nie deklaruje jasno tematu. Zdefiniuj go w pierwszym zdaniu.",
        })

    if scores.get("causal_chains", 100) < 60:
        actions.append({
            "priority": "medium",
            "area": "Lancuchy przyczynowe",
            "action": "Artykul stwierdza fakty ale nie wyjasnia DLACZEGO. Dodaj spojniki: dlatego, poniewaz, w efekcie.",
        })

    if scores.get("mention_variety", 100) < 40:
        actions.append({
            "priority": "medium",
            "area": "Warianty wzmianek",
            "action": "Fraza glowna powtarza sie w identycznej formie. Rotuj: pelna nazwa -> opis zastepczy -> zaimek.",
        })

    if scores.get("ngram_budget", 100) < 50:
        actions.append({
            "priority": "medium",
            "area": "Pokrycie fraz kluczowych",
            "action": "Brakuje waznych fraz z SERP. Sprawdz liste brakujacych n-gramow i wplec je naturalnie.",
        })

    for gap in gaps.get("structural_gaps") or []:
        actions.append({
            "priority": "high" if gap["type"] in ("missing_h1", "keyword_not_in_intro") else "medium",
            "area": "Struktura",
            "action": gap["recommendation"],
        })

    for gap in (gaps.get("paa_gaps") or [])[:3]:
        actions.append({
            "priority": "high",
            "area": "PAA bez odpowiedzi",
            "action": gap["recommendation"],
        })

    for gap in (gaps.get("entity_gaps") or [])[:5]:
        actions.append({
            "priority": "medium",
            "area": "Brakujacy temat",
            "action": gap["recommendation"],
        })

    priority_order = {"high": 0, "medium": 1, "low": 2}
    actions.sort(key=lambda a: priority_order.get(a["priority"], 2))
    return actions


# ── Report builder ────────────────────────────────────────────

def _build_audit_report(
    article_text: str,
    main_keyword: str,
    s1_data: dict,
    variables: dict,
    compliance: dict,
    ngram_coverage: dict,
    gaps: dict,
    recommendations: list,
) -> dict:
    """Build complete audit report for panel display."""
    article_words = len(article_text.split())
    target_words = int(variables.get("DLUGOSC_CEL", 0) or 0)

    h2_count = len(re.findall(r'^##\s+', article_text, re.MULTILINE))
    if h2_count == 0:
        h2_count = len(re.findall(r'<h2', article_text, re.IGNORECASE))

    # Generate brief for the Brief tab
    brief_data = None
    try:
        from src.article_pipeline.brief_generator import generate_brief
        brief_data = generate_brief(
            s1_data=s1_data,
            variables=variables,
        )
    except Exception as e:
        print(f"[AUDIT] Brief generation skipped: {e}")

    return {
        "overall_score": compliance.get("overall_score", 0),
        "component_scores": compliance.get("component_scores") or {},
        "article_meta": {
            "word_count": article_words,
            "target_word_count": target_words,
            "word_count_ratio": round(article_words / max(target_words, 1) * 100),
            "h2_count": h2_count,
            "main_keyword": main_keyword,
        },
        "s1_summary": {
            "sources_analyzed": (s1_data.get("summary") or {}).get("total_sources", 0),
            "entities_found": (s1_data.get("summary") or {}).get("entities_found", 0),
            "ngrams_found": len(s1_data.get("ngrams") or []),
            "paa_count": (s1_data.get("summary") or {}).get("paa_count", 0),
        },
        "entity_salience": compliance.get("entity_salience") or {},
        "spo_triples": compliance.get("spo_triples") or {},
        "causal_chains": compliance.get("causal_chains") or {},
        "mention_variety": compliance.get("mention_variety") or {},
        "centerpiece": compliance.get("centerpiece") or {},
        "ngram_coverage": ngram_coverage,
        "gaps": gaps,
        "recommendations": recommendations,
        "brief": brief_data,
        "s1_data": s1_data,
        "variables": {k: v for k, v in variables.items() if not k.startswith("_")},
    }
