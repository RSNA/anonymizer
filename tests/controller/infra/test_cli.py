"""CLI entry point tests."""

from __future__ import annotations

from click.testing import CliRunner

from anonymizer.anonymizer import main
from anonymizer.utils.version import get_version


def test_main_help_shows_version_title() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert get_version() in result.output
    assert "RSNA DICOM Anonymizer" in result.output


def test_main_version_option() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert get_version() in result.output
