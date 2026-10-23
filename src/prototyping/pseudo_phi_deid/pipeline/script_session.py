"""Apply packaged anonymizer script via AnonymizerController (prototyping)."""

import contextlib
import logging
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Self

from pydicom.dataelem import DataElement
from pydicom.dataset import Dataset

from anonymizer.controller.anonymizer import AnonymizerController
from anonymizer.controller.private_tags import private_tag_operation
from anonymizer.model.project import RETAIN_OPTIONS, DICOMNode, ProjectModel
from prototyping.pseudo_phi_deid.paths import PACKAGED_DEFAULT_SCRIPT, SCRIPTS_DIR

logger = logging.getLogger(__name__)

OperationForTag = Callable[[str, Dataset, DataElement], str]
_PACKAGED_DEFAULT = "default-anonymizer.script"


def resolve_script_path(script: str | Path | None = None) -> Path:
    """Resolve experiment or packaged default anonymizer script path."""
    if script is None:
        exp = SCRIPTS_DIR / _PACKAGED_DEFAULT
        if exp.is_file():
            return exp
        return PACKAGED_DEFAULT_SCRIPT
    return Path(script)


def make_anonymizer(storage_dir: Path, script_path: Path | None = None) -> AnonymizerController:
    """Build an AnonymizerController with RETAIN_OPTIONS for prototyping runs."""
    script = resolve_script_path(script_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    model = ProjectModel(
        site_id="99",
        project_name="MIDI_B",
        uid_root="1.2.826.0.1.3680043.10.474",
        storage_dir=storage_dir,
        scu=DICOMNode("127.0.0.1", 0, "MIDIB", True),
        scp=DICOMNode("127.0.0.1", 11121, "MIDIB", True),
        anonymizer_script_path=script,
        confidentiality_options=RETAIN_OPTIONS,
    )
    model.private_dir().mkdir(parents=True, exist_ok=True)
    model.images_dir().mkdir(parents=True, exist_ok=True)
    return AnonymizerController(model)


def operation_resolver(anon: AnonymizerController) -> OperationForTag:
    """Resolve script / KB operation for one element (NER field gating)."""

    def resolve(tag: str, ds: Dataset, elem: DataElement) -> str:
        if elem.tag.is_private:
            return private_tag_operation(
                ds, elem, retain_uids=False, date_delta=None
            )
        return anon.model._tag_keep.get(tag.upper()) or "@remove()"

    return resolve


def anonymize_dataset(ds: Dataset, anon: AnonymizerController) -> Dataset:
    """Anonymize ds in-place via controller; drop the temp store copy."""
    err = anon.anonymize("pseudo_phi_deid", ds)
    if err:
        raise RuntimeError(f"anonymizer script failed: {err}")
    try:
        written = anon.local_storage_path(anon.project_model.images_dir(), ds)
        if written.is_file():
            written.unlink()
            for parent in (written.parent, written.parent.parent, written.parent.parent.parent):
                try:
                    parent.rmdir()
                except OSError:
                    break
    except Exception:
        logger.debug("temp anon file cleanup skipped", exc_info=True)
    return ds


def ensure_experiment_script_copy(*, force: bool = False) -> Path:
    """Sync packaged default script into the experiment scripts dir."""
    dest = SCRIPTS_DIR / _PACKAGED_DEFAULT
    src = PACKAGED_DEFAULT_SCRIPT
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    if force or not dest.is_file() or dest.read_bytes() != src.read_bytes():
        shutil.copy2(src, dest)
        logger.info("synced anonymizer script → %s", dest)
    return dest


class AnonymizerSession:
    """Context manager owning temp storage + anonymizer workers."""

    def __init__(self, script_path: Path | None = None) -> None:
        self.script_path = script_path
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.anon: AnonymizerController | None = None

    def __enter__(self) -> Self:
        self._tmp = tempfile.TemporaryDirectory(prefix="pseudo_phi_anon_")
        self.anon = make_anonymizer(Path(self._tmp.name), self.script_path)
        return self

    def __exit__(self, *exc: object) -> None:
        if self.anon is not None:
            with contextlib.suppress(Exception):
                self.anon.stop()
        if self._tmp is not None:
            self._tmp.cleanup()

    def apply(self, ds: Dataset) -> Dataset:
        assert self.anon is not None
        return anonymize_dataset(ds, self.anon)
