"""
Tests for v2.0 pipeline architecture:
1. brief_compiler.py — compile_brief, build_example_paragraph, helpers
2. ngram_patcher.py — check_ngram_coverage, _parse_json
3. orchestrator.py v2 — pipeline structure, imports, SSE events
4. prompts.py v2 — minimal prompts, FORBIDDEN_PHRASES, DISCLAIMERS
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _read_file(relative_path):
    filepath = os.path.join(os.path.dirname(__file__), "..", relative_path)
    with open(filepath, encoding="utf-8") as f:
        return f.read()


# ── brief_compiler.py ──

class TestBriefCompiler:
    def test_compile_brief_returns_string(self):
        from src.article_pipeline.brief_compiler import compile_brief
        result = compile_brief(
            s1_data={"main_keyword": "test"},
            variables={"HASLO_GLOWNE": "test keyword", "DLUGOSC_CEL": "800"},
            h2_plan=["Sekcja 1", "Sekcja 2"],
            faq_plan=["Pytanie 1?"],
            h1="Test H1",
            search_variants={"peryfrazy": ["wariant1"], "named_forms": ["test keyword"]},
            ymyl_class="none",
            ymyl_context="",
        )
        assert isinstance(result, str)
        assert "TEMAT: test keyword" in result
        assert "H1: Test H1" in result
        assert "SEKCJA 1: Sekcja 1" in result
        assert "SEKCJA 2: Sekcja 2" in result

    def test_compile_brief_includes_variants(self):
        from src.article_pipeline.brief_compiler import compile_brief
        result = compile_brief(
            s1_data={},
            variables={"HASLO_GLOWNE": "kw"},
            h2_plan=["H2"],
            faq_plan=[],
            h1="H1",
            search_variants={
                "peryfrazy": ["peryfraza1", "peryfraza2"],
                "named_forms": ["kw"],
                "nominal_forms": ["ten sposob"],
                "pronominal_cues": ["to"],
            },
            ymyl_class="none",
            ymyl_context="",
        )
        assert "peryfraza1" in result
        assert "ten sposob" in result

    def test_compile_brief_includes_faq(self):
        from src.article_pipeline.brief_compiler import compile_brief
        result = compile_brief(
            s1_data={},
            variables={"HASLO_GLOWNE": "kw"},
            h2_plan=["H2"],
            faq_plan=["Czy to dziala?", "Jak uzyc?"],
            h1="H1",
            search_variants={},
            ymyl_class="none",
            ymyl_context="",
        )
        assert "Czy to dziala?" in result
        assert "Jak uzyc?" in result

    def test_compile_brief_includes_disclaimer(self):
        from src.article_pipeline.brief_compiler import compile_brief
        result = compile_brief(
            s1_data={},
            variables={"HASLO_GLOWNE": "kw"},
            h2_plan=["H2"],
            faq_plan=[],
            h1="H1",
            search_variants={},
            ymyl_class="prawo",
            ymyl_context="",
        )
        assert "DISCLAIMER" in result

    def test_compile_brief_no_disclaimer_for_none(self):
        from src.article_pipeline.brief_compiler import compile_brief
        result = compile_brief(
            s1_data={},
            variables={"HASLO_GLOWNE": "kw"},
            h2_plan=["H2"],
            faq_plan=[],
            h1="H1",
            search_variants={},
            ymyl_class="none",
            ymyl_context="",
        )
        assert "DISCLAIMER" not in result

    def test_compile_brief_includes_keyphrases(self):
        from src.article_pipeline.brief_compiler import compile_brief
        result = compile_brief(
            s1_data={},
            variables={
                "HASLO_GLOWNE": "kw",
                "_ngrams": [
                    {"ngram": "fraza testowa", "weight": 0.5},
                    {"ngram": "inna fraza", "weight": 0.3},
                ],
            },
            h2_plan=["H2"],
            faq_plan=[],
            h1="H1",
            search_variants={},
            ymyl_class="none",
            ymyl_context="",
        )
        assert "fraza testowa" in result
        assert "inna fraza" in result

    def test_compile_brief_dedup_tracking(self):
        from src.article_pipeline.brief_compiler import compile_brief
        result = compile_brief(
            s1_data={},
            variables={
                "HASLO_GLOWNE": "kw",
                "_hard_facts": [
                    {"value": "fakt alfa", "source_snippet": "sekcja jeden info"},
                    {"value": "fakt beta", "source_snippet": "sekcja dwa info"},
                ],
            },
            h2_plan=["Sekcja jeden", "Sekcja dwa"],
            faq_plan=[],
            h1="H1",
            search_variants={},
            ymyl_class="none",
            ymyl_context="",
        )
        assert "fakt alfa" in result
        # Second section should have "nie powtarzaj" instruction
        assert "nie powtarzaj" in result.lower()


class TestBriefCompilerExample:
    def test_example_prawo(self):
        from src.article_pipeline.brief_compiler import build_example_paragraph
        result = build_example_paragraph("jazda po alkoholu", [], "prawo")
        assert "promila" in result.lower() or "Przekroczenie" in result

    def test_example_zdrowie(self):
        from src.article_pipeline.brief_compiler import build_example_paragraph
        result = build_example_paragraph("koldra obciazeniowa", [], "zdrowie")
        assert "koldra" in result.lower() or "Koldra" in result

    def test_example_none(self):
        from src.article_pipeline.brief_compiler import build_example_paragraph
        result = build_example_paragraph("kurs barberski", [], "none")
        assert "kurs" in result.lower() or "barber" in result.lower()


class TestBriefCompilerHelpers:
    def test_find_relevant_facts(self):
        from src.article_pipeline.brief_compiler import _find_relevant_facts
        facts = [
            {"value": "kara 5000 zl", "source_snippet": "grzywna za alkohol"},
            {"value": "dieta 1500 kcal", "source_snippet": "odchudzanie"},
        ]
        result = _find_relevant_facts("Kary za alkohol", facts, [], set())
        assert len(result) >= 1
        assert "kara 5000 zl" in result

    def test_find_relevant_facts_skips_covered(self):
        from src.article_pipeline.brief_compiler import _find_relevant_facts
        facts = [{"value": "fakt abc", "source_snippet": "sekcja testowa"}]
        covered = {"fakt abc"}
        result = _find_relevant_facts("Sekcja testowa", facts, [], covered)
        assert len(result) == 0

    def test_find_relevant_causal(self):
        from src.article_pipeline.brief_compiler import _find_relevant_causal
        causal = {
            "chains": [
                {"cause": "alkohol", "effect": "kara grzywny"},
                {"cause": "dieta", "effect": "odchudzanie"},
            ]
        }
        result = _find_relevant_causal("Kary za alkohol", causal, "alkohol")
        assert len(result) >= 1
        assert "alkohol" in result[0]

    def test_find_relevant_cooccurrence(self):
        from src.article_pipeline.brief_compiler import _find_relevant_cooccurrence
        pairs = [
            {"entity_a": "kara grzywny", "entity_b": "zakaz prowadzenia"},
            {"entity_a": "dieta", "entity_b": "kalorie"},
        ]
        result = _find_relevant_cooccurrence("Grzywny za prowadzenie", pairs)
        assert len(result) >= 1


# ── ngram_patcher.py ──

class TestNgramPatcher:
    def test_check_ngram_coverage_basic(self):
        from src.article_pipeline.ngram_patcher import check_ngram_coverage
        article = "To jest artykul o testowaniu oprogramowania i jakosc kodu."
        ngrams = [
            {"ngram": "testowaniu", "weight": 0.5, "freq_min": 1},
            {"ngram": "brakujaca fraza", "weight": 0.4, "freq_min": 1},
            {"ngram": "jakosc", "weight": 0.3, "freq_min": 1},
        ]
        result = check_ngram_coverage(article, ngrams)
        assert result["total"] == 3
        assert len(result["present"]) == 2
        assert len(result["missing"]) == 1
        assert result["missing"][0]["term"] == "brakujaca fraza"

    def test_check_ngram_coverage_empty(self):
        from src.article_pipeline.ngram_patcher import check_ngram_coverage
        result = check_ngram_coverage("jakis tekst", [])
        assert result["total"] == 0
        assert result["coverage_pct"] == 0

    def test_check_ngram_coverage_percentage(self):
        from src.article_pipeline.ngram_patcher import check_ngram_coverage
        article = "fraza1 fraza2 fraza3"
        ngrams = [
            {"ngram": "fraza1", "weight": 0.5, "freq_min": 1},
            {"ngram": "fraza2", "weight": 0.5, "freq_min": 1},
            {"ngram": "brak1", "weight": 0.5, "freq_min": 1},
            {"ngram": "brak2", "weight": 0.5, "freq_min": 1},
        ]
        result = check_ngram_coverage(article, ngrams)
        assert result["coverage_pct"] == 50

    def test_important_missing_filter(self):
        from src.article_pipeline.ngram_patcher import check_ngram_coverage
        ngrams = [
            {"ngram": "wazna fraza", "weight": 0.5, "freq_min": 1},
            {"ngram": "niewazna", "weight": 0.1, "freq_min": 1},
        ]
        result = check_ngram_coverage("tekst bez fraz", ngrams)
        assert len(result["important_missing"]) == 1
        assert result["important_missing"][0]["term"] == "wazna fraza"

    def test_parse_json(self):
        from src.article_pipeline.ngram_patcher import _parse_json
        result = _parse_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_plain(self):
        from src.article_pipeline.ngram_patcher import _parse_json
        result = _parse_json('{"key": 42}')
        assert result == {"key": 42}

    def test_parse_json_invalid(self):
        from src.article_pipeline.ngram_patcher import _parse_json
        result = _parse_json('not json')
        assert result is None


# ── prompts.py v2 ──

class TestPromptsV2:
    def test_writer_system_exists(self):
        source = _read_file("src/article_pipeline/prompts.py")
        assert 'WRITER_SYSTEM = """' in source

    def test_writer_user_has_brief_placeholder(self):
        source = _read_file("src/article_pipeline/prompts.py")
        assert "{brief_text}" in source
        assert "{example_paragraph}" in source

    def test_ngram_patcher_prompts_exist(self):
        source = _read_file("src/article_pipeline/prompts.py")
        assert "NGRAM_PATCHER_SYSTEM" in source
        assert "NGRAM_PATCHER_USER" in source

    def test_h2_plan_prompts_exist(self):
        source = _read_file("src/article_pipeline/prompts.py")
        assert "H2_PLAN_SYSTEM" in source
        assert "H2_PLAN_USER" in source

    def test_forbidden_phrases_exist(self):
        from src.article_pipeline.prompts import FORBIDDEN_PHRASES
        assert len(FORBIDDEN_PHRASES) > 10

    def test_disclaimers_exist(self):
        from src.article_pipeline.prompts import DISCLAIMERS
        assert "prawo" in DISCLAIMERS
        assert "zdrowie" in DISCLAIMERS
        assert "finanse" in DISCLAIMERS

    def test_no_batch_prompts(self):
        """v2.0 should NOT have batch-based prompts."""
        source = _read_file("src/article_pipeline/prompts.py")
        assert "BATCH_0_PROMPT" not in source
        assert "BATCH_N_PROMPT" not in source
        assert "PRE_BATCH_PROMPT" not in source
        assert "POST_PROCESSING_PROMPT" not in source

    def test_prompts_line_count(self):
        """v2.0 prompts should be much shorter than v1.0 (~150 vs 850 lines)."""
        source = _read_file("src/article_pipeline/prompts.py")
        line_count = len(source.split("\n"))
        assert line_count < 250, f"prompts.py has {line_count} lines, expected < 250"


