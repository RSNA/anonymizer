"""Workspace routing and shared entity colors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from anonymizer.controller.ai.embedded_phi.ner.phi_entity import SCORED_LABELS
from anonymizer.view.reports import open_workspace
from anonymizer.view.reports.entity_colors import ENTITY_COLORS_HEX, entity_color_bgr, entity_color_hex


def test_entity_colors_cover_every_scored_label() -> None:
    assert set(ENTITY_COLORS_HEX) == set(SCORED_LABELS)
    assert len(set(ENTITY_COLORS_HEX.values())) == len(SCORED_LABELS)
    assert entity_color_hex("name") == ENTITY_COLORS_HEX["NAME"]
    b, g, r = entity_color_bgr("NAME")
    assert f"#{r:02x}{g:02x}{b:02x}" == ENTITY_COLORS_HEX["NAME"]


def test_open_series_workspace_routes_by_kind(tmp_path: Path) -> None:
    from anonymizer.view.reports import report_text_review

    with (
        patch.object(open_workspace, "show_series_view", return_value="series") as series,
        patch.object(report_text_review, "show_report_text_review", return_value="report") as report,
        patch.object(open_workspace, "classify_series") as classify,
    ):
        from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind

        kwargs = {"controller": object(), "series_path": tmp_path}
        classify.side_effect = [
            SeriesKind.IMAGING,
            SeriesKind.OTHER_PIXEL,
            SeriesKind.NATIVE_SR,
            SeriesKind.NATIVE_PDF,
            SeriesKind.PIXEL_TEXT_REPORT,
        ]
        assert open_workspace.open_series_workspace(None, modality="CT", **kwargs) == "series"
        assert open_workspace.open_series_workspace(None, modality="SC", **kwargs) == "series"
        assert open_workspace.open_series_workspace(None, modality="SR", **kwargs) == "report"
        assert open_workspace.open_series_workspace(None, modality="DOC", **kwargs) == "report"
        assert open_workspace.open_series_workspace(None, modality="SC", **kwargs) == "report"
    assert series.call_count == 2
    assert [c.kwargs["document_kind"] for c in report.call_args_list] == ["sr", "pdf", "pixel_report"]
