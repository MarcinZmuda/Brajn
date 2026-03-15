"""
Brief Compiler — konwertuje surowe dane S1 na brief w naturalnym języku.

Tu żyje CAŁA inteligencja interpretacji danych. Prompt pisarza pozostaje prosty i czysty.

S1 data (JSON, encje, n-gramy, triplety)
    ↓
brief_compiler
Brief (naturalny polski tekst, ~2000 słów)
    ↓
prompt pisarza
Artykuł
"""

import json
import re
from typing import Dict, List, Optional


def compile_brief(
    s1_data: dict,
    variables: dict,
    h2_plan: list,
    faq_plan: list,
    h1: str,
    search_variants: dict,
    ymyl_class: str,
    ymyl_context: str,
) -> str:
    """
    Compile all S1 data into a single natural-language brief.
    Returns a string ready to paste into WRITER_USER prompt.
    """
    keyword = variables.get("HASLO_GLOWNE", "")
    target_length = int(variables.get("DLUGOSC_CEL", 800) or 800)
    intro_length = int(variables.get("DLUGOSC_INTRO", 80) or 80)

    sections = []

    # -- 1. Naglowek --
    sections.append(f"TEMAT: {keyword}")
    sections.append(f"DLUGOSC: okolo {target_length} slow")
    sections.append(f"FRAZA GLOWNA: {keyword}")
    sections.append(
        f"Wplataj fraze glowna naturalnie, max 2x na sekcje. "
        f"W pozostalych zdaniach uzywaj wariantow ponizej."
    )
    sections.append("")

    # -- 2. Warianty --
    sections.append("WARIANTY FRAZY (uzywaj zamiennie):")
    named = search_variants.get("named_forms", [keyword])
    if isinstance(named, str):
        named = [named]
    nominal = search_variants.get("nominal_forms", [])
    pronominal = search_variants.get("pronominal_cues", [])
    peryfrazy = search_variants.get("peryfrazy", [])

    # Also pull from mention_forms if present
    mf = search_variants.get("mention_forms", {})
    if mf:
        if mf.get("named") and not named:
            named = [mf["named"]] if isinstance(mf["named"], str) else mf["named"]
        if mf.get("nominal") and not nominal:
            nominal = mf["nominal"]
        if mf.get("pronominal") and not pronominal:
            pronominal = mf["pronominal"]

    if named:
        sections.append(f"  Pelna nazwa: {', '.join(str(n) for n in named)}")
    if nominal:
        sections.append(f"  Opisy zastepcze (w srodku akapitow): {', '.join(str(n) for n in nominal)}")
    if pronominal:
        sections.append(f"  Zaimki (po pelnej nazwie): {', '.join(str(p) for p in pronominal)}")
    if peryfrazy:
        sections.append(f"  Peryfrazy: {', '.join(str(p) for p in peryfrazy[:5])}")
    sections.append(
        f"  Wzorzec: pelna nazwa -> opis -> zaimek -> (nowy akapit = znow pelna nazwa)"
    )
    sections.append("")

    # -- 3. H1 --
    sections.append(f"H1: {h1}")
    sections.append("")

    # -- 4. Intro --
    sections.append(f"INTRO (~{intro_length} slow):")
    sections.append(_build_intro_instructions(keyword, s1_data, variables))
    sections.append("")

    # -- 5. Sekcje H2 --
    entity_seo = s1_data.get("entity_seo") or {}
    hard_facts = variables.get("_hard_facts", [])
    causal = s1_data.get("causal_triplets", {})
    fact_triples = entity_seo.get("factographic_triples", [])

    covered_facts = set()  # Track what's already been assigned

    for i, h2 in enumerate(h2_plan):
        section_length = (target_length - intro_length) // max(len(h2_plan), 1)

        sections.append("---")
        sections.append(f"SEKCJA {i+1}: {h2}")
        sections.append(f"Dlugosc: ~{section_length} slow")

        # Fakty dla tej sekcji
        section_facts = _find_relevant_facts(h2, hard_facts, fact_triples, covered_facts)
        if section_facts:
            sections.append("Fakty do uzycia (TYLKO te, nie wymyslaj):")
            for fact in section_facts:
                sections.append(f"  - {fact}")
                covered_facts.add(fact)

        # Relacje kauzalne
        section_causal = _find_relevant_causal(h2, causal, keyword)
        if section_causal:
            sections.append("Wyjasnij mechanizmy (DLACZEGO -> CO -> EFEKT):")
            for rel in section_causal:
                sections.append(f"  - {rel}")

        # Co-occurrence pairs
        cooccurrence = entity_seo.get("entity_cooccurrence", [])
        section_pairs = _find_relevant_cooccurrence(h2, cooccurrence)
        if section_pairs:
            sections.append("Wspomnij RAZEM w jednym akapicie:")
            for pair in section_pairs:
                sections.append(f"  - {pair}")

        # Co NIE powtarzac
        if i > 0 and covered_facts:
            sections.append("Juz opisane wczesniej (nie powtarzaj):")
            recent = list(covered_facts)[-5:]
            for cf in recent:
                sections.append(f"  - {cf}")

        # Przejscie do nastepnej sekcji
        if i < len(h2_plan) - 1:
            sections.append(f"Zakoncz zdaniem prowadzacym do sekcji: {h2_plan[i+1]}")
        else:
            sections.append("Zakoncz zdaniem prowadzacym do FAQ.")

        sections.append("")

    # -- 6. FAQ --
    sections.append("---")
    sections.append(f"NAJCZESCIEJ ZADAWANE PYTANIA O {keyword.upper()}")
    sections.append("(przed pytaniami dodaj naglowek H2 z ta fraza)")
    sections.append("Kazde pytanie jako osobny ## naglowek. Odpowiedz: 2-4 zdania, konkretnie.")

    paa_unanswered = variables.get("_paa_unanswered", [])
    for q in faq_plan:
        priority = "PRIORYTET - nikt w SERP nie odpowiada" if q in paa_unanswered else ""
        sections.append(f"  - {q} {priority}")
    sections.append("")

    # -- 7. Disclaimer --
    from src.article_pipeline.prompts import DISCLAIMERS
    if ymyl_class in DISCLAIMERS:
        sections.append("DISCLAIMER (dodaj na koncu po ---):")
        sections.append(f"  {DISCLAIMERS[ymyl_class]}")
        sections.append("")

    # -- 8. YMYL context --
    if ymyl_context and len(ymyl_context) > 20:
        sections.append("KONTEKST PRAWNY/MEDYCZNY:")
        for line in ymyl_context.split("\n"):
            line = line.strip()
            if line and any(
                kw in line.lower()
                for kw in [
                    "art.",
                    "§",
                    "kodeks",
                    "ustaw",
                    "rozporz",
                    "przeciwwsk",
                    "bezpiecz",
                    "zagroz",
                    "cytat",
                    "zrodlo",
                ]
            ):
                sections.append(f"  {line[:200]}")
        sections.append("")

    # -- 9. Frazy kluczowe (uproszczone) --
    ngrams = variables.get("_ngrams", [])
    important_phrases = [
        ng.get("ngram", "")
        for ng in ngrams[:15]
        if isinstance(ng, dict) and ng.get("ngram") and len(ng.get("ngram", "")) > 3
    ]
    if important_phrases:
        sections.append("FRAZY KLUCZOWE (wplec naturalnie w tekst, kazda max 2-3x):")
        sections.append(f"  {', '.join(important_phrases)}")
        sections.append("")

    # -- 10. Styl --
    sections.append(
        "STYL: publicystyczny, zdania 11-15 slow, mow do czytelnika, aktywna strona."
    )
    sections.append(
        'Unikaj: "warto zaznaczyc", "nalezy podkreslic", "co wiecej", "ponadto".'
    )

    return "\n".join(sections)


