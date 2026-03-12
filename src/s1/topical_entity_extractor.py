"""
===============================================================================
🧠 TOPICAL ENTITY EXTRACTOR v1.0 — Encje pojęciowe (Concept/Semantic Entities)
===============================================================================
Wyciąga topical entities z tekstów konkurencji — pojęcia, koncepty, frazy
tematyczne, które NIE SĄ named entities (osoby/firmy/miejsca), ale są
kluczowe dla pokrycia tematu i Google Knowledge Graph.

Metody ekstrakcji:
1. spaCy noun_chunks → frazy rzeczownikowe ("bezpieczny transport", "dokumenty firmowe")
2. Frequency × Distribution scoring → ważniejsze = w wielu źródłach
3. Lemmatyzacja → grupuje odmiany ("dokumentów"/"dokumenty"/"dokumentami")
4. Garbage filtering → eliminuje CSS/JS/HTML artefakty

Integracja: entity_extractor.py → perform_entity_seo_analysis()

Autor: BRAJEN Team
Data: 2025
===============================================================================
"""

import re
import math
from collections import Counter, defaultdict
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field


# ================================================================
# 🚫 STOP WORDS & FILTERS
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
    "tutaj", "tam", "teraz", "potem", "zawsze", "nigdy", "każdy", "każda",
    "mieć", "móc", "musieć", "chcieć", "wiedzieć", "dużo", "mało",
    "ten", "ta", "to", "ci", "te", "tę", "tą", "tych", "tym", "tymi",
    "mój", "twój", "swój", "nasz", "wasz", "moje", "twoje", "nasze",
    "jeden", "dwa", "trzy", "cztery", "pięć", "kilka", "wiele",
    "co", "kto", "czego", "czym", "komu", "kogo", "kim",
    "strona", "link", "kliknij", "czytaj", "więcej", "dalej",
    "udostępnij", "komentarz", "odpowiedz", "przeczytaj",
}

# ================================================================
# 🚫 WEB GARBAGE FILTER — import or fallback
# ================================================================

try:
    try:
        from .web_garbage_filter import is_entity_garbage as _is_web_garbage, CSS_ENTITY_BLACKLIST
    except ImportError:
        from web_garbage_filter import is_entity_garbage as _is_web_garbage, CSS_ENTITY_BLACKLIST
    WEB_FILTER_AVAILABLE = True
    print(f"[TOPICAL] ✅ Web garbage filter loaded ({len(CSS_ENTITY_BLACKLIST)} entries)")
except ImportError:
    WEB_FILTER_AVAILABLE = False
    CSS_ENTITY_BLACKLIST = set()
    print("[TOPICAL] ⚠️ web_garbage_filter not found, using built-in patterns")


# Wzorce garbage (CSS/JS/HTML) w noun chunks — used as fallback
_GARBAGE_CHUNK_PATTERNS = re.compile(
    r'[{};@#\[\]<>=\\|]|'       # Specjalne znaki CSS/JS
    r'\.ast[-_]|\.wp[-_]|'       # WordPress/Astra CSS
    r'webkit|moz-|flex-|'        # CSS vendor prefixes
    r'font-|border-|padding-|'   # CSS properties
    r'display:|color:|margin:|'  # CSS declarations
    r'kevlar_|ytcfg|ytplayer|'   # YouTube JS
    r'px$|em$|rem$|vh$|vw$|'     # CSS units
    r'var\(|calc\(|rgb\(|'       # CSS functions
    r'none|inherit|auto|'        # CSS values
    r'data-|aria-|role=',        # HTML attributes
    re.IGNORECASE
)

# Minimum proporcja liter w chunku (odfiltruj "123px", "50%" etc.)
_MIN_ALPHA_RATIO = 0.6


# ================================================================
# 📦 STRUKTURY DANYCH
# ================================================================

@dataclass
class TopicalEntity:
    """Encja pojęciowa / topical entity."""
    text: str                    # Tekst encji (zlematyzowana forma bazowa)
    display_text: str            # Najczęstsza forma powierzchniowa
    type: str = "CONCEPT"        # CONCEPT (1-2 słowa) lub TOPICAL (2-4 słowa)
    frequency: int = 1           # Łączna częstość we wszystkich źródłach
    sources_count: int = 1       # W ilu źródłach występuje
    importance: float = 0.5      # Score 0-1
    contexts: List[str] = field(default_factory=list)
    variants: List[str] = field(default_factory=list)  # Odmiany
    freq_per_source: List[int] = field(default_factory=list)  # v51: per-source frequency
    
    def to_dict(self) -> Dict:
        # v51: Compute Surfer-style frequency ranges
        non_zero = sorted([c for c in self.freq_per_source if c > 0]) if self.freq_per_source else []
        if non_zero:
            freq_min = non_zero[0]
            freq_max = non_zero[-1]
            mid = len(non_zero) // 2
            freq_median = non_zero[mid] if len(non_zero) % 2 == 1 else (non_zero[mid-1] + non_zero[mid]) // 2
        else:
            freq_min = freq_median = freq_max = 0
        
        return {
            "text": self.display_text,
            "type": self.type,
            "frequency": self.frequency,
            "sources_count": self.sources_count,
            "importance": round(self.importance, 3),
            "sample_context": self.contexts[0] if self.contexts else "",
            "variants": self.variants[:5],
            "freq_per_source": self.freq_per_source,
            "freq_min": freq_min,
            "freq_median": freq_median,
            "freq_max": freq_max,
        }


