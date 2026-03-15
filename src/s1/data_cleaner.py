"""
===============================================================================
🧹 DATA CLEANER v1.0 — Czyszczenie danych na każdym etapie pipeline'u
===============================================================================
Obsługuje 5 warstw czyszczenia:

1. clean_scraped_content()  — HTML artefakty, nawigacja, footery, ciasteczka
2. clean_ngrams()           — nieistotne frazy, zbyt ogólne terminy
3. clean_entities()         — śmieci z NLP (CSS, JS, liczby, artefakty)
4. clean_h2_patterns()      — fałszywe H2 z competitorów
5. clean_s1_for_llm()       — przygotowanie S1 response przed wysłaniem do LLM

Używany w: analysis.py, scraper.py, entity_extractor.py, ngram_analyzer.py

Autor: BRAJEN Team
===============================================================================
"""

import re
from typing import List, Dict, Optional, Any

# ================================================================
# SHARED PATTERNS
# ================================================================

# Polskie stop words (rozszerzone)
_PL_STOP = {
    "i", "w", "na", "z", "do", "że", "się", "nie", "to", "jest", "za", "po",
    "od", "o", "jak", "ale", "co", "ten", "tym", "być", "może", "już", "tak",
    "gdy", "lub", "czy", "tego", "tej", "są", "dla", "ich", "przez", "jako",
    "te", "ze", "tych", "było", "ma", "przy", "które", "który", "która",
    "jego", "jej", "tego", "także", "więc", "tylko", "też", "sobie", "bardzo",
    "jeszcze", "wszystko", "przed", "między", "pod", "nad", "bez", "oraz",
    "gdzie", "kiedy", "ile", "jeśli", "jaki", "jaka", "jakie", "każdy",
    "każda", "każde", "inne", "inny", "inna", "więcej", "mniej", "tu", "tam",
    "tu", "sam", "sama", "samo", "nawet", "jednak", "chociaż", "dlatego",
}

# Angielskie stop words
_EN_STOP = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "this", "that", "these",
    "those", "it", "its", "their", "they", "we", "you", "he", "she", "i",
    "my", "your", "our", "his", "her", "more", "most", "some", "any",
    "all", "not", "no", "also", "just", "about", "up", "out", "as",
}

_ALL_STOP = _PL_STOP | _EN_STOP

# ================================================================
# 1. SCRAPED CONTENT CLEANER
# ================================================================

# Patterns wskazujące na nawigację / boilerplate
_NAV_PATTERNS = re.compile(
    r"(główna|strona główna|home|menu|nawigacja|breadcrumb|breadcrumbs|"
    r"szukaj|search|logowanie|rejestracja|konto|koszyk|cart|checkout|"
    r"polityka prywatności|regulamin|rodo|cookies|ciasteczka|zgoda|accept|"
    r"newsletter|zapisz się|subskrybuj|subscribe|"
    r"copyright|all rights reserved|wszelkie prawa|prawa autorskie|"
    r"telefon:|e-mail:|adres:|nip:|krs:|regon:|"
    r"facebook|twitter|instagram|linkedin|youtube|tiktok|"
    r"udostępnij|share|podziel się|komentarze|comments|"
    r"tagi:|kategorie:|tag:|category:|autor:|author:|"
    r"czytaj więcej|read more|dowiedz się więcej|sprawdź|kliknij tutaj|"
    # Gov/institutional site boilerplate
    r"mapa serwisu|mapa strony|nota prawna|redakcja serwisu|redakcja strony|"
    r"deklaracja dostępności|dostępność cyfrowa|wersja kontrastowa|"
    r"biuletyn informacji publicznej|biuletyn informacji|bip|"
    r"inne wersje portalu|inne wersje serwisu|wersja mobilna|"
    r"najważniejsze informacje|informacje o serwisie|o portalu|"
    r"kontakt z redakcją|zespół redakcyjny|"
    r"kanały rss|kanał rss|archiwum serwisu|archiwum bip|"
    r"wróć na górę|powrót do góry|do góry|przejdź do treści|skip to content|"
    r"powiększ czcionkę|pomniejsz czcionkę|rozmiar czcionki|"
    r"drukuj|wydrukuj|wersja do druku)",
    re.IGNORECASE
)

