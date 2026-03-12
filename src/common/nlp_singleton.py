"""
Shared spaCy NLP singleton — prevents loading model multiple times.
Tries pl_core_news_lg first (better NER), falls back to sm.
"""
import spacy

_PREFERRED_MODEL = "pl_core_news_lg"
_FALLBACK_MODEL = "pl_core_news_sm"

_nlp = None


def get_nlp():
    """Return shared spaCy NLP instance (lazy singleton)."""
    global _nlp
    if _nlp is not None:
        return _nlp

    for model in (_PREFERRED_MODEL, _FALLBACK_MODEL):
        try:
            _nlp = spacy.load(model)
            print(f"[NLP] spaCy {model} loaded (singleton)")
            return _nlp
        except OSError:
            print(f"[NLP] {model} not installed, trying next...")
            continue

    # Last resort: download sm (always available)
    print(f"[NLP] Downloading {_FALLBACK_MODEL}...")
    try:
        from spacy.cli import download
        download(_FALLBACK_MODEL)
        _nlp = spacy.load(_FALLBACK_MODEL)
        print(f"[NLP] spaCy {_FALLBACK_MODEL} downloaded and loaded")
    except Exception as e:
        print(f"[NLP] FATAL: cannot load any spaCy model: {e}")
        raise RuntimeError(f"spaCy model unavailable: {e}")
    return _nlp
