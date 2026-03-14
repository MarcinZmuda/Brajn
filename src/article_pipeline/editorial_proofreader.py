"""
===============================================================================
EDITORIAL PROOFREADER — Two-pass article correction
===============================================================================
Pass 1: Sonnet audit — finds ALL problems (duplicates, hallucinations, facts, language)
Pass 2: Autofix — applies safe corrections, rewrites duplicates via Haiku

Cost: ~$0.015-0.025 per article
===============================================================================
"""

import json
import re
from typing import Optional

from src.common.llm import claude_call


# ══════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════

def proofread_article(
    article_text: str,
    s1_data: dict,
    variables: dict,
    auto_fix: bool = True,
) -> dict:
    """
    Full proofreading pipeline.

    Args:
        article_text: Generated article (markdown)
        s1_data: Full S1 data dict
        variables: Template variables from extract_global_variables()
        auto_fix: If True, apply safe corrections automatically

    Returns:
        {
            "corrected_text": str,
            "applied": list of applied corrections,
            "flagged": list of issues for human review,
            "audit": raw audit result from Pass 1,
            "stats": summary counts,
        }
    """
    variables = variables or {}

    # ── Pass 1: Audyt (Sonnet) ──
    audit = _run_audit(article_text, s1_data, variables)

    if not audit:
        return {
            "corrected_text": article_text,
            "applied": [],
            "flagged": [],
            "audit": None,
            "stats": {"auto_fixed": 0, "flagged_for_review": 0,
                       "overall_quality": "unknown"},
        }

    if not auto_fix:
        return {
            "corrected_text": article_text,
            "applied": [],
            "flagged": _collect_all_issues(audit),
            "audit": audit,
            "stats": {
                "auto_fixed": 0,
                "flagged_for_review": _count_issues(audit),
                "overall_quality": audit.get("summary", {}).get("overall_quality", "?"),
            },
        }

    # ── Pass 2: Autofix ──
    result_text = article_text
    applied = []
    flagged = []

    # 2a. Korekty jezykowe -> str.replace()
    for corr in audit.get("corrections", []):
        original = corr.get("original", "")
        replacement = corr.get("replacement", "")

        if not original or not replacement:
            continue

        # Flagi specjalne -- nie autofix
        if replacement in ("__USUN__", "__PRZEREDAGUJ__"):
            flagged.append({
                "type": corr.get("type", "language"),
                "severity": corr.get("severity", "low"),
                "text": original,
                "reason": corr.get("reason", ""),
                "action": "Wymaga recznej interwencji copywritera",
            })
            continue

        # Bezpieczna podmiana -- tylko jesli exact match 1x
        count = result_text.count(original)
        if count == 1:
            result_text = result_text.replace(original, replacement, 1)
            applied.append({
                "original": original,
                "replacement": replacement,
                "reason": corr.get("reason", ""),
                "type": corr.get("type", "language"),
                "severity": corr.get("severity", "low"),
            })
        elif count == 0:
            flagged.append({
                "type": "match_error",
                "severity": "low",
                "text": original[:60],
                "reason": "Fragment nie znaleziony w tekscie -- pomijam",
                "action": "Sprawdz recznie",
            })
        else:
            flagged.append({
                "type": corr.get("type", "language"),
                "severity": corr.get("severity", "low"),
                "text": original[:60],
                "reason": f"Fragment pojawia sie {count}x -- niejednoznaczne, pomijam",
                "action": "Popraw recznie wlasciwe wystapienie",
            })

    # 2b. Halucynacje -> podmiana na suggestion
    for hall in audit.get("hallucinations", []):
        original = hall.get("text", "")
        suggestion = hall.get("suggestion", "")

        if not original:
            continue

        if suggestion and suggestion.upper() != "USUN" and result_text.count(original) == 1:
            result_text = result_text.replace(original, suggestion, 1)
            applied.append({
                "original": original,
                "replacement": suggestion,
                "reason": f"Halucynacja: {hall.get('reason', '')}",
                "type": "hallucination_fix",
                "severity": "high",
            })
        else:
            flagged.append({
                "type": "hallucination",
                "severity": "high",
                "text": original,
                "reason": hall.get("reason", ""),
                "action": suggestion if suggestion else "Usun lub zastap zweryfikowanym faktem",
            })

    # 2c. Duplikaty -> Haiku przepisuje jeden z pary
    main_keyword = variables.get("HASLO_GLOWNE", "")
    seo_phrases = _get_seo_phrases(variables)

    for dup in audit.get("duplicates", []):
        try:
            fix = _rewrite_duplicate(
                article_text=result_text,
                duplicate_info=dup,
                main_keyword=main_keyword,
                seo_phrases=seo_phrases,
            )
            if fix and fix.get("original") and fix.get("rewritten"):
                if result_text.count(fix["original"]) == 1:
                    result_text = result_text.replace(
                        fix["original"], fix["rewritten"], 1)
                    applied.append({
                        "original": fix["original"][:80] + ("..." if len(fix["original"]) > 80 else ""),
                        "replacement": fix["rewritten"][:80] + ("..." if len(fix["rewritten"]) > 80 else ""),
                        "reason": f"Duplikat z sekcja: {dup.get('section_a', '?')}",
                        "type": "duplicate_rewrite",
                        "severity": "high",
                    })
                else:
                    flagged.append({
                        "type": "duplicate",
                        "severity": "high",
                        "text": fix["original"][:80],
                        "reason": dup.get("recommendation", ""),
                        "action": "Przepisz recznie -- nie udalo sie automatycznie",
                    })
        except Exception as e:
            flagged.append({
                "type": "duplicate",
                "severity": "high",
                "text": dup.get("text_b", "")[:60],
                "reason": f"Blad autofix: {e}",
                "action": dup.get("recommendation", "Przepisz recznie"),
            })

    # 2d. Niespelnione obietnice -> ZAWSZE flaguj
    for promise in audit.get("unfulfilled_promises", []):
        flagged.append({
            "type": "unfulfilled_promise",
            "severity": "medium",
            "text": promise.get("h2", ""),
            "reason": f"Obiecuje: {promise.get('promise', '?')}. "
                      f"Dostarcza: {promise.get('reality', '?')}",
            "action": promise.get("recommendation", "Uzupelnij tresc lub zmien naglowek"),
        })

    # ── Stats ──
    summary = audit.get("summary", {})
    stats = {
        "auto_fixed": len(applied),
        "flagged_for_review": len(flagged),
        "duplicates_found": summary.get("duplicates_found", 0),
        "hallucinations_found": summary.get("hallucinations_found", 0),
        "fact_errors": summary.get("fact_errors", 0),
        "language_issues": summary.get("language_issues", 0),
        "overall_quality": summary.get("overall_quality", "?"),
    }

    print(f"[PROOFREADER] Auto-fixed: {stats['auto_fixed']}, "
          f"Flagged: {stats['flagged_for_review']}, "
          f"Quality: {stats['overall_quality']}")

    return {
        "corrected_text": result_text,
        "applied": applied,
        "flagged": flagged,
        "audit": audit,
        "stats": stats,
    }