_COOKIE_PATTERNS = re.compile(
    r"(używamy plików cookie|używamy cookies|klikając.*zgadzasz|"
    r"ta strona używa|this site uses cookies|we use cookies|"
    r"zaakceptuj wszystkie|accept all|reject all|odrzuć wszystkie|"
    r"zarządzaj preferencjami|manage preferences|"
    r"niezbędne pliki|necessary cookies|analityczne|analytics cookies)",
    re.IGNORECASE
)

_BOILERPLATE_LINE_PATTERNS = re.compile(
    r"^(\s*[\|\-–—\•\*]+\s*){3,}$|"  # separatory graficzne
    r"^\s*\d{1,3}\s*$|"               # same liczby (numery stron)
    r"^\s*[A-Z\s]{1,4}\s*$|"          # bardzo krótkie all-caps (menu items)
    r"^\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{4}\s*$",  # daty
    re.IGNORECASE
)

# Linie "menu-like" — krótkie, powtarzające się
def _is_nav_line(line: str) -> bool:
    """Wykrywa linie nawigacyjne / menu."""
    stripped = line.strip()
    if len(stripped) < 3:
        return True
    if len(stripped) < 30 and stripped.endswith(("»", "›", "→", ">")):
        return True
    if _BOILERPLATE_LINE_PATTERNS.match(stripped):
        return True
    words = stripped.split()
    if len(words) <= 2 and all(w[0].isupper() for w in words if w.isalpha()):
        # Bardzo krótkie zdanie z Dużych liter = prawdopodobnie link nawigacyjny
        return True
    return False


def clean_scraped_content(raw_text: str, max_chars: int = 50_000) -> str:
    """
    Czyści scraped content ze śmieci: nawigacja, footery, cookie banners,
    boilerplate, artefakty HTML, separator linie.

    Args:
        raw_text: Surowy tekst ze scraperów (trafilatura lub regex fallback)
        max_chars: Max długość wyjścia

    Returns:
        Wyczyszczony tekst głównej treści
    """
    if not raw_text:
        return ""

    # ── Krok 1: Usuń typowe artefakty HTML ──
    text = raw_text
    text = re.sub(r"&amp;|&nbsp;|&lt;|&gt;|&quot;|&#\d+;|&[a-z]+;", " ", text)
    text = re.sub(r"\[\d+\]", "", text)                    # [1] [2] (przypisy)
    text = re.sub(r"\{\{[^}]+\}\}", "", text)              # {{template}}
    text = re.sub(r"https?://\S+", "", text)               # URL-e
    text = re.sub(r"\b[A-Z0-9]{20,}\b", "", text)         # base64/hash strings

    # ── Krok 2: Usuń cookie banners ──
    text = _COOKIE_PATTERNS.sub("", text)

    # ── Krok 3: Filtruj linie ──
    lines = text.splitlines()
    clean_lines = []
    skip_block = False
    block_skip_counter = 0

    for line in lines:
        stripped = line.strip()

        # Wykryj bloki do pominięcia (nawigacja, footer)
        if _NAV_PATTERNS.search(stripped) and len(stripped) < 80:
            skip_block = True
            block_skip_counter = 0
            continue

        if skip_block:
            block_skip_counter += 1
            if block_skip_counter > 3 and len(stripped) > 50:
                skip_block = False  # wróć do treści gdy linia jest długa
            elif block_skip_counter > 8:
                skip_block = False  # reset po 8 liniach w każdym razie
            else:
                continue

        if _is_nav_line(stripped):
            continue

        # Linia za krótka (1-2 słowa) bez treści informacyjnej
        if len(stripped.split()) < 2 and not re.search(r"\d", stripped):
            continue

        clean_lines.append(line)

    text = "\n".join(clean_lines)

    # ── Krok 4: Usuń nadmiarowe białe znaki ──
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()

    return text[:max_chars]


# ================================================================
# 2. N-GRAM CLEANER
# ================================================================

