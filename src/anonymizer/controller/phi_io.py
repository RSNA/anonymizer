"""PHI dataset read-model, Patient Lookup CSV export, and Java index import orchestration.

Controller-layer I/O: builds DTOs from the ORM model and writes alternate formats.
Does not own SQLite persistence — that remains on AnonymizerModel.
"""

import csv
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import ClassVar

from anonymizer.model.anonymizer import (
    PHI,
    AnonymizerModel,
    Series,
    SeriesProcessingStatus,
    Study,
)
from anonymizer.utils.storage import JavaAnonymizerExportedStudy
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


def _format_pixel_phi(texts: Sequence[str]) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for item in texts:
        stripped = item.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            parts.append(stripped)
    return ", ".join(parts)


def _format_face_blur_status_label(algorithm: str) -> str:
    return " ".join(part.capitalize() for part in algorithm.strip().split("_"))


def format_series_processing_status(
    status: SeriesProcessingStatus,
    *,
    include_face_blur: bool = True,
) -> str:
    """Compact one-line series processing caption for Series View control bar."""
    total = status.pixel_phi_total_count
    applied = status.pixel_phi_applied_count
    if total == 0 or applied == 0:
        pixel_phi_part = _("None removed")
    elif applied == total:
        pixel_phi_part = _("Applied")
    else:
        pixel_phi_part = _("Partial ({applied}/{total})").format(applied=applied, total=total)

    harmonized = status.harmonized_description
    harmonized_part = harmonized.strip() if harmonized and harmonized.strip() else _("None")

    base = _("Pixel PHI: {pixel_phi} | Harmonized: {harmonized}").format(
        pixel_phi=pixel_phi_part,
        harmonized=harmonized_part,
    )
    if not include_face_blur:
        return base

    face_blur = status.face_blur_algorithm
    face_blur_part = _format_face_blur_status_label(face_blur) if face_blur and face_blur.strip() else _("None")
    return _("{base} | Face blur: {face_blur}").format(base=base, face_blur=face_blur_part)


@dataclass
class PHI_SeriesIndexRecord:
    """Per-series payload nested under a PHI dataset study row."""

    anon_series_uid: str
    modality: str
    description: str
    harmonized_description: str
    instance_count: int
    face_blur_algorithm: str
    pixel_phi_removed: bool
    pixel_phi: str

    def tree_label(self) -> str:
        description = (self.harmonized_description or self.description or "").strip()
        return description or "(no description)"

    def harmonized_display(self) -> str:
        text = (self.harmonized_description or "").strip()
        return text if text else "No"

    def face_blur_display(self) -> str:
        raw = (self.face_blur_algorithm or "").strip()
        return _format_face_blur_status_label(raw) if raw else ""

    def is_harmonized(self) -> bool:
        return bool((self.harmonized_description or "").strip())


