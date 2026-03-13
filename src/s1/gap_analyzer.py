"""
===============================================================================
📊 GAP ANALYZER v1.0 — Information Gain dla S1
===============================================================================
Identyfikuje tematy, których NIKT w top 10 nie pokrywa,
ale użytkownicy o nie pytają (PAA, related searches).

3 typy gapów:
1. PAA_UNANSWERED — pytania PAA, na które nikt nie odpowiada
2. SUBTOPIC_MISSING — related searches nieobecne w H2 konkurencji
3. DEPTH_MISSING — sekcje u wszystkich, ale płytkie (<120 słów)

Integracja: index.py → po entity_seo → dodaje "content_gaps" do response

Autor: BRAJEN Team
Data: 2025
===============================================================================
"""

import re
from typing import List, Dict, Set, Optional
from collections import Counter
from dataclasses import dataclass, asdict


# ================================================================
# 📦 STRUKTURY DANYCH
# ================================================================

@dataclass
class ContentGap:
    """Pojedynczy zidentyfikowany gap w treści konkurencji."""
    topic: str
    gap_type: str           # "paa_unanswered", "subtopic_missing", "depth_missing"
    evidence: str           # dlaczego to gap
    priority: str           # "high", "medium", "low"
    suggested_h2: str       # propozycja H2

    def to_dict(self) -> Dict:
        return asdict(self)


# ================================================================
# 🧹 HELPERY
# ================================================================

# Polskie stop words (rozszerzone)
_STOP_WORDS_PL = {
    "i", "w", "na", "z", "do", "że", "się", "nie", "to", "jest", "za", "po",
    "od", "o", "jak", "ale", "co", "ten", "tym", "być", "może", "już", "tak",
    "gdy", "lub", "czy", "tego", "tej", "są", "dla", "ich", "przez", "jako",
    "te", "ze", "tych", "było", "ma", "przy", "tym", "które", "który", "która",
    "których", "jego", "jej", "tego", "także", "więc", "tylko", "też", "sobie",
    "bardzo", "jeszcze", "wszystko", "przed", "między", "pod", "nad", "bez",
    "oraz", "gdzie", "kiedy", "ile", "jeśli", "jaki", "jaka", "jakie",
}


def _extract_content_words(text: str, min_len: int = 4) -> Set[str]:
    """Wyciąga znaczące słowa z tekstu (bez stop words)."""
    words = set(re.findall(r'\b[a-ząćęłńóśźż]{' + str(min_len) + r',}\b', text.lower()))
    return words - _STOP_WORDS_PL


def _normalize_h2(h2: str) -> str:
    """Normalizuje H2 do porównań."""
    return re.sub(r'[^a-ząćęłńóśźż0-9\s]', '', h2.lower()).strip()


def _words_overlap(words_a: Set[str], words_b: Set[str], threshold: int = 2) -> bool:
    """Sprawdza czy dwa zestawy słów mają wystarczający overlap."""
    return len(words_a & words_b) >= threshold


# ================================================================
# 📊 GŁÓWNA ANALIZA
# ================================================================

