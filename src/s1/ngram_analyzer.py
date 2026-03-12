"""
N-gram analysis engine — lemma-based with high-signal source boosting.
Ported from gpt-ngram-api v56.1.
"""
from collections import Counter, defaultdict
from src.common.nlp_singleton import get_nlp


def _lemmatize_tokens(nlp, text: str, limit: int = 50_000) -> tuple[list, list]:
    """Returns (raw_tokens, lemma_tokens) aligned, only alpha tokens."""
    doc = nlp(text[:limit])
    raw_toks, lem_toks = [], []
    for t in doc:
        if t.is_alpha:
            raw_toks.append(t.text.lower())
            lem_toks.append(t.lemma_.lower())
    return raw_toks, lem_toks


def _build_ngrams_for_source(
    raw_toks: list,
    lem_toks: list,
    src_label: str,
    src_idx: int,
    ngram_freqs: Counter,
    ngram_presence: dict,
    ngram_per_source: dict,
    lemma_surface_freq: dict,
):
    """Build 2-4 grams using lemmas as key, surface form for display."""
    for n in range(2, 5):
        for i in range(len(lem_toks) - n + 1):
            lemma_key = " ".join(lem_toks[i : i + n])
            surface_form = " ".join(raw_toks[i : i + n])
            ngram_freqs[lemma_key] += 1
            ngram_presence[lemma_key].add(src_label)
            ngram_per_source[lemma_key][src_idx] += 1
            lemma_surface_freq[lemma_key][surface_form] += 1


