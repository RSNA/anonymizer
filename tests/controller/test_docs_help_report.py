"""End-of-run capture inventory (one row per shot, languages per OS column)."""

from __future__ import annotations

from pathlib import Path

from docs_help.capture import format_capture_report
from docs_help.manifest import load_manifest


def _write_shot_png(_tmp_path: Path, shot_id: str, language: str, capture_os: str) -> None:
    manifest = load_manifest()
    shot = manifest.shot_by_id(shot_id)
    assert shot is not None
    dest = manifest.output_path(language, shot, capture_os=capture_os)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"png")


def _data_row(report: str, shot_id: str) -> str:
    rows = [line for line in report.splitlines() if line[2:].startswith(shot_id)]
    assert len(rows) == 1, report
    return rows[0]


def test_format_capture_report_one_row_with_os_language_columns(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("docs_help.manifest.REPO_ROOT", tmp_path)
    for lang in ("en_US", "de", "es", "fr"):
        _write_shot_png(tmp_path, "Welcome", lang, "macos")
    _write_shot_png(tmp_path, "Welcome", "en_US", "windows")
    _write_shot_png(tmp_path, "Process_Harmonize_Description", "fr", "macos")

    report = format_capture_report(
        [],
        shot_order=("Welcome", "Process_Harmonize_Description"),
        languages=("en_US", "de", "es", "fr"),
    )
    header = next(line for line in report.splitlines() if line.startswith("Shot"))
    assert "macos" in header
    assert "windows" in header
    assert "missing:" not in report

    welcome = _data_row(report, "Welcome")
    assert welcome.startswith("* Welcome")
    macos_col = welcome[35:53].strip()
    windows_col = welcome[54:].strip()
    assert macos_col == "en_US de es fr"
    assert windows_col == "en_US"

    desc = _data_row(report, "Process_Harmonize_Description")
    assert desc.startswith("* ")
    assert "fr" in desc
    assert desc.rstrip().endswith("-")
    assert "Summary: 2 shot(s), 0 complete, 2 incomplete" in report


def test_format_capture_report_complete_when_all_os_have_all_languages(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("docs_help.manifest.REPO_ROOT", tmp_path)
    for lang in ("en_US", "de"):
        _write_shot_png(tmp_path, "Welcome", lang, "macos")
        _write_shot_png(tmp_path, "Welcome", lang, "windows")
    report = format_capture_report(
        [],
        shot_order=("Welcome",),
        languages=("en_US", "de"),
    )
    welcome = _data_row(report, "Welcome")
    assert welcome.startswith("  Welcome")
    assert welcome.count("en_US de") == 2
    assert "* " not in report


def test_format_capture_report_sorts_shots_in_catalog_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("docs_help.manifest.REPO_ROOT", tmp_path)
    _write_shot_png(tmp_path, "Process_Harmonize_Description", "de", "macos")
    _write_shot_png(tmp_path, "Welcome", "de", "macos")
    report = format_capture_report(
        [],
        shot_order=("Welcome", "Process_Harmonize_Description"),
        languages=("de",),
    )
    assert report.index("Welcome") < report.index("Process_Harmonize_Description")
    assert "missing:" not in report
