"""
Keyword Budget Tracker — Firestore-backed stateful n-gram frequency tracking.

Persists keyword_state (remaining min/max budgets) to Firestore after each batch,
enabling:
- Cross-batch budget enforcement (LLM sees real remaining budget)
- Pipeline resume (reload state if generation was interrupted)
- Compliance audit trail (per-batch reports stored for debugging)

Collection: seo_keyword_budgets/{project_id}/batches/{batch_label}
"""
import json
from typing import Optional


def _get_db():
    """Get Firestore client, returns None if unavailable."""
    try:
        from src.common.firebase import get_db
        return get_db()
    except ImportError:
        return None


BUDGET_COLLECTION = "seo_keyword_budgets"


class KeywordTracker:
    """Stateful keyword budget tracker with optional Firestore persistence."""

    def __init__(self, project_id: Optional[str] = None, ngrams: list = None):
        """
        Args:
            project_id: Firestore document ID. If None, tracking is in-memory only.
            ngrams: List of ngram dicts with 'ngram', 'freq_min', 'freq_max', 'weight'.
        """
        self.project_id = project_id
        self.keyword_state = {}
        self.batch_reports = []  # compliance reports per batch
        self._db = _get_db() if project_id else None

        if ngrams:
            self._init_state_from_ngrams(ngrams)

    def _init_state_from_ngrams(self, ngrams: list):
        """Build initial keyword budget from S1 ngram data."""
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
            self.keyword_state[text] = {"min": fmin, "max": fmax}

    # ── Firestore persistence ──

    def save_state(self, batch_label: str = "current"):
        """Persist current keyword_state to Firestore."""
        if not self._db or not self.project_id:
            return
        try:
            doc_ref = self._db.collection(BUDGET_COLLECTION).document(self.project_id)
            doc_ref.set({
                "keyword_state": self.keyword_state,
                "batch_count": len(self.batch_reports),
            }, merge=True)

            # Save per-batch report
            if self.batch_reports:
                latest = self.batch_reports[-1]
                doc_ref.collection("batches").document(batch_label).set(latest)
        except Exception as e:
            print(f"[KEYWORD_TRACKER] Firestore save error: {e}")

    def load_state(self) -> bool:
        """Load keyword_state from Firestore. Returns True if state was loaded."""
        if not self._db or not self.project_id:
            return False
        try:
            doc = self._db.collection(BUDGET_COLLECTION).document(self.project_id).get()
            if doc.exists:
                data = doc.to_dict()
                saved_state = data.get("keyword_state")
                if saved_state and isinstance(saved_state, dict):
                    self.keyword_state = saved_state
                    print(f"[KEYWORD_TRACKER] Loaded state from Firestore ({len(saved_state)} keywords)")
                    return True
        except Exception as e:
            print(f"[KEYWORD_TRACKER] Firestore load error: {e}")
        return False

    def clear_state(self):
        """Clear persisted state (for fresh generation)."""
        if not self._db or not self.project_id:
            return
        try:
            self._db.collection(BUDGET_COLLECTION).document(self.project_id).delete()
        except Exception as e:
            print(f"[KEYWORD_TRACKER] Firestore clear error: {e}")

    # ── Compliance tracking ──

    def update_after_batch(self, batch_text: str, batch_label: str = "") -> dict:
        """
        Run compliance check on batch text and update remaining budget.

        Returns compliance report dict with:
        - compliance_report: list of per-keyword status
        - over_budget: list of keywords that exceeded budget
        - exhausted: list of keywords with max=0 (fully used)
        """
        if not self.keyword_state or not batch_text:
            return {}

        try:
            from src.s1.generate_compliance_report import generate_compliance_report
            result = generate_compliance_report(batch_text, self.keyword_state)
        except Exception as e:
            print(f"[KEYWORD_TRACKER] Compliance check failed: {e}")
            return {}

        report = result.get("compliance_report", [])
        self.keyword_state = result.get("new_keyword_state", self.keyword_state)

        # Categorize
        over_budget = [r for r in report if r.get("status") == "OVER"]
        exhausted = [
            kw for kw, budget in self.keyword_state.items()
            if budget.get("max", 0) <= 0
        ]

        batch_result = {
            "batch_label": batch_label,
            "compliance_report": report,
            "over_budget": [r["keyword"] for r in over_budget],
            "exhausted": exhausted,
            "keyword_state_after": dict(self.keyword_state),  # snapshot
        }
        self.batch_reports.append(batch_result)

        # Log warnings
        if over_budget:
            phrases = ", ".join(f"{r['keyword']}({r['actual_in_batch']})" for r in over_budget)
            print(f"[KEYWORD_TRACKER] {batch_label}: OVER-BUDGET: {phrases}")
        if exhausted:
            print(f"[KEYWORD_TRACKER] {batch_label}: Exhausted ({len(exhausted)}): {', '.join(exhausted[:5])}")

        # Persist to Firestore
        self.save_state(batch_label)

        return batch_result

    # ── Prompt formatting ──

    def format_for_prompt(self, ngram_names: list) -> str:
        """Format assigned ngrams with remaining budget for LLM prompt.

        Output format per line:
        - Active:    'zabezpieczyć meble · zostało 2-5x (nie przekraczaj 5)'
        - Exhausted: 'transport mebli · STOP — budżet wyczerpany, NIE UŻYWAJ'
        """
        lines = []
        for name in ngram_names:
            if not name or not isinstance(name, str):
                continue
            budget = self._lookup_budget(name)
            if budget:
                remaining_max = budget.get("max", 0)
                remaining_min = budget.get("min", 0)
                if remaining_max <= 0:
                    lines.append(f"{name} · STOP — budżet wyczerpany, NIE UŻYWAJ")
                else:
                    lines.append(
                        f"{name} · zostało {remaining_min}-{remaining_max}x "
                        f"(nie przekraczaj {remaining_max})"
                    )
            else:
                # Unknown ngram — conservative default
                lines.append(f"{name} · max 1-2x")
        return "\n".join(lines)

    def _lookup_budget(self, name: str) -> Optional[dict]:
        """Case-insensitive budget lookup."""
        budget = self.keyword_state.get(name.strip())
        if budget:
            return budget
        name_lower = name.strip().lower()
        for k, v in self.keyword_state.items():
            if k.lower() == name_lower:
                return v
        return None

    # ── Summary ──

    def get_summary(self) -> dict:
        """Return summary for final article event / panel display."""
        total = len(self.keyword_state)
        exhausted = sum(1 for b in self.keyword_state.values() if b.get("max", 0) <= 0)
        over = set()
        for report in self.batch_reports:
            over.update(report.get("over_budget", []))

        return {
            "total_keywords": total,
            "exhausted": exhausted,
            "over_budget_keywords": sorted(over),
            "batches_tracked": len(self.batch_reports),
            "remaining_budget": {
                k: v for k, v in self.keyword_state.items()
                if v.get("max", 0) > 0
            },
        }
