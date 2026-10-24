"""Synthetic DICOM helpers built from real TCIA private-tag KB rows.

Public API (tests only)
-----------------------
PrivateTagSpec
    One private element to plant on a dataset.

KbSample
    One PRIVATE_KB row with its lookup key.

sample_kb_entries(action, *, vr_in=None, require_creator=True, limit=3) -> list[KbSample]
    Stable sorted sample of KB rows for an action.

placeholder_value(vr) -> object
    Minimal value accepted by pydicom for the given VR.

spec_from_kb(sample, *, value=None, vr=None) -> PrivateTagSpec
    Build a plantable spec from a KB sample.

unknown_private_spec(...) -> PrivateTagSpec
    Spec for a creator/slot that is not in the KB (expect @remove).

ingest_fixture_specs() -> list[PrivateTagSpec]
    One KEEP, REMOVE, UID(UI), DATE_DELTA(DA/DT), and unknown for ingest walks.

minimal_sc_dataset(*, patient_id, study_date) -> Dataset
    Bare Secondary Capture shell for private-tag tests.

apply_private_specs(ds, specs) -> Dataset
    Create private blocks and add elements from specs; returns ds.
"""

from dataclasses import dataclass

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.private_tags.tcia_kb_data import (
    PRIVATE_KB,
    PrivateTagAction,
    PrivateTagEntry,
)

# Anonymizer stamps its own block here; skip when sampling KEEP rows.
_ANONYMIZER_PRIVATE_GROUP = 0x0013


@dataclass(frozen=True)
class KbSample:
    """One PRIVATE_KB row with its dict key."""

    creator: str
    group: int
    suffix: int
    entry: PrivateTagEntry


@dataclass(frozen=True)
class PrivateTagSpec:
    """One private element to plant on a dataset."""

    creator: str
    group: int
    suffix: int
    vr: str
    value: object
    action: PrivateTagAction | None = None


def sample_kb_entries(
    action: PrivateTagAction,
    *,
    vr_in: frozenset[str] | None = None,
    require_creator: bool = True,
    exclude_groups: frozenset[int] = frozenset({_ANONYMIZER_PRIVATE_GROUP}),
    limit: int = 3,
) -> list[KbSample]:
    """
    Return a stable sorted sample of PRIVATE_KB rows for action.

    Args:
        action: KB disposition to select.
        vr_in: When set, only rows whose entry.vr (upper) is in this set.
        require_creator: Skip rows with an empty creator string.
        exclude_groups: Private groups to omit (default: app 0x0013 block).
        limit: Maximum rows to return.

    Returns:
        Up to limit KbSample rows, sorted by creator/group/suffix.
    """
    rows: list[KbSample] = []
    for (_creator_cf, group, suffix), entry in PRIVATE_KB.items():
        if entry.action is not action:
            continue
        if group in exclude_groups:
            continue
        if require_creator and not (entry.creator or "").strip():
            continue
        if vr_in is not None and (entry.vr or "").upper() not in vr_in:
            continue
        rows.append(
            KbSample(
                creator=entry.creator,
                group=group,
                suffix=suffix,
                entry=entry,
            )
        )
    rows.sort(key=lambda s: (s.creator.casefold(), s.group, s.suffix))
    return rows[:limit]


def placeholder_value(vr: str) -> object:
    """
    Minimal value for planting a private element of the given VR.

    Args:
        vr: DICOM VR string.

    Returns:
        A value pydicom typically accepts for that VR.
    """
    key = (vr or "LO").upper()
    if key == "DA":
        return "20200115"
    if key == "DT":
        return "20200101120000"
    if key == "TM":
        return "120000"
    if key == "UI":
        return "1.2.3.4.5.6.7"
    if key in {"OB", "OW", "OF", "OD", "UC", "UR", "UT", "UN"}:
        return b"\x00\x01"
    if key in {"US", "SS"}:
        return 1
    if key in {"UL", "SL", "FL", "FD"}:
        return 1
    if key in {"IS", "DS"}:
        return "1"
    return "SYNTH"


