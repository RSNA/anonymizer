"""Metadata-only Harmonize profiles for XR (CR/DX), US, and MG.

Isolated from :mod:`anonymizer.controller.ai.tseg.modality_profile` — never uses
TotalSegmentator. SC / OT / DOC and other modalities resolve to None.
"""

from __future__ import annotations

from dataclasses import dataclass

from anonymizer.utils.modalities import normalize_modality, planar_harmonize_cohort


@dataclass(frozen=True)
class PlanarModalityProfile:
    """Frozen strategy for one planar (non-3D) Harmonize modality cohort."""

    cohort: str  # "XR" | "US" | "MG"
    modality_codes: tuple[str, ...]
    loinc_prefix: str
    uses_tseg: bool = False


def xr_modality_profile() -> PlanarModalityProfile:
    return PlanarModalityProfile(
        cohort="XR",
        modality_codes=("CR", "DX"),
        loinc_prefix="XR ",
    )


def us_modality_profile() -> PlanarModalityProfile:
    return PlanarModalityProfile(
        cohort="US",
        modality_codes=("US",),
        loinc_prefix="US ",
    )


def mg_modality_profile() -> PlanarModalityProfile:
    return PlanarModalityProfile(
        cohort="MG",
        modality_codes=("MG",),
        loinc_prefix="MG ",
    )


def planar_profile_for_modality(value: object | None) -> PlanarModalityProfile | None:
    """Resolve a planar Harmonize profile, or None for CT/MR/SC/OT/DOC/others."""
    cohort = planar_harmonize_cohort(value)
    if cohort == "XR":
        return xr_modality_profile()
    if cohort == "US":
        return us_modality_profile()
    if cohort == "MG":
        return mg_modality_profile()
    return None


def planar_profile_from_dataset(ds: object | None) -> PlanarModalityProfile | None:
    modality = getattr(ds, "Modality", None) if ds is not None else None
    return planar_profile_for_modality(modality)


def resolve_planar_profile_for_series(series_directory: object) -> PlanarModalityProfile | None:
    """Load the first DICOM header and resolve a planar profile (None for CT/MR)."""
    from anonymizer.controller.ai.tseg.modality_profile import load_series_header_dataset

    ds = load_series_header_dataset(series_directory)
    if ds is None:
        return None
    return planar_profile_from_dataset(ds)


def loinc_prefix_for_planar_cohort(cohort: str, *, doppler: bool = False, dbt: bool = False, ffd: bool = False) -> str:
    """LOINC LongCommonName prefix for a planar study."""
    if cohort == "US" and doppler:
        return "US.doppler "
    if cohort == "MG" and dbt:
        return "DBT "
    if cohort == "MG" and ffd:
        return "FFD "
    if cohort == "XR":
        return "XR "
    if cohort == "US":
        return "US "
    if cohort == "MG":
        return "MG "
    raise ValueError(f"Unknown planar cohort: {cohort!r}")


def normalize_planar_modality_label(value: object | None) -> str:
    """Uppercase modality; map CR/DX → XR for logging."""
    code = normalize_modality(value)
    if code in {"CR", "DX"}:
        return "XR"
    return code
