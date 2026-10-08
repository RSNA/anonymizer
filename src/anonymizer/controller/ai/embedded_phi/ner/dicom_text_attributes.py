"""Hitchhikers: free-text DICOM attributes outside SR/PDF bodies that may carry PHI."""

from __future__ import annotations

from collections.abc import Iterator

from pydicom import Dataset

from anonymizer.controller.ai.embedded_phi.report.content_text import TextSlot

# Keywords of long-text / free-text attributes (ST, LT, UT, LO) frequently holding narrative PHI.
HITCHHIKER_KEYWORDS: tuple[str, ...] = (
    "ImageComments",
    "PatientComments",
    "StudyComments",
    "AdditionalPatientHistory",
    "AdmittingDiagnosesDescription",
    "ReasonForTheRequestedProcedure",
    "ReasonForStudy",
    "RequestedProcedureDescription",
    "RequestedProcedureComments",
    "ImagingServiceRequestComments",
    "InterpretationText",
    "ResultsComments",
    "DerivationDescription",
    "ProtocolName",
    "AcquisitionComments",
    "ScheduledProcedureStepDescription",
    "PerformedProcedureStepDescription",
    "CommentsOnThePerformedProcedureStep",
    "ContentDescription",
    "VisitComments",
    "SpecialNeeds",
    "ConfidentialityConstraintOnPatientDataDescription",
)


def iter_hitchhiker_slots(ds: Dataset, *, key_prefix: str = "") -> Iterator[TextSlot]:
    """Yield a slot for each non-empty hitchhiker keyword present on ``ds`` (top level only)."""
    for kw in HITCHHIKER_KEYWORDS:
        if kw not in ds:
            continue
        elem = ds[kw]
        value = elem.value
        if value is None or isinstance(value, (list, tuple)) or not str(value).strip():
            continue

        def _write(new: str, _ds: Dataset = ds, _kw: str = kw) -> None:
            _ds[_kw].value = new

        yield TextSlot(key=f"{key_prefix}{kw}", context=kw, text=str(value), write=_write)