# ── orchestrator.py v2 ──

class TestOrchestratorV2:
    def test_v2_uses_brief_compiler(self):
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "from src.article_pipeline.brief_compiler import" in source
        assert "compile_brief" in source

    def test_v2_uses_ngram_patcher(self):
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "ngram_patcher" in source

    def test_v2_does_not_import_keyword_tracker(self):
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "KeywordTracker" not in source

    def test_v2_does_not_import_batch_prompts(self):
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "BATCH_0_PROMPT" not in source
        assert "BATCH_N_PROMPT" not in source
        assert "PRE_BATCH_PROMPT" not in source

    def test_v2_has_writer_system_import(self):
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "WRITER_SYSTEM" in source
        assert "WRITER_USER" in source

    def test_v2_orchestrator_line_count(self):
        """v2.0 orchestrator should be much shorter (~300 vs 1020 lines)."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        line_count = len(source.split("\n"))
        assert line_count <= 450, f"orchestrator.py has {line_count} lines, expected <= 450"

    def test_v2_complete_event_has_brief(self):
        """Complete event should include brief text."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        # In the complete event data
        assert '"brief": brief_text' in source

    def test_v2_complete_event_has_coverage(self):
        """Complete event should include coverage report."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert '"coverage": coverage' in source

    def test_v2_complete_event_has_h2_plan(self):
        """Complete event should include h2_plan."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert '"h2_plan": h2_plan' in source


# ── panel/index.html v2 ──

class TestPanelV2:
    def _read_html(self):
        return _read_file("src/panel/index.html")

    def test_renderBrief_handles_string(self):
        """v2.0 renderBrief should handle string briefs."""
        source = self._read_html()
        assert "typeof data === 'string'" in source

    def test_renderCoverage_function_exists(self):
        """renderCoverage function should exist for n-gram coverage display."""
        source = self._read_html()
        assert "function renderCoverage" in source

    def test_copyBriefMarkdown_handles_string(self):
        """copyBriefMarkdown should handle string briefs in v2.0."""
        source = self._read_html()
        fn_start = source.find("function copyBriefMarkdown()")
        fn_chunk = source[fn_start:fn_start + 300]
        assert "typeof b === 'string'" in fn_chunk
