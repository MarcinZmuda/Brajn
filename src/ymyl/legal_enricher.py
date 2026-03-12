"""
⚖️ Legal Enricher — Brajn SEO Engine
=====================================
Pobiera orzeczenia sądowe dla artykułów prawnych (YMYL=prawo).

Źródła (cascade):
  1. SAOS API — System Analizy Orzeczeń Sądowych (REST, bezpłatny)
  2. Lokalne portale sądowe — Scrapling (fallback gdy SAOS < 2 wyniki)

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


def _build_legal_block(keyword: str, judgments: List[Dict]) -> str:
    if not judgments:
        return (
            "⚖️ YMYL=PRAWO — brak orzeczeń do zacytowania.\n"
            "Artykuł może być napisany bez sygnatur. Dodaj disclaimer na końcu.\n"
            f"\n{LEGAL_DISCLAIMER}"
        )

    lines = [
        f"⚖️ YMYL=PRAWO — ORZECZENIA dla: {keyword}",
        f"Użyj maksymalnie 2 sygnatur. Format cytowania:",
        "  Cytuj: Sad X w wyroku z DD.MM.RRRR (sygn. ABC) stwierdził, ze... (dostepne na: portal).",
        "NIE wymyślaj sygnatur — używaj TYLKO poniższych.",
        "",
    ]
    for i, j in enumerate(judgments[:4], 1):
        sig = j.get("signature", "—")
        court = j.get("court", "")
        date = j.get("date", "")
        portal = j.get("portal", "orzeczenia.ms.gov.pl")
        excerpt = j.get("excerpt", "")
        lines.append(f"#{i} [{j.get('source','?')}] {sig} | {court} | {date} | {portal}")
        if excerpt:
            lines.append(f"   → {excerpt[:200]}")
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
        "prompt_block": "...",   ← gotowy {{YMYL_CONTEXT}}
        "disclaimer": "...",
      }
    """
    print(f"[LEGAL] Szukam orzeczeń dla: '{keyword}'")

    # 1. SAOS
    judgments = _saos_search(keyword, max_results=6)

    # 2. Local fallback when SAOS < 2
    if len(judgments) < 2:
        local = _local_courts_search(keyword, max_results=3)
        judgments = _dedup(judgments + local)

    prompt_block = _build_legal_block(keyword, judgments)

    return {
        "status": "OK" if judgments else "NO_RESULTS",
        "judgments": judgments,
        "prompt_block": prompt_block,
        "disclaimer": LEGAL_DISCLAIMER,
        "sources_used": list({j.get("source") for j in judgments}),
    }
