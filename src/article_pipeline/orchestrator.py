"""
Article Pipeline Orchestrator — BRAJEN_PROMPTS_v1.0
Drives the full article generation workflow:
1. Pre-Batch (entity/phrase placement map)
2. Batch 0 (H1 + intro)
3. Batch 1..N (H2 sections)
4. Batch FAQ
5. Post-Processing validation
"""
import json
import re
from typing import Generator

from src.common.llm import claude_call
from src.article_pipeline.prompts import (
    SYSTEM_PROMPT,
    ARTICLE_WRITER_PROMPT,
    H2_PLAN_SYSTEM,
    H2_PLAN_PROMPT,
    PRE_BATCH_PROMPT,
    BATCH_0_PROMPT,
    BATCH_N_PROMPT,
    BATCH_FAQ_PROMPT,
    POST_PROCESSING_PROMPT,
    FORBIDDEN_PHRASES,
    DISCLAIMERS,
)
from src.article_pipeline.variables import extract_global_variables, fill_template, format_ngrams_for_section
from src.article_pipeline.keyword_tracker import KeywordTracker
from src.article_pipeline.validators import (
    validate_batch,
    validate_global,
    check_forbidden_phrases,
)
from src.article_pipeline.ymyl_detector import detect_ymyl, get_disclaimer_text
from src.article_pipeline.search_variants import generate_search_variants


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
        return None


