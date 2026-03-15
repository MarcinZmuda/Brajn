"""
LanguageTool Polish Grammar Checker — Public API wrapper.

Checks Polish grammar, spelling, and style using LanguageTool's
free public HTTP API. No Java installation required.

Rate limit: 20 requests/minute (1 article = 1 request).
Cost: $0.00

Returns structured list of issues with positions, categories,
and suggested replacements.
"""

import re
import requests
from typing import Dict, List, Tuple

_LT_API_URL = "https://api.languagetool.org/v2/check"

# Rules to SKIP — false positives common in SEO/legal Polish text
_SKIP_RULES = {
    "WHITESPACE_RULE",          # spacing issues in markdown
    "UPPERCASE_SENTENCE_START", # headings don't start with uppercase always
    "COMMA_PARENTHESIS_WHITESPACE",
    "DOUBLE_PUNCTUATION",       # markdown artifacts
    "CONSECUTIVE_SPACES",       # markdown rendering
}

# Categories to prioritize
_PRIORITY_CATEGORIES = {
    "GRAMMAR": "high",
    "TYPOS": "medium",
    "STYLE": "low",
    "PUNCTUATION": "medium",
    "CASING": "low",
}


def check_polish_grammar(text: str, max_issues: int = 30) -> Dict:
    """
    Check Polish grammar using LanguageTool Public API.

    Args:
        text: Article text (markdown OK — will be stripped)
        max_issues: Max number of issues to return

    Returns:
        Dict with issues list and stats
    """
    # Strip markdown formatting for cleaner analysis
    clean = _strip_markdown(text)

    if not clean or len(clean) < 50:
        return {"issues": [], "stats": {"total": 0}, "skipped": True}

    # Truncate to API limit (~20k chars for free tier)
    if len(clean) > 18000:
        clean = clean[:18000]

    try:
        response = requests.post(
            _LT_API_URL,
            data={
                "text": clean,
                "language": "pl-PL",
                "enabledOnly": "false",
            },
            timeout=30,
            headers={"User-Agent": "BRAJN-SEO/2.0"},
        )

        if response.status_code != 200:
            print(f"[LANGUAGETOOL] API error: HTTP {response.status_code}")
            return {"issues": [], "stats": {"total": 0}, "error": f"HTTP {response.status_code}"}

        data = response.json()
        matches = data.get("matches", [])

    except requests.exceptions.Timeout:
        print("[LANGUAGETOOL] API timeout")
        return {"issues": [], "stats": {"total": 0}, "error": "timeout"}
    except Exception as e:
        print(f"[LANGUAGETOOL] Error: {e}")
        return {"issues": [], "stats": {"total": 0}, "error": str(e)}

    # Process matches
    issues = []
    category_counts = {}

    for match in matches:
        rule_id = match.get("rule", {}).get("id", "")

        # Skip noisy rules
        if rule_id in _SKIP_RULES:
            continue

        category = match.get("rule", {}).get("category", {}).get("id", "OTHER")
        severity = _PRIORITY_CATEGORIES.get(category, "low")

        # Count categories
        category_counts[category] = category_counts.get(category, 0) + 1

        context = match.get("context", {})
        replacements = [r.get("value", "") for r in match.get("replacements", [])[:3]]

        issue = {
            "rule_id": rule_id,
            "message": match.get("message", ""),
            "short_message": match.get("shortMessage", ""),
            "category": category,
            "severity": severity,
            "offset": match.get("offset", 0),
            "length": match.get("errorLength", 0),
            "context_text": context.get("text", ""),
            "context_offset": context.get("offset", 0),
            "replacements": replacements,
            "sentence": match.get("sentence", ""),
        }
        issues.append(issue)

    # Sort by severity (high first), then by offset
    severity_order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda x: (severity_order.get(x["severity"], 3), x["offset"]))

    # Limit
    issues = issues[:max_issues]

    stats = {
        "total": len(issues),
        "grammar": category_counts.get("GRAMMAR", 0),
        "typos": category_counts.get("TYPOS", 0),
        "style": category_counts.get("STYLE", 0),
        "punctuation": category_counts.get("PUNCTUATION", 0),
        "other": sum(v for k, v in category_counts.items()
                     if k not in ("GRAMMAR", "TYPOS", "STYLE", "PUNCTUATION")),
    }

    print(f"[LANGUAGETOOL] Found {stats['total']} issues: "
          f"grammar={stats['grammar']}, typos={stats['typos']}, "
          f"style={stats['style']}, punctuation={stats['punctuation']}")

    return {
        "issues": issues,
        "stats": stats,
        "skipped": False,
    }


def auto_fix_grammar(text: str, lt_result: Dict) -> Tuple[str, int]:
    """
    Auto-apply safe LanguageTool fixes (typos and clear grammar errors).
    Returns (fixed_text, num_fixes_applied).

    Only applies fixes where:
    - There is exactly 1 replacement suggestion
    - The category is GRAMMAR or TYPOS (not STYLE)
    - The replacement is similar length (not a major rewrite)
    """
    issues = lt_result.get("issues", [])
    if not issues:
        return text, 0

    # Apply fixes in reverse offset order to preserve positions
    safe_fixes = []
    for issue in issues:
        if issue["category"] not in ("GRAMMAR", "TYPOS"):
            continue
        if len(issue["replacements"]) != 1:
            continue
        replacement = issue["replacements"][0]
        # Safety: replacement should be similar length
        orig_len = issue["length"]
        if abs(len(replacement) - orig_len) > orig_len * 2:
            continue
        safe_fixes.append(issue)

    # Sort by offset descending (apply from end to preserve positions)
    safe_fixes.sort(key=lambda x: x["offset"], reverse=True)

    fixed = text
    applied = 0
    for fix in safe_fixes:
        offset = fix["offset"]
        length = fix["length"]
        replacement = fix["replacements"][0]

        # Verify the text at offset matches what we expect
        if offset + length <= len(fixed):
            original_fragment = fixed[offset:offset + length]
            # Only apply if fragments roughly match context
            if original_fragment.lower().strip() in fix.get("sentence", "").lower():
                fixed = fixed[:offset] + replacement + fixed[offset + length:]
                applied += 1

    if applied > 0:
        print(f"[LANGUAGETOOL] Auto-fixed {applied} issues")

    return fixed, applied


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting for cleaner LT analysis."""
    # Remove headings markers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove bold/italic
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    # Remove links
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove horizontal rules
    text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)
    # Collapse multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