def build_example_paragraph(
    keyword: str,
    hard_facts: list,
    ymyl_class: str,
    causal_data=None,
    entity_seo: dict = None,
) -> str:
    """
    Build example paragraph from REAL S1 data of this article.
    Falls back to style template if no data available.
    """
    # Extract first hard fact
    fact_str = ""
    if hard_facts:
        f = hard_facts[0]
        fact_str = f.get("value", str(f)) if isinstance(f, dict) else str(f)

    # Extract first causal relation
    cause, effect = "", ""
    if causal_data:
        if isinstance(causal_data, dict):
            singles = causal_data.get("singles") or causal_data.get("relations") or []
        elif isinstance(causal_data, list):
            singles = causal_data
        else:
            singles = []
        if singles and isinstance(singles[0], dict):
            cause = singles[0].get("cause", "")
            effect = singles[0].get("effect", "")

    # Full data — fact + causal relation
    if fact_str and cause and effect:
        return (
            f'Ponizej przyklad akapitu w oczekiwanym stylu —\n'
            f'konkretne fakty z briefu, aktywna strona, przejscie do nastepnej sekcji:\n\n'
            f'Temat: \u201e{keyword}\u201d\n'
            f'Uzyty fakt: {fact_str}\n'
            f'Uzyta relacja: {cause} \u2192 {effect}\n\n'
            f'Dobry akapit zawiera:\n'
            f'  Zdanie 1: konkretny fakt z briefu (liczba, prog, wartosc)\n'
            f'  Zdanie 2: mechanizm — DLACZEGO tak jest (spojnik: dlatego/poniewaz)\n'
            f'  Zdanie 3: konsekwencja dla czytelnika\n'
            f'  Zdanie 4: przejscie do tematu nastepnej sekcji'
        )

    # Partial data — fact only
    if fact_str:
        return (
            f'Ponizej przyklad akapitu w oczekiwanym stylu:\n\n'
            f'Temat: \u201e{keyword}\u201d\n'
            f'Uzyty fakt: {fact_str}\n\n'
            f'Dobry akapit zawiera:\n'
            f'  Zdanie 1: konkretny fakt z briefu\n'
            f'  Zdanie 2: wyjasnienie mechanizmu — DLACZEGO tak jest\n'
            f'  Zdanie 3: konsekwencja dla czytelnika\n'
            f'  Zdanie 4: przejscie do tematu nastepnej sekcji'
        )

    # Fallback — style template without specific data
    return (
        f'Wzorzec dobrego akapitu na temat \u201e{keyword}\u201d:\n\n'
        f'  Zdanie 1: konkretny fakt z briefu (liczba, prog, wartosc).\n'
        f'  Zdanie 2: mechanizm — DLACZEGO tak jest.\n'
        f'  Zdanie 3: konsekwencja dla czytelnika.\n'
        f'  Zdanie 4: przejscie do tematu nastepnej sekcji.\n\n'
        f'Kazde zdanie wnosi nowa informacje. Bez ogolnikow.'
    )