# ══════════════════════════════════════════════════════════════
# Pass 1: Audyt (Sonnet)
# ══════════════════════════════════════════════════════════════

_AUDIT_SYSTEM_PROMPT = """Jestes doswiadczonym redaktorem naczelnym polskiego portalu internetowego. Dostajesz artykul SEO do recenzji. Twoje zadanie: znalezc WSZYSTKIE problemy i zwrocic precyzyjna liste poprawek.

Sprawdzasz tekst na CZTERECH poziomach -- od najwazniejszego:

POZIOM 1 -- DUPLIKATY I POWTORZENIA (severity: high)
Porownuj KAZDA sekcje H2 z KAZDA inna. Szukaj:
- Zdan identycznych lub niemal identycznych w roznych sekcjach
- Akapitow zaczynajacych sie od tego samego schematu
- Tych samych faktow/argumentow powtorzonych w roznych miejscach
- Tych samych metafor, porownan lub sformulowan uzytych wielokrotnie
To jest NAJCZESTSZY blad w artykulach AI i NAJLATWIEJSZY do wykrycia.

POZIOM 2 -- FAKTY I HALUCYNACJE (severity: high)
- Konkretne liczby, statystyki, procenty, daty BEZ pokrycia w danych referencyjnych = HALUCYNACJA
- Powolania na badania, ekspertow, instytucje BEZ pokrycia w danych = HALUCYNACJA
- Kwoty/progi/paragrafy NIEZGODNE z danymi referencyjnymi = BLAD FAKTYCZNY
- Sprzecznosci wewnetrzne (X w jednej sekcji, nie-X w innej)

POZIOM 3 -- STRUKTURA I OBIETNICE (severity: medium)
- Naglowek H2 obiecuje cos czego tresc nie dostarcza
  (np. "8 objawow" ale w tekscie nie ma 8 wyraznych punktow)
- Naglowek H2 odbiega od planu
- Encja glowna brakuje w H1 lub pierwszym akapicie
- Sekcja FAQ powtarza tresc z sekcji H2 zamiast dodawac nowa wartosc
- Brak logicznego przejscia miedzy sekcjami

POZIOM 4 -- JEZYK (severity: low)
- Literowki, ortografia
- Bledy odmiany (przypadek, osoba, czas, rodzaj)
- Ciezkie konstrukcje do uproszczenia
  (np. "zachowanie sie osoby zdradzajacej" -> "zachowanie osoby zdradzajacej")
- Brak przecinka przed ktory/ze/bo, nadmiarowy przecinek
- Powtorzenie slowa niebedacego fraza SEO w sasiednich zdaniach
  (np. "partner" 5x w jednym akapicie -- zamien czesc na zaimki lub synonimy)

CZEGO NIE ROBISZ:
- NIE zmieniasz fraz kluczowych SEO (lista w danych) nawet jesli sie powtarzaja
- NIE dodajesz nowych tresci -- tylko poprawiasz istniejace
- NIE przenosisz akapitow -- wskazujesz problem, copywriter zdecyduje
- NIE wymyslasz poprawek na sile -- jesli tekst jest dobry, zwroc puste listy"""


