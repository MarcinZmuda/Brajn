"""
BRAJEN SEO — Prompty produkcyjne v1.0
Pipeline zgodny z BRAJEN_PROMPTS_v1.0.

All prompt templates with placeholder variables.
"""

# ══════════════════════════════════════════════════════════════
# 1. SYSTEM PROMPT — wysyłany jako system w każdym wywołaniu API
# v2.0: Persona only — reguły przeniesione do user prompt
# ══════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """Jesteś doświadczonym polskim redaktorem treści SEO. Piszesz fragment artykułu na podstawie danych dostarczonych w instrukcji. Zwracasz wyłącznie tekst w formacie określonym w <output_format>."""

# ══════════════════════════════════════════════════════════════
# 1b. ARTICLE WRITER — pełny prompt v2.0 (XML-structured)
# Może być użyty w trybie full-article lub per-batch
# ══════════════════════════════════════════════════════════════
ARTICLE_WRITER_PROMPT = """<task>
Napisz artykuł SEO na temat: „{{HASLO_GLOWNE}}".
Encja główna: „{{ENCJA_GLOWNA}}" (salience: {{SALIENCE}}).
Użyj WYŁĄCZNIE planu z <plan> i danych z <data>.
Nie dodawaj sekcji spoza planu.
</task>

<style>
1. JĘZYK: naturalny, publicystyczny polski. Mów do czytelnika bezpośrednio: „możesz", „warto", „pamiętaj", „jeśli szukasz".
2. ZDANIA: średnia 11–15 słów. Rytm: krótkie (5–8 słów) przeplataj z dłuższymi (18–22 słów).
3. AKAPITY: minimum 2, maksimum 6 zdań. Żadne dwa akapity w artykule nie mają identycznej liczby zdań. Długość akapitu wynika z funkcji, nie z nawyku.
4. STRONA CZASOWNIKA: aktywna wszędzie, gdzie możliwe.
5. PERYFRAZY: nie powtarzaj tych samych fraz. Rotuj synonimy z <periphrases> i <colloquial_variants>. Używaj ich naturalnie w tekście — nie upychaj na siłę.
6. ZDANIE POMOSTOWE: każda sekcja H2 kończy się zdaniem łączącym z kolejną sekcją. Każde zdanie pomostowe ma inny schemat składniowy.
</style>

<banned_phrases>
Nigdy nie używaj tych fraz (ani ich wariantów):
- Warto zaznaczyć / Warto podkreślić / Należy zaznaczyć / Należy podkreślić
- Jest to ważne / W dzisiejszym artykule / Kluczowym aspektem / Podsumowując powyższe
- Jak wspomniano wcześniej / Co więcej, / Ponadto, / Niemniej jednak,
- W związku z powyższym, / Mając na uwadze / Nie sposób nie wspomnieć / Wiele osób błędnie
</banned_phrases>

<entity_rules>
1. ENCJA GŁÓWNA („{{ENCJA_GLOWNA}}"): musi pojawić się w H1, w pierwszym akapicie intro, i minimum 1x w każdej sekcji H2 (odmieniana przez przypadki).
2. ENCJE KRYTYCZNE (lista w <critical_entities>): każda minimum 1x w całym artykule. Odmieniaj przez przypadki — nie wstawiaj w mianowniku na siłę.
3. Nie klastruj encji — rozłóż je równomiernie po artykule.
</entity_rules>

<ngram_rules>
Każdy n-gram z <ngrams> ma limit [min, max] wystąpień w CAŁYM artykule.
- min = minimalna liczba wystąpień (obowiązkowa).
- max = maksymalna — TWARDA GRANICA. Przekroczenie max = nadoptymalizacja i kara od Google.
- Odmiana fleksyjna liczy się jako wystąpienie (np. „mebli", „meblom", „meble" = to samo).
- Parafrazy i synonimy bliskie też się liczą — „zabezpieczyć meble" ≈ „zabezpieczanie mebli".
- Rozkładaj n-gramy równomiernie — nie koncentruj w jednej sekcji.
- Jeśli n-gram nie pasuje naturalnie do kontekstu zdania — POMIŃ GO. Naturalność > SEO.

ANTY-STUFFING: Pisz dla czytelnika, nie dla robota. Jeśli zdanie brzmi jak lista słów kluczowych
— przepisz je. Czytelnik nie powinien czuć, że tekst jest zoptymalizowany.
</ngram_rules>

<causal_rules>
Przyczyny i skutki z <causal_chains> wyjaśniaj przez schemat DLACZEGO → CO → EFEKT.
Używaj spójników: dlatego / bo / w efekcie / ponieważ / przez co / w rezultacie.
POPRAWNIE: „Przekroczenie 0,5 promila oznacza stan nietrzeźwości, przez co kierowca popełnia przestępstwo, a nie wykroczenie."
BŁĘDNIE: „Jazda po alkoholu jest przestępstwem." (brak przyczyny i mechanizmu)
</causal_rules>

<hard_facts_rules>
Liczby, kwoty, progi i fakty z <hard_facts> mają ABSOLUTNY PRIORYTET nad Twoją wiedzą.
- Nie zaokrąglaj, nie zastępuj własnymi szacunkami.
- Jeśli fakt z <hard_facts> koliduje z Twoją wiedzą — użyj wersji z <hard_facts>.
- Wplataj je naturalnie w tekst, nie wypisuj jako luźne liczby.
</hard_facts_rules>

<formatting_rules>
1. LISTY PUNKTOWE: tylko dla instrukcji krok po kroku, procedur, wymagań formalnych. Nie używaj list do opisywania abstrakcyjnych koncepcji.
2. POGRUBIENIA: zakazane w tekście ciągłym.
3. NAGŁÓWKI: używaj dokładnie nagłówków z <plan>. Nie przeformułowuj, nie dodawaj nowych.
4. FAQ: każde pytanie jako H2, odpowiedź 2–4 zdania. Pierwsze zdanie odpowiada wprost na pytanie (snippet-friendly).
</formatting_rules>

<length_rules>
1. CEL: {{DLUGOSC_CEL}} słów (±10%).
2. INTRO (tekst przed pierwszym H2): {{DLUGOSC_INTRO}} słów (±15%).
3. SEKCJE H2: rozłóż pozostałe słowa równomiernie między {{LICZBA_H2}} sekcji. Żadna sekcja nie może być krótsza niż 50% ani dłuższa niż 150% średniej.
4. FAQ: odpowiedzi 40–80 słów każda.
</length_rules>

<ymyl>
{{YMYL_CONTEXT}}
</ymyl>

<plan>
H1: {{H1}}

Intro: tekst przed pierwszym H2 ({{DLUGOSC_INTRO}} słów).

Sekcje H2 (w tej kolejności, nie zmieniaj):
{{PLAN_ARTYKULU}}

FAQ:
{{PLAN_FAQ}}
</plan>

<data>

<critical_entities>
{{ENCJE_KRYTYCZNE_JSON}}
</critical_entities>

<ngrams>
{{NGRAMY_Z_LIMITAMI_JSON}}
</ngrams>

<causal_chains>
{{LANCUCHY_KAUZALNE_JSON}}
</causal_chains>

<hard_facts>
{{HARD_FACTS_JSON}}
</hard_facts>

<periphrases>
{{PERYFRAZY_JSON}}
</periphrases>

<colloquial_variants>
{{WARIANTY_POTOCZNE_JSON}}
</colloquial_variants>

</data>

<output_format>
Zwróć artykuł jako czysty tekst z nagłówkami w markdown:
- # dla H1 (dokładnie jeden, na początku)
- ## dla każdego H2 (dokładnie w kolejności z <plan>)
- ## dla każdego pytania FAQ
- Bez pogrubień, bez HTML, bez metadanych.
- Na samym końcu artykułu (po FAQ): disclaimer z <ymyl> jeśli niepusty.
</output_format>

<self_check>
Przed zwróceniem artykułu zweryfikuj:
1. Czy encja główna jest w H1, intro i każdej sekcji H2?
2. Czy każda encja z <critical_entities> pojawia się min. 1x?
3. Czy każdy n-gram z <ngrams> mieści się w limicie [min, max]?
4. Czy żadna fraza z <banned_phrases> nie występuje w tekście?
5. Czy artykuł ma {{LICZBA_H2}} sekcji H2 + FAQ?
6. Czy długość intro ≈ {{DLUGOSC_INTRO}} słów, a całość ≈ {{DLUGOSC_CEL}} słów?
7. Czy każda sekcja kończy się zdaniem pomostowym?
8. Czy disclaimer jest na końcu (jeśli <ymyl> niepuste)?
Jeśli cokolwiek nie przechodzi — popraw ZANIM zwrócisz tekst.
</self_check>"""