@dataclass
class PHI_IndexRecord:
    anon_patient_id: str
    anon_patient_name: str
    phi_patient_name: str
    phi_patient_id: str
    date_offset: int
    phi_study_date: str
    anon_accession: str
    phi_accession: str
    anon_study_uid: str
    phi_study_uid: str
    modality: str = ""
    study_description: str = ""
    num_series: int = 0
    num_instances: int = 0
    harmonize: bool = False
    face_blurred: str = ""
    pixel_phi_removed: bool = False
    pixel_phi: str = ""
    series: list[PHI_SeriesIndexRecord] = field(default_factory=list)

    _NESTED_FIELD_NAMES: ClassVar[frozenset[str]] = frozenset({"series"})

    # Succinct Dataset View Treeview columns (CSV keeps LOOKUP_CSV_FIELD_TITLES).
    TREE_DISPLAY_FIELDS: ClassVar[tuple[str, ...]] = (
        "phi_patient_id",
        "anon_patient_id",
        "phi_accession",
        "date_offset",
        "modality",
        "num_series",
        "num_instances",
        "harmonize",
        "face_blurred",
        "pixel_phi_removed",
    )
    # View Dataset tree columns (see get_tree_display_titles).

    field_titles: ClassVar[dict[str, str]] = {
        "anon_patient_id": "ANON-PatientID",
        "anon_patient_name": "ANON-PatientName",
        "phi_patient_name": "PHI-PatientName",
        "phi_patient_id": "PHI-PatientID",
        "date_offset": "DateOffset",
        "phi_study_date": "PHI-StudyDate",
        "anon_accession": "ANON-AccNo",
        "phi_accession": "PHI-AccNo",
        "anon_study_uid": "ANON-StudyUID",
        "phi_study_uid": "PHI-StudyUID",
        "modality": "Modality",
        "study_description": "StudyDescription",
        "num_series": "Series",
        "num_instances": "Instances",
        "harmonize": "Harmonized",
        "face_blurred": "FaceBlurred",
        "pixel_phi_removed": "PixelPHIRemoved",
        "pixel_phi": "PixelPHI",
    }

    @staticmethod
    def _display_value(value: object) -> object:
        if isinstance(value, bool):
            return _("Yes") if value else _("No")
        return value

    @classmethod
    def _column_fields(cls):
        return [f for f in fields(cls) if f.name not in cls._NESTED_FIELD_NAMES]

    @classmethod
    def get_field_titles(cls) -> list:
        return [cls.field_titles.get(f.name) for f in cls._column_fields()]

    @classmethod
    def get_tree_display_fields(cls) -> list[str]:
        return list(cls.TREE_DISPLAY_FIELDS)

    @classmethod
    def get_tree_display_titles(cls) -> list[str]:
        titles = {
            "phi_patient_id": _("PHI ID"),
            "anon_patient_id": _("Anon ID"),
            "phi_accession": _("Acc No"),
            "date_offset": _("Offset"),
            "modality": _("Modality"),
            "num_series": _("Series"),
            "num_instances": _("Images"),
            "harmonize": _("Harmonized"),
            "face_blurred": _("Face blur"),
            "pixel_phi_removed": _("Pixel PHI"),
        }
        return [titles[name] for name in cls.TREE_DISPLAY_FIELDS]

    def modalities_display(self) -> str:
        """Comma-delimited unique series modalities in first-seen order."""
        seen: set[str] = set()
        parts: list[str] = []
        for series in self.series:
            modality = (series.modality or "").strip()
            if not modality or modality in seen:
                continue
            seen.add(modality)
            parts.append(modality)
        return ", ".join(parts)

    def flatten(self) -> tuple:
        """Study-level column values for legacy full-field layouts (excludes nested series)."""
        return tuple(self._display_value(getattr(self, f.name)) for f in self._column_fields())

    def series_flatten(self, series: PHI_SeriesIndexRecord) -> tuple:
        """Series child column values aligned with study flatten() columns."""
        values: dict[str, object] = {f.name: "" for f in self._column_fields()}
        values["modality"] = series.modality
        values["num_instances"] = series.instance_count
        values["harmonize"] = series.harmonized_display()
        values["face_blurred"] = series.face_blur_display()
        values["pixel_phi_removed"] = series.pixel_phi_removed
        values["pixel_phi"] = series.pixel_phi
        return tuple(self._display_value(values[f.name]) for f in self._column_fields())

    def tree_values(self) -> tuple:
        """Study-level values for Dataset View Treeview display columns."""
        values: dict[str, object] = {
            "phi_patient_id": self.phi_patient_id,
            "anon_patient_id": self.anon_patient_id,
            "phi_accession": self.phi_accession,
            "date_offset": self.date_offset,
            "modality": self.modalities_display(),
            "num_series": self.num_series,
            "num_instances": self.num_instances,
            "harmonize": self.harmonize,
            "face_blurred": bool((self.face_blurred or "").strip()),
            "pixel_phi_removed": self.pixel_phi_removed,
        }
        return tuple(self._display_value(values[name]) for name in self.TREE_DISPLAY_FIELDS)

    def series_tree_values(self, series: PHI_SeriesIndexRecord) -> tuple:
        """Series child values aligned with Dataset View Treeview display columns."""
        values: dict[str, object] = {name: "" for name in self.TREE_DISPLAY_FIELDS}
        values["modality"] = series.modality
        values["num_instances"] = series.instance_count
        values["harmonize"] = series.is_harmonized()
        values["face_blurred"] = series.face_blur_display()
        values["pixel_phi_removed"] = series.pixel_phi
        return tuple(self._display_value(values[name]) for name in self.TREE_DISPLAY_FIELDS)

    def tree_label(self) -> str:
        description = (self.study_description or "").strip()
        return description or "(no description)"

    @classmethod
    def get_field_names(cls) -> list:
        return [f.name for f in cls._column_fields()]

    LOOKUP_CSV_FIELD_TITLES: ClassVar[tuple[str, ...]] = (
        "ANON-PatientID",
        "ANON-PatientName",
        "PHI-PatientName",
        "PHI-PatientID",
        "DateOffset",
        "PHI-StudyDate",
        "ANON-AccNo",
        "PHI-AccNo",
        "ANON-StudyUID",
        "PHI-StudyUID",
        "Series",
        "StudyInstances",
        "ANON-SeriesUID",
        "Modality",
        "SeriesDescription",
        "SeriesHarmonized",
        "Instances",
        "FaceBlurred",
        "PixelPHIRemoved",
        "PixelPHI",
    )

    def _lookup_csv_study_prefix(self) -> tuple[object, ...]:
        return (
            self.anon_patient_id,
            self.anon_patient_name,
            self.phi_patient_name,
            self.phi_patient_id,
            self.date_offset,
            self.phi_study_date,
            self.anon_accession,
            self.phi_accession,
            self.anon_study_uid,
            self.phi_study_uid,
            self.num_series,
            self.num_instances,
        )

    def _lookup_csv_series_suffix(self, series: PHI_SeriesIndexRecord | None) -> tuple[object, ...]:
        if series is None:
            return ("", "", "", "No", "", "", "No", "")
        series_harmonized = bool((series.harmonized_description or "").strip())
        return (
            series.anon_series_uid,
            series.modality,
            series.description,
            self._display_value(series_harmonized),
            series.instance_count,
            series.face_blur_display(),
            self._display_value(series.pixel_phi_removed),
            series.pixel_phi,
        )

    def iter_lookup_csv_rows(self) -> Iterator[tuple[object, ...]]:
        """Yield denormalized Patient Lookup CSV rows (one per series; study keys repeated)."""
        prefix = self._lookup_csv_study_prefix()
        if not self.series:
            yield prefix + self._lookup_csv_series_suffix(None)
            return
        for series in self.series:
            yield prefix + self._lookup_csv_series_suffix(series)

    @staticmethod
    def lookup_csv_row_count(records: list["PHI_IndexRecord"]) -> int:
        total = 0
        for record in records:
            total += len(record.series) if record.series else 1
        return total

    @staticmethod
    def lookup_csv_entity_counts(records: list["PHI_IndexRecord"]) -> tuple[int, int, int]:
        """Return (patients, studies, series) totals for lookup CSV filenames."""
        patients = len({record.anon_patient_id for record in records})
        studies = len(records)
        series = sum(len(record.series) for record in records)
        return patients, studies, series


