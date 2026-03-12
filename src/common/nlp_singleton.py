"""
Shared spaCy NLP singleton — prevents loading model multiple times.
Uses pl_core_news_sm (~12MB) to stay within memory limits.
"""
import spacy

_PREFERRED_MODEL = "pl_core_news_sm"
_FALLBACK_MODEL = "pl_core_news_lg"

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
            continue

    print(f"[NLP] Downloading {_PREFERRED_MODEL}...")
    from spacy.cli import download
    download(_PREFERRED_MODEL)
    _nlp = spacy.load(_PREFERRED_MODEL)
    print(f"[NLP] spaCy {_PREFERRED_MODEL} downloaded and loaded")
    return _nlp