# ══════════════════════════════════════════════════════════════
# 2. PRE-BATCH PROMPT — mapa rozmieszczeń, nie generuje tekstu
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# 2. H2 PLAN PROMPT — v2.0
# Wykonywany po Search Variants, przed Pre-Batch
# Generuje plan artykułu jako JSON z coverage_check
# System prompt osobno, user prompt z XML tags
# ══════════════════════════════════════════════════════════════

H2_PLAN_SYSTEM = """Planujesz strukturę artykułów SEO. Na podstawie danych wejściowych zwracasz plan artykułu jako JSON zgodny ze schematem podanym w instrukcji. Nie pisz treści artykułu — tylko plan."""

H2_PLAN_PROMPT = """<task>
Zbuduj plan artykułu SEO dla hasła „{{HASLO_GLOWNE}}".
Zwróć WYŁĄCZNIE poprawny JSON zgodny ze schematem w <output_schema>.
Bez markdown, bez komentarzy, bez tekstu przed/po JSON.
</task>

<hard_constraints>
Te reguły MUSZĄ być spełnione. Jeśli którakolwiek jest naruszona, plan jest niepoprawny.

1. LICZBA_H2: Wybierz dokładnie {{LICZBA_H2}} sekcji H2 (nie licząc FAQ).
2. POKRYCIE_ENCJI: Każda encja z <must_cover_entities> musi pojawić się w co najmniej jednym polu "entities" w planie (w H2 lub FAQ).
3. UNIKALNOŚĆ: Żadne dwa H2 nie mogą odpowiadać na tę samą intencję użytkownika. Jeśli dwóch kandydatów pokrywa ten sam temat — wybierz tego z wyższym score lub połącz w jedno lepsze H2.
4. FAQ: Sekcja FAQ zawiera {{LICZBA_FAQ}} pytań. Priorytetowe pytania z <paa_priority> MUSZĄ być uwzględnione. Uzupełnij resztę z <paa_standard> lub wygeneruj pytania pokrywające encje/n-gramy nieobecne w sekcjach H2. FAQ jest buforem na niepokryte frazy — im więcej pytań, tym większe pokrycie.
5. KOLEJNOŚĆ: Pierwsza sekcja H2 powinna odpowiadać na główną intencję hasła. Kolejne sekcje — od ogólnych do szczegółowych, z logicznym flow.
6. H2_KEYWORDS (jeśli podane): Każda fraza z <h2_keywords> musi pojawić się w tekście co najmniej jednego nagłówka H2 (dosłownie lub w odmianie fleksyjnej). Jeśli <h2_keywords> jest puste lub nieobecne — ignoruj tę regułę.
</hard_constraints>

<selection_criteria>
Reguły wyboru i tworzenia H2 z listy kandydatów:

1. SCORE >= 0.30 → kandydat kwalifikuje się automatycznie do rozważenia.
2. SCORE 0.20-0.29 → uwzględnij TYLKO jeśli pokrywa encję z <must_cover_entities> nieobecną w kandydatach >= 0.30.
3. SCORE < 0.20 → odrzuć.
4. Jeśli dwóch kandydatów pokrywa ten sam temat (np. "Co grozi za jazdę..." i "Jaka kara za jazdę...") — wybierz lepszy score LUB przeformułuj w jedno H2 łączące oba.
5. Możesz przeformułować tekst H2 dla lepszego brzmienia, ale zachowaj intencję i główne frazy. Jeśli <h2_keywords> zawiera frazy — wplataj je w tekst H2 przy przeformułowywaniu (nie doklejaj mechanicznie, niech brzmią naturalnie).
6. Jeśli po selekcji masz < {{LICZBA_H2}} sekcji — wygeneruj brakujące na podstawie <must_cover_entities> i <entity_salience>.
7. Jeśli masz > {{LICZBA_H2}} — odrzuć te z najniższym score, chyba że pokrywają unikatową encję.
</selection_criteria>

<data>

<scored_h2>
{{SCORED_H2_JSON}}
</scored_h2>

<must_cover_entities>
{{MUST_COVER_ENTITIES_JSON}}
</must_cover_entities>

<entity_salience>
{{ENTITY_SALIENCE_JSON}}
</entity_salience>

<hard_facts>
{{HARD_FACTS_JSON}}
</hard_facts>

<paa_priority>
{{PAA_PRIORITY_JSON}}
</paa_priority>

<paa_standard>
{{PAA_STANDARD_JSON}}
</paa_standard>

<h2_keywords>
{{H2_KEYWORDS_JSON}}
</h2_keywords>

</data>

<output_schema>
{
  "keyword": "string — hasło główne",
  "h2_count": "integer — liczba sekcji H2 (bez FAQ)",
  "sections": [
    {
      "order": "integer — kolejność sekcji (1-based)",
      "h2": "string — tekst nagłówka H2",
      "intent": "string — jedno zdanie: na jaką intencję użytkownika odpowiada ta sekcja",
      "entities": ["string — encje z must_cover pokryte w tej sekcji"],
      "hard_facts": ["string — hard facts pasujące do tej sekcji (opcjonalne, puste [] jeśli brak)"],
      "source_score": "number|null — score kandydata źródłowego, null jeśli H2 wygenerowane",
      "h2_keywords_used": ["string — frazy z h2_keywords użyte w tym H2 (puste [] jeśli brak)"]
    }
  ],
  "faq": [
    {
      "question": "string — pytanie FAQ",
      "entities": ["string — encje pokryte w odpowiedzi"],
      "hard_facts": ["string — hard facts pasujące do odpowiedzi (opcjonalne)"],
      "source": "paa_priority | paa_standard | generated"
    }
  ],
  "coverage_check": {
    "all_entities_covered": "boolean — true jeśli każda encja z must_cover jest w co najmniej jednym section/faq",
    "uncovered_entities": ["string — lista encji NIEpokrytych (powinna być pusta)"],
    "all_h2_keywords_used": "boolean|null — true jeśli każda fraza z h2_keywords jest w co najmniej jednym H2, null jeśli h2_keywords puste",
    "unused_h2_keywords": ["string — frazy z h2_keywords nieużyte w żadnym H2 (powinna być pusta)"]
  }
}
</output_schema>

<self_check>
Przed zwróceniem JSON zweryfikuj:
1. Czy all_entities_covered === true? Jeśli nie — przypisz brakujące encje do istniejących sekcji lub dodaj sekcję.
2. Czy h2_count === {{LICZBA_H2}}?
3. Czy żadne dwa H2 nie odpowiadają na identyczną intencję?
4. Czy pytania z paa_priority są w FAQ?
5. Jeśli <h2_keywords> niepuste — czy all_h2_keywords_used === true? Jeśli nie — przeformułuj istniejące H2, żeby wpleść brakujące frazy.
Jeśli cokolwiek nie przechodzi — popraw plan ZANIM zwrócisz JSON.
</self_check>"""

