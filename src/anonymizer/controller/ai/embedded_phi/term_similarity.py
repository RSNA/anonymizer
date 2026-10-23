"""Shared string similarity matching for OCR modality whitelists.

Public API
----------
SimilarityMatchResult
    SimilarityMatchResult type.

similarity_term_match(text: str, terms: Sequence[str], *, threshold: float, min_length_ratio: float=0.7, min_term_len: int=1, min_text_len: int=1) -> SimilarityMatchResult
    Best difflib.SequenceMatcher hit of *text* against *terms*.
"""
import difflib
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SimilarityMatchResult:
    matched: bool
    term: str | None = None
    similarity: float = 0.0


def similarity_term_match(
    text: str,
    terms: Sequence[str],
    *,
    threshold: float,
    min_length_ratio: float = 0.7,
    min_term_len: int = 1,
    min_text_len: int = 1,
) -> SimilarityMatchResult:
    """
    Best difflib.SequenceMatcher hit of *text* against *terms*.

    Both sides are compared uppercased. Terms shorter than min_term_len and
    text shorter than min_text_len are skipped (callers use exact membership
    for short view codes).
    """
    processed = text.upper().strip()
    if len(processed) < min_text_len:
        return SimilarityMatchResult(matched=False)
    best_term: str | None = None
    best_similarity = 0.0
    for item in terms:
        if not item:
            continue
        candidate = item.upper().strip()
        if len(candidate) < min_term_len:
            continue
        length_ratio = min(len(processed), len(candidate)) / max(len(processed), len(candidate))
        if length_ratio < min_length_ratio:
            continue
        similarity = difflib.SequenceMatcher(None, processed, candidate).ratio()
        if similarity > threshold and similarity > best_similarity:
            best_similarity = similarity
            best_term = candidate
    if best_term is not None:
        return SimilarityMatchResult(matched=True, term=best_term, similarity=best_similarity)
    return SimilarityMatchResult(matched=False)
