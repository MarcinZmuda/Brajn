"""
Keyword Budget Tracker — in-memory phrase frequency control across batches,
with optional Firestore persistence for real-time panel display.

Pipeline (runs before _init_phrase_budget):
0. filter_garbage_ngrams — reject CSS/HTML/non-Polish junk from S1
1. remove_subsumed_basic — remove 1-2 word phrases contained in longer ones
2. cascade_deduct_targets — reduce budgets via inclusion-exclusion
3. deduplicate_keywords — aggressive reduction for phrases nested in MAIN

Counting method:
- Fuzzy regex: each word → prefix (≥75% length, min 4 chars) + \\w*
- "nawilżyć" pattern → \\bnawilż\\w*\\b → matches nawilżeniu, nawilżenia, nawilżone
- Aligns counting with cascade budget logic (same fuzzy matching)

Budget lives in RAM. Firestore is write-only (for panel reads), never blocks generation.
Collection: seo_keyword_budgets/{project_id}
"""
import math
import re
from typing import Optional, List, Dict


BUDGET_COLLECTION = "seo_keyword_budgets"

# ── Prompt cap: max EXTENDED phrases shown per batch ──
_MAX_EXTENDED_PER_BATCH = 12

# ── P0: Garbage n-gram filter patterns ──
_RE_CAMEL_CASE = re.compile(r'[a-z][A-Z]')              # camelCase
_RE_CSS_HYPHEN = re.compile(r'[a-z]+-[a-z]+-')           # css-like-props
_RE_PROG_CHARS = re.compile(r'[{}();=<>:\/\\#@$%^&*|]')  # code/CSS chars
_RE_ALL_ASCII = re.compile(r'^[a-zA-Z0-9\s\-_.]+$')      # purely ASCII (no Polish)
_RE_REPEATED_WORD = re.compile(r'\b(\w+)\s+\1\b', re.IGNORECASE)  # "left left"


def filter_garbage_ngrams(ngrams: list) -> list:
    """Reject n-grams that are CSS/HTML fragments, programming patterns, or non-Polish junk.

    Filters:
    1. camelCase patterns (e.g. "fontSize", "borderRadius")
    2. CSS-hyphenated patterns (e.g. "sizing-border", "font-weight")
    3. Programming chars (braces, semicolons, angle brackets, etc.)
    4. Purely ASCII strings with no Polish characters (likely scraped HTML/CSS)
    5. Duplicate-word phrases (e.g. "left left", "admin admin")
    6. Very short tokens (single char after stripping)

    Polish phrases naturally contain diacritics (ą, ć, ę, ł, ń, ó, ś, ź, ż)
    or common Polish word patterns. Pure ASCII tokens are almost never valid
    Polish SEO phrases.
    """
    _POLISH_DIACRITICS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")

    def _has_polish_chars(text: str) -> bool:
        return bool(set(text) & _POLISH_DIACRITICS)

    # Common Polish stop-words / short words that are valid despite being ASCII
    _POLISH_ASCII_WHITELIST = {
        "jak", "co", "to", "na", "do", "nie", "jest", "w", "i", "z", "o",
        "czy", "dla", "po", "od", "za", "przed", "bez", "przez", "nad",
        "pod", "ile", "kiedy", "gdzie", "jaki", "jaka", "jakie", "ten",
        "ta", "te", "a", "ale", "lub", "ani",
    }

    def _is_garbage(text: str) -> bool:
        if not text or len(text.strip()) < 2:
            return True
        if _RE_CAMEL_CASE.search(text):
            return True
        if _RE_CSS_HYPHEN.search(text):
            return True
        if _RE_PROG_CHARS.search(text):
            return True
        if _RE_REPEATED_WORD.search(text):
            return True
        # Purely ASCII check: must have at least one Polish diacritic
        # OR contain known Polish words
        if _RE_ALL_ASCII.match(text):
            words = text.lower().split()
            if not _has_polish_chars(text):
                # Allow if at least one word is a common Polish word
                if not any(w in _POLISH_ASCII_WHITELIST for w in words):
                    # Allow multi-word phrases where words look like Polish (3+ chars each)
                    if len(words) < 2 or not all(len(w) >= 3 for w in words):
                        return True
        return False

    result = []
    removed = []
    for ng in ngrams:
        text = (ng.get("ngram") or ng.get("text") or "").strip()
        if _is_garbage(text):
            removed.append(text)
        else:
            result.append(ng)

    if removed:
        print(f"[BUDGET] filter_garbage_ngrams: removed {len(removed)} junk phrases: "
              f"{removed[:10]}{'...' if len(removed) > 10 else ''}")
    return result


