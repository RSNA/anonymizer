"""External real-data loaders for metadata PHI eval (local trees)."""

from __future__ import annotations

__all__ = [
    "DEFAULT_OPENI_DIR",
    "DEFAULT_TCIA_SR_DIR",
    "DEFAULT_REXERR_DIR",
    "DEFAULT_PSEUDO_PHI_ROOT",
    "DEFAULT_PSEUDO_PHI_EVAL_DIR",
    "DEFAULT_PSEUDO_PHI_DEID_DIR",
    "DEFAULT_HEROLIM_SR_DIR",
    "DEFAULT_MIDI_B_VAL_DIR",
]

DEFAULT_OPENI_DIR = "/Users/michaelevans/DATA/OpenI_NLMCXR/ecgen-radiology"
DEFAULT_TCIA_SR_DIR = "/Users/michaelevans/DATA/SR_wgllssg1"
# PhysioNet ReXErr-v1 report-level CSVs (original_report column).
DEFAULT_REXERR_DIR = (
    "/Users/michaelevans/DATA/mimic-cxr-reports/ReXErr-v1/ReXErr-report-level"
)
DEFAULT_PSEUDO_PHI_ROOT = "/Users/michaelevans/DATA/Pseudo-PHI-DICOM-Dataset"
DEFAULT_PSEUDO_PHI_EVAL_DIR = f"{DEFAULT_PSEUDO_PHI_ROOT}/Evaluation"
DEFAULT_PSEUDO_PHI_DEID_DIR = f"{DEFAULT_PSEUDO_PHI_ROOT}/DeIdentified"
# Real-world X-Ray Radiation Dose SR (local only; contains real PHI — never commit).
DEFAULT_HEROLIM_SR_DIR = "/Users/michaelevans/DATA/HEROLIM SR"
# NIH MIDI-B 2024 validation set — held out for final prototype test (not used to pick methods).
DEFAULT_MIDI_B_VAL_DIR = "/Users/michaelevans/DATA/MIDI-B-2024-VAL"
