"""
N-gram Patcher — post-write check and optional fix.

After the writer produces the article, this module:
1. Counts n-gram occurrences (regex, zero LLM)
2. Identifies missing important phrases
3. Optionally calls Haiku to patch them in

Cost: $0.00 (check only) or ~$0.002 (with Haiku patch)
"""

import re
import json
from typing import Dict, List, Tuple


def check_ngram_coverage(article_text: str, ngrams: list) -> dict:
    """
    Check how many n-grams from S1 appear in the article.
    Returns coverage report.
    """
    article_lower = article_text.lower()
    missing = []
    present = []

    for ng in ngrams:
        if not isinstance(ng, dict):
            continue
        term = (ng.get("ngram") or ng.get("text") or "").strip()
        if not term or len(term) < 4:
            continue

        weight = float(ng.get("weight", 0))
        freq_min = int(ng.get("freq_min", 1))
        count = len(re.findall(re.escape(term.lower()), article_lower))

        entry = {"term": term, "count": count, "weight": weight, "freq_min": freq_min}

        if count == 0 and freq_min >= 1:
            missing.append(entry)
        else:
            present.append(entry)

    # Sort missing by weight (most important first)
    missing.sort(key=lambda x: x["weight"], reverse=True)

    total = len(missing) + len(present)
    return {
        "missing": missing,
        "present": present,
        "total": total,
        "coverage_pct": round(len(present) / max(total, 1) * 100),
        "important_missing": [m for m in missing if m["weight"] >= 0.3],
    }


def patch_missing_ngrams(
    article_text: str,
    missing_phrases: list,
    max_patches: int = 5,
) -> Tuple[str, list]:
    """
    Use Haiku to patch missing important phrases into article.
    Returns (patched_text, list_of_patches).
    """
    if not missing_phrases:
        return article_text, []

    # Only patch top N most important
    to_patch = [m["term"] for m in missing_phrases[:max_patches]]

    from src.article_pipeline.prompts import NGRAM_PATCHER_SYSTEM, NGRAM_PATCHER_USER
    from src.common.llm import claude_call

    prompt = NGRAM_PATCHER_USER.format(
        missing_phrases="\n".join(f"- {p}" for p in to_patch),
        article_text=article_text,
    )

    try:
        response, usage = claude_call(
            system_prompt=NGRAM_PATCHER_SYSTEM,
            user_prompt=prompt,
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            temperature=0.3,
        )

        # Parse patches
        parsed = _parse_json(response)
        if not parsed or "patches" not in parsed:
            return article_text, []

        patched = article_text
        applied = []

        for patch in parsed["patches"]:
            original = patch.get("original_sentence", "")
            replacement = patch.get("patched_sentence", "")
            if original and replacement and patched.count(original) == 1:
                patched = patched.replace(original, replacement, 1)
                applied.append(patch)

        return patched, applied

    except Exception as e:
        print(f"[PATCHER] Error: {e}")
        return article_text, []


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last >= 0:
        try:
            return json.loads(text[first : last + 1])
        except Exception:
            return None
    return None