# N-gramy które wyglądają na śmieci pomimo przejścia przez spaCy
_NGRAM_GARBAGE_PATTERNS = re.compile(
    r"(pixel|viewport|charset|utf-8|html|css|javascript|jquery|"
    r"responsive|bootstrap|elementor|wordpress|plugin|widget|"
    r"class=|id=|href=|src=|data-|aria-|ng-|v-bind|"
    r"\bpx\b|\brem\b|\bem\b|\bvh\b|\bvw\b|"
    r"border-radius|background-color|font-size|line-height|"
    r"margin-top|padding-left|z-index|flex-wrap|"
    r"\bblock\b|\bcover\b|\bbackground\b|\bglobal\b|\bcolor\b|\bdim\b|\bast\b)",
    re.IGNORECASE
)

# N-gramy zbyt generyczne dla SEO (bez wartości topical)
_GENERIC_NGRAMS = {
    "dobra jakość", "wysoka jakość", "najlepsza jakość",
    "strona internetowa", "nasza strona", "nasz serwis",
    "kliknij tutaj", "dowiedz się więcej", "czytaj więcej",
    "skontaktuj się", "kontakt z nami", "skontaktuj się z nami",
    "darmowa dostawa", "szybka dostawa", "bezpłatna dostawa",
    "dobra cena", "najlepsza cena", "atrakcyjna cena",
    "zapraszamy do", "zapraszamy na",
    "polecamy również", "sprawdź też", "sprawdź nasze",
    "znajdziesz tutaj", "znajdziesz u nas",
    "high quality", "best quality", "click here", "learn more",
    "read more", "find out more", "contact us", "our website",
}


def clean_ngrams(
    ngrams: List[Dict],
    main_keyword: str = "",
    min_weight: float = 0.05,
    min_freq: int = 2,
) -> List[Dict]:
    """
    Czyści listę n-gramów z nieistotnych fraz.

    Usuwa:
    - CSS/JS artefakty
    - Generyczne frazy marketingowe
    - Frazy składające się tylko ze stop words
    - Frazy poniżej progu wagi/częstotliwości

    Args:
        ngrams: Lista dict z kluczami: ngram, weight, freq
        main_keyword: Główna fraza — jej części zawsze przepuszczamy
        min_weight: Minimalna waga do zachowania
        min_freq: Minimalne wystąpienia

    Returns:
        Wyczyszczona lista n-gramów
    """
    if not ngrams:
        return []

    kw_words = set(main_keyword.lower().split()) if main_keyword else set()
    clean = []

    for ng in ngrams:
        text = ng.get("ngram", "") or ng.get("text", "")
        if not text:
            continue

        text_lower = text.lower().strip()

        # ── Garbage patterns (CSS/JS) ──
        if _NGRAM_GARBAGE_PATTERNS.search(text_lower):
            continue

        # ── Navigation / boilerplate n-gram ──
        if _NAV_PATTERNS.search(text_lower):
            # Allow if keyword overlap exists (topic might genuinely include nav words)
            ngram_words = set(re.findall(r'\b[a-ząćęłńóśźż]+\b', text_lower))
            if not (ngram_words & kw_words):
                continue

        # ── Generyczne frazy ──
        if text_lower in _GENERIC_NGRAMS:
            continue

        # ── Zbyt krótki ──
        if len(text_lower) < 4:
            continue

        # ── Tylko stop words ──
        words = set(re.findall(r'\b[a-ząćęłńóśźż]+\b', text_lower))
        meaningful_words = words - _ALL_STOP
        if not meaningful_words:
            continue

        # ── Zawiera znaki specjalne (CSS values etc.) ──
        if re.search(r'[{};:=<>@#$%^&*()\\]', text):
            continue

        # ── Liczby bez kontekstu ──
        if re.match(r'^\d+(\.\d+)?(\s+\d+(\.\d+)?)*$', text_lower.strip()):
            continue

        # ── Minimalny próg ──
        weight = ng.get("weight", 1.0)
        freq = ng.get("freq", ng.get("freq_total", 1))

        # Przepuść jeśli zawiera słowa z main keyword (always relevant)
        kw_overlap = words & kw_words
        if not kw_overlap:
            if weight < min_weight or freq < min_freq:
                continue

        # ── Outlier freq filter: artefakty jednej strony z nienaturalną częstotliwością ──
        # Parsujemy sources_count z site_distribution ("1/6" → 1) bo ngram dict
        # nie ma klucza sources_count — tylko site_distribution jako string.
        if not kw_overlap:
            freq_min_v = ng.get("freq_min", 0)
            freq_max_v = ng.get("freq_max", 0)
            site_dist = ng.get("site_distribution", "1/1")
            try:
                sources_count_v = int(str(site_dist).split("/")[0])
            except (ValueError, IndexError):
                sources_count_v = 1
            # Artefakt: jednoźródłowy z wysoką powtarzalnością (CSS/JS template)
            if sources_count_v == 1 and freq_min_v >= 20:
                continue
            # Artefakt: freq_min == freq_max → identyczna freq we wszystkich źródłach = szablon
            if freq_min_v > 0 and freq_min_v == freq_max_v and freq_min_v >= 15 and sources_count_v <= 2:
                continue

        clean.append(ng)

    return clean