# ==============================================================
# Helper functions
# ==============================================================


def _build_intro_instructions(
    keyword: str, s1_data: dict, variables: dict
) -> str:
    """Build intro writing instructions from AI Overview / Featured Snippet."""
    parts = []

    ai_overview = variables.get("AI_OVERVIEW_TEXT", "")
    featured = variables.get("FEATURED_SNIPPET_TEXT", "")

    if ai_overview and len(ai_overview) > 30:
        parts.append(
            "Google wyswietla taka odpowiedz (pokryj te same informacje swoimi slowami):"
        )
        parts.append(f'  "{ai_overview[:300]}"')
    elif featured and len(featured) > 30:
        parts.append(
            "Google wyswietla taki snippet (odpowiedz na te sama intencje):"
        )
        parts.append(f'  "{featured[:300]}"')

    # First paragraph entities
    first_entities = variables.get("ENCJE_PIERWSZY_AKAPIT", "")
    if first_entities and first_entities != "[]":
        try:
            ents = (
                json.loads(first_entities)
                if isinstance(first_entities, str)
                else first_entities
            )
            if ents:
                parts.append(
                    f"W intro wspomnij o: {', '.join(str(e) for e in ents[:4])}"
                )
        except Exception:
            pass

    parts.append(
        f'Pierwsze zdanie zawiera fraze "{keyword}" (ale NIE jako podmiot w mianowniku).'
    )
    parts.append("Kazde zdanie intro wnosi konkretna informacje - bez ogolnikow.")

    hard_facts = variables.get("_hard_facts", [])
    if hard_facts:
        top_facts = [
            hf.get("value", str(hf)) if isinstance(hf, dict) else str(hf)
            for hf in hard_facts[:3]
        ]
        parts.append(f"Kluczowe fakty do wplecenia: {', '.join(top_facts)}")

    return "\n".join(parts)


def _find_relevant_facts(
    h2_title: str,
    hard_facts: list,
    fact_triples: list,
    already_covered: set,
) -> list:
    """Find hard facts and factographic triples relevant to this H2 section."""
    h2_lower = h2_title.lower()
    results = []

    # Hard facts
    for hf in hard_facts:
        if isinstance(hf, dict):
            val = hf.get("value", "")
            snippet = hf.get("source_snippet", "")
            context = (val + " " + snippet).lower()
        else:
            val = str(hf)
            context = val.lower()

        if val in already_covered:
            continue

        # Relevance: any word from H2 title appears in fact context
        h2_words = [w for w in h2_lower.split() if len(w) > 3]
        if any(w in context for w in h2_words):
            results.append(val)

    # Factographic triples (SPO type)
    for t in fact_triples:
        if not isinstance(t, dict):
            continue
        subj = t.get("subject", "")
        pred = t.get("predicate", "")
        obj = t.get("object", "")
        full = f"{subj} {pred} {obj}".lower()

        if full in str(already_covered):
            continue

        h2_words = [w for w in h2_lower.split() if len(w) > 3]
        if any(w in full for w in h2_words):
            fact_str = f"{subj} -> {pred} -> {obj}"
            if t.get("triplet_type") == "eav":
                fact_str = f"{subj}: {obj}"
            results.append(fact_str)

    return results[:6]


def _find_relevant_causal(
    h2_title: str, causal_data: dict, keyword: str
) -> list:
    """Find causal relations relevant to this H2 section."""
    results = []
    h2_lower = h2_title.lower()

    for key in ("chains", "singles", "relations"):
        rels = causal_data.get(key, [])
        if not isinstance(rels, list):
            continue
        for rel in rels:
            if not isinstance(rel, dict):
                continue
            cause = rel.get("cause", "")
            effect = rel.get("effect", "")
            full = f"{cause} {effect}".lower()

            h2_words = [w for w in h2_lower.split() if len(w) > 3]
            if any(w in full for w in h2_words):
                results.append(f"{cause} -> {effect}")

    return results[:4]


def _find_relevant_cooccurrence(h2_title: str, cooccurrence: list) -> list:
    """Find co-occurrence pairs relevant to this H2 section."""
    h2_lower = h2_title.lower()
    h2_words = [w for w in h2_lower.split() if len(w) > 3]
    results = []

    for pair in cooccurrence:
        if not isinstance(pair, dict):
            continue
        a = pair.get("entity_a", "").lower()
        b = pair.get("entity_b", "").lower()
        if any(w in a or w in b for w in h2_words):
            results.append(f'"{pair.get("entity_a", "")}" + "{pair.get("entity_b", "")}"')

    return results[:3]
