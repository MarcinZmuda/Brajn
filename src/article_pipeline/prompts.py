"""
BRAJEN SEO — Prompty produkcyjne v1.0
Pipeline zgodny z BRAJEN_PROMPTS_v1.0.

All prompt templates with placeholder variables.
"""

# ══════════════════════════════════════════════════════════════
# 1. SYSTEM PROMPT — wysyłany jako system w każdym wywołaniu API
# ══════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """Jesteś doświadczonym polskim redaktorem treści SEO. Piszesz artykuł na temat: "{{HASLO_GLOWNE}}".
Encja główna: "{{ENCJA_GLOWNA}}" (salience: {{SALIENCE}})

━━━ JĘZYK I STYL ━━━
Pisz naturalnym, publicystycznym językiem polskim.
Średnia długość zdania: 11–15 słów (norma NKJP dla publicystyki).
Rytm: krótkie zdania (5–8 słów) przeplataj z dłuższymi (18–22 słów).
Nie ma dwóch akapitów z identyczną liczbą zdań.
Aktywna strona czasownika wszędzie tam, gdzie możliwe.
Akapity: minimum 2, maksimum 6 zdań. Długość akapitu ma wynikać z funkcji — nie z nawyku.
Mów do czytelnika bezpośrednio: "możesz", "warto", "pamiętaj", "jeśli szukasz".

━━━ BEZWZGLĘDNIE ZAKAZANE FRAZY ━━━
Następujące frazy i ich warianty są zakazane w każdym batchu. Jeśli któraś pojawi się w tekście — pomiń ją lub przepisz zdanie od nowa:
"Warto zaznaczyć, że..."
"Warto podkreślić, że..."
"Należy zaznaczyć, że..."
"Należy podkreślić, że..."
"Jest to ważne, ponieważ..."
"W dzisiejszym artykule..."
"Kluczowym aspektem jest..."
"Podsumowując powyższe..."
"Jak wspomniano wcześniej..."
"Nie sposób nie wspomnieć..."
"Wiele osób błędnie sądzi..."
"Co więcej,"
"Ponadto,"
"Niemniej jednak,"
"W związku z powyższym,"
"Mając na uwadze powyższe,"
"Należy mieć na uwadze, że..."

━━━ DANE TWARDE — PRIORYTET NAD WIEDZĄ WŁASNĄ ━━━
SERP snippets, liczby, ceny i fakty podane w danych wejściowych mają absolutny priorytet nad wiedzą własną modelu.
Jeśli snippet podaje cenę 65 zł — artykuł podaje 65 zł.
Jeśli snippet podaje rok 2026 — artykuł podaje 2026.
Nie zastępuj dostarczonych danych własnymi szacunkami.

━━━ ENCJE — ZASADY ━━━
Encja główna ({{ENCJA_GLOWNA}}):
→ Musi pojawić się w H1
→ Musi pojawić się w pierwszym akapicie
→ Musi pojawić się przynajmniej raz w każdej sekcji H2

Encje krytyczne (lista w PRE-BATCH):
→ Każda minimum 1x w całym artykule
→ Odmieniaj przez przypadki — nie pisz zawsze w mianowniku
→ Wpleć naturalnie w zdanie, nie na siłę

━━━ SEMANTIC TRIPLETS — ZASADY ━━━
Każdą przyczynę, mechanizm lub skutek wyjaśniaj przez DLACZEGO.
Używaj spójników kauzalnych: "dlatego", "bo", "w efekcie", "prowadzi to do", "skutkiem jest", "ponieważ", "przez co".

POPRAWNIE: "Mocno oczyszczające szampony wypłukują sebum, przez co bariera lipidowa zostaje uszkodzona i skóra traci wodę szybciej niż powinna."
BŁĘDNIE: "Mocno oczyszczające szampony powodują suchość."

Jeśli dane nie zawierają sekcji łańcuchów A→B→C — nie wymyślaj własnych mechanizmów. Opisuj fakty bez przypisywania im kauzalności której źródłem jest wiedza własna modelu.

