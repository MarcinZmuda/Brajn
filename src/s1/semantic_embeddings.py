"""
===============================================================================
🧠 SEMANTIC EMBEDDINGS v1.0 — Gemini Embedding 2 integration
===============================================================================
Używa Gemini Embedding 2 (multimodalny) do:

1. semantic_gap_analysis()   — luki treści przez cosine similarity
2. semantic_entity_clusters()— grupowanie encji semantycznie (nie po freq)
3. semantic_h2_ranking()     — ranking H2 kandydatów względem intencji
4. multimodal_embed()        — embeddingi obrazów/audio (future-ready)

Model: gemini-embedding-2-preview
Wymiary: 768 (balans jakość/koszt), max 3072

Autor: BRAJEN Team
===============================================================================
"""

import os
import math
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# ── Gemini client (lazy init) ─────────────────────────────────
_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            from google import genai
            api_key = os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                raise ValueError("GEMINI_API_KEY not set")
            _client = genai.Client(api_key=api_key)
        except Exception as e:
            print(f"[SEMANTIC] ❌ Gemini client init failed: {e}")
            return None
    return _client


_MODEL = "gemini-embedding-2-preview"
_DIMS = 768  # recommended: 768 for balance, 3072 for max quality


# ================================================================
# 📐 MATH HELPERS
# ================================================================

def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embed_texts(texts: List[str], output_dimensionality: int = _DIMS) -> List[List[float]]:
    """
    Embed a list of texts using Gemini Embedding 2.
    Returns list of embedding vectors (empty list on failure).
    """
    client = _get_client()
    if not client or not texts:
        return []

    # Clean and truncate texts
    clean = [str(t)[:8000] for t in texts if t and str(t).strip()]
    if not clean:
        return []

    try:
        from google.genai import types as gtypes
        result = client.models.embed_content(
            model=_MODEL,
            contents=clean,
            config=gtypes.EmbedContentConfig(
                output_dimensionality=output_dimensionality,
                task_type="SEMANTIC_SIMILARITY",
            ),
        )
        return [list(e.values) for e in result.embeddings]
    except Exception as e:
        print(f"[SEMANTIC] ❌ Embedding error: {e}")
        return []


def _embed_single(text: str, output_dimensionality: int = _DIMS) -> List[float]:
    """Embed a single text. Returns empty list on failure."""
    results = _embed_texts([text], output_dimensionality)
    return results[0] if results else []


# ================================================================
# 1. SEMANTIC GAP ANALYSIS
# ================================================================

@dataclass
class SemanticGap:
    topic: str
    gap_type: str        # "semantic_gap" | "low_coverage" | "unanswered_intent"
    similarity_to_keyword: float
    coverage_in_competitors: float  # 0.0 = nobody covers, 1.0 = everyone
    priority: str        # "high" | "medium" | "low"
    suggested_h2: str

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "gap_type": self.gap_type,
            "similarity_to_keyword": round(self.similarity_to_keyword, 3),
            "coverage_in_competitors": round(self.coverage_in_competitors, 3),
            "priority": self.priority,
            "suggested_h2": self.suggested_h2,
        }


