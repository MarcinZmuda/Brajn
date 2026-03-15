"""
Tests for:
1. prompts.py — company name ban added to both BATCH_N_SYSTEM and ARTICLE_WRITER_PROMPT
2. index.html — syntax validation, null checks, article editor section
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestAuditPromptInstructionRule:
    """Verify the KRYTYCZNA REGULA for suggestion format is in the audit prompt."""

    def _read_proofreader(self):
        filepath = os.path.join(
            os.path.dirname(__file__), "..", "src", "article_pipeline", "editorial_proofreader.py"
        )
        with open(filepath, encoding="utf-8") as f:
            return f.read()

    def test_rule_in_audit_prompt(self):
        source = self._read_proofreader()
        assert "GOTOWY TEKST ZASTEPCZY" in source, \
            "Audit prompt missing KRYTYCZNA REGULA about suggestion format"

    def test_rule_has_good_bad_examples(self):
        source = self._read_proofreader()
        assert "DOBRZE:" in source, "Rule should have DOBRZE example"
        assert "ZLE:" in source, "Rule should have ZLE examples"

    def test_is_editorial_instruction_function_exists(self):
        from src.article_pipeline.editorial_proofreader import _is_editorial_instruction
        assert callable(_is_editorial_instruction)

    def test_instruction_markers_defined(self):
        from src.article_pipeline.editorial_proofreader import _INSTRUCTION_MARKERS
        assert len(_INSTRUCTION_MARKERS) > 5, "Should have multiple instruction markers"
        assert "usuń" in _INSTRUCTION_MARKERS
        assert "zastąp" in _INSTRUCTION_MARKERS


class TestProofreaderDiagnosticLogging:
    """Verify diagnostic logging was added to editorial_proofreader.py."""

    def _read_proofreader(self):
        filepath = os.path.join(
            os.path.dirname(__file__), "..", "src", "article_pipeline", "editorial_proofreader.py"
        )
        with open(filepath, encoding="utf-8") as f:
            return f.read()

    def test_proofread_article_logs_entry(self):
        source = self._read_proofreader()
        fn_start = source.find("def proofread_article(")
        fn_chunk = source[fn_start:fn_start + 800]
        assert "[PROOFREADER] Called:" in fn_chunk

    def test_run_audit_logs_entry(self):
        source = self._read_proofreader()
        fn_start = source.find("def _run_audit(")
        fn_chunk = source[fn_start:fn_start + 500]
        assert "[PROOFREADER] Starting audit:" in fn_chunk

    def test_run_audit_logs_traceback_on_error(self):
        source = self._read_proofreader()
        fn_start = source.find("def _run_audit(")
        fn_chunk = source[fn_start:fn_start + 1200]
        assert "traceback.format_exc()" in fn_chunk


class TestHallucinationPrevention:
    """Verify anti-hallucination rules in WRITER_SYSTEM (v2.0)."""

    def _read_prompts(self):
        filepath = os.path.join(
            os.path.dirname(__file__), "..", "src", "article_pipeline", "prompts.py"
        )
        with open(filepath, encoding="utf-8") as f:
            return f.read()

    def test_hallucination_prevention_in_writer_system(self):
        source = self._read_prompts()
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "WYLACZNIE" in ws, "WRITER_SYSTEM should restrict to brief facts only"

    def test_prevention_forbids_ungrounded_facts(self):
        source = self._read_prompts()
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "kwoty" in ws.lower() or "bez kwoty" in ws.lower(), \
            "Should warn about inventing amounts"

    def test_prevention_suggests_generic_alternatives(self):
        source = self._read_prompts()
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "ogolnie" in ws.lower(), "Should suggest writing generally when no data"

    def test_prevention_mentions_consequences(self):
        """Should warn about real-world consequences of wrong numbers."""
        source = self._read_prompts()
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "szkode" in ws.lower() or "szkoda" in ws.lower() or "blad" in ws.lower()


class TestProofreadEndpointErrorHandling:
    """Verify /api/proofread returns proper fallback on error."""

    def _read_app(self):
        filepath = os.path.join(
            os.path.dirname(__file__), "..", "src", "app.py"
        )
        with open(filepath, encoding="utf-8") as f:
            return f.read()

    def test_endpoint_returns_fallback_fields(self):
        source = self._read_app()
        fn_start = source.find("async def proofread_article_endpoint")
        fn_end = source.find("\n@app.", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert '"corrected_text"' in fn, "Error fallback must include corrected_text"
        assert '"applied"' in fn, "Error fallback must include applied"
        assert '"flagged"' in fn, "Error fallback must include flagged"
        assert '"stats"' in fn, "Error fallback must include stats"

    def test_endpoint_logs_traceback(self):
        source = self._read_app()
        fn_start = source.find("async def proofread_article_endpoint")
        fn_end = source.find("\n@app.", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "traceback.format_exc()" in fn, "Should log full traceback"
        assert "[PROOFREAD API]" in fn, "Should use [PROOFREAD API] log prefix"


class TestPromptsCompanyBan:
    """Verify company/brand name ban is present in WRITER_SYSTEM (v2.0)."""

    def _read_prompts(self):
        filepath = os.path.join(
            os.path.dirname(__file__), "..", "src", "article_pipeline", "prompts.py"
        )
        with open(filepath, encoding="utf-8") as f:
            return f.read()

    def test_ban_in_writer_system(self):
        """WRITER_SYSTEM should contain company name ban."""
        source = self._read_prompts()
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "nazw firm" in ws or "marek" in ws.lower() or "firm" in ws.lower(), \
            "WRITER_SYSTEM missing company name ban"

    def test_ban_in_writer_system_with_exception(self):
        """Ban should allow firm names in H2 headings when required by brief."""
        source = self._read_prompts()
        start = source.find('WRITER_SYSTEM = """')
        end = source.find('"""', start + 20)
        ws = source[start:end]
        assert "H2" in ws or "naglowku" in ws.lower() or "brief" in ws.lower(), \
            "Ban should mention exception for H2 headings"

    def test_ban_exists_in_source(self):
        """Company name ban should exist somewhere in prompts."""
        source = self._read_prompts()
        assert "firm" in source.lower(), "Prompts should mention firm names"


