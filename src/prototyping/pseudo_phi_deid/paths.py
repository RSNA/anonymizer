"""Pseudo-PHI dataset defaults and results roots."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PACKAGE_DIR / "results"
SCRIPTS_DIR = PACKAGE_DIR / "scripts"
# Packaged product script (prototyping does not rely on install-dir chdir).
PACKAGED_DEFAULT_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "anonymizer"
    / "assets"
    / "scripts"
    / "default-anonymizer.script"
)

DEFAULT_PSEUDO_PHI_ROOT = Path("/Users/michaelevans/DATA/Pseudo-PHI-DICOM-Dataset")
DEFAULT_EVAL_DIR = (
    DEFAULT_PSEUDO_PHI_ROOT
    / "Evaluation"
    / "manifest-1617826555824"
    / "Pseudo-PHI-DICOM-Data"
)
DEFAULT_DEID_DIR = (
    DEFAULT_PSEUDO_PHI_ROOT
    / "DeIdentified"
    / "manifest-1617826161202"
    / "Pseudo-PHI-DICOM-Data_DEID"
)
DEFAULT_PATID_CROSSWALK = (
    DEFAULT_PSEUDO_PHI_ROOT / "Pseudo-PHI-DICOM-Dataset-patid_crosswalk.csv"
)
DEFAULT_UID_CROSSWALK = (
    DEFAULT_PSEUDO_PHI_ROOT / "Pseudo-PHI-DICOM-Dataset-uid_crosswalk.csv"
)


def phase_dir(phase: int, slug: str) -> Path:
    return RESULTS_DIR / f"phase_{phase}_{slug}"