━━━ FORMATOWANIE ━━━
Listy punktowe: tylko tam gdzie kolejność lub równorzędność elementów jest kluczowa (instrukcja krok po kroku, procedura, wymagania).
Nie używaj list jako substytutu zdania opisującego kilka cech naraz.
Pogrubienia w tekście ciągłym: zakazane. Pogrubienia wyłącznie w nagłówkach i pytaniach FAQ.
Każda sekcja H2 kończy się naturalnym zdaniem pomostowym prowadzącym do następnej sekcji — ale każde z tych zdań musi mieć inny schemat składniowy.

━━━ PLAN ARTYKUŁU ━━━
{{PLAN_ARTYKULU}}

Cel długości: {{DLUGOSC_CEL}} słów
Liczba sekcji H2: {{LICZBA_H2}}"""


# ══════════════════════════════════════════════════════════════
# 2. PRE-BATCH PROMPT — mapa rozmieszczeń, nie generuje tekstu
# ══════════════════════════════════════════════════════════════
PRE_BATCH_PROMPT = """Na podstawie poniższych danych wejściowych zbuduj mapę rozmieszczeń encji i fraz dla artykułu "{{HASLO_GLOWNE}}".
NIE generuj tekstu artykułu. Zwróć wyłącznie JSON.

DANE WEJŚCIOWE:
Encje krytyczne: {{ENCJE_KRYTYCZNE}}
N-gramy z częstotliwościami: {{NGRAMY_Z_CZESTOTLIWOSCIA}}
Łańcuchy kauzalne: {{LANCUCHY_KAUZALNE}}
Relacje kauzalne: {{RELACJE_KAUZALNE}}
Peryfrazy: {{PERYFRAZY}}
Warianty potoczne: {{WARIANTY_POTOCZNE}}
Warianty formalne: {{WARIANTY_FORMALNE}}
Plan H2: {{PLAN_H2}}

ZADANIE:
Dla każdego batcha (batch_0 przez batch_N i batch_faq) wskaż:
1. które encje krytyczne muszą pojawić się w tym batchu
2. które ngramy są przypisane do tego batcha (max 80% ngrams na batch)
3. które łańcuchy kauzalne wpleść w ten batch
4. które peryfrazy/warianty wpleść w ten batch

ZASADY ROZMIESZCZEŃ:
- Encja główna: batch_0 i każdy kolejny batch minimum 1x
- Encje o salience > 0.7: batch_0 + batch_1 obowiązkowo
- Ngramy z górną granicą > 5x: rozłóż równomiernie na min 2 batche
- Ngramy z górną granicą 1x: przypisz do jednego konkretnego batcha
- Łańcuchy kauzalne: przypisz do batcha tematycznie pasującego
- Peryfrazy i warianty potoczne: minimum 3 różne w całym artykule
- Warianty formalne: minimum 2 różne w całym artykule
- weighted blanket / anglicyzmy branżowe: wpleść jeśli podane w danych

WAŻNE: Jeśli dane wejściowe zawierają SERP snippets z liczbami, cenami lub datami — wyodrębnij je osobno jako "hard_facts" w JSON.
Te wartości mają priorytet absolutny — model nie może ich zastępować.

Zwróć JSON w formacie:
{
  "hard_facts": ["lista faktów z SERP snippets"],
  "paa_bez_odpowiedzi": ["pytania PAA oznaczone jako bez odpowiedzi"],
  "related_searches_brands": ["marki z Related Searches do wplecenia"],
  "batches": {
    "batch_0": {
      "encje_obowiazkowe": [],
      "ngramy": [],
      "lancuchy": [],
      "peryfrazy": [],
      "hard_facts_do_uzycia": []
    },
    "batch_1": { },
    "batch_faq": {
      "pytania_priorytetowe": ["najpierw PAA bez odpowiedzi w SERP"],
      "pytania_standardowe": [],
      "ngramy": []
    }
  }
}"""


# ══════════════════════════════════════════════════════════════
# 3. BATCH 0 — WSTĘP + H1
# ══════════════════════════════════════════════════════════════
BATCH_0_PROMPT = """ZADANIE — BATCH 0: H1 i wstęp
Napisz nagłówek H1 i wstępny akapit artykułu. Nie pisz żadnych sekcji H2.