def _get_db():
    """Get Firestore client, returns None if unavailable."""
    try:
        from src.common.firebase import get_db
        return get_db()
    except ImportError:
        return None


def _compute_main_kw_max(total_batches: int) -> int:
    """Dynamic main keyword max: ~1 per batch, min 4, max 15."""
    return max(4, min(total_batches, 15))


# ── Lemmatization layer (P1 fix) ──

_lemma_cache: Dict[str, str] = {}
_nlp_instance = None
_nlp_load_attempted = False


def _get_nlp():
    """Lazy-load spaCy NLP singleton. Returns None if unavailable."""
    global _nlp_instance, _nlp_load_attempted
    if _nlp_instance is not None:
        return _nlp_instance
    if _nlp_load_attempted:
        return None
    _nlp_load_attempted = True
    try:
        from src.common.nlp_singleton import get_nlp
        _nlp_instance = get_nlp()
        return _nlp_instance
    except Exception as e:
        print(f"[BUDGET] spaCy unavailable, using prefix fallback: {e}")
        return None


def _lemmatize_word(word: str) -> str:
    """Lemmatize a single Polish word. Falls back to lowercase if spaCy unavailable.

    Caches results for performance (~2ms per phrase amortized).
    Handles Polish morphology correctly: wózkiem→wózek, jedząc→jeść, skórze→skóra
    """
    word_lower = word.lower()
    if word_lower in _lemma_cache:
        return _lemma_cache[word_lower]

    nlp = _get_nlp()
    if nlp is not None:
        doc = nlp(word_lower)
        lemma = doc[0].lemma_ if len(doc) > 0 else word_lower
    else:
        lemma = word_lower

    _lemma_cache[word_lower] = lemma
    return lemma


def _lemmatize_phrase(phrase: str) -> List[str]:
    """Lemmatize all words in a phrase. Returns list of lemmas."""
    return [_lemmatize_word(w) for w in phrase.lower().split()]


# ── Fuzzy matching helpers ──

def _common_prefix_len(a: str, b: str) -> int:
    """Return length of common prefix between two strings."""
    n = 0
    for ca, cb in zip(a, b):
        if ca == cb:
            n += 1
        else:
            break
    return n


def _fuzzy_word_match(word_a: str, word_b: str) -> bool:
    """Check if two words are morphological variants.

    P1 fix: Uses spaCy lemmatization as PRIMARY matching (handles ó↔o alternation,
    consonant changes like pisać/piszę, supletivisms like człowiek/ludzie).
    Falls back to prefix heuristic (≥75%, min 4 chars) when spaCy unavailable
    or when lemmas don't match but prefix suggests variant.

    Examples with lemmatization:
        wózkiem ↔ wózek   → both lemmatize to "wózek" ✓
        skórze ↔ skóra    → both lemmatize to "skóra" ✓
        jedząc ↔ jeść     → both lemmatize to "jeść" ✓
        transport ↔ transparentny → different lemmas, prefix too short ✗
    """
    a_lower = word_a.lower()
    b_lower = word_b.lower()
    if a_lower == b_lower:
        return True

    # Primary: lemmatization (handles vowel alternation, supletivisms)
    lemma_a = _lemmatize_word(a_lower)
    lemma_b = _lemmatize_word(b_lower)
    if lemma_a == lemma_b:
        return True

    # Fallback: prefix heuristic for cases spaCy misses
    shorter = min(len(a_lower), len(b_lower))
    if shorter < 4:
        return False
    threshold = max(4, math.ceil(shorter * 0.75))
    return _common_prefix_len(a_lower, b_lower) >= threshold


