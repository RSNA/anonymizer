"""English (US) PATIENT_IDENTIFIER / PHONE / EMAIL pattern packs."""

import re

# Locale → model ids (resolved by LocaleRegistry).
SPACY_MODEL = "en_core_web_sm"
# Smaller clinical/PII token classifier (~33M) for offline pin + eval.
HF_DEID_MODEL = "OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1"
# Keep Longformer slot on the same id until a true long-context checkpoint is chosen.
HF_LONGFORMER_MODEL = "OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1"

# DICOM UID-like dotted OID (reject as PATIENT_IDENTIFIER).
UID_RE = re.compile(r"\b(?:\d+\.){3,}\d+\b")

# MRN / patient id after cue words (word-boundary before cue; avoid FAKE-MRN-001).
# Value must contain a digit so "medical record number" (trailing word) is not an ID.
MRN_VALUE_RE = re.compile(
    r"(?i)(?:"
    r"(?<![A-Za-z0-9])(?:mrn|mr\s*#|med(?:ical)?\s*rec(?:ord)?(?:\s*(?:no|num(?:ber)?|#))?|"
    r"patient\s*id|patientid|subject\s*id|chart\s*(?:no|num(?:ber)?|#)?|"
    r"unit\s*(?:no|num(?:ber)?)|acc(?:t|ount)(?:\s*(?:no|num(?:ber)?|#))?|"
    r"visit\s*(?:id|#|num(?:ber)?)?|encounter(?:\s*(?:id|#))?|fin|"
    r"case\s*(?:no|num(?:ber)?)|accession(?:\s*(?:no|num(?:ber)?|#))?|acc\s*#|"
    r"medicare(?:\s*id)?|medicaid(?:\s*id)?|"
    r"ssn|social\s*security(?:\s*(?:no|num(?:ber)?)?))"
    r"(?:[:#=]\s*|\s+)"  # punctuation or whitespace; not bare hyphen (avoids FAKE-MRN-001)
    r")(?=[A-Z0-9\-]*\d)([A-Z0-9][A-Z0-9\-]{2,20})",
)

# Bare alnum ID when preceded by ID# / ID:
ID_HASH_RE = re.compile(r"(?i)\bid\s*[#:]\s*([A-Z0-9][A-Z0-9\-]{2,20})")

# Require punctuation or +country so bare UID digit runs are not phones.
PHONE_RE = re.compile(
    r"(?<!\d)(?:"
    r"\+1[\s\-.]+\d{3}[\s\-.]+\d{3}[\s\-.]+\d{4}"
    r"|"
    r"\(\d{3}\)\s*\d{3}[\s\-.]\d{4}"
    r"|"
    r"\d{3}[\s\-.]\d{3}[\s\-.]\d{4}"
    r")"
    r"(?:\s*(?:x|ext\.?)\s*\d{1,6})?"
    r"(?!\d)",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(
    r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
)

# Technique / protocol numbers — not patient identifiers.
TECHNIQUE_CONTEXT_RE = re.compile(
    r"(?i)\b(?:kvp|mas|protocol|series|instance|frame|slice|thickness|station)\b",
)
