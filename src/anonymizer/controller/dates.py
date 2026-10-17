"""
DICOM date shift runtime for anonymization.

Owns day-delta apply, PatientID hash dates, TCIA rebase day math, and
longitudinal provenance stamps. Script parsing stays in anonymizer_script;
ingest walk dispatches in AnonymizerController._anonymize_element.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from pydicom import Dataset

from anonymizer.controller.anonymizer_script import rebasedate_origin

DEFAULT_ANON_DATE = "20000101"  # if source date is invalid or before 19000101


def valid_date(date_str: str) -> bool:
    """
    Return True if date_str is YYYYMMDD and on or after 19000101.

    Args:
        date_str: Candidate DICOM DA string.

    Returns:
        True when the date parses and is not before 1900-01-01.
    """
    try:
        date_obj = datetime.strptime(date_str, "%Y%m%d")
        return not (date_obj < datetime(1900, 1, 1))
    except ValueError:
        return False


def hash_date(date: str, patient_id: str) -> tuple[int, str]:
    """
    Hash a date by PatientID: add MD5(PatientID) mod 3652 days.

    Args:
        date: Source date YYYYMMDD.
        patient_id: PHI PatientID used for the hash offset.

    Returns:
        (days_incremented, formatted_YYYYMMDD). On invalid date or empty
        patient_id, returns (0, DEFAULT_ANON_DATE).
    """
    if not valid_date(date) or not len(patient_id):
        return 0, DEFAULT_ANON_DATE

    md5_hash = hashlib.md5(patient_id.encode()).hexdigest()
    hash_integer = int(md5_hash, 16)
    days_to_increment = hash_integer % 3652
    input_date = datetime.strptime(date, "%Y%m%d")
    incremented_date = input_date + timedelta(days=days_to_increment)
    formatted_date = incremented_date.strftime("%Y%m%d")
    return days_to_increment, formatted_date


def apply_day_delta(value: str, days: int) -> str:
    """
    Shift a DICOM DA or DT string by a signed number of days.

    Preserves any characters after the parsed date/datetime prefix (e.g. DT
    fractional seconds). Empty or unparseable values are returned unchanged.

    Args:
        value: DICOM date (YYYYMMDD) or datetime text.
        days: Signed day delta to add.

    Returns:
        Shifted string, or the original value if empty/too short/invalid.
    """
    if not value or not str(value).strip():
        return value
    text = str(value).strip()
    if len(text) >= 14:
        date_fmt = "%Y%m%d%H%M%S"
        length = 14
    elif len(text) >= 8:
        date_fmt = "%Y%m%d"
        length = 8
    else:
        return value
    try:
        dt = datetime.strptime(text[:length], date_fmt)
        shifted = dt + timedelta(days=days)
        return shifted.strftime(date_fmt) + text[length:]
    except ValueError:
        return value


def rebase_days(basedate: str | None, origin: str | None) -> int | None:
    """
    Days to add for TCIA epoch rebase: ORIGIN − basedate.

    Args:
        basedate: Lookup basedate YYYYMMDD for the patient, or None.
        origin: ORIGIN YYYYMMDD from @rebasedate(this,…), or None/invalid
            to use the bare @rebasedate default origin.

    Returns:
        Signed day delta, or None if basedate/origin cannot be parsed.
    """
    if not basedate:
        return None
    origin_da = (origin or "").strip()
    if len(origin_da) != 8 or not origin_da.isdigit():
        origin_da = rebasedate_origin("@rebasedate") or "19600101"
    try:
        base_dt = datetime.strptime(str(basedate), "%Y%m%d")
        origin_dt = datetime.strptime(origin_da, "%Y%m%d")
    except ValueError:
        return None
    return (origin_dt - base_dt).days


def stamp_dates_modified(ds: Dataset) -> None:
    """
    Set LongitudinalTemporalInformationModified to MODIFIED.

    Args:
        ds: Dataset to mutate.

    Returns:
        None.
    """
    ds.LongitudinalTemporalInformationModified = "MODIFIED"


def stamp_rebase_registration(
    ds: Dataset,
    phi_study_date: str | None,
    basedate: str | None,
) -> None:
    """
    Stamp TCIA REGISTRATION provenance from StudyDate and lookup basedate.

    Sets LongitudinalTemporalOffsetFromEvent, LongitudinalTemporalEventType
    REGISTRATION, and LongitudinalTemporalInformationModified MODIFIED when
    both dates are valid YYYYMMDD.

    Args:
        ds: Dataset to mutate.
        phi_study_date: Pre-anonymization StudyDate, or None.
        basedate: Lookup basedate YYYYMMDD, or None.

    Returns:
        None.
    """
    if not basedate or not phi_study_date:
        return
    study = str(phi_study_date).strip()[:8]
    base = str(basedate).strip()[:8]
    if len(study) != 8 or not study.isdigit() or len(base) != 8 or not base.isdigit():
        return
    try:
        study_dt = datetime.strptime(study, "%Y%m%d")
        base_dt = datetime.strptime(base, "%Y%m%d")
    except ValueError:
        return
    ds.LongitudinalTemporalOffsetFromEvent = float((study_dt - base_dt).days)
    ds.LongitudinalTemporalEventType = "REGISTRATION"
    ds.LongitudinalTemporalInformationModified = "MODIFIED"
