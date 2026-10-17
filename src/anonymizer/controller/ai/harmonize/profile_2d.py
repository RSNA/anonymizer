"""Metadata-only Harmonize profiles for 2D modalities (CR/DX, US, MG).

Isolated from :mod:`anonymizer.controller.ai.tseg.modality_profile` — never uses
TotalSegmentator.
"""

from __future__ import annotations

from dataclasses import dataclass

from anonymizer.controller.ai.tseg.modality_profile import load_series_header_dataset
from anonymizer.utils.modalities import XR_MODALITIES, Modality


@dataclass(frozen=True)
class Profile2D:
    """Frozen strategy for one 2D Harmonize playbook."""

    modalities: tuple[Modality, ...]
    loinc_prefix: str


def xr_profile() -> Profile2D:
    """CR/DX shared XR playbook."""
    return Profile2D(
        modalities=(Modality.CR, Modality.DX),
        loinc_prefix="XR ",
    )


def us_profile() -> Profile2D:
    """Ultrasound playbook."""
    return Profile2D(
        modalities=(Modality.US,),
        loinc_prefix="US ",
    )


def mg_profile() -> Profile2D:
    """Mammography playbook."""
    return Profile2D(
        modalities=(Modality.MG,),
        loinc_prefix="MG ",
    )


def profile_2d_for_modality(value: str | Modality | None) -> Profile2D | None:
    """
    Resolve a 2D Harmonize profile, or None when not a 2D playbook modality.

    Args:
        value: Modality enum or string code.

    Returns:
        Profile2D for CR/DX, US, or MG; otherwise None.
    """
    modality = value if isinstance(value, Modality) else Modality.from_code(value)
    if modality is None:
        return None
    if modality in XR_MODALITIES:
        return xr_profile()
    if modality is Modality.US:
        return us_profile()
    if modality is Modality.MG:
        return mg_profile()
    return None


def profile_2d_from_dataset(ds: object | None) -> Profile2D | None:
    """
    Resolve a 2D profile from a DICOM dataset Modality tag.

    Args:
        ds: Dataset with Modality attribute, or None.

    Returns:
        Profile2D or None.
    """
    modality = getattr(ds, "Modality", None) if ds is not None else None
    return profile_2d_for_modality(modality)


def resolve_profile_2d_for_series(series_directory: object) -> Profile2D | None:
    """
    Load the first DICOM header and resolve a 2D profile.

    Args:
        series_directory: Path to series DICOM files.

    Returns:
        Profile2D or None.
    """
    ds = load_series_header_dataset(series_directory)
    if ds is None:
        return None
    return profile_2d_from_dataset(ds)


def loinc_prefix_for_2d_profile(
    profile: Profile2D,
    *,
    doppler: bool = False,
    dbt: bool = False,
    ffd: bool = False,
) -> str:
    """
    LOINC LongCommonName prefix for a 2D study.

    Args:
        profile: 2D Harmonize profile.
        doppler: US Doppler variant.
        dbt: MG digital breast tomosynthesis variant.
        ffd: MG full-field digital variant.

    Returns:
        LOINC prefix string including trailing space.
    """
    if Modality.US in profile.modalities and doppler:
        return "US.doppler "
    if Modality.MG in profile.modalities and dbt:
        return "DBT "
    if Modality.MG in profile.modalities and ffd:
        return "FFD "
    return profile.loinc_prefix


def loinc_prefix_for_2d_modality(
    value: str | Modality | None,
    *,
    doppler: bool = False,
    dbt: bool = False,
    ffd: bool = False,
) -> str:
    """
    LOINC prefix for a 2D modality code.

    Args:
        value: Modality enum or string.
        doppler: US Doppler variant.
        dbt: MG DBT variant.
        ffd: MG FFD variant.

    Returns:
        LOINC prefix string.

    Raises:
        ValueError: If modality has no 2D playbook profile.
    """
    profile = profile_2d_for_modality(value)
    if profile is None:
        raise ValueError(f"No 2D Harmonize profile for modality: {value!r}")
    return loinc_prefix_for_2d_profile(profile, doppler=doppler, dbt=dbt, ffd=ffd)


def normalize_2d_modality_label(value: str | Modality | None) -> str:
    """
    Uppercase modality label for logging; map CR/DX → XR.

    Args:
        value: Modality enum or string.

    Returns:
        Display label string.
    """
    modality = value if isinstance(value, Modality) else Modality.from_code(value)
    if modality is None:
        return ""
    if modality in XR_MODALITIES:
        return "XR"
    return modality.value


def is_2d_harmonize_modality(value: str | Modality | None) -> bool:
    """
    True when modality has a 2D Harmonize playbook (CR/DX/US/MG).

    Args:
        value: Modality enum or string.

    Returns:
        Whether a Profile2D exists (stricter than ContentClass.D2 alone).
    """
    return profile_2d_for_modality(value) is not None
