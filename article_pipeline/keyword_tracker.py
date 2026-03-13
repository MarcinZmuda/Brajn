"""
Keyword Budget Tracker — in-memory phrase frequency control across batches,
with optional Firestore persistence for real-time panel display.

Tracks two separate budgets:
1. Main keyword — dynamic max based on total_batches (not hardcoded 6)
2. Phrase budget — BASIC + EXTENDED ngrams with \b word-boundary counting

Counting method (all phrases + main kw):
- re.findall(r'\\b' + re.escape(phrase) + r'\\b', text.lower())
- Word boundaries prevent inflected forms from burning budget
  (szamponem does NOT count as "szampon", suchej does NOT count as "sucha")

Budget lives in RAM. Firestore is write-only (for panel reads), never blocks generation.
Collection: seo_keyword_budgets/{project_id}
"""
import re
from typing import Optional


BUDGET_COLLECTION = "seo_keyword_budgets"

# ── Prompt cap: max EXTENDED phrases shown per batch ──
_MAX_EXTENDED_PER_BATCH = 12


def _get_db():
    """Get Firestore client, returns None if unavailable."""
    try:
        from src.common.firebase import get_db
        return get_db()
    except ImportError:
        return None


def _compute_main_kw_max(total_batches: int) -> int:
    """Dynamic main keyword max: ~1 per batch, min 4, max 15.

    800-word article (4 batches)  → max 4
    1200-word article (6 batches) → max 6
    1900-word article (8 batches) → max 8
    3000-word article (12 batches) → max 12
    """
    return max(4, min(total_batches, 15))


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

        # Fix 1: Dynamic main keyword max based on article length
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

        # Initialize budgets
        self._init_phrase_budget(ngrams or [], "BASIC")
        self._init_phrase_budget(extended_ngrams or [], "EXTENDED")

        # Save initial budget snapshot to Firestore
        self._save_to_firestore("init")

    def _init_phrase_budget(self, ngrams: list, ngram_type: str):
        """Initialize phrase budgets from S1 ngram data."""
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

            if ngram_type == "BASIC":
                global_max = min(max(3, target_max), self.total_batches * 2)
            else:  # EXTENDED
                global_max = min(max(1, target_max), self.total_batches)

            key = text.lower()
            if key not in self._global_phrase_budget:
                # Fix 2: Pre-compile \b pattern for each phrase
                self._global_phrase_budget[key] = {
                    "phrase": text,
                    "global_max": global_max,
                    "global_used": 0,
                    "global_remaining": global_max,
                    "type": ngram_type,
                    "_pattern": re.compile(r'\b' + re.escape(key) + r'\b'),
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

    # ── Counting (Fix 2: \b word boundaries for ALL phrases) ──

    def _count_main_kw(self, text: str) -> int:
        """Count main keyword — exact word-boundary match on lowercase."""
        return len(self._main_kw_pattern.findall(text.lower()))

    def _count_phrase(self, budget: dict, text_lower: str) -> int:
        """Count phrase — word-boundary regex match, not str.count().

        'szampon' matches 'szampon' but NOT 'szamponem', 'szamponu', 'szampony'.
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

        Fix 5: Never inject if status is STOP or FORCE_BAN — ban always wins.
        """
        if self._main_kw_status() != "NORMAL":
            return False
        # Underuse: batch >= 3 and never used
        if self.batch_count >= 3 and self._global_main_kw_count == 0:
            return True
        # Underuse: last 2 batches and used < 30% of max
        remaining_batches = self.total_batches - self.batch_count
        min_expected = max(2, self._kw_max // 3)
        if remaining_batches <= 2 and self._global_main_kw_count < min_expected:
            return True
        return False

    # ── Prompt formatting ──

    def format_main_kw_instruction(self) -> str:
        """Generate prompt instruction for main keyword.

        Fix 5: force-ban always wins over force-inject (no conflicting instructions).
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

    def format_phrases_for_prompt(self, assigned_phrases: list = None) -> str:
        """Format phrase budget for prompt.

        Fix 3: No STOP for non-exhausted phrases. If budget > 0, phrase is allowed
               regardless of whether it was "assigned" to this batch.
        Fix 4: Cap EXTENDED phrases to _MAX_EXTENDED_PER_BATCH, rotate by batch_count.
        """
        basic_lines = []
        extended_lines = []
        stop_lines = []

        # Collect all phrases with remaining budget
        phrases_to_show = {}
        if assigned_phrases:
            # Show assigned phrases + any with remaining budget
            for name in assigned_phrases:
                if not name or not isinstance(name, str):
                    continue
                key = name.strip().lower()
                if key in self._global_phrase_budget:
                    phrases_to_show[key] = self._global_phrase_budget[key]
            # Also include non-assigned BASIC phrases that still have budget
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
                # Fix 3: Only show STOP for BASIC exhausted phrases.
                # Don't clutter prompt with STOP for every EXTENDED phrase.
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

        # Fix 4: Rotate EXTENDED phrases across batches, cap at _MAX_EXTENDED_PER_BATCH
        if len(extended_lines) > _MAX_EXTENDED_PER_BATCH:
            # Rotate: shift by batch_count so different batches see different EXTENDED phrases
            offset = (self.batch_count * _MAX_EXTENDED_PER_BATCH) % len(extended_lines)
            rotated = extended_lines[offset:] + extended_lines[:offset]
            extended_lines = rotated[:_MAX_EXTENDED_PER_BATCH]

        ext_line_strs = [line for _, line in extended_lines]

        parts = []
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