# ================================================================
# 3. ENTITY CLEANER
# ================================================================

# Encje które są ewidentnymi artefaktami NLP
_ENTITY_GARBAGE_PATTERNS = re.compile(
    r"^(\d+[\.,]\d+|\d+px|\d+%|\d+em|\d+rem|0\.\d+|#[0-9a-f]{3,6})$|"
    r"(rgba?|hsla?|var\(|calc\(|url\()|"
    r"\b(px|em|rem|vh|vw|pt|cm|mm|ch)\b$|"
    r"^[a-z]+-[a-z]+-[a-z]+$|"     # CSS multi-hyphen class names
    r"^[A-Z_]{3,}$|"                # ALLCAPS_CONSTANTS
    r"^\w+\.\w+\.\w+",              # dotted namespace
    re.IGNORECASE
)

# Encje zbyt ogólne (bez wartości SEO)
_GENERIC_ENTITIES = {
    "rok", "lat", "czas", "miejsce", "sposób", "część", "wynik",
    "dane", "informacje", "treść", "tekst", "artykuł", "strona",
    "year", "time", "place", "way", "part", "result", "data",
    "information", "content", "text", "article", "page", "site",
    "inne", "więcej", "różne", "nowe", "nowy", "nowa",
    "dobry", "dobra", "dobre", "duży", "duża", "duże", "mały",
}


def clean_entities(
    entities: List[Dict],
    main_keyword: str = "",
    min_salience: float = 0.01,
    min_text_len: int = 3,
    max_text_len: int = 80,
) -> List[Dict]:
    """
    Czyści listę encji z NLP-śmieci.

    Usuwa:
    - CSS/JS wartości
    - Liczby bez kontekstu
    - Encje zbyt krótkie / zbyt długie
    - Encje ogólne bez wartości SEO
    - Encje z symbolami specjalnymi

    Args:
        entities: Lista dict z kluczami: text, salience, type itd.
        main_keyword: Główna fraza — jej części zawsze zachowujemy
        min_salience: Minimalna salience do zachowania (0.0–1.0)
        min_text_len: Minimalna długość tekstu encji
        max_text_len: Maksymalna długość

    Returns:
        Wyczyszczona lista encji
    """
    if not entities:
        return []

    kw_words = set(main_keyword.lower().split()) if main_keyword else set()
    seen_texts = set()
    clean = []

    for ent in entities:
        text = ent.get("text", "") or ent.get("entity", "")
        if not text:
            continue

        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        # ── Duplikaty ──
        if text_lower in seen_texts:
            continue

        # ── Długość ──
        if len(text_stripped) < min_text_len or len(text_stripped) > max_text_len:
            continue

        # ── Garbage patterns ──
        if _ENTITY_GARBAGE_PATTERNS.search(text_stripped):
            continue

        # ── Znaki specjalne (CSS/code) ──
        if re.search(r'[{};:=<>@#$%^*()\\|/]', text_stripped):
            continue

        # ── Tylko cyfry / interpunkcja ──
        if not re.search(r'[a-ząćęłńóśźżA-ZĄĆĘŁŃÓŚŹŻ]', text_stripped):
            continue

        # ── Zbyt generyczne ──
        if text_lower in _GENERIC_ENTITIES:
            continue

        # ── Tylko stop words ──
        words = set(re.findall(r'\b[a-ząćęłńóśźż]+\b', text_lower))
        if words and not (words - _ALL_STOP):
            continue

        # ── Salience ──
        salience = ent.get("salience", ent.get("relevance", 1.0))
        try:
            salience = float(salience)
        except (TypeError, ValueError):
            salience = 0.5

        # Zawsze zachowaj jeśli zawiera słowa z keyword
        kw_overlap = words & kw_words
        if not kw_overlap and salience < min_salience:
            continue

        seen_texts.add(text_lower)
        clean.append(ent)

    return clean


