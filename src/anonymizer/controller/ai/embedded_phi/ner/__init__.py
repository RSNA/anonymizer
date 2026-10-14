"""Free-text PHI NER (OpenMed model-only).

Submodules
----------
``ner.engine``
    Detect and replace PHI in unicode text.

    - ``Entity`` — ``label`` + ``start``/``end``; optional ``replacement`` (metadata PHI)
    - ``detect_entities(text, *, locale=\"en_US\")`` → ``list[Entity]``
    - ``detect_entities_in_segments(segments, …)`` → per-segment entities (chunked on field breaks)
    - ``replace_entities(text, entities=None, *, mode=\"blank\"|\"synth\", …)``
      → ``(new_text, entities_used)``; ``replacement`` always written when set
    - ``detect_locale_supported(locale)`` → bool
    - ``SCORED_LABELS``, ``SUPPORTED_DETECT_LOCALES``, ``ReplaceMode``, ``SEGMENT_SEP``

``ner.cache``
    OpenMed DeID weight download / readiness.

    - ``ner_ready()`` → bool
    - ``probe_ner_models()`` → ``(NerModelStatus, message)``
    - ``download_ner_models(*, locale=\"en_US\")`` → ``(ok, message)``
    - ``remove_ner_models()``
    - ``NerModelStatus`` — ``READY`` / ``MISSING`` / ``DOWNLOADING`` / ``FAILED``

``ner.synthetic_phi``
    Offline HMAC-seeded replacements (used when ``mode=\"synth\"``).

    - ``generate_synthetic_phi(label, *, project_id, anon_ptid, …)`` → str

``ner.radiology_filters``
    Pre-NER filters (Metadata + Report). Metadata: ``prepare_metadata_ner_segments``.
    Report: ``mask_text_for_ner``. Not Report study-PHI matching.

Import from the concrete submodule (not this package)::

    from anonymizer.controller.ai.embedded_phi.ner.engine import (
        Entity,
        detect_entities,
        detect_entities_in_segments,
        replace_entities,
    )
    from anonymizer.controller.ai.embedded_phi.ner.cache import ner_ready
    from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import (
        mask_text_for_ner,
        prepare_metadata_ner_segments,
    )
"""
