"""
Compliance Report — optional module.
Checks keyword frequency compliance against target ranges.
"""
from src.s1.generate_compliance_report import generate_compliance_report


def run_compliance(text: str, s1_data: dict = None) -> dict:
    """
    Run keyword compliance report.
    Checks if all keywords are used within target frequency ranges.
    """
    ngrams = (s1_data or {}).get("ngrams", [])
    keyword_state = {}
    for ng in ngrams:
        name = ng.get("ngram", "")
        if name:
            keyword_state[name] = {
                "min": ng.get("freq_min", 0),
                "max": max(ng.get("freq_max", 5), 1),
            }

    if not keyword_state:
        return {"error": "No keywords to check", "compliance": {}}

    return generate_compliance_report(text, keyword_state)
