"""Open AnonymizerModel for tests and always dispose the SQLAlchemy engine."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from anonymizer.model.anonymizer import AnonymizerModel
from tests.controller.dicom.support.test_nodes import TEST_SITEID, TEST_UIDROOT
from tests.paths import DEFAULT_ANONYMIZER_SCRIPT


@contextmanager
def opened_anonymizer_model(
    db_url: str,
    *,
    site_id: str = TEST_SITEID,
    uid_root: str = TEST_UIDROOT,
    script_path: Path | None = None,
) -> Iterator[AnonymizerModel]:
    """Yield an AnonymizerModel; always call ``close()`` so sqlite pools do not leak."""
    model = AnonymizerModel(
        site_id=site_id,
        uid_root=uid_root,
        script_path=script_path or DEFAULT_ANONYMIZER_SCRIPT,
        db_url=db_url,
    )
    try:
        yield model
    finally:
        model.close()