def _build_audit_user_prompt(
    article_text: str,
    s1_data: dict,
    variables: dict,
) -> str:
    """Build user prompt for audit pass."""

    main_keyword = variables.get("HASLO_GLOWNE", "")
    main_entity = variables.get("ENCJA_GLOWNA", "")
    hard_facts = _format_hard_facts(s1_data, variables)
    h2_plan = _format_h2_plan(variables)
    seo_phrases = _get_seo_phrases(variables)
    ymyl_context = variables.get("YMYL_CONTEXT", "Brak kontekstu YMYL -- artykul nie jest YMYL.")

    return f"""Sprawdz ponizszy artykul. Dla kazdego znalezionego problemu podaj precyzyjna poprawke.

=== ARTYKUL ===

{article_text}

=== DANE REFERENCYJNE ===

Haslo glowne: {main_keyword}
Encja glowna: {main_entity}

Twarde fakty (TYLKO te dane sa wiarygodne -- wszystko inne w artykule to potencjalna halucynacja):
{hard_facts}

Jesli artykul podaje liczbe, statystyke, badanie lub fakt ktorego NIE MA na powyzszej liscie -- zglos jako halucynacje z severity: high.

Plan naglowkow H2:
{h2_plan}

Frazy kluczowe SEO (NIE ruszaj, nawet jesli sie powtarzaja):
{seo_phrases}

Kontekst YMYL:
{ymyl_context}

=== PROCEDURA SPRAWDZANIA ===

Wykonaj te kroki PO KOLEI:

KROK 1: Wypisz sobie WSZYSTKIE zdania otwierajace kazda sekcje H2. Porownaj je parami. Czy ktores sa podobne? Czy te same frazy/schematy powtarzaja sie?

KROK 2: Wypisz WSZYSTKIE konkretne liczby, statystyki i fakty z artykulu. Sprawdz KAZDY z nich z lista twardych faktow powyzej. Jesli faktu NIE MA na liscie -- oznacz jako halucynacje.

KROK 3: Przeczytaj kazdy naglowek H2. Czy tresc pod nim SPELNIA obietnice naglowka? Jesli naglowek mowi "8 objawow" -- czy jest 8 wyraznych punktow? Jesli mowi "koszty" -- czy sa konkretne kwoty?

KROK 4: Sprawdz jezyk -- literowki, odmiane, przecinki, ciezkie konstrukcje.

=== FORMAT ODPOWIEDZI ===

Zwroc WYLACZNIE JSON -- bez markdown, bez komentarzy, bez tekstu przed/po:
{{
  "corrections": [
    {{
      "original": "dokladny cytat z artykulu (15-80 znakow, case-sensitive, z interpunkcja)",
      "replacement": "poprawiony fragment LUB '__USUN__' jesli trzeba usunac LUB '__PRZEREDAGUJ__' jesli wymaga przepisania",
      "reason": "wyjasnienie po polsku (max 20 slow)",
      "type": "duplicate|fact|structure|language",
      "severity": "high|medium|low"
    }}
  ],
  "hallucinations": [
    {{
      "text": "cytat z artykulu (20-100 znakow)",
      "reason": "dlaczego to halucynacja",
      "severity": "high",
      "suggestion": "bezpieczne sformulowanie zastepcze LUB 'USUN'"
    }}
  ],
  "duplicates": [
    {{
      "section_a": "nazwa sekcji z oryginalem (ta zostaje)",
      "section_b": "nazwa sekcji z duplikatem (ta do przepisania)",
      "text_a": "cytat z sekcji A (20-80 znakow)",
      "text_b": "cytat z sekcji B (20-80 znakow -- TEN do przepisania)",
      "similarity": "identical|near_identical|same_argument",
      "recommendation": "co zmienic w sekcji B"
    }}
  ],
  "unfulfilled_promises": [
    {{
      "h2": "tekst naglowka H2",
      "promise": "co naglowek obiecuje",
      "reality": "co tekst faktycznie dostarcza",
      "recommendation": "zmien naglowek LUB uzupelnij tresc"
    }}
  ],
  "summary": {{
    "duplicates_found": 0,
    "hallucinations_found": 0,
    "fact_errors": 0,
    "structure_issues": 0,
    "language_issues": 0,
    "overall_quality": "good|acceptable|needs_work"
  }}
}}

=== REGULY ===

1. "original" MUSI byc DOKLADNYM cytatem -- kopiuj litera po literze z tekstu powyzej.
2. Dla duplikatow: wpisz w "duplicates" (NIE w "corrections"). W "text_b" podaj fragment
   Z SEKCJI KTORA MA BYC PRZEPISANA (ta gorsza/pozniejsza).
3. Dla halucynacji: podaj "suggestion" z bezpiecznym zamiennikiem.
4. Dla niespe\u0142nionych obietnic: opisz w "unfulfilled_promises", nie w "corrections".
5. Frazy SEO: {seo_phrases} -- NIGDY nie zglaszaj ich powtorzen jako blad.
6. Maximum 30 pozycji lacznie. Priorytet: high -> medium -> low.
7. "overall_quality":
   - "good" = max 3 drobne jezykowe, 0 halucynacji, 0 duplikatow
   - "acceptable" = 4-8 jezykowych LUB 1 duplikat LUB 1 halucynacja
   - "needs_work" = 2+ duplikatow LUB 2+ halucynacji LUB 9+ jezykowych"""