PRE_BATCH_PROMPT = """Na podstawie poniższych danych wejściowych zbuduj mapę rozmieszczeń encji i fraz dla artykułu "{{HASLO_GLOWNE}}".
NIE generuj tekstu artykułu. Zwróć wyłącznie JSON.

DANE WEJŚCIOWE:
Encje krytyczne: {{ENCJE_KRYTYCZNE}}
N-gramy z częstotliwościami: {{NGRAMY_Z_CZESTOTLIWOSCIA}}
Łańcuchy kauzalne: {{LANCUCHY_KAUZALNE}}
Relacje kauzalne: {{RELACJE_KAUZALNE}}

{{YMYL_CONTEXT}}
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
BATCH_0_PROMPT = """<task>
Napisz nagłówek H1 i wstępny akapit artykułu na temat: „{{HASLO_GLOWNE}}".
To jest BATCH 0 — pisz WYŁĄCZNIE H1 i intro. Nie pisz sekcji H2 ani dalszej treści.
</task>

<lead_strategy>
Cel intro: zająć pozycję AI Overview w Google dla hasła „{{HASLO_GLOWNE}}".

Google generuje AI Overview na podstawie treści, które:
- bezpośrednio i zwięźle odpowiadają na intencję wyszukiwania
- podają konkretne fakty, liczby, progi (nie ogólniki)
- są spójne z tym, co Google już wyświetla jako AI Overview lub Featured Snippet