# ================================================================
# 4. H2 PATTERNS CLEANER
# ================================================================

# H2 które są śmieciami (nawigacja, boilerplate, błędy scrapera)
_H2_GARBAGE_PATTERNS = re.compile(
    r"(404|error|not found|page not found|"
    r"cookies|cookie policy|privacy policy|gdpr|rodo|"
    r"menu|navigation|navbar|sidebar|footer|header|"
    r"advertisement|reklama|sponsored|sponsorowane|"
    r"recent posts|ostatnie wpisy|related posts|powiązane|"
    r"leave a comment|zostaw komentarz|comments|komentarze|"
    r"share this|udostępnij|social media|"
    r"subscribe|newsletter|zapisz się|"
    r"loading\.\.\.|please wait|ładowanie|"
    r"javascript|jquery|css|html|php|sql)",
    re.IGNORECASE
)

# H2 zbyt krótkie by być sensownym nagłówkiem
_H2_MIN_WORDS = 2
_H2_MAX_WORDS = 15
_H2_MIN_CHARS = 8
_H2_MAX_CHARS = 120


def clean_h2_patterns(
    h2_patterns: List[str],
    main_keyword: str = "",
    deduplicate: bool = True,
) -> List[str]:
    """
    Czyści listę H2 z fałszywych nagłówków.

    Usuwa:
    - Nawigację / menu items
    - Cookie banners / GDPR
    - Zbyt krótkie lub zbyt długie (nie nagłówki)
    - Duplikaty (case-insensitive)
    - Artefakty scrapera (CSS, JS)
    - H2 składające się tylko ze stop words

    Args:
        h2_patterns: Surowe H2 zebrane ze stron konkurencji
        main_keyword: Do priorytetyzacji
        deduplicate: Czy usuwać duplikaty case-insensitive

    Returns:
        Wyczyszczona lista H2
    """
    if not h2_patterns:
        return []

    seen = set()
    clean = []

    for h2 in h2_patterns:
        if not h2:
            continue

        h2_stripped = h2.strip()
        h2_lower = h2_stripped.lower()

        # ── Długość ──
        if len(h2_stripped) < _H2_MIN_CHARS or len(h2_stripped) > _H2_MAX_CHARS:
            continue

        words = h2_stripped.split()
        if len(words) < _H2_MIN_WORDS or len(words) > _H2_MAX_WORDS:
            continue

        # ── Garbage patterns ──
        if _H2_GARBAGE_PATTERNS.search(h2_stripped):
            continue

        # ── Znaki specjalne (CSS/code artefakty) ──
        if re.search(r'[{};=<>@#$%^*\\|]', h2_stripped):
            continue

        # ── URL fragments ──
        if re.search(r'https?://|www\.', h2_lower):
            continue

        # ── Tylko cyfry ──
        if re.match(r'^[\d\s\.,\-]+$', h2_stripped):
            continue

        # ── Tylko stop words ──
        word_set = set(re.findall(r'\b[a-ząćęłńóśźż]+\b', h2_lower))
        if word_set and not (word_set - _ALL_STOP):
            continue

        # ── Duplikaty ──
        if deduplicate:
            # Normalizuj do deduplication key (lowercase, bez znaków)
            dedup_key = re.sub(r'[^a-ząćęłńóśźż0-9\s]', '', h2_lower).strip()
            dedup_key = re.sub(r'\s+', ' ', dedup_key)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

        clean.append(h2_stripped)

    return clean


# ================================================================
# 5. S1 RESPONSE CLEANER (przed wysłaniem do LLM)
# ================================================================

