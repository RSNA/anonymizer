"""Prepare a run-local ProjectModel.json from the pregenerated asset (JSON only)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from eval.midi_b.paths import ASSETS_DIR

_STORAGE_PLACEHOLDER = "__MIDI_B_RUN_STORAGE__"


def prepare_project_dir(run_dir: Path) -> tuple[Path, Path]:
    """
    Copy assets into run_dir/project and point storage_dir at that folder.

    Args:
        run_dir: Harness run directory.

    Returns:
        (project_model_json_path, project_storage_dir).
    """
    project_dir = Path(run_dir) / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    src_model = ASSETS_DIR / "ProjectModel.json"
    src_batch = ASSETS_DIR / "AiBatchConfig.json"
    dest_model = project_dir / "ProjectModel.json"
    data = json.loads(src_model.read_text(encoding="utf-8"))
    storage = str(project_dir.resolve())
    data["storage_dir"] = storage
    # Replace placeholder if present as string fragment.
    raw = json.dumps(data)
    raw = raw.replace(_STORAGE_PLACEHOLDER, storage)
    dest_model.write_text(json.dumps(json.loads(raw), indent=2) + "\n", encoding="utf-8")
    if src_batch.is_file():
        shutil.copy2(src_batch, run_dir / "AiBatchConfig.json")
    return dest_model, project_dir
