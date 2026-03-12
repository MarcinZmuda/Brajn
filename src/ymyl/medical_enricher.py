"""
🏥 Medical Enricher — Brajn SEO Engine
=======================================
Pobiera źródła medyczne dla artykułów zdrowotnych (YMYL=zdrowie).

Źródła (cascade):
  1. PubMed E-utilities — NCBI REST API (bezpłatny, bez klucza 3 req/s)
  2. ClinicalTrials.gov — REST API v2
  3. Polskie instytucje — PZH, AOTMiT via Scrapling

Wynik: blok {{YMYL_CONTEXT}} wstrzykiwany do PRE_BATCH i BATCH_N.
"""

import re
import os
import time
import json
from typing import List, Dict, Any, Optional
from xml.etree import ElementTree

import requests

# ── Scrapling ────────────────────────────────────────────────────────────────
SCRAPLING_AVAILABLE = False
try:
    from scrapling.fetchers import Fetcher as ScraplingFetcher
    SCRAPLING_AVAILABLE = True
    print("[MEDICAL] ✅ Scrapling available")
except ImportError:
    print("[MEDICAL] ⚠️ Scrapling not installed — pip install scrapling")

# ─────────────────────────────────────────────────────────────────────────────
# Polish → English term mapping (for PubMed queries)
# ─────────────────────────────────────────────────────────────────────────────

TERM_MAP = {
    "cukrzyca": "diabetes mellitus",
    "cukrzyca typu 2": "type 2 diabetes",
    "cukrzyca typu 1": "type 1 diabetes",
    "nadciśnienie": "hypertension",
    "zawał serca": "myocardial infarction",
    "udar mózgu": "stroke",
    "astma": "asthma",
    "depresja": "depression",
    "lęk": "anxiety",
    "schizofrenia": "schizophrenia",
    "alzheimer": "alzheimer disease",
    "parkinson": "parkinson disease",
    "stwardnienie rozsiane": "multiple sclerosis",
    "rak piersi": "breast cancer",
    "rak płuca": "lung cancer",
    "rak jelita": "colorectal cancer",
    "białaczka": "leukemia",
    "chłoniak": "lymphoma",
    "otyłość": "obesity",
    "osteoporoza": "osteoporosis",
    "niewydolność serca": "heart failure",
    "marskość wątroby": "liver cirrhosis",
    "zapalenie płuc": "pneumonia",
    "grypa": "influenza",
    "covid": "COVID-19",
    "metformina": "metformin",
    "insulina": "insulin",
    "aspiryna": "aspirin",
    "antybiotyk": "antibiotic",
    "statyny": "statins",
    "chemioterapia": "chemotherapy",
    "radioterapia": "radiotherapy",
    "immunoterapia": "immunotherapy",
    "leczenie": "treatment",
    "terapia": "therapy",
    "profilaktyka": "prevention",
    "objawy": "symptoms",
    "diagnoza": "diagnosis",
    "rehabilitacja": "rehabilitation",
}


def _translate_to_en(keyword: str) -> str:
    """Best-effort Polish → English for PubMed."""
    kw = keyword.lower()
    # Sort by length descending for greedy match
    for pl, en in sorted(TERM_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if pl in kw:
            kw = kw.replace(pl, en)
    return kw.strip()


# ─────────────────────────────────────────────────────────────────────────────
# PubMed E-utilities
# ─────────────────────────────────────────────────────────────────────────────

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "brajn@seo.pl")


