"""
BRAJN Article Orchestrator v2.0

3-step pipeline:
1. Brief compilation (code) -> Writer (Sonnet) -> Article
2. N-gram check (code) -> optional Haiku patch
3. Compliance check (code)

Proofreader runs as separate /api/proofread call from frontend.
"""

import json
import re
from typing import Generator

from src.common.llm import claude_call
from src.article_pipeline.prompts import (
    WRITER_SYSTEM, WRITER_USER,
    H2_PLAN_SYSTEM, H2_PLAN_USER,
    FORBIDDEN_PHRASES,
)
from src.article_pipeline.variables import extract_global_variables
from src.article_pipeline.validators import check_forbidden_phrases, validate_global
from src.article_pipeline.brief_compiler import compile_brief, build_example_paragraph


def _safe_json_parse(text: str) -> dict | None:
    """Parse JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1:
        return None
    try:
        return json.loads(text[first : last + 1])
    except json.JSONDecodeError:
        # Fix trailing commas
        clean = re.sub(r',\s*([}\]])', r'\1', text[first : last + 1])
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            return None


class ArticleOrchestrator:
    """Orchestrates the BRAJN v2.0 article generation pipeline."""

    def __init__(self, s1_data: dict, engine: str = "claude",
                 model: str = "claude-sonnet-4-6",
                 nw_terms: list = None, h2_keywords: list = None,
                 project_id: str = None):
        self.s1_data = s1_data.get("_llm_ready") or s1_data
        self._s1_full = s1_data
        self.engine = engine
        self.model = model
        self.project_id = project_id
        self.variables = extract_global_variables(s1_data)
        self._h2_keywords = h2_keywords or []
        self.full_article = ""
        self.prompt_log = []
        self.input_variables = {}

        # NW analysis
        from src.article_pipeline.nw_analyzer import analyze_nw_coverage
        self._nw_analysis = analyze_nw_coverage(nw_terms or [], s1_data)

    def _llm_call(self, system: str, user: str,
                   max_tokens: int = 8000, label: str = "",
                   model: str = None, temperature: float = 0.7,
                   timeout: int = 120) -> str:
        """Unified LLM call with logging."""
        use_model = model or self.model
        response, usage = claude_call(
            system_prompt=system,
            user_prompt=user,
            model=use_model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        self.prompt_log.append({
            "label": label,
            "system_preview": system[:200],
            "user_preview": user[:200],
            "response_preview": response[:200],
            "usage": usage,
        })
        return response

    def run_full_pipeline(self) -> Generator[dict, None, None]:
        """
        Run the complete v2.0 pipeline with SSE events.

        Steps:
        1. YMYL detection (Haiku)
        2. Search variants (Haiku)
        3. H2 plan (Sonnet)
        4. Brief compilation (code)
        5. Article writing (Sonnet) <- THE MAIN CALL
        6. N-gram check + patch (code + optional Haiku)
        7. Compliance check (code)
        """
        total_steps = 7

        # -- Step 1: YMYL --
        yield {"event": "step_start", "step": 1, "total": total_steps,
               "label": "YMYL: detekcja kategorii"}
        ymyl_class = self._detect_ymyl()
        ymyl_context = self._enrich_ymyl(ymyl_class)
        yield {"event": "step_done", "step": 1,
               "data": {"ymyl": ymyl_class}}

        # -- Step 2: Search variants --
        yield {"event": "step_start", "step": 2, "total": total_steps,
               "label": "Warianty jezykowe"}
        variants = self._generate_variants()
        yield {"event": "step_done", "step": 2,
               "data": {"variants_count": sum(len(v) for v in variants.values() if isinstance(v, list))}}

        # -- Step 3: H2 plan --
        yield {"event": "step_start", "step": 3, "total": total_steps,
               "label": "Plan artykulu"}
        plan = self._generate_h2_plan()
        h2_plan = plan.get("h2_plan", [])
        faq_plan = plan.get("faq", [])
        h1 = plan.get("h1_suggestion", self.variables.get("HASLO_GLOWNE", "") + " - kompletny przewodnik")
        yield {"event": "step_done", "step": 3,
               "data": {"h2_plan": h2_plan, "faq": faq_plan, "h1": h1}}

        # -- Step 4: Brief compilation --
        yield {"event": "step_start", "step": 4, "total": total_steps,
               "label": "Kompilacja briefu"}

        brief_text = compile_brief(
            s1_data=self._s1_full,
            variables=self.variables,
            h2_plan=h2_plan,
            faq_plan=faq_plan,
            h1=h1,
            search_variants=variants,
            ymyl_class=ymyl_class,
            ymyl_context=ymyl_context,
        )

        example = build_example_paragraph(
            keyword=self.variables.get("HASLO_GLOWNE", ""),
            hard_facts=self.variables.get("_hard_facts", []),
            ymyl_class=ymyl_class,
        )

        # Snapshot input variables for panel
        self.input_variables = {k: v for k, v in self.variables.items()
                                 if not k.startswith("_")}

        yield {"event": "step_done", "step": 4,
               "data": {"brief_preview": brief_text[:500],
                        "brief": brief_text}}

        # -- Step 5: WRITE ARTICLE (main Sonnet call) --
        yield {"event": "step_start", "step": 5, "total": total_steps,
               "label": "Pisanie artykulu"}

        user_prompt = WRITER_USER.format(
            brief_text=brief_text,
            example_paragraph=example,
        )

        article = self._llm_call(
            system=WRITER_SYSTEM,
            user=user_prompt,
            max_tokens=8000,
            label="write_article",
            temperature=0.7,
        )

        # Clean up
        article = article.strip()

        # Local validation (forbidden phrases)
        issues = check_forbidden_phrases(article)
        if issues:
            print(f"[WRITER] Found {len(issues)} forbidden phrases - removing")
            for phrase in issues:
                article = re.sub(
                    re.escape(phrase), "", article, flags=re.IGNORECASE
                )

        self.full_article = article

        yield {"event": "step_done", "step": 5,
               "data": {"text": article,
                         "word_count": len(article.split())}}
        yield {"event": "article_assembled",
               "data": {"full_text": article,
                        "total_words": len(article.split())}}

        # -- Step 6: N-gram check + patch --
        yield {"event": "step_start", "step": 6, "total": total_steps,
               "label": "Sprawdzenie fraz kluczowych"}

        from src.article_pipeline.ngram_patcher import check_ngram_coverage, patch_missing_ngrams

        ngrams = (self._s1_full.get("ngrams") or []) + (self._s1_full.get("extended_terms") or [])
        coverage = check_ngram_coverage(article, ngrams)

        patches_applied = []
        important_missing = coverage.get("important_missing", [])
        if len(important_missing) >= 3:
            print(f"[PATCHER] {len(important_missing)} important phrases missing - patching")
            article, patches_applied = patch_missing_ngrams(
                article, important_missing, max_patches=5
            )
            if patches_applied:
                self.full_article = article
                # Recheck coverage
                coverage = check_ngram_coverage(article, ngrams)

        yield {"event": "step_done", "step": 6,
               "data": {"coverage": coverage,
                         "patches": len(patches_applied)}}

        # -- Step 7: Compliance --
        yield {"event": "step_start", "step": 7, "total": total_steps,
               "label": "Compliance check"}

        entity_compliance = None
        try:
            from src.article_pipeline.entity_seo_compliance import run_entity_seo_compliance
            nlp = None
            try:
                from src.common.nlp_singleton import get_nlp
                nlp = get_nlp()
            except Exception:
                pass
            entity_compliance = run_entity_seo_compliance(
                article_text=article,
                s1_data=self._s1_full,
                ngram_coverage=coverage,
                nlp=nlp,
            )
        except Exception as e:
            print(f"[COMPLIANCE] Error: {e}")

        yield {"event": "step_done", "step": 7,
               "data": {"compliance_score": (entity_compliance or {}).get("overall_score", 0)}}

        # -- Complete --
        yield {"event": "complete", "data": {
            "full_text": article,
            "total_words": len(article.split()),
            "validation_score": (entity_compliance or {}).get("overall_score", 0),
            "ymyl": ymyl_class,
            "prompt_log": self.prompt_log,
            "input_variables": self.input_variables,
            "coverage": coverage,
            "entity_compliance": entity_compliance,
            "brief": brief_text,
            "s1_data": self._s1_full,
            "h2_plan": h2_plan,
            "faq_plan": faq_plan,
        }}

    # ==============================================================
    # Helper methods
    # ==============================================================

    def _detect_ymyl(self) -> str:
        """Detect YMYL category."""
        try:
            from src.article_pipeline.ymyl_detector import detect_ymyl
            result = detect_ymyl(self.variables.get("HASLO_GLOWNE", ""))
            return result.get("category", "none")
        except Exception:
            return "none"

    def _enrich_ymyl(self, ymyl_class: str) -> str:
        """Get YMYL context (legal/medical enrichment)."""
        if ymyl_class == "none":
            return ""
        try:
            if ymyl_class == "prawo":
                from src.ymyl.legal_enricher import enrich_legal
                result = enrich_legal(self.variables.get("HASLO_GLOWNE", ""), self._s1_full)
                ctx = result.get("context_block", "")
                self.variables["YMYL_CONTEXT"] = ctx
                return ctx
            elif ymyl_class == "zdrowie":
                from src.ymyl.medical_enricher import enrich_medical
                result = enrich_medical(self.variables.get("HASLO_GLOWNE", ""), self._s1_full)
                ctx = result.get("context_block", "")
                self.variables["YMYL_CONTEXT"] = ctx
                return ctx
        except Exception as e:
            print(f"[YMYL] Enrichment error: {e}")
        return ""

    def _generate_variants(self) -> dict:
        """Generate search variants via existing search_variants module."""
        keyword = self.variables.get("HASLO_GLOWNE", "")
        try:
            from src.article_pipeline.search_variants import generate_search_variants
            result = generate_search_variants(keyword)
            # Normalize structure for brief_compiler
            mf = result.get("mention_forms", {})
            return {
                "peryfrazy": result.get("peryfrazy", []),
                "warianty_potoczne": result.get("warianty_potoczne", []),
                "warianty_formalne": result.get("warianty_formalne", []),
                "named_forms": [mf.get("named", keyword)] if isinstance(mf.get("named"), str) else mf.get("named", [keyword]),
                "nominal_forms": mf.get("nominal", []),
                "pronominal_cues": mf.get("pronominal", []),
                "mention_forms": mf,
            }
        except Exception as e:
            print(f"[VARIANTS] Error: {e}")
            return {"peryfrazy": [], "named_forms": [keyword]}

    def _determine_h2_count(self) -> int:
        """Determine optimal H2 count from 4 signals."""
        import statistics

        target_length = int(self.variables.get("DLUGOSC_CEL", 800) or 800)

        # Signal 1: Median H2 count from SERP competitors
        serp_h2_counts = self._s1_full.get("serp_h2_counts", [])
        sig1 = int(statistics.median(serp_h2_counts)) if serp_h2_counts else 4

        # Signal 2: Strong H2 candidates (must_have + high_priority)
        h2_candidates = self._s1_full.get("h2_scored_candidates", {})
        if isinstance(h2_candidates, dict):
            strong = (
                len(h2_candidates.get("must_have", []))
                + len(h2_candidates.get("high_priority", []))
            )
        else:
            strong = len(h2_candidates) if isinstance(h2_candidates, list) else 0
        sig2 = max(4, strong)

        # Signal 3: Entity coverage needs (1 section per 3 entities)
        must_cover = self.variables.get("_must_cover", [])
        sig3 = max(4, -(-len(must_cover) // 3))  # ceil division

        # Signal 4: Length hard limit (max 1 section per 250 words)
        sig4 = max(4, target_length // 250)

        # Result: median of signals 1-3, clamped by signal 4
        # Min 4 H2 sections (intro + 4 sections + FAQ is the minimum structure)
        base = int(statistics.median([sig1, sig2, sig3]))
        return max(4, min(base, sig4, 8))

    def _generate_h2_plan(self) -> dict:
        """Generate H2 plan via Sonnet."""
        keyword = self.variables.get("HASLO_GLOWNE", "")
        target_length = int(self.variables.get("DLUGOSC_CEL", 800) or 800)

        # Determine H2 count dynamically from 4 signals
        h2_count = self._determine_h2_count()
        faq_count = max(3, min(7, 4 + len(self.variables.get("_paa_unanswered", []))))

        # Scored H2 candidates from S1
        h2_candidates = self._s1_full.get("h2_scored_candidates", {})
        all_candidates = (
            h2_candidates.get("must_have", []) +
            h2_candidates.get("high_priority", []) +
            h2_candidates.get("optional", [])
        )
        # Also try flat list
        if not all_candidates and isinstance(h2_candidates, list):
            all_candidates = h2_candidates

        scored = json.dumps(all_candidates[:15], ensure_ascii=False) if all_candidates else "[]"

        must_cover = json.dumps(
            self.variables.get("_must_cover", [])[:12], ensure_ascii=False
        )

        paa = self.variables.get("_paa_unanswered", []) + self.variables.get("_paa_standard", [])
        paa_str = "\n".join(f"- {q}" for q in paa[:10])

        # Use user-provided H2 structure if available
        if self._h2_keywords:
            return {
                "h2_plan": self._h2_keywords,
                "faq": paa[:faq_count],
                "h1_suggestion": f"{keyword} - kompletny przewodnik",
            }

        prompt = H2_PLAN_USER.format(
            keyword=keyword,
            scored_h2=scored,
            must_cover=must_cover,
            paa_questions=paa_str,
            h2_count=h2_count,
            faq_count=faq_count,
        )

        try:
            response = self._llm_call(
                system=H2_PLAN_SYSTEM,
                user=prompt,
                max_tokens=2000,
                label="h2_plan",
                temperature=0.3,
            )
            parsed = _safe_json_parse(response)
            if parsed and "h2_plan" in parsed:
                return parsed
        except Exception:
            pass

        # Fallback
        fallback_h2 = []
        for c in all_candidates[:h2_count]:
            if isinstance(c, dict):
                fallback_h2.append(c.get("text", c.get("h2", str(c))))
            else:
                fallback_h2.append(str(c))

        # If still empty, use _h2_plan_list from variables
        if not fallback_h2:
            fallback_h2 = self.variables.get("_h2_plan_list", [f"Czym jest {keyword}", f"Jak dziala {keyword}"])

        return {
            "h2_plan": fallback_h2,
            "faq": paa[:faq_count],
            "h1_suggestion": f"{keyword} - kompletny przewodnik",
        }