Dlatego intro musi pokrywać TE SAME informacje co źródło referencyjne — ale własnymi słowami, w lepszej strukturze, z wyższą gęstością informacji.

ZASADA FALLBACK — użyj PIERWSZEGO dostępnego źródła:

1. Jeśli <ai_overview> jest NIEPUSTE → to jest Twoje źródło referencyjne.
   Intro musi pokryć te same kluczowe informacje (fakty, liczby, progi, konsekwencje), ale:
   - przeformułowane własnymi słowami
   - wzbogacone o hard facts z <hard_facts> których brakuje w AI Overview
   - w naturalnym, publicystycznym stylu (nie kopiuj struktury zdań)

2. Jeśli <ai_overview> jest PUSTE, ale <featured_snippet> jest NIEPUSTE → to jest Twoje źródło.
   Intro musi odpowiadać na tę samą intencję co snippet, pokrywając te same informacje + hard facts.

3. Jeśli OBA są PUSTE → napisz intro na podstawie <hard_facts>, <batch_entities> i encji głównej.
   Struktura: kontekst problemu → główna konsekwencja/mechanizm → zapowiedź artykułu.
</lead_strategy>

<h1_rules>
1. Zawiera frazę „{{ENCJA_GLOWNA}}" (odmienioną naturalnie, nie w mianowniku na siłę).
2. Zapowiada główną wartość artykułu (kary / konsekwencje / przepisy / poradnik / itp.).
3. Maksymalnie 70 znaków ze spacjami.
4. NIE zaczynaj H1 od encji głównej w mianowniku jako podmiot.
</h1_rules>