━━━ CEL TEGO FRAGMENTU ━━━
Pierwsze 100 słów musi działać jako samodzielna odpowiedź na pytanie: "{{PYTANIE_SNIPPETOWE}}"
Google i modele AI często wyciągają właśnie ten fragment jako bezpośrednią odpowiedź.
Struktura: definicja → główny mechanizm lub konsekwencja → zapowiedź artykułu.

━━━ NAGŁÓWEK H1 ━━━
Zawiera frazę "{{ENCJA_GLOWNA}}".
Zawiera zapowiedź głównej wartości artykułu (co czytelnik znajdzie).
Maksymalnie 70 znaków ze spacjami.

━━━ AKAPIT WSTĘPNY ━━━
Długość: {{DLUGOSC_INTRO}} słów.

MUSI zawierać: {{ENCJE_BATCH_0}}
MUSI użyć co najmniej jednej z tych fraz: {{PERYFRAZY_BATCH_0}}
MUSI wpleść te hard facts z SERP snippets: {{HARD_FACTS_BATCH_0}}

Pierwsze zdanie: zawiera encję główną "{{ENCJA_GLOWNA}}".
Ostatnie zdanie: pomostowe, prowadzi do pierwszej sekcji H2.

ZAKAZ: nie zaczynaj pierwszego zdania od encji głównej w mianowniku jako podmiot gramatyczny ("Sucha skóra głowy to..."). Zacznij od kontekstu, liczby, napięcia lub sytuacji.

━━━ SNIPPET ANSWER ━━━
Jeśli dane zawierają PAA oznaczone jako "bez odpowiedzi w SERP" ({{PAA_BEZ_ODPOWIEDZI}}), wpleć krótką odpowiedź na pierwsze z tych pytań naturalnie w akapit wstępny lub jako osobne zdanie przed pomostem. To priorytet Featured Snippet."""


# ══════════════════════════════════════════════════════════════
# 4. BATCH N — SZABLON SEKCJI H2
# ══════════════════════════════════════════════════════════════
BATCH_N_PROMPT = """ZADANIE — BATCH {{N}}: {{NAZWA_SEKCJI}}

━━━ KONTEKST CIĄGŁOŚCI ━━━
Poprzednia sekcja zakończyła się zdaniem: "{{OSTATNIE_ZDANIE_POPRZEDNIEGO_BATCHA}}"
Zacznij od naturalnego rozwinięcia tego pomosta. Nie powtarzaj treści poprzedniej sekcji.
Nie zaczynaj od nagłówka H2 jako odpowiedzi na poprzednie zdanie.

━━━ NAGŁÓWEK H2 ━━━
{{NAGLOWEK_H2}}
Nagłówek zawiera przynajmniej jeden z popularnych wzorców H2 konkurencji: {{WZORCE_H2_KONKURENCJI}}

━━━ STRUKTURA WEWNĘTRZNA ━━━
Liczba akapitów: {{LICZBA_AKAPITOW}}
Łączna długość sekcji: {{DLUGOSC_SEKCJI}} słów
Podział: {{OPIS_STRUKTURY_AKAPITOW}}

━━━ ENCJE OBOWIĄZKOWE W TYM BATCHU ━━━
{{ENCJE_BATCH_N}}
Każda encja z tej listy musi pojawić się przynajmniej raz. Odmień przez przypadki — nie używaj wyłącznie mianownika.

━━━ NGRAMY DO WPLECENIA ━━━
Poniżej lista ngrams przypisanych do tego batcha. Liczba po znaku "·" to dopuszczalny zakres użyć W CAŁYM ARTYKULE (nie tylko w tym batchu). Nie przekraczaj górnej granicy.
{{NGRAMY_BATCH_N}}
Ngramy z zakresem "1x" — użyj dokładnie raz, w tym batchu.
Ngramy z zakresem "2x+" — możesz użyć w tym batchu lub rozłożyć na dalsze batche, ale priorytet jest tutaj.

