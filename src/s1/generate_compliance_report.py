import re
import json
from rapidfuzz import fuzz  # nowa biblioteka do fuzzy matchy

# --- Stałe dla fuzzy-matching ---
FUZZY_SIMILARITY_THRESHOLD = 90  # próg podobieństwa 0–100
MAX_FUZZY_WINDOW_EXPANSION = 2   # max ile dodatkowych lematów może wejść „w środek” frazy


# --- Ładowanie modelu (lazy — nie ładuj przy imporcie modułu) ---
_get_nlp = None
NLP = None

def _load_nlp():
    """Lazy singleton — ładowany dopiero przy pierwszym użyciu."""
    global NLP, _get_nlp
    if NLP is not None:
        return NLP
    try:
        from src.common.nlp_singleton import get_nlp as _get_nlp
    except ImportError:
        try:
            from api.nlp_singleton import get_nlp as _get_nlp
        except ImportError:
            from nlp_singleton import get_nlp as _get_nlp
    NLP = _get_nlp()
    return NLP


# --- Funkcja pomocnicza (Lematyzacja) ---
def _lemmatize_text_to_list(text):
    """Zwraca listę lematów z tekstu (tylko tokeny alfabetyczne)."""
    doc = _load_nlp()(text.lower())
    return [token.lemma_ for token in doc if token.is_alpha]


# --- NOWA FUNKCJA: parser stanu ---
def _parse_keyword_state(keyword_state_input):
    """
    Parsuje stan słów kluczowych.
    Wejście może być stringiem (brief S2) lub obiektem (poprzedni stan).
    Zawsze zwraca obiekt (słownik) formatu: {'fraza': {'min': X, 'max': Y}}
    """
    keywords_with_ranges = {}
    
    # Przypadek 1: Wejście to string (pierwsze wywołanie z S2)
    if isinstance(keyword_state_input, str):
        for line in keyword_state_input.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Format "słowo: min-max"
            match = re.match(
                r'^(.*?):\s*(\d+)\s*(?:-|–|—)\s*(\d+)\s*x?$',
                line,
                re.IGNORECASE
            )
            if match:
                kw, min_val, max_val = match.groups()
                keywords_with_ranges[kw.strip()] = {
                    "min": int(min_val),
                    "max": int(max_val)
                }
                continue

            # Format "słowo: max"
            match = re.match(r'^(.*?):\s*(\d+)\s*x?$', line, re.IGNORECASE)
            if match:
                kw, max_val = match.groups()
                keywords_with_ranges[kw.strip()] = {
                    "min": 1,
                    "max": int(max_val)
                }
                continue

            # Format "słowo" (bez zakresu)
            if ':' not in line and line:
                keywords_with_ranges[line] = {"min": 1, "max": 99}
        return keywords_with_ranges
    
    # Przypadek 2: Wejście to już obiekt (kolejne wywołania)
    elif isinstance(keyword_state_input, dict):
        # Walidacja, czy format jest poprawny
        if all(isinstance(v, dict) and 'min' in v and 'max' in v
               for v in keyword_state_input.values()):
            return keyword_state_input
        else:
            raise ValueError(
                "Niepoprawny format obiektu 'keyword_state'. "
                "Oczekiwano {'kw': {'min': x, 'max': y}}."
            )
    
    else:
        raise ValueError(
            "Niepoprawny typ 'keyword_state'. "
            "Oczekiwano stringa lub obiektu."
        )


# --- NOWA FUNKCJA: fuzzy-match na lematyzowanym tekście ---
def _count_fuzzy_matches(
    keyword_lemmas,
    text_lemmas,
    exact_spans,
    max_hits,
    threshold=FUZZY_SIMILARITY_THRESHOLD,
    max_expansion=MAX_FUZZY_WINDOW_EXPANSION,
):
    """
    Liczy dodatkowe (fuzzy) trafienia frazy w lematyzowanym tekście.
    - keyword_lemmas: lista lematów frazy, np. ["adwokat", "rozwodowy", "warszawa"]
    - text_lemmas: lista lematów tekstu batcha
    - exact_spans: lista (start, end) dla exact matchy (żeby ich nie dublować)
    - max_hits: ile fuzzy trafień maksymalnie możemy jeszcze doliczyć
    """
    if max_hits <= 0:
        return 0

    kw_len = len(keyword_lemmas)
    text_len = len(text_lemmas)
    if kw_len == 0 or text_len == 0:
        return 0

    kw_str = " ".join(keyword_lemmas)

    # Zajęte pozycje (exact matche), nie dublujemy ich dla fuzzy
    used_positions = set()
    for s, e in exact_spans:
        used_positions.update(range(s, e))

    fuzzy_count = 0

    # Szukamy okien od długości kw_len do kw_len + max_expansion
    for start in range(text_len):
        # Minimalna długość okna to kw_len
        for extra in range(max_expansion + 1):
            end = start + kw_len + extra
            if end > text_len:
                break

            window_positions = range(start, end)
            # Jeśli okno nachodzi na exact match – pomijamy
            if any(pos in used_positions for pos in window_positions):
                continue

            window_str = " ".join(text_lemmas[start:end])
            score = fuzz.token_set_ratio(kw_str, window_str)

            if score >= threshold:
                fuzzy_count += 1
                used_positions.update(window_positions)
                # Nie przekraczamy maksymalnej liczby fuzzy-hits
                if fuzzy_count >= max_hits:
                    return fuzzy_count
                # Jeżeli złapaliśmy match w tym starcie, nie badamy dłuższych okien
                break

    return fuzzy_count


