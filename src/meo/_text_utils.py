"""Text utility helpers — truncation and similarity for content quality guards.

These functions are intentionally dependency-free so they can be used
anywhere in the package without pulling in heavy libraries.
"""

from __future__ import annotations

# Japanese sentence-ending punctuation characters.
_SENTENCE_ENDS: frozenset[str] = frozenset("。！？")


def truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate *text* at the last Japanese sentence boundary at or before *max_chars*.

    Searches backwards through the first ``max_chars`` characters for the last
    occurrence of 。！？ and cuts there (inclusive).  Falls back to a hard
    character slice when no sentence-ending punctuation exists in the window —
    the same behaviour as the previous ``text[:max_chars]`` one-liner, but only
    triggered when there is genuinely no clean cut point.

    Returns *text* unchanged when ``len(text) <= max_chars``.
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    for i in range(len(window) - 1, -1, -1):
        if window[i] in _SENTENCE_ENDS:
            return window[: i + 1]
    return window


def char_bigrams(text: str) -> frozenset[str]:
    """Return the set of all character bigrams in *text*.

    An empty string yields an empty frozenset.  A single character also yields
    an empty frozenset (no bigram can be formed).
    """
    return frozenset(text[i : i + 2] for i in range(len(text) - 1))


def jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity of the character-bigram sets of *a* and *b* (0.0–1.0).

    Two identical strings return 1.0.  Two completely disjoint strings return
    0.0.  Two empty strings return 1.0 (vacuously identical).  One empty and
    one non-empty string return 0.0.
    """
    bg_a = char_bigrams(a)
    bg_b = char_bigrams(b)
    if not bg_a and not bg_b:
        return 1.0
    if not bg_a or not bg_b:
        return 0.0
    intersection = len(bg_a & bg_b)
    union = len(bg_a | bg_b)
    return intersection / union


def most_similar_entry(text: str, history: list[dict]) -> tuple[float, str]:
    """Return ``(max_similarity, snippet)`` for the most similar entry in *history*.

    Compares *text* against each ``"text"`` field in *history* using
    :func:`jaccard_similarity`.  Returns the highest similarity score and a
    60-character snippet of the matching entry.  Returns ``(0.0, "")`` when
    *history* is empty or all entries lack a ``"text"`` field.
    """
    best_sim = 0.0
    best_snippet = ""
    for entry in history:
        past = entry.get("text", "")
        if not past:
            continue
        sim = jaccard_similarity(text, past)
        if sim > best_sim:
            best_sim = sim
            best_snippet = past[:60]
    return best_sim, best_snippet
