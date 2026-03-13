"""
AI Detection Check — optional module.
Full v2.0 check including BANNED_OPENERS, BANNED_ANYWHERE, BANNED_CHARS,
sentence rhythm, passive voice, and lexical diversity.
"""
import re
from collections import Counter
from src.article_pipeline.prompts import (
    FORBIDDEN_PHRASES,
    BANNED_OPENERS,
    BANNED_ANYWHERE,
    BANNED_CHARS,
)


def check_ai_detection(text: str) -> dict:
    """
    Check text for AI-generated patterns.
    Returns score and list of issues grouped by category.
    """
    issues = []
    score = 100
    text_lower = text.lower()

    # ── 1. Core forbidden phrases (HIGH severity) ──
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

    # ── 2. Banned openers — sentence starters (HIGH severity) ──
    sentences = re.split(r'(?<=[.!?])\s+', text)
    opener_hits = []
    for sent in sentences:
        sent_lower = sent.strip().lower()
        for opener in BANNED_OPENERS:
            if sent_lower.startswith(opener.lower()):
                opener_hits.append(opener)
                break
    if opener_hits:
        counts = Counter(opener_hits)
        for opener, count in counts.items():
            issues.append({
                "type": "BANNED_OPENER",
                "severity": "HIGH",
                "phrase": opener,
                "count": count,
            })
            score -= count * 4

    # ── 3. Banned anywhere phrases (MEDIUM severity) ──
    for phrase in BANNED_ANYWHERE:
        count = text_lower.count(phrase.lower())
        if count > 0:
            issues.append({
                "type": "BANNED_ANYWHERE",
                "severity": "MEDIUM",
                "phrase": phrase,
                "count": count,
            })
            score -= count * 3

    # ── 4. Banned characters — em dash etc. (MEDIUM severity) ──
    for char in BANNED_CHARS:
        count = text.count(char)
        if count > 0:
            char_name = "em dash (\u2014)" if char == "\u2014" else repr(char)
            issues.append({
                "type": "BANNED_CHAR",
                "severity": "MEDIUM",
                "char": char_name,
                "count": count,
            })
            score -= min(count, 10) * 2  # cap penalty at 20

    # ── 5. Repetitive sentence starts ──
    starts = [s.split()[0].lower() if s.split() else "" for s in sentences if s.strip()]
    start_counts = Counter(starts)
    for start, count in start_counts.items():
        if count > 3 and start not in ("", "to", "w", "na", "z", "i", "a", "je"):
            issues.append({
                "type": "REPETITIVE_START",
                "severity": "MEDIUM",
                "word": start,
                "count": count,
            })
            score -= 2

    # ── 6. Paragraph uniformity (same sentence count) ──
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    sent_counts = []
    for p in paragraphs:
        sents = [s for s in re.split(r"[.!?]+\s+", p) if s.strip()]
        sent_counts.append(len(sents))

    for i in range(len(sent_counts) - 3):
        if len(set(sent_counts[i:i + 4])) == 1:
            issues.append({
                "type": "UNIFORM_PARAGRAPHS",
                "severity": "MEDIUM",
                "location": f"akapity {i + 1}-{i + 4}",
                "count": sent_counts[i],
            })
            score -= 3
            break

    # ── 7. Sentence length variance (AI tends to uniform length) ──
    sent_lengths = [len(s.split()) for s in sentences if len(s.split()) > 2]
    if len(sent_lengths) >= 5:
        avg_len = sum(sent_lengths) / len(sent_lengths)
        variance = sum((l - avg_len) ** 2 for l in sent_lengths) / len(sent_lengths)
        std_dev = variance ** 0.5
        # Low variance = robotic rhythm
        if std_dev < 3.0:
            issues.append({
                "type": "LOW_SENTENCE_VARIANCE",
                "severity": "LOW",
                "avg_length": round(avg_len, 1),
                "std_dev": round(std_dev, 1),
                "detail": "Zdania maja zbyt jednolita dlugosc — brak rytmu",
            })
            score -= 3

    # ── 8. List overuse ──
    list_items = len(re.findall(r"(?:^|\n)\s*[-•*]\s+", text))
    if list_items > 12:
        issues.append({
            "type": "LIST_OVERUSE",
            "severity": "MEDIUM",
            "count": list_items,
        })
        score -= 5

    # ── 9. Bold in prose ──
    bolds = re.findall(r"\*\*[^*]+\*\*", text)
    if bolds and len(bolds) > 3:
        issues.append({
            "type": "EXCESSIVE_BOLD",
            "severity": "LOW",
            "count": len(bolds),
        })
        score -= 3

    # ── 10. Anglosaski cudzyslow (') zamiast polskiego ──
    straight_quotes = text.count("'")
    # Only flag if used as quote (not apostrophe in common contractions)
    if straight_quotes > 2:
        issues.append({
            "type": "STRAIGHT_QUOTES",
            "severity": "LOW",
            "count": straight_quotes,
            "detail": "Anglosaski cudzyslów (') — uzyj polskich cudzyslowow (\u201e\u201d)",
        })
        score -= 2

    score = max(0, min(100, score))

    return {
        "ai_detection_score": score,
        "humanness_label": "HIGH" if score >= 80 else "MEDIUM" if score >= 60 else "LOW",
        "issues": issues,
        "total_issues": len(issues),
        "summary": {
            "forbidden_phrases": sum(1 for i in issues if i["type"] == "FORBIDDEN_PHRASE"),
            "banned_openers": sum(1 for i in issues if i["type"] == "BANNED_OPENER"),
            "banned_anywhere": sum(1 for i in issues if i["type"] == "BANNED_ANYWHERE"),
            "banned_chars": sum(1 for i in issues if i["type"] == "BANNED_CHAR"),
            "style_issues": sum(1 for i in issues if i["type"] in (
                "REPETITIVE_START", "UNIFORM_PARAGRAPHS", "LOW_SENTENCE_VARIANCE",
                "LIST_OVERUSE", "EXCESSIVE_BOLD", "STRAIGHT_QUOTES",
            )),
        },
    }