def semantic_gap_analysis(
    main_keyword: str,
    paa_questions: List[str],
    related_searches: List[str],
    competitor_texts: List[str],
    max_gaps: int = 15,
) -> Dict:
    """
    Identyfikuje luki treści przez cosine similarity.

    Dla każdego PAA/related search sprawdza:
    - Czy temat jest semantycznie bliski main_keyword
    - Na ile konkurencja pokrywa ten temat

    Tematy wysoko powiązane z keyword + słabo pokryte = HIGH PRIORITY GAP
    """
    print(f"[SEMANTIC] 🔍 Gap analysis: {len(paa_questions)} PAA + {len(related_searches)} related")

    candidates = list(dict.fromkeys(
        [q for q in paa_questions if q and len(q) > 5] +
        [r for r in related_searches if r and len(r) > 5]
    ))

    if not candidates:
        return {"status": "NO_CANDIDATES", "gaps": [], "total_gaps": 0}

    # Embed keyword + all candidates in one batch
    all_texts = [main_keyword] + candidates
    all_embeddings = _embed_texts(all_texts)

    if not all_embeddings or len(all_embeddings) < 2:
        print("[SEMANTIC] ⚠️ Embedding failed, skipping semantic gap analysis")
        return {"status": "EMBEDDING_FAILED", "gaps": [], "total_gaps": 0}

    kw_embedding = all_embeddings[0]
    candidate_embeddings = all_embeddings[1:]

    # Embed competitor texts (sample first 3000 chars each)
    comp_samples = [t[:3000] for t in competitor_texts if t and len(t) > 100]
    comp_embeddings = _embed_texts(comp_samples) if comp_samples else []

    gaps = []

    for i, (candidate, cand_emb) in enumerate(zip(candidates, candidate_embeddings)):
        if not cand_emb:
            continue

        # Similarity to main keyword
        sim_to_kw = _cosine(kw_embedding, cand_emb)

        # Coverage: avg similarity of this topic across competitor texts
        if comp_embeddings:
            comp_sims = [_cosine(cand_emb, ce) for ce in comp_embeddings if ce]
            coverage = sum(s > 0.55 for s in comp_sims) / len(comp_sims) if comp_sims else 0.0
        else:
            coverage = 0.5  # unknown

        # Gap scoring: high relevance to keyword + low coverage = gap
        gap_score = sim_to_kw * (1.0 - coverage)

        if gap_score < 0.15:
            continue  # not relevant or well-covered

        if coverage < 0.25 and sim_to_kw > 0.5:
            priority = "high"
            gap_type = "semantic_gap"
        elif coverage < 0.5 and sim_to_kw > 0.4:
            priority = "medium"
            gap_type = "low_coverage"
        else:
            priority = "low"
            gap_type = "unanswered_intent"

        # Suggested H2
        h2 = candidate.rstrip("?").strip()
        if h2:
            h2 = h2[0].upper() + h2[1:]

        gaps.append(SemanticGap(
            topic=candidate,
            gap_type=gap_type,
            similarity_to_keyword=sim_to_kw,
            coverage_in_competitors=coverage,
            priority=priority,
            suggested_h2=h2,
        ))

    # Sort by gap_score (relevance × lack of coverage)
    gaps.sort(key=lambda g: g.similarity_to_keyword * (1 - g.coverage_in_competitors), reverse=True)
    gaps = gaps[:max_gaps]

    print(f"[SEMANTIC] ✅ Found {len(gaps)} semantic gaps ({sum(1 for g in gaps if g.priority == 'high')} high)")

    return {
        "status": "OK",
        "total_gaps": len(gaps),
        "high": [g.to_dict() for g in gaps if g.priority == "high"],
        "medium": [g.to_dict() for g in gaps if g.priority == "medium"],
        "low": [g.to_dict() for g in gaps if g.priority == "low"],
        "all_gaps": [g.to_dict() for g in gaps],
        "suggested_new_h2s": [g.suggested_h2 for g in gaps if g.priority == "high"][:3],
    }


# ================================================================
# 2. SEMANTIC ENTITY CLUSTERING
# ================================================================

