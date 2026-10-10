"""Native report text PHI (SR / Encapsulated PDF).

Detect matches study PHI metadata strings (DICOM keyword labels + anon
``replacement``) then NER on the same original text (metadata wins overlaps).
Remove writes anon DICOM values for metadata entities; NER blank/synth.

Public API::

    from anonymizer.controller.ai.embedded_phi.report.process_report_text import (
        detect_phi,
        remove_phi,
        write_report_text,
        render_pdf_pages,
    )
"""
