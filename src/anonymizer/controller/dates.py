"""Date-delta runtime for the anonymize walk.

Resolves one day delta per file from the StudyDate operation, applies it to
DA/DT values, and stamps TCIA longitudinal / REGISTRATION tags when rebasing.

Public API
----------
DEFAULT_ANON_DATE
    Fallback YYYYMMDD when a source date is invalid or empty.

is_date_delta_operation(operation: str | None) -> bool
    True when the operation applies a day delta to a date value.

incrementdate_days(operation: str | None) -> int | None
    Parse day offset from @incrementdate(this,N).

rebasedate_origin(operation: str | None) -> str | None
    Parse ORIGIN YYYYMMDD from @rebasedate(this,YYYYMMDD).

valid_date(date_str: str) -> bool
    Return True if date_str is YYYYMMDD and on or after 19000101.

dateinc_days(path: str | None=None) -> int
    Load trial-wide DATEINC days from private_tags/dateinc.txt.

incrementdate_operand(days: int | None=None) -> str
    CTP @incrementdate(this,N) string.

hash_date(date: str, patient_id: str) -> tuple[int, str]
    Hash a date by PatientID: add MD5(PatientID) mod 3652 days.

resolve_date_delta(study_date_operation: str | None, *, patient_id: str, days_from_lookup: int, base_date: str | None) -> int | None
    Resolve the one day delta for a file from its StudyDate operation.

apply_day_delta(value: str, days: int) -> str
    Shift a DICOM DA or DT string by a signed number of days.

rebase_days(basedate: str | None, origin: str | None) -> int | None
    Days to add for TCIA epoch rebase: ORIGIN − basedate.

stamp_dates_modified(ds: Dataset) -> None
    Set LongitudinalTemporalInformationModified to MODIFIED.

stamp_rebase_registration(ds: Dataset, phi_study_date: str | None, basedate: str | None) -> None
    Stamp TCIA REGISTRATION provenance from StudyDate and lookup basedate.
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from pydicom import Dataset

logger = logging.getLogger(__name__)

DEFAULT_ANON_DATE = "20000101"  # if source date is invalid or before 19000101
_DATEINC_PATH = Path(__file__).resolve().parent / "private_tags" / "dateinc.txt"
_INCREMENTDATE_RE = re.compile(r"^@incrementdate\(\s*this\s*,\s*(-?\d+)\s*\)$", re.IGNORECASE)
_REBASEDATE_RE = re.compile(r"^@rebasedate\(\s*this\s*,\s*(\d{8})\s*\)$", re.IGNORECASE)
_DEFAULT_REBASE_ORIGIN = "19600101"


def is_date_delta_operation(operation: str | None) -> bool:
    """
    True when the operation applies a day delta to a date value.

    Args:
        operation: Script operation text.

    Returns:
        True for hashdate, lookup dateoffset, incrementdate, or rebasedate.
    """
    text = str(operation or "").strip().lower()
    if not text:
        return False
    return (
        "@hashdate" in text
        or "dateoffset" in text
        or "@incrementdate" in text
        or "@rebasedate" in text
    )


def incrementdate_days(operation: str | None) -> int | None:
    """
    Parse day offset from @incrementdate(this,N).

    Args:
        operation: Script operation text.

    Returns:
        Signed day count, or None if not that form.
    """
    match = _INCREMENTDATE_RE.match(str(operation or "").strip())
    if match is None:
        return None
    return int(match.group(1))


def rebasedate_origin(operation: str | None) -> str | None:
    """
    Parse ORIGIN YYYYMMDD from @rebasedate(this,YYYYMMDD).

    Args:
        operation: Script operation text.

    Returns:
        ORIGIN date, default origin for bare @rebasedate, or None.
    """
    text = str(operation or "").strip()
    match = _REBASEDATE_RE.match(text)
    if match is not None:
        return match.group(1)
    if text.lower() == "@rebasedate":
        return _DEFAULT_REBASE_ORIGIN
    return None



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


@lru_cache(maxsize=1)
def dateinc_days(path: str | None = None) -> int:
    """
    Load trial-wide DATEINC days from private_tags/dateinc.txt.

    Args:
        path: Optional override path; default is the packaged DATEINC file.

    Returns:
        Signed day count.

    Raises:
        FileNotFoundError: When the DATEINC file is missing.
        ValueError: When the file contains no integer.
    """
    p = Path(path) if path else _DATEINC_PATH
    if not p.is_file():
        raise FileNotFoundError(f"DATEINC file missing: {p}")
    for line in p.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        return int(text)
    raise ValueError(f"No DATEINC integer in {p}")


def incrementdate_operand(days: int | None = None) -> str:
    """
    CTP @incrementdate(this,N) string.

    Args:
        days: Day delta; when None, uses dateinc_days().

    Returns:
        Operation text @incrementdate(this,N).
    """
    n = dateinc_days() if days is None else int(days)
    return f"@incrementdate(this,{n})"


def hash_date(date: str, patient_id: str) -> tuple[int, str]:
    """
    Hash a date by PatientID: add MD5(PatientID) mod 3652 days.

    Args:
        date: Source date YYYYMMDD.
        patient_id: PHI PatientID used for the hash day delta.

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


def resolve_date_delta(
    study_date_operation: str | None,
    *,
    patient_id: str,
    days_from_lookup: int,
    base_date: str | None,
) -> int | None:
    """
    Resolve the one day delta for a file from its StudyDate operation.

    A project carries exactly one date strategy, defined by the StudyDate
    rule, so every date element in the file shifts by this single delta.

    Args:
        study_date_operation: Operation text of the StudyDate rule.
        patient_id: PHI PatientID (hash-date delta source).
        days_from_lookup: Lookup dateoffset days for this patient.
        base_date: Lookup base_date YYYYMMDD for this patient, or None.

    Returns:
        Signed day delta, or None when the strategy cannot produce one
        (@rebasedate without a base_date).
    """
    operation = (study_date_operation or "").strip()
    if "@incrementdate" in operation:
        return incrementdate_days(operation)
    if "@rebasedate" in operation.lower():
        return rebase_days(base_date, rebasedate_origin(operation))
    if "@hashdate" in operation:
        return hash_date(DEFAULT_ANON_DATE, patient_id)[0]
    if "dateoffset" in operation:
        return days_from_lookup
    return None


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
