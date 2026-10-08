"""Presidio PatternRecognizers built from the locale ID/date packs (single source)."""

from __future__ import annotations

from typing import Any

from prototyping.metadata_phi.locale_registry import get_locale_pack


def build_pattern_recognizers(locale: str = "en_US") -> list[Any]:
    """Return Presidio PatternRecognizer instances for PATIENT_IDENTIFIER / PHONE / EMAIL."""
    from presidio_analyzer import Pattern, PatternRecognizer

    pack = get_locale_pack(locale)
    id_mod = pack.id_patterns_module

    recognizers: list[Any] = []

    # Use the same MRN cue regex as the locale pack (group 0 = full match for Presidio).
    mrn_pat = Pattern(
        name="locale_mrn_cue",
        regex=id_mod.MRN_VALUE_RE.pattern,
        score=0.65,
    )
    recognizers.append(
        PatternRecognizer(
            supported_entity="MRN",
            name="LocaleMrnRecognizer",
            patterns=[mrn_pat],
            supported_language="en",
        )
    )

    id_hash = Pattern(name="locale_id_hash", regex=id_mod.ID_HASH_RE.pattern, score=0.55)
    recognizers.append(
        PatternRecognizer(
            supported_entity="MRN",
            name="LocaleIdHashRecognizer",
            patterns=[id_hash],
            supported_language="en",
        )
    )

    ssn = Pattern(
        name="locale_ssn_hyphen",
        regex=r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)",
        score=0.7,
    )
    recognizers.append(
        PatternRecognizer(
            supported_entity="US_SSN",
            name="LocaleSsnRecognizer",
            patterns=[ssn],
            supported_language="en",
        )
    )

    phone = Pattern(name="locale_phone", regex=id_mod.PHONE_RE.pattern, score=0.65)
    recognizers.append(
        PatternRecognizer(
            supported_entity="PHONE_NUMBER",
            name="LocalePhoneRecognizer",
            patterns=[phone],
            supported_language="en",
        )
    )

    email = Pattern(name="locale_email", regex=id_mod.EMAIL_RE.pattern, score=0.8)
    recognizers.append(
        PatternRecognizer(
            supported_entity="EMAIL_ADDRESS",
            name="LocaleEmailRecognizer",
            patterns=[email],
            supported_language="en",
        )
    )

    return recognizers
