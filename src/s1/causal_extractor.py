"""
===============================================================================
🔗 CAUSAL TRIPLET EXTRACTOR v2.0 (LLM-based)
===============================================================================
v1.0: Regex-based — missed ~90% of causal relations in real text because
      Polish legal/medical prose doesn't follow "X powoduje Y" patterns.

v2.0: LLM-based via OpenAI gpt-4.1-mini (same pattern as PAA fallback).
      Sends combined competitor text → gets structured causal relations.
      Cost: ~$0.002 per call (2-3K input tokens, 300 output tokens).

Integracja: index.py → po entity_seo → dodaje "causal_triplets" do response
===============================================================================
"""

import os
import re
import json
import logging
from typing import List, Dict
from dataclasses import dataclass, asdict
from collections import defaultdict

logger = logging.getLogger(__name__)

try:
    import requests as _requests
except ImportError:
    _requests = None


# ================================================================
# STRUKTURY DANYCH
# ================================================================

@dataclass
class CausalTriplet:
    """Pojedyncza relacja przyczynowo-skutkowa."""
    cause: str
    effect: str
    relation_type: str      # "causes", "prevents", "requires", "enables", "leads_to"
    confidence: float       # 0.0-1.0
    source_sentence: str    # opis relacji
    is_chain: bool = False  # czy element lancucha A->B->C

    def to_dict(self) -> Dict:
        return asdict(self)


# ================================================================
# EKSTRAKCJA (LLM-based)
# ================================================================

def extract_causal_triplets(
    texts: List[str],
    main_keyword: str,
    max_triplets: int = 15
) -> List[CausalTriplet]:
    """
    Wyciaga kauzalne triplety z tresci konkurencji przez LLM.

    v2.0: Zamiast regex, wysyla streszczony tekst do gpt-4.1-mini
    i prosi o strukturalne relacje przyczynowo-skutkowe.
    """
    if not texts or not main_keyword:
        return []

    # Combine texts with limit (~8K chars for context)
    combined = ""
    for t in texts:
        if t and len(combined) < 8000:
            chunk = t.strip()[:3000]
            if len(chunk) > 100:
                combined += chunk + "\n---\n"

    if len(combined) < 200:
        logger.warning("[CAUSAL_V2] Combined text too short, skipping")
        return []

    # LLM extraction
    triplets = _extract_via_llm(combined, main_keyword, max_triplets)

    if triplets:
        _build_chains(triplets)
        triplets.sort(key=lambda t: (-int(t.is_chain), -t.confidence))
        logger.info(f"[CAUSAL_V2] LLM extracted {len(triplets)} triplets "
                    f"({sum(1 for t in triplets if t.is_chain)} chains)")

    return triplets[:max_triplets]


def _extract_via_llm(
    text: str,
    main_keyword: str,
    max_triplets: int
) -> List[CausalTriplet]:
    """Extract causal relations via Anthropic Haiku (primary) or OpenAI (fallback)."""

    if not _requests:
        logger.warning("[CAUSAL_V2] requests module is not available")
        return []

    prompt = (
        f'Przeanalizuj ponizszy tekst z perspektywy tematu "{main_keyword}".\n\n'
        f'Znajdz {max_triplets} najwazniejszych relacji przyczynowo-skutkowych '
        f'(co powoduje co, co z czego wynika, co do czego prowadzi, co czemu zapobiega, '
        f'co jest wymagane do czego).\n\n'
        f'Odpowiedz TYLKO w formacie JSON — tablica obiektow:\n'
        f'[\n'
        f'  {{"cause": "przyczyna", "effect": "skutek", '
        f'"type": "causes|prevents|requires|enables|leads_to", "confidence": 0.8}}\n'
        f']\n\n'
        f'Zasady:\n'
        f'- Wyciagaj relacje FAKTYCZNIE obecne w tekscie, nie wymyslaj\n'
        f'- cause i effect: krotkie frazy (5-50 znakow), nie cale zdania\n'
        f'- confidence: 0.6-0.95 (wyzej = jasniej wyrazone w tekscie)\n'
        f'- Skup sie na relacjach istotnych dla "{main_keyword}"\n'
        f'- Zero komentarzy, TYLKO tablica JSON\n\n'
        f'TEKST:\n{text[:6000]}'
    )

    # Try Anthropic first (primary), then OpenAI (fallback)
    raw = _call_anthropic(prompt) or _call_openai(prompt)
    if not raw:
        return []

    return _parse_triplets_json(raw)


