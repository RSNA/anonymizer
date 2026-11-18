"""Project Settings script status line: new vs edit project."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from anonymizer.controller.script.option_explanations import options_status_line
from anonymizer.controller.script.paths import packaged_default_script_path
from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.view.settings.settings_dialog import SettingsDialog


def _dialog(*, new_model: bool, script_path: Path, options: frozenset[DeidMethodCode]) -> MagicMock:
    dlg = MagicMock(spec=SettingsDialog)
    dlg.new_model = new_model
    dlg.model = MagicMock()
    dlg.model.anonymizer_script_path = script_path
    dlg.model.confidentiality_options = options
    dlg._uses_packaged_default_script = lambda path: SettingsDialog._uses_packaged_default_script(dlg, path)
    return dlg


def test_new_project_with_packaged_default_shows_selected_options_not_custom() -> None:
    """Create flow: default script + Clean options must list options (edit-mode labels)."""
    options = frozenset(
        {
            DeidMethodCode.BASIC,
            DeidMethodCode.CLEAN_PIXEL_DATA,
            DeidMethodCode.CLEAN_STRUCTURED_CONTENT,
            DeidMethodCode.CLEAN_DESCRIPTORS,
        }
    )
    dlg = _dialog(new_model=True, script_path=packaged_default_script_path(), options=options)

    text = SettingsDialog._script_status_text(dlg)

    expected = options_status_line(options)
    assert "Custom" not in text
    assert expected in text
    assert "Clean Pixels" in text
    assert "default-anonymizer.script" in text


def test_edit_project_still_uses_script_status_line_for_on_disk_script(
    tmp_path: Path, monkeypatch
) -> None:
    """Existing project keeps Custom / options via script_status_line on the installed file."""
    script = tmp_path / "site-anonymizer.script"
    script.write_text("<rules></rules>", encoding="utf-8")
    options = frozenset({DeidMethodCode.BASIC, DeidMethodCode.CLEAN_PIXEL_DATA})
    dlg = _dialog(new_model=False, script_path=script, options=options)

    monkeypatch.setattr(
        "anonymizer.view.settings.settings_dialog.load_script_rules",
        lambda _path: MagicMock(name="doc"),
    )
    monkeypatch.setattr(
        "anonymizer.view.settings.settings_dialog.script_status_line",
        lambda _doc, _opts: "Custom",
    )

    text = SettingsDialog._script_status_text(dlg)

    assert text.endswith("· Custom")
    assert "site-anonymizer.script" in text
