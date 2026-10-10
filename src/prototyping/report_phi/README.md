# Report PHI experiment — **obsolete**

Product Report View is text-layer NER only (`report/process_report_text.py` + `ner/ner.py`).
This EasyOCR letterhead harness no longer imports product APIs (deleted `pdf_ocr` / hybrid `detect_phi`).

Use product logs from `detect_entities` / `detect_phi` when evaluating PDF/SR text.
Series View / `pixel_report` OCR remains under `embedded_phi/pixel/`.
