"""
Structural Rewriter — Entity SEO structure fixes.

Uses Sonnet to rewrite specific structural issues:
- Intro → Centerpiece Block (entity as subject + definition)
- First sentence of each H2 → entity as grammatical subject
- Mention rotation → inject nominal/pronominal variants
- Paragraph structure → SPO+ pattern

Cost: ~$0.03 per article (single Sonnet call)
Runs AFTER writer, BEFORE compliance check.
"""

import re
from typing import Tuple


_REWRITER_SYSTEM = """Jestes redaktorem strukturalnym polskiego tekstu SEO.

Dostajesz artykul i brief. Twoim zadaniem jest poprawic WYLACZNIE strukture
Entity SEO — nie zmieniaj faktow, nie dodawaj nowych informacji, nie usuwaj tresci.

ZASADY NAPRAWY:

1. INTRO (Centerpiece Block — pierwsze 3-4 zdania przed pierwszym H2):
   - Zdanie 1: [ENCJA GLOWNA] to [DEFINICJA]. Encja MUSI byc podmiotem gramatycznym.
   - Zdanie 2: Wymien 2-3 encje wspierajace i ich zwiazek z tematem.
   - Zdanie 3: Zapowiedz tresci artykulu.
   - ZAKAZANE poczatki: "Pytanie o...", "W tym artykule...", "Coraz czesciej..."

2. PIERWSZE ZDANIE KAZDEJ SEKCJI H2:
   - Encja glowna lub jej wariant nominalny MUSI byc podmiotem gramatycznym.
   - Strona CZYNNA (nie bierna).
   - Jesli zdanie zaczyna sie od "Podstawa...", "Kwestia...", "Pytanie..." — przepisz.

3. ROTACJA WZMIANEK:
   - W kazdej sekcji H2 uzyj pelnej nazwy encji MAX 2 razy.
   - W pozostalych zdaniach uzyj wariantow nominalnych i pronominalnych z briefu.
   - Nie zmieniaj sensu zdan — tylko podmien forme wzmianki.

4. ZDANIA PRZEJSCIOWE (bridge sentences):
   - Jesli ostatnie zdanie sekcji DOSLOWNIE powtarza tytul nastepnej sekcji H2 — przepisz
     tak zeby zapowiadalo temat ale innymi slowami.

WAZNE:
- Zwroc CALY artykul z poprawkami (nie tylko zmienione fragmenty).
- NIE zmieniaj naglowkow H1/H2/H3.
- NIE usuwaj ani nie dodawaj akapitow.
- NIE zmieniaj faktow ani danych liczbowych.
- Zachowaj identyczna dlugosc artykulu (±5%)."""


_REWRITER_USER = """ENCJA GLOWNA: {main_entity}

WARIANTY NOMINALNE (uzywaj zamiennie z pelna nazwa):
{nominal_forms}

WARIANTY PRONOMINALNIE (zaimki zastepujace encje):
{pronominal_forms}

ENCJE WSPIERAJACE (wymien w intro):
{supporting_entities}

ARTYKUL DO POPRAWY:
{article_text}"""


