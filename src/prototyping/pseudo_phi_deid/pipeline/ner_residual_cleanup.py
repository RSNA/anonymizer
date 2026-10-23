"""Step 6 — post-NER residual text cleanup (PseudoPHI header path).

After taxonomy scrub blanks NER spans, free-text fields often keep dangling
prepositions (``… for``), site prefixes (``FORFILE``), and month+year tokens
(``Sep1999``) that gold removes. This step strips those residues only.

Does not invent values, does not restore over-blanked tokens (those need
``@safe()`` / script policy), and does not touch private creators.
"""

import logging
import re

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.extract import TEXT_VRS

logger = logging.getLogger(__name__)

# FORFILE / ForFile as a leading or standalone token (site export prefix).
_FORFILE = re.compile(r"(?i)\bFOR\s*FILE\b|\bFORFILE\b")

# Dangling "for" left after a name blank (end of string or before punctuation).
_DANGLING_FOR = re.compile(r"(?i)(?:\s+for)+\s*$")
# " for " mid-string with nothing useful after (collapsed later).
_FOR_BEFORE_PUNCT = re.compile(r"(?i)\s+for(?=\s*[|,;/.-]*\s*$)")
# " for <digits>" — patient-id residue after name blank (not "for Patient").
_FOR_DIGITS = re.compile(r"(?i)\s+for\s+\d+\s*$")

# Month name + year, glued or spaced: Sep1999, Sep 1999, September-99, Sep199.
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)"
)
_MONTH_YEAR = re.compile(
    rf"(?i)(?:^|[\s|/_,;-]){_MONTH}\.?\s*-?\s*\d{{2,4}}\b"
)

# Standalone trailing "file" residue after FORFILE partial blank (rare).
_DANGLING_FILE = re.compile(r"(?i)(?:\s+file)+\s*$")


def cleanup_residual_text(text: str) -> str:
    """Strip NER/site/date residues from a free-text DICOM string."""
    if not text:
        return text
    out = str(text)
    out = _FORFILE.sub(" ", out)
    out = _MONTH_YEAR.sub(" ", out)
    out = _FOR_DIGITS.sub("", out)
    out = _DANGLING_FOR.sub("", out)
    out = _FOR_BEFORE_PUNCT.sub("", out)
    out = _DANGLING_FILE.sub("", out)
    # Collapse whitespace only — do not strip trailing commas/units
    # (e.g. AttenuationCorrectionMethod ``…cm-1,``).
    out = " ".join(out.split())
    return out


def cleanup_dataset_residuals(ds: Dataset) -> int:
    """Walk TEXT_VRs; apply :func:`cleanup_residual_text`. Returns fields changed."""
    changed = 0

    def walk(current: Dataset) -> None:
        nonlocal changed
        for elem in current:
            if elem.VR == "SQ" and elem.value:
                for item in elem.value:
                    if isinstance(item, Dataset):
                        walk(item)
                continue
            if elem.VR not in TEXT_VRS:
                continue
            try:
                raw = str(elem.value) if elem.value is not None else ""
            except Exception:
                continue
            if not raw.strip():
                continue
            cleaned = cleanup_residual_text(raw)
            if cleaned != raw:
                try:
                    elem.value = cleaned
                    changed += 1
                except Exception as exc:
                    logger.warning("residual cleanup write failed %s: %s", elem.tag, exc)

    walk(ds)
    if changed:
        logger.debug("step6.residual_cleanup: fields_changed=%d", changed)
    return changed
