"""JSON-only project prep for MIDI-B eval runs."""

from __future__ import annotations

import json
from pathlib import Path

from eval.midi_b.project_prep import prepare_project_dir


def test_prepare_project_dir_rewrites_storage(tmp_path: Path) -> None:
    model_path, project_dir = prepare_project_dir(tmp_path)
    assert model_path.is_file()
    assert project_dir == tmp_path / "project"
    data = json.loads(model_path.read_text(encoding="utf-8"))
    assert Path(data["storage_dir"]) == project_dir.resolve()
    assert 990054 in data["confidentiality_options"]
    assert (tmp_path / "AiBatchConfig.json").is_file()