def semantic_entity_clusters(
    entities: List[str],
    main_keyword: str,
    n_clusters: int = 8,
    min_cluster_size: int = 2,
) -> Dict:
    """
    Grupuje encje semantycznie używając Gemini embeddings + k-means-like clustering.

    Zamiast grupować po częstotliwości (jak spaCy), grupuje po znaczeniu.
    Np. "jazda po alkoholu" + "prowadzenie pod wpływem" = ten sam klaster.
    """
    print(f"[SEMANTIC] 🔗 Clustering {len(entities)} entities")

    if len(entities) < 3:
        return {"status": "TOO_FEW_ENTITIES", "clusters": []}

    # Embed all entities + keyword
    all_texts = [main_keyword] + entities
    all_embeddings = _embed_texts(all_texts)

    if not all_embeddings or len(all_embeddings) < 2:
        print("[SEMANTIC] ⚠️ Embedding failed for entity clustering")
        return {"status": "EMBEDDING_FAILED", "clusters": []}

    kw_emb = all_embeddings[0]
    entity_embs = all_embeddings[1:]

    # Score each entity by similarity to keyword
    scored = []
    for entity, emb in zip(entities, entity_embs):
        if not emb:
            continue
        sim = _cosine(kw_emb, emb)
        scored.append({"entity": entity, "embedding": emb, "relevance": sim})

    # Simple greedy clustering: most relevant entity = cluster seed
    scored.sort(key=lambda x: x["relevance"], reverse=True)

    clusters = []
    assigned = set()
    CLUSTER_THRESHOLD = 0.72  # entities this similar go in same cluster

    for seed_item in scored:
        if seed_item["entity"] in assigned:
            continue

        cluster_members = [seed_item["entity"]]
        assigned.add(seed_item["entity"])

        # Find similar entities for this cluster
        for other in scored:
            if other["entity"] in assigned:
                continue
            sim = _cosine(seed_item["embedding"], other["embedding"])
            if sim >= CLUSTER_THRESHOLD:
                cluster_members.append(other["entity"])
                assigned.add(other["entity"])

        if len(cluster_members) >= min_cluster_size or seed_item["relevance"] > 0.7:
            clusters.append({
                "seed": seed_item["entity"],
                "members": cluster_members,
                "relevance_to_keyword": round(seed_item["relevance"], 3),
                "size": len(cluster_members),
            })

        if len(clusters) >= n_clusters:
            break

    # Sort clusters by relevance
    clusters.sort(key=lambda c: c["relevance_to_keyword"], reverse=True)

    print(f"[SEMANTIC] ✅ {len(clusters)} entity clusters found")

    return {
        "status": "OK",
        "clusters": clusters,
        "total_clusters": len(clusters),
        "must_cover": [c["seed"] for c in clusters if c["relevance_to_keyword"] > 0.65],
        "should_cover": [c["seed"] for c in clusters if 0.45 <= c["relevance_to_keyword"] <= 0.65],
    }


# ================================================================
# 3. SEMANTIC H2 RANKING
# ================================================================