# --- Główna funkcja (wersja STANOWA) ---
def generate_compliance_report(text_to_process, keyword_state_input):
    """
    Generuje raport zgodności i ZWRACA NOWY STAN.
    Liczy słowa tylko w podanym 'text_to_process' (batchu).
    Odejmuje policzone słowa od stanu 'keyword_state_input'.
    Teraz:
      - najpierw liczy exact match (na lematy),
      - potem fuzzy match (rapidfuzz) na lematyzowanym tekście,
        z limitem do pozostałego 'max'.
    """

    # === 1. PARSOWANIE STANU ===
    try:
        # Wczytujemy pulę, jaka nam pozostała
        current_state = _parse_keyword_state(keyword_state_input)
    except Exception as e:
        return {"error": str(e), "new_keyword_state": keyword_state_input}

    # Jeśli tekst jest pusty, nie rób nic, zwróć ten sam stan
    if not text_to_process:
        empty_report = [{
            "keyword": kw,
            "range_remaining": f"{v['min']}-{v['max']}",
            "actual_in_batch": 0,
            "status": "OK"  # nic się nie stało
        } for kw, v in current_state.items()]
        return {
            "compliance_report": empty_report,
            "new_keyword_state": current_state
        }

    # === 2. ANALIZA NLP (tylko bieżący batch) ===
    text_lemmas = _lemmatize_text_to_list(text_to_process)
    text_lemmas_len = len(text_lemmas)

    # === 3. LOGIKA LICZENIA (batch) i AKTUALIZACJA STANU ===
    compliance_report_batch = []
    new_keyword_state = {}

    for keyword, ranges in current_state.items():
        min_val, max_val = ranges["min"], ranges["max"]

        # Lematyzacja frazy kluczowej
        keyword_lemmas = _lemmatize_text_to_list(keyword)
        kw_len = len(keyword_lemmas)
        actual_count_in_batch = 0  # licznik tylko dla tego batcha

        exact_spans = []

        if kw_len > 0:
            # --- 3a. EXACT MATCH NA LEMATY ---
            for i in range(text_lemmas_len - kw_len + 1):
                if text_lemmas[i:i + kw_len] == keyword_lemmas:
                    actual_count_in_batch += 1
                    exact_spans.append((i, i + kw_len))

            # --- 3b. FUZZY MATCH (tylko jeśli mamy jeszcze „miejsce” w max) ---
            remaining_room = max_val - actual_count_in_batch
            if remaining_room > 0:
                fuzzy_hits = _count_fuzzy_matches(
                    keyword_lemmas=keyword_lemmas,
                    text_lemmas=text_lemmas,
                    exact_spans=exact_spans,
                    max_hits=remaining_room,
                )
                actual_count_in_batch += fuzzy_hits

        # Obliczanie statusu dla BIEŻĄCEGO batcha
        # (czy nie przekroczył puli max, liczonej na wejściu batcha)
        status = "OK"
        if actual_count_in_batch > max_val:
            status = "OVER"  # użyto w batchu więcej niż pozostało w puli

        # Tworzenie raportu dla batcha
        compliance_report_batch.append({
            "keyword": keyword,
            "range_remaining": f"{min_val}-{max_val}",  # cel na początku batcha
            "actual_in_batch": actual_count_in_batch,
            "status": status
        })

        # Tworzenie NOWEGO STANU na następny batch
        # Odejmujemy to, co zużyliśmy w tym batchu
        new_min = max(0, min_val - actual_count_in_batch)  # min nie może spaść poniżej 0
        new_max = max(0, max_val - actual_count_in_batch)  # max nie może spaść poniżej 0

        if new_min > new_max:
            # Wyrównujemy, jeśli min > max (asekuracja)
            new_max = new_min

        new_keyword_state[keyword] = {
            "min": new_min,
            "max": new_max
        }

    return {
        "compliance_report": compliance_report_batch,
        "new_keyword_state": new_keyword_state  # zaktualizowana pula
    }
