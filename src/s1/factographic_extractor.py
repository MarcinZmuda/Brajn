"""
===============================================================================
FACTOGRAPHIC TRIPLET EXTRACTOR v1.0 (LLM-based)
===============================================================================
Extracts non-causal factographic triplets from competitor texts:
- SPO (Subject-Predicate-Object): "Tesla produkuje samochody elektryczne"
- EAV (Entity-Attribute-Value): "Dieta keto składa się z 70% tłuszczów"

Complementary to causal_extractor.py which handles ONLY causal relations
(causes/prevents/requires/enables/leads_to).

This module covers everything else: composition, production, properties,
requirements, definitions, classifications, etc.

Integration: analysis.py → after causal_extractor → adds "factographic_triplets"
Cost: ~$0.002 per call (Haiku, ~2-3K input tokens, ~400 output tokens)
===============================================================================
"""

import os
import re
import json
import logging
from typing import List, Dict
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

try:
    import requests as _requests
except ImportError:
    _requests = None


# ================================================================
# DATA STRUCTURES
# ================================================================

@dataclass
class FactographicTriplet:
    """Single factographic (non-causal) relation."""
    subject: str
    predicate: str
    object: str
    triplet_type: str       # "spo" or "eav"
    category: str           # "composition", "property", "definition", "classification",
                            # "production", "requirement", "location", "temporal", "quantitative"
    confidence: float       # 0.0-1.0
    source_sentence: str    # original or reconstructed sentence

    def to_dict(self) -> Dict:
        return asdict(self)


# ================================================================
# EXTRACTION (LLM-based)
# ================================================================

def extract_factographic_triplets(
    texts: List[str],
    main_keyword: str,
    max_triplets: int = 15,
) -> List[FactographicTriplet]:
    """
    Extract non-causal factographic triplets from competitor texts via LLM.

    Returns SPO and EAV triplets that describe facts, properties, compositions,
    definitions, etc. — everything that is NOT a causal relation.
    """
    if not texts or not main_keyword:
        return []

    # Combine texts with limit (~8K chars)
    combined = ""
    for t in texts:
        if t and len(combined) < 8000:
            chunk = t.strip()[:3000]
            if len(chunk) > 100:
                combined += chunk + "\n---\n"

    if len(combined) < 200:
        logger.warning("[FACTO] Combined text too short, skipping")
        return []

    triplets = _extract_via_llm(combined, main_keyword, max_triplets)

    if triplets:
        triplets.sort(key=lambda t: -t.confidence)
        logger.info(f"[FACTO] Extracted {len(triplets)} factographic triplets "
                    f"(SPO: {sum(1 for t in triplets if t.triplet_type == 'spo')}, "
                    f"EAV: {sum(1 for t in triplets if t.triplet_type == 'eav')})")

    return triplets[:max_triplets]


def _extract_via_llm(
    text: str,
    main_keyword: str,
    max_triplets: int,
) -> List[FactographicTriplet]:
    """Extract factographic relations via Anthropic Haiku (primary) or OpenAI (fallback)."""

    if not _requests:
        logger.warning("[FACTO] requests module is not available")
        return []

    prompt = (
        f'Przeanalizuj poniższy tekst z perspektywy tematu "{main_keyword}".\n\n'
        f'Znajdź {max_triplets} najważniejszych FAKTOGRAFICZNYCH relacji '
        f'(NIE przyczynowo-skutkowych!).\n\n'
        f'Szukaj relacji typu:\n'
        f'- SPO (Subject-Predicate-Object): kto/co robi co, kto/co jest czym\n'
        f'  Przykłady: "X składa się z Y", "X produkuje Y", "X wymaga Y", '
        f'"X jest rodzajem Y", "X zawiera Y"\n'
        f'- EAV (Entity-Attribute-Value): cecha/właściwość encji\n'
        f'  Przykłady: "X ma wartość Y", "X kosztuje Y", "X trwa Y", '
        f'"X waży Y kg", "X obowiązuje od Y"\n\n'
        f'WYKLUCZ relacje przyczynowe (powoduje, zapobiega, prowadzi do, '
        f'skutkuje, wynika z) — te są obsługiwane osobno.\n\n'
        f'Odpowiedz TYLKO w formacie JSON — tablica obiektów:\n'
        f'[\n'
        f'  {{"subject": "podmiot", "predicate": "orzeczenie/atrybut", '
        f'"object": "dopełnienie/wartość", '
        f'"type": "spo|eav", '
        f'"category": "composition|property|definition|classification|production|'
        f'requirement|location|temporal|quantitative", '
        f'"confidence": 0.8}}\n'
        f']\n\n'
        f'Zasady:\n'
        f'- Wyciągaj relacje FAKTYCZNIE obecne w tekście, nie wymyślaj\n'
        f'- subject, predicate, object: krótkie frazy (3-60 znaków)\n'
        f'- confidence: 0.6-0.95 (wyżej = jaśniej wyrażone w tekście)\n'
        f'- Skup się na relacjach istotnych dla "{main_keyword}"\n'
        f'- Zero komentarzy, TYLKO tablica JSON\n\n'
        f'TEKST:\n{text[:6000]}'
    )

    raw = _call_anthropic(prompt) or _call_openai(prompt)
    if not raw:
        return []

    return _parse_triplets_json(raw)


