"""
⚖️ Legal Enricher — Brajn SEO Engine
=====================================
Pobiera orzeczenia sądowe i przepisy prawne dla artykułów prawnych (YMYL=prawo).

Źródła (cascade):
  1. ISAP / Sejm ELI API — przepisy prawne (kodeksy, ustawy, artykuły)
  2. SAOS API — System Analizy Orzeczeń Sądowych (REST, bezpłatny)
  3. Lokalne portale sądowe — Scrapling (fallback gdy SAOS < 2 wyniki)

Wynik: blok {{YMYL_CONTEXT}} wstrzykiwany do PRE_BATCH i BATCH_N.
"""

import re
import time
import json
import os
from typing import List, Dict, Any, Optional

# ── Scrapling ────────────────────────────────────────────────────────────────
SCRAPLING_AVAILABLE = False
try:
    from scrapling.fetchers import Fetcher as ScraplingFetcher
    SCRAPLING_AVAILABLE = True
    print("[LEGAL] ✅ Scrapling available")
except ImportError:
    print("[LEGAL] ⚠️ Scrapling not installed — pip install scrapling")

# ── requests fallback ────────────────────────────────────────────────────────
import requests


# ─────────────────────────────────────────────────────────────────────────────
# ISAP / Sejm ELI API — Polish statutory law
# ─────────────────────────────────────────────────────────────────────────────

ISAP_ELI_BASE = "https://api.sejm.gov.pl/eli"
ISAP_TIMEOUT = 12

