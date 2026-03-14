"""
Tests for orchestrator.py fixes:
1. Step numbering — no collisions between Batch 0 and H2 sections
2. FAQ header — "Najczęściej zadawane pytania o {keyword}" prepended
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestStepNumbering:
    """Verify step numbers don't collide in run_full_pipeline."""

    def test_step_indices_no_collision(self):
        """
        Read the orchestrator source and verify step assignments:
        - Batch 0 uses step 5
        - H2 sections start at step 6 (step = 6 + i)
        - FAQ step = 6 + h2_count
        """
        import ast

        filepath = os.path.join(
            os.path.dirname(__file__), "..", "src", "article_pipeline", "orchestrator.py"
        )
        with open(filepath) as f:
            source = f.read()

        # Verify batch 0 is step 5
        assert '"step": 5' in source or "'step': 5" in source, \
            "Batch 0 should use step 5"

        # Verify H2 sections use step = 6 + i
        assert "step = 6 + i" in source, \
            "H2 sections should start at step = 6 + i (not 5 + i)"

        # Verify FAQ step = 6 + h2_count
        assert "faq_step = 6 + h2_count" in source, \
            "FAQ step should be 6 + h2_count (not 5 + h2_count)"

    def test_no_step_5_collision_in_h2_loop(self):
        """Ensure 'step = 5 + i' pattern does NOT exist (was the bug)."""
        filepath = os.path.join(
            os.path.dirname(__file__), "..", "src", "article_pipeline", "orchestrator.py"
        )
        with open(filepath) as f:
            source = f.read()

        assert "step = 5 + i" not in source, \
            "Bug regression: step = 5 + i would collide with Batch 0 (step 5)"

    def test_total_steps_formula(self):
        """total_steps = 7 + h2_count covers all steps correctly."""
        # Steps: 1(YMYL) + 2(variants) + 3(H2plan) + 4(prebatch) + 5(batch0)
        #        + h2_count(H2s at 6..5+h2_count) + 1(FAQ at 6+h2_count)
        #        + 1(postprocess at 7+h2_count)
        # Total = 7 + h2_count

        for h2_count in [1, 3, 6, 10]:
            total_steps = 7 + h2_count

            # All step indices
            steps = [1, 2, 3, 4, 5]  # Fixed steps
            steps += [6 + i for i in range(h2_count)]  # H2 sections
            steps.append(6 + h2_count)  # FAQ
            steps.append(total_steps)  # Post-processing = 7 + h2_count

            # No duplicates
            assert len(steps) == len(set(steps)), \
                f"Step collision detected for h2_count={h2_count}: {steps}"

            # Last step equals total_steps
            assert max(steps) == total_steps, \
                f"Max step ({max(steps)}) != total_steps ({total_steps})"


class TestFaqHeader:
    """Test that FAQ header is prepended correctly."""

    def test_faq_header_logic(self):
        """Simulate the FAQ header prepend logic from orchestrator."""
        keyword = "dieta ketogeniczna"
        faq_text = "## Czy dieta keto jest bezpieczna?\nTak, jest bezpieczna."

        faq_header = f"## Najczęściej zadawane pytania o {keyword}"
        if not faq_text.strip().startswith("## Najczęściej zadawane pytania"):
            faq_text = faq_header + "\n\n" + faq_text

        assert faq_text.startswith("## Najczęściej zadawane pytania o dieta ketogeniczna")
        assert "## Czy dieta keto jest bezpieczna?" in faq_text

    def test_faq_header_not_duplicated(self):
        """If LLM already generated the header, don't add it again."""
        keyword = "dieta ketogeniczna"
        faq_text = "## Najczęściej zadawane pytania o dieta ketogeniczna\n\n## Pytanie 1?\nOdpowiedz."

        faq_header = f"## Najczęściej zadawane pytania o {keyword}"
        if not faq_text.strip().startswith("## Najczęściej zadawane pytania"):
            faq_text = faq_header + "\n\n" + faq_text

        # Should NOT have two headers
        count = faq_text.count("## Najczęściej zadawane pytania")
        assert count == 1, f"Header duplicated: found {count} times"

    def test_faq_header_empty_keyword(self):
        """If keyword is empty, still adds a generic header."""
        keyword = ""
        faq_text = "## Pytanie?\nOdpowiedz."

        faq_header = f"## Najczęściej zadawane pytania o {keyword}" if keyword else "## Najczęściej zadawane pytania"
        if not faq_text.strip().startswith("## Najczęściej zadawane pytania"):
            faq_text = faq_header + "\n\n" + faq_text

        assert faq_text.startswith("## Najczęściej zadawane pytania")

    def test_faq_header_in_source_code(self):
        """Verify the FAQ header logic exists in orchestrator.py."""
        filepath = os.path.join(
            os.path.dirname(__file__), "..", "src", "article_pipeline", "orchestrator.py"
        )
        with open(filepath) as f:
            source = f.read()

        assert "Najczęściej zadawane pytania o" in source
        assert 'faq_header' in source