def _study_ct_series_all_harmonized(study: Study) -> bool:
    """Backward-compatible CT-only check (prefer ``_study_index_harmonized`` for Dataset)."""
    ct_series = [series for series in (study.series or []) if (series.modality or "").upper() == "CT"]
    if not ct_series:
        return False
    return all(
        series.harmonized_description is not None and bool(str(series.harmonized_description).strip())
        for series in ct_series
    )


def _study_index_harmonized(study: Study) -> bool:
    """True when Dataset should show the study Harmonized (green).

    - Studies with CT/MR series: all CT/MR series have ``harmonized_description``
      (planar siblings do not block).
    - Pure XR/US/MG studies: all planar Harmonize series are done.
    """
    from anonymizer.utils.modalities import (
        series_is_planar_harmonize_eligible,
        series_is_tseg_eligible,
    )

    tseg_series = [s for s in (study.series or []) if series_is_tseg_eligible(s.modality)]
    if tseg_series:
        return all(bool((s.harmonized_description or "").strip()) for s in tseg_series)

    planar_series = [s for s in (study.series or []) if series_is_planar_harmonize_eligible(s.modality)]
    if planar_series:
        return all(bool((s.harmonized_description or "").strip()) for s in planar_series)
    return False


def _study_face_blur_label(study: Study) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for series in study.series or []:
        raw = series.face_blur_algorithm_applied
        if raw is None or not str(raw).strip():
            continue
        key = str(raw).strip()
        if key in seen:
            continue
        seen.add(key)
        labels.append(_format_face_blur_status_label(key))
    return ", ".join(labels)


