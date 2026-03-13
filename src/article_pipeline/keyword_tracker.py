"""
Keyword Budget Tracker — in-memory phrase frequency control across batches.

Tracks two separate budgets:
1. _global_main_kw_count — main keyword (hasło główne), hardcoded max 6, hard ceiling 9
2. _global_phrase_budget — all other phrases from S1 ngrams (BASIC + EXTENDED)

Counting method:
- Main keyword: re.findall(r'\\b' + exact + r'\\b', text.lower()) — exact case-insensitive
- Phrases: str.count(phrase_lower) — substring match, no lemmatization

Budget lives in RAM for one workflow. No persistence (Firestore not involved).
"""
import re
from typing import Optional

# ── Main keyword constants ──
_GLOBAL_KW_MAX = 6           # max occurrences in entire article
_KW_HARD_CEILING = int(_GLOBAL_KW_MAX * 1.5)  # = 9, force-ban above this


class KeywordTracker:
    """In-memory keyword budget tracker for a single article generation workflow."""

    def __init__(self, main_keyword: str, ngrams: list = None,
                 extended_ngrams: list = None, total_batches: int = 6):
        """
        Args:
            main_keyword: Hasło główne (e.g. "sucha skóra głowy").
            ngrams: BASIC ngrams from S1 — list of dicts with 'ngram', 'freq_max', 'weight'.
            extended_ngrams: EXTENDED ngrams from S1 — same format, lower budgets.
            total_batches: Total number of batches in pipeline (intro + H2s + FAQ).
        """
        self.main_keyword = main_keyword.strip()
        self._main_kw_lower = self.main_keyword.lower()
        self._main_kw_pattern = re.compile(
            r'\b' + re.escape(self._main_kw_lower) + r'\b'
        )
        self.total_batches = max(2, total_batches)

        # Main keyword counter
        self._global_main_kw_count = 0

        # Phrase budget: {phrase_lower: {global_max, global_used, global_remaining, type}}
        self._global_phrase_budget = {}

        # Batch tracking
        self.batch_count = 0
        self.batch_reports = []

        # Initialize budgets
        self._init_phrase_budget(ngrams or [], "BASIC")
        self._init_phrase_budget(extended_ngrams or [], "EXTENDED")

    def _init_phrase_budget(self, ngrams: list, ngram_type: str):
        """Initialize phrase budgets from S1 ngram data."""
        for ng in ngrams:
            text = (ng.get("ngram") or ng.get("text") or "").strip()
            if not text:
                continue
            # Skip if it's the main keyword itself
            if text.lower() == self._main_kw_lower:
                continue

            target_max = ng.get("freq_max", 0)
            if target_max == 0:
                weight = ng.get("weight", 0)
                target_max = max(1, int(weight * 10))

            # Compute global_max based on type
            if ngram_type == "BASIC":
                global_max = min(max(3, target_max), self.total_batches * 2)
            else:  # EXTENDED
                global_max = min(max(1, target_max), self.total_batches)

            key = text.lower()
            if key not in self._global_phrase_budget:
                self._global_phrase_budget[key] = {
                    "phrase": text,  # original form for display
                    "global_max": global_max,
                    "global_used": 0,
                    "global_remaining": global_max,
                    "type": ngram_type,
                }

    # ── Counting ──

    def _count_main_kw(self, text: str) -> int:
        """Count main keyword occurrences — exact regex match on lowercase."""
        return len(self._main_kw_pattern.findall(text.lower()))

    def _count_phrase(self, phrase_lower: str, text_lower: str) -> int:
        """Count phrase occurrences — simple str.count substring match."""
        return text_lower.count(phrase_lower)

    # ── Budget update ──

    def update_after_batch(self, batch_text: str, batch_label: str = "") -> dict:
        """
        Count all phrases in batch text and update budgets.
        Call this after each accepted batch.

        Returns batch report dict.
        """
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
            count_in_batch = self._count_phrase(key, text_lower)
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

        # Build report
        report = {
            "batch_label": batch_label,
            "batch_number": self.batch_count,
            "main_kw": {
                "keyword": self.main_keyword,
                "in_batch": main_kw_in_batch,
                "total_used": self._global_main_kw_count,
                "max": _GLOBAL_KW_MAX,
                "hard_ceiling": _KW_HARD_CEILING,
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
                  f"{self._global_main_kw_count}/{_GLOBAL_KW_MAX} [{status}]")
        over = [p for p in phrase_report if p["status"] == "OVER"]
        if over:
            names = ", ".join(f"{p['phrase']}({p['total_used']}/{p['remaining'] + p['total_used']})" for p in over)
            print(f"[BUDGET] {batch_label}: OVER-BUDGET: {names}")

        return report

    # ── Status helpers ──

    def _main_kw_status(self) -> str:
        """Get main keyword status: NORMAL / STOP / FORCE_BAN."""
        if self._global_main_kw_count >= _KW_HARD_CEILING:
            return "FORCE_BAN"
        if self._global_main_kw_count >= _GLOBAL_KW_MAX:
            return "STOP"
        return "NORMAL"

    def _main_kw_needs_inject(self) -> bool:
        """Check if main keyword needs forced injection (underuse)."""
        # Force-inject if batch >= 3 and used == 0
        if self.batch_count >= 3 and self._global_main_kw_count == 0:
            return True
        # Force-inject if in last 2 batches and used < 3
        remaining_batches = self.total_batches - self.batch_count
        if remaining_batches <= 2 and self._global_main_kw_count < 3:
            return True
        return False

    # ── Prompt formatting ──

    def format_main_kw_instruction(self) -> str:
        """Generate prompt instruction for main keyword."""
        status = self._main_kw_status()
        used = self._global_main_kw_count
        remaining = _GLOBAL_KW_MAX - used

        if status == "FORCE_BAN":
            return (f'⛔ STOP: Fraza "{self.main_keyword}" przekroczona '
                    f'({used}/{_KW_HARD_CEILING}) — nie używaj w tym batchu.')
        if status == "STOP":
            return (f'🛑 STOP — nie używaj: "{self.main_keyword}" '
                    f'(wykorzystano {used}/{_GLOBAL_KW_MAX})')
        if self._main_kw_needs_inject():
            return (f'⚠️ Fraza główna zbyt rzadka — użyj min. 2×: '
                    f'"{self.main_keyword}" (dotychczas: {used})')
        return (f'Fraza główna: "{self.main_keyword}" — '
                f'zostało {remaining}x (użyto {used}/{_GLOBAL_KW_MAX})')

    def format_phrases_for_prompt(self, assigned_phrases: list = None) -> str:
        """Format phrase budget for prompt.

        If assigned_phrases is given, only format those.
        Otherwise, format all non-exhausted phrases.

        Each line shows phrase + allocated_this_batch + status.
        """
        lines = []
        stop_lines = []

        phrases_to_format = self._global_phrase_budget
        if assigned_phrases:
            phrases_to_format = {}
            for name in assigned_phrases:
                if not name or not isinstance(name, str):
                    continue
                key = name.strip().lower()
                if key in self._global_phrase_budget:
                    phrases_to_format[key] = self._global_phrase_budget[key]

        remaining_batches = max(1, self.total_batches - self.batch_count)

        for key, budget in phrases_to_format.items():
            phrase = budget["phrase"]
            remaining = budget["global_remaining"]

            if remaining <= 0:
                stop_lines.append(f'🛑 STOP — nie używaj: "{phrase}"')
                continue

            # Allocate for this batch: distribute remaining across remaining batches
            allocated = max(1, -(-remaining // remaining_batches))  # ceiling div
            allocated = min(allocated, remaining)  # don't exceed total remaining
            budget["allocated_this_batch"] = allocated

            lines.append(
                f'{phrase} · {allocated}x w tej sekcji '
                f'(zostało {remaining} na artykuł)'
            )

        return "\n".join(lines + stop_lines)

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
                "max": _GLOBAL_KW_MAX,
                "hard_ceiling": _KW_HARD_CEILING,
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