def _call_anthropic(prompt: str) -> str:
    """Call Anthropic Haiku. Returns raw text or empty string."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("[CAUSAL_V2] ANTHROPIC_API_KEY not set, skipping")
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
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )

        if resp.status_code != 200:
            logger.warning(f"[CAUSAL_V2] Anthropic API error: {resp.status_code} {resp.text[:200]}")
            return ""

        data = resp.json()
        content = data.get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "").strip()
        return ""

    except Exception as e:
        logger.warning(f"[CAUSAL_V2] Anthropic call error: {e}")
        return ""


def _call_openai(prompt: str) -> str:
    """Call OpenAI gpt-4.1-mini (fallback). Returns raw text or empty string."""
    oai_key = os.getenv("OPENAI_API_KEY")
    if not oai_key:
        logger.debug("[CAUSAL_V2] OPENAI_API_KEY not set, skipping fallback")
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
                "max_tokens": 800,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )

        if resp.status_code != 200:
            resp_text = resp.text[:200] if resp.text else ""
            if resp.status_code == 429 and "insufficient_quota" in resp_text.lower():
                logger.error(f"[CAUSAL_V2] OpenAI quota exhausted (insufficient_quota) — skipping")
            else:
                logger.warning(f"[CAUSAL_V2] OpenAI API error: {resp.status_code} {resp_text}")
            return ""

        return resp.json()["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logger.warning(f"[CAUSAL_V2] OpenAI call error: {e}")
        return ""


def _parse_triplets_json(raw: str) -> List[CausalTriplet]:
    """Parse JSON array of triplets from LLM response."""
    try:
        # Handle markdown code blocks
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        # Find JSON array
        json_match = re.search(r'\[[\s\S]*\]', raw)
        if not json_match:
            # v59.1 FIX: Handle truncated JSON (max_tokens cut off mid-response)
            # If response starts with '[' but no closing ']', try to salvage
            if raw.strip().startswith('['):
                # Find last complete object (ends with '}')
                last_brace = raw.rfind('}')
                if last_brace > 0:
                    salvaged = raw[:last_brace + 1].rstrip().rstrip(',') + '\n]'
                    try:
                        data = json.loads(salvaged)
                        logger.info(f"[CAUSAL_V2] Salvaged {len(data)} triplets from truncated JSON")
                        return _triplets_from_data(data)
                    except json.JSONDecodeError:
                        pass
            logger.warning(f"[CAUSAL_V2] No JSON array in response: {raw[:200]}")
            return []

        data = json.loads(json_match.group())
        return _triplets_from_data(data)

    except json.JSONDecodeError as e:
        logger.warning(f"[CAUSAL_V2] JSON parse error: {e}")
        return []
    except Exception as e:
        logger.error(f"[CAUSAL_V2] Parse error: {e}")
        return []


def _triplets_from_data(data: list) -> List[CausalTriplet]:
    """Convert parsed JSON data to CausalTriplet objects."""
    valid_types = {"causes", "prevents", "requires", "enables", "leads_to",
                   "may_cause", "results_from", "initiates", "treats"}

    triplets = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cause = str(item.get("cause", "")).strip()
        effect = str(item.get("effect", "")).strip()
        rel_type = str(item.get("type", "causes")).strip()
        confidence = float(item.get("confidence", 0.7))

        if not cause or not effect or len(cause) < 3 or len(effect) < 3:
            continue

        if rel_type not in valid_types:
            rel_type = "causes"

        triplets.append(CausalTriplet(
            cause=cause[:80],
            effect=effect[:80],
            relation_type=rel_type,
            confidence=min(0.95, max(0.3, confidence)),
            source_sentence=f"{cause} -> {effect}",
        ))

    return triplets


# ================================================================
# CHAIN BUILDER
# ================================================================

def _build_chains(triplets: List[CausalTriplet]) -> None:
    """
    Oznacza triplety bedace czescia lancuchow.
    Jesli A->B i B->C istnieja, oba dostaja is_chain=True.
    """
    effect_index = defaultdict(list)
    for t in triplets:
        effect_key = " ".join(t.effect.lower().split()[:3])
        effect_index[effect_key].append(t)

    for t in triplets:
        cause_key = " ".join(t.cause.lower().split()[:3])
        if cause_key in effect_index:
            t.is_chain = True
            for linked in effect_index[cause_key]:
                linked.is_chain = True


# ================================================================
# FORMATOWANIE DLA AGENTA
# ================================================================

def format_causal_for_agent(
    triplets: List[CausalTriplet],
    main_keyword: str
) -> str:
    """Formatuje kauzalne triplety jako instrukcje dla agenta GPT."""
    if not triplets:
        return ""

    lines = [
        f'RELACJE PRZYCZYNOWO-SKUTKOWE z top 10 dla "{main_keyword}":',
        "Wplec te relacje w artykul (wyjasniaj DLACZEGO, nie tylko CO):",
        ""
    ]

    chains = [t for t in triplets if t.is_chain]
    singles = [t for t in triplets if not t.is_chain]

    if chains:
        lines.append("LANCUCHY (A->B->C):")
        for t in chains[:5]:
            rel_label = _relation_label(t.relation_type)
            lines.append(f"  {t.cause} {rel_label} {t.effect}")
        lines.append("")

    if singles:
        lines.append("RELACJE KAUZALNE:")
        for t in singles[:8]:
            rel_label = _relation_label(t.relation_type)
            lines.append(f"  {t.cause} {rel_label} {t.effect}")
        lines.append("")

    return "\n".join(lines)


def _relation_label(rel_type: str) -> str:
    """Zamienia typ relacji na czytelna etykiete."""
    labels = {
        "causes": "-> powoduje ->",
        "may_cause": "-> moze powodowac ->",
        "prevents": "-> zapobiega ->",
        "requires": "-> wymaga ->",
        "enables": "-> umozliwia ->",
        "results_from": "<- wynika z <-",
        "required_for": "-> jest wymagane do ->",
        "omission_causes": "-> [brak] skutkuje ->",
        "initiates": "-> rozpoczyna ->",
        "untreated_causes": "-> [nieleczone] prowadzi do ->",
        "treats": "-> lagodzi ->",
        "deficiency_causes": "-> [niedobor] powoduje ->",
        "leads_to": "-> prowadzi do ->",
    }
    return labels.get(rel_type, "->")


# ================================================================
# EXPORTS
# ================================================================

__all__ = [
    'extract_causal_triplets',
    'format_causal_for_agent',
    'CausalTriplet',
]
