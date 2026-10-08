"""Cached radiology lexicon for OpenMed NAME false-positive guarding."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from anonymizer.controller.ai.embedded_phi.ner.locale_registry import load_ocr_whitelist_terms
from anonymizer.controller.ai.embedded_phi.term_similarity import similarity_term_match

logger = logging.getLogger(__name__)

GuardKind = Literal["exact", "fuzzy"]

# NAME-guard fuzzy thresholds (stricter than OCR hide-text defaults).
NAME_LEXICON_SIMILARITY = 0.85
NAME_LEXICON_MIN_LENGTH_RATIO = 0.75
NAME_LEXICON_MIN_FUZZY_LEN = 4

_STOPWORDS = frozenset(
    {
        "and",
        "or",
        "the",
        "of",
        "a",
        "an",
        "to",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "without",
        "plus",
        "vs",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-']{2,}")


@dataclass(frozen=True)
class RadiologyLexicon:
    """Exact membership set + smaller fuzzy term list for NAME drops."""

    exact: frozenset[str]
    fuzzy: tuple[str, ...]


def _norm(term: str) -> str:
    return term.casefold().strip()


def _add(sink: set[str], term: str) -> None:
    n = _norm(term)
    if n:
        sink.add(n)


def _radlex_display_labels() -> set[str]:
    """Playbook / planar surface strings (lazy — playbook pulls Harmonize deps)."""
    from anonymizer.controller.ai.harmonize import playbook as pb
    from anonymizer.controller.ai.harmonize.playbook_planar import _PLANAR_ANATOMY_CATALOG

    out: set[str] = set()
    for mapping in (
        pb._BODY_PART_MSGIDS,
        pb._PLANE_MSGIDS,
        pb._IV_CONTRAST_MSGIDS,
        pb._LATERALITY_MSGIDS,
        pb._LUMINAL_CONTRAST_MSGIDS,
        pb._VIEW_MSGIDS,
        pb._SERIES_TYPE_MSGIDS,
        pb._SERIES_TYPE_MODIFIER_MSGIDS,
        pb._KERNEL_MSGIDS,
    ):
        for label in mapping.values():
            _add(out, label)
            # Also keep short codes that appear on overlays (WO, W, Ax, …).
    for code in (
        *pb._BODY_PART_MSGIDS.keys(),
        *pb._PLANE_MSGIDS.keys(),
        *pb._IV_CONTRAST_MSGIDS.keys(),
        *pb._VIEW_MSGIDS.keys(),
    ):
        if len(code) >= 2 and "_" not in code:
            _add(out, code.replace("-", " "))
    for label in _PLANAR_ANATOMY_CATALOG:
        _add(out, label)
    # Prefer gettext-expanded body-part labels when available.
    for code in pb.BODY_PART_PLAYBOOK_CODES:
        try:
            _add(out, pb.body_part_label(code))
        except Exception:  # noqa: BLE001
            continue
    return out


def _loinc_terms() -> set[str]:
    from anonymizer.controller.ai.harmonize.loinc_study import load_loinc_study_descriptions

    out: set[str] = set()
    try:
        rows = load_loinc_study_descriptions()
    except Exception:  # noqa: BLE001
        return out
    for _code, name in rows:
        n = _norm(name)
        if not n:
            continue
        _add(out, n)
        # Leading modality token(s): "CT Abdomen …", "US.doppler …"
        head = n.split(None, 1)[0]
        if head and not head.isdigit():
            _add(out, head.split(".", 1)[0])
        for tok in _TOKEN_RE.findall(n):
            t = tok.casefold()
            if t in _STOPWORDS or t.isdigit() or len(t) < 4:
                continue
            _add(out, t)
    return out


def _build_lexicon(locale: str) -> RadiologyLexicon:
    whitelist = {_norm(t) for t in load_ocr_whitelist_terms(locale)}
    radlex = _radlex_display_labels()
    loinc = _loinc_terms()
    exact = frozenset(whitelist | radlex | loinc)
    # Fuzzy: whitelist + RadLex only (not full LOINC LongCommonNames).
    fuzzy_terms = sorted({t for t in (whitelist | radlex) if len(t) >= NAME_LEXICON_MIN_FUZZY_LEN})
    return RadiologyLexicon(exact=exact, fuzzy=tuple(fuzzy_terms))


@dataclass(frozen=True)
class LexiconGuardHit:
    """Why a NAME span was suppressed as radiology vocabulary (not patient PHI)."""

    kind: GuardKind
    fragment: str
    matched_term: str | None = None
    similarity: float = 0.0


@lru_cache(maxsize=8)
def get_radiology_lexicon(locale: str = "en_US") -> RadiologyLexicon:
    """Cached lexicon for *locale* (whitelist path falls back to en_US)."""
    return _build_lexicon(locale or "en_US")


def radiology_lexicon_name_guard(frag: str, *, locale: str = "en_US") -> LexiconGuardHit | None:
    """Return a hit when a NAME fragment should be dropped as radiology vocabulary."""
    text = frag.casefold().strip()
    if not text:
        return None
    lex = get_radiology_lexicon(locale)
    if text in lex.exact:
        return LexiconGuardHit(kind="exact", fragment=text, matched_term=text)
    if len(text) < NAME_LEXICON_MIN_FUZZY_LEN:
        return None
    hit = similarity_term_match(
        text,
        lex.fuzzy,
        threshold=NAME_LEXICON_SIMILARITY,
        min_length_ratio=NAME_LEXICON_MIN_LENGTH_RATIO,
        min_term_len=NAME_LEXICON_MIN_FUZZY_LEN,
        min_text_len=NAME_LEXICON_MIN_FUZZY_LEN,
    )
    if not hit.matched:
        return None
    return LexiconGuardHit(
        kind="fuzzy",
        fragment=text,
        matched_term=(hit.term or "").casefold() or None,
        similarity=hit.similarity,
    )


def name_matches_radiology_lexicon(frag: str, *, locale: str = "en_US") -> bool:
    """True when a NAME fragment should be dropped as radiology vocabulary."""
    return radiology_lexicon_name_guard(frag, locale=locale) is not None


def log_name_lexicon_guard(hit: LexiconGuardHit) -> None:
    """INFO log for a suppressed OpenMed NAME (fragment only — no surrounding PHI)."""
    if hit.kind == "exact":
        logger.info(
            "NAME guard: dropped OpenMed NAME %r (lexicon exact)",
            hit.fragment,
        )
        return
    logger.info(
        "NAME guard: dropped OpenMed NAME %r (lexicon fuzzy matched %r similarity=%.3f)",
        hit.fragment,
        hit.matched_term,
        hit.similarity,
    )
