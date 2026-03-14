"""
Tests for the proofreader instruction detection and hallucination filtering.
Verifies that editorial instructions in suggestions are NOT inserted into article text.
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.article_pipeline.editorial_proofreader import _is_editorial_instruction


def _apply_hallucination_fix(result_text: str, hallucinations: list) -> dict:
    """
    Mirrors the actual code from editorial_proofreader.py section 2b.
    Uses the real _is_editorial_instruction function.
    """
    applied = []
    flagged = []

    for hall in hallucinations:
        original = hall.get("text", "")
        suggestion = hall.get("suggestion", "")

        if not original:
            continue

        if (suggestion
                and not _is_editorial_instruction(suggestion)
                and result_text.count(original) == 1):
            result_text = result_text.replace(original, suggestion, 1)
            applied.append({
                "original": original,
                "replacement": suggestion,
            })
        else:
            flagged.append({
                "type": "hallucination",
                "text": original[:80],
                "action": suggestion if suggestion else "Usun lub zastap zweryfikowanym faktem",
            })

    return {"text": result_text, "applied": applied, "flagged": flagged}


# ── Tests for _is_editorial_instruction ──

class TestIsEditorialInstruction:
    """Direct tests for the instruction detection function."""

    def test_empty_is_instruction(self):
        assert _is_editorial_instruction("") is True

    def test_short_is_instruction(self):
        assert _is_editorial_instruction("abc") is True
        assert _is_editorial_instruction("12345") is True

    def test_usun_is_instruction(self):
        assert _is_editorial_instruction("USUN") is True
        assert _is_editorial_instruction("usun") is True
        assert _is_editorial_instruction("Usuń ten fragment") is True
        assert _is_editorial_instruction("usun lub zastap innym") is True

    def test_zastap_is_instruction(self):
        assert _is_editorial_instruction("Zastąp ogólnym stwierdzeniem") is True
        assert _is_editorial_instruction("zastap: 'nowy tekst'") is True

    def test_conditional_is_instruction(self):
        assert _is_editorial_instruction(
            "Jeśli dane są potwierdzone, pozostaw; w przeciwnym razie usuń"
        ) is True

    def test_sprawdz_is_instruction(self):
        assert _is_editorial_instruction("Sprawdź czy dane są aktualne") is True

    def test_popraw_is_instruction(self):
        assert _is_editorial_instruction("Popraw na bardziej ogólne sformułowanie") is True

    def test_przeredaguj_is_instruction(self):
        assert _is_editorial_instruction("__PRZEREDAGUJ__") is True
        assert _is_editorial_instruction("__USUN__") is True

    def test_colon_quote_pattern(self):
        """Instructions like "Usuń lub zastąp: 'replacement text'" should be caught."""
        assert _is_editorial_instruction(
            "USUN lub zastąp: 'Szkolenie trwa kilkanaście godzin'"
        ) is True
        assert _is_editorial_instruction(
            'Zmień na: "inna wersja tekstu"'
        ) is True

    def test_real_bug_case(self):
        """The actual bug case from production."""
        assert _is_editorial_instruction(
            "Jeśli dane są potwierdzone przez organizatora, pozostaw; "
            "w przeciwnym razie usuń lub zastąp: 'Szkolenie trwa kilkanaście godzin dydaktycznych'"
        ) is True

    def test_valid_replacement_not_instruction(self):
        """Clean replacement text should NOT be flagged."""
        assert _is_editorial_instruction(
            "Szkolenie trwa kilkanaście godzin dydaktycznych"
        ) is False
        assert _is_editorial_instruction(
            "Szkoła barberska zapewnia solidne wykształcenie."
        ) is False
        assert _is_editorial_instruction(
            "Producent oferuje swoje produkty na rynku polskim."
        ) is False

    def test_long_instruction_with_usun(self):
        """Very long text containing 'usuń' should be caught."""
        long_text = "x" * 201 + " usuń ten fragment"
        assert _is_editorial_instruction(long_text) is True


# ── Integration tests: hallucination fix flow ──

class TestHallucinationFixFlow:
    """Tests for the full hallucination fix flow with instruction detection."""

    ARTICLE = "To inwestycja w przyszłość, która się zwróci. Szkoła XYZ zapewnia najlepsze wykształcenie."

    def test_exact_usun_blocked(self):
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "USUN",
            "reason": "Hallucination"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1
        assert "Szkoła XYZ" in result["text"]

    def test_instruction_as_suggestion_blocked(self):
        """THE CRITICAL BUG: LLM returns instruction instead of replacement text."""
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "Jeśli dane są potwierdzone przez organizatora, pozostaw; w przeciwnym razie usuń lub zastąp: 'Szkoła barberska zapewnia solidne wykształcenie.'",
            "reason": "Company name - possible hallucination"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1
        # Article must NOT contain the instruction text
        assert "Jeśli dane" not in result["text"]
        assert "w przeciwnym razie" not in result["text"]
        # Original must be preserved
        assert "Szkoła XYZ" in result["text"]

    def test_usun_lub_zastap_blocked(self):
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "USUN lub zastąp: 'To inwestycja w rozwój zawodowy'",
            "reason": "Hallucination - company name"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1
        assert "USUN lub" not in result["text"]
        assert "Szkoła XYZ" in result["text"]

    def test_usun_variations(self):
        variants = [
            "USUN ten fragment",
            "Usun i zastap ogolnym stwierdzeniem",
            "USUN - halucynacja",
            "USUN lub przeredaguj",
            "usun calkowicie",
            "Zastąp ogólnym sformułowaniem o szkoleniach",
            "Sprawdź dane i popraw",
            "Popraw na: 'Szkolenie trwa kilka godzin'",
        ]
        for suggestion in variants:
            result = _apply_hallucination_fix(self.ARTICLE, [{
                "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
                "suggestion": suggestion,
                "reason": "Hallucination"
            }])
            assert len(result["applied"]) == 0, f"Should block: '{suggestion}'"
            assert len(result["flagged"]) == 1, f"Should flag: '{suggestion}'"

    def test_valid_suggestion_applied(self):
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "Szkoła barberska zapewnia solidne wykształcenie.",
            "reason": "Replace company name"
        }])
        assert len(result["applied"]) == 1
        assert len(result["flagged"]) == 0
        assert "Szkoła barberska" in result["text"]

    def test_empty_suggestion_flagged(self):
        result = _apply_hallucination_fix(self.ARTICLE, [{
            "text": "Szkoła XYZ zapewnia najlepsze wykształcenie.",
            "suggestion": "",
            "reason": "Hallucination"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1

    def test_duplicate_original_flagged(self):
        text = "To To inwestycja. To zwrot."
        result = _apply_hallucination_fix(text, [{
            "text": "To",
            "suggestion": "Ta wielka inwestycja",
            "reason": "Test"
        }])
        assert len(result["applied"]) == 0
        assert len(result["flagged"]) == 1

    def test_multiple_hallucinations_mixed(self):
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
        assert len(result["applied"]) == 1
        assert len(result["flagged"]) == 1
        assert "Producent oferuje" in result["text"]
        assert "USUN lub" not in result["text"]