def analyze_content_gaps(
    competitor_texts: List[str],
    competitor_h2s: List[str],
    paa_questions: List[Dict],
    related_searches: List[str],
    main_keyword: str,
    max_gaps: int = 15
) -> Dict:
    """
    Identyfikuje 3 typy gapów w treści konkurencji.

    Args:
        competitor_texts: Pełne treści stron z top 10
        competitor_h2s: Wszystkie H2 ze stron konkurencji
        paa_questions: Pytania People Also Ask (list of dicts z "question")
        related_searches: Related searches z Google
        main_keyword: Główna fraza kluczowa
        max_gaps: Max liczba gapów do zwrócenia

    Returns:
        Dict z content_gaps + agent_instruction
    """
    # Przygotuj dane
    combined_competitor = " ".join(t.lower() for t in competitor_texts if t)[:500000]
    
    # Normalizuj H2 konkurencji (h2 may be str or dict with "text" key)
    competitor_h2_normalized = set()
    competitor_h2_words = []
    for h2 in competitor_h2s:
        if isinstance(h2, dict):
            h2 = h2.get("text") or h2.get("pattern") or ""
        if not isinstance(h2, str) or not h2:
            continue
        norm = _normalize_h2(h2)
        if norm:
            competitor_h2_normalized.add(norm)
            competitor_h2_words.append(_extract_content_words(h2))

    gaps = []

    # ═══════════════════════════════════════
    # 1. PAA UNANSWERED
    # ═══════════════════════════════════════
    for paa in paa_questions:
        question = paa.get("question", "") if isinstance(paa, dict) else str(paa)
        if not question or len(question) < 10:
            continue

        question_words = _extract_content_words(question)
        if len(question_words) < 2:
            continue

        # Czy jakiś H2 konkurencji pokrywa to pytanie?
        covered_by_h2 = any(
            _words_overlap(question_words, h2w)
            for h2w in competitor_h2_words
        )

        # Czy treść konkurencji odpowiada na pytanie?
        # (sprawdzamy ile kluczowych słów z pytania pojawia się w treściach)
        words_in_content = sum(1 for w in question_words if w in combined_competitor)
        content_coverage = words_in_content / max(1, len(question_words))

        if not covered_by_h2 and content_coverage < 0.6:
            # Nikt nie pokrywa tego pytania
            gaps.append(ContentGap(
                topic=question,
                gap_type="paa_unanswered",
                evidence=f"PAA pytanie niepokryte: {words_in_content}/{len(question_words)} "
                         f"słów kluczowych w treściach, brak H2",
                priority="high",
                suggested_h2=_question_to_h2(question)
            ))
        elif not covered_by_h2 and content_coverage < 0.8:
            # Treść częściowo pokrywa, ale brak dedykowanego H2
            gaps.append(ContentGap(
                topic=question,
                gap_type="paa_unanswered",
                evidence=f"PAA pytanie bez dedykowanego H2 ({content_coverage:.0%} pokrycia w treści)",
                priority="medium",
                suggested_h2=_question_to_h2(question)
            ))

    # ═══════════════════════════════════════
    # 2. SUBTOPIC MISSING
    # ═══════════════════════════════════════
    for search in related_searches:
        if isinstance(search, dict):
            search = search.get("query") or search.get("text") or ""
        if not search or not isinstance(search, str) or len(search) < 5:
            continue

        search_words = _extract_content_words(search)
        if len(search_words) < 2:
            continue

        # Czy jakiś H2 pokrywa ten related search?
        covered_by_h2 = any(
            _words_overlap(search_words, h2w)
            for h2w in competitor_h2_words
        )

        if not covered_by_h2:
            # Sprawdź czy to nie duplikat main_keyword
            main_kw_words = _extract_content_words(main_keyword)
            if search_words == main_kw_words:
                continue

            gaps.append(ContentGap(
                topic=search,
                gap_type="subtopic_missing",
                evidence=f"Related search '{search}' nieobecny w H2 konkurencji",
                priority="medium",
                suggested_h2=search.strip().capitalize()
            ))

    # ═══════════════════════════════════════
    # 3. DEPTH MISSING — płytkie sekcje
    # ═══════════════════════════════════════
    # Policz H2 pojawiające się u wielu konkurentów
    h2_counter = Counter(
        _normalize_h2(h.get("text") or h.get("pattern") or "" if isinstance(h, dict) else h)
        for h in competitor_h2s
        if (h.get("text") or "" if isinstance(h, dict) else h).strip()
    )
    common_h2s = [h2 for h2, count in h2_counter.items() if count >= 3 and h2]

    for h2_norm in common_h2s:
        # Szacuj średnią długość sekcji pod tym H2 u konkurencji
        section_lengths = _estimate_section_lengths(competitor_texts, h2_norm)

        if section_lengths:
            avg_words = sum(section_lengths) / len(section_lengths)
            if avg_words < 120:
                # Znaleziono H2 w oryginale (nienormalizowany)
                original_h2 = _find_original_h2(competitor_h2s, h2_norm)
                
                gaps.append(ContentGap(
                    topic=original_h2 or h2_norm,
                    gap_type="depth_missing",
                    evidence=f"Sekcja '{original_h2 or h2_norm}' u konkurencji ma śr. "
                             f"{int(avg_words)} słów — można rozbudować",
                    priority="medium" if avg_words > 80 else "high",
                    suggested_h2=original_h2 or h2_norm.capitalize()
                ))

    # ═══════════════════════════════════════
    # DEDUPLIKACJA I SORTOWANIE
    # ═══════════════════════════════════════
    gaps = _deduplicate_gaps(gaps)
    
    # Sortuj: high > medium > low
    priority_order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: priority_order.get(g.priority, 2))
    gaps = gaps[:max_gaps]

    # ═══════════════════════════════════════
    # FORMATOWANIE DLA AGENTA
    # ═══════════════════════════════════════
    agent_instruction = _format_gaps_for_agent(gaps, main_keyword)

    return {
        "total_gaps": len(gaps),
        "paa_unanswered": [g.to_dict() for g in gaps if g.gap_type == "paa_unanswered"],
        "subtopic_missing": [g.to_dict() for g in gaps if g.gap_type == "subtopic_missing"],
        "depth_missing": [g.to_dict() for g in gaps if g.gap_type == "depth_missing"],
        "all_gaps": [g.to_dict() for g in gaps],
        "suggested_new_h2s": [
            g.suggested_h2 for g in gaps 
            if g.priority == "high" and g.gap_type in ("paa_unanswered", "subtopic_missing")
        ][:3],
        "agent_instruction": agent_instruction,
        "status": "OK"
    }