def _run_audit(
    article_text: str,
    s1_data: dict,
    variables: dict,
) -> Optional[dict]:
    """Run Pass 1: Sonnet audit."""

    user_prompt = _build_audit_user_prompt(article_text, s1_data, variables)

    try:
        response, usage = claude_call(
            system_prompt=_AUDIT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model="claude-sonnet-4-6",
            max_tokens=3000,
            temperature=0.2,
        )

        print(f"[PROOFREADER] Audit call: {usage.get('input_tokens', 0)} in, "
              f"{usage.get('output_tokens', 0)} out")

        return _parse_json_response(response)

    except Exception as e:
        print(f"[PROOFREADER] Audit error: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# Pass 2c: Rewrite duplicates (Haiku)
# ══════════════════════════════════════════════════════════════

_REWRITE_SYSTEM_PROMPT = """Przepisz ponizszy akapit tak, aby przekazywal te sama tresc ale INNYMI SLOWAMI.

ZASADY:
- Zachowaj dlugosc (+-20% slow)
- Zachowaj styl i ton
- Zachowaj WSZYSTKIE frazy SEO dokladnie jak sa
- Zachowaj fakty i dane liczbowe
- Zmien strukture zdan, kolejnosc argumentow i dobor slow
- NIE dodawaj nowych informacji
- NIE usuwaj istniejacych informacji
- Zwroc TYLKO przepisany akapit, bez komentarzy"""


def _rewrite_duplicate(
    article_text: str,
    duplicate_info: dict,
    main_keyword: str,
    seo_phrases: str,
) -> Optional[dict]:
    """
    Rewrite duplicate paragraph via Haiku.
    Returns {"original": str, "rewritten": str} or None.
    """
    text_b = duplicate_info.get("text_b", "")
    text_a = duplicate_info.get("text_a", "")
    section_b = duplicate_info.get("section_b", "")
    recommendation = duplicate_info.get("recommendation", "")

    if not text_b:
        return None

    # Znajdz pelny akapit zawierajacy text_b w artykule
    paragraph = _find_paragraph_containing(article_text, text_b)
    if not paragraph:
        return None

    user_prompt = f"""KONTEKST: Artykul o "{main_keyword}", sekcja "{section_b}". Akapit ponizej jest DUPLIKATEM podobnego fragmentu w innej sekcji. Przepisz go zachowujac sens ale zmieniajac slowa i strukture zdan.

AKAPIT DO PRZEPISANIA:
{paragraph}

FRAGMENT KTORY ZOSTAJE W INNEJ SEKCJI (nie powtarzaj tych sformulowan):
{text_a}

WSKAZOWKA: {recommendation}

FRAZY SEO (zachowaj dokladnie, nie zmieniaj):
{seo_phrases}

Zwroc TYLKO przepisany akapit."""

    try:
        response, usage = claude_call(
            system_prompt=_REWRITE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            temperature=0.6,
        )

        rewritten = response.strip()

        # Walidacja: przepisany tekst nie powinien byc za krotki
        if len(rewritten.split()) < len(paragraph.split()) * 0.5:
            return None
        # Walidacja: nie powinien byc identyczny
        if rewritten == paragraph:
            return None

        return {"original": paragraph, "rewritten": rewritten}

    except Exception as e:
        print(f"[PROOFREADER] Rewrite error: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════

def _format_hard_facts(s1_data: dict, variables: dict) -> str:
    """Format hard facts for audit prompt."""
    lines = []

    hard_facts = variables.get("_hard_facts", [])
    for hf in hard_facts[:20]:
        if isinstance(hf, dict):
            val = hf.get("value", "")
            cat = hf.get("category", "")
            snippet = hf.get("source_snippet", "")[:120]
            if val:
                lines.append(f"- {val} ({cat}) -- kontekst: \"{snippet}\"")
        elif isinstance(hf, str):
            lines.append(f"- {hf}")

    # Factographic triples (EAV type -- concrete values)
    fact_triples = s1_data.get("entity_seo", {}).get("factographic_triples", [])
    for t in fact_triples[:15]:
        if isinstance(t, dict) and t.get("triplet_type") == "eav":
            subj = t.get("subject", "")
            obj = t.get("object", "")
            if subj and obj:
                lines.append(f"- {subj}: {obj}")

    # Causal relations
    causal = s1_data.get("causal_triplets", {})
    for rel in (causal.get("singles") or causal.get("relations") or [])[:10]:
        if isinstance(rel, dict):
            cause = rel.get("cause", "")
            effect = rel.get("effect", "")
            if cause and effect:
                lines.append(f"- RELACJA: {cause} -> {effect}")

    # YMYL legal/medical facts
    ymyl = variables.get("YMYL_CONTEXT", "")
    for line in ymyl.split("\n"):
        line = line.strip()
        if any(kw in line.lower() for kw in ["art.", "\u00a7", "kodeks", "ustaw", "rozporz"]):
            lines.append(f"- PRAWO: {line[:150]}")

    if not lines:
        return "(brak twardych faktow -- sprawdzaj tylko jezyk i strukture)"

    return "\n".join(lines)


def _format_h2_plan(variables: dict) -> str:
    """Format H2 plan for audit prompt."""
    h2_plan = variables.get("_h2_plan_list", [])
    if not h2_plan:
        return "(brak planu H2)"
    return "\n".join(f"{i+1}. {h}" for i, h in enumerate(h2_plan))


def _get_seo_phrases(variables: dict) -> str:
    """Get SEO phrases that should NOT be touched."""
    phrases = set()

    # Main keyword + entity
    for key in ("HASLO_GLOWNE", "ENCJA_GLOWNA", "KEY_NGRAM"):
        val = variables.get(key, "")
        if val:
            phrases.add(val)

    # Top n-grams
    ngrams = variables.get("_ngrams", [])
    for ng in ngrams[:15]:
        if isinstance(ng, dict):
            text = ng.get("ngram", "")
            if text and len(text) > 3:
                phrases.add(text)

    # Periphrases
    periphrases = variables.get("PERYFRAZY", "")
    if isinstance(periphrases, str):
        try:
            periphrases = json.loads(periphrases)
        except (json.JSONDecodeError, ValueError):
            periphrases = []
    if isinstance(periphrases, list):
        for p in periphrases[:10]:
            if isinstance(p, str) and len(p) > 3:
                phrases.add(p)

    return ", ".join(sorted(phrases))


def _find_paragraph_containing(article_text: str, fragment: str) -> Optional[str]:
    """Find the full paragraph containing a text fragment."""
    paragraphs = re.split(r'\n\s*\n', article_text)

    for para in paragraphs:
        if fragment in para:
            return para.strip()

    # Fallback: try case-insensitive match
    fragment_lower = fragment.lower()
    for para in paragraphs:
        if fragment_lower in para.lower():
            return para.strip()

    return None


def _parse_json_response(response: str) -> Optional[dict]:
    """Parse JSON from LLM response, handling markdown fences."""
    text = response.strip()

    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # Find JSON boundaries
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1:
        print("[PROOFREADER] No JSON found in response")
        return None

    try:
        return json.loads(text[first:last + 1])
    except json.JSONDecodeError as e:
        print(f"[PROOFREADER] JSON parse error: {e}")
        # Try to fix common issues
        json_text = text[first:last + 1]
        json_text = re.sub(r',\s*([}\]])', r'\1', json_text)
        try:
            return json.loads(json_text)
        except (json.JSONDecodeError, ValueError):
            return None


def _collect_all_issues(audit: dict) -> list:
    """Collect all issues from audit as flat list for display."""
    issues = []

    for corr in audit.get("corrections", []):
        issues.append({
            "type": corr.get("type", "language"),
            "severity": corr.get("severity", "low"),
            "text": corr.get("original", ""),
            "reason": corr.get("reason", ""),
            "action": f"Zamien na: {corr.get('replacement', '')}",
        })

    for hall in audit.get("hallucinations", []):
        issues.append({
            "type": "hallucination",
            "severity": "high",
            "text": hall.get("text", ""),
            "reason": hall.get("reason", ""),
            "action": hall.get("suggestion", "Usun"),
        })

    for dup in audit.get("duplicates", []):
        issues.append({
            "type": "duplicate",
            "severity": "high",
            "text": f"{dup.get('section_a', '?')} <-> {dup.get('section_b', '?')}",
            "reason": f"Podobne: \"{dup.get('text_a', '')[:40]}\" vs \"{dup.get('text_b', '')[:40]}\"",
            "action": dup.get("recommendation", "Przepisz jedna z wersji"),
        })

    for promise in audit.get("unfulfilled_promises", []):
        issues.append({
            "type": "unfulfilled_promise",
            "severity": "medium",
            "text": promise.get("h2", ""),
            "reason": f"Obiecuje: {promise.get('promise', '?')}. Daje: {promise.get('reality', '?')}",
            "action": promise.get("recommendation", "Uzupelnij tresc lub zmien naglowek"),
        })

    return issues


def _count_issues(audit: dict) -> int:
    """Count total issues in audit."""
    return (len(audit.get("corrections", [])) +
            len(audit.get("hallucinations", [])) +
            len(audit.get("duplicates", [])) +
            len(audit.get("unfulfilled_promises", [])))