def spec_from_kb(
    sample: KbSample,
    *,
    value: object | None = None,
    vr: str | None = None,
) -> PrivateTagSpec:
    """
    Build a plantable PrivateTagSpec from a KB sample.

    Args:
        sample: Row from sample_kb_entries.
        value: Override value; default from placeholder_value.
        vr: Override VR on the dataset element (lookup still uses KB key).

    Returns:
        Spec ready for apply_private_specs.
    """
    resolved_vr = (vr or sample.entry.vr or "LO").upper()
    return PrivateTagSpec(
        creator=sample.creator,
        group=sample.group,
        suffix=sample.suffix,
        vr=resolved_vr,
        value=placeholder_value(resolved_vr) if value is None else value,
        action=sample.entry.action,
    )


def unknown_private_spec(
    *,
    creator: str = "NoSuchCreator_XYZ",
    group: int = 0x7777,
    suffix: int = 0x10,
    vr: str = "LO",
    value: object = "SECRET",
) -> PrivateTagSpec:
    """
    Spec for a private slot that is not in the KB.

    Args:
        creator: Private creator string.
        group: Private group.
        suffix: Element low byte.
        vr: Value representation.
        value: Element value.

    Returns:
        Spec expected to resolve to @remove().
    """
    return PrivateTagSpec(
        creator=creator,
        group=group,
        suffix=suffix,
        vr=vr,
        value=value,
        action=None,
    )


def ingest_fixture_specs() -> list[PrivateTagSpec]:
    """
    One real-KB sample per disposition plus an unknown slot for ingest walks.

    Returns:
        KEEP, REMOVE, UID(UI), DATE_DELTA(DA or DT), and unknown specs.
    """
    keep = sample_kb_entries(
        PrivateTagAction.KEEP, vr_in=frozenset({"LO", "ST", "CS"}), limit=1
    )
    remove = sample_kb_entries(
        PrivateTagAction.REMOVE, vr_in=frozenset({"LO", "ST", "CS"}), limit=1
    )
    uid = sample_kb_entries(PrivateTagAction.UID, vr_in=frozenset({"UI"}), limit=1)
    date = sample_kb_entries(
        PrivateTagAction.DATE_DELTA, vr_in=frozenset({"DA", "DT"}), limit=1
    )
    assert keep and remove and uid and date, "PRIVATE_KB missing required action samples"
    return [
        spec_from_kb(keep[0], value="KEEPME"),
        spec_from_kb(remove[0], value="DELETEME"),
        spec_from_kb(uid[0], value="1.2.3.4.5.6.7"),
        spec_from_kb(date[0]),
        unknown_private_spec(),
    ]


def minimal_sc_dataset(
    *,
    patient_id: str = "PRIV-TAG-PT",
    study_date: str = "20200101",
) -> Dataset:
    """
    Bare Secondary Capture shell for private-tag tests.

    Args:
        patient_id: PatientID.
        study_date: StudyDate YYYYMMDD.

    Returns:
        Dataset with file_meta and required UIDs.
    """
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientID = patient_id
    ds.StudyDate = study_date
    ds.Modality = "OT"
    return ds


def apply_private_specs(ds: Dataset, specs: list[PrivateTagSpec]) -> Dataset:
    """
    Create private blocks and add elements described by specs.

    Args:
        ds: Dataset to mutate.
        specs: Private elements to plant.

    Returns:
        The same dataset.
    """
    for spec in specs:
        block = ds.private_block(spec.group, spec.creator, create=True)
        block.add_new(spec.suffix, spec.vr, spec.value)
    return ds


def find_private_element(ds: Dataset, spec: PrivateTagSpec):
    """
    Locate the planted non-creator element matching spec on ds.

    Args:
        ds: Dataset after apply_private_specs.
        spec: Spec that was applied.

    Returns:
        DataElement for the data slot.

    Raises:
        LookupError: When no matching element is found.
    """
    for elem in ds:
        if not elem.tag.is_private or elem.tag.is_private_creator:
            continue
        if elem.tag.group != spec.group:
            continue
        if (elem.tag.element & 0xFF) != spec.suffix:
            continue
        return elem
    raise LookupError(
        f"private element not found: creator={spec.creator!r} "
        f"group={spec.group:04X} suffix={spec.suffix:02X}"
    )
