"""
S1 Analysis — main orchestrator for SERP analysis pipeline.
Combines: SERP fetching → scraping → n-gram analysis → entity SEO → causal → gaps.
"""
import os
from src.common.config import ENTITY_SEO_ENABLED
from src.common.nlp_singleton import get_nlp
from src.s1.serp_fetcher import fetch_serp_data
from src.s1.scraper import scrape_parallel
from src.s1.ngram_analyzer import analyze_ngrams, score_h2_candidates

# Optional modules — graceful degradation
try:
    from src.s1.entity_extractor import perform_entity_seo_analysis
    _ENTITY_SEO_AVAILABLE = True
except ImportError:
    _ENTITY_SEO_AVAILABLE = False
    print("[S1] Entity SEO module not available")

try:
    from src.s1.causal_extractor import extract_causal_triplets, format_causal_for_agent
    _CAUSAL_AVAILABLE = True
except ImportError:
    _CAUSAL_AVAILABLE = False
    print("[S1] Causal Extractor not available")

try:
    from src.s1.gap_analyzer import analyze_content_gaps
    _GAP_ANALYZER_AVAILABLE = True
except ImportError:
    _GAP_ANALYZER_AVAILABLE = False
    print("[S1] Gap Analyzer not available")

# Optional: Gemini for semantic extraction
_GEMINI_AVAILABLE = False
try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        _GEMINI_AVAILABLE = True
except ImportError:
    pass


def _extract_semantic_tags_gemini(text: str, top_n: int = 10) -> list:
    """Extract semantic keyphrases using Gemini Flash."""
    if not _GEMINI_AVAILABLE or not text.strip():
        return []
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"""Jesteś ekspertem SEO. Przeanalizuj poniższy tekst i wypisz {top_n} najważniejszych fraz kluczowych (semantic keywords), które najlepiej oddają jego sens.
Zwróć TYLKO listę po przecinku, bez numerowania.

TEKST: {text[:8000]}..."""
        response = model.generate_content(prompt)
        keywords = [k.strip() for k in (response.text or "").split(",") if k.strip()]
        return [{"phrase": kw, "score": 0.95 - (i * 0.02)} for i, kw in enumerate(keywords[:top_n])]
    except Exception as e:
        print(f"[S1] Gemini semantic error: {e}")
        return []


