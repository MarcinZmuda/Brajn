import re
from collections import Counter

def synthesize_topics(ngrams, headings):
    """
    Analizuje listy n-gramów i nagłówków H2, zwracając tematy i ich częstotliwości.
    """
    def get_themes(text_list):
        words = re.findall(r'\b\w{3,}\b', ' '.join(text_list).lower())
        return [theme for theme, _ in Counter(words).most_common(10)]

    ngram_themes = get_themes(ngrams)
    heading_themes = get_themes(headings)
    all_themes = sorted(list(set(ngram_themes + heading_themes)))

    topic_importance = []
    for theme in all_themes:
        h_freq = sum(1 for h in headings if theme in h.lower())
        n_freq = sum(1 for n in ngrams if theme in n.lower())
        if h_freq > 0 or n_freq > 0:
            topic_importance.append({
                "theme": theme,
                "h2_frequency": h_freq,
                "ngram_frequency": n_freq
            })

    return {"topic_importance": topic_importance}
