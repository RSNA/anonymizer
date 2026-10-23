"""Open AnonymizerModel for tests and always dispose the SQLAlchemy engine."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from anonymizer.controller.script.document import load_script_rules, tag_keep_from_document
from anonymizer.model.anonymizer import AnonymizerModel
from tests.controller.dicom.support.test_nodes import TEST_SITEID, TEST_UIDROOT
from tests.paths import DEFAULT_ANONYMIZER_SCRIPT


def load_model_script(model: AnonymizerModel, script_path: Path) -> None:
    """Fill the keep-table from a script file (mirrors AnonymizerController.reload_script)."""
    path = Path(script_path)
    model.replace_tag_keep(
        tag_keep_from_document(load_script_rules(path)),
        script_path=path,
    )


@contextmanager
def opened_anonymizer_model(
    db_url: str,
    *,
    site_id: str = TEST_SITEID,
    uid_root: str = TEST_UIDROOT,
    script_path: Path | None = None,
) -> Iterator[AnonymizerModel]:
    """Yield an AnonymizerModel; always call ``close()`` so sqlite pools do not leak."""
    path = script_path or DEFAULT_ANONYMIZER_SCRIPT
    model = AnonymizerModel(
        site_id=site_id,
        uid_root=uid_root,
        script_path=path,
        db_url=db_url,
    )
    load_model_script(model, path)
    try:
        yield model
    finally:
        model.close()
