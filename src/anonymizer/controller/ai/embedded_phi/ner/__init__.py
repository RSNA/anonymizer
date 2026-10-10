"""Free-text PHI NER (OpenMed model-only).

Submodules
----------
``ner.ner``
    Detect and replace PHI in unicode text.

    - ``Entity`` — ``label`` + ``start``/``end``; optional ``replacement`` (metadata PHI)
    - ``detect_entities(text, *, locale=\"en_US\")`` → ``list[Entity]``
    - ``replace_entities(text, entities=None, *, mode=\"blank\"|\"synth\", …)``
      → ``(new_text, entities_used)``; ``replacement`` always written when set
    - ``detect_locale_supported(locale)`` → bool
    - ``SCORED_LABELS``, ``SUPPORTED_DETECT_LOCALES``, ``ReplaceMode``

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

Import from the concrete submodule (not this package)::

    from anonymizer.controller.ai.embedded_phi.ner.ner import (
        Entity,
        detect_entities,
        replace_entities,
    )
    from anonymizer.controller.ai.embedded_phi.ner.cache import ner_ready
"""