# Mapping of common legal topics to relevant legal codes and articles.
# This allows us to always provide relevant legal references even when
# the ISAP search returns nothing for a broad keyword.
LEGAL_TOPIC_MAP = {
    # ── Prawo karne ──────────────────────────────────────────
    "jazda po alkoholu": [
        {"act": "Kodeks Karny", "articles": ["art. 178a"], "eli": "DU/1997/553",
         "desc": "Prowadzenie pojazdu w stanie nietrzeźwości lub pod wpływem środka odurzającego"},
        {"act": "Kodeks Wykroczeń", "articles": ["art. 87"], "eli": "DU/1971/114",
         "desc": "Prowadzenie pojazdu w stanie po użyciu alkoholu (wykroczenie)"},
        {"act": "Kodeks Karny", "articles": ["art. 178b"], "eli": "DU/1997/553",
         "desc": "Niezatrzymanie pojazdu i ucieczka przed kontrolą"},
    ],
    "prowadzenie pod wpływem": [
        {"act": "Kodeks Karny", "articles": ["art. 178a"], "eli": "DU/1997/553",
         "desc": "Prowadzenie pojazdu w stanie nietrzeźwości"},
        {"act": "Prawo o ruchu drogowym", "articles": ["art. 135"], "eli": "DU/1997/602",
         "desc": "Zatrzymanie prawa jazdy"},
    ],
    "kradzież": [
        {"act": "Kodeks Karny", "articles": ["art. 278", "art. 279"], "eli": "DU/1997/553",
         "desc": "Kradzież i kradzież z włamaniem"},
        {"act": "Kodeks Wykroczeń", "articles": ["art. 119"], "eli": "DU/1971/114",
         "desc": "Kradzież mienia o wartości do 800 zł (wykroczenie)"},
    ],
    "oszustwo": [
        {"act": "Kodeks Karny", "articles": ["art. 286"], "eli": "DU/1997/553",
         "desc": "Oszustwo — doprowadzenie do niekorzystnego rozporządzenia mieniem"},
    ],
    "groźby karalne": [
        {"act": "Kodeks Karny", "articles": ["art. 190", "art. 190a"], "eli": "DU/1997/553",
         "desc": "Groźba karalna i stalking (uporczywe nękanie)"},
    ],
    "stalking": [
        {"act": "Kodeks Karny", "articles": ["art. 190a"], "eli": "DU/1997/553",
         "desc": "Uporczywe nękanie (stalking)"},
    ],
    "znęcanie": [
        {"act": "Kodeks Karny", "articles": ["art. 207"], "eli": "DU/1997/553",
         "desc": "Znęcanie się nad osobą najbliższą lub zależną"},
    ],
    "przemoc domowa": [
        {"act": "Kodeks Karny", "articles": ["art. 207"], "eli": "DU/1997/553",
         "desc": "Znęcanie się fizyczne i psychiczne"},
        {"act": "Ustawa o przeciwdziałaniu przemocy domowej", "articles": [], "eli": "DU/2005/1390",
         "desc": "Procedura Niebieskiej Karty, nakaz opuszczenia lokalu"},
    ],
    "narkotyki": [
        {"act": "Ustawa o przeciwdziałaniu narkomanii", "articles": ["art. 62", "art. 59"], "eli": "DU/2005/1485",
         "desc": "Posiadanie i handel środkami odurzającymi"},
    ],

    # ── Prawo cywilne ────────────────────────────────────────
    "rozwód": [
        {"act": "Kodeks Rodzinny i Opiekuńczy", "articles": ["art. 56", "art. 57", "art. 58"], "eli": "DU/1964/59",
         "desc": "Przesłanki rozwodu, wina, orzeczenie o alimentach i władzy rodzicielskiej"},
    ],
    "alimenty": [
        {"act": "Kodeks Rodzinny i Opiekuńczy", "articles": ["art. 128", "art. 133", "art. 135"], "eli": "DU/1964/59",
         "desc": "Obowiązek alimentacyjny, zakres świadczeń"},
    ],
    "spadek": [
        {"act": "Kodeks Cywilny", "articles": ["art. 922", "art. 931", "art. 991"], "eli": "DU/1964/93",
         "desc": "Spadkobranie, dziedziczenie ustawowe i testamentowe, zachowek"},
    ],
    "zachowek": [
        {"act": "Kodeks Cywilny", "articles": ["art. 991", "art. 992", "art. 1007"], "eli": "DU/1964/93",
         "desc": "Prawo do zachowku — uprawnieni, wysokość, przedawnienie"},
    ],
    "umowa najmu": [
        {"act": "Kodeks Cywilny", "articles": ["art. 659", "art. 673"], "eli": "DU/1964/93",
         "desc": "Umowa najmu — prawa i obowiązki stron, wypowiedzenie"},
        {"act": "Ustawa o ochronie praw lokatorów", "articles": ["art. 11"], "eli": "DU/2001/733",
         "desc": "Ochrona lokatorów, eksmisja"},
    ],
    "eksmisja": [
        {"act": "Ustawa o ochronie praw lokatorów", "articles": ["art. 11", "art. 14"], "eli": "DU/2001/733",
         "desc": "Warunki eksmisji, lokal zastępczy"},
    ],
    "reklamacja": [
        {"act": "Ustawa o prawach konsumenta", "articles": ["art. 43a", "art. 43d"], "eli": "DU/2014/827",
         "desc": "Rękojmia konsumencka, naprawa/wymiana/zwrot"},
        {"act": "Kodeks Cywilny", "articles": ["art. 556", "art. 560"], "eli": "DU/1964/93",
         "desc": "Rękojmia za wady — obniżenie ceny, odstąpienie od umowy"},
    ],
    "zwrot towaru": [
        {"act": "Ustawa o prawach konsumenta", "articles": ["art. 27", "art. 30", "art. 34"], "eli": "DU/2014/827",
         "desc": "Prawo odstąpienia od umowy zawartej na odległość (14 dni)"},
    ],
    "rękojmia": [
        {"act": "Kodeks Cywilny", "articles": ["art. 556", "art. 560", "art. 568"], "eli": "DU/1964/93",
         "desc": "Rękojmia za wady fizyczne i prawne"},
    ],

    # ── Prawo pracy ──────────────────────────────────────────
    "wypowiedzenie umowy o pracę": [
        {"act": "Kodeks Pracy", "articles": ["art. 30", "art. 36", "art. 52"], "eli": "DU/1974/141",
         "desc": "Rozwiązanie umowy — okresy wypowiedzenia, dyscyplinarka"},
    ],
    "zwolnienie dyscyplinarne": [
        {"act": "Kodeks Pracy", "articles": ["art. 52", "art. 53"], "eli": "DU/1974/141",
         "desc": "Rozwiązanie umowy bez wypowiedzenia z winy pracownika"},
    ],
    "mobbing": [
        {"act": "Kodeks Pracy", "articles": ["art. 94³"], "eli": "DU/1974/141",
         "desc": "Mobbing — definicja, odpowiedzialność pracodawcy, odszkodowanie"},
    ],
    "dyskryminacja w pracy": [
        {"act": "Kodeks Pracy", "articles": ["art. 11³", "art. 18³a"], "eli": "DU/1974/141",
         "desc": "Zakaz dyskryminacji, równe traktowanie w zatrudnieniu"},
    ],
    "urlop": [
        {"act": "Kodeks Pracy", "articles": ["art. 152", "art. 154", "art. 171"], "eli": "DU/1974/141",
         "desc": "Prawo do urlopu, wymiar, ekwiwalent za niewykorzystany urlop"},
    ],

    # ── Prawo administracyjne / drogowe ──────────────────────
    "mandat": [
        {"act": "Kodeks Postępowania w Sprawach o Wykroczenia", "articles": ["art. 97", "art. 99"], "eli": "DU/2001/1148",
         "desc": "Tryb mandatowy, odmowa przyjęcia mandatu"},
        {"act": "Prawo o ruchu drogowym", "articles": ["art. 92a", "art. 97"], "eli": "DU/1997/602",
         "desc": "Wykroczenia drogowe, taryfikator mandatów"},
    ],
    "punkty karne": [
        {"act": "Prawo o ruchu drogowym", "articles": ["art. 98"], "eli": "DU/1997/602",
         "desc": "Punkty karne za naruszenie przepisów ruchu drogowego"},
    ],
    "utrata prawa jazdy": [
        {"act": "Prawo o ruchu drogowym", "articles": ["art. 135", "art. 102"], "eli": "DU/1997/602",
         "desc": "Zatrzymanie i cofnięcie prawa jazdy"},
    ],
}


