"""Apply rsna-anonymizer clinical (or experiment) script via AnonymizerController."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from pydicom.dataset import Dataset

from anonymizer.controller.anonymizer import AnonymizerController
from anonymizer.controller.anonymizer_script import packaged_script_path_for_policy
from anonymizer.model.project import AnonymizationPolicy, DICOMNode, ProjectModel

from prototyping.pseudo_phi_deid.paths import SCRIPTS_DIR

logger = logging.getLogger(__name__)


def resolve_script_path(script: str | Path | None = None) -> Path:
    if script is None:
        # Prefer experiment script if present.
        exp = SCRIPTS_DIR / "clinical-anonymizer.script"
        if exp.is_file():
            return exp
        return packaged_script_path_for_policy(AnonymizationPolicy.CLINICAL)
    return Path(script)


def make_anonymizer(storage_dir: Path, script_path: Path | None = None) -> AnonymizerController:
    script = resolve_script_path(script_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    model = ProjectModel(
        # Numeric site_id only — embedded in UID prefix (DICOM UI: digits/dots).
        site_id="99",
        project_name="MIDI_B",
        uid_root="1.2.826.0.1.3680043.10.474",
        storage_dir=storage_dir,
        scu=DICOMNode("127.0.0.1", 0, "MIDIB", True),
        scp=DICOMNode("127.0.0.1", 11121, "MIDIB", True),
        anonymizer_script_path=script,
        anonymization_policy=AnonymizationPolicy.CLINICAL,
    )
    model.private_dir().mkdir(parents=True, exist_ok=True)
    model.images_dir().mkdir(parents=True, exist_ok=True)
    return AnonymizerController(model)


def anonymize_dataset(ds: Dataset, anon: AnonymizerController) -> Dataset:
    """Anonymize ``ds`` in-place via controller; drop the temp store copy.

    ``AnonymizerController.anonymize`` mutates ``ds`` then writes it under
    ``images_dir``. Callers only need the in-memory dataset, so the written
    file is removed to avoid unbounded temp growth on large cohorts.
    """
    err = anon.anonymize("pseudo_phi_deid", ds)
    if err:
        raise RuntimeError(f"clinical script failed: {err}")
    try:
        written = anon.local_storage_path(anon.project_model.images_dir(), ds)
        if written.is_file():
            written.unlink()
            # Best-effort prune empty series/study/patient dirs.
            for parent in (written.parent, written.parent.parent, written.parent.parent.parent):
                try:
                    parent.rmdir()
                except OSError:
                    break
    except Exception:
        logger.debug("temp anon file cleanup skipped", exc_info=True)
    return ds


def ensure_experiment_script_copy(*, force: bool = False) -> Path:
    """Sync packaged clinical script into experiment ``scripts/``."""
    dest = SCRIPTS_DIR / "clinical-anonymizer.script"
    src = packaged_script_path_for_policy(AnonymizationPolicy.CLINICAL)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    if force or not dest.is_file() or dest.read_bytes() != src.read_bytes():
        shutil.copy2(src, dest)
        logger.info("synced clinical script → %s", dest)
    return dest


class ClinicalSession:
    """Context manager owning temp storage + anonymizer workers."""

    def __init__(self, script_path: Path | None = None) -> None:
        self.script_path = script_path
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.anon: AnonymizerController | None = None

    def __enter__(self) -> ClinicalSession:
        self._tmp = tempfile.TemporaryDirectory(prefix="pseudo_phi_anon_")
        self.anon = make_anonymizer(Path(self._tmp.name), self.script_path)
        return self

    def __exit__(self, *exc: object) -> None:
        if self.anon is not None:
            try:
                self.anon.stop()
            except Exception:
                pass
        if self._tmp is not None:
            self._tmp.cleanup()

    def apply(self, ds: Dataset) -> Dataset:
        assert self.anon is not None
        return anonymize_dataset(ds, self.anon)