def _phrase_contains_exact(long_phrase: str, short_phrase: str) -> bool:
    """Check if all words of short_phrase appear EXACTLY in long_phrase.

    Word-boundary: "rok" does NOT match in "wyrok".
    "szampon" ∈ "szampon do suchej skóry" → True
    "skórze" ∈ "nawilżyć skórę głowy" → False (skórze ≠ skórę)
    """
    long_words = long_phrase.lower().split()
    short_words = short_phrase.lower().split()
    if len(short_words) > len(long_words):
        return False
    used = set()
    for sw in short_words:
        matched = False
        for i, lw in enumerate(long_words):
            if i not in used and sw == lw:
                used.add(i)
                matched = True
                break
        if not matched:
            return False
    return True


def _phrase_contains_fuzzy(long_phrase: str, short_phrase: str) -> bool:
    """Check if all words of short_phrase fuzzy-match words in long_phrase.

    Uses _fuzzy_word_match (common prefix ≥75%, min 4 chars).
    "skórze" ∈ "nawilżyć skórę głowy" → True (skórz ≈ skórę)
    """
    long_words = long_phrase.lower().split()
    short_words = short_phrase.lower().split()
    if len(short_words) > len(long_words):
        return False
    used = set()
    for sw in short_words:
        matched = False
        for i, lw in enumerate(long_words):
            if i not in used and _fuzzy_word_match(sw, lw):
                used.add(i)
                matched = True
                break
        if not matched:
            return False
    return True


def _build_fuzzy_pattern(phrase_lower: str) -> re.Pattern:
    """Build regex that matches morphological variants of the phrase.

    Each word → prefix (≥75% length, min 4 chars) + \\w*
    Multi-word: joined with \\s+ (words must be adjacent).

    Examples:
        "nawilżyć"     → \\bnawilż\\w*\\b
        "sucha skóra"  → \\bsuch\\w*\\s+skór\\w*\\b
        "do"           → \\bdo\\b  (short words: exact match)
    """
    words = phrase_lower.split()
    parts = []
    for w in words:
        if len(w) < 4:
            parts.append(re.escape(w))
        else:
            prefix_len = max(4, math.ceil(len(w) * 0.75))
            prefix = w[:prefix_len]
            parts.append(re.escape(prefix) + r'\w*')
    pattern_str = r'\b' + r'\s+'.join(parts) + r'\b'
    return re.compile(pattern_str)


# ── Pre-processing: subsumption + cascade + dedup ──

def remove_subsumed_basic(ngrams: list, main_keyword: str = "") -> list:
    """Remove short (1-2 word) phrases that are fully contained in a longer phrase.

    "szampon" ⊂ "szampon do suchej skóry" → REMOVE "szampon"
    "skórze" ⊂ "sucha skóra głowy" → REMOVE "skórze"

    Only removes phrases with ≤2 words. 3+ word phrases are too specific to remove.
    Uses fuzzy word matching on word boundaries.
    """
    all_phrases = [(ng.get("ngram") or ng.get("text") or "").strip().lower()
                   for ng in ngrams]
    # Also check against main keyword
    if main_keyword:
        all_phrases.append(main_keyword.lower())

    to_remove = set()
    for i, ng in enumerate(ngrams):
        text = (ng.get("ngram") or ng.get("text") or "").strip()
        if not text:
            continue
        words = text.lower().split()
        if len(words) > 2:
            continue  # Only remove 1-2 word phrases

        # Check if this short phrase is contained in any longer phrase
        for j, other in enumerate(all_phrases):
            if i == j:
                continue
            other_words = other.split()
            if len(other_words) <= len(words):
                continue  # Only check against strictly longer phrases
            if _phrase_contains_exact(other, text):
                to_remove.add(i)
                break

    result = [ng for i, ng in enumerate(ngrams) if i not in to_remove]
    removed = len(ngrams) - len(result)
    if removed:
        print(f"[BUDGET] remove_subsumed_basic: removed {removed}/{len(ngrams)} subsumed phrases")
    return result