def run_s1_analysis(
    main_keyword: str,
    sources: list[dict] | None = None,
    top_n: int = 30,
    project_id: str | None = None,
) -> dict:
    """
    Run complete S1 analysis pipeline.

    If sources is empty/None, auto-fetches from SerpAPI.

    Returns full S1 response payload compatible with BRAJEN pipeline.
    """
    paa_questions = []
    featured_snippet = None
    ai_overview = None
    related_searches = []
    serp_titles = []
    serp_snippets = []

    if not sources:
        if not main_keyword:
            return {"error": "Brak main_keyword do analizy"}

        # Fetch SERP data
        serp_result = fetch_serp_data(main_keyword, num_results=8)

        paa_questions = serp_result.get("paa", [])
        featured_snippet = serp_result.get("featured_snippet")
        ai_overview = serp_result.get("ai_overview")
        related_searches = serp_result.get("related_searches", [])
        serp_titles = serp_result.get("serp_titles", [])
        serp_snippets = serp_result.get("serp_snippets", [])

        # Scrape organic results
        organic_results = serp_result.get("organic_results", [])
        scrape_targets = [
            {"url": r.get("link", ""), "title": r.get("title", "")}
            for r in organic_results[:8]
            if r.get("link")
        ]

        sources = scrape_parallel(scrape_targets)

        # If no scraped sources, try synthetic from snippets
        if not sources and (serp_snippets or serp_titles):
            print("[S1] 0 scraped sources — creating synthetic from SERP snippets")
            for i, (title, snippet) in enumerate(zip(serp_titles, serp_snippets)):
                synthetic = f"{title}. {snippet}"
                if len(synthetic) > 50:
                    sources.append({
                        "url": f"serp_snippet_{i}",
                        "title": title,
                        "content": synthetic,
                        "h2_structure": [],
                        "word_count": len(synthetic.split()),
                        "is_snippet": True,
                    })

        if not sources:
            return {
                "error": "Nie udało się pobrać źródeł",
                "main_keyword": main_keyword,
                "paa": paa_questions,
                "related_searches": related_searches,
            }

    # N-gram analysis
    ngram_result = analyze_ngrams(
        sources=sources,
        main_keyword=main_keyword,
        paa_questions=paa_questions,
        related_searches=related_searches,
        serp_titles=serp_titles,
        serp_snippets=serp_snippets,
        top_n=top_n,
    )

    # Semantic keyphrases (Gemini)
    full_text_sample = " ".join(ngram_result["all_text_content"])[:15_000]
    semantic_keyphrases = _extract_semantic_tags_gemini(full_text_sample)

    # SERP analysis data
    serp_analysis_data = {
        "paa_questions": paa_questions,
        "featured_snippet": featured_snippet,
        "ai_overview": ai_overview,
        "related_searches": related_searches,
        "competitor_titles": serp_titles[:10],
        "competitor_snippets": serp_snippets[:10],
        "competitor_h2_patterns": ngram_result["h2_patterns"],
        "competitors": [
            {
                "url": src.get("url", ""),
                "title": src.get("title", ""),
                "word_count": src.get("word_count", 0),
                "h2_count": len(src.get("h2_structure", [])),
                "first_paragraph": (src.get("content", "") or "")[:400].strip(),
            }
            for src in sources
        ],
    }

    # Entity SEO
    nlp = get_nlp()
    entity_seo_data = None
    if ENTITY_SEO_ENABLED and _ENTITY_SEO_AVAILABLE and sources:
        try:
            entity_seo_data = perform_entity_seo_analysis(
                nlp=nlp,
                sources=sources,
                main_keyword=main_keyword,
                h2_patterns=ngram_result["h2_patterns"],
            )
            print(f"[S1] Entity SEO: {entity_seo_data.get('entity_seo_summary', {}).get('total_entities', 0)} entities")
        except Exception as e:
            print(f"[S1] Entity SEO error: {e}")
            entity_seo_data = {"error": str(e), "status": "FAILED"}

    # Causal Triplets
    causal_data = None
    if _CAUSAL_AVAILABLE and sources:
        try:
            causal_triplets = extract_causal_triplets(
                texts=[s.get("content", "") for s in sources],
                main_keyword=main_keyword,
            )
            causal_data = {
                "count": len(causal_triplets),
                "chains": [t.to_dict() for t in causal_triplets if t.is_chain],
                "singles": [t.to_dict() for t in causal_triplets if not t.is_chain],
                "agent_instruction": format_causal_for_agent(causal_triplets, main_keyword),
            }
        except Exception as e:
            print(f"[S1] Causal extraction error: {e}")
            causal_data = {"error": str(e), "status": "FAILED"}

    # Content Gaps
    content_gaps_data = None
    if _GAP_ANALYZER_AVAILABLE and sources:
        try:
            content_gaps_data = analyze_content_gaps(
                competitor_texts=[s.get("content", "") for s in sources],
                competitor_h2s=ngram_result["h2_patterns"],
                paa_questions=paa_questions,
                related_searches=related_searches,
                main_keyword=main_keyword,
            )
        except Exception as e:
            print(f"[S1] Gap analysis error: {e}")
            content_gaps_data = {"error": str(e), "status": "FAILED"}

    # Build response
    response = {
        "main_keyword": main_keyword,
        "ngrams": ngram_result["ngrams"],
        "extended_terms": ngram_result["extended_terms"],
        "h2_patterns": ngram_result["h2_patterns"],
        "semantic_keyphrases": semantic_keyphrases,
        "full_text_sample": full_text_sample,
        "serp_content": full_text_sample,
        "serp_analysis": serp_analysis_data,
        "entity_seo": entity_seo_data,
        "causal_triplets": causal_data,
        "content_gaps": content_gaps_data,
        "summary": {
            "total_sources": len(sources),
            "paa_count": len(paa_questions),
            "has_featured_snippet": featured_snippet is not None,
            "has_ai_overview": ai_overview is not None,
            "related_searches_count": len(related_searches),
            "h2_patterns_found": len(ngram_result["h2_patterns"]),
            "entity_seo_enabled": ENTITY_SEO_ENABLED,
            "entities_found": (entity_seo_data or {}).get("entity_seo_summary", {}).get("total_entities", 0),
            "causal_triplets_found": (causal_data or {}).get("count", 0),
            "content_gaps_found": (content_gaps_data or {}).get("total_gaps", 0),
            "extended_terms_count": len(ngram_result["extended_terms"]),
            "lsi_candidates": len(semantic_keyphrases),
        },
    }

    # H2 scoring
    try:
        h2_scored = score_h2_candidates(response, main_keyword)
        if h2_scored and h2_scored.get("all_candidates"):
            response["h2_scored_candidates"] = h2_scored
    except Exception as e:
        print(f"[S1] H2 scoring error: {e}")

    # Firestore save
    if project_id:
        try:
            from src.common.firebase import save_project
            save_project(project_id, {
                "s1_data": response,
                "avg_competitor_length": (
                    sum(len(t.split()) for t in ngram_result["all_text_content"]) // len(ngram_result["all_text_content"])
                    if ngram_result["all_text_content"] else 0
                ),
            })
            response["saved_to_firestore"] = True
        except Exception as e:
            print(f"[S1] Firestore error: {e}")

    # Attach cleaned version for LLM (panel uses full response, LLM uses cleaned)
    try:
        from src.s1.data_cleaner import clean_s1_for_llm
        response["_llm_ready"] = clean_s1_for_llm(response)
        print(f"[S1] LLM-ready data prepared")
    except Exception as e:
        print(f"[S1] clean_s1_for_llm error: {e}")

    return response