def _series_pixel_phi_texts(series: Series) -> list[str]:
    texts: list[str] = []
    for instance in series.instances or []:
        raw = instance.pixel_phi
        if raw is None or not str(raw).strip():
            continue
        texts.extend(item.strip() for item in str(raw).split(",") if item.strip())
    return texts


def _series_pixel_phi_digest(series: Series) -> str:
    return _format_pixel_phi(_series_pixel_phi_texts(series))


def _study_pixel_phi_digest(study: Study) -> str:
    texts: list[str] = []
    for series in study.series or []:
        texts.extend(_series_pixel_phi_texts(series))
    return _format_pixel_phi(texts)


def _study_pixel_phi_removed(study: Study) -> bool:
    return bool(_study_pixel_phi_digest(study))


def _phi_series_index_record(series: Series) -> PHI_SeriesIndexRecord:
    digest = _series_pixel_phi_digest(series)
    return PHI_SeriesIndexRecord(
        anon_series_uid=series.anon_series_uid,
        modality=str(series.modality or ""),
        description=str(series.description or ""),
        harmonized_description=str(series.harmonized_description or ""),
        instance_count=len(series.instances or []),
        face_blur_algorithm=str(series.face_blur_algorithm_applied or ""),
        pixel_phi_removed=bool(digest),
        pixel_phi=digest,
    )


def _phi_index_record_from_orm(phi: PHI, study: Study) -> PHI_IndexRecord:
    num_series = len(study.series or [])
    num_instances = sum(len(s.instances or []) for s in (study.series or []))
    series_records = [
        _phi_series_index_record(s)
        for s in sorted(
            study.series or [],
            key=lambda item: (
                (item.modality or "").upper(),
                (item.description or "").lower(),
                item.anon_series_uid,
            ),
        )
    ]
    return PHI_IndexRecord(
        anon_patient_id=phi.anon_patient_id,
        anon_patient_name=phi.anon_patient_id,
        phi_patient_id=phi.patient_id,
        phi_patient_name=phi.patient_name if phi.patient_name else "",
        date_offset=study.anon_date_delta,
        phi_study_date=study.study_date,
        anon_accession=str(study.anon_accession_number),
        phi_accession=study.accession_number if study.accession_number else "",
        anon_study_uid=study.anon_study_uid,
        phi_study_uid=study.study_uid,
        study_description=str(study.harmonized_description or study.description or ""),
        num_series=num_series,
        num_instances=num_instances,
        harmonize=_study_index_harmonized(study),
        face_blurred=_study_face_blur_label(study),
        pixel_phi_removed=_study_pixel_phi_removed(study),
        pixel_phi=_study_pixel_phi_digest(study),
        series=series_records,
    )


def build_phi_index(anon_model: AnonymizerModel) -> list[PHI_IndexRecord] | None:
    """Build nested PHI dataset records from the ORM model."""
    phi_instances = anon_model.load_phi_with_studies_series()
    if not phi_instances:
        return None

    phi_index_records: list[PHI_IndexRecord] = []
    for phi in phi_instances:
        if phi.studies is None:
            continue
        for study in phi.studies:
            phi_index_records.append(_phi_index_record_from_orm(phi, study))

    return phi_index_records if phi_index_records else None


def write_lookup_csv(path: Path, records: list[PHI_IndexRecord]) -> None:
    """Write series-grain Patient Lookup CSV to ``path``."""
    with open(path, "w", newline="") as csv_file:
        writer = csv.writer(csv_file, delimiter=",")
        writer.writerow(PHI_IndexRecord.LOOKUP_CSV_FIELD_TITLES)
        for record in records:
            for row in record.iter_lookup_csv_rows():
                writer.writerow(row)


def import_java_phi_studies(
    anon_model: AnonymizerModel,
    java_studies: list[JavaAnonymizerExportedStudy],
) -> None:
    """Orchestrate Java index import; persistence is delegated to the model."""
    logger.info("Importing %d Java PHI studies via model persistence", len(java_studies))
    anon_model.persist_java_exported_studies(java_studies)