def _pubmed_search(query: str, max_results: int = 5) -> List[str]:
    """ESearch — returns list of PMIDs."""
    try:
        params = {
            "db": "pubmed",
            "term": f"({query}) AND (\"systematic review\"[pt] OR \"meta-analysis\"[pt] OR \"randomized controlled trial\"[pt] OR \"review\"[pt])",
            "retmax": max_results,
            "sort": "relevance",
            "retmode": "json",
            "tool": "BrajnSEO",
            "email": NCBI_EMAIL,
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        r = requests.get(f"{PUBMED_BASE}/esearch.fcgi", params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        pmids = data.get("esearchresult", {}).get("idlist", [])
        print(f"[MEDICAL] PubMed ESearch → {len(pmids)} PMIDs")
        return pmids
    except Exception as e:
        print(f"[MEDICAL] PubMed search error: {e}")
        return []


def _pubmed_fetch(pmids: List[str]) -> List[Dict]:
    """EFetch — returns publication metadata."""
    if not pmids:
        return []
    try:
        time.sleep(0.35)  # NCBI rate limit without key
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
            "tool": "BrajnSEO",
            "email": NCBI_EMAIL,
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        r = requests.get(f"{PUBMED_BASE}/efetch.fcgi", params=params, timeout=20)
        r.raise_for_status()

        root = ElementTree.fromstring(r.text)
        results = []

        for article in root.findall(".//PubmedArticle"):
            try:
                pmid = article.findtext(".//PMID") or ""
                title = article.findtext(".//ArticleTitle") or ""
                year = (
                    article.findtext(".//PubDate/Year")
                    or article.findtext(".//PubDate/MedlineDate", "")[:4]
                )
                journal = article.findtext(".//Journal/Title") or ""
                abstract_texts = article.findall(".//AbstractText")
                abstract = " ".join(
                    (at.text or "") for at in abstract_texts if at.text
                )[:500]

                # Authors
                author_list = article.findall(".//Author")
                if author_list:
                    last = author_list[0].findtext("LastName") or ""
                    authors_short = f"{last} et al." if len(author_list) > 1 else last
                else:
                    authors_short = "Unknown"

                # Article type
                pub_type_list = article.findall(".//PublicationType")
                pub_types = [pt.text or "" for pt in pub_type_list]
                evidence_label = "Review"
                for pt in ["Meta-Analysis", "Systematic Review", "Randomized Controlled Trial", "Guideline"]:
                    if any(pt in ptt for ptt in pub_types):
                        evidence_label = pt
                        break

                results.append({
                    "pmid": pmid,
                    "title": title,
                    "authors_short": authors_short,
                    "year": year,
                    "journal": journal,
                    "abstract": abstract,
                    "evidence_label": evidence_label,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "source": "pubmed",
                })
            except Exception:
                continue

        print(f"[MEDICAL] PubMed EFetch → {len(results)} publikacji")
        return results
    except Exception as e:
        print(f"[MEDICAL] PubMed fetch error: {e}")
        return []


def search_pubmed(keyword: str, max_results: int = 4) -> List[Dict]:
    """Full PubMed pipeline: search → fetch."""
    en_query = _translate_to_en(keyword)
    print(f"[MEDICAL] PubMed query: '{en_query}'")
    pmids = _pubmed_search(en_query, max_results=max_results)
    if not pmids:
        # Fallback: simplified query
        pmids = _pubmed_search(keyword, max_results=max_results)
    return _pubmed_fetch(pmids[:max_results])


# ─────────────────────────────────────────────────────────────────────────────
# ClinicalTrials.gov v2 API
# ─────────────────────────────────────────────────────────────────────────────

CT_BASE = "https://clinicaltrials.gov/api/v2"


def search_clinical_trials(keyword: str, max_results: int = 2) -> List[Dict]:
    """ClinicalTrials.gov — completed studies only."""
    try:
        en_query = _translate_to_en(keyword)
        params = {
            "query.cond": en_query,
            "filter.overallStatus": "COMPLETED",
            "fields": "NCTId,BriefTitle,BriefSummary,LeadSponsorName,StartDate,CompletionDate",
            "pageSize": max_results,
            "format": "json",
        }
        r = requests.get(f"{CT_BASE}/studies", params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        studies = data.get("studies", [])
        results = []
        for s in studies:
            proto = s.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            status = proto.get("statusModule", {})
            desc = proto.get("descriptionModule", {})
            nct_id = ident.get("nctId", "")
            results.append({
                "nct_id": nct_id,
                "title": ident.get("briefTitle", "")[:80],
                "summary": (desc.get("briefSummary") or "")[:400],
                "sponsor": proto.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", ""),
                "completion": status.get("completionDateStruct", {}).get("date", ""),
                "url": f"https://clinicaltrials.gov/study/{nct_id}",
                "source": "clinicaltrials",
            })
        print(f"[MEDICAL] ClinicalTrials → {len(results)} badań")
        return results
    except Exception as e:
        print(f"[MEDICAL] ClinicalTrials error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Polish health institutions via Scrapling
# ─────────────────────────────────────────────────────────────────────────────

POLISH_SOURCES = [
    {
        "name": "NIZP-PZH",
        "search_url": "https://www.pzh.gov.pl/?s={query}",
        "link_pattern": "a[href*='pzh.gov.pl']",
    },
    {
        "name": "AOTMiT",
        "search_url": "https://www.aotm.gov.pl/?s={query}",
        "link_pattern": "a[href*='aotm.gov.pl']",
    },
    {
        "name": "MZ",
        "search_url": "https://www.gov.pl/web/zdrowie/szukaj?query={query}",
        "link_pattern": "a.search-result__title-link",
    },
]


def _scrapling_polish_source(source: Dict, keyword: str) -> Optional[Dict]:
    """Fetches one result from a Polish health source."""
    if not SCRAPLING_AVAILABLE:
        return None
    try:
        fetcher = ScraplingFetcher(auto_match=False)
        url = source["search_url"].format(query=requests.utils.quote(keyword))
        page = fetcher.get(url, timeout=12, stealthy_headers=True)
        if not page:
            return None

        links = page.css(source["link_pattern"])
        if not links:
            links = page.css("h2 a, h3 a, .search-result a, article a")

        if not links:
            return None

        first = links[0]
        title = first.text.strip()[:100]
        href = first.attrib.get("href", "")
        if not href.startswith("http"):
            base = source["search_url"].split("/?")[0].split("/szukaj")[0].split("/web")[0]
            href = base + href

        # Try to scrape content from the result page
        content = ""
        try:
            detail = fetcher.get(href, timeout=10, stealthy_headers=True)
            if detail:
                paragraphs = detail.css("article p, .content p, .entry-content p")
                content = " ".join(p.text.strip() for p in paragraphs[:4] if p.text)[:600]
        except Exception:
            pass

        return {
            "source": source["name"],
            "title": title,
            "url": href,
            "content": content,
        }
    except Exception as e:
        print(f"[MEDICAL] Polish source {source['name']} error: {e}")
        return None


def search_polish_health(keyword: str, max_results: int = 2) -> List[Dict]:
    """Searches Polish health institutions for the keyword."""
    if not SCRAPLING_AVAILABLE:
        return []
    results = []
    for source in POLISH_SOURCES:
        if len(results) >= max_results:
            break
        item = _scrapling_polish_source(source, keyword)
        if item:
            results.append(item)
            time.sleep(1.0)  # Be polite
    print(f"[MEDICAL] Polish health → {len(results)} źródeł")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Prompt block builder
# ─────────────────────────────────────────────────────────────────────────────

MEDICAL_DISCLAIMER = (
    "ZASTRZEŻENIE: Ten artykuł ma charakter wyłącznie informacyjny i edukacyjny. "
    "Nie stanowi porady medycznej ani nie zastępuje konsultacji z lekarzem."
)


def _build_medical_block(
    keyword: str,
    publications: List[Dict],
    trials: List[Dict],
    polish: List[Dict],
) -> str:
    total = len(publications) + len(trials) + len(polish)
    lines = [
        f"🏥 YMYL=ZDROWIE — ŹRÓDŁA MEDYCZNE dla: {keyword}",
        f"Pisz na podstawie poniższych źródeł. Cytuj format: (źródło: [Nazwa](URL)).",
        "Każde źródło cytuj MAKSYMALNIE RAZ. Disclaimer na końcu artykułu.",
        "",
    ]

    src_num = 0

    for pub in publications[:2]:
        src_num += 1
        lines.append(
            f"#{src_num} [PubMed] {pub.get('authors_short','?')} ({pub.get('year','?')}) — "
            f"{pub.get('title','')[:80]} [{pub.get('evidence_label','')}]"
        )
        lines.append(f"   Cytuj: (źródło: [PubMed]({pub.get('url','')}))")
        if pub.get("abstract"):
            lines.append(f"   Streszczenie: {pub['abstract'][:400]}")
        lines.append("")

    for trial in trials[:1]:
        src_num += 1
        lines.append(
            f"#{src_num} [ClinicalTrials] {trial.get('nct_id','')} — {trial.get('title','')}"
        )
        lines.append(f"   Cytuj: (źródło: [ClinicalTrials.gov]({trial.get('url','')}))")
        if trial.get("summary"):
            lines.append(f"   Opis: {trial['summary'][:300]}")
        lines.append("")

    for pl in polish[:1]:
        src_num += 1
        lines.append(
            f"#{src_num} [{pl.get('source','PL')}] {pl.get('title','')[:70]}"
        )
        lines.append(
            f"   Cytuj: (źródło: [{pl.get('source','PL')}]({pl.get('url','')}))"
        )
        if pl.get("content"):
            lines.append(f"   Treść: {pl['content'][:500]}")
        lines.append("")

    if total == 0:
        lines.append("Brak źródeł medycznych — pisz na podstawie wiedzy ogólnej, bez wymyślania statystyk.")

    lines.append("NIE wymyślaj badań ani URL. Terminologia medyczna + wyjaśnienia dla laika.")
    lines.append("")
    lines.append(MEDICAL_DISCLAIMER)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_medical_context(keyword: str) -> Dict[str, Any]:
    """
    Główna funkcja. Zwraca:
      {
        "status": "OK" | "NO_RESULTS",
        "publications": [...],
        "trials": [...],
        "polish_sources": [...],
        "prompt_block": "...",   ← gotowy {{YMYL_CONTEXT}}
        "disclaimer": "...",
      }
    """
    print(f"[MEDICAL] Szukam źródeł dla: '{keyword}'")

    publications = search_pubmed(keyword, max_results=4)
    trials = search_clinical_trials(keyword, max_results=2)
    polish = search_polish_health(keyword, max_results=2)

    prompt_block = _build_medical_block(keyword, publications, trials, polish)
    total = len(publications) + len(trials) + len(polish)

    return {
        "status": "OK" if total > 0 else "NO_RESULTS",
        "publications": publications,
        "trials": trials,
        "polish_sources": polish,
        "prompt_block": prompt_block,
        "disclaimer": MEDICAL_DISCLAIMER,
        "sources_used": (
            (["pubmed"] if publications else [])
            + (["clinicaltrials"] if trials else [])
            + (["polish_health"] if polish else [])
        ),
    }