# ================================================================
# 🔧 HELPER FUNCTIONS
# ================================================================

def _question_to_h2(question: str) -> str:
    """Konwertuje pytanie PAA na propozycję H2."""
    # Usuń znaki zapytania i capitalize
    h2 = question.rstrip("?").strip()
    # Jeśli zaczyna się od "Czy ", zmień na stwierdzenie
    if h2.lower().startswith("czy "):
        h2 = h2[4:]
    # Capitalize first letter
    if h2:
        h2 = h2[0].upper() + h2[1:]
    return h2


def _estimate_section_lengths(
    competitor_texts: List[str],
    h2_normalized: str
) -> List[int]:
    """
    Szacuje długość sekcji pod danym H2 u konkurencji.
    Proste podejście: znajdź H2 → policz słowa do następnego H2.
    """
    lengths = []
    h2_words = set(h2_normalized.split())
    
    for text in competitor_texts:
        if not text:
            continue
        text_lower = text.lower()
        
        # Znajdź pozycję H2 (przybliżone — szukamy słów z H2)
        # Szukamy linii, która wygląda jak H2 i zawiera nasze słowa
        lines = text_lower.split('\n')
        found_pos = -1
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if len(line_stripped) < 100:  # H2 raczej krótkie
                line_words = set(re.findall(r'\b[a-ząćęłńóśźż]{3,}\b', line_stripped))
                if len(h2_words & line_words) >= max(2, len(h2_words) - 1):
                    found_pos = i
                    break
        
        if found_pos == -1:
            continue
        
        # Policz słowa do następnego "H2-like" nagłówka
        section_text = []
        for j in range(found_pos + 1, min(found_pos + 50, len(lines))):
            line = lines[j].strip()
            # Heurystyka: krótka linia (<80 znaków) po pustej linii = prawdopodobnie H2
            if (len(line) < 80 and len(line) > 5 and 
                j > found_pos + 2 and not lines[j-1].strip()):
                break
            section_text.append(line)
        
        word_count = len(" ".join(section_text).split())
        if word_count > 10:  # Ignoruj bardzo krótkie (prawdopodobnie błędne matche)
            lengths.append(word_count)
    
    return lengths


def _find_original_h2(h2_list: List[str], normalized: str) -> Optional[str]:
    """Znajduje oryginalny (nienormalizowany) H2."""
    for h2 in h2_list:
        text = h2.get("text") or h2.get("pattern") or "" if isinstance(h2, dict) else h2
        if text and _normalize_h2(text) == normalized:
            return text
    return None


def _deduplicate_gaps(gaps: List[ContentGap]) -> List[ContentGap]:
    """Usuwa duplikaty na podstawie podobieństwa tematu."""
    seen_topics = set()
    unique = []
    
    for gap in gaps:
        # Klucz dedup: pierwsze 3 znaczące słowa
        topic_words = sorted(_extract_content_words(gap.topic))[:3]
        key = "|".join(topic_words)
        
        if key not in seen_topics and key:
            seen_topics.add(key)
            unique.append(gap)
    
    return unique


def _format_gaps_for_agent(gaps: List[ContentGap], main_keyword: str) -> str:
    """Formatuje gapy jako instrukcję dla agenta GPT."""
    if not gaps:
        return ""

    lines = [
        f"📊 CONTENT GAPS — tematy, których NIKT w top 10 nie pokrywa dla \"{main_keyword}\":",
        ""
    ]

    high_gaps = [g for g in gaps if g.priority == "high"]
    medium_gaps = [g for g in gaps if g.priority == "medium"]

    if high_gaps:
        lines.append("🔴 WYSOKIE PRIORYTETY (rozważ dodanie osobnego H2):")
        for g in high_gaps[:5]:
            gap_type_label = {
                "paa_unanswered": "PAA",
                "subtopic_missing": "Related",
                "depth_missing": "Depth"
            }.get(g.gap_type, g.gap_type)
            lines.append(f"  • [{gap_type_label}] {g.topic}")
            lines.append(f"    → Proponowany H2: \"{g.suggested_h2}\"")
        lines.append("")

    if medium_gaps:
        lines.append("🟡 ŚREDNIE PRIORYTETY (wpleć w istniejące sekcje):")
        for g in medium_gaps[:5]:
            lines.append(f"  • {g.topic} ({g.evidence[:60]})")
        lines.append("")

    lines.append(
        "💡 STRATEGIA: Dodanie 1-2 H2 z gapów HIGH to najszybsza ścieżka "
        "do Information Gain — Google nagrodzi treść, której nikt inny nie ma."
    )

    return "\n".join(lines)


# ================================================================
# EXPORTS
# ================================================================

__all__ = [
    'analyze_content_gaps',
    'ContentGap',
]
