"""
AI Detection Check — optional module.
Ported from master-seo-api/ai_detection_metrics.py (simplified).
"""
import re
from src.article_pipeline.prompts import FORBIDDEN_PHRASES


def check_ai_detection(text: str) -> dict:
    """
    Check text for AI-generated patterns.
    Returns score and list of issues.
    """
    issues = []
    score = 100

    # 1. Forbidden phrases
    text_lower = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        count = text_lower.count(phrase.lower())
        if count > 0:
            issues.append({
                "type": "FORBIDDEN_PHRASE",
                "severity": "HIGH",
                "phrase": phrase,
                "count": count,
            })
            score -= count * 5

    # 2. Repetitive sentence starts
    sentences = re.split(r"[.!?]+\s+", text)
    starts = [s.split()[0].lower() if s.split() else "" for s in sentences if s.strip()]
    from collections import Counter
    start_counts = Counter(starts)
    for start, count in start_counts.items():
        if count > 3 and start not in ("", "to", "w", "na", "z", "i", "a"):
            issues.append({
                "type": "REPETITIVE_START",
                "severity": "MEDIUM",
                "word": start,
                "count": count,
            })
            score -= 2

    # 3. Paragraph uniformity (same sentence count)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    sent_counts = []
    for p in paragraphs:
        sents = [s for s in re.split(r"[.!?]+\s+", p) if s.strip()]
        sent_counts.append(len(sents))

    for i in range(len(sent_counts) - 3):
        if len(set(sent_counts[i:i+4])) == 1:
            issues.append({
                "type": "UNIFORM_PARAGRAPHS",
                "severity": "MEDIUM",
                "location": f"paragraphs {i+1}-{i+4}",
                "count": sent_counts[i],
            })
            score -= 3
            break

    # 4. List overuse
    list_count = len(re.findall(r"(?:^|\n)\s*[-•*]\s+", text))
    if list_count > 12:
        issues.append({
            "type": "LIST_OVERUSE",
            "severity": "MEDIUM",
            "count": list_count,
        })
        score -= 5

    # 5. Bold in prose
    bolds = re.findall(r"\*\*[^*]+\*\*", text)
    if bolds and len(bolds) > 3:
        issues.append({
            "type": "EXCESSIVE_BOLD",
            "severity": "LOW",
            "count": len(bolds),
        })
        score -= 3

    score = max(0, min(100, score))

    return {
        "ai_detection_score": score,
        "humanness_label": "HIGH" if score >= 80 else "MEDIUM" if score >= 60 else "LOW",
        "issues": issues,
        "total_issues": len(issues),
    }