def analyze_ngrams(
    sources: list[dict],
    main_keyword: str,
    paa_questions: list = None,
    related_searches: list = None,
    serp_titles: list = None,
    serp_snippets: list = None,
    top_n: int = 30,
) -> dict:
    """
    Perform full n-gram analysis on sources.

    Returns:
        {
            "ngrams": [...],           # top_n basic terms
            "extended_terms": [...],   # 30-80% competitor coverage
            "h2_patterns": [...],      # unique H2 headings from competitors
            "all_text_content": [...], # raw text from all sources
        }
    """
    nlp = get_nlp()
    paa_questions = paa_questions or []
    related_searches = related_searches or []
    serp_titles = serp_titles or []
    serp_snippets = serp_snippets or []

    ngram_presence = defaultdict(set)
    ngram_freqs = Counter()
    ngram_per_source = defaultdict(lambda: Counter())
    lemma_surface_freq = defaultdict(Counter)
    all_text_content = []
    h2_patterns = []
    h2_source_counter = {}  # h2_lower → set of source urls (for scoring)

    # Main sources: scraped pages
    for src_idx, src in enumerate(sources):
        content = (src.get("content", "") or "").lower()
        if not content.strip():
            continue
        all_text_content.append(src.get("content", ""))
        src_h2 = src.get("h2_structure", [])
        if src_h2:
            h2_patterns.extend(src_h2)
            src_url = src.get("url", f"src_{src_idx}")
            for h in src_h2:
                if h:
                    key = h.strip().lower()
                    if key not in h2_source_counter:
                        h2_source_counter[key] = set()
                    h2_source_counter[key].add(src_url)
        raw_toks, lem_toks = _lemmatize_tokens(nlp, content)
        _build_ngrams_for_source(
            raw_toks, lem_toks,
            src.get("url", f"src_{src_idx}"), src_idx,
            ngram_freqs, ngram_presence, ngram_per_source, lemma_surface_freq,
        )

    # High-signal sources: PAA + related searches + SERP snippets
    HIGH_SIGNAL_SRC_IDX = len(sources)
    HIGH_SIGNAL_LABEL = "__google_signals__"
    high_signal_texts = []

    for paa_item in paa_questions:
        q = paa_item.get("question", "") if isinstance(paa_item, dict) else str(paa_item)
        if q:
            high_signal_texts.append(q)
    for rs in related_searches:
        q = rs if isinstance(rs, str) else (rs.get("query", "") or rs.get("text", ""))
        if q:
            high_signal_texts.append(q)
    for title in serp_titles:
        if title:
            high_signal_texts.append(title)
    for snippet in serp_snippets:
        if snippet:
            high_signal_texts.append(snippet)

    if high_signal_texts:
        combined_signal = " . ".join(high_signal_texts)
        raw_hs, lem_hs = _lemmatize_tokens(nlp, combined_signal, limit=20_000)
        _build_ngrams_for_source(
            raw_hs, lem_hs,
            HIGH_SIGNAL_LABEL, HIGH_SIGNAL_SRC_IDX,
            ngram_freqs, ngram_presence, ngram_per_source, lemma_surface_freq,
        )
        print(f"[NGRAM] High-signal: {len(high_signal_texts)} texts added")

    # Resolve best surface form per lemma-key
    lemma_to_surface = {}
    for lemma_key, surface_counts in lemma_surface_freq.items():
        lemma_to_surface[lemma_key] = surface_counts.most_common(1)[0][0]

    max_freq = max(ngram_freqs.values()) if ngram_freqs else 1
    num_sources = len(sources)
    results = []

    for ngram, freq in ngram_freqs.items():
        page_presence = {s for s in ngram_presence[ngram] if s != HIGH_SIGNAL_LABEL}
        page_freq = sum(
            cnt for idx, cnt in ngram_per_source[ngram].items()
            if idx != HIGH_SIGNAL_SRC_IDX
        )
        is_high_signal_only = (
            HIGH_SIGNAL_LABEL in ngram_presence[ngram] and not page_presence
        )

        if page_freq < 2 and not is_high_signal_only:
            continue

        display_ngram = lemma_to_surface.get(ngram, ngram)
        page_presence_set = {s for s in ngram_presence[ngram] if s != HIGH_SIGNAL_LABEL}
        freq_norm = page_freq / max_freq if max_freq else 0
        site_score = len(page_presence_set) / num_sources if num_sources else 0
        weight = round(freq_norm * 0.5 + site_score * 0.5, 4)

        if main_keyword and main_keyword.lower() in display_ngram:
            weight += 0.1
        if HIGH_SIGNAL_LABEL in ngram_presence[ngram]:
            weight += 0.08

        # Per-source frequency stats (Surfer-style ranges)
        per_src = ngram_per_source.get(ngram, {})
        all_counts = [per_src.get(i, 0) for i in range(num_sources)]
        non_zero = sorted([c for c in all_counts if c > 0])

        if non_zero:
            freq_min = non_zero[0]
            freq_max = non_zero[-1]
            mid = len(non_zero) // 2
            freq_median = (
                non_zero[mid]
                if len(non_zero) % 2 == 1
                else (non_zero[mid - 1] + non_zero[mid]) // 2
            )
        else:
            freq_min = freq_median = freq_max = 0

        results.append({
            "ngram": display_ngram,
            "ngram_lemma": ngram,
            "freq": page_freq,
            "freq_total": freq,
            "is_high_signal": is_high_signal_only,
            "weight": min(1.0, weight),
            "site_distribution": f"{len(page_presence_set)}/{num_sources}",
            "freq_per_source": all_counts,
            "freq_min": freq_min,
            "freq_median": freq_median,
            "freq_max": freq_max,
        })

    # Sort and split into basic + extended
    all_results_sorted = sorted(results, key=lambda x: x["weight"], reverse=True)
    basic_terms = all_results_sorted[:top_n]
    basic_lemmas = {r["ngram_lemma"] for r in basic_terms}

    # Extended = phrases from 30-80% sources not in basic top_n
    extended_terms = []
    if num_sources >= 3:
        ext_min = max(2, int(num_sources * 0.3))
        ext_max = int(num_sources * 0.8)

        for r in all_results_sorted:
            if r["ngram_lemma"] in basic_lemmas:
                continue
            try:
                src_count = int(r["site_distribution"].split("/")[0])
            except (ValueError, IndexError):
                continue
            if ext_min <= src_count <= ext_max:
                extended_terms.append({
                    "term": r["ngram"],
                    "term_lemma": r["ngram_lemma"],
                    "sources_count": src_count,
                    "sources_total": num_sources,
                    "site_distribution": r["site_distribution"],
                    "weight": r["weight"],
                    "type": "EXTENDED_SUGGESTION",
                })

        extended_terms.sort(key=lambda x: (x["sources_count"], x["weight"]), reverse=True)
        extended_terms = extended_terms[:15]

    # Build unique H2 list (raw strings, deduped)
    unique_h2_raw = list(dict.fromkeys(h2_patterns))[:90]  # wide net before cleaning

    # ── Data cleaning pass ──
    try:
        from src.s1.data_cleaner import clean_h2_patterns, clean_ngrams
        unique_h2_strings = clean_h2_patterns(unique_h2_raw, main_keyword)[:40]
        basic_terms = clean_ngrams(basic_terms, main_keyword)
        extended_terms = clean_ngrams(extended_terms, main_keyword)
        print(f"[NGRAM] After cleaning: {len(basic_terms)} basic, {len(extended_terms)} extended, {len(unique_h2_strings)} H2")
    except ImportError:
        unique_h2_strings = unique_h2_raw[:30]

    # Build scored H2 dicts with source count
    # KEY INSIGHT: Nav items (Mapa serwisu, BIP, footer) always appear on exactly 1 page.
    # Real content H2s repeat across competitors. Min threshold = 2 sources eliminates
    # all single-page nav garbage without any blacklist.
    num_sources_total = len(sources) or 1
    # Dynamic threshold: 2 for small corpora, 3 for 6+ sources
    MIN_H2_SOURCES = 2 if num_sources_total <= 5 else 3
    unique_h2_patterns = []
    seen_h2 = set()
    for h in unique_h2_strings:
        key = h.strip().lower()
        if key in seen_h2:
            continue
        seen_h2.add(key)
        src_count = len(h2_source_counter.get(key, set()))
        if src_count < MIN_H2_SOURCES:
            continue  # single-page H2 = nav item, skip
        unique_h2_patterns.append({
            "text": h,
            "count": src_count,
            "sources_total": num_sources_total,
            "site_distribution": f"{src_count}/{num_sources_total}",
        })

    # Sort by count descending
    unique_h2_patterns.sort(key=lambda x: x["count"], reverse=True)
    print(f"[NGRAM] H2 after source-count filter (min {MIN_H2_SOURCES}): {len(unique_h2_patterns)} headings")

    return {
        "ngrams": basic_terms,
        "extended_terms": extended_terms,
        "h2_patterns": unique_h2_patterns,
        "all_text_content": all_text_content,
    }