# ================================================================
# 🔧 HELPER FUNCTIONS
# ================================================================

def _is_chunk_garbage(text: str) -> bool:
    """Sprawdza czy noun chunk to CSS/JS/HTML garbage."""
    if not text or len(text) < 2:
        return True
    
    # Use comprehensive filter if available
    if WEB_FILTER_AVAILABLE and _is_web_garbage(text):
        return True
    
    # Fallback: Garbage pattern check
    if _GARBAGE_CHUNK_PATTERNS.search(text):
        return True
    
    # Alpha ratio check
    alpha_count = sum(1 for c in text if c.isalpha())
    if len(text) > 0 and alpha_count / len(text) < _MIN_ALPHA_RATIO:
        return True
    
    # Too short or too long
    if len(text) < 3 or len(text) > 80:
        return True
    
    return False


def _is_only_stopwords(words: List[str]) -> bool:
    """Sprawdza czy fraza składa się tylko ze stop words."""
    meaningful = [w for w in words if w.lower() not in _STOP_WORDS_PL and len(w) > 2]
    return len(meaningful) == 0


def _normalize_chunk(text: str) -> str:
    """Normalizuje noun chunk do porównywania."""
    # Lowercase, strip, remove extra whitespace
    text = re.sub(r'\s+', ' ', text.lower().strip())
    # Remove leading/trailing punctuation
    text = text.strip('.,;:!?-–—()[]"\'')
    return text


def _pos_noun_chunks(doc):
    """
    Fallback for languages without noun_chunks (e.g. Polish).
    Builds noun-phrase spans from POS tags: sequences of ADJ/NOUN/PROPN
    ending in NOUN or PROPN, length 2-5 tokens.
    Returns list of spaCy Span objects (same interface as doc.noun_chunks).
    """
    _NP_POS = {"NOUN", "PROPN", "ADJ"}
    spans = []
    start = None
    for i, token in enumerate(doc):
        if token.pos_ in _NP_POS and not token.is_stop:
            if start is None:
                start = i
        else:
            if start is not None:
                end = i
                length = end - start
                if 2 <= length <= 5 and doc[end - 1].pos_ in {"NOUN", "PROPN"}:
                    spans.append(doc[start:end])
                start = None
    # handle tail
    if start is not None:
        end = len(doc)
        length = end - start
        if 2 <= length <= 5 and doc[end - 1].pos_ in {"NOUN", "PROPN"}:
            spans.append(doc[start:end])
    return spans


def _get_lemma_key(doc_chunk) -> str:
    """
    Tworzy klucz lemmatyzacyjny z noun chunka.
    Używa lemmatów spaCy do grupowania odmian.
    """
    lemmas = []
    for token in doc_chunk:
        if token.is_stop or token.is_punct:
            continue
        lemma = token.lemma_.lower()
        if len(lemma) > 2:
            lemmas.append(lemma)
    
    return " ".join(sorted(lemmas))  # Sorted dla niezależności od kolejności


def _get_context(text: str, phrase: str, window: int = 60) -> str:
    """Wyciąga kontekst wokół frazy."""
    idx = text.lower().find(phrase.lower())
    if idx < 0:
        return ""
    start = max(0, idx - window)
    end = min(len(text), idx + len(phrase) + window)
    ctx = text[start:end].strip()
    if start > 0:
        ctx = "..." + ctx
    if end < len(text):
        ctx = ctx + "..."
    return ctx


# ================================================================
# 🧠 MAIN EXTRACTION
# ================================================================