def _call_anthropic(prompt: str) -> str:
    """Call Anthropic Haiku. Returns raw text or empty string."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("[FACTO] ANTHROPIC_API_KEY not set, skipping")
        return ""

    try:
        resp = _requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )

        if resp.status_code != 200:
            logger.warning(f"[FACTO] Anthropic API error: {resp.status_code} {resp.text[:200]}")
            return ""

        data = resp.json()
        content = data.get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "").strip()
        return ""

    except Exception as e:
        logger.warning(f"[FACTO] Anthropic call error: {e}")
        return ""


def _call_openai(prompt: str) -> str:
    """Call OpenAI gpt-4.1-mini (fallback). Returns raw text or empty string."""
    oai_key = os.getenv("OPENAI_API_KEY")
    if not oai_key:
        logger.debug("[FACTO] OPENAI_API_KEY not set, skipping fallback")
        return ""

    try:
        resp = _requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {oai_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4.1-mini",
                "max_tokens": 1000,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )

        if resp.status_code != 200:
            resp_text = resp.text[:200] if resp.text else ""
            if resp.status_code == 429 and "insufficient_quota" in resp_text.lower():
                logger.error(f"[FACTO] OpenAI quota exhausted — skipping")
            else:
                logger.warning(f"[FACTO] OpenAI API error: {resp.status_code} {resp_text}")
            return ""

        return resp.json()["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logger.warning(f"[FACTO] OpenAI call error: {e}")
        return ""


def _parse_triplets_json(raw: str) -> List[FactographicTriplet]:
    """Parse JSON array of factographic triplets from LLM response."""
    try:
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        json_match = re.search(r'\[[\s\S]*\]', raw)
        if not json_match:
            # Salvage truncated JSON
            if raw.strip().startswith('['):
                last_brace = raw.rfind('}')
                if last_brace > 0:
                    salvaged = raw[:last_brace + 1].rstrip().rstrip(',') + '\n]'
                    try:
                        data = json.loads(salvaged)
                        logger.info(f"[FACTO] Salvaged {len(data)} triplets from truncated JSON")
                        return _triplets_from_data(data)
                    except json.JSONDecodeError:
                        pass
            logger.warning(f"[FACTO] No JSON array in response: {raw[:200]}")
            return []

        data = json.loads(json_match.group())
        return _triplets_from_data(data)

    except json.JSONDecodeError as e:
        logger.warning(f"[FACTO] JSON parse error: {e}")
        return []
    except Exception as e:
        logger.error(f"[FACTO] Parse error: {e}")
        return []


def _triplets_from_data(data: list) -> List[FactographicTriplet]:
    """Convert parsed JSON data to FactographicTriplet objects."""
    valid_types = {"spo", "eav"}
    valid_categories = {
        "composition", "property", "definition", "classification",
        "production", "requirement", "location", "temporal", "quantitative",
    }

    triplets = []
    for item in data:
        if not isinstance(item, dict):
            continue

        subject = str(item.get("subject", "")).strip()
        predicate = str(item.get("predicate", "")).strip()
        obj = str(item.get("object", "")).strip()
        t_type = str(item.get("type", "spo")).strip().lower()
        category = str(item.get("category", "property")).strip().lower()
        confidence = float(item.get("confidence", 0.7))

        if not subject or not predicate or not obj:
            continue
        if len(subject) < 2 or len(obj) < 2:
            continue

        if t_type not in valid_types:
            t_type = "spo"
        if category not in valid_categories:
            category = "property"

        triplets.append(FactographicTriplet(
            subject=subject[:80],
            predicate=predicate[:80],
            object=obj[:80],
            triplet_type=t_type,
            category=category,
            confidence=min(0.95, max(0.3, confidence)),
            source_sentence=f"{subject} {predicate} {obj}",
        ))

    return triplets


# ================================================================
# FORMATTING FOR AGENT
# ================================================================

def format_factographic_for_agent(
    triplets: List[FactographicTriplet],
    main_keyword: str,
) -> str:
    """Format factographic triplets as instructions for the writing agent."""
    if not triplets:
        return ""

    lines = [
        f'FAKTY FAKTOGRAFICZNE z top 10 dla "{main_keyword}":',
        "Wpleć te fakty w artykuł (konkretne informacje > ogólniki):",
        "",
    ]

    spo = [t for t in triplets if t.triplet_type == "spo"]
    eav = [t for t in triplets if t.triplet_type == "eav"]

    if spo:
        lines.append("RELACJE SPO (kto/co → robi/jest → co/czym):")
        for t in spo[:8]:
            lines.append(f"  {t.subject} → {t.predicate} → {t.object}")
        lines.append("")

    if eav:
        lines.append("WŁAŚCIWOŚCI EAV (encja → atrybut → wartość):")
        for t in eav[:7]:
            lines.append(f"  {t.subject}: {t.predicate} = {t.object}")
        lines.append("")

    return "\n".join(lines)


# ================================================================
# EXPORTS
# ================================================================

__all__ = [
    'extract_factographic_triplets',
    'format_factographic_for_agent',
    'FactographicTriplet',
]