class TestFrontendIndexHtml:
    """Tests for index.html modifications."""

    def _read_html(self):
        filepath = os.path.join(
            os.path.dirname(__file__), "..", "src", "panel", "index.html"
        )
        with open(filepath, encoding="utf-8") as f:
            return f.read()

    # ── Null checks ──

    def test_log_has_null_check(self):
        source = self._read_html()
        # Find log function
        log_fn_start = source.find("function log(m, cls)")
        log_fn_end = source.find("\nfunction ", log_fn_start + 10)
        log_fn = source[log_fn_start:log_fn_end]
        assert "if (!c) return" in log_fn, "log() missing null check for logC"

    def test_renderAnnotationView_has_null_check(self):
        source = self._read_html()
        fn_start = source.find("function renderAnnotationView()")
        fn_chunk = source[fn_start:fn_start + 300]
        assert "if (!c) return" in fn_chunk, "renderAnnotationView() missing null check"

    def test_renderCompliance_has_null_check(self):
        source = self._read_html()
        fn_start = source.find("function renderCompliance(data)")
        fn_chunk = source[fn_start:fn_start + 300]
        assert "if (!c) return" in fn_chunk, "renderCompliance() missing null check"

    def test_renderArticle_has_null_check(self):
        source = self._read_html()
        fn_start = source.find("function renderArticle(text)")
        fn_chunk = source[fn_start:fn_start + 300]
        assert "if (!preview) return" in fn_chunk, "renderArticle() missing null check for preview"

    def test_showValidation_has_null_checks(self):
        source = self._read_html()
        fn_start = source.find("function showValidation(v)")
        fn_end = source.find("\nfunction ", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "if (badge)" in fn or "if (!badge)" in fn, \
            "showValidation() missing null check for scoreBadge"

    def test_renderEntityCompliance_has_null_check(self):
        source = self._read_html()
        fn_start = source.find("function renderEntityCompliance(data)")
        fn_chunk = source[fn_start:fn_start + 200]
        assert "if (!c) return" in fn_chunk, "renderEntityCompliance() missing null check"

    def test_cleanup_has_null_checks(self):
        source = self._read_html()
        fn_start = source.find("function cleanup()")
        fn_end = source.find("\nfunction ", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "if (btn)" in fn or "if (stop)" in fn, \
            "cleanup() missing null checks for buttons"

    def test_selMode_has_null_checks(self):
        source = self._read_html()
        fn_start = source.find("function selMode(m)")
        fn_end = source.find("\nfunction ", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "if (auditFields)" in fn, "selMode() missing null check for auditFields"
        assert "if (btnStart)" in fn, "selMode() missing null check for btnStart"

    def test_selEngine_has_null_check(self):
        source = self._read_html()
        fn_start = source.find("function selEngine(e)")
        fn_end = source.find("\nfunction ", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "if (lbl)" in fn, "selEngine() missing null check for engineLabel"

    # ── XSS fix ──

    def test_renderArticle_escapes_before_markdown(self):
        """renderArticle should call esc(text) before markdown conversion."""
        source = self._read_html()
        fn_start = source.find("function renderArticle(text)")
        fn_end = source.find("\n// ──", fn_start + 10)
        fn = source[fn_start:fn_end]
        # esc(text) should appear before the markdown regex replacements
        esc_pos = fn.find("esc(text)")
        h1_pos = fn.find("replace(/^# ")
        assert esc_pos != -1, "renderArticle() should call esc(text)"
        assert esc_pos < h1_pos, "esc(text) should come before markdown conversion"

    def test_showValidation_escapes_passed(self):
        """v.passed items should be escaped."""
        source = self._read_html()
        fn_start = source.find("function showValidation(v)")
        fn_end = source.find("\nfunction ", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "esc(String(p))" in fn or "esc(p)" in fn, \
            "v.passed items should be escaped with esc()"

    # ── pre_batch_keys display ──

    def test_pre_batch_keys_shows_length(self):
        """pre_batch_keys should display as count, not array.toString()."""
        source = self._read_html()
        assert "pre_batch_keys.length" in source, \
            "pre_batch_keys should use .length for display"

    # ── Proofreader highlights ──

    def test_proof_highlight_css_exists(self):
        """CSS classes for proofreader highlights should exist."""
        source = self._read_html()
        assert ".proof-hl-high" in source, "Missing proof-hl-high CSS class"
        assert ".proof-hl-med" in source, "Missing proof-hl-med CSS class"
        assert ".proof-hl-low" in source, "Missing proof-hl-low CSS class"

    def test_proofFlagged_global_declared(self):
        """proofFlagged global variable should be declared."""
        source = self._read_html()
        assert "proofFlagged" in source, "Missing proofFlagged global variable"

    def test_renderArticle_applies_highlights(self):
        """renderArticle should highlight flagged fragments."""
        source = self._read_html()
        fn_start = source.find("function renderArticle(text)")
        fn_end = source.find("\n// ──", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "proofFlagged" in fn, "renderArticle should use proofFlagged"
        assert "proof-hl-" in fn, "renderArticle should apply proof-hl- classes"
        assert "<mark" in fn, "renderArticle should use <mark> for highlights"

    def test_proofFlagged_set_before_render(self):
        """proofFlagged should be set before renderProofreading/renderArticle calls."""
        source = self._read_html()
        # In standalone proofreader flow
        set_pos = source.find("proofFlagged = result.flagged")
        assert set_pos != -1, "proofFlagged should be set from result.flagged"
        # In pipeline flow
        set_pos2 = source.find("proofFlagged = (d.data.proofreading.flagged")
        assert set_pos2 != -1, "proofFlagged should be set in pipeline flow"

    # ── Article Editor ──

    def test_article_edit_section_exists(self):
        source = self._read_html()
        assert 'id="articleEditSection"' in source, "Missing articleEditSection HTML"
        assert 'id="articleEditMode"' in source, "Missing articleEditMode HTML"
        assert 'id="articleEditArea"' in source, "Missing articleEditArea textarea"
        assert 'id="selectionFixModal"' in source, "Missing selectionFixModal HTML"
        assert 'id="fixInstruction"' in source, "Missing fixInstruction textarea"

    def test_article_edit_functions_exist(self):
        source = self._read_html()
        assert "function toggleArticleEdit()" in source
        assert "function saveArticleEdit()" in source
        assert "function fixSelection()" in source
        assert "function closeSelectionFix()" in source
        assert "function applySelectionFix()" in source

    def test_applySelectionFix_uses_bearer_auth(self):
        """applySelectionFix should use Authorization: Bearer, not X-API-Key."""
        source = self._read_html()
        fn_start = source.find("async function applySelectionFix()")
        fn_end = source.find("\n// ──", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "'Authorization': 'Bearer ' + apiKey" in fn, \
            "applySelectionFix should use Authorization: Bearer header"
        assert "X-API-Key" not in fn, \
            "applySelectionFix should NOT use X-API-Key header"

    def test_article_edit_section_shown_in_renderArticle(self):
        """renderArticle should show the edit section."""
        source = self._read_html()
        fn_start = source.find("function renderArticle(text)")
        fn_end = source.find("\n// ──", fn_start + 10)
        fn = source[fn_start:fn_end]
        assert "articleEditSection" in fn, \
            "renderArticle() should show articleEditSection"

    # ── HTML structure ──

    def test_html_is_valid_structure(self):
        """Basic HTML structure checks."""
        source = self._read_html()
        assert source.strip().startswith("<!DOCTYPE html>")
        assert "<html" in source
        assert "</html>" in source
        # All opened script tags are closed
        script_opens = source.count("<script>") + source.count("<script ")
        script_closes = source.count("</script>")
        assert script_opens == script_closes, \
            f"Mismatched script tags: {script_opens} opens vs {script_closes} closes"

    # ── JS syntax ──

    def test_no_obvious_js_syntax_errors(self):
        """Check for common JS syntax issues in the script section."""
        source = self._read_html()
        script_start = source.find("<script>")
        script_end = source.rfind("</script>")
        js = source[script_start + 8:script_end]

        # Check balanced braces
        brace_count = 0
        for ch in js:
            if ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
            assert brace_count >= 0, "Unmatched closing brace in JS"
        assert brace_count == 0, f"Unmatched braces in JS: {brace_count} unclosed"

        # Check balanced parentheses
        paren_count = 0
        for ch in js:
            if ch == '(':
                paren_count += 1
            elif ch == ')':
                paren_count -= 1
        assert paren_count == 0, f"Unmatched parentheses in JS: {paren_count} unclosed"
