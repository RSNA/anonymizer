"""Native report text PHI for SR and Encapsulated PDF (post-ingest).

Detect matches study PHI metadata strings then NER; remove writes anon
DICOM values for metadata entities or NER blank/synth replacements.

Public API
----------
(none)
    Import process_report_text (detect_phi, remove_phi, write_report_text, …).
"""