def extract_topical_entities(
    nlp,
    texts: List[str],
    urls: List[str] = None,
    main_keyword: str = "",
    max_entities: int = 30,
    min_frequency: int = 2,
    min_sources: int = 1,
) -> List[TopicalEntity]:
    """
    Wyciąga topical/concept entities z tekstów konkurencji.
    
    Używa spaCy noun_chunks zamiast NER — wyciąga frazy rzeczownikowe
    jak "bezpieczny transport", "dokumenty firmowe", "karton do przeprowadzki".
    
    Args:
        nlp: Załadowany model spaCy
        texts: Lista tekstów (z content_extractor lub SERP scraper)
        urls: Lista URL-i źródeł
        main_keyword: Fraza główna (do boostowania relevance)
        max_entities: Max encji do zwrócenia
        min_frequency: Min częstość (suma ze wszystkich źródeł)
        min_sources: Min ile źródeł musi zawierać frazę
    
    Returns:
        Lista TopicalEntity posortowana po importance
    """
    if not texts:
        return []
    
    urls = urls or [f"source_{i}" for i in range(len(texts))]
    total_sources = len(texts)
    
    # Struktura do agregacji
    # klucz = lemma_key, wartości = dane
    chunk_data = defaultdict(lambda: {
        "frequency": 0,
        "sources": set(),
        "surface_forms": Counter(),  # Zlicza formy powierzchniowe
        "contexts": [],
        "word_count": 0,
        "freq_per_source": Counter(),  # v51: per-source frequency
    })
    
    # Keyword lemmas (do relevance boosting)
    keyword_words = set()
    if main_keyword:
        keyword_words = {w.lower() for w in main_keyword.split() 
                        if w.lower() not in _STOP_WORDS_PL and len(w) > 2}
    
    print(f"[TOPICAL] 🔍 Extracting concept entities from {len(texts)} sources")
    
    for idx, text in enumerate(texts):
        if not text or len(text) < 100:
            continue
        
        # Limit tekstu dla wydajności
        text_sample = text[:50000]
        
        try:
            doc = nlp(text_sample)

            # Polish spaCy models don't support noun_chunks,
            # so we build them from POS tags (NOUN/PROPN/ADJ sequences)
            try:
                chunks = list(doc.noun_chunks)
            except NotImplementedError:
                chunks = _pos_noun_chunks(doc)

            for chunk in chunks:
                chunk_text = chunk.text.strip()
                
                # --- FILTRACJA ---
                
                # Skip garbage
                if _is_chunk_garbage(chunk_text):
                    continue
                
                # Normalizuj
                normalized = _normalize_chunk(chunk_text)
                if not normalized or len(normalized) < 3:
                    continue
                
                # Podziel na słowa
                words = normalized.split()
                
                # Skip single stopwords lub pure numbers
                if _is_only_stopwords(words):
                    continue
                
                # Skip za długie frazy (>5 słów = prawdopodobnie zdanie)
                if len(words) > 5:
                    continue
                
                # Skip jeśli pierwsze słowo to przyimek/zaimek (np. "w domu", "to jest")
                if words[0] in _STOP_WORDS_PL and len(words) <= 2:
                    continue
                
                # --- GRUPOWANIE po lematach ---
                lemma_key = _get_lemma_key(chunk)
                if not lemma_key or len(lemma_key) < 3:
                    continue
                
                data = chunk_data[lemma_key]
                data["frequency"] += 1
                data["sources"].add(urls[idx])
                data["surface_forms"][normalized] += 1
                data["word_count"] = max(data["word_count"], len(words))
                data["freq_per_source"][idx] += 1  # v51: per-source tracking
                
                # Kontekst (max 3 per entity)
                if len(data["contexts"]) < 3:
                    ctx = _get_context(text_sample, chunk_text)
                    if ctx and ctx not in data["contexts"]:
                        data["contexts"].append(ctx)
        
        except Exception as e:
            print(f"[TOPICAL] ⚠️ Error processing source {idx}: {e}")
            continue
    
    # --- SCORING & RANKING ---
    entities = []
    
    for lemma_key, data in chunk_data.items():
        freq = data["frequency"]
        sources_count = len(data["sources"])
        
        # Minimum thresholds
        if freq < min_frequency:
            continue
        if sources_count < min_sources:
            continue
        
        # Najczęstsza forma powierzchniowa = display text
        # v52.1: Spellcheck — preferuj formy bez oczywistych literówek.
        # Literówka = słowo z sekwencją 3+ spółgłosek BEZ samogłoski (np. "uchwtów")
        # lub krótkie słowo z brakującymi literami w środku.
        def _has_typo(word: str) -> bool:
            """Heurystyczna detekcja literówki w polskim słowie.

            v52.1: Reguła: 4+ spółgłosek z rzędu po pierwszej samogłosce = literówka.
            Polskie grupy na POCZĄTKU słowa (strz, prz, chr, szcz) są dozwolone.
            W środku słowa sekwencja 4+ spółgłosek = brakujące litery.
            Przykład: 'uchwtów' → po 'u' pojawia się 'chwt' (4 spółgłoski) = literówka.
            """
            vowels = set("aąeęioóuy")
            w = word.lower()
            i = 0
            # Pomiń początkową grupę spółgłosek (dozwolone w polskim: strz, prz, chr itp.)
            while i < len(w) and w[i].isalpha() and w[i] not in vowels:
                i += 1
            # Skanuj resztę słowa — mid-word 4+ spółgłoski = literówka
            cluster = 0
            while i < len(w):
                ch = w[i]
                if not ch.isalpha():
                    cluster = 0
                elif ch in vowels:
                    cluster = 0
                else:
                    cluster += 1
                    if cluster >= 4:
                        return True
                i += 1
            return False

        def _best_surface_form(surface_forms_counter):
            """Wybiera najczęstszą formę, ale pomija ewidentne literówki."""
            candidates = surface_forms_counter.most_common()
            for form, count in candidates:
                words_in_form = form.split()
                if not any(_has_typo(w) for w in words_in_form):
                    return form
            # Fallback: zwróć najczęstszą mimo potencjalnej literówki
            return candidates[0][0]

        most_common_form = _best_surface_form(data["surface_forms"])

        # Wszystkie warianty (bez literówek na pierwszym miejscu)
        variants = [form for form, _ in data["surface_forms"].most_common(5)]
        
        # Typ: CONCEPT (1-2 słowa) lub TOPICAL (3+ słów)
        word_count = data["word_count"]
        entity_type = "CONCEPT" if word_count <= 2 else "TOPICAL"
        
        # --- IMPORTANCE SCORE ---
        score = 0.0
        
        # 1. Distribution score (w ilu źródłach, 0-0.35)
        #    Encja w 100% źródeł = 0.35
        distribution = sources_count / max(total_sources, 1)
        score += distribution * 0.35
        
        # 2. Frequency score (log scale, 0-0.25)
        freq_score = min(0.25, math.log(freq + 1) * 0.06)
        score += freq_score
        
        # 3. Specificity score (2-3 słowa = najlepsze, 0-0.20)
        if word_count == 2:
            score += 0.20
        elif word_count == 3:
            score += 0.18
        elif word_count == 1:
            score += 0.10
        elif word_count >= 4:
            score += 0.08
        
        # 4. Keyword relevance boost (0-0.20)
        if keyword_words:
            chunk_words = set(most_common_form.split())
            overlap = chunk_words & keyword_words
            if overlap:
                relevance = len(overlap) / max(len(keyword_words), 1)
                score += relevance * 0.20
        
        # v51: Build per-source frequency list (include 0 for sources without this entity)
        per_src_counts = [data["freq_per_source"].get(i, 0) for i in range(total_sources)]
        
        entity = TopicalEntity(
            text=lemma_key,
            display_text=most_common_form,
            type=entity_type,
            frequency=freq,
            sources_count=sources_count,
            importance=min(1.0, score),
            contexts=data["contexts"],
            variants=variants,
            freq_per_source=per_src_counts,
        )
        entities.append(entity)
    
    # Sortuj po importance
    entities.sort(key=lambda x: x.importance, reverse=True)
    
    print(f"[TOPICAL] ✅ Found {len(entities)} concept entities "
          f"(returning top {min(max_entities, len(entities))})")
    
    return entities[:max_entities]