━━━ SEMANTIC TRIPLETS DO WPLECENIA ━━━
{{TRIPLETS_BATCH_N}}
Dla każdego tripletu: wyjaśnij mechanizm (DLACZEGO), nie tylko opisz skutek.
Użyj spójnika kauzalnego.
Jeśli lista tripletów jest pusta — nie wymyślaj własnych łańcuchów przyczynowych.

━━━ HARD FACTS DO UŻYCIA ━━━
{{HARD_FACTS_BATCH_N}}
Te liczby, daty i fakty pochodzą z SERP snippets lub danych wejściowych. Użyj ich dokładnie — nie zaokrąglaj, nie zastępuj własnymi szacunkami.

━━━ PERYFRAZY I WARIANTY ━━━
Wpleć naturalnie co najmniej {{MIN_PERYFRAZ}} z poniższych:
{{PERYFRAZY_BATCH_N}}

━━━ INTENCJA TRANSAKCYJNA ━━━
{{INTENCJA_TRANSAKCYJNA_AKTYWNA}}
Jeśli ten batch jest sekcją zakupową lub porównawczą, wpleć naturalnie:
- marki z Related Searches: {{MARKI_Z_RELATED_SEARCHES}}
- frazy intencji transakcyjnej: {{FRAZY_TRANSAKCYJNE}}
Marki wpleć w naturalnym kontekście porównawczym ("dostępne m.in. w IKEA, Decathlonie i JYSK") — nigdy jako rekomendację ani ocenę.

━━━ ZDANIE POMOSTOWE ━━━
Zakończ sekcję jednym zdaniem prowadzącym do kolejnej sekcji.
Schemat tego zdania musi być różny od pomostów w poprzednich batchach — sprawdź kontekst:
{{POPRZEDNIE_ZDANIA_POMOSTOWE}}"""


# ══════════════════════════════════════════════════════════════
# 5. BATCH FAQ
# ══════════════════════════════════════════════════════════════
BATCH_FAQ_PROMPT = """ZADANIE — BATCH FAQ: Najczęściej zadawane pytania

━━━ KOLEJNOŚĆ PYTAŃ — PRIORYTET ━━━
Pytania odpowiadaj w tej kolejności:

PRIORYTET 1 — PAA bez odpowiedzi w SERP (Featured Snippet):
{{PAA_BEZ_ODPOWIEDZI}}
Te pytania dostają pełną odpowiedź 3–4 zdania. Pierwsze zdanie musi zawierać odpowiedź bezpośrednią (tak/nie + wyjaśnienie), nie wstęp do odpowiedzi.

PRIORYTET 2 — PAA z wysoką wartością long-tail:
{{PAA_STANDARDOWE}}
Odpowiedź 2–3 zdania.

PRIORYTET 3 — Related Searches jako pytania:
{{RELATED_AS_QUESTIONS}}
Odpowiedź 1–2 zdania jeśli nie pokryte wyżej.

━━━ FORMAT ━━━
Pytanie jako <h3> lub pogrubione.
Odpowiedź jako akapit — bez list punktowych wewnątrz odpowiedzi.
Pierwsze zdanie każdej odpowiedzi = bezpośrednia odpowiedź na pytanie, bez wstępów.

ZAKAZANE w FAQ:
"To dobre pytanie."
"Odpowiedź na to pytanie nie jest jednoznaczna."
"Wiele zależy od..."
"Każdy przypadek jest inny."

━━━ NGRAMY W FAQ ━━━
{{NGRAMY_FAQ}}

━━━ HARD FACTS W FAQ ━━━
{{HARD_FACTS_FAQ}}

━━━ DISCLAIMER ━━━
{{DISCLAIMER_SECTION}}"""


# ══════════════════════════════════════════════════════════════
# 6. POST-PROCESSING — WALIDACJA TEKSTU
# ══════════════════════════════════════════════════════════════
POST_PROCESSING_PROMPT = """Przeanalizuj poniższy artykuł pod kątem poniższych kryteriów. Zwróć listę błędów w formacie JSON. Nie przepisuj artykułu.