# Pola które LLM nie potrzebuje (techniczne, debugging, raw data)
_STRIP_FROM_LLM = {
    "full_text_sample",
    "serp_content",
    "all_text_content",
    "raw_html",
    "debug",
    "status",
    "error",
    "ngram_lemma",
    "freq_per_source",
    "embedding",
    "embeddings",
}

# Maksymalne rozmiary list (LLM nie potrzebuje 50 n-gramów)
_LLM_LIST_LIMITS = {
    "ngrams": 25,
    "extended_terms": 15,
    "h2_patterns": 20,
    "h2_scored_candidates": 15,
    "entities": 20,
    "concept_entities": 20,
    "paa_unanswered": 8,
    "subtopic_missing": 8,
    "depth_missing": 5,
    "all_gaps": 15,
    "semantic_gaps": 10,
    "entity_cooccurrence": 15,
    "topical_clusters": 8,
    "serp_snippets": 5,
    "competitors": 10,
}

# Pola wewnątrz n-gramów które LLM nie potrzebuje
_NGRAM_STRIP_KEYS = {
    "ngram_lemma", "freq_per_source", "freq_total",
    "is_high_signal", "site_distribution",
}

# Pola wewnątrz encji które LLM nie potrzebuje
_ENTITY_STRIP_KEYS = {
    "embedding", "raw_mentions", "source_indices",
    "chunk_count", "sentence_positions",
}


def _trim_list(data: Any, key: str) -> Any:
    """Przytnij listę do limitu dla danego klucza."""
    if isinstance(data, list) and key in _LLM_LIST_LIMITS:
        return data[:_LLM_LIST_LIMITS[key]]
    return data


def _strip_dict_keys(d: dict, strip_keys: set) -> dict:
    """Usuń niepotrzebne klucze ze słownika."""
    return {k: v for k, v in d.items() if k not in strip_keys}


def _clean_ngram_list(ngrams: List[Dict]) -> List[Dict]:
    """Uproszcz n-gramy dla LLM — tylko niezbędne pola."""
    clean = []
    for ng in (ngrams or []):
        if not isinstance(ng, dict):
            continue
        simplified = {
            "ngram": ng.get("ngram", ng.get("text", "")),
            "weight": ng.get("weight", 0),
            "freq": ng.get("freq", 0),
        }
        if ng.get("freq_min") is not None:
            simplified["range"] = f"{ng.get('freq_min', 0)}-{ng.get('freq_max', 0)}"
        clean.append(simplified)
    return clean


def _clean_entity_list(entities: List[Dict]) -> List[Dict]:
    """Uproszcz encje dla LLM — tylko niezbędne pola."""
    clean = []
    for e in (entities or []):
        if not isinstance(e, dict):
            clean.append(e)
            continue
        simplified = {k: v for k, v in e.items() if k not in _ENTITY_STRIP_KEYS}
        clean.append(simplified)
    return clean


