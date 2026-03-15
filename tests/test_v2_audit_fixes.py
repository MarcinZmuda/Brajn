"""
Tests for the v2.0 audit fixes:
1. brief_generator.py — centerpiece, co-occurrence, causal per H2, quality gate, YMYL, empty S1
2. prompts.py — WRITER_SYSTEM prompt
3. orchestrator.py — _llm_call timeout, structure validation
4. app.py — brief in ProofreadRequest
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _read_file(relative_path):
    filepath = os.path.join(os.path.dirname(__file__), "..", relative_path)
    with open(filepath, encoding="utf-8") as f:
        return f.read()


# ── brief_generator.py ──

class TestBriefGeneratorCenterpiece:
    def test_centerpiece_in_plan(self):
        from src.article_pipeline.brief_generator import generate_brief
        brief = generate_brief(
            s1_data={"main_keyword": "test"},
            variables={"ENCJA_GLOWNA": "test entity", "_h2_plan_list": ["H2 one"]},
        )
        plan = brief.get("plan", {})
        assert "centerpiece" in plan
        cp = plan["centerpiece"]
        assert "definition" in cp
        assert "goal" in cp
        assert "test entity" in cp["definition"]

    def test_centerpiece_in_markdown(self):
        from src.article_pipeline.brief_generator import generate_brief, render_brief_markdown
        brief = generate_brief(
            s1_data={"main_keyword": "test"},
            variables={"ENCJA_GLOWNA": "test entity", "_h2_plan_list": ["H2 one"]},
        )
        md = render_brief_markdown(brief)
        assert "Struktura intro" in md
        assert "test entity" in md


class TestBriefGeneratorCooccurrence:
    def test_find_relevant_pairs(self):
        from src.article_pipeline.brief_generator import _find_relevant_pairs
        pairs = [
            {"entity_a": "kara grzywny", "entity_b": "zakaz prowadzenia", "sentence_count": 5},
            {"entity_a": "dieta", "entity_b": "kalorie", "sentence_count": 3},
        ]
        result = _find_relevant_pairs("Grzywny za prowadzenie", pairs)
        assert len(result) >= 1
        assert result[0]["entity_a"] == "kara grzywny"

    def test_find_relevant_pairs_no_match(self):
        from src.article_pipeline.brief_generator import _find_relevant_pairs
        pairs = [{"entity_a": "dieta", "entity_b": "kalorie", "sentence_count": 3}]
        result = _find_relevant_pairs("Samochody elektryczne", pairs)
        assert len(result) == 0

    def test_cooccurrence_in_plan_sections(self):
        from src.article_pipeline.brief_generator import generate_brief
        brief = generate_brief(
            s1_data={
                "main_keyword": "test",
                "entity_seo": {
                    "entity_cooccurrence": [
                        {"entity_a": "test encja", "entity_b": "powiazana", "sentence_count": 4},
                    ],
                },
            },
            variables={"_h2_plan_list": ["Sekcja o test encji"]},
        )
        sections = brief["plan"]["sections"]
        assert len(sections) == 1
        assert "cooccurrence_pairs" in sections[0]

    def test_cooccurrence_in_markdown(self):
        from src.article_pipeline.brief_generator import generate_brief, render_brief_markdown
        brief = generate_brief(
            s1_data={
                "main_keyword": "test",
                "entity_seo": {
                    "entity_cooccurrence": [
                        {"entity_a": "test encja", "entity_b": "powiazana", "sentence_count": 4},
                    ],
                },
            },
            variables={"_h2_plan_list": ["Sekcja o test encji"]},
        )
        md = render_brief_markdown(brief)
        assert "RAZEM w jednym akapicie" in md


class TestBriefGeneratorCausalPerH2:
    def test_find_relevant_causal(self):
        from src.article_pipeline.brief_generator import _find_relevant_causal
        items = [
            {"cause": "alkohol", "effect": "kara grzywny"},
            {"cause": "dieta", "effect": "odchudzanie"},
        ]
        result = _find_relevant_causal("Kary za alkohol", items)
        assert len(result) >= 1
        assert result[0]["cause"] == "alkohol"

    def test_causal_in_plan_sections(self):
        from src.article_pipeline.brief_generator import generate_brief
        brief = generate_brief(
            s1_data={
                "main_keyword": "test",
                "causal_triplets": {
                    "chains": [{"cause": "testowanie", "effect": "jakosc"}],
                    "singles": [],
                },
            },
            variables={"_h2_plan_list": ["Jak testowanie wplywa"]},
        )
        sections = brief["plan"]["sections"]
        assert len(sections) == 1
        assert "causal_relations" in sections[0]


class TestBriefGeneratorSPOInstructions:
    def test_spo_instruction_in_markdown(self):
        from src.article_pipeline.brief_generator import generate_brief, render_brief_markdown
        brief = generate_brief(
            s1_data={"main_keyword": "test"},
            variables={"_h2_plan_list": ["Sekcja 1"]},
            pre_batch_map={"batch_1": {"hard_facts": ["fakt 1", "fakt 2"]}},
        )
        md = render_brief_markdown(brief)
        assert "KTO/CO" in md
        assert "ROBI" in md


class TestBriefGeneratorEmptyS1Fallback:
    def test_empty_data_warning_when_sparse(self):
        from src.article_pipeline.brief_generator import generate_brief
        brief = generate_brief(
            s1_data={"main_keyword": "test keyword"},
            variables={"DLUGOSC_CEL": "1000"},
        )
        assert "empty_data_warning" in brief
        assert "test keyword" in brief["empty_data_warning"]

    def test_no_warning_when_data_rich(self):
        from src.article_pipeline.brief_generator import generate_brief
        brief = generate_brief(
            s1_data={
                "main_keyword": "test",
                "ngrams": [
                    {"ngram": f"ngram_{i}", "weight": 0.5, "freq_min": 1, "freq_max": 3}
                    for i in range(5)
                ],
                "causal_triplets": {
                    "chains": [{"cause": "a", "effect": "b"}],
                    "singles": [],
                },
            },
            variables={"_hard_facts": [{"value": "fakt1"}, {"value": "fakt2"}, {"value": "fakt3"}]},
        )
        assert "empty_data_warning" not in brief


class TestBriefGeneratorYMYLFallback:
    def test_ymyl_fallback_when_no_keywords_match(self):
        source = _read_file("src/article_pipeline/brief_generator.py")
        assert "ymyl_display" in source or "kw_filters" in source

    def test_ymyl_uses_fallback_500_chars(self):
        source = _read_file("src/article_pipeline/brief_generator.py")
        assert "[:500]" in source


# ── prompts.py ──

class TestWriterSystemPrompt:
    def test_writer_system_exists(self):
        source = _read_file("src/article_pipeline/prompts.py")
        assert 'WRITER_SYSTEM = """' in source

    def test_writer_system_has_subject_ratio(self):
        source = _read_file("src/article_pipeline/prompts.py")
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "PODMIOTEM" in ws or "podmiot" in ws.lower()
        assert "strona" in ws.lower()

    def test_writer_system_has_anti_hallucination(self):
        source = _read_file("src/article_pipeline/prompts.py")
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "bez kwoty" in ws.lower() or "nie wymyslaj" in ws.lower()

    def test_writer_system_has_dedup(self):
        source = _read_file("src/article_pipeline/prompts.py")
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "NOWA" in ws

    def test_writer_system_bans_company_names(self):
        source = _read_file("src/article_pipeline/prompts.py")
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "nazw firm" in ws.lower() or "marek" in ws.lower() or "firm" in ws.lower()