def _get_last_sentence(text: str) -> str:
    """Extract last sentence from text."""
    sentences = re.split(r"[.!?]+\s*", text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    return sentences[-1] if sentences else ""


def _hard_facts_values(facts: list) -> list:
    """Extract plain string values from hard facts (handles both str and dict)."""
    return [f.get("value", "") if isinstance(f, dict) else str(f) for f in facts if f]


class ArticleOrchestrator:
    """Orchestrates the full BRAJEN article generation pipeline."""

    def __init__(self, s1_data: dict, engine: str = "claude", model: str = "claude-sonnet-4-6",
                 nw_terms: list = None, h2_keywords: list = None, project_id: str = None):
        # Use LLM-optimized version if available, fallback to full s1_data
        self.s1_data = s1_data.get("_llm_ready") or s1_data
        self._s1_full = s1_data  # full version for panel display
        self.engine = engine
        self.model = model
        self.project_id = project_id
        self.variables = extract_global_variables(s1_data)
        # H2 keywords from user (NW/Surfer phrases required in H2 headings)
        self._h2_keywords = h2_keywords or []
        # NW/Surfer coverage analysis
        from src.article_pipeline.nw_analyzer import analyze_nw_coverage
        self._nw_analysis = analyze_nw_coverage(nw_terms or [], s1_data)
        nw_block = self._nw_analysis.get("prompt_block", "")
        self.variables["NW_LUKI"] = nw_block
        if self._nw_analysis.get("stats", {}).get("total", 0) > 0:
            print(f"[NW] Coverage analysis: {self._nw_analysis['stats']}")
        self.pre_batch_map = None
        self.batch_texts = []
        self.bridge_sentences = []
        self.full_article = ""
        self.validation_result = None
        self.ymyl_result = None
        self.search_variants_result = None
        # Keyword budget tracker (in-memory + Firestore write-only for panel)
        self.keyword_tracker = KeywordTracker(
            main_keyword=self.variables.get("HASLO_GLOWNE", ""),
            ngrams=self.variables.get("_ngrams", []),
            extended_ngrams=(self.variables.get("_ngrams_full", [])
                             [len(self.variables.get("_ngrams", [])):]),  # extended only
            total_batches=max(3, len(self.variables.get("_h2_plan_list", [])) + 2),
            project_id=project_id,
        )
        # Logging for "Dane wsadowe" panel tab
        self.prompt_log = []   # [{label, system, user}]
        self.input_variables = {}  # snapshot after all variables are ready

    def _llm_call(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000, label: str = "") -> str:
        """Make LLM call with the configured engine. Logs prompt for Dane wsadowe tab."""
        text, usage = claude_call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.model,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        # Log prompt for panel
        if label:
            self.prompt_log.append({
                "label": label,
                "system": system_prompt[:2000] + ("..." if len(system_prompt) > 2000 else ""),
                "user": user_prompt[:3000] + ("..." if len(user_prompt) > 3000 else ""),
                "tokens_out": len(text.split()),
            })
        return text

    def _calc_faq_count(self, target_h2: int, must_cover: list,
                        paa_priority: list, paa_standard: list,
                        candidates: list) -> int:
        """
        Dynamic FAQ count: base 4, increases if phrase/entity coverage is low.

        Logic:
        - Each H2 section can realistically cover ~2-3 entities and ~3-5 n-grams
        - If we have more entities/n-grams than H2 sections can absorb, FAQ acts as overflow
        - PAA priority questions are always included
        - Range: 4-10
        """
        base = 4

        # 1. PAA priority always included
        paa_bonus = max(0, len(paa_priority) - base)  # if >4 priority PAA, add extra

        # 2. Entity coverage pressure
        entity_capacity = target_h2 * 3  # each H2 covers ~3 entities
        entity_overflow = max(0, len(must_cover) - entity_capacity)
        entity_bonus = min(2, entity_overflow // 2)  # +1 FAQ per 2 uncovered entities

        # 3. N-gram coverage pressure
        ngrams = self.variables.get("_ngrams", [])
        total_ngrams = len(ngrams)
        ngram_capacity = target_h2 * 5  # each H2 can weave ~5 n-grams
        ngram_overflow = max(0, total_ngrams - ngram_capacity)
        ngram_bonus = min(2, ngram_overflow // 4)  # +1 FAQ per 4 uncovered n-grams

        # 4. Scored H2 candidates that didn't make it into sections
        # These represent topics that should be covered somewhere
        rejected_candidates = max(0, len([c for c in candidates if (c.get("score") or 0) >= 0.20]) - target_h2)
        rejected_bonus = min(2, rejected_candidates // 2)

        faq_count = base + paa_bonus + entity_bonus + ngram_bonus + rejected_bonus

        # Clamp to 4-10
        faq_count = max(4, min(10, faq_count))

        if faq_count > base:
            reasons = []
            if paa_bonus: reasons.append(f"PAA+{paa_bonus}")
            if entity_bonus: reasons.append(f"entities+{entity_bonus}")
            if ngram_bonus: reasons.append(f"ngrams+{ngram_bonus}")
            if rejected_bonus: reasons.append(f"rejected_h2+{rejected_bonus}")
            print(f"[H2_PLAN] FAQ count: {faq_count} (base {base} + {', '.join(reasons)})")
        else:
            print(f"[H2_PLAN] FAQ count: {faq_count} (base)")

        return faq_count

    def run_ymyl_detection(self) -> dict:
        """Detect YMYL category, then enrich with legal/medical sources."""
        keyword = self.variables.get("HASLO_GLOWNE", "")
        self.ymyl_result = detect_ymyl(keyword)
        category = self.ymyl_result.get("category", "none")
        self.variables["YMYL_KLASYFIKACJA"] = category
        self.variables["YMYL_CONTEXT"] = ""  # default empty

        if category == "prawo":
            try:
                from src.ymyl.legal_enricher import get_legal_context
                legal = get_legal_context(keyword)
                self.ymyl_result["legal"] = legal
                self.variables["YMYL_CONTEXT"] = legal.get("prompt_block", "")
                print(f"[YMYL] ⚖️ Legal context: {legal.get('status')} — {len(legal.get('judgments', []))} orzeczeń")
            except Exception as e:
                print(f"[YMYL] ⚠️ Legal enricher error: {e}")

        elif category == "zdrowie":
            try:
                from src.ymyl.medical_enricher import get_medical_context
                medical = get_medical_context(keyword)
                self.ymyl_result["medical"] = medical
                self.variables["YMYL_CONTEXT"] = medical.get("prompt_block", "")
                print(f"[YMYL] 🏥 Medical context: {medical.get('status')} — sources: {medical.get('sources_used', [])}")
            except Exception as e:
                print(f"[YMYL] ⚠️ Medical enricher error: {e}")

        return self.ymyl_result

    def run_search_variants(self) -> dict:
        """Generate search variants and update variables."""
        keyword = self.variables.get("HASLO_GLOWNE", "")
        ngrams = self.variables.get("_ngrams", [])
        secondary = [ng.get("ngram", "") for ng in ngrams[:10]]
        self.search_variants_result = generate_search_variants(keyword, secondary)

        self.variables["PERYFRAZY"] = json.dumps(
            self.search_variants_result.get("peryfrazy", []), ensure_ascii=False
        )
        self.variables["PERYFRAZY_ALL"] = self.variables["PERYFRAZY"]
        self.variables["WARIANTY_POTOCZNE"] = json.dumps(
            self.search_variants_result.get("warianty_potoczne", []), ensure_ascii=False
        )
        self.variables["WARIANTY_FORMALNE"] = json.dumps(
            self.search_variants_result.get("warianty_formalne", []), ensure_ascii=False
        )
        return self.search_variants_result

    def run_h2_plan(self) -> list:
        """
        Step 2.5: Generate H2 article plan using Claude — v2.0.
        Uses structured XML prompt with explicit JSON schema, selection criteria,
        hard constraints, and self-check.
        Updates _h2_plan_list, PLAN_ARTYKULU, PLAN_H2, and FAQ variables.
        """
        import json

        s1 = self.s1_data
        keyword = self.variables.get("HASLO_GLOWNE", "")

        # ── Scored H2 candidates ──
        h2_scored = s1.get("h2_scored_candidates") or {}
        candidates = (
            (h2_scored.get("must_have") or [])
            + (h2_scored.get("high_priority") or [])
            + (h2_scored.get("optional") or [])
        )
        scored_h2_json = json.dumps(
            [{"text": c.get("text"), "score": c.get("score"), "reason": c.get("reason")}
             for c in candidates[:20]],
            ensure_ascii=False, indent=2
        )

        # ── Entities ──
        entity_seo = s1.get("entity_seo") or {}
        must_cover = entity_seo.get("must_cover_concepts") or []
        if not must_cover:
            must_cover = self.variables.get("_must_cover", [])

        entity_salience_raw = entity_seo.get("entity_salience") or []
        entity_salience = [
            {"entity": e.get("entity_text") or e.get("entity", ""),
             "salience": e.get("salience_score") or e.get("salience", 0),
             "type": e.get("type", "")}
            for e in entity_salience_raw[:12]
            if (e.get("salience_score") or e.get("salience", 0)) > 0.1
        ]

        # ── Hard facts (extract values only for prompt) ──
        hard_facts = _hard_facts_values(self.variables.get("_hard_facts", []))

        # ── PAA: priority = unanswered, standard = answered ──
        paa_priority = self.variables.get("_paa_unanswered", [])
        paa_standard = self.variables.get("_paa_standard", [])

        # ── H2 keywords (from NW/Surfer or user-provided h2_structure) ──
        h2_keywords = getattr(self, "_h2_keywords", []) or []

        # ── Determine target H2 count ──
        # Base on target article length: ~250 words per H2 section + intro + FAQ
        target_length = int(self.variables.get("DLUGOSC_CEL", "2000") or "2000")
        intro_words = int(self.variables.get("DLUGOSC_INTRO", "180") or "180")
        faq_est_words = 400  # ~80 words x 5 questions
        h2_words_available = target_length - intro_words - faq_est_words
        target_h2_by_length = max(4, h2_words_available // 250)

        # Also consider candidate count (don't ask for more than available + some gen)
        candidate_count = len([c for c in candidates if (c.get("score") or 0) >= 0.20])
        target_h2_by_candidates = max(candidate_count, 5)  # at least 5, or candidates

        # Take the minimum of both, clamped 5-10
        target_h2 = min(target_h2_by_length, target_h2_by_candidates)
        target_h2 = max(5, min(10, target_h2))
        print(f"[H2_PLAN] Target H2: {target_h2} (by_length={target_h2_by_length}, by_candidates={target_h2_by_candidates})")

        # ── FAQ count: base 4, scale up if many uncovered phrases/entities ──
        faq_count = self._calc_faq_count(
            target_h2=target_h2,
            must_cover=must_cover,
            paa_priority=paa_priority,
            paa_standard=paa_standard,
            candidates=candidates,
        )

        # ── Build prompt variables ──
        prompt_vars = {
            "HASLO_GLOWNE": keyword,
            "LICZBA_H2": str(target_h2),
            "LICZBA_FAQ": str(faq_count),
            "SCORED_H2_JSON": scored_h2_json,
            "MUST_COVER_ENTITIES_JSON": json.dumps(must_cover[:15], ensure_ascii=False),
            "ENTITY_SALIENCE_JSON": json.dumps(entity_salience, ensure_ascii=False),
            "HARD_FACTS_JSON": json.dumps(hard_facts[:15], ensure_ascii=False),
            "PAA_PRIORITY_JSON": json.dumps(paa_priority[:8], ensure_ascii=False),
            "PAA_STANDARD_JSON": json.dumps(paa_standard[:10], ensure_ascii=False),
            "H2_KEYWORDS_JSON": json.dumps(h2_keywords, ensure_ascii=False),
        }

        user = fill_template(H2_PLAN_PROMPT, prompt_vars)
        response = self._llm_call(
            system_prompt=H2_PLAN_SYSTEM,
            user_prompt=user,
            max_tokens=3000,
            label="h2_plan"
        )

        # ── Parse v2.0 response ──
        h2_plan = []
        faq_items = []
        coverage_check = {}
        try:
            text = response.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            # Find JSON boundaries
            first_brace = text.find("{")
            last_brace = text.rfind("}")
            if first_brace != -1 and last_brace != -1:
                text = text[first_brace:last_brace + 1]
            parsed = json.loads(text.strip())

            # Extract sections → h2_plan
            sections = parsed.get("sections", [])
            if sections:
                h2_plan = [s["h2"] for s in sections if s.get("h2")]
                self._h2_plan_full = sections  # full section objects for panel
            else:
                # Fallback: try old format
                h2_plan = [h["heading"] for h in parsed.get("h2_plan", []) if h.get("heading")]
                self._h2_plan_full = parsed.get("h2_plan", [])

            # Extract FAQ
            faq_items = parsed.get("faq", [])
            self._faq_plan = faq_items

            # Coverage check
            coverage_check = parsed.get("coverage_check", {})
            if coverage_check:
                uncovered = coverage_check.get("uncovered_entities", [])
                if uncovered:
                    print(f"[H2_PLAN] ⚠️ Uncovered entities: {uncovered}")
                unused_kw = coverage_check.get("unused_h2_keywords", [])
                if unused_kw:
                    print(f"[H2_PLAN] ⚠️ Unused h2_keywords: {unused_kw}")

            print(f"[H2_PLAN] ✅ v2.0 generated {len(h2_plan)} sections + {len(faq_items)} FAQ")
        except Exception as e:
            print(f"[H2_PLAN] ⚠️ Parse error: {e} — falling back to scored candidates")
            h2_plan = [c.get("text") for c in candidates[:target_h2] if c.get("text")]

        if not h2_plan:
            kw = keyword or "Temat"
            h2_plan = [f"Czym jest {kw}", f"Jak działa {kw}", f"Konsekwencje: {kw}", f"FAQ: {kw}"]

        # ── Update variables ──
        h2_plan = h2_plan[:target_h2]
        self.variables["_h2_plan_list"] = h2_plan
        self.variables["PLAN_ARTYKULU"] = "\n".join(f"{i+1}. {h}" for i, h in enumerate(h2_plan))
        self.variables["PLAN_H2"] = json.dumps(h2_plan, ensure_ascii=False)
        self.variables["LICZBA_H2"] = str(len(h2_plan))

        # ── FAQ questions from plan → merge into PAA ──
        if faq_items:
            faq_questions = [f.get("question", "") for f in faq_items if f.get("question")]
            # Split into priority and standard based on source
            paa_from_plan = [f.get("question") for f in faq_items
                             if f.get("source") == "paa_priority" and f.get("question")]
            other_faq = [f.get("question") for f in faq_items
                         if f.get("source") != "paa_priority" and f.get("question")]

            existing_paa = self.variables.get("_paa_unanswered", [])
            merged_priority = list(dict.fromkeys(paa_from_plan + existing_paa))
            self.variables["PAA_BEZ_ODPOWIEDZI"] = json.dumps(merged_priority, ensure_ascii=False)
            self.variables["_paa_unanswered"] = merged_priority

            existing_std = self.variables.get("_paa_standard", [])
            merged_std = list(dict.fromkeys(other_faq + existing_std))
            self.variables["PAA_STANDARDOWE"] = json.dumps(merged_std, ensure_ascii=False)
            self.variables["_paa_standard"] = merged_std

        # Store coverage for panel display
        self._h2_coverage_check = coverage_check

        return h2_plan

    def run_pre_batch(self) -> dict:
        """
        Step 1: Generate entity/phrase placement map.
        Returns JSON map for batch-level phrase assignment.
        """
        system = fill_template(SYSTEM_PROMPT, self.variables)
        user = fill_template(PRE_BATCH_PROMPT, self.variables)

        response = self._llm_call(system, user, max_tokens=3000, label="pre_batch")
        parsed = _safe_json_parse(response)

        if not parsed:
            print("[ORCHESTRATOR] Pre-batch JSON parse failed, using fallback")
            parsed = self._generate_fallback_pre_batch()

        self.pre_batch_map = parsed
        return parsed

    def _generate_fallback_pre_batch(self) -> dict:
        """Generate minimal pre-batch map when LLM fails."""
        h2_plan = self.variables.get("_h2_plan_list", [])
        ngrams = self.variables.get("_ngrams", [])
        encje = json.loads(self.variables.get("ENCJE_KRYTYCZNE", "[]"))

        batches = {}
        batches["batch_0"] = {
            "encje_obowiazkowe": encje[:3],
            "ngramy": [ng.get("ngram", "") for ng in ngrams[:5]],
            "lancuchy": [],
            "peryfrazy": [],
            "hard_facts_do_uzycia": _hard_facts_values(self.variables.get("_hard_facts", [])[:3]),
        }

        ngrams_per_batch = max(1, len(ngrams) // max(1, len(h2_plan)))
        for i, h2 in enumerate(h2_plan):
            start = i * ngrams_per_batch
            batch_ngrams = [ng.get("ngram", "") for ng in ngrams[start : start + ngrams_per_batch]]
            batches[f"batch_{i + 1}"] = {
                "encje_obowiazkowe": [self.variables["ENCJA_GLOWNA"]] + encje[i : i + 2],
                "ngramy": batch_ngrams,
                "lancuchy": [],
                "peryfrazy": [],
                "hard_facts_do_uzycia": [],
            }

        batches["batch_faq"] = {
            "pytania_priorytetowe": self.variables.get("_paa_unanswered", []),
            "pytania_standardowe": self.variables.get("_paa_standard", [])[:5],
            "ngramy": [ng.get("ngram", "") for ng in ngrams[-3:]],
        }

        return {
            "hard_facts": self.variables.get("_hard_facts", []),
            "paa_bez_odpowiedzi": self.variables.get("_paa_unanswered", []),
            "related_searches_brands": self.variables.get("_brands", []),
            "batches": batches,
        }

    def run_batch_0(self) -> str:
        """
        Step 2: Generate H1 + intro paragraph (v2 — AI Overview strategy).
        """
        pre = self.pre_batch_map or {}
        batch_0_data = (pre.get("batches") or {}).get("batch_0", {})

        # Hard facts for batch 0: from pre-batch allocation or global
        hard_facts_b0 = batch_0_data.get("hard_facts_do_uzycia", [])
        if not hard_facts_b0:
            hard_facts_b0 = _hard_facts_values(self.variables.get("_hard_facts", [])[:5])

        batch_vars = {
            **self.variables,
            "HARD_FACTS_BATCH_0_JSON": json.dumps(hard_facts_b0, ensure_ascii=False),
        }

        system = fill_template(SYSTEM_PROMPT, batch_vars)
        user = fill_template(BATCH_0_PROMPT, batch_vars)

        text = self._llm_call(system, user, max_tokens=2000, label="batch_0")

        # Validate
        issues = check_forbidden_phrases(text)
        if issues:
            print(f"[ORCHESTRATOR] Batch 0: {len(issues)} forbidden phrases, retrying...")
            retry_prompt = user + f"\n\nUWAGA: W poprzedniej wersji wykryto zakazane frazy: {', '.join(issues)}. Przepisz bez nich."
            text = self._llm_call(system, retry_prompt, max_tokens=2000)

        self.batch_texts.append(text)
        self.bridge_sentences.append(_get_last_sentence(text))

        # Update phrase budget after batch 0
        self.keyword_tracker.update_after_batch(text, batch_label="batch_0")

        # Extract H1 from batch_0 output for use in ARTICLE_WRITER_PROMPT
        h1_match = re.match(r"#\s+(.+)", text.strip())
        if h1_match:
            self.variables["H1"] = h1_match.group(1).strip()

        return text

    def run_batch_n(self, n: int, section_name: str, h2_heading: str) -> str:
        """
        Step 3: Generate H2 section.
        """
        pre = self.pre_batch_map or {}
        batch_data = (pre.get("batches") or {}).get(f"batch_{n}", {})
        target_length = self.variables.get("_target_length", 2000)
        h2_count = len(self.variables.get("_h2_plan_list", []))
        # Distribute words: subtract intro, divide rest among H2s
        intro_words = int(self.variables.get("DLUGOSC_INTRO", "180") or "180")
        section_length = max(200, (target_length - intro_words) // max(1, h2_count))

        # Get section-specific data from H2 plan (v2.0)
        h2_plan_full = getattr(self, "_h2_plan_full", [])
        section_plan = h2_plan_full[n - 1] if n - 1 < len(h2_plan_full) and isinstance(h2_plan_full, list) else {}
        if isinstance(section_plan, dict):
            section_hard_facts = section_plan.get("hard_facts", [])
            section_entities = section_plan.get("entities", [])
        else:
            section_hard_facts = []
            section_entities = []

        # Merge pre-batch entities with plan entities
        pre_batch_entities = batch_data.get("encje_obowiazkowe", [])
        merged_entities = list(dict.fromkeys(pre_batch_entities + section_entities))

        # Merge hard facts
        pre_batch_hf = batch_data.get("hard_facts_do_uzycia", [])
        merged_hf = list(dict.fromkeys(pre_batch_hf + section_hard_facts))

        # Format ngrams with remaining budget from in-memory tracker
        assigned_ngrams = batch_data.get("ngramy", [])
        ngrams_formatted = self.keyword_tracker.format_phrases_for_prompt(assigned_ngrams, h2_heading=h2_heading)

        batch_vars = {
            **self.variables,
            "N": str(n),
            "NAZWA_SEKCJI": section_name,
            "NAGLOWEK_H2": h2_heading,
            "OSTATNIE_ZDANIE_POPRZEDNIEGO_BATCHA": self.bridge_sentences[-1] if self.bridge_sentences else "",
            "POPRZEDNIE_ZDANIA_POMOSTOWE": json.dumps(self.bridge_sentences, ensure_ascii=False),
            "ENCJE_BATCH_N": json.dumps(merged_entities, ensure_ascii=False),
            "NGRAMY_BATCH_N": ngrams_formatted,
            "MAIN_KW_INSTRUCTION": self.keyword_tracker.format_main_kw_instruction(),
            "TRIPLETS_BATCH_N": json.dumps(batch_data.get("lancuchy", []), ensure_ascii=False),
            "HARD_FACTS_BATCH_N": json.dumps(merged_hf, ensure_ascii=False),
            "PERYFRAZY_BATCH_N": json.dumps(
                batch_data.get("peryfrazy", []) or
                json.loads(self.variables.get("PERYFRAZY", "[]"))[:3],
                ensure_ascii=False
            ),
            "DLUGOSC_SEKCJI": str(section_length),
            "MIN_PERYFRAZ": "2",
            "INTENCJA_TRANSAKCYJNA_AKTYWNA": "false",
            "FRAZY_TRANSAKCYJNE": "[]",
        }

        system = fill_template(SYSTEM_PROMPT, batch_vars)
        user = fill_template(BATCH_N_PROMPT, batch_vars)

        text = self._llm_call(system, user, max_tokens=3000, label=f"batch_{n}")

        # Validate
        issues = check_forbidden_phrases(text)
        if issues:
            print(f"[ORCHESTRATOR] Batch {n}: {len(issues)} forbidden phrases, retrying...")
            retry_prompt = user + f"\n\nUWAGA: Przepisz bez zakazanych fraz: {', '.join(issues)}"
            text = self._llm_call(system, retry_prompt, max_tokens=3000)

        self.batch_texts.append(text)
        self.bridge_sentences.append(_get_last_sentence(text))

        # Update phrase budget after each H2 section
        self.keyword_tracker.update_after_batch(text, batch_label=f"batch_{n}")

        return text

    def run_batch_faq(self) -> str:
        """
        Step 4: Generate FAQ section.
        """
        pre = self.pre_batch_map or {}
        faq_data = (pre.get("batches") or {}).get("batch_faq", {})
        ymyl = self.variables.get("YMYL_KLASYFIKACJA", "none")
        disclaimer = DISCLAIMERS.get(ymyl, "")
        pubmed = self.variables.get("PUBMED_CYTAT", "")
        if pubmed and ymyl in ("zdrowie",):
            disclaimer += f" (źródło: {pubmed})"

        related_as_questions = []
        for rs in self.variables.get("_related_searches", [])[:5]:
            text = rs if isinstance(rs, str) else str(rs)
            if not text.endswith("?"):
                text = f"Czym jest {text}?" if len(text.split()) <= 3 else f"{text}?"
            related_as_questions.append(text)

        batch_vars = {
            **self.variables,
            "PAA_STANDARDOWE": json.dumps(faq_data.get("pytania_standardowe", self.variables.get("_paa_standard", [])), ensure_ascii=False),
            "RELATED_AS_QUESTIONS": json.dumps(related_as_questions, ensure_ascii=False),
            "NGRAMY_FAQ": "\n".join(faq_data.get("ngramy", [])),
            "HARD_FACTS_FAQ": json.dumps(_hard_facts_values(self.variables.get("_hard_facts", [])), ensure_ascii=False),
            "DISCLAIMER_SECTION": disclaimer if disclaimer else "Brak wymagań YMYL — pomiń disclaimer.",
        }

        system = fill_template(SYSTEM_PROMPT, batch_vars)
        user = fill_template(BATCH_FAQ_PROMPT, batch_vars)

        text = self._llm_call(system, user, max_tokens=3000, label="batch_faq")
        self.batch_texts.append(text)
        return text

    def assemble_article(self) -> str:
        """Assemble all batches into final article."""
        self.full_article = "\n\n".join(self.batch_texts)
        return self.full_article

    def run_coverage_check(self) -> dict:
        """
        Porównuje tekst artykułu z zakresami freq_min/freq_max z S1 ngrams.
        Zwraca raport: missing, under, over, ok.
        Bez LLM — czysto lokalne liczenie.
        """
        import re as _re

        article = self.full_article.lower()
        if not article:
            return {}

        s1_full = self._s1_full
        ngrams = (s1_full.get("ngrams") or []) + (s1_full.get("extended_terms") or [])

        missing, under, over, ok = [], [], [], []

        for ng in ngrams:
            term = (ng.get("ngram") or ng.get("text") or "").lower().strip()
            if not term or len(term) < 3:
                continue
            freq_min = ng.get("freq_min", 1)
            freq_max = ng.get("freq_max", 99)
            weight   = ng.get("weight", 0)

            actual = len(_re.findall(_re.escape(term), article))

            entry = {
                "term":   ng.get("ngram") or ng.get("text"),
                "actual": actual,
                "min":    freq_min,
                "max":    freq_max,
                "weight": round(weight, 3),
            }

            if actual == 0 and freq_min >= 1:
                missing.append(entry)
            elif 0 < actual < freq_min:
                under.append(entry)
            elif freq_max and actual > freq_max:
                over.append(entry)
            else:
                ok.append(entry)

        missing.sort(key=lambda x: x["weight"], reverse=True)
        under.sort(key=lambda x: x["min"] - x["actual"], reverse=True)
        over.sort(key=lambda x: x["actual"] - x["max"], reverse=True)

        result = {
            "missing": missing,
            "under":   under,
            "over":    over,
            "ok":      ok,
            "stats": {
                "total":        len(ngrams),
                "missing":      len(missing),
                "under":        len(under),
                "over":         len(over),
                "ok":           len(ok),
                "coverage_pct": round(len(ok) / max(len(ngrams), 1) * 100),
            }
        }
        self.coverage_result = result
        print(f"[COVERAGE] {result['stats']}")
        return result

    def run_post_processing(self) -> dict:
        """
        Step 5: Validate the full article.
        Returns validation result with score.
        """
        if not self.full_article:
            self.assemble_article()

        post_vars = {
            **self.variables,
            "PELNY_TEKST_ARTYKULU": self.full_article,
        }

        system = "Jesteś walidatorem tekstu SEO. Analizujesz artykuły pod kątem zgodności z wytycznymi."
        user = fill_template(POST_PROCESSING_PROMPT, post_vars)

        response = self._llm_call(system, user, max_tokens=3000)
        parsed = _safe_json_parse(response)

        if parsed:
            self.validation_result = parsed
        else:
            # Local validation fallback
            self.validation_result = validate_global(self.full_article, self.variables)

        return self.validation_result

    def run_full_pipeline(self) -> Generator[dict, None, None]:
        """
        Run the complete article generation pipeline with SSE-compatible events.
        Yields status events for each step.
        """
        # H2 plan is unknown before Claude generates it — estimate 6 sections, update after
        h2_count_est = 6
        # Steps: YMYL + variants + H2 plan + pre-batch + batch0 + H2s + FAQ + post-processing
        total_steps = 6 + h2_count_est

        # Step 1: YMYL detection
        yield {"event": "step_start", "step": 1, "total": total_steps, "label": "YMYL: detekcja kategorii"}
        ymyl = self.run_ymyl_detection()
        yield {"event": "step_done", "step": 1, "data": {"ymyl": ymyl}}

        # Step 2: Search variants
        yield {"event": "step_start", "step": 2, "total": total_steps, "label": "Warianty wyszukiwania"}
        variants = self.run_search_variants()
        yield {"event": "step_done", "step": 2, "data": {"variants_count": sum(len(v) for v in variants.values())}}

        # Step 3: H2 plan — Claude generates article structure based on scored candidates
        yield {"event": "step_start", "step": 3, "total": total_steps, "label": "Plan H2: struktura artykułu"}
        h2_plan = self.run_h2_plan()
        h2_count = len(h2_plan)
        total_steps = 6 + h2_count  # recalculate with actual H2 count
        yield {"event": "step_done", "step": 3, "data": {
            "h2_plan": getattr(self, "_h2_plan_full", h2_plan),
            "faq_plan": getattr(self, "_faq_plan", []),
            "coverage_check": getattr(self, "_h2_coverage_check", {}),
            "h2_count": h2_count,
        }}

        # Build PLAN_FAQ from faq_plan or PAA questions
        faq_plan = getattr(self, "_faq_plan", [])
        if faq_plan:
            faq_questions = [f.get("question", "") for f in faq_plan if f.get("question")]
        else:
            faq_questions = (
                self.variables.get("_paa_unanswered", [])[:4]
                + self.variables.get("_paa_standard", [])[:3]
            )
        self.variables["PLAN_FAQ"] = "\n".join(f"- {q}" for q in faq_questions)

        # Populate JSON data placeholders for ARTICLE_WRITER_PROMPT
        self.variables["ENCJE_KRYTYCZNE_JSON"] = self.variables.get("ENCJE_KRYTYCZNE", "[]")
        self.variables["NGRAMY_Z_LIMITAMI_JSON"] = self.variables.get("NGRAMY_Z_LIMITAMI", "[]")
        self.variables["LANCUCHY_KAUZALNE_JSON"] = self.variables.get("LANCUCHY_KAUZALNE", "[]")
        self.variables["HARD_FACTS_JSON"] = json.dumps(
            _hard_facts_values(self.variables.get("_hard_facts", [])), ensure_ascii=False
        )
        self.variables["PERYFRAZY_JSON"] = self.variables.get("PERYFRAZY", "[]")
        self.variables["WARIANTY_POTOCZNE_JSON"] = self.variables.get("WARIANTY_POTOCZNE", "[]")
        # H1 placeholder — will be filled by batch_0, set default for now
        if "H1" not in self.variables:
            kw = self.variables.get("HASLO_GLOWNE", "")
            self.variables["H1"] = f"{kw} — kompletny przewodnik"

        # Snapshot all input variables after H2 plan is ready
        self.input_variables = {k: v for k, v in self.variables.items() if not k.startswith("_")}

        # Step 4: Pre-batch
        yield {"event": "step_start", "step": 4, "total": total_steps, "label": "Pre-Batch: mapa rozmieszczeń"}
        self.run_pre_batch()
        yield {"event": "step_done", "step": 4, "data": {
            "pre_batch_keys": list((self.pre_batch_map or {}).keys()),
            "pre_batch_map": self.pre_batch_map or {},
            "input_variables": self.input_variables,
        }}

        # Step 5: Batch 0
        yield {"event": "step_start", "step": 5, "total": total_steps, "label": "Batch 0: H1 + wstęp"}
        intro = self.run_batch_0()
        yield {"event": "step_done", "step": 5, "data": {
            "text": intro, "word_count": len(intro.split()),
            "keyword_budget": self.keyword_tracker.get_summary(),
        }}

        # Steps 5..N: H2 sections
        h2_plan = self.variables.get("_h2_plan_list", [])
        for i, h2 in enumerate(h2_plan):
            step = 5 + i
            yield {"event": "step_start", "step": step, "total": total_steps, "label": f"Batch {i+1}: {h2[:50]}"}
            section = self.run_batch_n(i + 1, h2, h2)
            yield {"event": "step_done", "step": step, "data": {
                "text": section, "word_count": len(section.split()),
                "keyword_budget": self.keyword_tracker.get_summary(),
            }}

        # FAQ
        faq_step = 5 + h2_count
        yield {"event": "step_start", "step": faq_step, "total": total_steps, "label": "Batch FAQ"}
        faq = self.run_batch_faq()
        yield {"event": "step_done", "step": faq_step, "data": {"text": faq, "word_count": len(faq.split())}}

        # Assemble
        article = self.assemble_article()
        yield {"event": "article_assembled", "data": {
            "full_text": article,
            "total_words": len(article.split()),
            "total_batches": len(self.batch_texts),
        }}

        # Post-processing validation
        yield {"event": "step_start", "step": total_steps, "total": total_steps, "label": "Post-Processing: walidacja"}
        validation = self.run_post_processing()

        # Coverage check — bez LLM, czysto lokalne
        coverage = self.run_coverage_check()

        yield {"event": "step_done", "step": total_steps, "data": {"validation": validation}}

        yield {"event": "complete", "data": {
            "full_text": article,
            "total_words": len(article.split()),
            "validation_score": validation.get("score", 0) if validation else 0,
            "ymyl": self.ymyl_result,
            "prompt_log": self.prompt_log,
            "input_variables": self.input_variables,
            "pre_batch_map": self.pre_batch_map or {},
            "coverage": coverage,
            "keyword_budget": self.keyword_tracker.get_summary(),
            "keyword_reports": self.keyword_tracker.batch_reports,
        }}