def clamp_freq_limits(ngrams: list, article_length: int = 2000) -> list:
    """P0: Prevent unnaturally dense repetition from S1 competition data.

    1. freq_min ceiling based on article density: max_reasonable_min = max(1, article_length // 400)
       A 4-gram phrase appearing every 250 words is almost always stuffing.
    2. If freq_min == freq_max (rigid), relax to freq_max = freq_min + ceil(freq_min * 0.3)
       Gives the model flexibility instead of forcing exact count.
    """
    max_reasonable_min = max(1, article_length // 400)  # ~5 for 2000w

    for ng in ngrams:
        text = (ng.get("ngram") or ng.get("text") or "").strip()
        if not text:
            continue
        fmin = ng.get("freq_min", 0)
        fmax = ng.get("freq_max", 0)
        word_count = len(text.split())
        old_min, old_max = fmin, fmax

        # Ceiling on freq_min — stricter for longer phrases (more specific = less repetition)
        phrase_ceiling = max_reasonable_min
        if word_count >= 3:
            phrase_ceiling = max(1, phrase_ceiling // 2)  # 3+ word phrases: even stricter
        if fmin > phrase_ceiling:
            fmin = phrase_ceiling

        # Relax rigid min==max — give model ±30% flexibility
        if fmin > 0 and fmin == fmax:
            fmax = fmin + max(1, math.ceil(fmin * 0.3))

        # Ensure min <= max
        if fmin > fmax:
            fmin = fmax

        if fmin != old_min or fmax != old_max:
            ng["freq_min"] = fmin
            ng["freq_max"] = fmax
            print(f"[BUDGET] clamp_freq: {text} [{old_min},{old_max}] → [{fmin},{fmax}]")

    return ngrams


def cascade_deduct_targets(ngrams: list) -> list:
    """Reduce budgets via inclusion-exclusion.

    If phrase A contains phrase B (fuzzy), then every use of A implicitly
    counts as a use of B. So B's budget should be reduced.

    adj_min = max(0, raw_min − Σ target_min of all children)  [pessimistic — P3 fix]
    adj_max = max(0, raw_max − Σ target_min of all children)
    """
    # Build phrase list with targets
    items = []
    for ng in ngrams:
        text = (ng.get("ngram") or ng.get("text") or "").strip()
        if not text:
            continue
        fmin = ng.get("freq_min", 0)
        fmax = ng.get("freq_max", 0)
        weight = ng.get("weight", 0)
        if fmin == fmax == 0:
            fmin = max(1, int(weight * 5))
            fmax = max(fmin, int(weight * 10))
        items.append({"ng": ng, "text": text.lower(), "fmin": fmin, "fmax": fmax})

    # For each phrase, find all "children" (longer phrases that contain it)
    for i, item in enumerate(items):
        children_fmin_sum = 0
        children_fmax_sum = 0
        for j, other in enumerate(items):
            if i == j:
                continue
            # other is a child of item if other contains item AND other is longer
            if len(other["text"].split()) > len(item["text"].split()):
                if _phrase_contains_fuzzy(other["text"], item["text"]):
                    children_fmin_sum += other["fmin"]
                    children_fmax_sum += other["fmax"]

        if children_fmin_sum > 0:
            old_min, old_max = item["fmin"], item["fmax"]
            # P3 fix: use pessimistic (target_min) for both — safer when children underperform
            item["fmin"] = max(0, item["fmin"] - children_fmin_sum)
            item["fmax"] = max(0, item["fmax"] - children_fmin_sum)
            # Write back
            item["ng"]["freq_min"] = item["fmin"]
            item["ng"]["freq_max"] = item["fmax"]
            if old_max != item["fmax"]:
                name = item["ng"].get("ngram") or item["ng"].get("text")
                print(f"[BUDGET] cascade: {name} [{old_min},{old_max}] → [{item['fmin']},{item['fmax']}]")

    return ngrams


def deduplicate_keywords(ngrams: list, main_keyword: str) -> list:
    """Adaptive reduction for phrases nested in the main keyword.

    P2 fix: replaced magic 2/3 with adaptive ratio based on phrase overlap.
    - Full overlap (all words of phrase in MAIN): ratio = 0.5 (conservative)
    - Partial overlap: ratio = overlap_words / total_main_words * 0.5
    This gives an empirically-grounded ratio instead of hardcoded 2/3.
    """
    main_lower = main_keyword.strip().lower()
    main_words = main_lower.split()
    main_lemmas = _lemmatize_phrase(main_lower)

    # Estimate main_max from typical usage
    main_max = 9  # reasonable default; exact value from S1 if available

    # Find main_max from ngrams if main keyword is in the list
    for ng in ngrams:
        text = (ng.get("ngram") or ng.get("text") or "").strip().lower()
        if text == main_lower:
            main_max = ng.get("freq_max", 0) or 9
            break

    for ng in ngrams:
        text = (ng.get("ngram") or ng.get("text") or "").strip()
        if not text or text.lower() == main_lower:
            continue

        fmax = ng.get("freq_max", 0)
        if fmax == 0:
            continue

        # Check if nested in MAIN
        if _phrase_contains_fuzzy(main_lower, text):
            # Adaptive ratio: measure actual word overlap
            phrase_lemmas = _lemmatize_phrase(text)
            overlap_count = sum(1 for pl in phrase_lemmas if pl in main_lemmas)
            overlap_ratio = overlap_count / max(1, len(main_words))
            # Scale: full overlap → 0.5, partial → proportionally less
            reduction_ratio = overlap_ratio * 0.5
            reduction = max(1, int(main_max * reduction_ratio))
            new_max = max(1, fmax - reduction)
            if new_max != fmax:
                ng["freq_max"] = new_max
                print(f"[BUDGET] dedup_main: {text} freq_max {fmax} → {new_max} "
                      f"(nested in MAIN, ratio={reduction_ratio:.2f}×{main_max})")

    return ngrams


class KeywordTracker:
    """In-memory keyword budget tracker for a single article generation workflow."""

    def __init__(self, main_keyword: str, ngrams: list = None,
                 extended_ngrams: list = None, total_batches: int = 6,
                 project_id: Optional[str] = None):
        self.main_keyword = main_keyword.strip()
        self._main_kw_lower = self.main_keyword.lower()
        self._main_kw_pattern = re.compile(
            r'\b' + re.escape(self._main_kw_lower) + r'\b'
        )
        self.total_batches = max(2, total_batches)

        # Dynamic main keyword max based on article length
        self._kw_max = _compute_main_kw_max(self.total_batches)
        self._kw_hard_ceiling = int(self._kw_max * 1.5)

        # Main keyword counter
        self._global_main_kw_count = 0

        # Phrase budget: {phrase_lower: {global_max, global_used, global_remaining, type, _pattern}}
        self._global_phrase_budget = {}

        # Batch tracking
        self.batch_count = 0
        self.batch_reports = []

        # Firestore — write-only for panel real-time display
        self.project_id = project_id
        self._db = _get_db() if project_id else None

        # Pre-process ngrams before budget init
        basic = list(ngrams or [])
        extended = list(extended_ngrams or [])

        # Step 0: Filter garbage n-grams (CSS/HTML/non-Polish junk from S1)
        basic = filter_garbage_ngrams(basic)
        extended = filter_garbage_ngrams(extended)

        # Step 0b: Clamp rigid freq_min/freq_max limits from S1
        # Estimate article length from total_batches (~250 words/batch)
        est_article_length = self.total_batches * 250
        basic = clamp_freq_limits(basic, est_article_length)
        extended = clamp_freq_limits(extended, est_article_length)

        # Step 1: Remove subsumed short phrases
        basic = remove_subsumed_basic(basic, self.main_keyword)
        extended = remove_subsumed_basic(extended, self.main_keyword)

        # Step 2: Cascade deduct targets (inclusion-exclusion)
        all_ngrams = basic + extended
        cascade_deduct_targets(all_ngrams)

        # Step 3: Deduplicate against main keyword
        deduplicate_keywords(basic, self.main_keyword)
        deduplicate_keywords(extended, self.main_keyword)

        # Initialize budgets with pre-processed data
        self._init_phrase_budget(basic, "BASIC")
        self._init_phrase_budget(extended, "EXTENDED")

        # Save initial budget snapshot to Firestore
        self._save_to_firestore("init")

    def _is_topic_phrase(self, phrase_lower: str) -> bool:
        """Check if phrase shares word stems with main keyword → topic-central.

        P2 fix: Uses lemmatization for exact match instead of prefix ≥4 chars.
        Prevents false positives like "transport" matching "transparentny".
        Falls back to exact word match if lemmatization unavailable.
        """
        main_lemmas = set(_lemmatize_phrase(self._main_kw_lower))
        phrase_lemmas = _lemmatize_phrase(phrase_lower)
        for pl in phrase_lemmas:
            if len(pl) < 3:
                continue
            if pl in main_lemmas:
                return True
        return False

    def _init_phrase_budget(self, ngrams: list, ngram_type: str):
        """Initialize phrase budgets from pre-processed ngram data.

        Budget scaling:
        - BASIC:  max(total_batches * 2, freq_max * 2), topic phrases * 2
        - EXTENDED: max(2, freq_max), topic phrases * 1.5
        - Fuzzy pattern for counting (aligns with cascade logic)
        """
        for ng in ngrams:
            text = (ng.get("ngram") or ng.get("text") or "").strip()
            if not text:
                continue
            if text.lower() == self._main_kw_lower:
                continue

            target_max = ng.get("freq_max", 0)
            if target_max == 0:
                weight = ng.get("weight", 0)
                target_max = max(1, int(weight * 10))

            is_topic = self._is_topic_phrase(text.lower())

            if ngram_type == "BASIC":
                global_max = max(self.total_batches * 2, target_max * 2)
                if is_topic:
                    global_max *= 2
            else:  # EXTENDED
                global_max = max(2, target_max)
                if is_topic:
                    global_max = int(global_max * 1.5)

            key = text.lower()
            if key not in self._global_phrase_budget:
                self._global_phrase_budget[key] = {
                    "phrase": text,
                    "global_max": global_max,
                    "global_used": 0,
                    "global_remaining": global_max,
                    "type": ngram_type,
                    "_pattern": _build_fuzzy_pattern(key),
                }

    # ── Firestore persistence (write-only, for panel real-time display) ──

    def _save_to_firestore(self, batch_label: str = ""):
        """Write current budget state to Firestore. Never blocks generation on failure."""
        if not self._db or not self.project_id:
            return
        try:
            doc_ref = self._db.collection(BUDGET_COLLECTION).document(self.project_id)
            doc_ref.set({
                "main_keyword": {
                    "keyword": self.main_keyword,
                    "used": self._global_main_kw_count,
                    "max": self._kw_max,
                    "hard_ceiling": self._kw_hard_ceiling,
                    "status": self._main_kw_status(),
                },
                "phrases": {
                    k: {
                        "phrase": v["phrase"],
                        "global_max": v["global_max"],
                        "global_used": v["global_used"],
                        "global_remaining": v["global_remaining"],
                        "type": v["type"],
                    }
                    for k, v in self._global_phrase_budget.items()
                },
                "batch_count": self.batch_count,
                "last_batch": batch_label,
            }, merge=True)

            if batch_label and batch_label != "init":
                latest = self.batch_reports[-1] if self.batch_reports else {}
                doc_ref.collection("batches").document(batch_label).set(latest)
        except Exception as e:
            print(f"[BUDGET] Firestore save error (non-blocking): {e}")

    # ── Counting (fuzzy regex — aligns with cascade logic) ──

    def _count_main_kw(self, text: str) -> int:
        """Count main keyword — exact word-boundary match on lowercase."""
        return len(self._main_kw_pattern.findall(text.lower()))

    def _count_phrase(self, budget: dict, text_lower: str) -> int:
        """Count phrase using fuzzy pattern.

        Pattern matches morphological variants:
        'nawilżyć' pattern → \\bnawilż\\w*\\b → matches nawilżeniu, nawilżenia, nawilżone
        'sucha skóra' → \\bsuch\\w*\\s+skór\\w*\\b → matches suchej skórze
        """
        return len(budget["_pattern"].findall(text_lower))

    # ── Budget update ──

    def update_after_batch(self, batch_text: str, batch_label: str = "") -> dict:
        """Count all phrases in batch text and update budgets."""
        if not batch_text:
            return {}

        text_lower = batch_text.lower()
        self.batch_count += 1

        # 1. Main keyword
        main_kw_in_batch = self._count_main_kw(batch_text)
        self._global_main_kw_count += main_kw_in_batch

        # 2. Phrases
        phrase_report = []
        for key, budget in self._global_phrase_budget.items():
            count_in_batch = self._count_phrase(budget, text_lower)
            budget["global_used"] += count_in_batch
            budget["global_remaining"] = max(0, budget["global_max"] - budget["global_used"])

            if count_in_batch > 0:
                phrase_report.append({
                    "phrase": budget["phrase"],
                    "in_batch": count_in_batch,
                    "total_used": budget["global_used"],
                    "remaining": budget["global_remaining"],
                    "status": "OVER" if budget["global_used"] > budget["global_max"] else "OK",
                })

        report = {
            "batch_label": batch_label,
            "batch_number": self.batch_count,
            "main_kw": {
                "keyword": self.main_keyword,
                "in_batch": main_kw_in_batch,
                "total_used": self._global_main_kw_count,
                "max": self._kw_max,
                "hard_ceiling": self._kw_hard_ceiling,
                "status": self._main_kw_status(),
            },
            "phrases": phrase_report,
            "exhausted": [
                b["phrase"] for b in self._global_phrase_budget.values()
                if b["global_remaining"] <= 0
            ],
        }
        self.batch_reports.append(report)

        # Log
        if main_kw_in_batch > 0:
            status = self._main_kw_status()
            print(f"[BUDGET] {batch_label}: main_kw '{self.main_keyword}' "
                  f"{self._global_main_kw_count}/{self._kw_max} [{status}]")
        over = [p for p in phrase_report if p["status"] == "OVER"]
        if over:
            names = ", ".join(f"{p['phrase']}({p['total_used']}/{p['remaining'] + p['total_used']})" for p in over)
            print(f"[BUDGET] {batch_label}: OVER-BUDGET: {names}")

        self._save_to_firestore(batch_label)
        return report

    # ── Status helpers ──

    def _main_kw_status(self) -> str:
        """Get main keyword status: NORMAL / STOP / FORCE_BAN."""
        if self._global_main_kw_count >= self._kw_hard_ceiling:
            return "FORCE_BAN"
        if self._global_main_kw_count >= self._kw_max:
            return "STOP"
        return "NORMAL"

    def _main_kw_needs_inject(self) -> bool:
        """Check if main keyword needs forced injection (underuse).

        Never inject if status is STOP or FORCE_BAN — ban always wins.
        """
        if self._main_kw_status() != "NORMAL":
            return False
        if self.batch_count >= 3 and self._global_main_kw_count == 0:
            return True
        remaining_batches = self.total_batches - self.batch_count
        min_expected = max(2, self._kw_max // 3)
        if remaining_batches <= 2 and self._global_main_kw_count < min_expected:
            return True
        return False

    # ── Prompt formatting ──

    def format_main_kw_instruction(self) -> str:
        """Generate prompt instruction for main keyword.

        force-ban always wins over force-inject (no conflicting instructions).
        """
        status = self._main_kw_status()
        used = self._global_main_kw_count
        remaining = self._kw_max - used

        if status == "FORCE_BAN":
            return (f'⛔ STOP: Fraza "{self.main_keyword}" przekroczona '
                    f'({used}/{self._kw_hard_ceiling}) — nie używaj w tym batchu.')
        if status == "STOP":
            return (f'🛑 Fraza "{self.main_keyword}" osiągnęła limit '
                    f'({used}/{self._kw_max}) — używaj synonimów i peryfraz zamiast formy dosłownej.')
        if self._main_kw_needs_inject():
            return (f'⚠️ Fraza główna zbyt rzadka — użyj min. 2×: '
                    f'"{self.main_keyword}" (dotychczas: {used})')
        return (f'Fraza główna: "{self.main_keyword}" — '
                f'zostało {remaining}x (użyto {used}/{self._kw_max})')

    def format_phrases_for_prompt(self, assigned_phrases: list = None,
                                   h2_heading: str = "") -> str:
        """Format phrase budget for prompt.

        - No STOP for non-exhausted phrases.
        - Cap EXTENDED phrases to _MAX_EXTENDED_PER_BATCH.
        - P3 fix: sort EXTENDED by H2 topic relevance (keyword overlap) before rotating.
        """
        basic_lines = []
        extended_lines = []
        stop_lines = []

        phrases_to_show = {}
        if assigned_phrases:
            for name in assigned_phrases:
                if not name or not isinstance(name, str):
                    continue
                key = name.strip().lower()
                if key in self._global_phrase_budget:
                    phrases_to_show[key] = self._global_phrase_budget[key]
            for key, budget in self._global_phrase_budget.items():
                if key not in phrases_to_show and budget["type"] == "BASIC" and budget["global_remaining"] > 0:
                    phrases_to_show[key] = budget
        else:
            phrases_to_show = dict(self._global_phrase_budget)

        remaining_batches = max(1, self.total_batches - self.batch_count)

        for key, budget in phrases_to_show.items():
            phrase = budget["phrase"]
            remaining = budget["global_remaining"]
            ptype = budget["type"]

            if remaining <= 0:
                if ptype == "BASIC":
                    stop_lines.append(f'🛑 STOP — nie używaj: "{phrase}"')
                continue

            allocated = max(1, -(-remaining // remaining_batches))
            allocated = min(allocated, remaining)
            budget["allocated_this_batch"] = allocated

            line = (f'{phrase} · {allocated}x w tej sekcji '
                    f'(zostało {remaining} na artykuł)')

            if ptype == "BASIC":
                basic_lines.append(line)
            else:
                extended_lines.append((key, line))

        # P3 fix: sort EXTENDED by H2 relevance before capping
        if h2_heading and len(extended_lines) > _MAX_EXTENDED_PER_BATCH:
            h2_lemmas = set(_lemmatize_phrase(h2_heading.lower()))

            def _h2_relevance(item):
                key, _ = item
                phrase_lemmas = _lemmatize_phrase(key)
                overlap = sum(1 for pl in phrase_lemmas if pl in h2_lemmas)
                return -overlap  # negative for descending sort

            extended_lines.sort(key=_h2_relevance)
            extended_lines = extended_lines[:_MAX_EXTENDED_PER_BATCH]
        elif len(extended_lines) > _MAX_EXTENDED_PER_BATCH:
            # Fallback: round-robin rotation when no H2 heading provided
            offset = (self.batch_count * _MAX_EXTENDED_PER_BATCH) % len(extended_lines)
            rotated = extended_lines[offset:] + extended_lines[:offset]
            extended_lines = rotated[:_MAX_EXTENDED_PER_BATCH]

        ext_line_strs = [line for _, line in extended_lines]

        # P1: Coverage alert — inform model about underperforming phrases
        coverage_alert_lines = []
        if self.batch_count >= 2:  # Only after first 2 batches have data
            progress_ratio = self.batch_count / max(1, self.total_batches)
            for key, budget in self._global_phrase_budget.items():
                if budget["type"] != "BASIC" or budget["global_remaining"] <= 0:
                    continue
                expected_used = budget["global_max"] * progress_ratio
                actual_used = budget["global_used"]
                # Flag if actual usage is less than 40% of expected
                if expected_used > 1 and actual_used < expected_used * 0.4:
                    deficit = int(expected_used - actual_used)
                    coverage_alert_lines.append(
                        f'"{budget["phrase"]}" ({actual_used}/{budget["global_max"]} użyć, '
                        f'zaległość: ~{deficit}× — priorytetyzuj)'
                    )

        parts = []
        if coverage_alert_lines:
            parts.append(
                "<coverage_alert>\n"
                "Frazy z zaległościami — priorytetyzuj je w tej sekcji:\n"
                + "\n".join(coverage_alert_lines[:8])  # cap at 8 alerts
                + "\n</coverage_alert>"
            )
        if basic_lines:
            parts.append("MUST (użyj obowiązkowo):\n" + "\n".join(basic_lines))
        if ext_line_strs:
            parts.append("NICE-TO-HAVE (użyj jeśli pasują do kontekstu):\n" + "\n".join(ext_line_strs))
        if stop_lines:
            parts.append("\n".join(stop_lines))

        return "\n\n".join(parts)

    # ── Summary ──

    def get_summary(self) -> dict:
        """Return summary for SSE events / panel display."""
        exhausted = [
            b["phrase"] for b in self._global_phrase_budget.values()
            if b["global_remaining"] <= 0
        ]
        over = [
            b["phrase"] for b in self._global_phrase_budget.values()
            if b["global_used"] > b["global_max"]
        ]

        return {
            "main_keyword": {
                "keyword": self.main_keyword,
                "used": self._global_main_kw_count,
                "max": self._kw_max,
                "hard_ceiling": self._kw_hard_ceiling,
                "status": self._main_kw_status(),
            },
            "phrases": {
                "total": len(self._global_phrase_budget),
                "exhausted": len(exhausted),
                "exhausted_list": exhausted,
                "over_budget": over,
            },
            "batches_tracked": self.batch_count,
        }
