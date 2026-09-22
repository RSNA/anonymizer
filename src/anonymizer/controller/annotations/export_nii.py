"""NIfTI ML export bundle from annotation store."""

from __future__ import annotations

import json
from pathlib import Path

from anonymizer.controller.annotations.store import (
    LABEL_MAP_FILENAME,
    LABELS_FILENAME,
    AnnotateSession,
    label_map_path,
    labels_path,
    save_annotate_session,
)


def export_ml_bundle(
    cache_dir: Path,
    dest_dir: Path,
    *,
    session: AnnotateSession | None = None,
) -> Path:
    """Copy volume + labels + label_map into ``dest_dir`` for ML training."""
    cache_dir = Path(cache_dir)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if session is not None and session.dirty:
        save_annotate_session(session)

    volume_src = cache_dir / "volume.nii.gz"
    if volume_src.is_file():
        (dest_dir / "volume.nii.gz").write_bytes(volume_src.read_bytes())

    labels_src = labels_path(cache_dir)
    if labels_src.is_file():
        (dest_dir / LABELS_FILENAME).write_bytes(labels_src.read_bytes())
    map_src = label_map_path(cache_dir)
    if map_src.is_file():
        (dest_dir / LABEL_MAP_FILENAME).write_text(
            map_src.read_text(encoding="utf-8"), encoding="utf-8"
        )

    meta = {
        "background": 0,
        "convention": "multi-class uint16 labels.nii.gz matching volume.nii.gz grid",
        "source_cache": str(cache_dir),
    }
    (dest_dir / "export_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return dest_dir