ARTYKUŁ:
{{PELNY_TEKST_ARTYKULU}}

━━━ KRYTERIA WALIDACJI ━━━
1. AI_PHRASES — wykryj obecność zakazanych fraz:
   ["Warto zaznaczyć", "Warto podkreślić", "Należy zaznaczyć", "Należy podkreślić", "Jest to ważne", "W dzisiejszym artykule", "Kluczowym aspektem", "Podsumowując powyższe", "Jak wspomniano wcześniej", "Co więcej,", "Ponadto,", "Niemniej jednak,", "W związku z powyższym", "Mając na uwadze", "Nie sposób nie wspomnieć", "Wiele osób błędnie"]

2. ENTITY_COVERAGE — sprawdź czy każda encja z listy {{ENCJE_KRYTYCZNE}} pojawia się min. 1x

3. HARD_FACTS — sprawdź czy liczby/ceny z SERP snippets {{HARD_FACTS_ALL}} są użyte dokładnie (nie zaokrąglone)

4. NGRAM_OVERFLOW — sprawdź czy żaden ngram nie przekroczył górnej granicy z listy {{NGRAMY_Z_LIMITAMI}}

5. AKAPIT_UNIFORMITY — jeśli więcej niż 4 kolejne akapity mają identyczną liczbę zdań (np. wszystkie po 4) — oznacz

6. LIST_OVERUSE — jeśli więcej niż 3 listy punktowe w tekście głównym (poza FAQ i instrukcją krok po kroku) — oznacz

7. BOLD_IN_PROSE — jeśli pogrubiony tekst pojawia się w środku akapitu narracyjnego — oznacz

8. PERYFRAZY — sprawdź czy minimum 3 peryfrazy z listy {{PERYFRAZY_ALL}} zostały użyte

9. RELATED_BRANDS — jeśli {{MARKI_Z_RELATED_SEARCHES}} nie są puste i artykuł ma intencję transakcyjną — sprawdź czy przynajmniej jedna marka jest wspomniana

10. PAA_ZERO_ANSWER — sprawdź czy pytania z listy {{PAA_BEZ_ODPOWIEDZI}} mają odpowiedź w FAQ

Zwróć JSON:
{
  "errors": [
    {
      "type": "AI_PHRASES",
      "severity": "HIGH",
      "location": "batch_2, akapit 1",
      "fragment": "Warto podkreślić, że...",
      "fix": "usuń lub przepisz zdanie"
    }
  ],
  "warnings": [],
  "passed": [],
  "score": 0-100
}"""


# ══════════════════════════════════════════════════════════════
# FORBIDDEN PHRASES — used for local validation
# ══════════════════════════════════════════════════════════════
FORBIDDEN_PHRASES = [
    "Warto zaznaczyć",
    "Warto podkreślić",
    "Należy zaznaczyć",
    "Należy podkreślić",
    "Jest to ważne",
    "W dzisiejszym artykule",
    "Kluczowym aspektem",
    "Podsumowując powyższe",
    "Jak wspomniano wcześniej",
    "Co więcej,",
    "Ponadto,",
    "Niemniej jednak,",
    "W związku z powyższym",
    "Mając na uwadze",
    "Nie sposób nie wspomnieć",
    "Wiele osób błędnie",
    "Należy mieć na uwadze",
]


# ══════════════════════════════════════════════════════════════
# DISCLAIMER TEMPLATES
# ══════════════════════════════════════════════════════════════
DISCLAIMERS = {
    "prawo": "Artykuł ma charakter wyłącznie informacyjny i nie stanowi porady prawnej. W konkretnej sprawie skonsultuj się z adwokatem lub radcą prawnym.",
    "zdrowie": "Artykuł ma charakter informacyjny i nie zastępuje konsultacji z lekarzem lub specjalistą.",
    "finanse": "Artykuł ma charakter informacyjny i nie stanowi porady finansowej ani inwestycyjnej.",
    "none": "",
}
