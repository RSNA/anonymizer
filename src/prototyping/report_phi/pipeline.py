"""Obsolete EasyOCR×OpenMed letterhead harness (product APIs removed)."""


def run(*_a, **_k):
    raise RuntimeError(
        "prototyping.report_phi is obsolete. "
        "Use anonymizer.controller.ai.embedded_phi.ner.engine.detect_entities "
        "and report.process_report_text for text-layer PDF/SR NER."
    )