def rewrite_structure(
    article_text: str,
    main_entity: str,
    nominal_forms: list = None,
    pronominal_forms: list = None,
    supporting_entities: list = None,
    llm_call=None,
) -> Tuple[str, dict]:
    """
    Rewrite article structure for Entity SEO compliance.

    Returns:
        (rewritten_text, stats_dict)
    """
    if not article_text or not main_entity:
        return article_text, {"skipped": True, "reason": "no_data"}

    # Check if structural issues exist before calling LLM
    issues = _detect_structural_issues(article_text, main_entity)
    if not issues:
        print("[REWRITER] No structural issues detected — skipping")
        return article_text, {"skipped": True, "reason": "no_issues", "checks": issues}

    print(f"[REWRITER] Found {len(issues)} structural issues: {issues}")

    # Build prompt
    nominal_str = "\n".join(f"- {f}" for f in (nominal_forms or [])) or "- (brak danych)"
    pronominal_str = "\n".join(f"- {f}" for f in (pronominal_forms or [])) or "- (brak danych)"
    supporting_str = "\n".join(f"- {e}" for e in (supporting_entities or [])[:5]) or "- (brak danych)"

    user_prompt = _REWRITER_USER.format(
        main_entity=main_entity,
        nominal_forms=nominal_str,
        pronominal_forms=pronominal_str,
        supporting_entities=supporting_str,
        article_text=article_text,
    )

    if llm_call is None:
        from src.common.llm import claude_call
        llm_call = claude_call

    try:
        response, usage = llm_call(
            system_prompt=_REWRITER_SYSTEM,
            user_prompt=user_prompt,
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            temperature=0.4,
        )

        rewritten = response.strip()

        # Sanity check: rewritten should be similar length
        orig_words = len(article_text.split())
        new_words = len(rewritten.split())
        ratio = new_words / max(orig_words, 1)

        if ratio < 0.7 or ratio > 1.3:
            print(f"[REWRITER] Length mismatch: {orig_words} → {new_words} ({ratio:.0%}). Keeping original.")
            return article_text, {"skipped": True, "reason": "length_mismatch",
                                  "original_words": orig_words, "rewritten_words": new_words}

        # Check H2 count preserved
        orig_h2 = len(re.findall(r'^##\s', article_text, re.MULTILINE))
        new_h2 = len(re.findall(r'^##\s', rewritten, re.MULTILINE))
        if orig_h2 != new_h2:
            print(f"[REWRITER] H2 count changed: {orig_h2} → {new_h2}. Keeping original.")
            return article_text, {"skipped": True, "reason": "h2_count_changed"}

        stats = {
            "skipped": False,
            "issues_found": issues,
            "original_words": orig_words,
            "rewritten_words": new_words,
            "usage": usage,
        }
        print(f"[REWRITER] Success: {orig_words} → {new_words} words, {len(issues)} issues addressed")
        return rewritten, stats

    except Exception as e:
        print(f"[REWRITER] Error: {e}")
        return article_text, {"skipped": True, "reason": f"error: {e}"}


def _detect_structural_issues(text: str, main_entity: str) -> list:
    """Quick detection of structural issues (no LLM needed)."""
    issues = []
    entity_lower = main_entity.lower()
    entity_stem = entity_lower.split()[0][:5] if entity_lower else ""

    # Get intro (before first H2)
    h2_match = re.search(r'^##\s', text, re.MULTILINE)
    intro = text[:h2_match.start()].strip() if h2_match else text[:500]
    intro_sentences = re.split(r'[.!?]+\s+', intro)

    # Issue 1: Intro starts with meta-pattern
    if intro_sentences:
        first = intro_sentences[0].lower().strip()
        bad_starts = ["pytanie o", "pytanie,", "w tym artykule", "coraz częściej",
                      "coraz wiecej", "temat ", "kwestia "]
        if any(first.startswith(bs) for bs in bad_starts):
            issues.append("intro_meta_pattern")

    # Issue 2: Entity not subject in first sentence
    if intro_sentences:
        first_words = intro_sentences[0].lower().split()[:3]
        first_chunk = " ".join(first_words)
        if entity_stem and entity_stem not in first_chunk:
            issues.append("entity_not_subject_intro")

    # Issue 3: Bridge sentences repeating H2 title
    sections = re.split(r'^(##\s+.+)$', text, flags=re.MULTILINE)
    for i in range(len(sections) - 2):
        section_text = sections[i].strip()
        next_h2 = sections[i + 1].strip() if sections[i + 1].strip().startswith("##") else ""
        if next_h2 and section_text:
            last_sentence = section_text.split(".")[-2] if "." in section_text else ""
            h2_title = next_h2.replace("##", "").strip().lower()
            if last_sentence and h2_title and h2_title[:20] in last_sentence.lower():
                issues.append("bridge_repeats_h2")
                break  # one is enough

    # Issue 4: No nominal/pronominal variety (all mentions = exact keyword)
    entity_exact_count = text.lower().count(entity_lower)
    if entity_exact_count > 8:
        issues.append("keyword_stuffing_suspected")

    return issues