def clean_s1_for_llm(s1_data: Dict, max_total_chars: int = 60_000) -> Dict:
    """
    Czyści i optymalizuje S1 response przed wysłaniem do LLM.

    Usuwa:
    - Techniczne/debugowe pola
    - Surowe teksty (full_text_sample etc.)
    - Nadmiarowe wpisy w listach
    - Klucze wewnętrzne n-gramów i encji

    Zachowuje:
    - Wszystkie sygnały SEO (n-gramy, encje, H2, gaps)
    - Statystyki i metadane
    - Instrukcje agenta (agent_instruction)

    Args:
        s1_data: Pełny output z run_s1_analysis()
        max_total_chars: Limit znaków całego JSON output

    Returns:
        Zoptymalizowany dict gotowy do wysłania do LLM
    """
    if not s1_data or not isinstance(s1_data, dict):
        return s1_data

    clean = {}

    for key, value in s1_data.items():

        # ── Usuń techniczne pola ──
        if key in _STRIP_FROM_LLM:
            continue

        # ── N-gramy — uproszcz i przytnij ──
        if key == "ngrams":
            clean[key] = _clean_ngram_list(_trim_list(value, key))
            continue

        if key == "extended_terms":
            clean[key] = _clean_ngram_list(_trim_list(value, key))
            continue

        # ── H2 patterns — przytnij ──
        if key == "h2_patterns":
            clean[key] = _trim_list(value, key)
            continue

        # ── Entity SEO — wyczyść ──
        if key == "entity_seo" and isinstance(value, dict):
            ent_clean = {}
            for ek, ev in value.items():
                if ek in _STRIP_FROM_LLM:
                    continue
                if ek == "entities":
                    ent_clean[ek] = _clean_entity_list(_trim_list(ev, ek))
                elif ek == "concept_entities":
                    ent_clean[ek] = _clean_entity_list(_trim_list(ev, ek))
                elif ek == "entity_cooccurrence":
                    ent_clean[ek] = _trim_list(ev, ek)
                elif isinstance(ev, list):
                    ent_clean[ek] = _trim_list(ev, ek)
                else:
                    ent_clean[ek] = ev
            clean[key] = ent_clean
            continue

        # ── Content gaps — przytnij listy ──
        if key == "content_gaps" and isinstance(value, dict):
            gaps_clean = {}
            for gk, gv in value.items():
                if gk in _STRIP_FROM_LLM:
                    continue
                if isinstance(gv, list):
                    gaps_clean[gk] = _trim_list(gv, gk)
                else:
                    gaps_clean[gk] = gv
            clean[key] = gaps_clean
            continue

        # ── SERP analysis — przytnij snippety i competitors ──
        if key == "serp_analysis" and isinstance(value, dict):
            serp_clean = {}
            for sk, sv in value.items():
                if sk in _STRIP_FROM_LLM:
                    continue
                if isinstance(sv, list):
                    serp_clean[sk] = _trim_list(sv, sk)
                else:
                    serp_clean[sk] = sv
            clean[key] = serp_clean
            continue

        # ── H2 scored candidates ──
        if key == "h2_scored_candidates" and isinstance(value, dict):
            h2c_clean = {}
            for hk, hv in value.items():
                if isinstance(hv, list):
                    h2c_clean[hk] = _trim_list(hv, "h2_scored_candidates")
                    # Usuń verbose reason z każdego kandidata
                    if hk in ("must_have", "high_priority", "optional", "all_candidates"):
                        h2c_clean[hk] = [
                            {k2: v2 for k2, v2 in c.items() if k2 != "reason"}
                            if isinstance(c, dict) else c
                            for c in h2c_clean[hk]
                        ]
                else:
                    h2c_clean[hk] = hv
            clean[key] = h2c_clean
            continue

        # ── Listy generyczne — przytnij ──
        if isinstance(value, list) and key in _LLM_LIST_LIMITS:
            clean[key] = _trim_list(value, key)
            continue

        # ── Puste wartości — pomiń ──
        if value is None or value == [] or value == {}:
            continue

        clean[key] = value

    return clean


# ================================================================
# CONVENIENCE: CLEAN ALL AT ONCE
# ================================================================

def clean_all(
    scraped_content: Optional[str] = None,
    ngrams: Optional[List[Dict]] = None,
    entities: Optional[List[Dict]] = None,
    h2_patterns: Optional[List[str]] = None,
    s1_data: Optional[Dict] = None,
    main_keyword: str = "",
) -> Dict:
    """
    Czyści wszystkie warstwy danych naraz.

    Returns:
        Dict z wyczyszczonymi danymi dla każdej warstwy
    """
    result = {}

    if scraped_content is not None:
        result["scraped_content"] = clean_scraped_content(scraped_content)

    if ngrams is not None:
        result["ngrams"] = clean_ngrams(ngrams, main_keyword)

    if entities is not None:
        result["entities"] = clean_entities(entities, main_keyword)

    if h2_patterns is not None:
        result["h2_patterns"] = clean_h2_patterns(h2_patterns, main_keyword)

    if s1_data is not None:
        result["s1_for_llm"] = clean_s1_for_llm(s1_data)

    return result


__all__ = [
    "clean_scraped_content",
    "clean_ngrams",
    "clean_entities",
    "clean_h2_patterns",
    "clean_s1_for_llm",
    "clean_all",
]
