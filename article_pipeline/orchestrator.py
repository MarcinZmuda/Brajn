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
    PRE_BATCH_PROMPT,
    BATCH_0_PROMPT,
    BATCH_N_PROMPT,
    BATCH_FAQ_PROMPT,
    POST_PROCESSING_PROMPT,
    FORBIDDEN_PHRASES,
    DISCLAIMERS,
)
from src.article_pipeline.variables import extract_global_variables, fill_template
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


class ArticleOrchestrator:
    """Orchestrates the full BRAJEN article generation pipeline."""

    def __init__(self, s1_data: dict, engine: str = "claude", model: str = "claude-sonnet-4-6"):
        self.s1_data = s1_data
        self.engine = engine
        self.model = model
        self.variables = extract_global_variables(s1_data)
        self.pre_batch_map = None
        self.batch_texts = []
        self.bridge_sentences = []
        self.full_article = ""
        self.validation_result = None
        self.ymyl_result = None
        self.search_variants_result = None
        self.prompt_log: list[dict] = []  # stores all prompts sent to LLM

    def _llm_call(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000, label: str = "") -> str:
        """Make LLM call with the configured engine and log the prompt."""
        self.prompt_log.append({
            "label": label or f"call_{len(self.prompt_log) + 1}",
            "system": system_prompt,
            "user": user_prompt,
            "max_tokens": max_tokens,
        })
        text, usage = claude_call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.model,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return text

    def run_ymyl_detection(self) -> dict:
        """Detect YMYL category and update variables."""
        keyword = self.variables.get("HASLO_GLOWNE", "")
        self.ymyl_result = detect_ymyl(keyword)
        category = self.ymyl_result.get("category", "none")
        self.variables["YMYL_KLASYFIKACJA"] = category
        if self.ymyl_result.get("is_ymyl"):
            self.variables["PUBMED_CYTAT"] = ""  # placeholder for future PubMed integration
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
            "hard_facts_do_uzycia": self.variables.get("_hard_facts", [])[:3],
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
        Step 2: Generate H1 + intro paragraph.
        """
        pre = self.pre_batch_map or {}
        batch_0_data = (pre.get("batches") or {}).get("batch_0", {})

        batch_vars = {
            **self.variables,
            "ENCJE_BATCH_0": json.dumps(batch_0_data.get("encje_obowiazkowe", []), ensure_ascii=False),
            "PERYFRAZY_BATCH_0": json.dumps(batch_0_data.get("peryfrazy", []), ensure_ascii=False),
            "HARD_FACTS_BATCH_0": json.dumps(batch_0_data.get("hard_facts_do_uzycia", []), ensure_ascii=False),
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
        return text

    def run_batch_n(self, n: int, section_name: str, h2_heading: str) -> str:
        """
        Step 3: Generate H2 section.
        """
        pre = self.pre_batch_map or {}
        batch_data = (pre.get("batches") or {}).get(f"batch_{n}", {})
        target_length = self.variables.get("_target_length", 2000)
        h2_count = len(self.variables.get("_h2_plan_list", []))
        section_length = max(200, target_length // max(1, h2_count + 1))

        batch_vars = {
            **self.variables,
            "N": str(n),
            "NAZWA_SEKCJI": section_name,
            "NAGLOWEK_H2": h2_heading,
            "OSTATNIE_ZDANIE_POPRZEDNIEGO_BATCHA": self.bridge_sentences[-1] if self.bridge_sentences else "",
            "POPRZEDNIE_ZDANIA_POMOSTOWE": json.dumps(self.bridge_sentences, ensure_ascii=False),
            "ENCJE_BATCH_N": json.dumps(batch_data.get("encje_obowiazkowe", []), ensure_ascii=False),
            "NGRAMY_BATCH_N": "\n".join(batch_data.get("ngramy", [])),
            "TRIPLETS_BATCH_N": json.dumps(batch_data.get("lancuchy", []), ensure_ascii=False),
            "HARD_FACTS_BATCH_N": json.dumps(batch_data.get("hard_facts_do_uzycia", []), ensure_ascii=False),
            "PERYFRAZY_BATCH_N": json.dumps(batch_data.get("peryfrazy", []), ensure_ascii=False),
            "DLUGOSC_SEKCJI": str(section_length),
            "LICZBA_AKAPITOW": "3-5",
            "OPIS_STRUKTURY_AKAPITOW": "akapity narracyjne z naturalnym przepływem",
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
            "HARD_FACTS_FAQ": json.dumps(self.variables.get("_hard_facts", []), ensure_ascii=False),
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

        response = self._llm_call(system, user, max_tokens=3000, label="pre_batch")
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
        h2_count = len(self.variables.get("_h2_plan_list", []))
        # Steps: YMYL + variants + pre-batch + batch0 + H2s + FAQ + post-processing
        total_steps = 6 + h2_count

        # Step 1: YMYL detection
        yield {"event": "step_start", "step": 1, "total": total_steps, "label": "YMYL: detekcja kategorii"}
        ymyl = self.run_ymyl_detection()
        yield {"event": "step_done", "step": 1, "data": {"ymyl": ymyl}}

        # Step 2: Search variants
        yield {"event": "step_start", "step": 2, "total": total_steps, "label": "Warianty wyszukiwania"}
        variants = self.run_search_variants()
        yield {"event": "step_done", "step": 2, "data": {"variants_count": sum(len(v) for v in variants.values())}}

        # Step 3: Pre-batch
        yield {"event": "step_start", "step": 3, "total": total_steps, "label": "Pre-Batch: mapa rozmieszczeń"}
        self.run_pre_batch()
        yield {"event": "step_done", "step": 3, "data": {"pre_batch_keys": list((self.pre_batch_map or {}).keys())}}

        # Step 4: Batch 0
        yield {"event": "step_start", "step": 4, "total": total_steps, "label": "Batch 0: H1 + wstęp"}
        intro = self.run_batch_0()
        yield {"event": "step_done", "step": 4, "data": {"text": intro, "word_count": len(intro.split())}}

        # Steps 5..N: H2 sections
        h2_plan = self.variables.get("_h2_plan_list", [])
        for i, h2 in enumerate(h2_plan):
            step = 5 + i
            yield {"event": "step_start", "step": step, "total": total_steps, "label": f"Batch {i+1}: {h2[:50]}"}
            section = self.run_batch_n(i + 1, h2, h2)
            yield {"event": "step_done", "step": step, "data": {"text": section, "word_count": len(section.split())}}

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
        yield {"event": "step_done", "step": total_steps, "data": {"validation": validation}}

        yield {"event": "complete", "data": {
            "full_text": article,
            "total_words": len(article.split()),
            "validation_score": validation.get("score", 0) if validation else 0,
            "ymyl": self.ymyl_result,
            "prompt_log": self.prompt_log,
            "input_variables": {k: v for k, v in self.variables.items() if not k.startswith("_")},
            "pre_batch_map": self.pre_batch_map,
        }}
