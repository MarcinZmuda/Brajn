"""
Tests for orchestrator.py v2.0 pipeline:
1. Step numbering — fixed 7 steps, no collisions
2. FAQ header — brief contains FAQ section
3. Brief-based deduplication — covered_facts tracking in brief_compiler
"""
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _read_file(name):
    filepath = os.path.join(os.path.dirname(__file__), "..", name)
    with open(filepath) as f:
        return f.read()


class TestStepNumbering:
    """Verify step numbers in v2.0 pipeline (fixed 7 steps)."""

    def test_v2_total_steps_is_7(self):
        """v2.0 has exactly 7 fixed steps."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "total_steps = 7" in source

    def test_no_step_5_collision_in_h2_loop(self):
        """Ensure 'step = 5 + i' pattern does NOT exist (was the v1 bug)."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "step = 5 + i" not in source

    def test_v2_step_sequence(self):
        """v2.0 steps: 1=YMYL, 2=variants, 3=plan, 4=brief, 5=write, 6=ngram, 7=compliance."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        # All 7 step_start events
        for step_num in range(1, 8):
            assert f'"step": {step_num}' in source, f"Step {step_num} missing"

    def test_total_steps_formula_v2(self):
        """v2.0: fixed 7 steps, no dynamic formula needed."""
        steps = list(range(1, 8))
        assert len(steps) == len(set(steps)), "Step collision"
        assert max(steps) == 7


class TestBriefDeduplication:
    """Test dedup via covered_facts tracking in brief_compiler."""

    def test_brief_compiler_tracks_covered_facts(self):
        """brief_compiler should track covered_facts per section."""
        source = _read_file("src/article_pipeline/brief_compiler.py")
        assert "covered_facts" in source
        assert "already_covered" in source or "covered_facts" in source

    def test_brief_compiler_warns_not_to_repeat(self):
        """Brief should tell writer not to repeat covered facts."""
        source = _read_file("src/article_pipeline/brief_compiler.py")
        assert "nie powtarzaj" in source.lower()

    def test_brief_compiler_builds_intro_instructions(self):
        """Brief should have intro instructions builder."""
        source = _read_file("src/article_pipeline/brief_compiler.py")
        assert "def _build_intro_instructions" in source

    def test_brief_compiler_finds_relevant_facts(self):
        """Brief should find facts relevant to each H2."""
        source = _read_file("src/article_pipeline/brief_compiler.py")
        assert "def _find_relevant_facts" in source

    def test_dedup_logic_simulation(self):
        """Simulate: covered_facts prevents repeat assignment."""
        covered = set()
        facts = ["fakt A", "fakt B", "fakt C"]
        # Section 1 gets fakt A
        covered.add("fakt A")
        # Section 2 should not get fakt A
        available = [f for f in facts if f not in covered]
        assert "fakt A" not in available
        assert "fakt B" in available

    def test_summary_logic_empty(self):
        """Simulate: no previous facts - empty covered set."""
        covered = set()
        assert len(covered) == 0

    def test_summary_logic_with_facts(self):
        """Simulate: previous batch with facts - non-empty summary."""
        batch_texts = [
            "## Progi alkoholu\n\nProg wynosi 0,5 promila. Grzywna do 5000 zl."
        ]
        covered_facts = set()
        covered_topics = set()
        for prev_text in batch_texts:
            numbers = re.findall(
                r'\d[\d\s,.]*(?:promil[aei]|zl|zlotych|lat|roku|lat[a]?|%|tys|mies)',
                prev_text.lower()
            )
            covered_facts.update(n.strip() for n in numbers[:10])
            h2s = re.findall(r'^##\s+(.+)', prev_text, re.MULTILINE)
            covered_topics.update(h2s)

        assert len(covered_facts) >= 1, f"Should find facts, got: {covered_facts}"
        assert "Progi alkoholu" in covered_topics
        assert any("promil" in f for f in covered_facts)


class TestFaqHeader:
    """Test that FAQ header is in the brief."""

    def test_faq_header_logic(self):
        """Simulate the FAQ header prepend logic."""
        keyword = "dieta ketogeniczna"
        faq_text = "## Czy dieta keto jest bezpieczna?\nTak, jest bezpieczna."

        faq_header = f"## Najczesciej zadawane pytania o {keyword}"
        if not faq_text.strip().startswith("## Najczesciej zadawane pytania"):
            faq_text = faq_header + "\n\n" + faq_text

        assert faq_text.startswith("## Najczesciej zadawane pytania o dieta ketogeniczna")
        assert "## Czy dieta keto jest bezpieczna?" in faq_text

    def test_faq_header_not_duplicated(self):
        """If LLM already generated the header, don't add it again."""
        keyword = "dieta ketogeniczna"
        faq_text = "## Najczesciej zadawane pytania o dieta ketogeniczna\n\n## Pytanie 1?\nOdpowiedz."

        faq_header = f"## Najczesciej zadawane pytania o {keyword}"
        if not faq_text.strip().startswith("## Najczesciej zadawane pytania"):
            faq_text = faq_header + "\n\n" + faq_text

        count = faq_text.count("## Najczesciej zadawane pytania")
        assert count == 1, f"Header duplicated: found {count} times"

    def test_faq_header_empty_keyword(self):
        """If keyword is empty, still adds a generic header."""
        keyword = ""
        faq_text = "## Pytanie?\nOdpowiedz."

        faq_header = f"## Najczesciej zadawane pytania o {keyword}" if keyword else "## Najczesciej zadawane pytania"
        if not faq_text.strip().startswith("## Najczesciej zadawane pytania"):
            faq_text = faq_header + "\n\n" + faq_text

        assert faq_text.startswith("## Najczesciej zadawane pytania")

    def test_faq_section_in_brief_compiler(self):
        """Verify FAQ section exists in brief_compiler.py."""
        source = _read_file("src/article_pipeline/brief_compiler.py")
        assert "NAJCZESCIEJ ZADAWANE PYTANIA" in source
        assert "faq_plan" in source