# ── orchestrator.py ──

class TestOrchestratorTimeout:
    def test_llm_call_has_timeout_param(self):
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "timeout: int = 120" in source or "timeout=120" in source

    def test_llm_call_passes_timeout_to_claude_call(self):
        source = _read_file("src/article_pipeline/orchestrator.py")
        fn_start = source.find("def _llm_call(")
        fn_end = source.find("\n    def ", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "timeout=timeout" in fn


class TestOrchestratorV2Pipeline:
    def test_v2_has_forbidden_phrases_check(self):
        """v2.0 pipeline checks forbidden phrases after writing."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "check_forbidden_phrases" in source

    def test_v2_has_compliance_check(self):
        """v2.0 pipeline runs entity_seo_compliance."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "run_entity_seo_compliance" in source

    def test_v2_has_ngram_patcher(self):
        """v2.0 pipeline uses ngram_patcher for post-write check."""
        source = _read_file("src/article_pipeline/orchestrator.py")
        assert "check_ngram_coverage" in source
        assert "patch_missing_ngrams" in source


# ── app.py ──

class TestProofreadRequestBrief:
    def test_brief_field_in_model(self):
        source = _read_file("src/app.py")
        assert "brief: Optional[str]" in source

    def test_brief_field_is_optional(self):
        source = _read_file("src/app.py")
        assert "brief: Optional" in source
        assert "default=None" in source[source.find("brief: Optional"):source.find("brief: Optional") + 100]


# ── index.html ──

class TestFrontendProofreaderTimeout:
    def _read_html(self):
        return _read_file("src/panel/index.html")

    def test_abort_controller_in_proofreader(self):
        source = self._read_html()
        fn_start = source.find("function runProofreader")
        fn_end = source.find("\n// ──", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "AbortController" in fn
        assert "180000" in fn  # 3 minute timeout

    def test_brief_passed_to_proofreader(self):
        source = self._read_html()
        fn_start = source.find("function runProofreader")
        fn_end = source.find("\n// ──", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "brief:" in fn

    def test_centerpiece_rendered_in_brief(self):
        source = self._read_html()
        fn_start = source.find("function renderBrief")
        fn_end = source.find("\n// ──", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "centerpiece" in fn
        assert "Struktura intro" in fn

    def test_empty_data_warning_rendered(self):
        source = self._read_html()
        assert "empty_data_warning" in source

    def test_cooccurrence_rendered_per_section(self):
        source = self._read_html()
        fn_start = source.find("function renderBrief")
        fn_end = source.find("\n// ──", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "cooccurrence_pairs" in fn

    def test_causal_rendered_per_section(self):
        source = self._read_html()
        fn_start = source.find("function renderBrief")
        fn_end = source.find("\n// ──", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "causal_relations" in fn