def _match_topic_keywords(keyword: str) -> List[Dict]:
    """Match keyword against LEGAL_TOPIC_MAP using fuzzy substring matching."""
    keyword_lower = keyword.lower().strip()
    results = []
    seen_keys = set()

    # 1. Direct key match
    for topic_key, refs in LEGAL_TOPIC_MAP.items():
        if topic_key in keyword_lower or keyword_lower in topic_key:
            for ref in refs:
                ref_key = f"{ref['act']}|{'|'.join(ref['articles'])}"
                if ref_key not in seen_keys:
                    seen_keys.add(ref_key)
                    results.append(ref)

    # 2. Word overlap — match if 2+ meaningful words overlap
    kw_words = set(re.findall(r"\w{3,}", keyword_lower))
    if not results and len(kw_words) >= 1:
        for topic_key, refs in LEGAL_TOPIC_MAP.items():
            topic_words = set(re.findall(r"\w{3,}", topic_key.lower()))
            overlap = kw_words & topic_words
            if len(overlap) >= 1:
                for ref in refs:
                    ref_key = f"{ref['act']}|{'|'.join(ref['articles'])}"
                    if ref_key not in seen_keys:
                        seen_keys.add(ref_key)
                        results.append(ref)

    return results[:6]


def _isap_search_acts(keyword: str, max_results: int = 4) -> List[Dict]:
    """
    Search ISAP ELI API for legal acts matching keyword.
    Falls back to topic map if API unavailable.
    """
    results = []

    # Try ELI API search
    try:
        # The Sejm ELI API allows searching acts
        params = {"title": keyword, "limit": max_results}
        r = requests.get(
            f"{ISAP_ELI_BASE}/acts/DU/search",
            params=params,
            timeout=ISAP_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("items", [])
            for item in items[:max_results]:
                title = item.get("title", "") or item.get("titleFinal", "")
                eli = item.get("ELI", "") or item.get("eli", "")
                pub_date = item.get("promulgation", "") or item.get("announcementDate", "")
                results.append({
                    "act": title[:120],
                    "articles": [],
                    "eli": eli,
                    "desc": title[:200],
                    "pub_date": pub_date,
                    "source": "isap_api",
                })
            if results:
                print(f"[LEGAL] ISAP API → {len(results)} aktów dla '{keyword}'")
    except Exception as e:
        print(f"[LEGAL] ISAP API error: {e}")

    # Try alternative ISAP endpoint
    if not results:
        try:
            r = requests.get(
                f"{ISAP_ELI_BASE}/acts/DU",
                params={"title": keyword, "limit": max_results},
                timeout=ISAP_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            if r.status_code == 200:
                data = r.json()
                items = data if isinstance(data, list) else data.get("items", [])
                for item in items[:max_results]:
                    title = item.get("title", "") or ""
                    eli = item.get("ELI", "") or ""
                    results.append({
                        "act": title[:120],
                        "articles": [],
                        "eli": eli,
                        "desc": title[:200],
                        "source": "isap_api",
                    })
                if results:
                    print(f"[LEGAL] ISAP API (alt) → {len(results)} aktów")
        except Exception as e:
            print(f"[LEGAL] ISAP API (alt) error: {e}")

    return results


def _get_legal_references(keyword: str) -> List[Dict]:
    """
    Get legal references: topic map + ISAP API.
    Returns list of legal act references with articles.
    """
    # 1. Topic map — always reliable
    topic_refs = _match_topic_keywords(keyword)

    # 2. ISAP API — for broader coverage
    isap_refs = _isap_search_acts(keyword, max_results=3)

    # Merge, dedup by act name
    all_refs = list(topic_refs)
    seen_acts = {r["act"].lower() for r in all_refs}
    for ref in isap_refs:
        if ref["act"].lower() not in seen_acts:
            seen_acts.add(ref["act"].lower())
            all_refs.append(ref)

    print(f"[LEGAL] References: {len(topic_refs)} from topic map, {len(isap_refs)} from ISAP")
    return all_refs[:8]


# ─────────────────────────────────────────────────────────────────────────────
# SAOS API
# ─────────────────────────────────────────────────────────────────────────────

SAOS_BASE = "https://www.saos.org.pl/api"
SAOS_TIMEOUT = 15


def _saos_search(keyword: str, max_results: int = 6) -> List[Dict]:
    """Szuka orzeczeń w SAOS API."""
    try:
        params = {
            "all": keyword,
            "pageSize": max_results,
            "sort": "SCORE",
        }
        r = requests.get(
            f"{SAOS_BASE}/search/judgments",
            params=params,
            timeout=SAOS_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()

        items = data.get("items", [])
        results = []
        for item in items:
            j = item.get("judgment") or item
            sig = j.get("caseNumbers", [None])[0] or ""
            court_name = (
                (j.get("courtType") or "")
                + " "
                + ((j.get("court") or {}).get("name") or "")
            ).strip()
            date = j.get("judgmentDate", "")
            summary = j.get("summary", "") or ""
            if not summary:
                # Try textContent snippet
                tc = j.get("textContent", "")
                summary = tc[:300].replace("\n", " ") if tc else ""

            results.append({
                "signature": sig,
                "court": court_name or "Sąd",
                "date": date,
                "excerpt": summary[:250],
                "portal": "www.saos.org.pl",
                "source": "saos",
            })
        print(f"[LEGAL] SAOS → {len(results)} orzeczeń dla '{keyword}'")
        return results
    except Exception as e:
        print(f"[LEGAL] SAOS error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Local court portals via Scrapling
# ─────────────────────────────────────────────────────────────────────────────

LOCAL_PORTALS = [
    "https://orzeczenia.warszawa.so.gov.pl",
    "https://orzeczenia.krakow.so.gov.pl",
    "https://orzeczenia.gdansk.sa.gov.pl",
    "https://orzeczenia.lodz.so.gov.pl",
    "https://orzeczenia.poznan.so.gov.pl",
]


def _scrapling_search_portal(portal_url: str, keyword: str) -> List[Dict]:
    """Scrapes a single court portal for the keyword using Scrapling."""
    if not SCRAPLING_AVAILABLE:
        return []
    try:
        fetcher = ScraplingFetcher(auto_match=False)
        search_url = f"{portal_url}/search?q={requests.utils.quote(keyword)}"
        page = fetcher.get(search_url, timeout=10, stealthy_headers=True)
        if not page:
            return []

        results = []
        # Most portals use <a class="judgment-link"> or <tr> rows
        for link in page.css("a[href*='/details/']")[:4]:
            text = link.text.strip()
            href = link.attrib.get("href", "")
            # Try to extract signature from text (e.g. "I C 123/22")
            sig_match = re.search(r"[IVX]+\s+[A-Za-z]{1,4}\s+\d+/\d{2,4}", text)
            sig = sig_match.group() if sig_match else text[:40]
            full_url = href if href.startswith("http") else portal_url + href
            domain = portal_url.replace("https://", "").replace("http://", "")
            results.append({
                "signature": sig,
                "court": domain,
                "date": "",
                "excerpt": text[:200],
                "portal": domain,
                "source": "local",
            })
        return results
    except Exception as e:
        print(f"[LEGAL] Local portal {portal_url} error: {e}")
        return []


def _local_courts_search(keyword: str, max_results: int = 3) -> List[Dict]:
    """Tries multiple local court portals, returns first N results."""
    if not SCRAPLING_AVAILABLE:
        return []
    all_results: List[Dict] = []
    for portal in LOCAL_PORTALS:
        if len(all_results) >= max_results:
            break
        found = _scrapling_search_portal(portal, keyword)
        all_results.extend(found)
        if found:
            time.sleep(0.5)
    print(f"[LEGAL] Local portals → {len(all_results)} orzeczeń")
    return all_results[:max_results]


# ─────────────────────────────────────────────────────────────────────────────
# Deduplicate
# ─────────────────────────────────────────────────────────────────────────────

def _dedup(judgments: List[Dict]) -> List[Dict]:
    seen: set = set()
    out = []
    for j in judgments:
        sig = re.sub(r"\s+", "", (j.get("signature") or "").upper())
        if not sig:
            out.append(j)
            continue
        if sig not in seen:
            seen.add(sig)
            out.append(j)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Prompt block builder
# ─────────────────────────────────────────────────────────────────────────────

LEGAL_DISCLAIMER = (
    "ZASTRZEŻENIE PRAWNE: Niniejszy artykuł ma charakter wyłącznie informacyjny "
    "i nie stanowi porady prawnej. W indywidualnych sprawach zalecamy konsultację "
    "z wykwalifikowanym prawnikiem lub radcą prawnym."
)


def _build_legal_block(keyword: str, judgments: List[Dict], legal_refs: List[Dict]) -> str:
    lines = [f"⚖️ YMYL=PRAWO — KONTEKST PRAWNY dla: {keyword}", ""]

    # ── Legal references (statutes, codes, articles) ──
    if legal_refs:
        lines.append("PRZEPISY PRAWNE (cytuj numery artykułów w tekście):")
        for i, ref in enumerate(legal_refs[:5], 1):
            act = ref.get("act", "")
            articles = ref.get("articles", [])
            desc = ref.get("desc", "")
            art_str = ", ".join(articles) if articles else "cały akt"
            lines.append(f"  #{i} {act} — {art_str}")
            if desc:
                lines.append(f"     → {desc}")
        lines.append("")
        lines.append("Format cytowania przepisów:")
        lines.append("  Zgodnie z art. XX Kodeksu YY, [treść przepisu].")
        lines.append("  Na podstawie art. XX ustawy o ZZ, [konsekwencja].")
        lines.append("NIE wymyślaj numerów artykułów — używaj TYLKO powyższych.")
        lines.append("")

    # ── Court judgments ──
    if judgments:
        lines.append("ORZECZENIA SĄDOWE (użyj maks. 2 sygnatur):")
        lines.append("  Format: Sąd X w wyroku z DD.MM.RRRR (sygn. ABC) stwierdził, że...")
        lines.append("")
        for i, j in enumerate(judgments[:4], 1):
            sig = j.get("signature", "—")
            court = j.get("court", "")
            date = j.get("date", "")
            portal = j.get("portal", "orzeczenia.ms.gov.pl")
            excerpt = j.get("excerpt", "")
            lines.append(f"  #{i} [{j.get('source','?')}] {sig} | {court} | {date} | {portal}")
            if excerpt:
                lines.append(f"     → {excerpt[:200]}")
        lines.append("")

    if not judgments and not legal_refs:
        lines.append("Brak orzeczeń i przepisów do zacytowania.")
        lines.append("Artykuł może być napisany bez konkretnych sygnatur/artykułów.")
        lines.append("Dodaj disclaimer na końcu.")
        lines.append("")

    lines.append(LEGAL_DISCLAIMER)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_legal_context(keyword: str) -> Dict[str, Any]:
    """
    Główna funkcja. Zwraca:
      {
        "status": "OK" | "NO_RESULTS",
        "judgments": [...],
        "legal_refs": [...],
        "prompt_block": "...",   ← gotowy {{YMYL_CONTEXT}}
        "disclaimer": "...",
      }
    """
    print(f"[LEGAL] Szukam kontekstu prawnego dla: '{keyword}'")

    # 1. Legal references (topic map + ISAP)
    legal_refs = _get_legal_references(keyword)

    # 2. SAOS court judgments
    judgments = _saos_search(keyword, max_results=6)

    # 3. Local fallback when SAOS < 2
    if len(judgments) < 2:
        local = _local_courts_search(keyword, max_results=3)
        judgments = _dedup(judgments + local)

    prompt_block = _build_legal_block(keyword, judgments, legal_refs)
    has_data = bool(judgments or legal_refs)

    return {
        "status": "OK" if has_data else "NO_RESULTS",
        "judgments": judgments,
        "legal_refs": legal_refs,
        "prompt_block": prompt_block,
        "disclaimer": LEGAL_DISCLAIMER,
        "sources_used": list(
            {j.get("source") for j in judgments}
            | ({"topic_map"} if any(r.get("source") != "isap_api" for r in legal_refs) else set())
            | ({"isap_api"} if any(r.get("source") == "isap_api" for r in legal_refs) else set())
        ),
    }