def score_h2_candidates(s1_data: dict, main_keyword: str = "") -> dict:
    """
    Score H2 candidates from S1 response data.
    Simple business logic: competitor count, PAA unanswered, content gaps.
    """
    candidates = []
    seen = set()

    # Pool 1: Competitor H2 patterns
    serp_h2 = (s1_data.get("serp_analysis") or {}).get("competitor_h2_patterns") or []
    for h in serp_h2:
        if isinstance(h, dict):
            text = h.get("text", h.get("pattern", h.get("h2", "")))
            count = h.get("count", h.get("sources", 1))
        elif isinstance(h, str):
            text, count = h, 1
        else:
            continue
        if not text or text.lower().strip() in seen:
            continue
        seen.add(text.lower().strip())
        score = min(count * 0.085, 0.85)
        candidates.append({
            "text": text,
            "score": round(score, 3),
            "source": "competitor",
            "comp_count": count,
            "reason": f"{count}x u konkurencji",
        })

    # Pool 2: PAA unanswered
    content_gaps = s1_data.get("content_gaps") or {}
    for q in (content_gaps.get("paa_unanswered") or [])[:8]:
        q_text = q if isinstance(q, str) else (q.get("question", q.get("text", "")) if isinstance(q, dict) else str(q))
        if not q_text or q_text.lower().strip() in seen:
            continue
        seen.add(q_text.lower().strip())
        candidates.append({
            "text": q_text if q_text.endswith("?") else f"{q_text}?",
            "score": 0.50,
            "source": "paa_unanswered",
            "reason": "PAA bez odpowiedzi u konkurencji",
        })

    # Pool 3: Suggested new H2s
    for h in (content_gaps.get("suggested_new_h2s") or [])[:6]:
        h_text = h if isinstance(h, str) else (h.get("h2", h.get("title", "")) if isinstance(h, dict) else str(h))
        if not h_text or h_text.lower().strip() in seen:
            continue
        seen.add(h_text.lower().strip())
        candidates.append({
            "text": h_text,
            "score": 0.35,
            "source": "content_gap",
            "reason": "Luka - nikt z TOP-10 nie pokrywa",
        })

    # Pool 4: depth_missing
    for d in (content_gaps.get("depth_missing") or [])[:5]:
        d_text = d if isinstance(d, str) else (d.get("topic", d.get("text", "")) if isinstance(d, dict) else str(d))
        if not d_text or d_text.lower().strip() in seen:
            continue
        seen.add(d_text.lower().strip())
        candidates.append({
            "text": d_text,
            "score": 0.25,
            "source": "depth_missing",
            "reason": "Zbyt plytko u konkurencji",
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    must_have = [c for c in candidates if c["score"] >= 0.65]
    high_prio = [c for c in candidates if 0.40 <= c["score"] < 0.65]
    optional = [c for c in candidates if c["score"] < 0.40]

    return {
        "must_have": must_have,
        "high_priority": high_prio,
        "optional": optional,
        "all_candidates": candidates,
        "stats": {
            "total": len(candidates),
            "must_have": len(must_have),
            "high_priority": len(high_prio),
            "optional": len(optional),
        },
    }