<intro_rules>
1. DŁUGOŚĆ: {{DLUGOSC_INTRO}} słów (±15%).

2. PIERWSZE ZDANIE:
   - Zawiera encję główną, ale NIE jako podmiot w mianowniku.
   - Zacznij od kontekstu, liczby, napięcia lub sytuacji.
   POPRAWNIE: „Co roku tysiące kierowców traci prawo jazdy za jazdę pod wpływem alkoholu."
   BŁĘDNIE: „Jazda pod wpływem alkoholu jest przestępstwem."

3. GĘSTOŚĆ INFORMACJI:
   - Pierwsze 100 słów = zwięzła odpowiedź na intencję hasła (to Google wyciąga do AI Overview).
   - Nie marnuj słów na ogólniki typu „temat jest ważny" / „wiele osób się zastanawia".
   - Każde zdanie musi wnosić konkretną informację: fakt, próg, konsekwencję lub mechanizm.

4. ENCJE I FRAZY W INTRO:
   - Encja główna („{{ENCJA_GLOWNA}}") — OBOWIĄZKOWA, minimum 1x (pierwsze zdanie ją zawiera — zaliczone).
   - Jeśli <key_ngram> jest NIEPUSTE — wpleć tę frazę naturalnie (1x wystarczy). To najważniejszy n-gram zawierający encję główną.
   - Jeśli <key_triplet> jest NIEPUSTE — użyj tego tripletu przyczyna→skutek jako oś jednego ze zdań w intro.
   - To WSZYSTKO. Nie ładuj intro dodatkowymi encjami — {{DLUGOSC_INTRO}} słów to za mało. Reszta encji i n-gramów trafi do sekcji H2.

6. ZAPOWIEDŹ ARTYKUŁU:
   Ostatnie 1–2 zdania intro zapowiadają, co czytelnik znajdzie dalej.
   Nawiąż do tematu pierwszej sekcji H2: „{{PIERWSZY_H2}}".
   Nie powtarzaj tytułu H2 dosłownie.

7. HARD FACTS: wpleć co najmniej 2 fakty z <hard_facts>. Reszta trafi do sekcji H2.
</intro_rules>

<style>
1. Naturalny, publicystyczny polski. Mów do czytelnika: „możesz", „pamiętaj", „jeśli".
2. Średnia długość zdania: 11–15 słów. Rytm: krótkie (5–8) przeplataj z dłuższymi (18–22).
3. Akapity: 2–6 zdań. Żadne dwa akapity nie mają identycznej liczby zdań.
4. Aktywna strona czasownika.
</style>

<banned_phrases>
Nigdy nie używaj (ani wariantów):
- Warto zaznaczyć / Warto podkreślić / Należy zaznaczyć / Należy podkreślić
- Jest to ważne / W dzisiejszym artykule / Kluczowym aspektem / Podsumowując powyższe
- Jak wspomniano wcześniej / Co więcej, / Ponadto, / Niemniej jednak,
- W związku z powyższym, / Mając na uwadze / Nie sposób nie wspomnieć / Wiele osób błędnie
</banned_phrases>

<data>

<ai_overview>
{{AI_OVERVIEW_TEXT}}
</ai_overview>

<featured_snippet>
{{FEATURED_SNIPPET_TEXT}}
</featured_snippet>

<key_ngram>
{{KEY_NGRAM}}
</key_ngram>

<key_triplet>
{{KEY_TRIPLET}}
</key_triplet>

<hard_facts>
{{HARD_FACTS_BATCH_0_JSON}}
</hard_facts>

</data>

<output_format>
Zwróć WYŁĄCZNIE:

# [tekst H1]

[akapit(y) wstępne — pełny tekst intro]

Bez komentarzy, metadanych, ani tekstu przed/po. Markdown: # dla H1, potem akapit(y) jako czysty tekst.
</output_format>

<self_check>
Przed zwróceniem zweryfikuj:
1. H1 ≤ 70 znaków ze spacjami?
2. H1 zawiera encję główną i NIE zaczyna się od niej w mianowniku?
3. Intro ma ≈ {{DLUGOSC_INTRO}} słów (±15%)?
4. Pierwsze zdanie zawiera encję główną, ale nie jako podmiot w mianowniku?
5. Pierwsze 100 słów pokrywa kluczowe informacje ze źródła referencyjnego (AI Overview / Featured Snippet)?
6. Minimum 2 hard facts z <hard_facts> są wplecione?
7. Jeśli <key_ngram> niepuste — czy fraza pojawia się w intro?
8. Jeśli <key_triplet> niepuste — czy triplet przyczyna→skutek jest użyty?
9. Ostatnie zdanie nawiązuje do tematu „{{PIERWSZY_H2}}"?
10. Żadna fraza z <banned_phrases> nie występuje?
11. Żadne zdanie nie jest ogólnikiem bez konkretnej informacji?
Jeśli nie przechodzi — popraw ZANIM zwrócisz tekst.
</self_check>"""


# ══════════════════════════════════════════════════════════════
# 4. BATCH N — SZABLON SEKCJI H2 (v2.0 XML)
# ══════════════════════════════════════════════════════════════
BATCH_N_PROMPT = """<task>
Napisz WYŁĄCZNIE sekcję H2 nr {{N}} artykułu „{{HASLO_GLOWNE}}".
Nie pisz intro, nie pisz FAQ, nie pisz innych sekcji.
</task>

<continuity>
Poprzednia sekcja zakończyła się zdaniem: „{{OSTATNIE_ZDANIE_POPRZEDNIEGO_BATCHA}}"
Zacznij od naturalnego rozwinięcia tego pomosta. Nie powtarzaj treści poprzedniej sekcji.
Poprzednie zdania pomostowe (nie powtarzaj ich schematu): {{POPRZEDNIE_ZDANIA_POMOSTOWE}}
</continuity>

<section_spec>
Nagłówek H2: {{NAGLOWEK_H2}}
Długość sekcji: {{DLUGOSC_SEKCJI}} słów (±15%)
Akapity: 3–5 akapitów narracyjnych z naturalnym przepływem
</section_spec>

<section_data>

<main_keyword_budget>
{{MAIN_KW_INSTRUCTION}}
</main_keyword_budget>

<entities>
{{ENCJE_BATCH_N}}
Każda encja musi pojawić się min. 1x. Odmieniaj przez przypadki.
Encja główna „{{ENCJA_GLOWNA}}" — obowiązkowa w każdej sekcji.
</entities>

<ngrams>
{{NGRAMY_BATCH_N}}

ZASADY:
- MUST = frazy obowiązkowe. Użyj w dokładnej formie podanej powyżej.
- NICE-TO-HAVE = frazy opcjonalne. Użyj tylko jeśli naturalnie pasują do sekcji.
- Liczba po „·" = ile razy MOŻESZ użyć frazy w tej sekcji. Nie przekraczaj.
- 🛑 STOP = budżet wyczerpany. NIE UŻYWAJ tej frazy w żadnej formie.
- Jeśli fraza nie pasuje do kontekstu — POMIŃ. Lepiej 0 niż wciśnięta na siłę.
- Liczy się tylko DOKŁADNA forma. Odmienione formy (np. „szamponem" ≠ „szampon") NIE zużywają budżetu, więc możesz odmieniać swobodnie.
</ngrams>

<causal_triplets>
{{TRIPLETS_BATCH_N}}
Dla każdego: wyjaśnij DLACZEGO (spójnik kauzalny). Jeśli lista pusta — nie wymyślaj.
</causal_triplets>

<hard_facts>
{{HARD_FACTS_BATCH_N}}
Użyj dokładnie — nie zaokrąglaj, nie zastępuj własnymi szacunkami.
</hard_facts>

<periphrases>
Wpleć naturalnie min. {{MIN_PERYFRAZ}} z: {{PERYFRAZY_BATCH_N}}
</periphrases>

</section_data>

{{NW_LUKI}}

{{YMYL_CONTEXT}}

<transactional>
{{INTENCJA_TRANSAKCYJNA_AKTYWNA}}
Marki z Related Searches: {{MARKI_Z_RELATED_SEARCHES}}
Frazy transakcyjne: {{FRAZY_TRANSAKCYJNE}}
Marki wpleć w naturalnym kontekście porównawczym — nigdy jako rekomendację.
</transactional>

<anti_stuffing>
PRIORYTET: naturalność tekstu > nasycenie frazami SEO.
- Nie powtarzaj tego samego n-gramu w sąsiednich zdaniach.
- Nie zaczynaj dwóch akapitów od tej samej frazy kluczowej.
- Jeśli zdanie brzmi sztucznie z powodu wciśniętego n-gramu — usuń go.
- Lepiej mieć 0 użyć frazy niż 1 użycie, które psuje tekst.
</anti_stuffing>

<bridge>
Zakończ sekcję zdaniem pomostowym prowadzącym do kolejnej sekcji.
Schemat składniowy musi być inny niż poprzednie pomosty.
</bridge>

<output_format>
Zwróć:
## {{NAGLOWEK_H2}}

[Tekst sekcji — {{DLUGOSC_SEKCJI}} słów]
</output_format>"""


# ══════════════════════════════════════════════════════════════
# 5. BATCH FAQ (v2.0 XML)
# ══════════════════════════════════════════════════════════════
BATCH_FAQ_PROMPT = """<task>
Napisz WYŁĄCZNIE sekcję FAQ artykułu „{{HASLO_GLOWNE}}".
Nie pisz intro, nie pisz sekcji H2.
</task>

<faq_questions>
PRIORYTET 1 — PAA bez odpowiedzi w SERP (Featured Snippet):
{{PAA_BEZ_ODPOWIEDZI}}
Odpowiedź 3–4 zdania. Pierwsze zdanie = bezpośrednia odpowiedź (tak/nie + wyjaśnienie).

PRIORYTET 2 — PAA standardowe:
{{PAA_STANDARDOWE}}
Odpowiedź 2–3 zdania.

PRIORYTET 3 — Related Searches jako pytania:
{{RELATED_AS_QUESTIONS}}
Odpowiedź 1–2 zdania jeśli nie pokryte wyżej.
</faq_questions>

<faq_format>
- Każde pytanie jako ## (nagłówek H2)
- Odpowiedź jako akapit — bez list punktowych
- Pierwsze zdanie = bezpośrednia odpowiedź na pytanie, bez wstępów
- Odpowiedzi 40–80 słów każda
</faq_format>

<faq_banned>
ZAKAZANE w FAQ:
- „To dobre pytanie."
- „Odpowiedź na to pytanie nie jest jednoznaczna."
- „Wiele zależy od..."
- „Każdy przypadek jest inny."
</faq_banned>

<faq_data>
N-gramy do wplecenia: {{NGRAMY_FAQ}}
Hard facts: {{HARD_FACTS_FAQ}}
</faq_data>

<disclaimer>
{{DISCLAIMER_SECTION}}
Na samym końcu (po ostatnim FAQ) dodaj disclaimer jeśli niepusty.
</disclaimer>

<output_format>
Zwróć:
## [Pytanie FAQ 1]
[Odpowiedź 40–80 słów]

## [Pytanie FAQ 2]
[Odpowiedź 40–80 słów]

...

[Disclaimer jeśli wymagany]
</output_format>"""


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
# FORBIDDEN PHRASES — used for local validation (core list)
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
# BANNED OPENERS v2.0 — frazy zakazane na początku zdań/akapitów
# ══════════════════════════════════════════════════════════════
BANNED_OPENERS = [
    # Czasowe
    "w dzisiejszych czasach",
    "w obecnych czasach",
    "współcześnie",
    "w dzisiejszym świecie",
    "w dynamicznie zmieniającym się świecie",
    # Hedge
    "nie ulega wątpliwości",
    "nie da się ukryć",
    "jak wiadomo",
    "każdy z nas",
    "coraz więcej osób",
    # Warto-frazy
    "warto wiedzieć",
    "warto zauważyć",
    "warto podkreślić",
    "warto pamiętać",
    "warto dodać",
    "warto wspomnieć",
    # Należy-frazy
    "należy podkreślić",
    "należy zauważyć",
    "należy zaznaczyć",
    "należy pamiętać",
    "należy mieć na uwadze",
    # Ważność
    "istotne jest",
    "kluczowe jest",
    "ważne jest, aby",
]

# ══════════════════════════════════════════════════════════════
# BANNED ANYWHERE v2.0 — frazy zakazane w dowolnym miejscu tekstu
# ══════════════════════════════════════════════════════════════
BANNED_ANYWHERE = [
    # Connectory / podsumowania
    "co więcej",
    "podsumowując",
    "reasumując",
    "w podsumowaniu",
    "to prowadzi nas do wniosku",
    "w skrócie",
    "ogólnie rzecz biorąc",
    "mam nadzieję, że",
    "oczywiście",
    "to jeszcze",
    "to już",
    # Kalki / anglicyzmy do zastąpienia
    "posiadać",       # poza kontekstem własności prawnej/majątkowej
    "zaadresować",    # zamiast: rozwiązać/zająć się
    "zaimplementować",  # zamiast: wdrożyć
    "targetować",     # zamiast: kierować do
    # Hiperbole AI
    "niesamowity",
    "niezwykły",
    "wyjątkowy",
    "rewolucyjny",
    "przełomowy",
    "game changer",
    "holistyczny",
    "kompleksowy",
    # Pseudo-prawnicze
    "na podstawie dostępnych danych",
    "w świetle obowiązujących przepisów",
    "zgodnie z literą prawa",
    "ustawodawca przewidział",
]

# Znak typograficzny zakazany w tekście
BANNED_CHARS = [
    "\u2014",  # em dash (—) — zakazany, używaj krótkiego myślnika lub przecinka
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
