"""
Tests for the proofreader USUN condition fix.
Verifies that hallucination suggestions containing "USUN" (in any form)
are NOT applied as text replacements.
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _apply_hallucination_fix(result_text: str, hallucinations: list) -> dict:
    """
    Extracted logic from editorial_proofreader.py _apply_corrections()
    section 2b — hallucination handling. Mirrors the actual code.
    """
    applied = []
    flagged = []

    for hall in hallucinations:
        original = hall.get("text", "")
        suggestion = hall.get("suggestion", "")

        if not original:
            continue

        if (suggestion
                and "USUN" not in suggestion.upper()
                and "__PRZEREDAGUJ__" not in suggestion.upper()
                and len(suggestion) > 5
                and result_text.count(original) == 1):
            result_text = result_text.replace(original, suggestion, 1)
            applied.append({
                "original": original,
                "replacement": suggestion,
            })
        else:
            flagged.append({
                "type": "hallucination",
                "text": original,
                "action": suggestion if suggestion else "Usun lub zastap zweryfikowanym faktem",
            })

    return {"text": result_text, "applied": applied, "flagged": flagged}


class TestUsunCondition:
    """Tests for the USUN hallucination filter."""

    ARTICLE = "To inwestycja w przyszłość, która się zwróci. Szkoła XYZ zapewnia najlepsze wykształcenie."

    def test_exact_usun_blocked(self):
        """Exact 'USUN' suggestion should be blocked."""
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "USUN",
            "reason": "Hallucination"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1
        assert "Szkoła XYZ" in result["text"]  # Original preserved

    def test_usun_lowercase_blocked(self):
        """Lowercase 'usun' should also be blocked."""
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "usun",
            "reason": "Hallucination"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1

    def test_usun_lub_zastap_blocked(self):
        """BUG FIX: 'USUN lub zastąp: ...' should be blocked (was passing before)."""
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "USUN lub zastąp: 'To inwestycja w rozwój zawodowy'",
            "reason": "Hallucination - company name"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1
        # Original text should NOT contain "USUN lub zastąp"
        assert "USUN lub" not in result["text"]
        assert "Szkoła XYZ" in result["text"]  # Original preserved

    def test_usun_or_replace_variations(self):
        """Various 'USUN' variations in suggestion should all be blocked."""
        variants = [
            "USUN ten fragment",
            "Usun i zastap ogolnym stwierdzeniem",
            "USUN - halucynacja",
            "USUN lub przeredaguj",
            "usun calkowicie",
        ]
        for suggestion in variants:
            result = _apply_hallucination_fix(self.ARTICLE, [{
                "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
                "suggestion": suggestion,
                "reason": "Hallucination"
            }])
            assert len(result["applied"]) == 0, f"Should block suggestion: '{suggestion}'"
            assert len(result["flagged"]) == 1, f"Should flag suggestion: '{suggestion}'"

    def test_przeredaguj_blocked(self):
        """__PRZEREDAGUJ__ suggestion should be blocked."""
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "__PRZEREDAGUJ__",
            "reason": "AI artifact"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1

    def test_short_suggestion_blocked(self):
        """Suggestions <= 5 chars should be blocked (too short to be valid)."""
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "abc",
            "reason": "Too short"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1

    def test_valid_suggestion_applied(self):
        """A proper replacement suggestion should be applied."""
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "Szkoła barberska zapewnia solidne wykształcenie.",
            "reason": "Replace company name"
        }])
        assert len(result["applied"]) == 1
        assert len(result["flagged"]) == 0
        assert "Szkoła barberska" in result["text"]
        assert "Szkoła XYZ" not in result["text"]

    def test_empty_suggestion_flagged(self):
        """Empty suggestion should be flagged, not applied."""
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "",
            "reason": "Hallucination"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1

    def test_duplicate_original_flagged(self):
        """When original appears more than once, should be flagged."""
        text = "To To inwestycja. To zwrot."
        result = _apply_hallucination_fix(text, [{
            "text": "To",
            "suggestion": "Ta wielka inwestycja",
            "reason": "Test"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1

    def test_multiple_hallucinations_mixed(self):
        """Mix of valid and invalid suggestions processed correctly."""
        text = "Firma ABC produkuje. Ekspert Jan Kowalski twierdzi że jest dobrze."
        result = _apply_hallucination_fix(text, [
            {
                "text": "Firma ABC produkuje.",
                "suggestion": "Producent oferuje swoje produkty.",
                "reason": "Company name"
            },
            {
                "text": "Ekspert Jan Kowalski twierdzi że jest dobrze.",
                "suggestion": "USUN lub zastąp: 'Eksperci twierdzą...'",
                "reason": "Person name hallucination"
            },
        ])
        assert len(result["applied"]) == 1  # First one applied
        assert len(result["flagged"]) == 1  # Second one blocked
        assert "Producent oferuje" in result["text"]
        assert "USUN lub" not in result["text"]