# ================================================================
# 📊 CONCEPT ENTITY SUMMARY
# ================================================================

def generate_topical_summary(
    entities: List[TopicalEntity],
    main_keyword: str = "",
) -> Dict[str, Any]:
    """
    Generuje podsumowanie topical entities dla promptów SEO.
    """
    if not entities:
        return {
            "status": "NO_DATA",
            "concepts": [],
            "agent_instruction": "",
        }
    
    # Top concepts (high importance, multi-source)
    must_cover = [e for e in entities if e.sources_count >= 2 and e.importance >= 0.3]
    should_cover = [e for e in entities if e not in must_cover and e.importance >= 0.2]
    
    # Instruction for the writing agent
    concept_list = ", ".join([e.display_text for e in must_cover[:10]])
    should_list = ", ".join([e.display_text for e in should_cover[:8]])
    
    instruction_parts = []
    
    if must_cover:
        instruction_parts.append(
            f"🎯 KLUCZOWE POJĘCIA (występują u większości konkurencji — MUSISZ je wpleść): "
            f"{concept_list}"
        )
    
    if should_cover:
        instruction_parts.append(
            f"📌 DODATKOWE POJĘCIA (warto wspomnieć dla pełnego pokrycia tematu): "
            f"{should_list}"
        )
    
    instruction_parts.append(
        "💡 Użyj tych pojęć naturalnie w tekście — nie jako listy, "
        "ale wplecione w zdania. Google nagradza treści, które pokrywają "
        "pełne pole semantyczne tematu."
    )
    
    return {
        "status": "OK",
        "total_concepts": len(entities),
        "must_cover_count": len(must_cover),
        "should_cover_count": len(should_cover),
        "must_cover": [e.to_dict() for e in must_cover[:15]],
        "should_cover": [e.to_dict() for e in should_cover[:10]],
        "all_concepts": [e.display_text for e in entities[:30]],
        "agent_instruction": "\n".join(instruction_parts),
    }
