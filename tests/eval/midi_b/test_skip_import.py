"""--skip-import / --run-dir reuse guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.midi_b.cli import _resolve_run_dir, _run_split_body


class _Args:
    def __init__(self, **kwargs):
        self.patients = None
        self.slug = None
        self.synthetic_root = None
        self.answer_key = None
        self.harness_root = None
        self.run_dir = None
        self.skip_import = False
        self.skip_ai_batch = True
        self.multiprocessing = False
        self.no_reports = True
        self.__dict__.update(kwargs)


def test_skip_import_requires_run_dir() -> None:
    with pytest.raises(ValueError, match="requires --run-dir"):
        _run_split_body(_Args(skip_import=True), split="validation")


def test_resolve_run_dir_reuses_path(tmp_path: Path) -> None:
    run = tmp_path / "existing"
    run.mkdir()
    got = _resolve_run_dir(_Args(run_dir=str(run)), split="validation")
    assert got == run


def test_skip_import_requires_project_artifacts(tmp_path: Path) -> None:
    run = tmp_path / "empty_run"
    run.mkdir()
    (run / "mappings").mkdir()
    with pytest.raises(FileNotFoundError, match="ProjectModel"):
        _run_split_body(_Args(run_dir=str(run), skip_import=True), split="validation")