def semantic_h2_ranking(
    h2_candidates: List[str],
    main_keyword: str,
    paa_questions: List[str] = None,
    competitor_h2s: List[str] = None,
    top_n: int = 10,
) -> Dict:
    """
    Rankuje H2 kandydatów przez cosine similarity do:
    - main_keyword (intencja tematu)
    - PAA questions (intencja użytkownika)
    - Competitor H2s (pokrycie rynkowe)

    Zastępuje score_h2_candidates() oparty na count-based heurystykach.
    """
    print(f"[SEMANTIC] 📊 H2 ranking: {len(h2_candidates)} candidates")

    if not h2_candidates:
        return {"status": "NO_CANDIDATES", "ranked": []}

    paa_questions = paa_questions or []
    competitor_h2s = competitor_h2s or []

    # Build reference texts
    reference_texts = [main_keyword]
    if paa_questions:
        reference_texts.extend(paa_questions[:5])

    # Embed everything
    all_to_embed = reference_texts + h2_candidates
    all_embeddings = _embed_texts(all_to_embed)

    if not all_embeddings or len(all_embeddings) <= len(reference_texts):
        print("[SEMANTIC] ⚠️ H2 ranking embedding failed")
        return {"status": "EMBEDDING_FAILED", "ranked": []}

    ref_embeddings = all_embeddings[:len(reference_texts)]
    h2_embeddings = all_embeddings[len(reference_texts):]

    # Embed competitor H2s for coverage scoring
    comp_h2_embeddings = _embed_texts(competitor_h2s[:20]) if competitor_h2s else []

    ranked = []
    for h2, h2_emb in zip(h2_candidates, h2_embeddings):
        if not h2_emb:
            continue

        # Score 1: similarity to keyword (weight: 0.5)
        kw_sim = _cosine(ref_embeddings[0], h2_emb)

        # Score 2: max similarity to PAA (weight: 0.3)
        paa_sim = 0.0
        if len(ref_embeddings) > 1:
            paa_sims = [_cosine(paa_emb, h2_emb) for paa_emb in ref_embeddings[1:] if paa_emb]
            paa_sim = max(paa_sims) if paa_sims else 0.0

        # Score 3: competitor frequency signal (weight: 0.2)
        comp_sim = 0.0
        if comp_h2_embeddings:
            comp_sims = [_cosine(ce, h2_emb) for ce in comp_h2_embeddings if ce]
            high_sim_count = sum(1 for s in comp_sims if s > 0.75)
            comp_sim = min(high_sim_count / max(len(comp_h2_embeddings), 1), 1.0)

        # Weighted final score
        final_score = (kw_sim * 0.5) + (paa_sim * 0.3) + (comp_sim * 0.2)

        ranked.append({
            "text": h2,
            "score": round(final_score, 4),
            "kw_similarity": round(kw_sim, 3),
            "paa_similarity": round(paa_sim, 3),
            "competitor_coverage": round(comp_sim, 3),
            "priority": "must_have" if final_score >= 0.65 else ("high" if final_score >= 0.50 else "optional"),
            "reason": f"kw={kw_sim:.2f} paa={paa_sim:.2f} comp={comp_sim:.2f}",
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    ranked = ranked[:top_n]

    must_have = [r for r in ranked if r["priority"] == "must_have"]
    high = [r for r in ranked if r["priority"] == "high"]
    optional = [r for r in ranked if r["priority"] == "optional"]

    print(f"[SEMANTIC] ✅ H2 ranked: {len(must_have)} must_have, {len(high)} high, {len(optional)} optional")

    return {
        "status": "OK",
        "must_have": must_have,
        "high_priority": high,
        "optional": optional,
        "all_candidates": ranked,
        "stats": {
            "total": len(ranked),
            "must_have_count": len(must_have),
            "avg_score": round(sum(r["score"] for r in ranked) / len(ranked), 3) if ranked else 0,
        },
    }


# ================================================================
# 4. MULTIMODAL EMBED (images, audio)
# ================================================================

def embed_image(image_path: str = None, image_bytes: bytes = None, mime_type: str = "image/jpeg") -> List[float]:
    """
    Embed an image using Gemini Embedding 2 multimodal.
    Returns embedding vector or empty list on failure.
    """
    client = _get_client()
    if not client:
        return []

    try:
        from google.genai import types as gtypes

        if image_bytes is None and image_path:
            with open(image_path, "rb") as f:
                image_bytes = f.read()

        if not image_bytes:
            return []

        result = client.models.embed_content(
            model=_MODEL,
            contents=[
                gtypes.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            ],
            config=gtypes.EmbedContentConfig(output_dimensionality=_DIMS),
        )
        return list(result.embeddings[0].values) if result.embeddings else []
    except Exception as e:
        print(f"[SEMANTIC] ❌ Image embedding error: {e}")
        return []


def compare_text_to_image(text: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> float:
    """
    Compare text to image in shared embedding space.
    Returns cosine similarity (0.0 - 1.0).
    Useful for: checking if competitor infographic matches topic.
    """
    client = _get_client()
    if not client:
        return 0.0

    try:
        from google.genai import types as gtypes

        result = client.models.embed_content(
            model=_MODEL,
            contents=[
                text,
                gtypes.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=gtypes.EmbedContentConfig(output_dimensionality=_DIMS),
        )
        if len(result.embeddings) < 2:
            return 0.0

        text_emb = list(result.embeddings[0].values)
        img_emb = list(result.embeddings[1].values)
        return round(_cosine(text_emb, img_emb), 4)
    except Exception as e:
        print(f"[SEMANTIC] ❌ Text-image compare error: {e}")
        return 0.0


# ================================================================
# AVAILABILITY CHECK
# ================================================================

def is_available() -> bool:
    """Check if Gemini embeddings are available."""
    return _get_client() is not None


__all__ = [
    "semantic_gap_analysis",
    "semantic_entity_clusters",
    "semantic_h2_ranking",
    "embed_image",
    "compare_text_to_image",
    "is_available",
]
